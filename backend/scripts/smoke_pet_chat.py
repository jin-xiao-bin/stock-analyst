"""宠物对话指令 E2E 验收"""
import json
import urllib.request

BASE = "http://127.0.0.1:8300/api/pet/chat"


def chat(text, confirm=False):
    body = {"text": text, "confirm": confirm}
    req = urllib.request.Request(BASE, method="POST", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["text"]


print("1.帮助:", chat("帮助")[:60])
print("2.行情:", chat("行情 000001")[:70])
print("3.状态:", chat("状态")[:80])
print("4.买入(待确认):", chat("买入 000001 500"))
print("5.确认执行:", chat("确认", confirm=True))
print("6.卖出全部(待确认):", chat("卖出 000001 全部"))
print("7.确认卖出:", chat("确认", confirm=True))
print("8.非指令LLM:", chat("你好，简单介绍一下你自己")[:80])
