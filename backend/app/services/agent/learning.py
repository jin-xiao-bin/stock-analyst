"""A4 学习闭环：每周对比 agent 决策 vs 参考策略表现 → 生成学习笔记注入决策 prompt"""
import datetime as dt
import json
import logging

from sqlalchemy import select

from ...config import settings
from ...db import SessionLocal
from ...models import AgentConfig, AgentDecision, SimAccount, SimTrade
from ...services.deepseek_client import client as ds_client

log = logging.getLogger(__name__)


def _collect(db) -> dict:
    """汇总学习素材：agent 已实现盈亏、决策统计、参考策略对比"""
    config = db.query(AgentConfig).first()
    if not config:
        return {}
    account = db.get(SimAccount, config.account_id)
    trades = db.scalars(select(SimTrade).where(
        SimTrade.account_id == config.account_id)
        .order_by(SimTrade.trade_date, SimTrade.id)).all()
    # 已实现盈亏（加权成本法，同 risk 模块口径）
    pnl: list[float] = []
    book: dict[str, tuple[int, float]] = {}
    for t in trades:
        q, avg = book.get(t.ts_code, (0, 0.0))
        if t.side == "buy":
            cost = avg * q + float(t.amount) + float(t.fee)
            book[t.ts_code] = (q + t.qty, cost / (q + t.qty))
        else:
            if q > 0:
                pnl.append(round((float(t.price) - avg) * t.qty - float(t.fee), 2))
            book[t.ts_code] = (max(0, q - t.qty), avg)

    decisions = db.scalars(select(AgentDecision).where(
        AgentDecision.account_id == config.account_id)
        .order_by(AgentDecision.id.desc()).limit(50)).all()
    stats = {"executed": 0, "hold": 0, "rejected_by_risk": 0, "failed": 0}
    rejected_notes: list[str] = []
    for d in decisions:
        if d.status in stats:
            stats[d.status] += 1
        if d.status == "rejected_by_risk" and d.risk_note:
            rejected_notes.append(f"{d.run_date} {d.action}被拒:{d.risk_note[:60]}")

    value = float(account.cash) if account else 0
    return {
        "realized_pnls": pnl,
        "decision_stats": stats,
        "recent_rejections": rejected_notes[:8],
        "current_cash": value,
        "initial": float(account.initial_cash) if account else 0,
        "style": config.style,
        "reference_strategies": config.reference_strategies or {},
    }


def weekly_learning() -> bool:
    """生成学习笔记写入 config.prompt_notes（决策时自动注入）"""
    db = SessionLocal()
    try:
        config = db.query(AgentConfig).first()
        if not config:
            return False
        material = _collect(db)
        if not material:
            return False
        system = (
            "你是交易行为复盘教练。根据自主交易agent的近期决策统计、已实现盈亏和风控拒绝记录，"
            "输出不超过5条、总计300字以内的行为改进笔记（直接给agent看）。"
            "要求：具体可执行（如'连续X次盘中开仓被风控拒绝，应更倾向等待收盘深度决策'），"
            "基于数据不空谈，用分号分隔条目，不要标题。"
        )
        try:
            notes = ds_client.chat(
                [{"role": "system", "content": system},
                 {"role": "user", "content": json.dumps(material, ensure_ascii=False)}],
                model=settings.chat_model, temperature=0.4, max_tokens=600)
        except Exception as e:  # noqa: BLE001
            log.warning("学习笔记生成失败: %s", e)
            return False
        config.prompt_notes = f"[{dt.date.today().isoformat()}周复盘] " + notes.strip()[:1500]
        db.commit()
        log.info("agent 学习笔记已更新(%d字)", len(config.prompt_notes))
        # 普通级飞书通知：学习笔记更新
        try:
            from ..services.notify import notify
            notify("Agent 周学习笔记已更新", f"下次决策将注入以下经验（{len(config.prompt_notes)}字）：\n"
                  f"{notes.strip()[:400]}")
        except Exception:  # noqa: BLE001
            pass
        return True
    finally:
        db.close()
