"""检查飞书应用的事件订阅和权限配置"""
import json
import sys
import urllib.request

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

print("=" * 60)
print("飞书应用配置检查（API层面）")
print("=" * 60)

# 1. 机器人信息
print("\n[1] 机器人基本信息")
try:
    r = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://open.feishu.cn/open-apis/bot/v3/info", headers=headers), timeout=10).read())
    if r.get("code") == 0:
        d = r.get("data", {})
        print(f"  名称: {d.get('bot_name', '?')}")
        print(f"  状态: activate={d.get('activate_status')}")
    else:
        print(f"  ❌ {r.get('msg', r)}")
except Exception as e:
    print(f"  ❌ {e}")

# 2. 发送测试消息到指定群（验证API权限）
print("\n[2] im:message 发送权限")
try:
    # 尝试发送（会失败如果没权限，但错误信息能告诉我们缺什么）
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        data=json.dumps({"receive_id": "oc_dummy", "msg_type": "text",
                         "content": json.dumps({"text": "test"})}).encode(),
        headers={**headers, "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10)
except urllib.error.HTTPError as e:
    body = json.loads(e.read())
    code = body.get("code", e.code)
    msg = body.get("msg", "")
    if code == 99991672:
        print("  ❌ 缺少 im:message 权限（需要去权限管理开通）")
    elif code == 99991661:
        print("  ✅ im:message 权限正常（chat_id不存在是预期错误）")
    else:
        print(f"  ⚠️ code={code} msg={msg}")

# 3. 检查事件订阅列表
print("\n[3] 事件订阅（通过API无法直接查询，需网页端确认）")
print("  ⚠️ 飞书API不提供事件订阅查询接口")
print("  请在网页端检查：事件与回调 → 事件配置")

print("\n" + "=" * 60)
print("网页端检查步骤")
print("=" * 60)
print("""
打开浏览器 → https://open.feishu.cn → 登录 → 开发者后台

找到你的应用（App ID: """ + settings.feishu_app_id[:12] + """...）→ 点击进入

━━━ 步骤① 检查事件订阅 ━━━
左侧菜单 → 「事件与回调」→「事件配置」
  ✗ 确认订阅方式 = 「使用长连接接收事件」
    （如果显示的是「将事件发送至开发者服务器」= Webhook模式，需要切换）
  ✗ 在已订阅事件列表中找到：
    「接收消息 im.message.receive_v1」
    （如果没有 → 点「添加事件」→ 搜索"接收消息"→ 添加）
  ✗ 添加后需要点右上角「创建版本并发布」才能生效

━━━ 步骤② 检查权限 ━━━
左侧菜单 → 「权限管理」
  搜索框输入 im:message
  ✗ 确认「获取与发送单聊、群组消息」状态 = 已开通
  ✗ 如果显示「未开通」→ 点开通 → 需要重新发布版本

━━━ 步骤③ 检查应用状态 ━━━
左侧菜单 → 「版本管理与发布」
  ✗ 确认最新版本状态 = 「已上线」（不是审核中/已撤回）
  ✗ 如果有未发布的变更 → 创建新版本 → 提交发布

━━━ 步骤④ 确认机器人在群里 ━━━
回到飞书 → 你的群 → 设置 → 群机器人
  ✗ 确认列表里有你的「应用机器人」（不是自定义机器人）
  ✗ 如果没有 → 添加机器人 → 搜索你的应用名 → 添加

━━━ 完成后 ━━━
全部检查完 → 在群里 @机器人 发「我的ID」测试
""")
