"""多用户鉴权 E2E：模拟不同角色的飞书消息"""
import json
import sys
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE = "http://127.0.0.1:8300/api"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


import time

SUFFIX = str(int(time.time()))  # 每次跑用不同后缀避免冲突

# 1. 初始化 admin
try:
    r = call("POST", "/users", {"open_id": f"ou_admin_{SUFFIX}", "name": "Admin", "role": "admin"})
    print(f"admin created: {r}")
except urllib.error.HTTPError as e:
    print(f"admin: {e.read().decode('utf-8', 'replace')[:50]}")

# 2. 添加 trader（自动建账户）
try:
    r = call("POST", "/users", {"open_id": f"ou_trader_{SUFFIX}", "name": "Trader", "role": "trader",
                                "initial_cash": 50000})
    print(f"trader created: {r.get('account_id', '?')}")
except urllib.error.HTTPError as e:
    print(f"trader: {e.read().decode('utf-8', 'replace')[:50]}")

# 3. 添加 viewer
try:
    r = call("POST", "/users", {"open_id": f"ou_viewer_{SUFFIX}", "name": "Viewer", "role": "viewer"})
    print(f"viewer created")
except urllib.error.HTTPError as e:
    print(f"viewer: {e.read().decode('utf-8', 'replace')[:50]}")

# 4. 用户列表
print("\n用户列表:")
print(call("GET", "/users"))

# 5. 模拟消息处理（直接调 handle_text 模拟各角色）
from app.services.feishu_bot import handle_text
print("\n--- 模拟飞书消息 ---")
print("未授权:", handle_text("买入 601689 1000股", "chat1", "ou_nobody")[:50])
print("admin列表:", handle_text("用户列表", "chat1", f"ou_admin_{SUFFIX}")[:60])
print("trader买入:", handle_text("买入 601689 100股", "chat1", f"ou_trader_{SUFFIX}")[:80])
print("viewer买入:", handle_text("买入 601689 100股", "chat1", f"ou_viewer_{SUFFIX}")[:50])
print("viewer状态:", handle_text("状态", "chat1", f"ou_viewer_{SUFFIX}")[:80])
print("trader决策:", handle_text("决策 601689", "chat1", f"ou_trader_{SUFFIX}")[:50])

# 6. 操作审计
logs = call("GET", "/users/logs")
print(f"\n操作日志: {len(logs)} 条")
for l in logs[:5]:
    print(f"  {l['user_name']} {l['action']} {str(l.get('detail', ''))[:50]}")

# 7. 不清理（保留用户供后续测试）
