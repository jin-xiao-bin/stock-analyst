"""管理接口：手动触发同步"""
from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..services.market_sync import sync_all_tracked, sync_stock_basic

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/sync/basic")
def sync_basic(background: BackgroundTasks, db: Session = Depends(get_db)):
    n = sync_stock_basic(db)
    db.commit()
    return {"rows": n}


@router.post("/sync/daily")
def sync_daily_all(background: BackgroundTasks, db: Session = Depends(get_db)):
    # 后台执行，避免请求超时
    background.add_task(run_sync_all)
    return {"status": "started"}


def run_sync_all():
    from ..db import SessionLocal
    db = SessionLocal()
    try:
        sync_all_tracked(db)
    finally:
        db.close()
