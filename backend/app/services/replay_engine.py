"""回放引擎：会话推进 / 下撮合 / 估值 / 统计（纯逻辑层，路由调用）"""
import datetime as dt
import logging
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import DailyPrice, ReplaySession, SimAccount, SimPosition, SimTrade, Strategy
from .market_sync import sync_daily

log = logging.getLogger(__name__)


def ensure_daily(db: Session, ts_code: str) -> None:
    """本地无日线时先全量拉取（懒加载，同 stocks.py 风格）"""
    has = db.scalar(select(DailyPrice.close).where(DailyPrice.ts_code == ts_code).limit(1))
    if has is None:
        try:
            sync_daily(db, ts_code, incremental=True)  # 本地无数据时内部自动转全量
        except Exception as e:  # noqa: BLE001
            raise HTTPException(502, f"Tushare 拉取失败: {e}") from e
        if db.scalar(select(DailyPrice.close).where(DailyPrice.ts_code == ts_code).limit(1)) is None:
            raise HTTPException(404, f"未找到 {ts_code} 的行情数据")


def trade_dates(db: Session, ts_code: str) -> list[dt.date]:
    return list(db.execute(
        select(DailyPrice.trade_date).where(DailyPrice.ts_code == ts_code)
        .order_by(DailyPrice.trade_date)
    ).scalars())


def bar_at(db: Session, ts_code: str, date: dt.date) -> DailyPrice | None:
    return db.scalar(
        select(DailyPrice).where(DailyPrice.ts_code == ts_code, DailyPrice.trade_date == date)
    )


def bar_on_or_before(db: Session, ts_code: str, date: dt.date) -> DailyPrice | None:
    return db.scalar(
        select(DailyPrice).where(DailyPrice.ts_code == ts_code, DailyPrice.trade_date <= date)
        .order_by(DailyPrice.trade_date.desc()).limit(1)
    )


def limit_pct(ts_code: str) -> float:
    """涨跌停幅度：北交所(8/4开头)±30%，创业板30/科创68 ±20%，主板±10%"""
    code = ts_code.split(".")[0]
    if code[:1] in ("8", "4"):
        return 0.30
    if code[:2] in ("30", "68"):
        return 0.20
    return 0.10


def get_session(db: Session, session_id: int) -> ReplaySession:
    s = db.get(ReplaySession, session_id)
    if s is None:
        raise HTTPException(404, f"回放会话 {session_id} 不存在")
    return s


def advance(db: Session, session: ReplaySession, days: int = 1) -> dt.date | None:
    """cursor 向后推进 days 个交易日；返回新 cursor（无可推进日期则保持并返回 None）"""
    dates = trade_dates(db, session.ts_code)
    after = [d for d in dates if d > session.cursor_date]
    if not after:
        return None
    new_cursor = after[min(days, len(after)) - 1]
    session.cursor_date = new_cursor
    db.commit()
    return new_cursor


def goto(db: Session, session: ReplaySession, date: dt.date) -> dt.date:
    if date < session.cursor_date:
        raise HTTPException(400, "goto 仅允许向前推进")
    if date == session.cursor_date:
        return date
    candidates = [d for d in trade_dates(db, session.ts_code)
                  if session.cursor_date < d <= date]
    if not candidates:
        # 目标日无交易且之后无新K线：推进到 <= date 的最后一根
        last = bar_on_or_before(db, session.ts_code, date)
        if last is None or last.trade_date <= session.cursor_date:
            raise HTTPException(400, f"{date} 之后无可推进的交易日")
        session.cursor_date = last.trade_date
    else:
        session.cursor_date = candidates[-1]
    db.commit()
    return session.cursor_date


def _pre_close(db: Session, ts_code: str, bar: DailyPrice) -> float:
    if bar.pre_close is not None:
        return float(bar.pre_close)
    prev = db.scalar(
        select(DailyPrice.close).where(DailyPrice.ts_code == ts_code,
                                       DailyPrice.trade_date < bar.trade_date)
        .order_by(DailyPrice.trade_date.desc()).limit(1)
    )
    if prev is None:
        return float(bar.close)
    return float(prev)


def bought_today_qty(db: Session, account_id: int, ts_code: str, date: dt.date) -> int:
    """当日买入数量（T+1 判断依据）"""
    rows = db.execute(
        select(SimTrade.qty).where(SimTrade.account_id == account_id,
                                   SimTrade.ts_code == ts_code,
                                   SimTrade.side == "buy",
                                   SimTrade.trade_date == date)
    ).scalars().all()
    return sum(rows)


def place_order(db: Session, session: ReplaySession, account: SimAccount,
                side: str, qty: int) -> SimTrade:
    """按 cursor_date 当日 close 撮合；失败抛 HTTPException(400)"""
    if qty <= 0 or qty % 100 != 0:
        raise HTTPException(400, "下单数量必须为 100 的整数倍且大于 0")
    bar = bar_at(db, session.ts_code, session.cursor_date)
    if bar is None:
        raise HTTPException(400, f"{session.cursor_date} 无行情，无法交易")

    price = Decimal(str(bar.close))
    amount = (price * qty).quantize(Decimal("0.01"))
    commission = max(amount * Decimal(str(settings.commission_rate)),
                     Decimal(str(settings.commission_min))).quantize(Decimal("0.01"))

    # 涨跌停校验（成交价=当日收盘，对比昨收）
    pre = Decimal(str(_pre_close(db, session.ts_code, bar)))
    pct = Decimal(str(limit_pct(session.ts_code)))
    tol = Decimal("0.0001")  # 容忍四舍五入误差
    if side == "buy" and price > pre * (1 + pct) + tol:
        raise HTTPException(400, f"涨停无法买入：{price} > 昨收{pre}×(1+{pct})")
    if side == "sell" and price < pre * (1 - pct) - tol:
        raise HTTPException(400, f"跌停无法卖出：{price} < 昨收{pre}×(1-{pct})")

    position = db.scalar(select(SimPosition).where(
        SimPosition.account_id == account.id, SimPosition.ts_code == session.ts_code))

    if side == "buy":
        total = amount + commission
        if Decimal(str(account.cash)) < total:
            raise HTTPException(400,
                f"资金不足：需 {total}（含佣金 {commission}），可用 {account.cash}")
        if position is None:
            position = SimPosition(account_id=account.id, ts_code=session.ts_code,
                                   qty=qty, avg_cost=float(total / qty))
            db.add(position)
        else:
            old_qty = position.qty
            new_cost = Decimal(str(position.avg_cost)) * old_qty + total
            position.qty = old_qty + qty
            position.avg_cost = float((new_cost / position.qty).quantize(Decimal("0.0001")))
        account.cash = float(Decimal(str(account.cash)) - total)
        fee = commission
    elif side == "sell":
        if position is None or position.qty < qty:
            raise HTTPException(400, f"持仓不足：当前 {position.qty if position else 0} 股")
        locked = bought_today_qty(db, account.id, session.ts_code, session.cursor_date)
        if position.qty - locked < qty:
            raise HTTPException(400,
                f"T+1 限制：当日买入 {locked} 股不可卖，可卖 {position.qty - locked} 股")
        tax = (amount * Decimal(str(settings.stamp_tax_rate))).quantize(Decimal("0.01"))
        fee = commission + tax
        net = amount - fee
        account.cash = float(Decimal(str(account.cash)) + net)
        position.qty -= qty
        if position.qty == 0:
            db.delete(position)
    else:
        raise HTTPException(400, "side 必须为 buy 或 sell")

    trade = SimTrade(account_id=account.id, ts_code=session.ts_code,
                     trade_date=session.cursor_date, side=side,
                     price=float(price), qty=qty, amount=float(amount),
                     fee=float(fee), source="manual",
                     note=f"replay#{session.id}")
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade


def account_snapshot(db: Session, session: ReplaySession, account: SimAccount) -> dict:
    """cash + 按 cursor_date 收盘价实时估值"""
    positions = db.scalars(select(SimPosition).where(
        SimPosition.account_id == account.id)).all()
    items, market_value = [], Decimal("0")
    for p in positions:
        bar = bar_on_or_before(db, p.ts_code, session.cursor_date)
        last_price = float(bar.close) if bar else 0.0
        mv = Decimal(str(last_price)) * p.qty
        market_value += mv
        cost = Decimal(str(p.avg_cost)) * p.qty
        profit = mv - cost
        items.append({
            "ts_code": p.ts_code, "name": _stock_name(db, p.ts_code),
            "qty": p.qty, "avg_cost": float(p.avg_cost), "last_price": last_price,
            "market_value": float(mv.quantize(Decimal("0.01"))),
            "profit": float(profit.quantize(Decimal("0.01"))),
            "profit_pct": float((profit / cost * 100).quantize(Decimal("0.01"))) if cost else 0.0,
        })
    cash = Decimal(str(account.cash))
    total = cash + market_value
    initial = Decimal(str(account.initial_cash))
    profit = total - initial
    return {
        "cash": float(cash.quantize(Decimal("0.01"))),
        "market_value": float(market_value.quantize(Decimal("0.01"))),
        "total_value": float(total.quantize(Decimal("0.01"))),
        "profit": float(profit.quantize(Decimal("0.01"))),
        "profit_pct": float((profit / initial * 100).quantize(Decimal("0.01"))) if initial else 0.0,
        "positions": items,
    }


def _stock_name(db: Session, ts_code: str) -> str:
    from ..models import StockBasic
    name = db.scalar(select(StockBasic.name).where(StockBasic.ts_code == ts_code))
    return name or ts_code


def _trades_of(db: Session, account_id: int, ts_code: str | None = None) -> list[SimTrade]:
    stmt = select(SimTrade).where(SimTrade.account_id == account_id)
    if ts_code:
        stmt = stmt.where(SimTrade.ts_code == ts_code)  # 会话维度只统计本股票
    return db.scalars(stmt.order_by(SimTrade.trade_date, SimTrade.id)).all()


def summary(db: Session, session: ReplaySession, account: SimAccount) -> dict:
    trades = _trades_of(db, account.id, session.ts_code)

    # 胜率：每笔卖出 vs 其前所有买入的加权成本（简化配对）
    avg_cost: Decimal | None = None
    holding_qty = 0
    wins = sell_count = 0
    for t in trades:
        if t.side == "buy":
            total_cost = (avg_cost or Decimal("0")) * holding_qty + Decimal(str(t.amount)) + Decimal(str(t.fee))
            holding_qty += t.qty
            avg_cost = total_cost / holding_qty if holding_qty else None
        else:
            sell_count += 1
            pnl = (Decimal(str(t.price)) - (avg_cost or Decimal("0"))) * t.qty
            if pnl > 0:
                wins += 1
            holding_qty -= t.qty
            avg_cost = avg_cost if holding_qty > 0 else None

    # equity 曲线：start→cursor 逐交易日，持仓数量与现金由交易记录重建
    dates = [d for d in trade_dates(db, session.ts_code)
             if session.start_date <= d <= session.cursor_date]
    close_map = dict(db.execute(
        select(DailyPrice.trade_date, DailyPrice.close)
        .where(DailyPrice.ts_code == session.ts_code, DailyPrice.trade_date.in_(dates))
    ).all())
    trades_by_date: dict[dt.date, list[SimTrade]] = {}
    for t in trades:
        trades_by_date.setdefault(t.trade_date, []).append(t)

    cash = Decimal(str(account.initial_cash))
    qty = 0
    peak = Decimal("-Infinity")
    max_dd = Decimal("0")
    for d in dates:
        for t in trades_by_date.get(d, []):
            amt, fee = Decimal(str(t.amount)), Decimal(str(t.fee))
            if t.side == "buy":
                cash -= amt + fee
                qty += t.qty
            else:
                cash += amt - fee
                qty -= t.qty
        equity = cash + Decimal(str(close_map.get(d, 0))) * qty
        if equity > peak:
            peak = equity
        dd = (peak - equity) / peak if peak > 0 else Decimal("0")
        if dd > max_dd:
            max_dd = dd

    buy_count = sum(1 for t in trades if t.side == "buy")
    snap = account_snapshot(db, session, account)
    return {
        "trades": [trade_dict(t) for t in trades],
        "win_rate": round(wins / sell_count * 100, 2) if sell_count else 0.0,
        "total_profit": snap["profit"],
        "profit_pct": snap["profit_pct"],
        "max_drawdown": float(round(max_dd * 100, 2)),
        "buy_count": buy_count,
        "sell_count": sell_count,
    }


def trade_dict(t: SimTrade) -> dict:
    return {
        "id": t.id, "account_id": t.account_id, "ts_code": t.ts_code,
        "trade_date": t.trade_date.isoformat(), "side": t.side,
        "price": float(t.price), "qty": t.qty, "amount": float(t.amount),
        "fee": float(t.fee), "source": t.source,
        "strategy_id": t.strategy_id, "note": t.note,
    }


# ---------------- 策略回放：推进后对新增交易日逐根执行策略 ----------------

class _ReplayStrategyTrader:
    """沙箱 trader 适配器：把策略信号转为回放账户真实下单（复用 place_order 全套规则）"""

    def __init__(self, db: Session, session: ReplaySession, account: SimAccount,
                 exec_after: dt.date | None):
        self._db = db
        self._s = session
        self._acc = account
        self._after = exec_after          # 只执行 date > after 的信号（防重复触发）
        self._ctx = None                  # run_in_sandbox 注入
        self.executed = 0

    def attach(self, ctx):  # sandbox 约定入口
        self._ctx = ctx

    def _cur_date(self) -> dt.date | None:
        if self._ctx is None or self._ctx._i < 0:  # noqa: SLF001 同包内部约定
            return None
        return dt.date.fromisoformat(str(self._ctx._bars[self._ctx._i]["date"])[:10])  # noqa: SLF001

    def _should_exec(self) -> bool:
        d = self._cur_date()
        return d is not None and (self._after is None or d > self._after)

    @property
    def position_qty(self) -> int:
        pos = self._db.scalar(select(SimPosition).where(
            SimPosition.account_id == self._acc.id,
            SimPosition.ts_code == self._s.ts_code))
        return pos.qty if pos else 0

    @property
    def cash(self) -> float:
        return float(self._acc.cash)

    def _order(self, side: str, qty: int, reason: str):
        cur, date = self._s.cursor_date, self._cur_date()
        try:
            self._s.cursor_date = date  # 借道 place_order（按当日收盘撮合）
            t = place_order(self._db, self._s, self._acc, side, qty)
            t.source = "strategy"
            t.strategy_id = self._s.strategy_id
            t.note = f"replay#{self._s.id} {reason[:80]}"
            self._db.commit()
            self.executed += 1
        except HTTPException as e:
            log.info("策略回放 %s %s 跳过: %s", date, side, e.detail)
        finally:
            self._s.cursor_date = cur

    def buy(self, ratio: float = 1.0, reason: str = "") -> None:
        if not self._should_exec():
            return
        price = float(self._ctx._bars[self._ctx._i]["close"])  # noqa: SLF001
        budget = self.cash * max(0.0, min(1.0, ratio))
        qty = int(budget / price / 100) * 100
        if qty >= 100:
            self._order("buy", qty, reason)

    def sell(self, qty: int, reason: str = "") -> None:
        if not self._should_exec():
            return
        if qty >= 100:
            self._order("sell", min(int(qty), self.position_qty), reason)

    def sell_all(self, reason: str = "") -> None:
        if not self._should_exec():
            return
        locked = bought_today_qty(self._db, self._acc.id, self._s.ts_code,
                                  self._cur_date())
        qty = self.position_qty - locked
        if qty >= 100:
            self._order("sell", qty, reason)


def run_session_strategy(db: Session, session: ReplaySession) -> dict:
    """推进后调用：策略对 (strategy_last_date, cursor] 的新增交易日执行。
    绑定策略时 strategy_last_date=当时cursor，即只从绑定时刻开始生效。"""
    if not session.strategy_id:
        return {"ok": True, "executed": 0}
    strat = db.get(Strategy, session.strategy_id)
    if strat is None or strat.status == "disabled":
        return {"ok": True, "executed": 0, "note": "策略不存在或已停用，跳过"}
    account = db.get(SimAccount, session.account_id)

    from .backtest_engine import load_bars
    from .sandbox import run_in_sandbox
    bars = load_bars(db, session.ts_code, end=session.cursor_date)
    if not bars:
        return {"ok": False, "error": "无行情数据"}

    trader = _ReplayStrategyTrader(db, session, account, session.strategy_last_date)
    res = run_in_sandbox(strat.code, bars, trader, session.params or strat.params)
    session.strategy_last_date = session.cursor_date
    db.commit()
    if not res.get("ok"):
        log.warning("回放会话%s 策略执行出错: %s", session.id, res.get("error"))
        return {"ok": False, "error": res.get("error"), "executed": trader.executed}
    return {"ok": True, "executed": trader.executed}
