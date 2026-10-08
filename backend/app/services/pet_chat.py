"""桌面宠物对话：自然语言问答(LLM) + 交易指令解析（指令过风控，买入需二次确认）"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import AgentConfig, SimAccount, SimPosition
from ..services.realtime import get_realtime

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pet", tags=["pet"])

COMMANDS_HINT = (
    "可用指令：买入 <代码> [数量]｜卖出 <代码> 全部|数量｜决策 <代码>｜状态｜清仓｜"
    "开始巡逻 <代码>｜停止巡逻 <代码>｜行情 <代码>｜任务｜帮助"
)


def _agent_ctx(db: Session) -> tuple[AgentConfig, SimAccount] | tuple[None, None]:
    config = db.query(AgentConfig).first()
    if config is None:
        return None, None
    account = db.get(SimAccount, config.account_id)
    return config, account


def _parse_command(text: str) -> dict | None:
    """解析交易指令。返回 {cmd, ...} 或 None（非指令）"""
    import re
    t = text.strip()
    t = re.sub(r"[，。！？!?.]", "", t)
    code_m = re.search(r"(\d{6})", t)
    code = code_m.group(1) if code_m else None

    if t.startswith("买入") or t.startswith("买") and code:
        qty = None
        qm = re.search(r"(\d{3,})(?:股|手)?", t.replace("买入", "", 1))
        if qm:
            n = int(qm.group(1))
            qty = n if n >= 100 else n * 100
        return {"cmd": "buy", "code": code, "qty": qty}
    if t.startswith("卖出") or t.startswith("卖") and code:
        all_flag = "全部" in t or "清仓" in t
        qty = None
        qm = re.search(r"(\d{3,})", t)
        if qm:
            n = int(qm.group(1))
            qty = n if n >= 100 else n * 100
        return {"cmd": "sell", "code": code, "qty": None if all_flag else qty, "all": all_flag}
    if t.startswith("决策"):
        return {"cmd": "decision", "code": code}
    if t in ("状态",):
        return {"cmd": "status"}
    if t in ("清仓",):
        return {"cmd": "close_all"}
    if t.startswith("开始巡逻"):
        return {"cmd": "patrol_on", "code": code}
    if t.startswith("停止巡逻"):
        return {"cmd": "patrol_off", "code": code}
    if t.startswith("行情"):
        return {"cmd": "quote", "code": code}
    if t in ("帮助", "指令"):
        return {"cmd": "help"}
    return None


def _fmt_quote(code: str, db: Session) -> str:
    from ..services.realtime import get_realtime
    rt = get_realtime(code) or {}
    if rt.get("price") is None:
        return f"{code} 暂无实时数据"
    return (f"{rt.get('name', code)} 现价 {rt['price']}（{rt.get('pct_chg', 0):+.2f}%）"
            f" 开{rt.get('open')} 高{rt.get('high')} 低{rt.get('low')}")


@router.post("/chat")
def chat(body: dict, db: Session = Depends(get_db)):
    text = str(body.get("text", "")).strip()
    confirmed = bool(body.get("confirm"))

    # ===== 确认流 =====
    if confirmed:
        cmd = _parse_command(text)
        if cmd and cmd["cmd"] in ("buy", "sell"):
            if cmd.get("code"):
                from ..utils import resolve_ts_code
                code = resolve_ts_code(db, cmd["code"])
                if code is None:
                    return {"type": "text", "text": f"股票代码 {cmd['code']} 不存在。"}
                cmd["code"] = code
            return _exec_trade(db, cmd, confirmed=True)
        return {"type": "text", "text": "确认已过期，请重新发送指令。"}

    # ===== 指令解析 =====
    cmd = _parse_command(text)
    if cmd is None:
        return _llm_chat(db, text)

    config, account = _agent_ctx(db)
    if cmd["cmd"] in ("buy", "sell") and account is None:
        return {"type": "text", "text": "尚未配置自主决策账户，请先在「自主决策」页 setup。"}

    from ..utils import resolve_ts_code
    if cmd.get("code"):
        resolved = resolve_ts_code(db, cmd["code"])
        if resolved is None:
            return {"type": "text", "text": f"股票代码 {cmd['code']} 不存在，请检查。"}
        cmd["code"] = resolved

    if cmd["cmd"] == "status":
        return _status_reply(db)
    if cmd["cmd"] == "quote":
        if not cmd.get("code"):
            return {"type": "text", "text": "请带上代码，如：行情 000001"}
        return {"type": "text", "text": _fmt_quote(cmd["code"], db)}
    if cmd["cmd"] == "help":
        return {"type": "text", "text": COMMANDS_HINT}
    if cmd["cmd"] == "patrol_on":
        return _patrol_toggle(db, cmd["code"], enable=True)
    if cmd["cmd"] == "patrol_off":
        return _patrol_toggle(db, cmd["code"], enable=False)

    if cmd["cmd"] in ("buy", "sell"):
        return _exec_trade(db, cmd, confirmed=confirmed)

    if cmd["cmd"] == "decision":
        # 触发深度决策（同步，较慢）
        from ..services.agent.trader import run_daily
        config2, account2 = _agent_ctx(db)
        if config2 is None:
            return {"type": "text", "text": "尚未配置自主决策账户。"}
        r = run_daily(db, config2, account2, cmd["code"])
        return {"type": "text",
                "text": f"决策完成：{r['action']}（{r['status']}）{('数量' + str(r['qty'])) if r.get('qty') else ''}"}

    if cmd["cmd"] == "close_all":
        from ..services.agent.trader import run_pool  # noqa: F401 占位，实际走强制清仓
        return {"type": "text",
                "text": "清仓请在「自主决策」页点「强制清仓」（涉及全部持仓，需在页面二次确认）。"}

    return {"type": "text", "text": "未识别的指令。\n" + COMMANDS_HINT}


def _patrol_toggle(db: Session, code: str, enable: bool) -> dict:
    if not code:
        return {"type": "text", "text": "请带上代码，如：停止巡逻 000001"}
    config = db.query(AgentConfig).first()
    if config is None or code not in (config.stocks or []):
        return {"type": "text", "text": f"{code} 不在追踪池中。"}
    disabled = list(config.disabled_stocks or [])
    if enable:
        disabled = [c for c in disabled if c != code]
        config.disabled_stocks = disabled
        db.commit()
        return {"type": "text", "text": f"{code} 已开启巡盘。"}
    disabled.append(code)
    config.disabled_stocks = disabled
    db.commit()
    return {"type": "text", "text": f"{code} 已停止巡盘。"}


def _status_reply(db: Session) -> dict:
    config, account = _agent_ctx(db)
    if config is None:
        return {"type": "text", "text": "尚未配置自主决策账户。"}
    from ..services.agent import risk as risk_engine
    value = risk_engine.account_value(db, account)
    positions = db.scalars(
        select(SimPosition).where(SimPosition.account_id == config.account_id)).all()
    pos_text = "；".join(
        f"{p.ts_code} {p.qty}股 成本{p.avg_cost}" for p in positions) or "无持仓"
    return {"type": "text",
            "text": (f"账户#{config.account_id}（{config.status}）总资产 {value:.0f}"
                     f"（初始 {float(account.initial_cash):.0f}）\n持仓：{pos_text}")}


def _exec_trade(db: Session, cmd: dict, confirmed: bool) -> dict:
    """交易指令：首次返回待确认；confirm=True 才执行（走风控+实时价成交）"""
    from ..services.agent.executor import execute_agent_order
    config, account = _agent_ctx(db)
    if account is None:
        return {"type": "text", "text": "尚未配置自主决策账户，请先在「自主决策」页 setup。"}
    if cmd["code"] not in (config.stocks or []):
        return {"type": "text", "text": f"{cmd['code']} 不在追踪股票池（R6），请在配置中先添加。"}

    from ..services.realtime import get_realtime
    rt = get_realtime(cmd["code"]) or {}
    price = rt.get("price")
    if price is None:
        return {"type": "text", "text": "暂无实时价格，无法成交。"}

    from ..services.agent import risk as risk_engine
    from ..models import SimPosition  # noqa: F401
    action = "buy" if cmd["cmd"] == "buy" else "sell"
    pos = db.scalar(
        select(SimPosition).where(
            SimPosition.account_id == account.id, SimPosition.ts_code == cmd["code"]))
    held = pos.qty if pos else 0
    target_pct = None

    if action == "buy":
        qty = cmd.get("qty")
        if not qty:
            # 未指定数量：按目标仓位 20% 估算
            from ..services.agent import risk as r2
            value = r2.account_value(db, account)
            qty = int(value * 0.20 / price / 100) * 100
        rc = risk_engine.check(db, config, account, cmd["code"], "buy",
                               None, 0.8, price)  # 用风控校验（数量由风控/指令取小）
        if not rc["ok"]:
            return {"type": "text", "text": f"⛔ 风控拒绝：{rc['note']}"}
        qty = min(qty, rc["qty"]) if rc["qty"] else qty
    else:
        if cmd.get("all"):
            qty = held
        elif cmd.get("qty"):
            qty = min(cmd["qty"], held)
        else:
            return {"type": "text", "text": "请指定卖出数量或「全部」。"}
        if qty < 100:
            return {"type": "text", "text": f"可卖数量不足（持有 {held}）。"}

    # ===== 二次确认 =====
    if not confirmed:
        verb = "买入" if action == "buy" else "卖出"
        return {"type": "text",
                "text": f"确认{verb} {cmd['code']} {qty} 股，按现价 {price} 成交？\n回复「确认」执行，"
                        f"「取消」放弃。",
                "pending_confirm": {"text": f"{verb} {cmd['code']} {qty}"}}

    res = execute_agent_order(db, account, cmd["code"], action, qty, float(price),
                              rt.get("pre_close"), note="agent:chat指令")
    if not res["ok"]:
        return {"type": "text", "text": f"执行失败：{res['error']}"}
    db.commit()
    t = res["trade"]
    return {"type": "text",
            "text": f"✅ 已{('买入' if action == 'buy' else '卖出')} {t.qty} 股 {cmd['code']}"
                    f" @ {float(t.price)}（费用 {t.fee}）"}


def _llm_chat(db: Session, text: str) -> dict:
    """非指令的自然语言：LLM 问答（附实时上下文）"""
    config, account = _agent_ctx(db)
    ctx = ""
    if config:
        pos = db.scalars(
            select(SimPosition).where(SimPosition.account_id == config.account_id)).all()
        pos_text = "；".join(f"{p.ts_code} {p.qty}股@{p.avg_cost}" for p in pos) or "无"
        ctx = f"（用户持仓：{pos_text}；账户现金 {float(account.cash):.0f}）"
    try:
        from ..services.deepseek_client import client as ds_client
        from ..config import settings
        reply = ds_client.chat(
            [{"role": "system",
              "content": "你是股票模拟交易助手（A股、日级+实时价数据）。简短回答用户问题，"
                         "涉及投资建议必须提醒仅供模拟研究。"},
             {"role": "user", "content": f"{text}\n{ctx}"}],
            model=settings.chat_model, max_tokens=500)
        return {"type": "text", "text": reply}
    except Exception as e:  # noqa: BLE001
        return {"type": "text", "text": f"LLM 调用失败：{e}"}
