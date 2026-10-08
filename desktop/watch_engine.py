"""盯盘引擎：自选股+agent池轮询实时价 → 警报规则 → 事件回调"""
import datetime as dt
import logging
import time

log = logging.getLogger(__name__)


class WatchEngine:
    """交易时段轮询实时价，驱动警报规则。回调由 UI 层注入（线程安全：Qt 信号转发）。"""

    def __init__(self, api, on_alert, interval: float = 4.0):
        self.api = api
        self.interval = interval
        self.on_alert = on_alert          # on_alert(ts_code, title, text, important)
        self._stop = threading.Event() if (threading := __import__("threading")) else None
        self.price_hist: dict[str, list[tuple[float, float]]] = {}  # code -> [(ts, price)]
        self._cooldown: dict[str, float] = {}       # rule_key -> last fire ts
        self._thread = None

    # ---- 交易时段判断 ----
    @staticmethod
    def is_trading_time(now: time.struct_time | None = None) -> bool:
        now = now or time.localtime()
        if now.tm_wday >= 5:
            return False
        hm = now.tm_hour * 60 + now.tm_min
        return (9 * 60 + 25) <= hm <= (11 * 60 + 30) or (13 * 60) <= hm <= (15 * 60 + 5)

    def start(self):
        import threading
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="watch")
        self._thread.start()

    def stop(self):
        if self._stop:
            self._stop.set()

    def _loop(self):
        while not self._stop.is_set():
            try:
                if self.is_trading_time():
                    self._tick()
                else:
                    self._cooldown.clear()
                    time.sleep(30)
                    continue
            except Exception as e:  # noqa: BLE001
                log.warning("盯盘轮询异常: %s", e)
            self._stop.wait(self.interval)

    def _codes(self) -> list[str]:
        codes = [w["ts_code"] for w in self.api.watchlist()]
        # agent 池并入
        try:
            for cfg in self.api.agent_status():
                for c in cfg.get("stocks") or []:
                    if c not in codes:
                        codes.append(c)
        except Exception:  # noqa: BLE001
            pass
        return codes

    def _tick(self):
        rules = [r for r in self.api.rules() if r.get("enabled")]
        rule_by_code: dict[str, list] = {}
        for r in rules:
            rule_by_code.setdefault(r["ts_code"], []).append(r)

        for code in self._codes():
            try:
                rt = self.api.realtime(code)
                price = rt.get("price")
                if price is None:
                    continue
                now = time.time()
                hist = self.price_hist.setdefault(code, [])
                hist.append((now, price))
                # 只留 10 分钟窗口
                while hist and now - hist[0][0] > 600:
                    hist.pop(0)

                pre = rt.get("pre_close")
                pct = (price / pre - 1) * 100 if pre else 0

                for rule in rule_by_code.get(code, []):
                    self._check_rule(code, rule, price, pct, now)
            except Exception as e:  # noqa: BLE001
                log.warning("盯盘 %s 失败: %s", code, e)

    def _fire(self, key: str, ts_code: str, title: str, text: str, important=False):
        now = time.time()
        if now - self._cooldown.get(key, 0) < 1800:  # 30分钟冷却
            return
        self._cooldown[key] = now
        self.on_alert(ts_code, title, text, important)

    def _check_rule(self, code: str, rule: dict, price: float, pct: float, now: float):
        params = rule.get("params") or {}
        rid = f"{rule['id']}"
        if rule["rule_type"] == "threshold":
            th = abs(float(params.get("pct", 3)))
            if abs(pct) >= th:
                self._fire(f"th:{rid}:{th}", code,
                           f"{code} 涨跌幅警报 {pct:+.2f}%",
                           f"当前 {price}，当日涨跌 {pct:+.2f}% 超过阈值 ±{th}%",
                           important=abs(pct) >= th + 2)
        elif rule["rule_type"] == "cross":
            direction = params.get("direction", "below")
            line = float(params.get("price", 0))
            if direction == "below" and price <= line:
                self._fire(f"cross:{rid}", code, f"{code} 跌破 {line}",
                           f"现价 {price} 已跌破价格线 {line}", important=True)
            elif direction == "above" and price >= line:
                self._fire(f"cross:{rid}", code, f"{code} 突破 {line}",
                           f"现价 {price} 已突破价格线 {line}", important=True)
        elif rule["rule_type"] == "spike":
            window = float(params.get("window_min", 5))
            sp = float(params.get("pct", 2))
            hist = self.price_hist.get(code, [])
            recent = [p for ts, p in hist if now - ts <= window * 60]
            if len(recent) >= 2:
                base = recent[0]
                move = (price / base - 1) * 100 if base else 0
                if abs(move) >= sp:
                    self._fire(f"spike:{rid}:{window}", code,
                               f"{code} 快速异动 {move:+.2f}%",
                               f"{window:.0f} 分钟内变动 {move:+.2f}%（{base} → {price}）",
                               important=abs(move) >= sp * 1.5)
