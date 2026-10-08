"""双通道新闻聚合验证"""
from app.services import news_source

print("=== get_news(000001.SZ 平安银行) ===")
items = news_source.get_news("000001.SZ", "平安银行", count=10)
print("total:", len(items))
for it in items[:6]:
    print(f"  [{it['source']}] {it['date']} {it['title'][:45]}")

print("=== verify_search(000001.SZ 分红) ===")
v = news_source.verify_search("000001.SZ 分红 派息", count=5)
print("total:", len(v))
for it in v[:3]:
    print(f"  [{it['source']}] {it['date']} {it['title'][:45]}")
