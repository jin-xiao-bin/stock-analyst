"""调试东财新闻搜索 jsonp"""
import json

import httpx

param = {
    "uid": "", "keyword": "平安银行", "type": ["cmsArticleWebOld"],
    "client": "web", "clientType": "web", "clientVersion": "curr",
    "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                    "pageIndex": 1, "pageSize": 5, "preTag": "", "postTag": ""}},
}
url = "https://search-api-web.eastmoney.com/search/jsonp"
r = httpx.get(url, params={"cb": "cb", "param": json.dumps(param, ensure_ascii=False)}, timeout=15)
print("status:", r.status_code)
print("head:", r.text[:300])
