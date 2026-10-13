"""飞书用户鉴权与权限路由（多用户体系核心）"""
import datetime as dt
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import FeishuUser, OperationLog, SimAccount

log = logging.getLogger(__name__)

ROLE_ADMIN = "admin"
ROLE_TRADER = "trader"
ROLE_VIEWER = "viewer"


def get_user_by_open_id(open_id: str) -> FeishuUser | None:
    db = SessionLocal()
    try:
        return db.scalar(select(FeishuUser).where(
            FeishuUser.open_id == open_id, FeishuUser.status == "active"))
    finally:
        db.close()


def log_operation(user: FeishuUser | None, action: str, detail: dict | None = None,
                  account_id: int | None = None):
    """审计落库（不阻塞主流程）"""
    db = SessionLocal()
    try:
        db.add(OperationLog(
            user_id=user.id if user else None,
            user_name=user.name if user else "unknown",
            action=action[:32], detail=detail or {},
            account_id=account_id))
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.warning("审计落库失败: %s", e)
    finally:
        db.close()


def can_trade(user: FeishuUser) -> bool:
    return user is not None and user.role in (ROLE_ADMIN, ROLE_TRADER)


def can_manage_users(user: FeishuUser) -> bool:
    return user is not None and user.role == ROLE_ADMIN


def can_trigger_decision(user: FeishuUser) -> bool:
    return user is not None and user.role == ROLE_ADMIN


def get_trading_account_id(user: FeishuUser) -> int | None:
    """交易指令路由到的账户：
    - trader → 自己绑定的 account_id
    - admin → agent_config 的基金账户（默认）
    """
    if user.role == ROLE_TRADER:
        return user.account_id
    if user.role == ROLE_ADMIN:
        from ..models import AgentConfig
        db = SessionLocal()
        try:
            c = db.query(AgentConfig).first()
            return c.account_id if c else None
        finally:
            db.close()
    return None


def create_user(open_id: str, name: str, role: str,
                initial_cash: float = 100_000) -> tuple[FeishuUser | None, str]:
    """admin 添加用户；trader 自动建专属账户"""
    db = SessionLocal()
    try:
        existing = db.scalar(select(FeishuUser).where(FeishuUser.open_id == open_id))
        if existing:
            return None, f"用户 {existing.name}({open_id[:12]}...) 已存在"
        if role not in (ROLE_ADMIN, ROLE_TRADER, ROLE_VIEWER):
            return None, f"角色必须是 {ROLE_ADMIN}/{ROLE_TRADER}/{ROLE_VIEWER}"

        account_id = None
        if role == ROLE_TRADER:
            acc = SimAccount(name=f"{name}的个人账户", mode="sim",
                             initial_cash=initial_cash, cash=initial_cash)
            db.add(acc)
            db.flush()
            account_id = acc.id

        u = FeishuUser(open_id=open_id, name=name, role=role, account_id=account_id)
        db.add(u)
        db.commit()
        db.refresh(u)
        acc_info = f"，账户#{account_id}" if account_id else ""
        return u, f"✅ 用户 {name}({role}) 已添加{acc_info}"
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return None, f"添加失败: {e}"
    finally:
        db.close()


def block_user(user_id: int) -> str:
    db = SessionLocal()
    try:
        u = db.get(FeishuUser, user_id)
        if not u:
            return f"用户 #{user_id} 不存在"
        if u.role == ROLE_ADMIN:
            n_admin = len(db.scalars(select(FeishuUser).where(
                FeishuUser.role == ROLE_ADMIN,
                FeishuUser.status == "active")).all())
            if n_admin <= 1:
                return "⚠️ 不能删除最后一个 admin"
        u.status = "blocked"
        db.commit()
        return f"✅ 用户 {u.name}(#{user_id}) 已禁用"
    finally:
        db.close()


def set_role(user_id: int, role: str) -> str:
    db = SessionLocal()
    try:
        u = db.get(FeishuUser, user_id)
        if not u:
            return f"用户 #{user_id} 不存在"
        if role not in (ROLE_ADMIN, ROLE_TRADER, ROLE_VIEWER):
            return f"角色必须是 admin/trader/viewer"
        if u.role == ROLE_ADMIN and role != ROLE_ADMIN:
            n_admin = len(db.scalars(select(FeishuUser).where(
                FeishuUser.role == ROLE_ADMIN,
                FeishuUser.status == "active")).all())
            if n_admin <= 1:
                return "⚠️ 不能降级最后一个 admin"
        # trader 角色需有账户
        if role == ROLE_TRADER and not u.account_id:
            acc = SimAccount(name=f"{u.name}的个人账户", mode="sim",
                             initial_cash=100_000, cash=100_000)
            db.add(acc)
            db.flush()
            u.account_id = acc.id
        u.role = role
        db.commit()
        return f"✅ {u.name} 角色已改为 {role}"
    finally:
        db.close()


def list_users() -> str:
    db = SessionLocal()
    try:
        rows = db.scalars(select(FeishuUser)
                          .order_by(FeishuUser.id)).all()
        if not rows:
            return "暂无用户（请先运行 init_admin 脚本）"
        lines = []
        for u in rows:
            status_icon = "✅" if u.status == "active" else "⛔"
            acc = f" 账户#{u.account_id}" if u.account_id else ""
            lines.append(f"{status_icon} #{u.id} {u.name} [{u.role}]{acc}")
        return "\n".join(lines)
    finally:
        db.close()
