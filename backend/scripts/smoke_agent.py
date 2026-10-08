"""Agent 自主交易 E2E：setup → start → 手动盘中决策 → 校验留痕/风控/成交"""
import json
import urllib.request

BASE = "http://127.0.0.1:8300/api"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


# 1. setup（10万，稳健，000001.SZ，参考策略#1）
r = call("POST", "/agent/setup", {
    "stocks": ["000001.SZ"], "initial_cash": 100000,
    "style": "steady", "patrol_freq": 60,
    "risk_params": None, "reference_strategies": {"000001.SZ": [1]}})
print("setup:", r["status"], "account:", r["account"])
sid = r["id"]

# 2. start
print("start:", call("POST", "/agent/start"))

# 3. 手动盘中决策（真实 LLM）
r = call("POST", "/agent/run", {"ts_code": "000001.SZ", "mode": "intraday"})
res = r["results"][0]
print("intraday:", res)

# 4. 收盘深度决策
r = call("POST", "/agent/run", {"ts_code": "000001.SZ", "mode": "daily"})
res = r["results"][0]
print("daily:", res)

# 5. 决策流水与详情
d = call("GET", "/agent/decisions?page_size=10")
print("decisions total:", d["total"])
for it in d["items"]:
    print(f"  #{it['id']} {it['run_time']} {it['ts_code']} {it['decision_type']} "
          f"{it['action']}/{it['status']} qty={it['qty']} risk={it['risk_note']}")
if d["items"]:
    detail = call("GET", f"/agent/decisions/{d['items'][0]['id']}")
    print("detail: analysis len:", len(detail.get("analysis_md") or ""),
          "inputs keys:", list((detail.get("inputs_snapshot") or {}).keys())[:6])

# 6. 状态与曲线
st = call("GET", "/agent/status")[0]
print("status:", st["status"], st["account"], "positions:", len(st["positions"]))
eq = call("GET", "/agent/equity")
print("equity points:", len(eq), eq[-1] if eq else None)
