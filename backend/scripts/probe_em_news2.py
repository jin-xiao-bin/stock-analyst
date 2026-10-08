"""东财新闻搜索：POST 与无cb JSON 两种形式"""
import json

import httpx

param = {
    "uid": "", "keyword": "平安银行", "type": ["cmsArticleWebOld"],
    "client": "web", "clientType": "web", "clientVersion": "curr",
    "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "default",
                                    "pageIndex": 1, "pageSize": 5, "preTag": "<em>", "postTag": "</em>"}},
}
pjson = json.dumps(param, ensure_ascii=False)

# 形式1: POST form
try:
    r = httpx.post("https://search-api-web.eastmoney.com/search/jsonp",
                   data={"param": pjson}, timeout=15,
                   headers={"Content-Type": "application/x-www-form-urlencoded"})
    print("POST status:", r.status_code, "len:", len(r.text))
    print("POST head:", r.text[:200])
except Exception as e:  # noqa: BLE001
    print("POST FAIL:", e)

# 形式2: GET 无cb（纯JSON）
try:
    r2 = httpx.get("https://search-api-web.eastmoney.com/search/jsonp",
                   params={"param": pjson, "cb": ""}, timeout=15)
    print("GET-nocb status:", r2.status_code, "len:", len(r2.text))
    print("GET-nocb head:", r2.text[:200])
except Exception as e:  # noqa: BLE001
    print("GET-nocb FAIL:", e)
