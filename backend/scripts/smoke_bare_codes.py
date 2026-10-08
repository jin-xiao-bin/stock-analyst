"""裸6位代码全接口验证（不实际触发LLM，只验证解析和查询路径）"""
import json
import urllib.request

BASE = "http://127.0.0.1:8300/api"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=120) as r:
        return json.loads(r.read())


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, method=method, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())


ok = fail = 0


def check(name, cond):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + name)
    ok, fail = ok + (1 if cond else 0), fail + (0 if cond else 1)


# 1. 日线（裸 000001 → 000001.SZ）
d = get("/stocks/000001/daily?start=2024-01-01&end_date=2024-01-31&adjust=none"
        .replace("end_date", "end"))
check("daily bare 000001", len(d) > 15)

# 2. 实时
r = get("/stocks/601689/realtime")
check("realtime bare 601689 (SH纠错)", r.get("price") is not None)

# 3. 财务
f = get("/stocks/000001/finance")
check("finance bare", isinstance(f, list))

# 4. markers
m = get("/stocks/000001/markers")
check("markers bare", isinstance(m, list))

# 5. 交易记录筛选
t = get("/trades?ts_code=000001&page_size=5")
check("trades filter bare", t["total"] >= 1)

# 6. 任务筛选
w = get("/watch-tasks?ts_code=000001&page_size=5")
check("watch-tasks filter bare", w["total"] >= 1)

# 7. 回放创建（裸代码）
s = call("POST", "/replay", {"ts_code": "601689", "start_date": "2025-01-02",
                             "initial_cash": 200000, "name": "裸代码测试"})
check("replay create bare", s["ts_code"] == "601689.SH")
call("DELETE", f"/replay/{s['id']}")

# 8. agent setup（裸+去重）与决策筛选
a = call("POST", "/agent/setup", {"stocks": ["000001", "601689.SH"],
                                  "reference_strategies": {"000001": [1]}})
check("agent setup bare normalize", a["stocks"] == ["000001.SZ", "601689.SH"]
      and list(a["reference_strategies"].keys()) == ["000001.SZ"])
dd = get("/agent/decisions?ts_code=000001&page_size=5")
check("agent decisions filter bare", dd["total"] >= 1)
# 恢复原股票池
call("POST", "/agent/setup", {"stocks": ["000001.SZ"],
                              "reference_strategies": {"000001.SZ": [1]}})

# 9. 后缀纠错（错误后缀 SZ→SH）
d2 = get("/stocks/601689.SZ/daily?start=2026-09-01&end=2026-09-30")
check("daily wrong-suffix fix", len(d2) > 10)

# 10. 不存在代码 400
try:
    get("/stocks/999999/finance")
    check("invalid code 400", False)
except Exception:
    check("invalid code 400", True)

print(f"\n{ok} pass / {fail} fail")
