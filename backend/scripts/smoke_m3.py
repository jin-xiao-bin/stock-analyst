"""M3 端到端：真实 DeepSeek 分析 SSE 流验收"""
import json
import urllib.request

url = "http://127.0.0.1:8300/api/analysis/000001.SZ"
req = urllib.request.Request(url, method="POST", data=b"{}", headers={"Accept": "text/event-stream"})
events = []
with urllib.request.urlopen(req, timeout=600) as resp:
    cur_event = None
    for raw in resp:
        line = raw.decode("utf-8").rstrip("\n")
        if line.startswith("event:"):
            cur_event = line[6:].strip()
        elif line.startswith("data:") and cur_event:
            try:
                payload = json.loads(line[5:].strip())
            except Exception:  # noqa: BLE001
                payload = line[5:].strip()
            events.append((cur_event, payload))
            cur_event = None

for ev, data in events:
    if ev == "status":
        print("STATUS", data.get("stage"), "-", str(data.get("msg"))[:60])
    elif ev == "section":
        print("SECTION", data.get("role"), "title:", str(data.get("title"))[:40], "len:", len(str(data.get("content", ""))))
    elif ev == "done":
        print("DONE report_id:", data.get("report_id"), "watch_tasks:", len(data.get("watch_tasks", [])))
        for t in data.get("watch_tasks", [])[:5]:
            print("  task:", json.dumps(t, ensure_ascii=False)[:150])
    elif ev == "error":
        print("ERROR", str(data)[:200])
print("total events:", len(events))
