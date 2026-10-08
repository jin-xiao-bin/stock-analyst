"""AI 分析 API（契约第3节）：SSE 分析流、报告列表/详情、chain、diff、synthesis"""
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.company_analysis import parse_structured, run_analysis
from ..agents.synthesis import run_synthesis
from ..db import get_db
from ..models import (AnalysisReport, ReportChain, ReportDiscussion,
                      ReportMerge, StockBasic, WatchTask)
from pydantic import BaseModel

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _agent_stream(gen):
    """把 agent 生成器的 (kind, payload) 转成 SSE 文本流"""
    try:
        for kind, payload in gen:
            if kind == "status":
                stage = payload.get("stage", "")
                if stage == "done":
                    continue  # done stage 是内部状态，完成信号由 done 事件给出
                yield _sse_event("status", payload)
            else:
                yield _sse_event(kind, payload)
    except Exception as e:  # noqa: BLE001
        yield _sse_event("error", {"msg": f"内部错误: {e}"})


@router.post("/{ts_code}")
def start_analysis(ts_code: str, db: Session = Depends(get_db)):
    """公司分析 SSE 流：status/section/done/error"""
    from ..utils import resolve_ts_code
    code = resolve_ts_code(db, ts_code)
    if code is None:
        raise HTTPException(400, f"股票代码 {ts_code} 不存在")
    db.close()  # Depends 会话由本请求持有；生成器内自建会话（生命周期长于请求处理）
    return StreamingResponse(
        _agent_stream(run_analysis(code)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{ts_code}/synthesis")
def start_synthesis(ts_code: str, db: Session = Depends(get_db)):
    """归纳总结 SSE 流：同分析流事件"""
    from ..utils import resolve_ts_code
    code = resolve_ts_code(db, ts_code)
    if code is None:
        raise HTTPException(400, f"股票代码 {ts_code} 不存在")
    db.close()
    return StreamingResponse(
        _agent_stream(run_synthesis(code)),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/reports/{report_id}")
def get_report(report_id: int, db: Session = Depends(get_db)):
    rep = db.get(AnalysisReport, report_id)
    if not rep:
        raise HTTPException(404, "报告不存在")
    merged = db.scalar(select(ReportMerge).where(ReportMerge.report_id == report_id))
    n_discuss = len(db.scalars(select(ReportDiscussion.id).where(
        ReportDiscussion.report_id == report_id)).all())
    return {
        "id": rep.id,
        "ts_code": rep.ts_code,
        "as_of_date": rep.as_of_date.isoformat(),
        "title": rep.title,
        "report_type": rep.report_type,
        "content": rep.content,
        "model": rep.model,
        "created_at": rep.created_at.isoformat(),
        "structured": parse_structured(rep.content),
        "merged_content": merged.content if merged else None,
        "merged_updated_at": merged.updated_at.isoformat(timespec="minutes") if merged else None,
        "discussion_count": n_discuss,
    }


# ---------------- 报告讨论（用户观点收集 → 自动融合综合分析） ----------------

DISCUSS_SYSTEM = (
    "你是该分析报告的第一作者（首席交易员），正与报告读者（用户）讨论这份报告。"
    "基于报告内容与讨论历史回应用户：解答疑问、接受合理质疑并修正结论、"
    "对不合理的质疑给出依据并坚持。如实告知不确定性。简洁专业，中文。"
)

MERGE_SYSTEM = (
    "你是研究主管，把一份AI分析报告与用户讨论融合为「人机综合分析」。"
    "结构：1) 核心结论（含修订）；2) AI原判断摘要；3) 用户观点与依据；"
    "4) 观点分歧与裁决（采纳谁、为什么，用数据说话）；5) 修订后的关键价位与操作建议；"
    "6) 风险与未验证信息。末尾保留/更新一个 ```json structured 块（score/bullish_points/"
    "bearish_points/key_levels），如用户观点改变了评分/价位请更新数值。中文 markdown。"
)


def _do_merge(db: Session, report_id: int):
    """自动融合：原始报告 + 讨论全记录 → ReportMerge（每轮讨论后调用）"""
    rep = db.get(AnalysisReport, report_id)
    if not rep:
        return
    msgs = db.scalars(select(ReportDiscussion).where(
        ReportDiscussion.report_id == report_id)
        .order_by(ReportDiscussion.id)).all()
    if not msgs:
        return
    discussion = "\n\n".join(
        f"{'【用户】' if m.role == 'user' else '【AI】'}：{m.content}" for m in msgs)
    from ..services.deepseek_client import client as ds_client
    from ..config import settings
    try:
        content = ds_client.chat(
            [{"role": "system", "content": MERGE_SYSTEM},
             {"role": "user",
              "content": f"=== 原始AI报告 ===\n{rep.content[:8000]}\n\n=== 讨论记录 ===\n{discussion[:8000]}"}],
            model=settings.reasoner_model, max_tokens=4096)
    except Exception:  # noqa: BLE001 融合失败不影响讨论本身
        return
    merged = db.scalar(select(ReportMerge).where(ReportMerge.report_id == report_id))
    if merged:
        merged.content = content
    else:
        db.add(ReportMerge(report_id=report_id, content=content))
    db.commit()


class DiscussReq(BaseModel):
    content: str


@router.get("/reports/{report_id}/discussion")
def get_discussion(report_id: int, db: Session = Depends(get_db)):
    msgs = db.scalars(select(ReportDiscussion).where(
        ReportDiscussion.report_id == report_id)
        .order_by(ReportDiscussion.id)).all()
    merged = db.scalar(select(ReportMerge).where(ReportMerge.report_id == report_id))
    return {
        "messages": [{"id": m.id, "role": m.role, "content": m.content,
                      "created_at": m.created_at.isoformat(timespec="minutes")} for m in msgs],
        "merged_content": merged.content if merged else None,
        "merged_updated_at": merged.updated_at.isoformat(timespec="minutes") if merged else None,
    }


@router.post("/reports/{report_id}/discussion")
def post_discussion(report_id: int, req: DiscussReq, db: Session = Depends(get_db)):
    """用户发言 → AI 回应（报告+讨论历史+实时价上下文）→ 自动融合综合分析"""
    rep = db.get(AnalysisReport, report_id)
    if not rep:
        raise HTTPException(404, "报告不存在")
    text = (req.content or "").strip()
    if not text:
        raise HTTPException(400, "内容为空")

    db.add(ReportDiscussion(report_id=report_id, role="user", content=text))
    db.commit()

    history = db.scalars(select(ReportDiscussion).where(
        ReportDiscussion.report_id == report_id)
        .order_by(ReportDiscussion.id)).all()
    dialogue = "\n".join(
        f"{'用户' if m.role == 'user' else 'AI'}：{m.content}" for m in history)

    rt_line = ""
    try:
        from ..services.realtime import get_realtime
        rt = get_realtime(rep.ts_code) or {}
        if rt.get("price"):
            rt_line = f"\n当前实时：现价{rt['price']} 涨跌{rt.get('pct_chg')}%（讨论时参考）"
    except Exception:  # noqa: BLE001
        pass

    from ..services.deepseek_client import client as ds_client
    from ..config import settings
    try:
        reply = ds_client.chat(
            [{"role": "system", "content": DISCUSS_SYSTEM},
             {"role": "user",
              "content": f"=== 报告 ===\n{rep.content[:7000]}\n{rt_line}\n\n=== 讨论记录 ===\n{dialogue[:6000]}\n\n请回应最新一条用户发言。"}],
            model=settings.chat_model, temperature=0.5, max_tokens=1500)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"AI 回应失败: {e}") from e
    db.add(ReportDiscussion(report_id=report_id, role="assistant", content=reply))
    db.commit()

    # 自动融合（异步感同步做：reasoner 较慢，但保证返回时综合分析已最新）
    _do_merge(db, report_id)

    merged = db.scalar(select(ReportMerge).where(ReportMerge.report_id == report_id))
    return {
        "reply": reply,
        "merged_content": merged.content if merged else None,
        "merged_updated_at": merged.updated_at.isoformat(timespec="minutes") if merged else None,
    }


@router.get("/diff")
def diff_reports(report_a: int, report_b: int, db: Session = Depends(get_db)):
    """对比两份报告的 structured：评分变化、关键位、新增多空论点"""
    a, b = db.get(AnalysisReport, report_a), db.get(AnalysisReport, report_b)
    if not a:
        raise HTTPException(404, f"报告 {report_a} 不存在")
    if not b:
        raise HTTPException(404, f"报告 {report_b} 不存在")
    sa, sb = parse_structured(a.content), parse_structured(b.content)

    def _summary(rep, s):
        return {
            "id": rep.id, "ts_code": rep.ts_code, "as_of_date": rep.as_of_date.isoformat(),
            "title": rep.title, "report_type": rep.report_type,
            "score": s.get("score") if s else None,
        }

    def _norm(items):
        return {t.strip() for t in items or []}

    def _new_items(base, cur):
        return [t for t in (cur or []) if t.strip() not in _norm(base)]

    sa, sb = sa or {}, sb or {}
    return {
        "a": _summary(a, sa), "b": _summary(b, sb),
        "score_delta": (sb.get("score") - sa.get("score")) if (sa.get("score") is not None and sb.get("score") is not None) else None,
        "key_levels_a": sa.get("key_levels") or {"support": [], "resistance": []},
        "key_levels_b": sb.get("key_levels") or {"support": [], "resistance": []},
        "bullish_new": _new_items(sa.get("bullish_points"), sb.get("bullish_points")),
        "bearish_new": _new_items(sa.get("bearish_points"), sb.get("bearish_points")),
    }


@router.get("/all-reports")
def list_all_reports(db: Session = Depends(get_db)):
    """全局报告列表（跨股票）：company 与 synthesis 全量，含公司名称，前端按 ts_code 关联归纳"""
    rows = db.scalars(
        select(AnalysisReport).order_by(AnalysisReport.id.desc())
    ).all()
    names = dict(db.execute(
        select(StockBasic.ts_code, StockBasic.name)).all())
    return [
        {
            "id": r.id, "ts_code": r.ts_code,
            "stock_name": names.get(r.ts_code),
            "as_of_date": r.as_of_date.isoformat(),
            "title": r.title, "report_type": r.report_type, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.delete("/reports/{report_id}")
def delete_report(report_id: int, db: Session = Depends(get_db)):
    """删除报告（含版本链与该报告创建的观察任务）"""
    rep = db.get(AnalysisReport, report_id)
    if not rep:
        raise HTTPException(404, "报告不存在")
    db.query(ReportChain).filter(
        (ReportChain.report_id == report_id) |
        (ReportChain.prev_report_id == report_id)).delete(synchronize_session=False)
    db.query(WatchTask).filter(WatchTask.source_report_id == report_id)\
        .delete(synchronize_session=False)
    db.delete(rep)
    db.commit()
    return {"ok": True, "deleted": report_id}


@router.get("/{ts_code}/reports")
def list_reports(ts_code: str, db: Session = Depends(get_db)):
    from ..utils import resolve_ts_code
    ts_code = resolve_ts_code(db, ts_code) or ts_code
    rows = db.scalars(
        select(AnalysisReport).where(AnalysisReport.ts_code == ts_code)
        .order_by(AnalysisReport.id.desc())
    ).all()
    return [
        {
            "id": r.id, "as_of_date": r.as_of_date.isoformat(), "title": r.title,
            "report_type": r.report_type, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/{ts_code}/chain")
def report_chain(ts_code: str, db: Session = Depends(get_db)):
    from ..utils import resolve_ts_code
    ts_code = resolve_ts_code(db, ts_code) or ts_code
    rows = db.scalars(
        select(ReportChain).where(ReportChain.ts_code == ts_code)
        .order_by(ReportChain.report_id.desc())
    ).all()
    reports = {r.id: r for r in db.scalars(
        select(AnalysisReport).where(AnalysisReport.ts_code == ts_code)).all()}
    out = []
    for rc in rows:
        rep = reports.get(rc.report_id)
        out.append({
            "report_id": rc.report_id,
            "as_of_date": rep.as_of_date.isoformat() if rep else None,
            "title": rep.title if rep else None,
            "prev_report_id": rc.prev_report_id,
        })
    return out
