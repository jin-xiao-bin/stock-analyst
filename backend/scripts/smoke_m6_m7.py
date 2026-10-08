"""M6 审查 SSE + M7 挂机执行 验收"""
import json
import urllib.request

BASE = "http://127.0.0.1:8300/api"


def sse(path, body):
    req = urllib.request.Request(BASE + path, method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"Accept": "text/event-stream", "Content-Type": "application/json"})
    out = []
    with urllib.request.urlopen(req, timeout=900) as resp:
        cur = None
        for raw in resp:
            line = raw.decode("utf-8").rstrip("\n")
            if line.startswith("event:"):
                cur = line[6:].strip()
            elif line.startswith("data:") and cur:
                try:
                    out.append((cur, json.loads(line[5:].strip())))
                except Exception:  # noqa: BLE001
                    out.append((cur, line[5:].strip()))
                cur = None
    return out


# 1. 对账户1（含 M2 手动交易）发起审查
print("=== 交易审查 SSE ===")
for ev, d in sse("/reviews", {"account_id": 1, "scope": "all"}):
    if ev == "status":
        print("STATUS", str(d)[:60])
    elif ev == "section":
        print("SECTION len:", len(str(d.get("content", ""))))
    elif ev == "done":
        print("DONE review_id:", d.get("review_id"), "suggestions:", len(d.get("suggestions", [])))
        for s in d.get("suggestions", []):
            print("  -", s.get("type"), ":", str(s.get("detail"))[:60])
    elif ev == "error":
        print("ERROR", str(d)[:200])

# 2. 手动触发挂机执行（最新bar下单）
print("=== 挂机策略执行 ===")
from app.db import SessionLocal  # noqa: E402
from app.services.live_runner import run_all_bindings  # noqa: E402

db = SessionLocal()
try:
    r = run_all_bindings(db)
    print("live_runner:", json.dumps(r, ensure_ascii=False)[:300])
finally:
    db.close()
