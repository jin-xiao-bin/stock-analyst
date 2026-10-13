"""初始化 admin 用户（首次部署必跑一次）
用法: python scripts/init_admin.py <你的飞书open_id> [你的名字]
获取 open_id：在飞书群里@机器人发一条消息，后端日志会打出 open_id=ou_xxxx
"""
import sys

from app.db import SessionLocal
from app.models import FeishuUser
from app.services.feishu_auth import create_user


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/init_admin.py <open_id> [名字]")
        print("获取 open_id：飞书群@机器人发消息后查看后端日志")
        return 1

    open_id = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else "管理员"

    db = SessionLocal()
    try:
        existing_admin = db.query(FeishuUser).filter_by(
            open_id=open_id).first()
        if existing_admin:
            print(f"用户已存在: {existing_admin.name}({existing_admin.role})")
            return 0
    finally:
        db.close()

    user, msg = create_user(open_id, name, "admin")
    print(msg)
    return 0 if user else 1


if __name__ == "__main__":
    sys.exit(main())
