"""东财新闻搜索：带浏览器头重试"""
import json

import httpx

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Referer": "https://so.eastmoney.com/",
}
param = {
    "uid": "", "keyword": "平安银行", "type": ["cmsArticleWebOld"],
    "client": "web", "clientType": "web", "clientVersion": "curr",
    "param": {"cmsArticleWebOld": {"searchScope": "default", "sort": "time",
                                    "pageIndex": 1, "pageSize": 5, "preTag": "", "postTag": ""}},
}
pjson = json.dumps(param, ensure_ascii=False)
r = httpx.get("https://search-api-web.eastmoney.com/search/jsonp",
              params={"cb": "jQuery1", "param": pjson}, timeout=15, headers=HEADERS)
print("status:", r.status_code, "len:", len(r.text))
print("head:", r.text[:250])
if r.text.startswith("jQuery1("):
    d = json.loads(r.text[len("jQuery1("):-1])
    arts = (d.get("result") or {}).get("cmsArticleWebOld") or []
    print("rows:", len(arts))
    for a in arts[:3]:
        print(" -", a.get("date", "")[:10], a.get("title", "")[:45])
