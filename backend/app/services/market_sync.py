"""行情同步：股票列表 / 日线(懒加载+增量) / 复权因子 / 财务指标"""
import datetime as dt
import logging

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.orm import Session

from ..models import AdjFactor, DailyBasic, DailyPrice, FinancialSnapshot, StockBasic
from .tushare_client import client

log = logging.getLogger(__name__)


def _upsert_df(db: Session, model, df: pd.DataFrame, keys: list[str]):
    """按主键批量 upsert DataFrame"""
    if df is None or df.empty:
        return 0
    rows = df.to_dict(orient="records")
    for chunk_start in range(0, len(rows), 500):
        chunk = rows[chunk_start:chunk_start + 500]
        stmt = mysql_insert(model).values(chunk)
        updates = {c: stmt.inserted[c] for c in chunk[0] if c not in keys}
        stmt = stmt.on_duplicate_key_update(**updates)
        db.execute(stmt)
    return len(rows)


def sync_stock_basic(db: Session) -> int:
    df = client.query("stock_basic", exchange="", list_status="L",
                      fields="ts_code,symbol,name,area,industry,market,list_date")
    if df.empty:
        return 0
    df["list_date"] = pd.to_datetime(df["list_date"]).dt.date
    return _upsert_df(db, StockBasic, df, ["ts_code"])


def _sync_adj_factor(db: Session, ts_code: str, start: str | None) -> int:
    kwargs = {"ts_code": ts_code, "fields": "ts_code,trade_date,adj_factor"}
    if start:
        kwargs["start_date"] = start
    df = client.query("adj_factor", **kwargs)
    if df.empty:
        return 0
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return _upsert_df(db, AdjFactor, df, ["ts_code", "trade_date"])


def _sync_daily_basic(db: Session, ts_code: str, start: str | None) -> int:
    """每日估值指标（PE/PB/换手率/量比/市值）"""
    kwargs = {"ts_code": ts_code,
              "fields": "ts_code,trade_date,pe,pe_ttm,pb,turnover_rate,volume_ratio,total_mv,circ_mv"}
    if start:
        kwargs["start_date"] = start
    try:
        df = client.query("daily_basic", retries=2, **kwargs)
    except Exception as e:  # noqa: BLE001 中转瞬时失败不阻塞行情同步
        log.warning("daily_basic 拉取失败(跳过): %s", e)
        return 0
    if df.empty:
        return 0
    df = df.rename(columns={"turnover_rate": "turn_rate"})
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    for c in ("pe", "pe_ttm", "pb", "turn_rate", "volume_ratio", "total_mv", "circ_mv"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.astype(object).where(pd.notna(df), None)
    return _upsert_df(db, DailyBasic, df, ["ts_code", "trade_date"])


def sync_daily(db: Session, ts_code: str, incremental: bool = False) -> dict:
    """拉取日线（不复权）。incremental=True 时仅从本地最新日期之后拉取。
    首次调用为全量（上市至今），并同步全量复权因子。"""
    start = None
    if incremental:
        last = db.execute(
            select(func.max(DailyPrice.trade_date)).where(DailyPrice.ts_code == ts_code)
        ).scalar()
        if last is None:
            incremental = False  # 本地无数据，转全量
        else:
            start = (last + dt.timedelta(days=1)).strftime("%Y%m%d")
            if start > dt.date.today().strftime("%Y%m%d"):
                return {"ts_code": ts_code, "rows": 0, "mode": "up-to-date"}

    kwargs = {"ts_code": ts_code,
              "fields": "ts_code,trade_date,open,high,low,close,pre_close,vol,amount,pct_chg"}
    if start:
        kwargs["start_date"] = start
    df = client.query("daily", **kwargs)
    n = 0
    if not df.empty:
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        for c in ("open", "high", "low", "close", "pre_close", "vol", "amount", "pct_chg"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        n = _upsert_df(db, DailyPrice, df, ["ts_code", "trade_date"])

    # 复权因子与估值指标与日线同范围维护
    _sync_adj_factor(db, ts_code, start)
    _sync_daily_basic(db, ts_code, start)
    db.commit()
    return {"ts_code": ts_code, "rows": n, "mode": "incremental" if start else "full"}


def sync_finance(db: Session, ts_code: str) -> int:
    df = client.query("fina_indicator", ts_code=ts_code, periods=8,
                      fields="ts_code,end_date,roe,eps,grossprofit_margin,netprofit_margin,"
                             "debt_to_assets,revenue_growth,netprofit_growth")
    if df.empty:
        return 0
    df = df.rename(columns={
        "grossprofit_margin": "gross_margin",
        "netprofit_margin": "net_margin",
        "debt_to_assets": "debt_ratio",
        "revenue_growth": "revenue_yoy",
        "netprofit_growth": "net_profit_yoy",
    })
    df["end_date"] = pd.to_datetime(df["end_date"]).dt.date
    # fina_indicator 每期可能返回多行(不同ann_type)；按报告期去重取首行，NaN 置 None（MySQL 不接受 nan）
    df = df.drop_duplicates(subset=["ts_code", "end_date"], keep="first")
    df = df.astype(object).where(pd.notna(df), None)
    return _upsert_df(db, FinancialSnapshot, df, ["ts_code", "end_date"])


def is_local_stale(db: Session, ts_code: str) -> bool:
    """本地日线是否落后：交易日 17:10 后本地最新 < 今天；非交易日/盘中则容错4个自然日"""
    import datetime as _dt
    latest = db.scalar(
        select(func.max(DailyPrice.trade_date)).where(DailyPrice.ts_code == ts_code))
    if latest is None:
        return False  # 无数据走懒加载逻辑
    now = _dt.datetime.now()
    today = now.date()
    if now.weekday() < 5 and now.hour >= 17:
        return latest < today
    return (today - latest).days > 4  # 节假日容错


def sync_all_tracked(db: Session) -> dict:
    """每日定时任务：增量更新所有本地已有行情的股票"""
    codes = db.execute(select(DailyPrice.ts_code).distinct()).scalars().all()
    total = 0
    failed = []
    for code in codes:
        try:
            r = sync_daily(db, code, incremental=True)
            total += r["rows"]
        except Exception as e:  # noqa: BLE001
            log.error("增量同步 %s 失败: %s", code, e)
            failed.append(code)
    log.info("每日增量同步完成: %d 只股票, %d 行, 失败 %d", len(codes), total, len(failed))
    return {"stocks": len(codes), "rows": total, "failed": failed}
