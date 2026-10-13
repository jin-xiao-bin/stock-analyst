"""飞书通道诊断：1)凭证有效性 2)能否发消息 3)WS连接状态"""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from app.config import settings

print("=== 飞书通道诊断 ===")
print(f"App ID: {settings.feishu_app_id[:8]}...")
print(f"App Secret: {settings.feishu_app_secret[:4]}...")
print(f"Webhook: {settings.feishu_webhook_url[:30]}...")

# 1. 获取 tenant_access_token（验证凭证）
print("\n[1] 凭证验证...")
req = urllib.request.Request(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    data=json.dumps({"app_id": settings.feishu_app_id,
                     "app_secret": settings.feishu_app_secret}).encode(),
    headers={"Content-Type": "application/json"})
resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
if resp.get("code") != 0:
    print(f"  ❌ 凭证无效: {resp}")
    sys.exit(1)
token = resp["tenant_access_token"]
print(f"  ✅ 凭证有效，token 获取成功")

# 2. 获取机器人信息
print("\n[2] 机器人信息...")
req = urllib.request.Request(
    "https://open.feishu.cn/open-apis/bot/v3/info",
    headers={"Authorization": f"Bearer {token}"})
try:
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    if resp.get("code") == 0:
        bot = resp.get("data", {})
        print(f"  ✅ 机器人: {bot.get('bot_name', '?')} (activate={bot.get('activate_status')})")
    else:
        print(f"  ⚠️ {resp.get('msg', resp)}")
except Exception as e:
    print(f"  ⚠️ {e}")

# 3. 检查是否有多个进程在竞争连接
print("\n[3] 检查Python进程（WS连接竞争）...")
import subprocess
result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq python.exe"],
                       capture_output=True, text=True)
lines = [l for l in result.stdout.splitlines() if "python" in l.lower()]
print(f"  Python进程数: {len(lines)}")
for l in lines[:5]:
    print(f"  {l.strip()}")
if len(lines) > 3:
    print("  ⚠️ 有多个Python进程，可能存在旧WS连接竞争！")
    print("  建议：结束多余进程后重启后端")

# 4. 通过 webhook 发测试消息（验证基础通知通路）
print("\n[4] Webhook通知测试...")
try:
    req = urllib.request.Request(
        settings.feishu_webhook_url,
        data=json.dumps({"msg_type": "text",
                         "content": {"text": "🔧 飞书通道诊断：如果你能看到这条消息，说明Webhook正常。请@机器人发「我的ID」测试长连接。"}}).encode(),
        headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    print(f"  {'✅' if resp.get('code') == 0 else '❌'} Webhook: {resp}")
except Exception as e:
    print(f"  ❌ Webhook: {e}")

print("\n=== 诊断完成 ===")
print("如果[4]成功但你@机器人没反应 → 长连接问题（可能多进程竞争或事件订阅失效）")
print("建议操作：1)关闭所有python进程 2)重启后端 3)再@机器人测试")
