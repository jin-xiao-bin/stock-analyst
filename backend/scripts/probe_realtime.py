"""探测中转(tuaremax)对 Tushare 实时类接口的支持度"""
import tushare as ts

TOKEN = "939cdb5accb807501e243533e037081aa04831e10eed10dcbf3e3d946aac"
URL = "https://tuaremax.top"

pro = ts.pro_api(TOKEN)
pro._DataApi__token = TOKEN
pro._DataApi__http_url = URL

# 实时相关接口逐个探测
probes = [
    ("realtime_quote", dict(ts_code="000001.SZ")),           # 实时行情(新浪/东财源)
    ("rt_k", dict(ts_code="000001.SZ")),                      # 实时分钟线
    ("realtime_tick", dict(ts_code="000001.SZ", trade_date="20260930")),  # 实时盘口TICK
    ("stk_mins", dict(ts_code="000001.SZ", freq="5min", start_date="2026-09-30 09:00:00", end_date="2026-09-30 15:00:00")),  # 分钟线(历史)
    ("daily_basic", dict(ts_code="000001.SZ", start_date="20260928", end_date="20260930")),  # 每日指标(估值)
]
for name, kw in probes:
    try:
        df = getattr(pro, name)(**kw)
        if df is None or len(df) == 0:
            print(f"{name}: EMPTY (0 rows)")
        else:
            print(f"{name}: OK rows={len(df)} cols={list(df.columns)[:8]}")
            if name == "realtime_quote":
                row = df.iloc[0].to_dict()
                for k in list(row)[:10]:
                    print(f"    {k}: {row[k]}")
    except Exception as e:  # noqa: BLE001
        print(f"{name}: FAIL -> {str(e)[:110]}")
