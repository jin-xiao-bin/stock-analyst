"""回放交易 API（契约第 1 节）"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DailyPrice, ReplaySession, SimAccount, SimTrade, Strategy
from ..services.replay_engine import (
    account_snapshot, advance, ensure_daily, get_session, goto, place_order,
    run_session_strategy, summary, trade_dates,
)
from ..services import replay_engine as engine

router = APIRouter(prefix="/api/replay", tags=["replay"])


class CreateReq(BaseModel):
    ts_code: str
    start_date: dt.date
    initial_cash: float = 1_000_000
    name: str | None = None


class OrderReq(BaseModel):
    side: str = Field(pattern="^(buy|sell)$")
    qty: int


class GotoReq(BaseModel):
    date: dt.date


class NextReq(BaseModel):
    days: int = 1


def _detail(db: Session, s: ReplaySession) -> dict:
    account = db.get(SimAccount, s.account_id)
    snap = account_snapshot(db, s, account)
    bars = [
        {"date": r.trade_date.isoformat(), "open": float(r.open), "high": float(r.high),
         "low": float(r.low), "close": float(r.close),
         "pre_close": float(r.pre_close) if r.pre_close is not None else None,
         "volume": float(r.vol) if r.vol is not None else None,
         "amount": float(r.amount) if r.amount is not None else None,
         "pct_chg": float(r.pct_chg) if r.pct_chg is not None else None}
        for r in db.scalars(
            select(DailyPrice).where(DailyPrice.ts_code == s.ts_code)
            .order_by(DailyPrice.trade_date)).all()
    ]
    trades = [engine.trade_dict(t) for t in db.scalars(
        select(SimTrade).where(SimTrade.account_id == s.account_id)
        .order_by(SimTrade.trade_date, SimTrade.id)).all()
        if t.trade_date <= s.cursor_date]
    return {
        "session": {"id": s.id, "ts_code": s.ts_code,
                    "account_id": s.account_id,
                    "start_date": s.start_date.isoformat(),
                    "cursor_date": s.cursor_date.isoformat(),
                    "strategy_id": s.strategy_id,
                    "strategy_name": db.get(Strategy, s.strategy_id).name if s.strategy_id else None,
                    "params": s.params},
        "account": {k: snap[k] for k in
                    ("cash", "market_value", "total_value", "profit", "profit_pct")},
        "positions": snap["positions"],
        "bars": bars,
        "trades": trades,
    }


@router.post("")
def create_session(req: CreateReq, db: Session = Depends(get_db)):
    from ..utils import resolve_ts_code
    code = resolve_ts_code(db, req.ts_code)
    if code is None:
        raise HTTPException(400, f"股票代码 {req.ts_code} 不存在")
    req.ts_code = code
    ensure_daily(db, req.ts_code)
    dates = trade_dates(db, req.ts_code)
    start = next((d for d in dates if d >= req.start_date), None)
    if start is None:
        raise HTTPException(400, f"{req.start_date} 起无行情数据")

    account = SimAccount(name=req.name or f"回放 {req.ts_code}", mode="replay",
                         initial_cash=req.initial_cash, cash=req.initial_cash)
    db.add(account)
    db.flush()
    s = ReplaySession(account_id=account.id, ts_code=req.ts_code,
                      start_date=start, cursor_date=start, auto_play=False, speed_days=1)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "account_id": s.account_id, "ts_code": s.ts_code,
            "start_date": s.start_date.isoformat(), "cursor_date": s.cursor_date.isoformat(),
            "auto_play": s.auto_play}


@router.get("")
def list_sessions(db: Session = Depends(get_db)):
    out = []
    for s in db.scalars(select(ReplaySession).order_by(ReplaySession.id.desc())).all():
        account = db.get(SimAccount, s.account_id)
        snap = account_snapshot(db, s, account)
        initial = float(account.initial_cash) if account else 0
        total = snap["total_value"]
        out.append({"id": s.id, "ts_code": s.ts_code,
                    "account_id": s.account_id,
                    "account_name": account.name if account else f"#{s.account_id}",
                    "name": engine._stock_name(db, s.ts_code),
                    "start_date": s.start_date.isoformat(),
                    "cursor_date": s.cursor_date.isoformat(),
                    "total_value": total,
                    "profit_pct": round((total / initial - 1) * 100, 2) if initial else 0,
                    "strategy_id": s.strategy_id,
                    "updated_at": s.updated_at.isoformat()})
    return out


@router.get("/{session_id}")
def get_detail(session_id: int, db: Session = Depends(get_db)):
    return _detail(db, get_session(db, session_id))


@router.post("/{session_id}/next")
def next_days(session_id: int, req: NextReq, db: Session = Depends(get_db)):
    s = get_session(db, session_id)
    ensure_daily(db, s.ts_code)
    new_cursor = advance(db, s, max(1, req.days))
    if new_cursor is None:
        raise HTTPException(400, "已到最新交易日，无法继续推进")
    db.commit()
    run_session_strategy(db, s)
    return _detail(db, s)


@router.post("/{session_id}/goto")
def goto_date(session_id: int, req: GotoReq, db: Session = Depends(get_db)):
    s = get_session(db, session_id)
    ensure_daily(db, s.ts_code)
    goto(db, s, req.date)
    db.commit()
    run_session_strategy(db, s)
    return _detail(db, s)


class BindStrategyReq(BaseModel):
    strategy_id: int
    params: dict | None = None


@router.post("/{session_id}/strategy")
def bind_strategy(session_id: int, req: BindStrategyReq, db: Session = Depends(get_db)):
    """挂载策略：从当前 cursor 起对后续推进的交易日生效（不回补历史信号）"""
    s = get_session(db, session_id)
    strat = db.get(Strategy, req.strategy_id)
    if strat is None:
        raise HTTPException(404, f"策略 {req.strategy_id} 不存在")
    s.strategy_id = strat.id
    s.params = req.params
    s.strategy_last_date = s.cursor_date
    db.commit()
    return {"ok": True, "strategy_id": strat.id, "strategy_name": strat.name,
            "effective_from": s.cursor_date.isoformat()}


@router.delete("/{session_id}/strategy")
def unbind_strategy(session_id: int, db: Session = Depends(get_db)):
    s = get_session(db, session_id)
    s.strategy_id = None
    s.params = None
    s.strategy_last_date = None
    db.commit()
    return {"ok": True}


@router.post("/{session_id}/order")
def order(session_id: int, req: OrderReq, db: Session = Depends(get_db)):
    s = get_session(db, session_id)
    account = db.get(SimAccount, s.account_id)
    trade = place_order(db, s, account, req.side, req.qty)
    snap = account_snapshot(db, s, account)
    return {"trade": engine.trade_dict(trade),
            "account": {k: snap[k] for k in
                        ("cash", "market_value", "total_value", "profit", "profit_pct")},
            "positions": snap["positions"]}


@router.delete("/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = get_session(db, session_id)
    db.delete(s)
    db.commit()
    return {"ok": True, "deleted": session_id, "account_id_preserved": s.account_id}


@router.get("/{session_id}/summary")
def session_summary(session_id: int, db: Session = Depends(get_db)):
    s = get_session(db, session_id)
    account = db.get(SimAccount, s.account_id)
    return summary(db, s, account)
