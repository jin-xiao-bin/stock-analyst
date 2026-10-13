"""P0 各项严格自测"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")

passed = failed = 0

def check(name, cond, detail=""):
    global passed, failed
    s = "PASS" if cond else "FAIL"
    print(f"  {s} {name}" + (f": {detail}" if detail else ""))
    if cond:
        passed += 1
    else:
        failed += 1


# ================= P0-1 基准线 =================
print("\n=== P0-1 回测基准线 ===")
from app.db import SessionLocal
from app.models import BacktestRun, IndexDaily
from sqlalchemy import select, func
db = SessionLocal()

idx_count = db.scalar(select(func.count()).select_from(IndexDaily))
check("指数数据已落库", idx_count > 0, f"{idx_count} 行")

# 最近一次回测是否含 benchmark 指标
runs = db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(3)).all()
has_bm = any(r.metrics and "excess_return" in (r.metrics or {}) for r in runs)
check("回测含超额收益指标", has_bm)

# 直接调 _benchmark_curve 验证
from app.services.backtest_engine import _benchmark_curve
bars = [{"date": "2026-01-05"}, {"date": "2026-01-06"}]
bm = _benchmark_curve(db, bars, 1_000_000)
check("_benchmark_curve 返回数据", len(bm) > 0, f"{len(bm)} 点")
db.close()

# ================= P0-3 事件日历 =================
print("\n=== P0-3 事件日历 ===")
db = SessionLocal()
from app.models import EventCalendar
ev_count = db.scalar(select(func.count()).select_from(EventCalendar))
print(f"  事件日历条数: {ev_count}（可能为0，因为 Tushare token 过期无法同步）")

from app.services.event_sync import upcoming_events
evs = upcoming_events(db, "601689.SH", days=5)
check("upcoming_events 不报错", isinstance(evs, list), f"{len(evs)} 条")
db.close()

# ================= P0-4 组合风控 =================
print("\n=== P0-4 组合风控 R7/R8/R9 ===")
from app.services.agent.risk import DEFAULT_RISK, check as risk_check
check("R7 行业集中度参数存在", "max_industry_pct" in DEFAULT_RISK)
check("R8 分散度参数存在", "min_holdings" in DEFAULT_RISK)
check("R9 账户熔断参数存在", "account_drawdown_halt" in DEFAULT_RISK)

# 参数归一化测试（UI传30表示30%）
from app.services.agent.risk import _params
class FakeConfig:
    risk_params = {"max_pos_pct": 30, "max_industry_pct": 40, "account_drawdown_halt": 20}
p = _params(FakeConfig())
check("百分比参数归一化(30→0.3)", p["max_pos_pct"] == 0.3)
check("行业百分比归一化(40→0.4)", p["max_industry_pct"] == 0.4)
check("熔断百分比归一化(20→0.2)", p["account_drawdown_halt"] == 0.2)

# ================= P0-2 参数寻优 =================
print("\n=== P0-2 参数寻优 ===")
from app.services.param_scan import _param_space, diagnose_overfit
grid = [{"name": "fast", "start": 5, "end": 9, "step": 2},
        {"name": "slow", "start": 15, "end": 25, "step": 5}]
combos = _param_space(grid)
check("网格展开正确", len(combos) == 9, f"{len(combos)} 组合")

# 过拟合诊断
results = [
    {"params": {"fast": 5, "slow": 20}, "metrics": {"total_return": 0.10}},
    {"params": {"fast": 7, "slow": 20}, "metrics": {"total_return": 0.01}},
    {"params": {"fast": 5, "slow": 15}, "metrics": {"total_return": 0.02}},
    {"params": {"fast": 5, "slow": 25}, "metrics": {"total_return": 0.03}},
    {"params": {"fast": 7, "slow": 15}, "metrics": {"total_return": 0.01}},
    {"params": {"fast": 7, "slow": 25}, "metrics": {"total_return": 0.005}},
]
diag = diagnose_overfit(results, grid)
check("孤峰检测（best=10%, 邻域~1%）", diag["overfit_risk"] is True,
      f"decay={diag['neighbor_mean_decay']}")

# 平原场景
results2 = [
    {"params": {"fast": 5, "slow": 20}, "metrics": {"total_return": 0.10}},
    {"params": {"fast": 7, "slow": 20}, "metrics": {"total_return": 0.09}},
    {"params": {"fast": 5, "slow": 15}, "metrics": {"total_return": 0.095}},
    {"params": {"fast": 5, "slow": 25}, "metrics": {"total_return": 0.092}},
]
diag2 = diagnose_overfit(results2, grid)
check("平原不误报", diag2["overfit_risk"] is False,
      f"decay={diag2['neighbor_mean_decay']}")

# ================= P0-7 周报 =================
print("\n=== P0-7 周报 ===")
from app.services.weekly_report import build_report
report = build_report()
check("周报数据构建成功", report is not None and "decisions_total" in report,
      f"本周{report['decisions_total']}次决策" if report else "None")

# ================= P0-8 单测已验证 =================
print(f"\n{'='*40}")
print(f"总计: {passed}/{passed+failed} passed, {failed} failed")
