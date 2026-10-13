"""严格自测：飞书鉴权链路（不依赖飞书连接，直接调 handle_text）"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from app.db import SessionLocal
from app.models import FeishuUser

db = SessionLocal()
db.query(FeishuUser).filter(FeishuUser.open_id.like("ou_st_%")).delete(synchronize_session=False)
db.commit()
db.close()

from app.services.feishu_auth import create_user
u1, _ = create_user("ou_st_admin", "TestAdmin", "admin")
u2, _ = create_user("ou_st_trader", "TestTrader", "trader", 50000)
u3, _ = create_user("ou_st_viewer", "TestViewer", "viewer")
print("users created:", bool(u1), bool(u2), bool(u3))

from app.services.feishu_bot import handle_text
tests = [
    ("未注册→自动回复open_id", "ou_nobody", "买入 601689", "未授权"),
    ("未注册→帮助含open_id", "ou_nobody", "帮助", "open_id"),
    ("admin→用户列表", "ou_st_admin", "用户列表", "TestAdmin"),
    ("trader→买入(路由个人账户)", "ou_st_trader", "买入 601689 100股", "买入"),
    ("trader→决策被拒", "ou_st_trader", "决策 601689", "仅 admin"),
    ("viewer→买入被拒", "ou_st_viewer", "买入 601689", "无交易权限"),
    ("viewer→状态可查", "ou_st_viewer", "状态", "账户"),
    ("admin→添加用户(默认trader)", "ou_st_admin", "添加用户 ou_st_new2 新人2", "trader"),
    ("admin→删除用户", "ou_st_admin", "删除用户 99", "不存在"),
    ("非admin→添加被拒", "ou_st_trader", "添加用户 ou_x 新人 viewer", "仅 admin"),
]
passed = failed = 0
for desc, oid, text, expect in tests:
    result = handle_text(text, "test_chat", oid) or ""
    ok = expect in result
    status = "PASS" if ok else "FAIL"
    print(f"  {status} {desc}: {str(result)[:80]}")
    if ok:
        passed += 1
    else:
        failed += 1

print(f"\n{passed}/{passed + failed} passed, {failed} failed")
