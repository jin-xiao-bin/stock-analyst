"""M4 策略中心 API 验收：CRUD + validate + 回测"""
import json
import urllib.request

BASE = "http://127.0.0.1:8300/api"


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


CODE = """
def init(ctx):
    pass

def on_bar(ctx, bar, i):
    if i < 25:
        return
    fast = ctx.ema(5)
    slow = ctx.ema(20)
    if ctx.crossover(fast, slow, i):
        ctx.buy(ratio=0.95, reason='golden_cross')
    elif ctx.crossunder(fast, slow, i):
        ctx.sell_all(reason='death_cross')
"""

# 1. 创建策略
st, r = call("POST", "/strategies", {"name": "EMA金叉死叉", "code": CODE, "source": "manual"})
print("create:", st, "id:", r.get("id"))
sid = r["id"]

# 2. validate
st, r = call("POST", f"/strategies/{sid}/validate", {})
print("validate:", st, r)

# 3. 回测
st, r = call("POST", "/backtests", {"strategy_id": sid, "ts_code": "000001.SZ",
                                    "start_date": "2025-01-01", "end_date": "2026-09-30"})
print("backtest:", st, "status:", r.get("status"), "metrics:", json.dumps(r.get("metrics", {}), ensure_ascii=False))

# 4. 回测历史
st, r = call("GET", f"/backtests?strategy_id={sid}")
print("backtest list:", st, "runs:", len(r))

# 5. 挂机绑定（用 M2 冒烟的账户1）
st, r = call("POST", f"/strategies/{sid}/bind", {"account_id": 1, "ts_codes": ["000001.SZ"]})
print("bind:", st, r)
