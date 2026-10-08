"""策略挂机执行（M7）：run_all_bindings(db)

遍历 active strategy_binding，对最新交易日收盘价执行沙箱策略：
- 复用沙箱 Ctx + SimTrader 撮合规则，但只在最后一根 bar（最新交易日）允许真实下单
- 下单直接落库：sim_trade(source=strategy) + sim_position + 账户 cash
- 策略可见数据截止当日（防未来：本地 daily_price 天然只含已同步的历史）
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SimAccount, SimPosition, SimTrade, Strategy, StrategyBinding
from .backtest_engine import SimTrader, load_bars

log = logging.getLogger(__name__)

WARMUP_BARS = 250  # 指标预热窗口（约一年）


class LiveTrader(SimTrader):
    """只在最后一根 bar（最新交易日）允许真实下单的 trader"""

    def __init__(self, *a, on_trade=None, **kw):
        super().__init__(*a, on_trade=on_trade, **kw)

    def _live(self) -> bool:
        return self._ctx is not None and self._ctx._i == len(self.bars) - 1

    def buy(self, ratio=1.0, reason=""):
        if not self._live():
            return
        super().buy(ratio, reason)

    def sell(self, qty, reason=""):
        if not self._live():
            return
        super().sell(qty, reason)

    def sell_all(self, reason=""):
        if not self._live():
            return
        super().sell_all(reason)


def _run_one_binding(db: Session, binding: StrategyBinding) -> dict:
    strat = db.get(Strategy, binding.strategy_id)
    if strat is None:
        return {"binding_id": binding.id, "error": "策略不存在"}
    account = db.get(SimAccount, binding.account_id)
    if account is None:
        return {"binding_id": binding.id, "error": "账户不存在"}

    results = []
    for ts_code in (binding.ts_codes or [])[:1]:  # M7 前单标的
        bars = load_bars(db, ts_code)
        if not bars:
            results.append({"ts_code": ts_code, "error": "无行情数据"})
            continue
        window = bars[-WARMUP_BARS:]
        trade_date = bars[-1]["date"]  # 最新交易日

        pos = db.scalar(select(SimPosition).where(
            SimPosition.account_id == account.id, SimPosition.ts_code == ts_code))
        qty = pos.qty if pos else 0
        avg_cost = float(pos.avg_cost) if pos else 0.0
        # T+1：扣掉当日已买入数量
        bought_today = db.execute(
            select(SimTrade.qty).where(SimTrade.account_id == account.id,
                                       SimTrade.ts_code == ts_code,
                                       SimTrade.trade_date == bars[-1]["date"],
                                       SimTrade.side == "buy")
        ).scalars()
        avail = qty - sum(b for b in bought_today if b)

        db_trades: list[SimTrade] = []

        def persist(t: dict) -> None:
            row = SimTrade(account_id=account.id, ts_code=ts_code,
                           trade_date=t["trade_date"], side=t["side"],
                           price=t["price"], qty=t["qty"], amount=t["amount"],
                           fee=t["fee"], source="strategy",
                           strategy_id=strat.id, note=t.get("reason") or None)
            db.add(row)
            db_trades.append(row)

        trader = LiveTrader(window, ts_code, float(account.cash),
                            qty=qty, avail_qty=max(0, avail), avg_cost=avg_cost,
                            on_trade=persist)
        from .sandbox import run_in_sandbox
        res = run_in_sandbox(strat.code, window, trader, binding.params or strat.params)
        if not res["ok"]:
            db.rollback()
            results.append({"ts_code": ts_code, "error": res["error"]})
            continue

        # 落库：交易已在 persist 中 add；更新持仓与现金
        if trader.qty > 0:
            if pos:
                pos.qty, pos.avg_cost = trader.qty, round(trader.avg_cost, 4)
            else:
                db.add(SimPosition(account_id=account.id, ts_code=ts_code,
                                   qty=trader.qty, avg_cost=round(trader.avg_cost, 4)))
        elif pos:
            pos.qty, pos.avg_cost = 0, 0.0
        account.cash = round(trader.cash, 2)
        db.commit()
        results.append({"ts_code": ts_code, "trade_date": trade_date,
                        "trades": len(db_trades),
                        "cash": float(account.cash), "position": trader.qty})
    return {"binding_id": binding.id, "strategy_id": strat.id, "results": results}


def run_all_bindings(db: Session) -> list[dict]:
    """17:45 定时任务入口：全部 active 挂机执行一次"""
    bindings = db.scalars(select(StrategyBinding)
                          .where(StrategyBinding.status == "active")).all()
    out = []
    for b in bindings:
        try:
            r = _run_one_binding(db, b)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            log.exception("挂机执行失败 binding=%s: %s", b.id, e)
            r = {"binding_id": b.id, "error": str(e)}
        out.append(r)
    log.info("挂机执行完成: %d 个绑定", len(bindings))
    return out
