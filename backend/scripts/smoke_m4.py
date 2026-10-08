"""M4 沙箱+回测冒烟：金叉死叉策略跑 000001.SZ"""
from app.db import SessionLocal
from app.services.backtest_engine import run_backtest

CODE = """
def init(ctx):
    pass

def on_bar(ctx, bar, i):
    if i < 25:
        return
    fast = ctx.ema(5)
    slow = ctx.ema(20)
    if ctx.crossover(fast, slow, i):
        ctx.buy(ratio=0.95, reason='golden_cross')
    elif ctx.crossunder(fast, slow, i):
        ctx.sell_all(reason='death_cross')
"""

BAD_CODE = """
def init(ctx):
    import os
    os.system('echo hacked')

def on_bar(ctx, bar, i):
    pass
"""

db = SessionLocal()
try:
    # 1. 危险代码必须被拦截
    r = run_backtest(db, BAD_CODE, {}, "000001.SZ", "2024-01-01", "2024-12-31", 1_000_000)
    blocked = r.get("status") == "failed"
    print("sandbox-block:", "PASS" if blocked else "FAIL!", str(r.get("error", ""))[:100])
    db.rollback()

    # 2. 正常策略回测
    r = run_backtest(db, CODE, {}, "000001.SZ", "2025-10-09", "2026-09-30", 1_000_000)
    print("backtest status:", r["status"])
    if r["status"] == "success":
        m = r["metrics"]
        print("metrics:", {k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()})
        print("trades:", len(r.get("trades", [])), "equity points:", len(r.get("equity_curve", [])))
    else:
        print("error:", r.get("error", "")[:200])
finally:
    db.close()
