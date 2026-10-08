"""行情查询 API"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AdjFactor, DailyPrice, FinancialSnapshot, StockBasic
from ..services.market_sync import sync_daily, sync_finance

router = APIRouter(prefix="/api", tags=["market"])


class StockInfo(BaseModel):
    ts_code: str
    symbol: str
    name: str
    area: str | None = None
    industry: str | None = None
    market: str | None = None
    list_date: dt.date | None = None


class Bar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    pre_close: float | None = None
    volume: float | None = None   # 手
    amount: float | None = None   # 千元
    pct_chg: float | None = None


def _ensure_stock_list(db: Session):
    if db.scalar(select(StockBasic.ts_code).limit(1)) is None:
        from ..services.market_sync import sync_stock_basic
        sync_stock_basic(db)
        db.commit()


@router.get("/stocks", response_model=list[StockInfo])
def search_stocks(q: str = Query("", max_length=32), limit: int = 20, db: Session = Depends(get_db)):
    _ensure_stock_list(db)
    stmt = select(StockBasic)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(StockBasic.name.like(like),
                              StockBasic.ts_code.like(like),
                              StockBasic.symbol.like(like)))
    stmt = stmt.order_by(StockBasic.ts_code).limit(limit)
    return db.scalars(stmt).all()


@router.get("/stocks/{ts_code}/daily", response_model=list[Bar])
def get_daily(
    ts_code: str,
    start: dt.date | None = None,
    end: dt.date | None = None,
    adjust: str = Query("qfq", pattern="^(qfq|hfq|none)$"),
    db: Session = Depends(get_db),
):
    """日线数据。本地无数据时自动从 Tushare 全量拉取（懒加载）。支持裸6位代码。"""
    from ..utils import resolve_ts_code
    ts_code = resolve_ts_code(db, ts_code) or ts_code

    def _query_rows():
        stmt2 = select(DailyPrice).where(DailyPrice.ts_code == ts_code)
        if start:
            stmt2 = stmt2.where(DailyPrice.trade_date >= start)
        if end:
            stmt2 = stmt2.where(DailyPrice.trade_date <= end)
        return db.scalars(stmt2.order_by(DailyPrice.trade_date)).all()

    rows = _query_rows()

    # 自愈补偿：定时同步错过（如服务重启）导致本地陈旧时，查询时内联增量补齐
    if rows:
        try:
            from ..services.market_sync import is_local_stale, sync_daily
            if is_local_stale(db, ts_code):
                sync_daily(db, ts_code, incremental=True)
                rows = _query_rows()
        except Exception:  # noqa: BLE001 补漏失败不阻塞查询
            db.rollback()

    if not rows:
        try:
            sync_daily(db, ts_code, incremental=True)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"Tushare 拉取失败: {e}") from e
        rows = _query_rows()
        if not rows:
            raise HTTPException(404, f"未找到 {ts_code} 的行情数据，请检查代码")

    if adjust != "none":
        factors = {
            r.trade_date: float(r.adj_factor)
            for r in db.scalars(
                select(AdjFactor).where(AdjFactor.ts_code == ts_code,
                                        AdjFactor.trade_date >= rows[0].trade_date)
            ).all()
        }
        if factors:
            # qfq: hfq价/最新因子(锚定当前价); hfq: 锚定最早因子
            base = max(factors.values()) if adjust == "qfq" else min(factors.values())
            for r in rows:
                f = factors.get(r.trade_date)
                if f is None:
                    continue
                ratio = f / base
                r.open = float(r.open) * ratio
                r.high = float(r.high) * ratio
                r.low = float(r.low) * ratio
                r.close = float(r.close) * ratio
                if r.pre_close is not None:
                    r.pre_close = float(r.pre_close) * ratio

    return [
        Bar(date=r.trade_date.isoformat(), open=float(r.open), high=float(r.high),
            low=float(r.low), close=float(r.close), pre_close=r.pre_close,
            volume=float(r.vol) if r.vol is not None else None,
            amount=float(r.amount) if r.amount is not None else None,
            pct_chg=float(r.pct_chg) if r.pct_chg is not None else None)
        for r in rows
    ]


@router.get("/stocks/{ts_code}/realtime")
def get_realtime_quote(ts_code: str, db: Session = Depends(get_db)):
    """实时报价（Tushare→东财降级）；支持裸6位代码"""
    from ..utils import resolve_ts_code
    ts_code = resolve_ts_code(db, ts_code) or ts_code
    from ..services.realtime import get_realtime
    return get_realtime(ts_code) or {"price": None, "source": "none"}


@router.get("/stocks/{ts_code}/finance")
def get_finance(ts_code: str, db: Session = Depends(get_db)):
    from ..utils import resolve_ts_code
    ts_code = resolve_ts_code(db, ts_code) or ts_code
    rows = db.scalars(
        select(FinancialSnapshot).where(FinancialSnapshot.ts_code == ts_code)
        .order_by(FinancialSnapshot.end_date.desc()).limit(8)
    ).all()
    if not rows:
        try:
            n = sync_finance(db, ts_code)
            db.commit()
        except Exception:  # noqa: BLE001 中转瞬时失败时回退本地缓存（哪怕旧数据）
            db.rollback()
        rows = db.scalars(
            select(FinancialSnapshot).where(FinancialSnapshot.ts_code == ts_code)
            .order_by(FinancialSnapshot.end_date.desc()).limit(8)
        ).all()
        if not rows:
            raise HTTPException(502, "财务数据拉取失败且本地无缓存（Tushare中转可能瞬时不可用，稍后重试）")
    # 最新估值（PE/PB/换手/市值），有则附带
    from ..models import DailyBasic
    val = db.scalar(select(DailyBasic).where(DailyBasic.ts_code == ts_code)
                    .order_by(DailyBasic.trade_date.desc()).limit(1))
    valuation = None
    if val:
        valuation = {"date": val.trade_date.isoformat(),
                     "pe": float(val.pe) if val.pe else None,
                     "pe_ttm": float(val.pe_ttm) if val.pe_ttm else None,
                     "pb": float(val.pb) if val.pb else None,
                     "turn_rate": float(val.turn_rate) if val.turn_rate else None,
                     "volume_ratio": float(val.volume_ratio) if val.volume_ratio else None,
                     "total_mv_wan": float(val.total_mv) if val.total_mv else None}
    return {
        "financial": [
            {"end_date": r.end_date.isoformat(), "roe": float(r.roe) if r.roe else None,
             "eps": float(r.eps) if r.eps else None,
             "gross_margin": float(r.gross_margin) if r.gross_margin else None,
             "net_margin": float(r.net_margin) if r.net_margin else None,
             "debt_ratio": float(r.debt_ratio) if r.debt_ratio else None,
             "revenue_yoy": float(r.revenue_yoy) if r.revenue_yoy else None,
             "net_profit_yoy": float(r.net_profit_yoy) if r.net_profit_yoy else None}
            for r in rows
        ],
        "valuation": valuation,
    }
