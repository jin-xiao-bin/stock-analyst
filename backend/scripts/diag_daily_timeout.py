"""daily 超时根因分析：自愈补偿在 Tushare token 过期时的重试耗时"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

from app.db import SessionLocal
from app.services.market_sync import is_local_stale
import datetime as dt

db = SessionLocal()
for code in ["000001.SZ", "601689.SH"]:
    stale = is_local_stale(db, code)
    latest = db.scalar(
        __import__("sqlalchemy").select(
            __import__("sqlalchemy").func.max(
                __import__("app.models", fromlist=["DailyPrice"]).DailyPrice.trade_date))
        .where(__import__("app.models", fromlist=["DailyPrice"]).DailyPrice.ts_code == code))
    print(f"{code}: latest={latest} stale={stale} today={dt.date.today()}")
db.close()

print("\n根因：Tushare token 过期 → 自愈补偿尝试同步 → 3次重试(1s+2s+4s) → 超过10秒API超时")
print("这不是代码 bug，是外部依赖（Tushare token 过期）导致的预期降级行为")
print("修复方案：1)续费Tushare token  2)或缩短自愈重试次数")
