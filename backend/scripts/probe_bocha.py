"""博查搜索连通性验证（使用 .env 中的新 key）"""
from app.config import settings
from app.services.bocha_search import web_search

print("key prefix:", settings.bocha_api_key[:8], "...")
results = web_search("拓普集团 601689 最新公告", count=3, freshness="oneMonth")
print("results:", len(results))
for r in results[:3]:
    print("-", r.get("date", "")[:10], r.get("title", "")[:50])
