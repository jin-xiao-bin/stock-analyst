"""深度诊断：获取机器人所在群列表（修复版）"""
import json
import sys
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from app.config import settings

# 获取 token
req = urllib.request.Request(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    data=json.dumps({"app_id": settings.feishu_app_id,
                     "app_secret": settings.feishu_app_secret}).encode(),
    headers={"Content-Type": "application/json"})
resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
token = resp["tenant_access_token"]
headers = {"Authorization": f"Bearer {token}"}

# 获取群列表 - 修正 API 调用
print("机器人所在群列表:")
try:
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/chats?page_size=20",
        headers=headers)
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    print(f"  code: {resp.get('code')}")
    chats = resp.get("data", {}).get("items", [])
    print(f"  机器人在 {len(chats)} 个群中:")
    for c in chats:
        print(f"    chat_id: {c.get('chat_id')}")
        print(f"    name: {c.get('name', '?')}")
except urllib.error.HTTPError as e:
    body = e.read().decode('utf-8', errors='replace')
    print(f"  HTTP {e.code}: {body[:500]}")
except Exception as e:
    print(f"  Error: {e}")

print("\n--- 检查机器人是否被添加到群 ---")
print("如果上面显示 0 个群或报错，说明「智能交易员」应用机器人还没有被拉进任何群。")
print("解决方法：飞书群 → 设置 → 群机器人 → 添加机器人 → 搜索「智能交易员」→ 添加")
