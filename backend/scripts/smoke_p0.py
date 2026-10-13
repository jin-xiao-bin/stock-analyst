"""P0 全量 E2E 验收"""
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8300/api"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


# P0-2 参数寻优（EMA fast 5-9×4 / slow 15-25×3 = 12组合）
r = call("POST", "/strategies/1/scan", {
    "ts_code": "601689.SH", "start_date": "2025-01-01", "end_date": "2026-09-30",
    "grid": [{"name": "fast", "start": 5, "end": 9, "step": 2},
             {"name": "slow", "start": 15, "end": 25, "step": 5}]})
print(f"scan started: id={r['scan_id']} combos={r['total_combos']}")
sid = r["scan_id"]
for _ in range(60):
    time.sleep(3)
    s = call("GET", f"/strategies/scans/{sid}")
    if s["status"] != "running":
        break
print(f"scan done: status={s['status']} results={len(s.get('results') or [])}")
if s.get("best"):
    print(f"  best: {s['best']['params']} return={s['best']['metrics']['total_return']:.2%}")
    print(f"  diagnosis: overfit={s['best']['diagnosis']['overfit_risk']}, "
          f"decay={s['best']['diagnosis']['neighbor_mean_decay']}")
if s.get("heat"):
    h = s["heat"]
    print(f"  heat: {h['x_name']}×{h['y_name']} {len(h['x_vals'])}×{len(h['y_vals'])} matrix")

# P0-3 事件注入
print("\nupcoming_events(601689):", call("GET", "/agent/status")[0]["stocks"][:1] if call("GET", "/agent/status") else "no config")
