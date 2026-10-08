"""对比测试：中转 vs 官方端点的 news 接口"""
import time

import tushare as ts

token = "939cdb5accb807501e243533e037081aa04831e10eed10dcbf3e3d946aac"
kw = dict(src="sina", start_date="2024-01-15 09:00:00", end_date="2024-01-15 10:00:00")

for label, url in [("中转 tuaremax", "https://tuaremax.top"),
                   ("官方 api.tushare.pro", "https://api.tushare.pro")]:
    pro = ts.pro_api(token)
    pro._DataApi__token = token
    pro._DataApi__http_url = url
    try:
        df = pro.news(**kw)
        print(f"{label}: OK rows={len(df)}")
        if len(df):
            print("  sample:", df.iloc[0].get("title", "")[:40])
    except Exception as e:  # noqa: BLE001
        print(f"{label}: FAIL -> {str(e)[:120]}")
    time.sleep(3)
