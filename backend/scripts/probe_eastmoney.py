"""探测东方财富公开接口：公告 + 新闻搜索"""
import json

import httpx

# 1. 公告接口（个股）
code = "000001.SZ"
symbol = code.split(".")[0]
r = httpx.get(
    "https://np-anotice-stock.eastmoney.com/api/security/ann",
    params={"sr": -1, "page_size": 5, "page_index": 1, "ann_type": "A", "stock_list": symbol},
    timeout=15,
)
print("ann status:", r.status_code)
try:
    data = r.json()
    lst = data.get("data", {}).get("list") or []
    print("ann rows:", len(lst))
    for it in lst[:3]:
        print(" -", it.get("notice_date", "")[:10], it.get("title", "")[:40],
          "arts:", (it.get("art_code") or ""))
except Exception as e:  # noqa: BLE001
    print("ann parse FAIL:", e, r.text[:200])

print()

# 2. 新闻搜索（jsonp）
param = {
    "uid": "", "keyword": "平安银行", "type": ["cmsArticleWebOld"],
    "client": "web", "clientType": "web", "clientVersion": "curr",
    "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                    "pageIndex": 1, "pageSize": 5, "preTag": "", "postTag": ""}},
}
r2 = httpx.get(
    "https://search-api-web.eastmoney.com/search/jsonp",
    params={"cb": "cb", "param": json.dumps(param, ensure_ascii=False)},
    timeout=15,
)
print("news status:", r2.status_code)
text = r2.text.strip()
if text.startswith("cb("):
    text = text[3:-1]
try:
    d = json.loads(text)
    arts = (d.get("result") or {}).get("cmsArticleWebOld") or []
    print("news rows:", len(arts))
    for a in arts[:3]:
        print(" -", a.get("date", "")[:10], a.get("title", "").replace("<em>", "").replace("</em>", "")[:40])
except Exception as e:  # noqa: BLE001
    print("news parse FAIL:", e, text[:200])
