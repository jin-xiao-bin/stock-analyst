"""任务监控 API（契约第6节）：列表/取消/手动核验/markers"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..models import SimTrade, WatchTask
from ..services.watch_tasks import verify_all

router = APIRouter(prefix="/api", tags=["watch-tasks"])


def _task_out(t: WatchTask) -> dict:
    return {
        "id": t.id, "ts_code": t.ts_code, "source_report_id": t.source_report_id,
        "task_type": t.task_type, "condition_json": t.condition_json,
        "expect_json": t.expect_json, "status": t.status,
        "trigger_date": t.trigger_date.isoformat() if t.trigger_date else None,
        "trigger_detail": t.trigger_detail,
        "expire_date": t.expire_date.isoformat() if t.expire_date else None,
    }


@router.get("/watch-tasks")
def list_tasks(
    status: str = Query(None),
    ts_code: str = Query(None),
    source_report_id: int = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    stmt = select(WatchTask)
    if status:
        stmt = stmt.where(WatchTask.status == status)
    if ts_code:
        from ..utils import resolve_ts_code
        ts_code = resolve_ts_code(db, ts_code) or ts_code
        stmt = stmt.where(WatchTask.ts_code == ts_code)
    if source_report_id:
        stmt = stmt.where(WatchTask.source_report_id == source_report_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(WatchTask.id.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {"total": total, "items": [_task_out(t) for t in rows]}


@router.put("/watch-tasks/{task_id}/cancel")
def cancel_task(task_id: int, db: Session = Depends(get_db)):
    task = db.get(WatchTask, task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task.status != "waiting":
        raise HTTPException(400, f"仅 waiting 任务可取消，当前状态 {task.status}")
    task.status = "cancelled"
    db.commit()
    return _task_out(task)


@router.post("/watch-tasks/verify")
def manual_verify(background: BackgroundTasks):
    """手动触发一次全量核验（异步后台执行）"""

    def _job():
        db = SessionLocal()
        try:
            verify_all(db)
        finally:
            db.close()

    background.add_task(_job)
    return {"ok": True, "msg": "核验已提交后台执行"}


@router.get("/stocks/{ts_code}/markers")
def stock_markers(ts_code: str, db: Session = Depends(get_db)):
    """K线标记：该股已触发 watch_task + 全部账户该股 sim_trade 买卖点"""
    from ..utils import resolve_ts_code
    ts_code = resolve_ts_code(db, ts_code) or ts_code
    markers = []
    tasks = db.scalars(
        select(WatchTask).where(WatchTask.ts_code == ts_code, WatchTask.status == "triggered")
    ).all()
    for t in tasks:
        if not t.trigger_date:
            continue
        cond = t.condition_json or {}
        label = (f"{cond.get('kind', t.task_type)}"
                 + (f"@{cond.get('value')}" if cond.get("value") is not None else ""))
        markers.append({
            "date": t.trigger_date.isoformat(),
            "type": "watch_triggered",
            "label": label,
            "detail": t.trigger_detail or "",
            "ref_id": t.id,
        })
    trades = db.scalars(
        select(SimTrade).where(SimTrade.ts_code == ts_code).order_by(SimTrade.trade_date)
    ).all()
    for tr in trades:
        markers.append({
            "date": tr.trade_date.isoformat(),
            "type": tr.side,  # buy / sell
            "label": f"{tr.side} {tr.qty}@{tr.price}",
            "detail": tr.note or f"账户{tr.account_id} {tr.source}",
            "ref_id": tr.id,
        })
    markers.sort(key=lambda m: (m["date"], str(m["type"])))
    return markers
