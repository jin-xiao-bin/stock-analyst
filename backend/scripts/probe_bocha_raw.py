"""原始 API 诊断：查看 403 响应体"""
import httpx

from app.config import settings

r = httpx.post(
    "https://api.bochaai.com/v1/web-search",
    headers={"Authorization": f"Bearer {settings.bocha_api_key}",
             "Content-Type": "application/json"},
    json={"query": "拓普集团", "count": 3, "freshness": "oneMonth"},
    timeout=20,
)
print("status:", r.status_code)
print("body:", r.text[:500])
