"""M6 自回归闭环验收：注入建议 -> apply -> 新版本+对比回测"""
import json
import urllib.request

BASE = "http://127.0.0.1:8300/api"

# 1. 给 review 1 注入一条 param_adjust 建议
from app.db import SessionLocal
from app.models import TradeReview

db = SessionLocal()
rv = db.get(TradeReview, 1)
rv.suggestions = [{
    "type": "param_adjust",
    "detail": "EMA5/20 参数过于敏感导致频繁交易(18笔仅22%胜率)，建议放慢快线并加长期趋势过滤",
    "proposed_action": "将 EMA5/EMA20 调整为 EMA10/EMA60，降低交易频率",
}]
db.commit()
print("suggestion injected")
db.close()

# 2. 调 apply
req = urllib.request.Request(f"{BASE}/reviews/1/apply", method="POST",
                             data=json.dumps({"suggestion_index": 0}).encode(),
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=900) as r:
    res = json.loads(r.read())
print("apply status keys:", list(res.keys()))
for k in ("new_strategy_id", "old_run_id", "new_run_id"):
    print(k, "=", res.get(k))
vn = res.get("version_note", "")
print("version_note len:", len(vn))
print(vn[:400])

# 3. 查版本链
with urllib.request.urlopen(f"{BASE}/strategies", timeout=60) as r:
    strategies = json.loads(r.read())
for s in strategies:
    print(f"strategy#{s['id']} {s['name']} v{s.get('version_no')} parent={s.get('parent_id')} source={s['source']} status={s['status']}")
