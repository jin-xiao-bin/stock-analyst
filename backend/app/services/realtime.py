"""实时行情：Tushare realtime_quote(中转) → 东财 push2 兜底 → 本地日线降级"""
import logging

import httpx

from ..config import settings

log = logging.getLogger(__name__)

EM_PUSH2 = "https://push2.eastmoney.com/api/qt/stock/get"
EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://quote.eastmoney.com/",
}


def _tushare_realtime(ts_code: str) -> dict | None:
    try:
        from .tushare_client import client
        df = client.query("realtime_quote", retries=1, ts_code=ts_code)
        if df is None or df.empty:
            return None
        r = df.iloc[0].to_dict()

        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        return {
            "name": r.get("name"), "price": _f(r.get("price")),
            "open": _f(r.get("open")), "high": _f(r.get("high")), "low": _f(r.get("low")),
            "pre_close": _f(r.get("pre_close")),
            "pct_chg": round((r["price"] / r["pre_close"] - 1) * 100, 2)
            if _f(r.get("price")) and _f(r.get("pre_close")) else None,
            "volume": _f(r.get("volume")),      # 手
            "amount": _f(r.get("amount")),      # 万元
            "bid": _f(r.get("bid")), "ask": _f(r.get("ask")),
            "time": f"{str(r.get('date', ''))[:4]}-{str(r.get('date', ''))[4:6]}-{str(r.get('date', ''))[6:8]} {r.get('time', '')}",
            "source": "tushare",
        }
    except Exception as e:  # noqa: BLE001
        log.info("tushare realtime_quote 失败(降级东财): %s", e)
        return None


def _em_secid(ts_code: str) -> str:
    symbol, _, suffix = ts_code.partition(".")
    market = "1" if suffix.upper() == "SH" else "0"
    return f"{market}.{symbol}"


def _eastmoney_realtime(ts_code: str) -> dict | None:
    try:
        r = httpx.get(
            EM_PUSH2,
            params={
                "secid": _em_secid(ts_code), "fltt": 2, "invt": 2,
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170",
            },
            timeout=8, headers=EM_HEADERS,
        )
        r.raise_for_status()
        d = (r.json().get("data") or {})
        if not d or d.get("f43") in ("-", None):
            return None

        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        return {
            "name": d.get("f58"), "price": _f(d.get("f43")),
            "open": _f(d.get("f46")), "high": _f(d.get("f44")), "low": _f(d.get("f45")),
            "pre_close": _f(d.get("f60")), "pct_chg": _f(d.get("f170")),
            "volume": _f(d.get("f47")),    # 手
            "amount": round(_f(d.get("f48")) / 10000, 2) if _f(d.get("f48")) else None,  # 元→万元
            "bid": None, "ask": None,
            "time": None, "source": "eastmoney",
        }
    except Exception as e:  # noqa: BLE001
        log.warning("东财实时接口失败: %s", e)
        return None


def get_realtime(ts_code: str) -> dict | None:
    """三级降级：Tushare realtime_quote → 东财 push2 → None(前端显示本地收盘)"""
    return _tushare_realtime(ts_code) or _eastmoney_realtime(ts_code)
