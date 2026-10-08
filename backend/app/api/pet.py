"""桌面宠物 API：自选股清单 / 警报规则 / 对话指令"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import DailyPrice
from ..utils import resolve_ts_code

router = APIRouter(prefix="/api/pet", tags=["pet"])

# ---------- 自选股清单 ----------


@router.get("/watchlist")
def get_watchlist(db: Session = Depends(get_db)):
    from ..models import PetWatchlist
    rows = db.scalars(select(PetWatchlist).order_by(PetWatchlist.id)).all()
    return [{"id": r.id, "ts_code": r.ts_code} for r in rows]


@router.post("/watchlist")
def add_watchlist(body: dict, db: Session = Depends(get_db)):
    from ..models import PetWatchlist
    code = resolve_ts_code(db, str(body.get("ts_code", "")))
    if code is None:
        raise HTTPException(400, f"股票代码 {body.get('ts_code')} 不存在")
    exists = db.scalar(select(PetWatchlist).where(PetWatchlist.ts_code == code))
    if exists:
        return {"ok": True, "id": exists.id, "ts_code": code, "dedup": True}
    row = PetWatchlist(ts_code=code)
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id, "ts_code": code}


@router.delete("/watchlist/{row_id}")
def del_watchlist(row_id: int, db: Session = Depends(get_db)):
    from ..models import PetWatchlist
    row = db.get(PetWatchlist, row_id)
    if row:
        db.delete(row)
        db.commit()
    return {"ok": True}


# ---------- 警报规则 ----------


class RuleBody(BaseModel):
    ts_code: str
    rule_type: str  # threshold / cross / spike
    params: dict    # {"pct":3} / {"direction":"below","price":10.5} / {"window_min":5,"pct":2}
    enabled: bool = True


@router.get("/alert-rules")
def get_rules(db: Session = Depends(get_db)):
    from ..models import PetAlertRule
    rows = db.scalars(select(PetAlertRule).order_by(PetAlertRule.id.desc())).all()
    return [{"id": r.id, "ts_code": r.ts_code, "rule_type": r.rule_type,
             "params": r.params, "enabled": r.enabled} for r in rows]


@router.post("/alert-rules")
def add_rule(body: RuleBody, db: Session = Depends(get_db)):
    from ..models import PetAlertRule
    code = resolve_ts_code(db, body.ts_code)
    if code is None:
        raise HTTPException(400, f"股票代码 {body.ts_code} 不存在")
    if body.rule_type not in ("threshold", "cross", "spike"):
        raise HTTPException(400, "rule_type 必须是 threshold/cross/spike")
    row = PetAlertRule(ts_code=code, rule_type=body.rule_type,
                       params=body.params, enabled=body.enabled)
    db.add(row)
    db.commit()
    return {"ok": True, "id": row.id}


@router.put("/alert-rules/{rule_id}")
def update_rule(rule_id: int, body: RuleBody, db: Session = Depends(get_db)):
    from ..models import PetAlertRule
    r = db.get(PetAlertRule, rule_id)
    if r is None:
        raise HTTPException(404, "规则不存在")
    r.params = body.params
    r.enabled = body.enabled
    db.commit()
    return {"ok": True}


@router.delete("/alert-rules/{rule_id}")
def del_rule(rule_id: int, db: Session = Depends(get_db)):
    from ..models import PetAlertRule
    r = db.get(PetAlertRule, rule_id)
    if r:
        db.delete(r)
        db.commit()
    return {"ok": True}


# ---------- 对话指令 ----------


@router.post("/chat")
def chat(body: dict, db: Session = Depends(get_db)):
    from ..services.pet_chat import chat as pet_chat
    return pet_chat(body, db)
