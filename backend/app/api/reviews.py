"""交易审查 API（契约第7节）"""
from __future__ import annotations

import datetime as dt
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import TradeReview

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


class ReviewCreate(BaseModel):
    account_id: int
    scope: str = "all"  # manual | strategy | all
    strategy_id: int | None = None
    period_start: dt.date | None = None
    period_end: dt.date | None = None


class FollowupBody(BaseModel):
    followup: str  # adopted | dismissed


class ApplyBody(BaseModel):
    suggestion_index: int


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("")
def create_review(body: ReviewCreate, db: Session = Depends(get_db)):
    from ..agents.review_agent import run_review

    if body.scope not in ("manual", "strategy", "all"):
        raise HTTPException(400, "scope 必须为 manual/strategy/all")
    if body.scope == "strategy" and not body.strategy_id:
        raise HTTPException(400, "scope=strategy 时必须提供 strategy_id")

    def gen():
        try:
            for ev in run_review(db, body.account_id, body.scope, body.strategy_id,
                                 body.period_start, body.period_end):
                yield _sse(ev["event"], ev["data"])
        except Exception as e:  # noqa: BLE001
            yield _sse("error", {"msg": str(e)})
        finally:
            db.close()

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("")
def list_reviews(account_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(TradeReview).order_by(TradeReview.id.desc()).limit(50)
    if account_id:
        stmt = stmt.where(TradeReview.account_id == account_id)
    return [{"id": r.id, "account_id": r.account_id, "scope": r.scope,
             "strategy_id": r.strategy_id,
             "period_start": r.period_start.isoformat() if r.period_start else None,
             "period_end": r.period_end.isoformat() if r.period_end else None,
             "followup": r.followup, "created_at": r.created_at.isoformat()}
            for r in db.scalars(stmt).all()]


@router.get("/{rid}")
def get_review(rid: int, db: Session = Depends(get_db)):
    r = db.get(TradeReview, rid)
    if r is None:
        raise HTTPException(404, f"审查 {rid} 不存在")
    return {"id": r.id, "account_id": r.account_id, "scope": r.scope,
            "strategy_id": r.strategy_id,
            "period_start": r.period_start, "period_end": r.period_end,
            "content": r.content, "suggestions": r.suggestions,
            "followup": r.followup, "created_at": r.created_at.isoformat()}


@router.put("/{rid}/followup")
def set_followup(rid: int, body: FollowupBody, db: Session = Depends(get_db)):
    r = db.get(TradeReview, rid)
    if r is None:
        raise HTTPException(404, f"审查 {rid} 不存在")
    if body.followup not in ("adopted", "dismissed"):
        raise HTTPException(400, "followup 必须为 adopted/dismissed")
    r.followup = body.followup
    db.commit()
    return {"id": r.id, "followup": r.followup}


@router.post("/{rid}/apply")
def apply_review(rid: int, body: ApplyBody, db: Session = Depends(get_db)):
    from ..services.review_service import apply_suggestion
    return apply_suggestion(db, rid, body.suggestion_index)
