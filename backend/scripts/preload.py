"""P0-5：预置沪深300成分股数据（可选，消除冷启动空白期）
用法: cd backend && python scripts/preload.py
耗时约 300×2s ≈ 10分钟（中转限流下），进度实时打印"""
import sys
import time

from app.db import SessionLocal
from app.services.market_sync import sync_stock_basic, sync_index


def main():
    db = SessionLocal()
    try:
        print("① 同步股票列表…")
        n = sync_stock_basic(db)
        db.commit()
        print(f"   {n} 只股票")

        print("② 同步沪深300指数基准…")
        n = sync_index(db)
        db.commit()
        print(f"   {n} 行")

        print("③ 拉取全部A股日线（懒加载预热，可 Ctrl+C 中断，已拉的保留）…")
        from app.models import StockBasic
        from sqlalchemy import select
        codes = db.scalars(select(StockBasic.ts_code)).all()
        done = 0
        for code in codes:
            done += 1
            try:
                from app.services.market_sync import sync_daily
                r = sync_daily(db, code, incremental=True)
                db.commit()
                if done % 20 == 0 or done == len(codes):
                    print(f"   [{done}/{len(codes)}] {code}: {r['rows']} 行 ({r['mode']})")
            except Exception as e:  # noqa: BLE001
                db.rollback()
                print(f"   [{done}/{len(codes)}] {code} 失败: {str(e)[:60]}")
            time.sleep(0.3)
        print("✅ 预置完成")
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
