"""策略中心 API（契约第4节）+ activate/deactivate（契约第7节）"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BacktestRun, Strategy, StrategyBinding, StrategyDiscussion
from ..services.backtest_engine import validate_strategy_code

router = APIRouter(prefix="/api/strategies", tags=["strategies"])

# ---------------- 策略对话（讨论 → AI出新码 → 人工确认应用为新版本） ----------------

STRATEGY_CHAT_SYSTEM = (
    "你是该量化策略的作者（资深量化工程师），正与策略使用者讨论这个策略。\n"
    "策略代码运行在受限沙箱，只能用以下 API：\n"
    "def init(ctx) / def on_bar(ctx, bar, i)\n"
    "ctx: .get(k)/.set(k,v)/.params/.close(i)/.open(i)/.high(i)/.low(i)/.volume(i)"
    "/.ema(p)/.ma(p)/.rsi(p)/.macd()({'dif','dea','hist'})/.crossover(a,b,i)/.crossunder(a,b,i)"
    "/.buy(ratio,reason)/.sell_all(reason)/.sell(qty,reason)/.position_qty/.cash/.bar_count\n"
    "bar: {date,open,high,low,close,volume}；指标在 on_bar 内调用（勿在 init 缓存）\n"
    "要求：解释设计逻辑时简洁专业；当用户要求修改策略时，先说明修改思路与预期影响，"
    "然后输出**完整的修改后代码**（一个 ```python 代码块，必须包含 init 和 on_bar，"
    "禁止 import/open/eval 等沙箱外操作）。不修改时不要输出代码块。中文回答。"
)


class StrategyCreate(BaseModel):
    name: str
    code: str
    description: str | None = None
    params: dict | None = None
    source: str = "manual"  # manual | import


class StrategyUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    description: str | None = None
    params: dict | None = None


class ValidateBody(BaseModel):
    code: str | None = None
    params: dict | None = None


class BindBody(BaseModel):
    account_id: int
    ts_codes: list[str]
    params: dict | None = None


class GenerateBody(BaseModel):
    prompt: str


class DiscussBody(BaseModel):
    content: str


class JqImportBody(BaseModel):
    code: str
    name: str | None = None


@router.post("/import-jq")
def import_jq(body: JqImportBody, db: Session = Depends(get_db)):
    """聚宽策略导入：Notebook/纯Python → 兼容层桥接 → 失败则LLM转换 → 校验入库"""
    from ..services import jq_adapter
    from ..services.backtest_engine import validate_strategy_code

    raw = (body.code or "").strip()
    if not raw:
        raise HTTPException(400, "代码为空")
    try:
        jq_code, fmt = jq_adapter.extract_code(raw)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if not jq_code.strip():
        raise HTTPException(400, "未从 Notebook 中抽取到代码 cell")

    name = (body.name or "聚宽导入策略").strip()
    warnings = []

    # 轨道1：兼容层确定性桥接
    wrapped = jq_adapter.build_wrapped(jq_code)
    v = validate_strategy_code(db, wrapped)
    mode = None
    final_code = None
    if v.get("ok"):
        mode, final_code = "shim", wrapped
        warnings.append("通过兼容层运行：聚宽API已自动桥接，订单作用于回测标的；"
                        "多股票选股逻辑已简化为单标的")
    else:
        # 轨道2：LLM 转换兜底（失败自动重试一轮）
        converted = jq_adapter.convert_via_llm(jq_code, str(v.get("error")))
        for _attempt in range(2):
            if not converted:
                break
            v2 = validate_strategy_code(db, converted)
            if v2.get("ok"):
                mode, final_code = "llm", converted
                break
            converted = jq_adapter.convert_via_llm(jq_code, str(v2.get("error")))
        if final_code is None:
            raise HTTPException(
                400, (f"聚宽策略适配失败（兼容层报错：{str(v.get('error'))[:150]}；"
                      f"LLM转换亦未通过校验）。多股票选股/组合类策略受单标的沙箱限制，"
                      f"请提炼单标的逻辑后用「AI生成策略」描述思路"))

    s = Strategy(
        name=name, source="import", code=final_code,
        description=(f"[聚宽适配-{mode}] 输入格式: {fmt}。" + "；".join(warnings)),
        status="draft")
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"strategy_id": s.id, "name": s.name, "mode": mode,
            "input_format": fmt, "warnings": warnings,
            "note": "建议先发起回测验证行为是否符合预期"}


def _strategy_context(db: Session, s: Strategy) -> str:
    """策略上下文：代码 + 参数 + 最近一次回测指标"""
    bt = db.scalar(select(BacktestRun).where(BacktestRun.strategy_id == s.id)
                   .order_by(BacktestRun.id.desc()).limit(1))
    bt_line = ""
    if bt and bt.metrics:
        m = bt.metrics
        bt_line = (f"\n最近回测({bt.start_date}~{bt.end_date})：收益{m.get('total_return'):.2%} "
                   f"最大回撤{m.get('max_drawdown'):.2%} 胜率{m.get('win_rate'):.1%} "
                   f"夏普{m.get('sharpe'):.2f} 交易{m.get('trade_count')}笔")
    return (f"策略：#{s.id} {s.name}（来源{s.source} 版本v{s.version_no}）\n"
            f"参数：{json.dumps(s.params or {}, ensure_ascii=False)}{bt_line}\n"
            f"当前代码：\n```python\n{s.code}\n```")


@router.get("/{sid}/discussion")
def get_strategy_discussion(sid: int, db: Session = Depends(get_db)):
    msgs = db.scalars(select(StrategyDiscussion).where(
        StrategyDiscussion.strategy_id == sid)
        .order_by(StrategyDiscussion.id)).all()
    return {"messages": [
        {"id": m.id, "role": m.role, "content": m.content,
         "proposed_code": m.proposed_code,
         "created_at": m.created_at.isoformat(timespec="minutes")} for m in msgs]}


@router.post("/{sid}/discussion")
def post_strategy_discussion(sid: int, req: DiscussBody, db: Session = Depends(get_db)):
    """用户发言 → AI 回应（代码+参数+最近回测+讨论历史上下文）→
    若给出新代码：沙箱校验（失败自动修复一次）→ 携带 proposed_code 返回"""
    s = db.get(Strategy, sid)
    if s is None:
        raise HTTPException(404, f"策略 {sid} 不存在")
    text = (req.content or "").strip()
    if not text:
        raise HTTPException(400, "内容为空")
    db.add(StrategyDiscussion(strategy_id=sid, role="user", content=text))
    db.commit()

    history = db.scalars(select(StrategyDiscussion).where(
        StrategyDiscussion.strategy_id == sid)
        .order_by(StrategyDiscussion.id)).all()
    dialogue = "\n".join(
        f"{'用户' if m.role == 'user' else 'AI'}：{m.content[:1500]}" for m in history)

    from ..config import settings
    from ..services.deepseek_client import client as ds_client
    try:
        reply = ds_client.chat(
            [{"role": "system", "content": STRATEGY_CHAT_SYSTEM},
             {"role": "user",
              "content": f"{_strategy_context(db, s)}\n\n=== 讨论记录 ===\n{dialogue}\n\n请回应最新一条用户发言。"}],
            model=settings.chat_model, temperature=0.4, max_tokens=2500)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI 回应失败: {e}") from e

    # 提取 ```python 代码块 → 沙箱校验（失败带错误让AI修复一次）
    import re
    proposed = None
    validation = None
    blocks = re.findall(r"```python\s*(.*?)\s*```", reply, re.DOTALL)
    if blocks:
        proposed = blocks[-1]
        vr = validate_strategy_code(db, proposed, s.params)
        if not vr.get("ok"):
            try:
                fix = ds_client.chat(
                    [{"role": "system", "content": STRATEGY_CHAT_SYSTEM},
                     {"role": "user",
                      "content": (f"{_strategy_context(db, s)}\n用户要求：{text}\n"
                                  f"你给出的代码未通过沙箱校验，错误：{vr.get('error')}\n"
                                  "请修复并重新输出完整代码（```python块）。")}],
                    model=settings.chat_model, temperature=0.2, max_tokens=2500)
                fix_blocks = re.findall(r"```python\s*(.*?)\s*```", fix, re.DOTALL)
                if fix_blocks:
                    proposed = fix_blocks[-1]
                    reply = reply + "\n\n---\n（已自动修复）\n" + fix
                    vr = validate_strategy_code(db, proposed, s.params)
            except Exception:  # noqa: BLE001
                pass
        validation = {"ok": vr.get("ok", False), "error": vr.get("error"),
                      "trial_trades": vr.get("trades")}

    msg = StrategyDiscussion(strategy_id=sid, role="assistant",
                             content=reply, proposed_code=proposed)
    db.add(msg)
    db.commit()
    return {"id": msg.id, "role": "assistant", "content": reply,
            "proposed_code": proposed, "validation": validation}


@router.post("/{sid}/discussion/{msg_id}/apply")
def apply_discussion_code(sid: int, msg_id: int, db: Session = Depends(get_db)):
    """人工确认：将讨论中的代码提案应用为新版本（版本链，旧版保留）"""
    s = db.get(Strategy, sid)
    msg = db.get(StrategyDiscussion, msg_id)
    if s is None or msg is None or msg.strategy_id != sid or not msg.proposed_code:
        raise HTTPException(404, "提案不存在")
    vr = validate_strategy_code(db, msg.proposed_code, s.params)
    if not vr.get("ok"):
        raise HTTPException(400, f"代码校验失败: {vr.get('error')}")
    # 找链头最新版本
    latest = db.scalar(select(Strategy).where(Strategy.parent_id == sid)
                       .order_by(Strategy.version_no.desc()).limit(1))
    base = latest or s
    note = (f"对话修改：依据与AI的讨论（消息#{msg_id}），"
            f"用户指令：{msg.content[:120]}")
    new = Strategy(name=s.name, source=s.source, code=msg.proposed_code,
                   description=s.description, params=s.params,
                   parent_id=base.id if latest else s.id,
                   version_note=note, version_no=(base.version_no if latest else s.version_no) + 1,
                   status="backtested")
    db.add(new)
    db.flush()
    return {"ok": True, "new_strategy_id": new.id, "version_no": new.version_no,
            "parent_id": new.parent_id}


def _serialize(s: Strategy, with_code: bool = False) -> dict:
    d = {"id": s.id, "name": s.name, "source": s.source, "status": s.status,
         "version_no": s.version_no, "parent_id": s.parent_id,
         "version_note": s.version_note, "description": s.description,
         "params": s.params, "created_at": s.created_at.isoformat()}
    if with_code:
        d["code"] = s.code
    return d


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_or_404(db: Session, sid: int) -> Strategy:
    s = db.get(Strategy, sid)
    if s is None:
        raise HTTPException(404, f"策略 {sid} 不存在")
    return s


@router.get("")
def list_strategies(db: Session = Depends(get_db)):
    rows = db.scalars(select(Strategy).order_by(Strategy.id.desc())).all()
    return [_serialize(s) for s in rows]


def _precheck_import(code: str):
    """导入前置诊断：识别常见不兼容来源，给出明确指引而非晦涩沙箱报错"""
    c = (code or "").strip()
    if not c:
        raise HTTPException(400, "策略代码为空")
    if c.startswith("{") and '"cells"' in c:
        raise HTTPException(400,
                            "检测到 Jupyter Notebook 格式（.ipynb 的 JSON 源码）。"
                            "请先在 Jupyter 中 File→Export→as .py 导出纯 Python 代码再导入")
    import re as _re
    platform_signs = [
        (r"from jqdata|import jqdata|jqfactor|get_fundamentals|get_index_stocks",
         "聚宽(JoinQuant)"),
        (r"from vnpy|import vnpy", "vn.py"),
        (r"import backtrader|from backtrader", "Backtrader"),
        (r"set_benchmark|order_target|handle_data\(context", "聚宽/米筐类平台"),
    ]
    for pat, name in platform_signs:
        if _re.search(pat, c):
            raise HTTPException(
                400, f"检测到 {name} 平台的策略代码，与本平台沙箱 API 不兼容"
                     f"（本平台策略只需定义 init(ctx)/on_bar(ctx,bar,i)，"
                     f"禁用 import 和外部数据接口）。"
                     f"可通过「AI生成策略」用自然语言描述该策略思路，让 AI 按本平台 API 重写")


@router.post("")
def create_strategy(body: StrategyCreate, db: Session = Depends(get_db)):
    _precheck_import(body.code)
    v = validate_strategy_code(db, body.code, body.params)
    if not v.get("ok"):
        raise HTTPException(400, f"沙箱校验失败: {v.get('error')}")
    s = Strategy(name=body.name, code=body.code, description=body.description,
                 params=body.params, source=body.source if body.source in ("manual", "import") else "manual",
                 status="draft")
    db.add(s)
    db.commit()
    db.refresh(s)
    return _serialize(s, with_code=True)


@router.get("/{sid}")
def get_strategy(sid: int, db: Session = Depends(get_db)):
    return _serialize(_get_or_404(db, sid), with_code=True)


@router.put("/{sid}")
def update_strategy(sid: int, body: StrategyUpdate, db: Session = Depends(get_db)):
    s = _get_or_404(db, sid)
    if body.code is not None:
        _precheck_import(body.code)
        v = validate_strategy_code(db, body.code, body.params or s.params)
        if not v.get("ok"):
            raise HTTPException(400, f"沙箱校验失败: {v.get('error')}")
        s.code = body.code
    if body.name is not None:
        s.name = body.name
    if body.description is not None:
        s.description = body.description
    if body.params is not None:
        s.params = body.params
    db.commit()
    return _serialize(s, with_code=True)


@router.post("/{sid}/validate")
def validate_strategy(sid: int, body: ValidateBody, db: Session = Depends(get_db)):
    s = _get_or_404(db, sid)
    code = body.code if body.code is not None else s.code
    params = body.params if body.params is not None else s.params
    v = validate_strategy_code(db, code, params)
    out: dict = {"ok": v.get("ok", False)}
    if not out["ok"]:
        out["error"] = v.get("error")
    return out


@router.post("/generate")
def generate(body: GenerateBody, db: Session = Depends(get_db)):
    from ..agents.strategy_generator import generate_strategy

    def gen():
        try:
            for ev in generate_strategy(db, body.prompt):
                yield _sse(ev["event"], ev["data"])
        except Exception as e:  # noqa: BLE001
            yield _sse("error", {"msg": str(e)})
        finally:
            db.close()

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{sid}/bindings")
def list_bindings(sid: int, db: Session = Depends(get_db)):
    """该策略的挂机绑定列表（含账户名称）"""
    from ..models import SimAccount
    _get_or_404(db, sid)
    rows = db.scalars(select(StrategyBinding).where(
        StrategyBinding.strategy_id == sid)
        .order_by(StrategyBinding.id.desc())).all()
    out = []
    for b in rows:
        acc = db.get(SimAccount, b.account_id)
        out.append({
            "binding_id": b.id, "account_id": b.account_id,
            "account_name": acc.name if acc else f"#{b.account_id}",
            "ts_codes": b.ts_codes or [], "params": b.params,
            "status": b.status,
            "bound": True,
        })
    return out


@router.post("/{sid}/bind")
def bind_strategy(sid: int, body: BindBody, db: Session = Depends(get_db)):
    from ..utils import resolve_ts_code
    _get_or_404(db, sid)
    codes = []
    for c in body.ts_codes:
        code = resolve_ts_code(db, c)
        if code is None:
            raise HTTPException(400, f"股票代码 {c} 不存在")
        if code not in codes:
            codes.append(code)
    b = db.scalar(select(StrategyBinding).where(
        StrategyBinding.strategy_id == sid, StrategyBinding.account_id == body.account_id))
    if b:
        b.ts_codes, b.params, b.status = codes, body.params, "active"
    else:
        b = StrategyBinding(strategy_id=sid, account_id=body.account_id,
                            ts_codes=codes, params=body.params, status="active")
        db.add(b)
    db.commit()
    db.refresh(b)
    return {"binding_id": b.id}


@router.delete("/{sid}/bind/{binding_id}")
def unbind_strategy(sid: int, binding_id: int, db: Session = Depends(get_db)):
    b = db.get(StrategyBinding, binding_id)
    if b is None or b.strategy_id != sid:
        raise HTTPException(404, f"绑定 {binding_id} 不存在")
    b.status = "inactive"
    db.commit()
    return {"ok": True}


@router.post("/{sid}/activate")
def activate_strategy(sid: int, db: Session = Depends(get_db)):
    s = _get_or_404(db, sid)
    s.status = "active"
    # 同策略族成员（不论状态）：旧版→deprecated + 挂机绑定自动迁移到新版本
    migrated = 0
    olds = db.scalars(select(Strategy).where(Strategy.id != s.id)).all()
    for o in olds:
        if o.id == s.parent_id or o.parent_id == s.id or (
                s.parent_id and o.parent_id == s.parent_id):
            if o.status == "active":
                o.status = "deprecated"
            for b in db.scalars(select(StrategyBinding).where(
                    StrategyBinding.strategy_id == o.id,
                    StrategyBinding.status == "active")).all():
                b.strategy_id = s.id
                migrated += 1
    db.commit()
    return {**_serialize(s), "bindings_migrated": migrated}


@router.post("/{sid}/deactivate")
def deactivate_strategy(sid: int, db: Session = Depends(get_db)):
    s = _get_or_404(db, sid)
    s.status = "draft"
    db.commit()
    return _serialize(s)
