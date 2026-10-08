"""探测 Tushare 公告/新闻类接口在当前 token(中转5000档)下的可用性"""
from app.services.tushare_client import client

probes = [
    ("anns", dict(ts_code="000001.SZ", start_date="20240101", end_date="20240301")),
    ("major_notice", dict(ts_code="000001.SZ", start_date="20240101", end_date="20240301")),
    ("news", dict(src="sina", start_date="2024-01-15 09:00:00", end_date="2024-01-15 10:00:00")),
]
for name, kwargs in probes:
    try:
        df = client.query(name, retries=1, **kwargs)
        print(f"{name}: OK rows={len(df)} cols={list(df.columns)[:6]}")
    except Exception as e:  # noqa: BLE001
        print(f"{name}: FAIL -> {str(e)[:200]}")
