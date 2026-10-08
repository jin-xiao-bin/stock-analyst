"""M2 回放交易功能冒烟测试"""
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

# 1. 创建回放会话（平安银行，2024-01-02 起，初始 100 万）
r = c.post("/api/replay", json={"ts_code": "000001.SZ", "start_date": "2024-01-02", "initial_cash": 1000000})
print("create:", r.status_code, r.json().get("id"), r.json().get("cursor_date"))
sid = r.json()["id"]

# 2. 推进 5 天
r = c.post(f"/api/replay/{sid}/next", json={"days": 5})
d = r.json()
print("next5:", r.status_code, "cursor:", d["session"]["cursor_date"], "cash:", d["account"]["cash"])

# 3. 买入 10000 股
r = c.post(f"/api/replay/{sid}/order", json={"side": "buy", "qty": 10000})
print("buy:", r.status_code, "cash:", r.json().get("account", {}).get("cash"), "pos:", r.json().get("positions"))

# 4. 当日卖出应被 T+1 拒绝
r = c.post(f"/api/replay/{sid}/order", json={"side": "sell", "qty": 10000})
print("sell-same-day (expect 400):", r.status_code, r.json().get("detail", "")[:50])

# 5. 推进 3 天后卖出
c.post(f"/api/replay/{sid}/next", json={"days": 3})
r = c.post(f"/api/replay/{sid}/order", json={"side": "sell", "qty": 10000})
print("sell:", r.status_code, "cash:", r.json().get("account", {}).get("cash"))

# 6. 汇总 + 交易记录 + 账户
r = c.get(f"/api/replay/{sid}/summary")
print("summary:", r.status_code, {k: v for k, v in r.json().items() if k != "trades"})
r = c.get("/api/trades?page_size=10")
print("trades:", r.status_code, "total:", r.json().get("total"))
r = c.get("/api/accounts")
print("accounts:", r.status_code, len(r.json()))
