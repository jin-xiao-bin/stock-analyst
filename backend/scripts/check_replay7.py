import json
import urllib.request

d = json.loads(urllib.request.urlopen(
    "http://127.0.0.1:8300/api/replay/7", timeout=30).read())
print("session:", d["session"])
print("bars last3:", [b["date"] for b in d["bars"][-3:]])
print("trades returned:")
for t in d["trades"]:
    print(" ", t["trade_date"], t["side"], t["qty"], "@", t["price"], t.get("source"))
