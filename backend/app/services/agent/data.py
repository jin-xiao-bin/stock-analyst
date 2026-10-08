"""数据聚合：实时价/K线/财务/新闻/历史决策/观察任务/参考策略信号"""
import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (AgentDecision, DailyPrice, FinancialSnapshot,
                       SimAccount, SimPosition, Strategy, WatchTask)
from .. import news_source
from ..realtime import get_realtime

log = logging.getLogger(__name__)


def strategy_signal(db: Session, strategy_id: int, ts_code: str) -> dict | None:
    """F9：沙箱跑参考策略，取其当前方向与最近信号"""
    try:
        s = db.get(Strategy, strategy_id)
        if s is None:
            return None
        from ..backtest_engine import load_bars
        from ..sandbox import run_in_sandbox
        bars = load_bars(db, ts_code)
        if not bars:
            return None

        class Probe:
            def __init__(self):
                self.position = 0
                self.signals: list[tuple[str, str]] = []  # (date, side)
                self._ctx = None

            def attach(self, ctx): self._ctx = ctx

            @property
            def position_qty(self): return self.position

            @property
            def cash(self): return 1_000_000.0

            def _cur(self):
                i = self._ctx._i  # noqa: SLF001
                return bars[i]["date"]

            def buy(self, ratio=1.0, reason=""):
                self.position = max(1, self.position)
                self.signals.append((self._cur(), f"buy({reason})"))

            def sell_all(self, reason=""):
                self.position = 0
                self.signals.append((self._cur(), f"sell_all({reason})"))

            def sell(self, qty, reason=""):
                self.position = max(0, self.position - qty)
                self.signals.append((self._cur(), f"sell({reason})"))

        probe = Probe()
        res = run_in_sandbox(s.code, bars, probe, s.params)
        if not res.get("ok"):
            return {"error": res.get("error")}
        last_date, last_sig = probe.signals[-1] if probe.signals else (None, None)
        bars_since = None
        if last_date:
            for i, b in enumerate(bars):
                if b["date"] >= last_date:
                    bars_since = len(bars) - 1 - i
                    break
        return {"strategy": f"#{s.id} {s.name}", "direction": "hold" if probe.position else "flat",
                "last_signal": last_sig, "last_signal_date": last_date,
                "bars_since_signal": bars_since, "total_signals": len(probe.signals)}
    except Exception as e:  # noqa: BLE001
        log.warning("策略信号探测失败 #%s %s: %s", strategy_id, ts_code, e)
        return {"error": str(e)[:120]}


def aggregate(db: Session, config, account: SimAccount, ts_code: str,
              deep: bool = False) -> dict:
    """决策输入聚合。deep=True 收盘全量；False 盘中轻量。"""
    data: dict = {"ts_code": ts_code, "as_of": dt.datetime.now().isoformat(timespec="seconds")}

    rt = get_realtime(ts_code)
    data["realtime"] = rt or {}

    bars = db.scalars(select(DailyPrice).where(DailyPrice.ts_code == ts_code)
                      .order_by(DailyPrice.trade_date.desc()).limit(250)).all()
    bars = list(reversed(bars))
    data["bars_text"] = "\n".join(
        f"{b.trade_date} C:{b.close} 涨跌%:{b.pct_chg} 量:{b.vol}" for b in bars[-60:]
    ) if bars else "（无本地日线）"
    data["latest_local_close"] = float(bars[-1].close) if bars else None

    pos = db.scalar(select(SimPosition).where(
        SimPosition.account_id == account.id, SimPosition.ts_code == ts_code))
    if pos:
        px = (rt or {}).get("price") or data["latest_local_close"] or pos.avg_cost
        data["position"] = {"qty": pos.qty, "avg_cost": pos.avg_cost,
                            "last_price": px,
                            "pnl_pct": round((px / pos.avg_cost - 1) * 100, 2)}
    else:
        data["position"] = None
    data["account"] = {"cash": float(account.cash),
                       "initial": float(account.initial_cash)}

    # 近10次该股决策
    decisions = db.scalars(select(AgentDecision).where(
        AgentDecision.account_id == account.id, AgentDecision.ts_code == ts_code,
        AgentDecision.action != "hold")
        .order_by(AgentDecision.id.desc()).limit(10)).all()
    data["recent_decisions"] = [
        {"time": d.run_time.isoformat(timespec="minutes") if d.run_time else None,
         "action": d.action, "status": d.status, "reason": (d.reason or "")[:80]}
        for d in reversed(decisions)]

    # thesis 兑现情况：该股已触发观察任务
    triggered = db.scalars(select(WatchTask).where(
        WatchTask.ts_code == ts_code, WatchTask.status == "triggered")
        .order_by(WatchTask.trigger_date.desc()).limit(3)).all()
    data["triggered_watch"] = [
        {"trigger_date": t.trigger_date.isoformat() if t.trigger_date else None,
         "detail": t.trigger_detail} for t in triggered]

    # 参考策略信号（F9）
    ref_ids = (config.reference_strategies or {}).get(ts_code) or []
    if ref_ids:
        data["strategy_signals"] = [strategy_signal(db, sid, ts_code) for sid in ref_ids]

    # 学习注入区（F10：每周日自动复盘生成）
    if config.prompt_notes:
        data["learning_notes"] = config.prompt_notes

    if deep:
        fins = db.scalars(select(FinancialSnapshot).where(
            FinancialSnapshot.ts_code == ts_code)
            .order_by(FinancialSnapshot.end_date.desc()).limit(8)).all()
        data["finance_text"] = "\n".join(
            f"报告期 {f.end_date} ROE:{f.roe} EPS:{f.eps} 毛利率:{f.gross_margin} "
            f"净利率:{f.net_margin} 营收同比%:{f.revenue_yoy} 净利同比%:{f.net_profit_yoy}"
            for f in fins) or "（无财务数据）"
        from ...models import DailyBasic
        val = db.scalar(select(DailyBasic).where(DailyBasic.ts_code == ts_code)
                        .order_by(DailyBasic.trade_date.desc()).limit(1))
        data["valuation_text"] = (
            f"PE(TTM){val.pe_ttm} PB{val.pb} 换手{val.turn_rate}% 总市值{round(float(val.total_mv or 0)/10000,1)}亿"
            if val else "（无估值数据）")
        news = news_source.get_news(ts_code, ts_code.split(".")[0], count=8)
        data["news_text"] = "\n".join(
            f"- [{n.get('date', '')[:10]}][{n.get('source')}] {n['title']}" for n in news
        ) or "（无近期新闻）"
    else:
        news = news_source.verify_search(f"{ts_code} 最新", count=3)
        data["news_headlines"] = [n["title"] for n in news][:3]

    return data
