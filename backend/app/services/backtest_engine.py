"""回测引擎：数据加载 + 交易规则模拟（自实现，不依赖其他 agent 模块）

费用/T+1/涨跌停/100股整数倍 与回放（契约第1节）同规则：
- 佣金 max(amount*0.00025, 5)；印花税 卖出 amount*0.001（settings 读取）
- T+1：当日买入不可卖（avail_qty 模型）
- 涨跌停：主板±10%，创业(30)/科创(68)±20%，北交(8/4开头)±30%（按代码前缀）
- 买入按收盘价、100 股整数倍
"""
from __future__ import annotations

import datetime as dt
import math

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..models import BacktestRun, DailyPrice
from .sandbox import run_in_sandbox


# ---------------------------------------------------------------- 交易规则
def limit_pct(ts_code: str) -> float:
    """按代码前缀返回涨跌停幅度（小数）"""
    symbol = ts_code.split(".")[0]
    if symbol.startswith(("30", "68")):
        return 0.20
    if symbol.startswith(("8", "4", "92")):
        return 0.30
    return 0.10


def commission(amount: float) -> float:
    return max(amount * settings.commission_rate, settings.commission_min)


def stamp_tax(amount: float) -> float:
    return amount * settings.stamp_tax_rate


class SimTrader:
    """按当根收盘价撮合的模拟交易器（回测/挂机共用）"""

    def __init__(self, bars: list[dict], ts_code: str, cash: float,
                 qty: int = 0, avail_qty: int = 0, avg_cost: float = 0.0,
                 on_trade=None, strict: bool = False):
        self.bars = bars
        self.ts_code = ts_code
        self.cash = float(cash)
        self.qty = int(qty)
        self.avail_qty = int(avail_qty)  # T+1 可卖数量
        self.avg_cost = float(avg_cost)
        self.on_trade = on_trade          # callback(trade: dict)
        self.strict = strict              # True: 规则违规抛错；False: 跳过该笔
        self._ctx = None
        self._cur_date: str | None = None
        self.trades: list[dict] = []

    # ---- 引擎接口 ----
    def attach(self, ctx):
        self._ctx = ctx

    def new_day(self, date: str) -> None:
        if self._cur_date != date:
            self._cur_date = date
            self.avail_qty = self.qty  # T+1：新交易日昨仓可卖

    @property
    def position_qty(self) -> int:
        return self.qty

    def _bar(self) -> dict:
        bar = self.bars[self._ctx._i]
        self.new_day(bar["date"])  # 惰性推进交易日（T+1 解冻昨仓）
        return bar

    def _pre_close(self, bar: dict) -> float:
        pc = bar.get("pre_close")
        if pc:
            return float(pc)
        i = self._ctx._i
        return float(self.bars[i - 1]["close"]) if i > 0 else float(bar["close"])

    def _record(self, bar, side, price, qty, amount, fee, reason):
        t = {"trade_date": bar["date"], "ts_code": self.ts_code, "side": side,
             "price": round(price, 4), "qty": qty, "amount": round(amount, 2),
             "fee": round(fee, 2), "reason": reason}
        self.trades.append(t)
        if self.on_trade:
            self.on_trade(t)

    # ---- 下单 ----
    def buy(self, ratio: float = 1.0, reason: str = "") -> None:
        bar = self._bar()
        price = float(bar["close"])
        pc = self._pre_close(bar)
        if price > pc * (1 + limit_pct(self.ts_code)) + 1e-6:
            if self.strict:
                raise ValueError("涨停禁止买入")
            return
        budget = self.cash * max(0.0, min(1.0, ratio))
        shares = int(budget / (price * (1 + settings.commission_rate)) // 100) * 100
        while shares >= 100:
            amount = shares * price
            fee = commission(amount)
            if amount + fee <= self.cash + 1e-6:
                break
            shares -= 100
        if shares < 100:
            return  # 资金不足整手，跳过
        amount = shares * price
        fee = commission(amount)
        # 均摊买入费用到成本
        total_cost = self.avg_cost * self.qty + amount + fee
        self.qty += shares
        self.avg_cost = total_cost / self.qty
        self.cash -= amount + fee
        self._record(bar, "buy", price, shares, amount, fee, reason)

    def _sell_check(self, bar: dict) -> bool:
        price = float(bar["close"])
        pc = self._pre_close(bar)
        if price < pc * (1 - limit_pct(self.ts_code)) - 1e-6:
            if self.strict:
                raise ValueError("跌停禁止卖出")
            return False
        return True

    def sell(self, qty: int, reason: str = "") -> None:
        if self.qty <= 0 or qty <= 0:
            return
        bar = self._bar()
        if not self._sell_check(bar):
            return
        qty = min(int(qty), self.avail_qty)
        qty = qty // 100 * 100
        if qty <= 0:
            if self.strict:
                raise ValueError("T+1：当日买入不可卖 / 非100整数倍")
            return
        self._do_sell(bar, qty, reason)

    def sell_all(self, reason: str = "") -> None:
        if self.qty <= 0:
            return
        bar = self._bar()
        if not self._sell_check(bar):
            return
        qty = self.avail_qty  # T+1：只能卖昨仓
        if qty <= 0:
            return
        self._do_sell(bar, qty, reason)

    def _do_sell(self, bar: dict, qty: int, reason: str) -> None:
        price = float(bar["close"])
        amount = qty * price
        fee = commission(amount) + stamp_tax(amount)
        self.cash += amount - fee
        self.qty -= qty
        self.avail_qty -= qty
        if self.qty == 0:
            self.avg_cost = 0.0
        self._record(bar, "sell", price, qty, amount, fee, reason)


# ---------------------------------------------------------------- 指标
def compute_metrics(equity: list[float], trades: list[dict],
                    initial_cash: float) -> dict:
    n = len(equity)
    final = equity[-1] if n else initial_cash
    total_return = final / initial_cash - 1

    # 年化（252 交易日）
    annual_return = (1 + total_return) ** (252 / n) - 1 if n > 0 else 0.0

    # 最大回撤
    peak, mdd = -math.inf, 0.0
    for v in equity:
        peak = max(peak, v)
        if peak > 0:
            mdd = max(mdd, (peak - v) / peak)
    max_drawdown = -mdd

    # 夏普（日频，无风险 2%）
    sharpe = 0.0
    if n > 1:
        rets = [equity[i] / equity[i - 1] - 1 for i in range(1, n) if equity[i - 1] > 0]
        if len(rets) > 1:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
            std = math.sqrt(var)
            if std > 1e-12:
                sharpe = (mean - 0.02 / 252) / std * math.sqrt(252)

    # 交易统计（按卖出笔，成本含买入费用分摊）
    wins, losses = [], []
    avg_cost = 0.0  # 不重新推演，用 trades 中 buy 记录重演成本
    qty = 0
    cost_basis = 0.0
    for t in trades:
        if t["side"] == "buy":
            cost_basis += t["amount"] + t["fee"]
            qty += t["qty"]
            avg_cost = cost_basis / qty
        else:
            pnl = (t["price"] - avg_cost) * t["qty"] - t["fee"]
            (wins if pnl > 0 else losses).append(pnl)
            cost_basis -= avg_cost * t["qty"]
            qty -= t["qty"]
            avg_cost = cost_basis / qty if qty > 0 else 0.0
    sell_count = len(wins) + len(losses)
    win_rate = len(wins) / sell_count if sell_count else 0.0
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 1e-9 else (None if not wins else 999.0)

    return {
        "total_return": round(total_return, 6),
        "annual_return": round(annual_return, 6),
        "max_drawdown": round(max_drawdown, 6),
        "sharpe": round(sharpe, 4),
        "win_rate": round(win_rate, 4),
        "trade_count": len(trades),
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
    }


# ---------------------------------------------------------------- 数据加载
def load_bars(db: Session, ts_code: str, start=None, end=None) -> list[dict]:
    stmt = select(DailyPrice).where(DailyPrice.ts_code == ts_code)
    if start:
        stmt = stmt.where(DailyPrice.trade_date >= start)
    if end:
        stmt = stmt.where(DailyPrice.trade_date <= end)
    rows = db.scalars(stmt.order_by(DailyPrice.trade_date)).all()
    if not rows:
        from .market_sync import sync_daily
        sync_daily(db, ts_code, incremental=True)
        rows = db.scalars(
            select(DailyPrice).where(DailyPrice.ts_code == ts_code)
            .order_by(DailyPrice.trade_date)
        ).all()
        if start or end:  # 再按区间过滤
            rows = [r for r in rows
                    if (not start or r.trade_date >= start)
                    and (not end or r.trade_date <= end)]
    return [
        {"date": r.trade_date.isoformat(), "open": float(r.open),
         "high": float(r.high), "low": float(r.low), "close": float(r.close),
         "volume": float(r.vol) if r.vol is not None else 0.0,
         "pre_close": float(r.pre_close) if r.pre_close is not None else None}
        for r in rows
    ]


# ---------------------------------------------------------------- 主入口
def run_backtest(db: Session, code: str, params: dict | None, ts_code: str,
                 start=None, end=None, initial_cash: float = 1_000_000.0,
                 strategy_id: int | None = None) -> dict:
    """执行回测并落库 backtest_run，返回完整结果 dict（契约第5节）"""
    run = BacktestRun(
        strategy_id=strategy_id or 0, ts_codes=[ts_code],  # 库表 NOT NULL，独立调用记 0
        start_date=start, end_date=end,
        initial_cash=initial_cash, params=params, status="running")
    db.add(run)
    db.commit()
    db.refresh(run)

    def fail(error: str) -> dict:
        # 失败不留历史：删除本次 run 记录，只返回错误信息给前端展示
        try:
            db.delete(run)
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        return {"strategy_id": strategy_id,
                "status": "failed", "error": error}

    try:
        bars = load_bars(db, ts_code, start, end)
        if not bars:
            # 带出本地实际可用区间，便于诊断
            from sqlalchemy import func as _f
            rng = db.execute(
                select(_f.min(DailyPrice.trade_date), _f.max(DailyPrice.trade_date))
                .where(DailyPrice.ts_code == ts_code)).first()
            if rng and rng[0]:
                return fail(
                    f"{ts_code} 在 {start or '开始'} ~ {end or '结束'} 区间内无行情数据；"
                    f"本地可用数据范围：{rng[0]} ~ {rng[1]}，请调整回测区间")
            return fail(f"无 {ts_code} 行情数据（本地为空且Tushare拉取失败，请先在行情页查询一次该股）")
    except Exception as e:  # noqa: BLE001
        return fail(f"行情加载失败: {e}")

    trader = SimTrader(bars, ts_code, initial_cash)

    def equity_curve() -> list[dict]:
        # 逐日重演：按 trades 推每日收盘总资产（cash + 持仓市值）
        curve, ti, cash, q, avg = [], 0, initial_cash, 0, 0.0
        for bar in bars:
            d = bar["date"]
            while ti < len(trader.trades) and trader.trades[ti]["trade_date"] == d:
                t = trader.trades[ti]
                if t["side"] == "buy":
                    basis = avg * q + t["amount"] + t["fee"]
                    q += t["qty"]
                    avg = basis / q
                    cash -= t["amount"] + t["fee"]
                else:
                    cash += t["amount"] - t["fee"]
                    q -= t["qty"]
                    avg = avg if q > 0 else 0.0
                ti += 1
            curve.append({"date": d, "equity": round(cash + q * bar["close"], 2)})
        return curve

    res = run_in_sandbox(code, bars, trader, params)
    # 注意：逐bar执行中 trader.new_day 需在每根bar前调用——通过包装实现
    if not res["ok"]:
        return fail(res["error"] or "策略执行失败")

    curve = equity_curve()
    metrics = compute_metrics([p["equity"] for p in curve], trader.trades, initial_cash)

    run.status = "success"
    run.metrics = metrics
    run.equity_curve = curve
    run.trades_json = trader.trades
    db.commit()
    return {"id": run.id, "strategy_id": strategy_id, "status": "success",
            "ts_code": ts_code, "start_date": bars[0]["date"] if bars else None,
            "end_date": bars[-1]["date"] if bars else None,
            "initial_cash": initial_cash, "metrics": metrics,
            "equity_curve": curve, "trades": trader.trades, "error": None}


def validate_strategy_code(db: Session, code: str, params: dict | None = None,
                           ts_code: str = "000001.SZ", initial_cash: float = 1_000_000.0) -> dict:
    """沙箱校验：编译 + 近120交易日试跑，返回 {ok, error?}"""
    from .sandbox import compile_strategy, SandboxError
    try:
        compile_strategy(code)
    except SandboxError as e:
        return {"ok": False, "error": str(e)}
    try:
        all_bars = load_bars(db, ts_code)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"行情加载失败: {e}"}
    bars = all_bars[-120:]
    if not bars:
        return {"ok": False, "error": f"无 {ts_code} 行情数据用于试跑"}
    trader = SimTrader(bars, ts_code, initial_cash)
    res = run_in_sandbox(code, bars, trader, params)
    if not res["ok"]:
        return {"ok": False, "error": res["error"]}
    return {"ok": True, "trades": len(trader.trades)}
