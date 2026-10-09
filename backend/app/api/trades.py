"""账户 / 交易记录查询 API（契约第 2 节）"""
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (DailyPrice, ReplaySession, SimAccount, SimPosition,
                      SimTrade, StockBasic, StrategyBinding)
from ..services.replay_engine import trade_dict

router = APIRouter(prefix="/api", tags=["trades"])


@router.post("/accounts")
def create_account(body: dict, db: Session = Depends(get_db)):
    """新增模拟账户（name/mode/initial_cash）"""
    name = (body.get("name") or "").strip() or "模拟账户"
    mode = body.get("mode") or "sim"
    if mode not in ("sim", "replay", "agent"):
        raise HTTPException(400, "mode 必须为 sim/replay/agent")
    try:
        initial = float(body.get("initial_cash") or 100000)
    except (TypeError, ValueError):
        raise HTTPException(400, "initial_cash 非法")
    if initial <= 0:
        raise HTTPException(400, "初始资金必须大于 0")
    a = SimAccount(name=name, mode=mode, initial_cash=initial, cash=initial)
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"id": a.id, "name": a.name, "mode": a.mode,
            "initial_cash": float(a.initial_cash), "cash": float(a.cash)}


@router.get("/accounts/{account_id}/positions")
def account_positions(account_id: int, db: Session = Depends(get_db)):
    """单账户持仓明细（按最新收盘估值）"""
    a = db.get(SimAccount, account_id)
    if a is None:
        raise HTTPException(404, f"账户 {account_id} 不存在")
    out = []
    for p in db.scalars(select(SimPosition).where(
            SimPosition.account_id == account_id)).all():
        last = db.scalar(
            select(DailyPrice.close).where(DailyPrice.ts_code == p.ts_code)
            .order_by(DailyPrice.trade_date.desc()).limit(1))
        px = float(last or 0)
        avg = float(p.avg_cost)
        out.append({"ts_code": p.ts_code, "qty": p.qty, "avg_cost": avg,
                    "last_price": px, "market_value": round(px * p.qty, 2),
                    "pnl": round((px - avg) * p.qty, 2),
                    "pnl_pct": round((px / avg - 1) * 100, 2) if avg else 0})
    return {"account_id": account_id, "cash": float(a.cash),
            "positions": out}


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    """删除账户：级联删除其交易记录、持仓、回放会话、策略绑定"""
    a = db.get(SimAccount, account_id)
    if a is None:
        raise HTTPException(404, f"账户 {account_id} 不存在")
    n_trades = db.query(SimTrade).filter(SimTrade.account_id == account_id)\
        .delete(synchronize_session=False)
    db.query(SimPosition).filter(SimPosition.account_id == account_id)\
        .delete(synchronize_session=False)
    db.query(ReplaySession).filter(ReplaySession.account_id == account_id)\
        .delete(synchronize_session=False)
    db.query(StrategyBinding).filter(StrategyBinding.account_id == account_id)\
        .delete(synchronize_session=False)
    db.delete(a)
    db.commit()
    return {"ok": True, "deleted": account_id, "trades_removed": n_trades}


@router.get("/accounts")
def list_accounts(db: Session = Depends(get_db)):
    accounts = db.scalars(select(SimAccount).order_by(SimAccount.id.desc())).all()
    out = []
    for a in accounts:
        # 市值按最新日线收盘实时计算
        market_value = 0.0
        for p in db.scalars(select(SimPosition).where(SimPosition.account_id == a.id)).all():
            last = db.scalar(
                select(DailyPrice.close)
                .where(DailyPrice.ts_code == p.ts_code)
                .order_by(DailyPrice.trade_date.desc()).limit(1)
            )
            market_value += float(last or 0) * p.qty
        total = float(a.cash) + market_value
        initial = float(a.initial_cash)
        profit = total - initial
        out.append({
            "id": a.id, "name": a.name, "mode": a.mode,
            "cash": float(a.cash), "market_value": round(market_value, 2),
            "total_value": round(total, 2), "initial_cash": initial,
            "profit": round(profit, 2),
            "profit_pct": round(profit / initial * 100, 2) if initial else 0.0,
            "created_at": a.created_at.isoformat(),
        })
    return out


@router.get("/trades")
def list_trades(
    account_id: int | None = None,
    ts_code: str = "",
    source: str = "",
    side: str = "",
    start: dt.date | None = None,
    end: dt.date | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    conds = []
    if account_id is not None:
        conds.append(SimTrade.account_id == account_id)
    if ts_code:
        from ..utils import resolve_ts_code
        ts_code = resolve_ts_code(db, ts_code) or ts_code
        conds.append(SimTrade.ts_code == ts_code)
    if source:
        conds.append(SimTrade.source == source)
    if side:
        conds.append(SimTrade.side == side)
    if start:
        conds.append(SimTrade.trade_date >= start)
    if end:
        conds.append(SimTrade.trade_date <= end)

    base = select(SimTrade).where(*conds)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    trades = db.scalars(
        base.order_by(SimTrade.trade_date.desc(), SimTrade.id.desc())
        .offset((page - 1) * page_size).limit(page_size)).all()

    name_map = dict(db.execute(
        select(StockBasic.ts_code, StockBasic.name)
        .where(StockBasic.ts_code.in_([t.ts_code for t in trades] or [""]))
    ).all())

    items = []
    for t in trades:
        d = trade_dict(t)
        d["name"] = name_map.get(t.ts_code, t.ts_code)
        items.append(d)
    return {"total": total, "items": items}


@router.get("/trades/stats")
def trade_stats(
    account_id: int | None = None,
    start: dt.date | None = None,
    end: dt.date | None = None,
    db: Session = Depends(get_db),
):
    conds = []
    if account_id is not None:
        conds.append(SimTrade.account_id == account_id)
    if start:
        conds.append(SimTrade.trade_date >= start)
    if end:
        conds.append(SimTrade.trade_date <= end)
    trades = db.scalars(
        select(SimTrade).where(*conds).order_by(SimTrade.trade_date, SimTrade.id)).all()

    avg_cost: float | None = None
    holding = 0
    wins = sell_count = buy_count = 0
    total_fee = total_amount = 0.0
    for t in trades:
        amt, fee = float(t.amount), float(t.fee)
        total_fee += fee
        total_amount += amt
        if t.side == "buy":
            buy_count += 1
            cost = (avg_cost or 0.0) * holding + amt + fee
            holding += t.qty
            avg_cost = cost / holding if holding else None
        else:
            sell_count += 1
            pnl = (float(t.price) - (avg_cost or 0.0)) * t.qty
            if pnl > 0:
                wins += 1
            holding -= t.qty
            avg_cost = avg_cost if holding > 0 else None

    return {
        "count": len(trades), "buy_count": buy_count, "sell_count": sell_count,
        "win_rate": round(wins / sell_count * 100, 2) if sell_count else 0.0,
        "total_fee": round(total_fee, 2), "total_amount": round(total_amount, 2),
    }
