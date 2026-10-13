"""P0-3 事件日历同步：财报预约披露 / 限售解禁 / 除权除息
Tushare 失败时静默降级（空表 → R7 自动跳过）"""
import datetime as dt
import logging

import httpx
import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from ..models import EventCalendar
from .tushare_client import client

log = logging.getLogger(__name__)

EM_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://data.eastmoney.com/"}


def _upsert_events(db, rows: list[dict]):
    if not rows:
        return 0
    stmt = mysql_insert(EventCalendar).values(rows)
    stmt = stmt.on_duplicate_key_update(detail=stmt.inserted.detail)
    db.execute(stmt)
    return len(rows)


def sync_events(db, codes: list[str] | None = None):
    """同步事件日历。codes 为空时同步 agent 股票池 + 持仓股"""
    today = dt.date.today()
    rows = []
    for ts_code in codes or []:
        # 财报预约披露（Tushare disclosure_date）
        try:
            df = client.query("disclosure_date", retries=1, ts_code=ts_code,
                              period=f"{today.year}{['0331','0630','0930','1231'][min(3, (today.month - 1) // 3)]}",
                              fields="ts_code,name,end_date,actual_date")
            for _, r in df.iterrows():
                d = r.get("actual_date") or r.get("end_date")
                if d:
                    d = pd.to_datetime(str(d)).date()
                    if today <= d <= today + dt.timedelta(days=90):
                        rows.append({"ts_code": ts_code, "event_type": "earnings",
                                     "event_date": d,
                                     "detail": f"财报披露 {r.get('name', '')}".strip(),
                                     "source": "tushare"})
        except Exception as e:  # noqa: BLE001
            log.debug("disclosure_date %s 失败: %s", ts_code, e)

        # 限售解禁（Tushare share_float）
        try:
            df = client.query("share_float", retries=1, ts_code=ts_code,
                              start_date=today.strftime("%Y%m%d"),
                              end_date=(today + dt.timedelta(days=90)).strftime("%Y%m%d"),
                              fields="ts_code,ann_date,float_date,float_share,float_ratio")
            for _, r in df.iterrows():
                if r.get("float_date"):
                    d = pd.to_datetime(str(r["float_date"])).date()
                    ratio = float(r.get("float_ratio") or 0)
                    rows.append({"ts_code": ts_code, "event_type": "unlock",
                                 "event_date": d,
                                 "detail": f"解禁 {ratio:.1f}% 流通股" if ratio else "限售解禁",
                                 "source": "tushare"})
        except Exception as e:  # noqa: BLE001
            log.debug("share_float %s 失败: %s", ts_code, e)

        # 除权除息（Tushare dividend — 未来90天）
        try:
            df = client.query("dividend", retries=1, ts_code=ts_code,
                              fields="ts_code,end_date,ann_date,div_proc,stk_div,cash_div,base_share")
            for _, r in df.iterrows():
                if r.get("ann_date") and r.get("div_proc") == "实施方案":
                    d = pd.to_datetime(str(r["ann_date"])).date()
                    if today <= d <= today + dt.timedelta(days=90):
                        cd = float(r.get("cash_div") or 0)
                        sd = float(r.get("stk_div") or 0)
                        detail = "除权除息"
                        if cd:
                            detail += f" 每10股派{cd}元"
                        if sd:
                            detail += f" 每10股送{sd}股"
                        rows.append({"ts_code": ts_code, "event_type": "ex_dividend",
                                     "event_date": d, "detail": detail.strip(),
                                     "source": "tushare"})
        except Exception as e:  # noqa: BLE001
            log.debug("dividend %s 失败: %s", ts_code, e)

    n = _upsert_events(db, rows)
    db.commit()
    return n


def upcoming_events(db, ts_code: str, days: int = 5) -> list[dict]:
    """未来 N 日事件（供 agent 决策注入）"""
    today = dt.date.today()
    rows = db.scalars(select(EventCalendar).where(
        EventCalendar.ts_code == ts_code,
        EventCalendar.event_date >= today,
        EventCalendar.event_date <= today + dt.timedelta(days=days))
        .order_by(EventCalendar.event_date)).all()
    return [{"date": r.event_date.isoformat(), "type": r.event_type,
             "detail": r.detail or ""} for r in rows]
