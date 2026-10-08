import json
import urllib.request


def chat(text, confirm=False):
    body = {"text": text, "confirm": confirm}
    req = urllib.request.Request("http://127.0.0.1:8300/api/pet/chat", method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["text"]


r1 = chat("买入 601689 500")
print("1 pending:", r1[:90].replace("\n", " "))
# 协议：重发原始指令文本 + confirm=True（宠物客户端 pet_widget 的实现方式）
r2 = chat("买入 601689 500", confirm=True)
print("2 confirmed:", r2[:140])
