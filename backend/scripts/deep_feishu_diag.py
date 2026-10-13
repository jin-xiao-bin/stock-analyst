"""飞书WS长连接深度诊断"""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from app.config import settings

print("=" * 60)
print("飞书长连接深度诊断")
print("=" * 60)

# 1. 基本配置
print(f"\nApp ID: {settings.feishu_app_id}")
print(f"App Secret: {settings.feishu_app_secret[:4]}***")

# 2. 获取 token 并获取机器人加入的群列表
print("\n[1] 获取 tenant_access_token...")
req = urllib.request.Request(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    data=json.dumps({"app_id": settings.feishu_app_id,
                     "app_secret": settings.feishu_app_secret}).encode(),
    headers={"Content-Type": "application/json"})
resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
if resp.get("code") != 0:
    print(f"  ❌ {resp}")
    sys.exit(1)
token = resp["tenant_access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("  ✅ OK")

# 3. 获取机器人所在的群列表（关键诊断）
print("\n[2] 机器人所在的群列表...")
req = urllib.request.Request(
    "https://open.feishu.cn/open-apis/im/v1/chats?page_size=20",
    headers=headers)
try:
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    if resp.get("code") == 0:
        chats = resp.get("data", {}).get("items", [])
        print(f"  ✅ 机器人在 {len(chats)} 个群中:")
        for c in chats:
            print(f"    - chat_id: {c.get('chat_id')}")
            print(f"      name: {c.get('name', '?')}")
            print(f"      owner: {c.get('owner_id', '?')}")
    else:
        print(f"  ⚠️ code={resp.get('code')} msg={resp.get('msg')}")
        if resp.get("code") == 99991672:
            print("  → 缺少 im:chat 权限，需要开通「获取群组信息」权限")
except Exception as e:
    print(f"  ❌ {e}")

# 4. Webhook 推送（确认用户能看到）
print("\n[3] Webhook 推送诊断提示...")
try:
    req = urllib.request.Request(
        settings.feishu_webhook_url,
        data=json.dumps({"msg_type": "text",
                         "content": {"text": "🔴 长连接诊断：WS通道可能有问题，请检查飞书开放平台的事件订阅配置"}}).encode(),
        headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    print(f"  {'✅' if resp.get('code') == 0 else '⚠️'} Webhook推送: {resp.get('msg', '')}")
except Exception as e:  # noqa: BLE001
    print(f"  ⚠️ Webhook: {e}")

print("\n=== 关键问题 ===")
print("如果机器人不在任何群里 → 需要把「智能交易员」应用机器人拉进群")
print("如果在群里但收不到消息 → 检查飞书开放平台的事件订阅是否是「长连接」模式")
print("并且确认「接收消息 im.message.receive_v1」事件已订阅且应用已发布")
