"""P0-7 每周投资周报：账户收益 + 最优/最差决策 + 风控拦截 + 待触发任务 + 下周事件
周日 19:00（学习笔记之后）执行，飞书 interactive 卡片推送"""
import datetime as dt
import logging

from sqlalchemy import select

from ..db import SessionLocal
from ..models import (AgentConfig, AgentDecision, SimAccount, WatchTask)

log = logging.getLogger(__name__)


def build_report() -> dict | None:
    db = SessionLocal()
    try:
        config = db.query(AgentConfig).first()
        if not config:
            return None
        account = db.get(SimAccount, config.account_id)
        week_ago = dt.date.today() - dt.timedelta(days=7)

        # 本周决策
        decisions = db.scalars(select(AgentDecision).where(
            AgentDecision.account_id == config.account_id,
            AgentDecision.run_date >= week_ago)
            .order_by(AgentDecision.id.desc())).all()
        executed = [d for d in decisions if d.status == "executed"]
        rejected = [d for d in decisions if d.status == "rejected_by_risk"]

        # 待触发任务
        waiting = db.scalars(select(WatchTask).where(
            WatchTask.status == "waiting").limit(10)).all()

        # 下周事件日历
        try:
            from ..event_sync import upcoming_events
            events = []
            for code in (config.stocks or [])[:3]:
                events.extend(upcoming_events(db, code, days=7))
        except Exception:  # noqa: BLE001
            events = []

        best = decisions[0] if decisions else None
        worst = decisions[-1] if len(decisions) > 1 else None

        return {
            "account_name": account.name if account else "Agent",
            "cash": float(account.cash) if account else 0,
            "initial": float(account.initial_cash) if account else 0,
            "decisions_total": len(decisions),
            "executed": len(executed),
            "rejected": len(rejected),
            "best": {"ts_code": best.ts_code, "action": best.action,
                     "reason": (best.reason or "")[:80]} if best else None,
            "waiting_tasks": [{"ts_code": t.ts_code, "detail": (t.condition_json or {}).get("desc", str(t.condition_json))}
                              for t in waiting[:5]],
            "events": events[:5],
        }
    finally:
        db.close()


def weekly_report():
    data = build_report()
    if not data:
        return False
    from .notify import notify_card

    # 飞书 interactive 卡片
    elements = [
        {"tag": "div", "text": {"tag": "lark_md",
                                "content": (f"**账户** {data['account_name']} ｜ "
                                            f"现金 {data['cash']:,.0f} / 初始 {data['initial']:,.0f}\n"
                                            f"**本周决策** {data['decisions_total']} 次"
                                            f"（执行 {data['executed']}｜风控拦截 {data['rejected']}）")}},
    ]
    if data["best"]:
        elements.append({"tag": "div", "text": {"tag": "lark_md",
                        "content": (f"**最近决策** {data['best']['ts_code']} {data['best']['action']}："
                                    f"{data['best']['reason']}")}})
    if data["waiting_tasks"]:
        task_lines = "\n".join(f"· {t['ts_code']}: {str(t['detail'])[:40]}" for t in data["waiting_tasks"])
        elements.append({"tag": "div", "text": {"tag": "lark_md",
                        "content": f"**待触发任务**\n{task_lines}"}})
    if data["events"]:
        ev_lines = "\n".join(f"· {e['date']} {e['detail'][:30]}" for e in data["events"])
        elements.append({"tag": "div", "text": {"tag": "lark_md",
                        "content": f"**下周事件**\n{ev_lines}"}})

    card = {
        "header": {"title": {"tag": "plain_text",
                             "content": f"📊 投资周报 {dt.date.today().isoformat()}"},
                   "template": "blue"},
        "elements": elements,
    }
    ok = notify_card(card)
    log.info("周报推送: %s", "成功" if ok else "失败/未配置")
    return ok
