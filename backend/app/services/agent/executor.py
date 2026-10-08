"""执行器：agent 订单按【决策时刻实时价】成交（费用/T+1/涨跌停，规则同回放）"""
import datetime as dt
import logging
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import settings
from ...models import DailyPrice, SimAccount, SimPosition, SimTrade

log = logging.getLogger(__name__)


def _limit_pct(ts_code: str) -> float:
    symbol = ts_code.split(".")[0]
    if symbol.startswith(("30", "68")):
        return 0.20
    if symbol.startswith(("8", "4", "92")):
        return 0.30
    return 0.10


def _pre_close(db: Session, ts_code: str, realtime_pre_close: float | None) -> float:
    if realtime_pre_close:
        return float(realtime_pre_close)
    last = db.scalar(
        select(DailyPrice.close).where(DailyPrice.ts_code == ts_code)
        .order_by(DailyPrice.trade_date.desc()).limit(1))
    return float(last) if last else 0.0


def _bought_today(db: Session, account_id: int, ts_code: str, date: dt.date) -> int:
    trades = db.scalars(select(SimTrade).where(
        SimTrade.account_id == account_id, SimTrade.ts_code == ts_code,
        SimTrade.trade_date == date, SimTrade.side == "buy")).all()
    return sum(t.qty for t in trades)


def execute_agent_order(db: Session, account: SimAccount, ts_code: str, side: str,
                        qty: int, price: float, pre_close: float | None = None,
                        note: str = "") -> dict:
    """按实时价撮合；返回 {ok, trade} 或 {ok:False, error}；不抛异常（风控层处理拒绝）。"""
    if qty <= 0 or qty % 100 != 0:
        return {"ok": False, "error": f"数量必须100整数倍: {qty}"}
    p = Decimal(str(price))
    amount = (p * qty).quantize(Decimal("0.01"))
    commission = max(amount * Decimal(str(settings.commission_rate)),
                     Decimal(str(settings.commission_min))).quantize(Decimal("0.01"))
    today = dt.date.today()

    pre = Decimal(str(_pre_close(db, ts_code, pre_close)))
    pct = Decimal(str(_limit_pct(ts_code)))
    tol = Decimal("0.0001")
    if pre > 0:
        if side == "buy" and p > pre * (1 + pct) + tol:
            return {"ok": False, "error": f"涨停拒单 {p} > {pre}×{1+pct}"}
        if side == "sell" and p < pre * (1 - pct) - tol:
            return {"ok": False, "error": f"跌停拒单 {p} < {pre}×{1-pct}"}

    position = db.scalar(select(SimPosition).where(
        SimPosition.account_id == account.id, SimPosition.ts_code == ts_code))

    if side == "buy":
        total = amount + commission
        if Decimal(str(account.cash)) < total:
            return {"ok": False, "error": f"资金不足 需{total} 有{account.cash}"}
        if position is None:
            position = SimPosition(account_id=account.id, ts_code=ts_code,
                                   qty=qty, avg_cost=float(total / qty))
            db.add(position)
        else:
            old = position.qty
            cost = Decimal(str(position.avg_cost)) * old + total
            position.qty = old + qty
            position.avg_cost = float((cost / position.qty).quantize(Decimal("0.0001")))
        account.cash = float(Decimal(str(account.cash)) - total)
        fee = float(commission)
    else:  # sell
        if position is None or position.qty < qty:
            return {"ok": False, "error": f"持仓不足 {position.qty if position else 0} < {qty}"}
        locked = _bought_today(db, account.id, ts_code, today)
        if position.qty - locked < qty:
            return {"ok": False, "error": f"T+1限制 可卖{position.qty - locked}"}
        tax = (amount * Decimal(str(settings.stamp_tax_rate))).quantize(Decimal("0.01"))
        fee = float(commission + tax)
        account.cash = float(Decimal(str(account.cash)) + amount - commission - tax)
        position.qty -= qty
        if position.qty == 0:
            db.delete(position)
    trade = SimTrade(account_id=account.id, ts_code=ts_code, trade_date=today,
                     side=side, price=float(p), qty=qty, amount=float(amount),
                     fee=fee, source="agent", note=note[:250] or "agent")
    db.add(trade)
    db.flush()
    return {"ok": True, "trade": trade}
