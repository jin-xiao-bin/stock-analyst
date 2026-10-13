"""飞书指令通道：长连接接收消息 → 指令解析 → 执行（同风控）→ 回复卡片/文本
支持指令：
  帮助
  状态
  买入 {代码} [数量股 | 百分比%]     （缺省按目标仓位20%由风控计算）
  卖出 {代码} [全部 | 数量股]
  决策 {代码} [深度]                 （触发一次决策，异步完成后推通知）
  清仓
  停止巡逻 {代码} / 开始巡逻 {代码}
  任务                               （已触发的观察任务）
"""
import datetime as dt
import json
import logging
import threading

import httpx

from ..config import settings

log = logging.getLogger(__name__)

_tenant_token_cache: dict = {}  # {"token":..., "expire": ts}


def _tenant_token() -> str | None:
    import time
    now = time.time()
    if _tenant_token_cache.get("expire", 0) > now + 60:
        return _tenant_token_cache["token"]
    try:
        r = httpx.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                       json={"app_id": settings.feishu_app_id,
                             "app_secret": settings.feishu_app_secret}, timeout=10)
        d = r.json()
        if d.get("code") != 0:
            log.warning("获取 tenant_access_token 失败: %s", d)
            return None
        _tenant_token_cache["token"] = d["tenant_access_token"]
        _tenant_token_cache["expire"] = now + int(d.get("expire", 3600)) - 120
        return _tenant_token_cache["token"]
    except Exception as e:  # noqa: BLE001
        log.warning("tenant token 请求异常: %s", e)
        return None


def reply(chat_id: str, text: str):
    """向会话回复文本消息"""
    token = _tenant_token()
    if not token:
        return
    try:
        httpx.post(
            "https://open.feishu.cn/open-apis/im/v1/messages",
            params={"receive_id_type": "chat_id"},
            headers={"Authorization": f"Bearer {token}"},
            json={"receive_id": chat_id, "msg_type": "text",
                  "content": json.dumps({"text": text}, ensure_ascii=False)},
            timeout=10)
    except Exception as e:  # noqa: BLE001
        log.warning("飞书回复失败: %s", e)


# ---------------- 指令执行（开独立会话，线程安全） ----------------

def _cmd_status_for(account_id: int | None = None) -> str:
    """状态查询（可指定个人账户；默认基金账户）"""
    from ..db import SessionLocal
    from ..models import AgentConfig, SimAccount, SimPosition
    from .agent import risk as risk_engine
    db = SessionLocal()
    try:
        if account_id:
            acc = db.get(SimAccount, account_id)
            if not acc:
                return f"账户#{account_id} 不存在"
            value = risk_engine.account_value(db, acc)
            positions = db.scalars(select(SimPosition).where(
                SimPosition.account_id == account_id)).all()
            pl = "；".join(f"{p.ts_code} {p.qty}股@{p.avg_cost}" for p in positions) or "空仓"
            return (f"我的账户 #{account_id} {acc.name}\n"
                    f"总资产：{value:.0f}（初始 {float(acc.initial_cash):.0f}）\n"
                    f"现金：{float(acc.cash):.0f}｜持仓：{pl}")
        # 基金账户（admin 默认）
        c = db.query(AgentConfig).first()
        if not c:
            return "尚未配置自主交易"
        acc = db.get(SimAccount, c.account_id)
        value = risk_engine.account_value(db, acc)
        positions = db.scalars(select(SimPosition).where(
            SimPosition.account_id == c.account_id)).all()
        pl = "；".join(f"{p.ts_code} {p.qty}股@{p.avg_cost}" for p in positions) or "空仓"
        return (f"基金账户状态：{c.status}｜风格：{c.style}｜巡逻：{c.patrol_freq}分钟\n"
                f"总资产：{value:.0f}（初始 {float(acc.initial_cash):.0f}）\n"
                f"现金：{float(acc.cash):.0f}｜持仓：{pl}\n股票池：{'、'.join(c.stocks or [])}")
    finally:
        db.close()


from sqlalchemy import select  # noqa: E402


def _cmd_decide(code: str, deep: bool) -> str:
    from ..db import SessionLocal
    from ..models import AgentConfig, SimAccount
    from .agent.trader import run_intraday, run_daily
    db = SessionLocal()
    try:
        c = db.query(AgentConfig).first()
        if not c:
            return "尚未配置自主交易"
        acc = db.get(SimAccount, c.account_id)
        fn = run_daily if deep else run_intraday
        r = fn(db, c, acc, code)
        if r["status"] == "executed":
            return f"决策完成：{r['action']} {r['qty']} 股"
        if r["status"] == "rejected_by_risk":
            return f"决策被风控拒绝：{r.get('risk_note')}"
        return f"决策完成：{r['action']}（{r['status']}）"
    finally:
        db.close()


def _cmd_trade(action: str, code: str, qty: int | None, pct: float | None,
               account_id: int | None = None) -> str:
    """交易指令（可指定账户，默认基金账户）"""
    from ..db import SessionLocal
    from ..models import AgentConfig, SimAccount
    from .realtime import get_realtime
    from .agent.executor import execute_agent_order
    from .agent import risk as risk_engine
    db = SessionLocal()
    try:
        if account_id:
            acc = db.get(SimAccount, account_id)
        else:
            c = db.query(AgentConfig).first()
            acc = db.get(SimAccount, c.account_id) if c else None
        if not acc:
            return "未找到账户"
        rt = get_realtime(code) or {}
        price = rt.get("price")
        if not price:
            return f"获取 {code} 实时价失败，无法成交"
        if action == "sell" and qty is None:
            qty = None  # 全部
        if qty is None:
            # 个人账户不走风控闸门（手动指令用户自担）；基金账户走
            if account_id is None:
                rc = risk_engine.check(db, c, acc, code, action, pct, 1.0, price)
                if not rc["ok"]:
                    return f"风控拒绝：{rc['note']}"
                qty = rc["qty"]
            else:
                # 个人账户：买入按金额比例，卖出全部
                if action == "buy":
                    budget = float(acc.cash) * (pct or 0.2)
                    qty = int(budget / float(price) / 100) * 100
                else:
                    pos = db.scalar(select(SimPosition).where(
                        SimPosition.account_id == acc.id, SimPosition.ts_code == code))
                    qty = pos.qty if pos else 0
        res = execute_agent_order(db, acc, code, action, qty, float(price),
                                  rt.get("pre_close"), note="agent:feishu_cmd")
        if not res["ok"]:
            return f"执行失败：{res['error']}"
        t = res["trade"]
        # 留痕
        from ..models import AgentDecision
        db.add(AgentDecision(
            account_id=acc.id, ts_code=code, run_date=dt.date.today(),
            decision_type="intraday", action=action, status="executed",
            qty=qty, price=float(t.price), risk_note="飞书指令",
            reason="飞书手动指令", inputs_snapshot={"chat_command": True},
            trade_id=t.id))
        db.commit()
        return f"已{('买入' if action == 'buy' else '卖出')} {qty} 股 {code} @ {float(t.price)}（费用 {t.fee}）"
    finally:
        db.close()


def _cmd_toggle(code: str, disable: bool) -> str:
    from ..db import SessionLocal
    from ..models import AgentConfig
    db = SessionLocal()
    try:
        c = db.query(AgentConfig).first()
        if not c:
            return "尚未配置"
        disabled = list(c.disabled_stocks or [])
        if disable and code not in disabled:
            disabled.append(code)
        elif not disable and code in disabled:
            disabled.remove(code)
        c.disabled_stocks = disabled
        db.commit()
        return f"{code} 巡盘已{'停止' if disable else '开启'}"
    finally:
        db.close()


def handle_text(text: str, chat_id: str, open_id: str = ""):
    """鉴权 → 解析指令 → 按角色路由执行 → 审计；返回回复文本"""
    from . import feishu_auth as auth

    t = text.strip().replace("@_user_1", "").strip()

    # ---- 鉴权 ----
    user = auth.get_user_by_open_id(open_id) if open_id else None
    # ---- 鉴权前的免鉴权指令 ----
    if t == "我的ID":
        return f"您的 open_id：\n{open_id}\n\n请将此 ID 发给管理员，在飞书群里执行：\n添加用户 {open_id} 您的昵称 trader"

    if user is None:
        # 未注册用户：自动回复其 open_id，方便发给管理员开通
        if t in ("帮助", "help", "Help"):
            return ("⛔ 您尚未授权使用本机器人。\n"
                    f"您的 open_id：{open_id}\n"
                    "请将此 ID 发给管理员，管理员在群里执行：\n"
                    f"添加用户 {open_id} 您的名字 trader")
        auth.log_operation(None, "unauthorized", {"text": t[:100], "open_id": open_id})
        return (f"⛔ 未授权用户，请联系管理员开通。\n"
                f"您的 open_id（发给管理员）：{open_id}")

    role = user.role
    try:
        # ---- admin 专属：用户管理 ----
        if t == "用户列表":
            if not auth.can_manage_users(user):
                return "⛔ 仅 admin 可管理用户"
            result = auth.list_users()
            auth.log_operation(user, "list_users")
            return result

        if t.startswith("添加用户"):
            if not auth.can_manage_users(user):
                return "⛔ 仅 admin 可添加用户"
            # 添加用户 <open_id> <名> [角色] [初始资金]  — 角色缺省=trader（可交易）
            parts = t.split()
            if len(parts) < 3:
                return "用法：添加用户 <open_id> <名字> [trader/viewer/admin] [初始资金]"
            open_id_new = parts[1]
            name_new = parts[2]
            role_new = parts[3] if len(parts) > 3 and parts[3] in ("admin", "trader", "viewer") else "trader"
            cash = float(parts[4]) if len(parts) > 4 else 100_000
            _, msg = auth.create_user(open_id_new, name_new, role_new, cash)
            auth.log_operation(user, "add_user", {"open_id": open_id_new, "role": role_new})
            return msg

        if t.startswith("删除用户"):
            if not auth.can_manage_users(user):
                return "⛔ 仅 admin 可删除用户"
            parts = t.split()
            if len(parts) < 2:
                return "用法：删除用户 <id>"
            msg = auth.block_user(int(parts[1]))
            auth.log_operation(user, "block_user", {"target_id": parts[1]})
            return msg

        if t.startswith("设角色"):
            if not auth.can_manage_users(user):
                return "⛔ 仅 admin 可设置角色"
            parts = t.split()
            if len(parts) < 3:
                return "用法：设角色 <id> <admin/trader/viewer>"
            msg = auth.set_role(int(parts[1]), parts[2])
            auth.log_operation(user, "set_role", {"target_id": parts[1], "role": parts[2]})
            return msg

        # ---- 通用 ----
        if t in ("帮助", "help", "Help"):
            help_text = "指令集：\n买入 000001 1000股｜买入 000001 20%\n卖出 000001 全部\n状态｜任务\n"
            if role == "admin":
                help_text += ("决策 000001 [深度]\n清仓｜停止巡逻 000001｜开始巡逻 000001\n"
                              "用户列表｜添加用户 <open_id> <名字> [trader] [资金]\n"
                              "删除用户 <id>｜设角色 <id> <角色>")
            elif role == "viewer":
                help_text = "（您的角色为 viewer：只能查询和消息分析，不能交易）"
            return help_text

        if t in ("状态",):
            account_id = auth.get_trading_account_id(user)
            result = _cmd_status_for(account_id)
            auth.log_operation(user, "status", account_id=account_id)
            return result

        if t == "任务":
            result = _cmd_tasks()
            auth.log_operation(user, "tasks")
            return result

        # ---- admin 专属：巡逻/决策 ----
        if t.startswith(("停止巡逻", "开始巡逻")):
            if role != "admin":
                return "⛔ 仅 admin 可控制巡逻"
            parts = t.split()
            result = _cmd_toggle(parts[1], t.startswith("停止")) if len(parts) > 1 else "缺代码"
            auth.log_operation(user, "toggle_patrol", {"text": t[:50]})
            return result

        if t.startswith("决策"):
            if not auth.can_trigger_decision(user):
                return "⛔ 仅 admin 可触发决策"
            parts = t.split()
            if len(parts) < 2:
                return "用法：决策 000001 [深度]"
            deep = "深度" in t
            reply(chat_id, f"开始执行{'收盘深度' if deep else '盘中'}决策 {parts[1]}，完成后推送结果…")
            auth.log_operation(user, "decision", {"code": parts[1], "deep": deep})
            threading.Thread(target=lambda: reply(chat_id, _cmd_decide(parts[1], deep)),
                             daemon=True).start()
            return None

        # ---- 交易指令（admin + trader）----
        if t.startswith(("买入", "卖出")):
            if not auth.can_trade(user):
                auth.log_operation(user, "trade_denied", {"text": t[:50]})
                return "⛔ 您的角色无交易权限"

            action = "buy" if t.startswith("买入") else "sell"
            toks = t[2:].strip().split()
            if not toks:
                return "用法：买入/卖出 601689 [1000股|20%|全部]（缺省时买入按风控仓位、卖出全部）"
            code = toks[0]
            spec = toks[1] if len(toks) > 1 else None
            qty = pct = None
            if spec is None:
                pass
            elif spec.replace("股", "").isdigit():
                qty = int(spec.replace("股", ""))
            elif spec.endswith("%"):
                pct = float(spec[:-1]) / 100
            elif action == "sell" and spec in ("全部", "all"):
                qty = None
            else:
                return "数量格式不对，示例：买入 601689 1000股 / 卖出 601689 20%"

            from ..utils import resolve_ts_code
            from ..db import SessionLocal
            db = SessionLocal()
            try:
                code = resolve_ts_code(db, code) or code
            finally:
                db.close()

            # 路由到操作者的账户
            account_id = auth.get_trading_account_id(user)
            if not account_id:
                return "⛔ 未找到可交易的账户，请联系管理员"
            result = _cmd_trade(action, code, qty, pct, account_id=account_id)
            auth.log_operation(user, f"{action}",
                               {"code": code, "qty": qty, "pct": pct,
                                "result": str(result)[:100]},
                               account_id=account_id)
            return result

        if t == "清仓":
            if not auth.can_trade(user):
                return "⛔ 您的角色无清仓权限"
            account_id = auth.get_trading_account_id(user)
            result = _cmd_force_close(account_id=account_id)
            auth.log_operation(user, "force_close", account_id=account_id)
            return result

        # ---- 自由对话（所有已授权角色）----
        auth.log_operation(user, "chat", {"text_len": len(t)})
        return None  # → 走 _cmd_chat

    except Exception as e:  # noqa: BLE001
        log.exception("飞书指令处理失败: %s", t)
        return f"指令执行出错：{e}"


def _cmd_chat(text: str, chat_id: str):
    """自由文本：LLM 结合实时行情/持仓/新闻做分析或问答（异步）"""
    import re as _re

    def _job():
        try:
            from ..db import SessionLocal
            from ..models import AgentConfig, SimPosition
            from .realtime import get_realtime
            from . import news_source
            from .deepseek_client import client as ds_client
            from ..config import settings

            codes = _re.findall(r"\d{6}", text)
            rt_lines, news_lines = [], []
            db = SessionLocal()
            try:
                config = db.query(AgentConfig).first()
                pool_codes = (config.stocks if config else None) or []
                for code in (codes or pool_codes)[:2]:
                    full = code if "." in code else (code + (".SH" if code[0] in "69" else ".BJ" if code[0] in "48" else ".SZ"))
                    rt = get_realtime(full)
                    if rt and rt.get("price"):
                        rt_lines.append(f"{full} 现价{rt['price']} 涨跌{rt.get('pct_chg')}%")
                    news = news_source.verify_search(f"{full} 最新", count=3)
                    news_lines += [f"- {n['title']}" for n in news]
            finally:
                db.close()

            pos_text = "无"
            db = SessionLocal()
            try:
                config = db.query(AgentConfig).first()
                if config:
                    positions = db.scalars(select(SimPosition).where(
                        SimPosition.account_id == config.account_id)).all()
                    pos_text = "；".join(f"{p.ts_code} {p.qty}股@{p.avg_cost}" for p in positions) or "无"
            finally:
                db.close()

            system = (
                "你是股票研究助手。用户可能贴来一条新闻/消息让你分析利弊，或提问股票/持仓问题。"
                "结合提供的实时行情、当前持仓与相关新闻，输出：利（2-3点）、弊（2-3点）、"
                "对持仓的影响与简要建议。仅研究参考，不构成投资建议。中文回答，简洁分点。"
            )
            user = (f"用户消息：{text}\n\n"
                    f"相关实时行情：{chr(10).join(rt_lines) or '（未识别到股票代码）'}\n"
                    f"相关新闻：{chr(10).join(news_lines) or '（无）'}\n"
                    f"当前持仓：{pos_text}")
            answer = ds_client.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                model=settings.chat_model, max_tokens=1500)
            reply(chat_id, answer)
        except Exception as e:  # noqa: BLE001
            log.exception("自由对话失败")
            reply(chat_id, f"分析失败：{e}")

    reply(chat_id, "收到，分析中…（约10-30秒）")
    threading.Thread(target=_job, name="feishu-chat", daemon=True).start()


def _cmd_force_close(account_id: int | None = None) -> str:
    from ..db import SessionLocal
    from ..models import AgentConfig, SimAccount, SimPosition
    from .realtime import get_realtime
    from .agent.executor import execute_agent_order
    db = SessionLocal()
    try:
        if account_id:
            acc = db.get(SimAccount, account_id)
        else:
            c = db.query(AgentConfig).first()
            acc = db.get(SimAccount, c.account_id) if c else None
        if not acc:
            return "未找到账户"
        out = []
        for p in db.scalars(select(SimPosition).where(
                SimPosition.account_id == acc.id)).all():
            rt = get_realtime(p.ts_code) or {}
            px = rt.get("price")
            if not px:
                out.append(f"{p.ts_code} 获取实时价失败")
                continue
            res = execute_agent_order(db, acc, p.ts_code, "sell", p.qty,
                                      float(px), rt.get("pre_close"), note="agent:feishu清仓")
            db.commit()
            out.append(f"{p.ts_code} {'已清仓' if res['ok'] else '失败:' + res['error']}")
        return "；".join(out) or "无持仓"
    finally:
        db.close()


def _cmd_tasks() -> str:
    from ..db import SessionLocal
    from ..models import WatchTask
    db = SessionLocal()
    try:
        rows = db.scalars(select(WatchTask).where(
            WatchTask.status == "triggered")
            .order_by(WatchTask.trigger_date.desc()).limit(5)).all()
        if not rows:
            return "近 5 条：无已触发任务"
        return "\n".join(f"{t.trigger_date} {t.ts_code}: {t.trigger_detail}" for t in rows)
    finally:
        db.close()


# ---------------- 长连接客户端 ----------------

def start_ws_client():
    """启动飞书长连接（阻塞式，须放入后台线程）。未配置则跳过。"""
    if not settings.feishu_app_id or not settings.feishu_app_secret:
        log.info("飞书自建应用未配置，指令通道不启动")
        return

    def _do_start():
        import time
        import lark_oapi as lark
        from lark_oapi.api.im.v1 import P2ImMessageReceiveV1

        def on_message(data: P2ImMessageReceiveV1) -> None:
            try:
                msg = data.event.message
                if msg.message_type != "text":
                    return
                content = json.loads(msg.content)
                text = content.get("text", "")
                chat_id = msg.chat_id
                # 提取发送者 open_id（鉴权标识）
                try:
                    open_id = data.event.sender.sender_id.open_id or ""
                except Exception:  # noqa: BLE001
                    open_id = ""
                log.info("飞书消息到达: chat=%s open_id=%s text=%r",
                         chat_id, open_id, text[:80])
                reply_text = handle_text(text, chat_id, open_id)
                if reply_text:
                    reply(chat_id, reply_text)
                else:
                    # 非指令文本 → 自由对话/消息利弊分析
                    _cmd_chat(text, chat_id)
            except Exception:  # noqa: BLE001
                log.exception("飞书消息处理异常")

        while True:  # 断线自动重连
            try:
                handler = (lark.EventDispatcherHandler.builder("", "")
                           .register_p2_im_message_receive_v1(on_message).build())
                client = lark.ws.Client(settings.feishu_app_id, settings.feishu_app_secret,
                                        event_handler=handler,
                                        log_level=lark.LogLevel.WARNING)
                log.info("飞书指令通道已启动（长连接）")
                client.start()
                log.warning("飞书长连接断开，15 秒后重连")
            except Exception:  # noqa: BLE001
                log.exception("飞书长连接启动失败，15 秒后重连")
            time.sleep(15)

    threading.Thread(target=_do_start, name="feishu-ws", daemon=True).start()
