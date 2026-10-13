"""Web API 用户管理端点（供前端/管理界面使用，暂无鉴权——Web 层暂不做登录）"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import OperationLog
from ..services.feishu_auth import (block_user, create_user, list_users,
                                    set_role)

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreateBody(BaseModel):
    open_id: str
    name: str
    role: str  # admin/trader/viewer
    initial_cash: float = 100_000


class RoleBody(BaseModel):
    role: str


@router.get("")
def list_all(db: Session = Depends(get_db)):
    """用户列表"""
    return list_users()


@router.post("")
def create(body: UserCreateBody):
    user, msg = create_user(body.open_id, body.name, body.role, body.initial_cash)
    if not user:
        raise HTTPException(400, msg)
    return {"id": user.id, "open_id": user.open_id, "name": user.name,
            "role": user.role, "account_id": user.account_id, "msg": msg}


@router.put("/{user_id}/role")
def change_role(user_id: int, body: RoleBody):
    msg = set_role(user_id, body.role)
    if not msg.startswith("✅"):
        raise HTTPException(400, msg)
    return {"msg": msg}


@router.delete("/{user_id}")
def block(user_id: int):
    msg = block_user(user_id)
    if not msg.startswith("✅"):
        raise HTTPException(400, msg)
    return {"msg": msg}


@router.get("/logs")
def operation_logs(user_id: int | None = None, page: int = 1,
                   page_size: int = 50, db: Session = Depends(get_db)):
    """操作审计日志"""
    stmt = select(OperationLog).order_by(OperationLog.id.desc())
    if user_id:
        stmt = stmt.where(OperationLog.user_id == user_id)
    rows = db.scalars(stmt.offset((page - 1) * page_size)
                      .limit(page_size)).all()
    return [{"id": r.id, "user_id": r.user_id, "user_name": r.user_name,
             "action": r.action, "detail": r.detail,
             "account_id": r.account_id,
             "created_at": r.created_at.isoformat(timespec="minutes")}
            for r in rows]
