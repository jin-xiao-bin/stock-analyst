"""策略回放 E2E：创建会话→挂载策略→推进→验证策略自动交易"""
import json
import urllib.request

BASE = "http://127.0.0.1:8300/api"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


# 1. 创建回放（601689 从 2025-06-01）
s = call("POST", "/replay", {"ts_code": "601689.SH", "start_date": "2025-06-01",
                             "initial_cash": 1000000, "name": "策略回放测试"})
sid = s["id"]
print("session:", sid, "cursor:", s["cursor_date"])

# 2. 挂载策略 #1（EMA金叉死叉）
b = call("POST", f"/replay/{sid}/strategy", {"strategy_id": 1})
print("bind:", b)

# 3. 快进 60 交易日
d = call("POST", f"/replay/{sid}/next", {"days": 60})
print("advanced to:", d["session"]["cursor_date"])
strat_trades = [t for t in d["trades"] if t["source"] == "strategy"]
print("strategy trades:", len(strat_trades))
for t in strat_trades[:4]:
    print(f"  {t['trade_date']} {t['side']} {t['qty']}@{t['price']} note={t['note'][:40]}")
print("account:", {k: round(v, 2) for k, v in d["account"].items()})

# 4. 再推进 40 天，验证增量不重复
d2 = call("POST", f"/replay/{sid}/next", {"days": 40})
strat2 = [t for t in d2["trades"] if t["source"] == "strategy"]
dates = [t["trade_date"] for t in strat2]
print("after 2nd advance: strategy trades total:", len(strat2),
      "duplicates:", len(dates) != len(set(dates)))
# 卸载
print("unbind:", call("DELETE", f"/replay/{sid}/strategy"))
# 清理测试会话
print("delete:", call("DELETE", f"/replay/{sid}"))
