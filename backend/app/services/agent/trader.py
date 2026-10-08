"""自主交易决策大脑：盘中轻量(intraday) + 收盘深度(daily)，风控闸门 + 执行 + 留痕"""
import datetime as dt
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy.orm import Session

from ...config import settings
from ...db import SessionLocal
from ...models import AgentConfig, AgentDecision, SimAccount, WatchTask
from ...services.deepseek_client import client as ds_client
from . import data as agent_data
from . import risk as risk_engine
from .executor import execute_agent_order

log = logging.getLogger(__name__)
JSON_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)

STYLE_PROFILES = {
    "steady": ("稳健型：低仓位（单票建议不超过15%总资产），高确信门槛（confidence<0.7倾向hold），"
               "只在多路证据一致时开仓，优先保住本金。"),
    "balanced": ("均衡型：单票建议不超过25%总资产，确信门槛中等（confidence<0.6倾向hold），"
                 "跟随证据强度调仓。"),
    "aggressive": ("激进型：可用满风控允许的仓位（上限30%），确信门槛低（confidence<0.5也可行动），"
                   "追求机会捕获，接受更高回撤。"),
}


def _parse_decision(content: str) -> dict | None:
    for block in reversed(JSON_RE.findall(content)):
        try:
            d = json.loads(block)
            if isinstance(d, dict) and d.get("action") in ("buy", "sell", "hold"):
                return d
        except Exception:  # noqa: BLE001
            continue
    return None


def _jsonable(obj):
    """递归把 Decimal/date 等转成 JSON 可序列化类型"""
    from decimal import Decimal
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    return obj


def _save_decision(db: Session, **kw) -> AgentDecision:
    if kw.get("inputs_snapshot") is not None:
        kw["inputs_snapshot"] = _jsonable(kw["inputs_snapshot"])
    d = AgentDecision(**kw)
    db.add(d)
    db.flush()
    return d


def _run_and_execute(db: Session, config: AgentConfig, account: SimAccount,
                     ts_code: str, decision: dict, analysis_md: str | None,
                     snapshot: dict, decision_type: str) -> AgentDecision:
    """风控 → 执行 → 留痕（共用）"""
    action = decision.get("action", "hold")
    price = (snapshot.get("realtime") or {}).get("price") or snapshot.get("latest_local_close")
    tgt = decision.get("target_pos_pct")
    conf = decision.get("confidence")
    try:
        tgt_f = float(tgt) if tgt is not None else None
    except (TypeError, ValueError):
        tgt_f = None
    try:
        conf_f = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf_f = None

    if action == "hold":
        return _save_decision(
            db, account_id=account.id, ts_code=ts_code, run_date=dt.date.today(),
            decision_type=decision_type, action="hold", status="hold",
            price=price, target_pos_pct=tgt_f,
            reason=str(decision.get("reason", ""))[:2000],
            thesis=str(decision.get("thesis", ""))[:4000],
            invalidation=decision.get("invalidation"),
            analysis_md=analysis_md, inputs_snapshot=snapshot)

    rc = risk_engine.check(db, config, account, ts_code, action, tgt_f, conf_f, price)
    if not rc["ok"]:
        return _save_decision(
            db, account_id=account.id, ts_code=ts_code, run_date=dt.date.today(),
            decision_type=decision_type, action=action, status="rejected_by_risk",
            price=price, target_pos_pct=tgt_f,
            risk_note=rc["note"],
            reason=str(decision.get("reason", ""))[:2000],
            thesis=str(decision.get("thesis", ""))[:4000],
            invalidation=decision.get("invalidation"),
            analysis_md=analysis_md, inputs_snapshot=snapshot)

    note = f"agent:{decision_type} {str(decision.get('reason', ''))[:150]}"
    res = execute_agent_order(db, account, ts_code, action, rc["qty"],
                              float(price), (snapshot.get("realtime") or {}).get("pre_close"),
                              note=note)
    if not res["ok"]:
        return _save_decision(
            db, account_id=account.id, ts_code=ts_code, run_date=dt.date.today(),
            decision_type=decision_type, action=action, status="failed",
            price=price, target_pos_pct=tgt_f,
            risk_note=f"执行失败: {res['error']}",
            reason=str(decision.get("reason", ""))[:2000],
            thesis=str(decision.get("thesis", ""))[:4000],
            invalidation=decision.get("invalidation"),
            analysis_md=analysis_md, inputs_snapshot=snapshot)

    trade = res["trade"]
    decision_row = _save_decision(
        db, account_id=account.id, ts_code=ts_code, run_date=dt.date.today(),
        decision_type=decision_type, action=action, status="executed",
        qty=trade.qty, price=float(trade.price), target_pos_pct=tgt_f,
        risk_note=rc["note"],
        reason=str(decision.get("reason", ""))[:2000],
        thesis=str(decision.get("thesis", ""))[:4000],
        invalidation=decision.get("invalidation"),
        analysis_md=analysis_md, inputs_snapshot=snapshot, trade_id=trade.id)

    # 🔴 重要通知：agent 执行了买卖（飞书 + 桌面事件总线）
    from ..services.notify import notify
    from ..services import event_bus
    event_bus.publish("agent_trade",
                      {"ts_code": ts_code, "action": action, "qty": trade.qty,
                       "price": float(trade.price),
                       "reason": str(decision.get("reason", ""))[:120]},
                      important=True)
    notify(f"Agent {action.upper()} {ts_code}",
           f"{trade.qty} 股 @ {float(trade.price)}（{decision_type}）\n"
           f"理由：{str(decision.get('reason', ''))[:120]}\n"
           f"信心度：{decision.get('confidence', '-')}", important=True)

    # thesis 失效条件自动建观察任务（R:invalidation 闭环）
    inv = decision.get("invalidation")
    if isinstance(inv, dict) and inv.get("kind") in ("price_below", "price_above"):
        try:
            db.add(WatchTask(
                ts_code=ts_code, source_report_id=None, task_type="price_level",
                condition_json={"kind": inv["kind"], "value": float(inv["value"])},
                expect_json={"expect": f"agent thesis 失效条件({decision_type}): {str(decision.get('thesis', ''))[:120]}"},
                status="waiting",
                expire_date=dt.date.today() + dt.timedelta(days=60)))
        except (TypeError, ValueError):
            pass
    return decision_row


def run_intraday(db: Session, config: AgentConfig, account: SimAccount, ts_code: str) -> dict:
    """盘中轻量决策（deepseek-chat，~3k token）"""
    snapshot = agent_data.aggregate(db, config, account, ts_code, deep=False)
    rt = snapshot["realtime"]
    pos = snapshot["position"]
    system = (
        "你是资深自主交易员的盘中巡逻模块。基于轻量快照快速判断：维持/加仓/减仓/清仓/观望。"
        f"风格：{STYLE_PROFILES.get(config.style, STYLE_PROFILES['steady'])}\n"
        "原则：盘中决策只处理明显机会或风险（如 thesis 失效、急涨急跌、重大新闻）；"
        "不确信必须 hold；无持仓时盘中一般不开新仓（等收盘深度决策）。\n"
        "末尾输出 ```json {\"action\":\"buy/sell/hold\",\"target_pos_pct\":0-1或null,"
        "\"confidence\":0-1,\"reason\":\"一句话\",\"thesis\":\"逻辑(买入/持有时)\","
        "\"invalidation\":{\"kind\":\"price_below/price_above\",\"value\":数字}或null}```"
    )
    user = (
        f"股票 {ts_code}\n实时: 现价{rt.get('price')} 涨跌{rt.get('pct_chg')}% "
        f"开{rt.get('open')} 高{rt.get('high')} 低{rt.get('low')} 昨收{rt.get('pre_close')}\n"
        f"持仓: {json.dumps(pos, ensure_ascii=False) if pos else '无'}\n"
        f"账户现金: {snapshot['account']['cash']:.0f}\n"
        f"近60日收盘序列:\n{snapshot['bars_text'][:1500]}\n"
        f"新闻标题: {snapshot.get('news_headlines')}\n"
        f"已触发观察: {json.dumps(snapshot.get('triggered_watch', []), ensure_ascii=False)}\n"
        f"参考策略信号: {json.dumps(snapshot.get('strategy_signals', []), ensure_ascii=False)}\n"
        f"近期决策: {json.dumps(snapshot.get('recent_decisions', []), ensure_ascii=False)}\n"
        f"学习提示: {snapshot.get('learning_notes', '无')}"
    )
    try:
        content = ds_client.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=settings.chat_model, temperature=0.3, max_tokens=1200)
    except Exception as e:  # noqa: BLE001
        d = _save_decision(db, account_id=account.id, ts_code=ts_code,
                           run_date=dt.date.today(), decision_type="intraday",
                           action="hold", status="failed", risk_note=f"LLM调用失败: {e}",
                           inputs_snapshot=snapshot)
        return {"decision_id": d.id, "action": "hold", "status": "failed"}
    decision = _parse_decision(content) or {"action": "hold", "reason": "决策json解析失败"}
    row = _run_and_execute(db, config, account, ts_code, decision,
                           analysis_md=content[:3000], snapshot=snapshot,
                           decision_type="intraday")
    db.commit()
    return {"decision_id": row.id, "action": row.action, "status": row.status,
            "qty": row.qty, "risk_note": row.risk_note}


def run_daily(db: Session, config: AgentConfig, account: SimAccount, ts_code: str) -> dict:
    """收盘全量深度决策：三子agent并行 → reasoner 决策"""
    snapshot = agent_data.aggregate(db, config, account, ts_code, deep=True)
    rt = snapshot["realtime"]
    pos = snapshot["position"]

    # 三子agent并行（复用 company_analysis 的子agent规格）
    from ..tushare_client import client as _  # noqa: F401 确认依赖可用
    from ...agents.company_analysis import SUB_AGENTS

    def sub(role: str) -> tuple[str, str]:
        spec = SUB_AGENTS[role]
        if role == "technical":
            u = (f"股票{ts_code} 现价{rt.get('price')}。近60日收盘序列:\n{snapshot['bars_text']}")
        elif role == "fundamental":
            u = (f"股票{ts_code}。财务快照:\n{snapshot['finance_text']}\n"
                 f"估值: {snapshot.get('valuation_text', '（无）')}\n"
                 f"当前持仓: {json.dumps(pos, ensure_ascii=False) if pos else '无'}")
        else:
            u = f"股票{ts_code}。近一月新闻:\n{snapshot['news_text']}"
        c = ds_client.chat(
            [{"role": "system", "content": spec["system"]}, {"role": "user", "content": u}],
            model=settings.chat_model, temperature=0.5, max_tokens=2000)
        return role, c

    sections: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        for role, content in pool.map(sub, ("technical", "fundamental", "sentiment")):
            sections[role] = content
    analysis = "\n\n".join(f"## {r}\n\n{sections[r]}" for r in sections)

    system = (
        "你是资深自主交易员，做今日收盘后的深度决策（明日执行视角，以当前实时/收盘价成交模拟）。"
        f"风格：{STYLE_PROFILES.get(config.style, STYLE_PROFILES['steady'])}\n"
        "综合三路分析与持仓状态决策 buy/sell/hold。要求 thesis 必须引用输入数据；"
        "不确信必须 hold；卖出需说明 thesis 变化。\n"
        "末尾输出 ```json {\"action\":\"buy/sell/hold\",\"target_pos_pct\":0-1,"
        "\"confidence\":0-1,\"reason\":\"一句话\",\"thesis\":\"完整逻辑\","
        "\"invalidation\":{\"kind\":\"price_below/price_above\",\"value\":数字}或null}```"
    )
    user = (
        f"股票 {ts_code}\n实时: {json.dumps(rt, ensure_ascii=False)}\n"
        f"持仓: {json.dumps(pos, ensure_ascii=False) if pos else '无'}\n"
        f"账户: {json.dumps(snapshot['account'])}\n"
        f"参考策略信号: {json.dumps(snapshot.get('strategy_signals', []), ensure_ascii=False)}\n"
        f"已触发观察: {json.dumps(snapshot.get('triggered_watch', []), ensure_ascii=False)}\n"
        f"近期决策: {json.dumps(snapshot.get('recent_decisions', []), ensure_ascii=False)}\n"
        f"学习提示: {snapshot.get('learning_notes', '无')}\n\n三路分析:\n{analysis}"
    )
    try:
        content = ds_client.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            model=settings.reasoner_model, max_tokens=4096)
    except Exception as e:  # noqa: BLE001
        d = _save_decision(db, account_id=account.id, ts_code=ts_code,
                           run_date=dt.date.today(), decision_type="daily",
                           action="hold", status="failed", risk_note=f"LLM调用失败: {e}",
                           analysis_md=analysis, inputs_snapshot=snapshot)
        db.commit()
        return {"decision_id": d.id, "action": "hold", "status": "failed"}

    decision = _parse_decision(content) or {"action": "hold", "reason": "决策json解析失败"}
    row = _run_and_execute(db, config, account, ts_code, decision,
                           analysis_md=analysis + "\n\n## 决策\n" + content,
                           snapshot=snapshot, decision_type="daily")
    db.commit()
    return {"decision_id": row.id, "action": row.action, "status": row.status,
            "qty": row.qty, "risk_note": row.risk_note}


def run_pool(decision_type: str = "intraday", ts_code: str | None = None) -> list[dict]:
    """调度入口：遍历 running 配置的股票池执行决策"""
    db = SessionLocal()
    out = []
    try:
        configs = db.query(AgentConfig).filter(AgentConfig.status == "running").all()
        for config in configs:
            account = db.get(SimAccount, config.account_id)
            if account is None:
                continue
            pool = [ts_code] if ts_code else (config.stocks or [])
            disabled = config.disabled_stocks or []
            for code in pool:
                if code not in (config.stocks or []):
                    continue
                if code in disabled:
                    continue  # 该股已停止巡盘
                try:
                    fn = run_intraday if decision_type == "intraday" else run_daily
                    r = fn(db, config, account, code)
                    out.append({"ts_code": code, **r})
                except Exception as e:  # noqa: BLE001
                    log.exception("agent 决策失败 %s", code)
                    out.append({"ts_code": code, "action": "hold", "status": "failed",
                                "error": str(e)[:150]})
        return out
    finally:
        db.close()
