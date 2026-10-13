"""风控闸门 R1-R6：纯代码校验 LLM 决策，通过返回裁剪后的执行参数，拒绝返回原因"""
import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...models import (AgentDecision, DailyPrice, SimAccount, SimPosition, SimTrade)

log = logging.getLogger(__name__)

DEFAULT_RISK = {
    "max_pos_pct": 0.30,        # R1 单票仓位上限（占账户总值，小数）
    "max_trades_per_day": 5,    # R2 每股每日最大交易次数
    "max_drawdown_halt": 0.15,  # R3 回撤熔断阈值（小数）
    "halt_days": 10,            # R3 熔断天数
    "loss_streak_limit": 5,     # R4 连续亏损笔数限制
    "cooldown_days": 1,         # R5 同股交易冷却（交易日）
    # ---- P0-4 组合级 ----
    "max_industry_pct": 0.40,   # R7 单一行业市值占比上限
    "min_holdings": 3,          # R8 分散度告警阈值
    "account_drawdown_halt": 0.20,  # R9 账户级回撤熔断
}


def _params(config) -> dict:
    """合并用户配置并归一化单位：百分比形式(>1)自动转小数（UI 存的是 30 表示 30%）"""
    merged = {**DEFAULT_RISK, **(config.risk_params or {})}
    for pct_key in ("max_pos_pct", "max_drawdown_halt", "max_industry_pct",
                    "account_drawdown_halt"):
        if merged.get(pct_key, 0) > 1:
            merged[pct_key] = merged[pct_key] / 100
    return merged


def _realized_pnls(db: Session, account_id: int, ts_code: str | None = None) -> list[float]:
    """按交易顺序重演每笔卖出的已实现盈亏（加权成本法）"""
    stmt = select(SimTrade).where(SimTrade.account_id == account_id)
    if ts_code:
        stmt = stmt.where(SimTrade.ts_code == ts_code)
    trades = db.scalars(stmt.order_by(SimTrade.trade_date, SimTrade.id)).all()
    pnl: list[float] = []
    book: dict[str, tuple[int, float]] = {}  # ts_code -> (qty, avg_cost含费)
    for t in trades:
        qty, avg = book.get(t.ts_code, (0, 0.0))
        if t.side == "buy":
            new_cost = avg * qty + float(t.amount) + float(t.fee)
            qty += t.qty
            book[t.ts_code] = (qty, new_cost / qty)
        else:
            if qty > 0:
                pnl.append((float(t.price) - avg) * t.qty - float(t.fee))
            qty -= t.qty
            book[t.ts_code] = (max(0, qty), avg)
    return pnl


def account_value(db: Session, account: SimAccount) -> float:
    """现金 + 持仓按最新收盘估值"""
    value = float(account.cash)
    for p in db.scalars(select(SimPosition).where(
            SimPosition.account_id == account.id)).all():
        last = db.scalar(
            select(DailyPrice.close).where(DailyPrice.ts_code == p.ts_code)
            .order_by(DailyPrice.trade_date.desc()).limit(1))
        value += float(last or 0) * p.qty
    return value


def check(db: Session, config, account: SimAccount, ts_code: str,
          action: str, target_pos_pct: float | None,
          confidence: float | None, price: float | None) -> dict:
    """返回 {ok, qty, note}（qty=按规则裁剪后的最终股数）"""
    P = _params(config)
    today = dt.date.today()

    # R6 股票池白名单
    pool = config.stocks or []
    if ts_code not in pool:
        return {"ok": False, "qty": 0, "note": "R6拒绝：股票不在追踪池"}

    # R3 熔断（开仓类）
    if action == "buy":
        if config.pause_until and today <= config.pause_until:
            return {"ok": False, "qty": 0, "note": f"R3熔断中 至{config.pause_until}"}
        # 用已实现盈亏曲线近似峰值回撤（含当前浮盈亏则更准，这里以账户现值+盈亏序列估计）
        pnl = _realized_pnls(db, account.id)
        equity, peak, trough = float(account.initial_cash), float(account.initial_cash), 0.0
        for x in pnl:
            equity += x
            peak = max(peak, equity)
        value_now = account_value(db, account)
        peak = max(peak, value_now)
        drawdown = (peak - value_now) / peak if peak > 0 else 0
        if drawdown > P["max_drawdown_halt"]:
            config.pause_until = today + dt.timedelta(days=P["halt_days"])
            db.commit()
            from ..services.notify import notify
            from ..services import event_bus
            event_bus.publish("agent_halt",
                              {"ts_code": ts_code, "drawdown": round(drawdown, 4),
                               "pause_until": config.pause_until.isoformat()},
                              important=True)
            notify("Agent 风控熔断触发",
                   f"账户回撤 {drawdown:.1%} 超过阈值 {P['max_drawdown_halt']:.0%}，"
                   f"已暂停开仓至 {config.pause_until}", important=True)
            return {"ok": False, "qty": 0,
                    "note": f"R3熔断：回撤{drawdown:.1%}>{P['max_drawdown_halt']:.0%}，暂停至{config.pause_until}"}

    # R2 日内限次
    n_today = len(db.scalars(select(SimTrade.id).where(
        SimTrade.account_id == account.id, SimTrade.ts_code == ts_code,
        SimTrade.trade_date == today)).all())
    if n_today >= P["max_trades_per_day"]:
        return {"ok": False, "qty": 0, "note": f"R2拒绝：今日已交易{n_today}次"}

    # R4 连续亏损（开仓类）
    if action == "buy":
        pnl = _realized_pnls(db, account.id)
        streak = 0
        for x in reversed(pnl):
            if x < 0:
                streak += 1
            else:
                break
        if streak >= P["loss_streak_limit"]:
            return {"ok": False, "qty": 0, "note": f"R4拒绝：连续亏损{streak}笔，只允许卖出/持有"}

    # R5 冷却期
    last_trade = db.scalar(select(SimTrade.trade_date).where(
        SimTrade.account_id == account.id, SimTrade.ts_code == ts_code)
        .order_by(SimTrade.trade_date.desc()).limit(1))
    if last_trade and (today - last_trade).days < P["cooldown_days"]:
        return {"ok": False, "qty": 0,
                "note": f"R5拒绝：距上次交易{last_trade}不足{P['cooldown_days']}天"}

    # ---- P0-4 组合级风控（仅开仓） ----
    warnings = []
    if action == "buy":
        # P0-3 R7 财报前规避
        avoid_days = P.get("avoid_earnings_days", 3)
        try:
            from ..event_sync import upcoming_events
            for ev in upcoming_events(db, ts_code, days=avoid_days):
                if ev["type"] in ("earnings", "earnings_forecast"):
                    return {"ok": False, "qty": 0,
                            "note": (f"R7拒绝：{ev['date']} 有{ev['detail'][:30]}，"
                                     f"财报前{avoid_days}日禁止开仓")}
        except Exception:  # noqa: BLE001 事件表缺数据不阻塞
            pass
        # 行业集中度
        value = account_value(db, account)
        if value > 0:
            from ...models import StockBasic
            industry_values: dict[str, float] = {}
            for p in db.scalars(select(SimPosition).where(
                    SimPosition.account_id == account.id)).all():
                last = db.scalar(select(DailyPrice.close).where(
                    DailyPrice.ts_code == p.ts_code)
                    .order_by(DailyPrice.trade_date.desc()).limit(1))
                px = float(last or 0)
                ind = db.scalar(select(StockBasic.industry).where(
                    StockBasic.ts_code == p.ts_code)) or "未知"
                industry_values[ind] = industry_values.get(ind, 0) + px * p.qty
            new_ind = db.scalar(select(StockBasic.industry).where(
                StockBasic.ts_code == ts_code)) or "未知"
            cur_ind_val = industry_values.get(new_ind, 0)
            new_pos_val = (price or 0) * 1000  # 待裁剪后精确算，先粗算1000股
            # 用目标仓位粗算：若买入后该行业占比超限 → 拒绝
            est_ind = cur_ind_val + value * min(target_pos_pct or P["max_pos_pct"],
                                                P["max_pos_pct"]) * (1 if new_ind in industry_values or cur_ind_val == 0 else 1)
            if cur_ind_val / value > P["max_industry_pct"] and new_ind in industry_values:
                return {"ok": False, "qty": 0,
                        "note": (f"R7拒绝：行业[{new_ind}]市值占比"
                                 f"{cur_ind_val / value:.0%}>{P['max_industry_pct']:.0%}，"
                                 f"禁止同行业加仓")}
            # R8 分散度告警（不拦截）
            n_hold = len(industry_values)
            if n_hold and n_hold < P["min_holdings"]:
                warnings.append(f"R8告警：持仓仅{n_hold}只（建议≥{P['min_holdings']}），集中度风险高")
        # R9 账户级熔断（独立阈值）
        pnl = _realized_pnls(db, account.id)
        equity, peak = float(account.initial_cash), float(account.initial_cash)
        for x in pnl:
            equity += x
            peak = max(peak, equity)
        peak = max(peak, account_value(db, account))
        value_now = account_value(db, account)
        acct_dd = (peak - value_now) / peak if peak > 0 else 0
        if acct_dd > P["account_drawdown_halt"]:
            return {"ok": False, "qty": 0,
                    "note": (f"R9拒绝：账户级回撤{acct_dd:.1%}>"
                             f"{P['account_drawdown_halt']:.0%}（组合熔断）")}

    # 仓位与数量裁剪
    if action == "hold":
        return {"ok": True, "qty": 0, "note": "hold"}
    position = db.scalar(select(SimPosition).where(
        SimPosition.account_id == account.id, SimPosition.ts_code == ts_code))
    held = position.qty if position else 0

    if action == "sell":
        if target_pos_pct is not None and target_pos_pct > 0 and price:
            # 减仓到目标仓位
            keep_value = account_value(db, account) * min(target_pos_pct, P["max_pos_pct"])
            keep_qty = int(keep_value / price / 100) * 100
            qty = max(0, held - keep_qty)
        else:
            qty = held
        qty = int(qty / 100) * 100
        if qty < 100:
            return {"ok": False, "qty": 0, "note": "卖出数量不足100股"}
        return {"ok": True, "qty": qty, "note": ("通过；" + ";".join(warnings)) if warnings else "通过"}

    # buy：目标仓位 × 信心度，且不超 R1 上限；扣减已持有市值
    conf = max(0.0, min(1.0, confidence or 0.6))
    value = account_value(db, account)
    tgt = min(target_pos_pct or P["max_pos_pct"], P["max_pos_pct"]) * conf
    budget = value * tgt - (held * (price or 0))
    if not price or budget <= 0:
        return {"ok": False, "qty": 0, "note": f"已达目标仓位（持有{held}股）"}
    qty = int(budget / price / 100) * 100
    if qty < 100:
        return {"ok": False, "qty": 0, "note": "可买金额不足100股"}
    # 现金校验
    cost = qty * price
    if cost > float(account.cash):
        qty = int(float(account.cash) / price / 100) * 100
        if qty < 100:
            return {"ok": False, "qty": 0, "note": "现金不足"}
    return {"ok": True, "qty": qty,
            "note": (f"通过（目标仓位{tgt:.0%}）" + ("；" + ";".join(warnings)) if warnings else "")}
