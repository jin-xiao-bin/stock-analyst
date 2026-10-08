"""realtime_quote 轮询压力测试：10次快速调用看限频"""
import time

import tushare as ts

TOKEN = "939cdb5accb807501e243533e037081aa04831e10eed10dcbf3e3d946aac"
pro = ts.pro_api(TOKEN)
pro._DataApi__token = TOKEN
pro._DataApi__http_url = "https://tuaremax.top"

ok = fail = 0
errs = set()
t0 = time.time()
for i in range(10):
    try:
        df = pro.realtime_quote(ts_code="000001.SZ")
        ok += 1 if len(df) else 0
        time.sleep(1)
    except Exception as e:  # noqa: BLE001
        fail += 1
        errs.add(str(e)[:80])
        time.sleep(3)
print(f"10次调用: 成功={ok} 失败={fail} 耗时={time.time()-t0:.0f}s")
for e in errs:
    print("  err:", e)

# 批量能力：一次多只
try:
    df = pro.realtime_quote(ts_code="000001.SZ,601689.SH,600519.SH")
    print(f"批量3只: rows={len(df)} -> {list(df['ts_code'])}")
except Exception as e:  # noqa: BLE001
    print("批量 FAIL:", str(e)[:100])
