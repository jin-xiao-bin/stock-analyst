"""独立复核回测资金曲线：trades+bars 重算 vs 引擎存的 equity_curve"""
import json

from sqlalchemy import select

from app.db import SessionLocal
from app.models import BacktestRun, DailyPrice

db = SessionLocal()
run = db.get(BacktestRun, 13)
print("status:", run.status, "metrics:", json.dumps(run.metrics, ensure_ascii=False)[:120])

trades = run.trades_json or []
curve = run.equity_curve or []
print("trades:", len(trades), "curve points:", len(curve))
print("first trade:", json.dumps(trades[0], ensure_ascii=False, default=str)[:160] if trades else None)

# 取该策略区间K线
ts_codes = run.ts_codes or []
ts_code = ts_codes[0] if ts_codes else None
bars = db.scalars(
    select(DailyPrice).where(DailyPrice.ts_code == ts_code,
                             DailyPrice.trade_date >= run.start_date,
                             DailyPrice.trade_date <= run.end_date)
    .order_by(DailyPrice.trade_date)
).all()
print("bars:", len(bars), ts_code, run.start_date, "->", run.end_date)

# 独立重算：cash + qty*close（trades 的 trade_date 必须与 bar.trade_date 精确匹配才算成交）
trades_by_date = {}
for t in trades:
    d = str(t.get("trade_date"))[:10]
    trades_by_date.setdefault(d, []).append(t)

cash = float(run.initial_cash)
q = 0
avg = 0.0
mismatch = 0
recomputed = []
for b in bars:
    d = b.trade_date.isoformat()
    for t in trades_by_date.get(d, []):
        amt, fee, qty = float(t["amount"]), float(t["fee"]), int(t["qty"])
        if t["side"] == "buy":
            q += qty
            cash -= amt + fee
        else:
            q -= qty
            cash += amt - fee
    recomputed.append(round(cash + q * float(b.close), 2))

stored = [p["equity"] for p in curve]
if len(stored) == len(recomputed):
    diffs = [(i, s, r) for i, (s, r) in enumerate(zip(stored, recomputed)) if abs(s - r) > 1]
    print("mismatched points:", len(diffs))
    for i, s, r in diffs[:5]:
        print(f"  {curve[i]['date']}: stored={s} recomputed={r}")
else:
    print("length mismatch!", len(stored), len(recomputed))
print("stored first/last:", stored[0], stored[-1])
print("recomputed first/last:", recomputed[0], recomputed[-1])
db.close()
