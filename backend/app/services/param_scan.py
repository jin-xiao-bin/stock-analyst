"""P0-2 参数寻优引擎：网格扫描 + 过拟合诊断（参数孤峰 vs 平原）"""
import logging
from itertools import product

from sqlalchemy.orm import Session

from ..models import ParamScan, Strategy

log = logging.getLogger(__name__)


def _param_space(grid: list[dict]) -> list[dict]:
    """展开参数网格 [{name,start,end,step}] → [{name: value}]"""
    axes = []
    for g in grid:
        vals = []
        v = float(g["start"])
        while v <= float(g["end"]) + 1e-9:
            vals.append(int(v) if float(v).is_integer() else round(v, 4))
            v += float(g["step"])
        axes.append((g["name"], vals))
    if not axes:
        return [{}]
    combos = []
    for values in product(*[a[1] for a in axes]):
        combos.append(dict(zip([a[0] for a in axes], values)))
    return combos


def diagnose_overfit(results: list[dict], grid: list[dict],
                     metric_key: str = "total_return") -> dict:
    """过拟合诊断：最优点 8 邻域均值衰减 + 方差 → 孤峰/平原判定

    返回 {overfit_risk: bool, neighbor_mean_decay: float, neighbor_variance: float,
          plain_center: params 或 None}
    """
    if not results or len(grid) != 2:
        return {"overfit_risk": False, "neighbor_mean_decay": 0.0,
                "neighbor_variance": 0.0, "plain_center": None}
    lookup = {tuple(sorted(r["params"].items())): r["metrics"].get(metric_key, 0)
              for r in results}
    best_r = max(results, key=lambda r: r["metrics"].get(metric_key, 0))
    best_key = best_r["params"]
    g1, g2 = grid[0], grid[1]
    step1, step2 = float(g1["step"]), float(g2["step"])
    neighbors = []
    for dx in (-step1, 0, step1):
        for dy in (-step2, 0, step2):
            if dx == 0 and dy == 0:
                continue
            key = {g1["name"]: best_key[g1["name"]] + dx,
                   g2["name"]: best_key[g2["name"]] + dy}
            v = lookup.get(tuple(sorted(key.items())))
            if v is not None:
                neighbors.append(v)
    if not neighbors:
        return {"overfit_risk": False, "neighbor_mean_decay": 0.0,
                "neighbor_variance": 0.0, "plain_center": None}
    best_val = best_r["metrics"].get(metric_key, 0)
    n_mean = sum(neighbors) / len(neighbors)
    n_var = sum((x - n_mean) ** 2 for x in neighbors) / len(neighbors)
    decay = 1 - (n_mean / best_val) if best_val and best_val > 0 else 0.0
    # 孤峰判定：邻域衰减>50% 或邻域方差 > 最优点绝对值
    overfit = decay > 0.5 or (abs(best_val) > 0 and n_var > abs(best_val))
    # 平原中心：取邻域中位数替代极值（更稳健）
    sorted_nb = sorted(neighbors)
    plain_center = dict(best_key)
    if overfit and sorted_nb:
        # 找邻域中最大值对应的参数（在平面上移动一步）
        best_nb_val = max(neighbors)
        for dx in (-step1, 0, step1):
            for dy in (-step2, 0, step2):
                key = {g1["name"]: best_key[g1["name"]] + dx,
                       g2["name"]: best_key[g2["name"]] + dy}
                if lookup.get(tuple(sorted(key.items()))) == best_nb_val:
                    plain_center = key
                    break
    return {"overfit_risk": overfit,
            "neighbor_mean_decay": round(decay, 3),
            "neighbor_variance": round(n_var, 6),
            "plain_center": plain_center if overfit else None}


def run_scan(scan_id: int):
    """执行寻优任务（后台线程调；自管 Session）"""
    from ..db import SessionLocal
    from .backtest_engine import load_bars, SimTrader, equity_replay, compute_metrics
    from .sandbox import run_in_sandbox
    db = SessionLocal()
    try:
        scan = db.get(ParamScan, scan_id)
        if not scan:
            return
        s = db.get(Strategy, scan.strategy_id)
        if not s:
            scan.status = "failed"
            scan.error = "策略不存在"
            db.commit()
            return
        try:
            bars = load_bars(db, scan.ts_code, scan.start_date, scan.end_date)
            if not bars:
                raise RuntimeError("无区间行情数据")
        except Exception as e:  # noqa: BLE001
            scan.status = "failed"
            scan.error = str(e)
            db.commit()
            return

        combos = _param_space(scan.grid or [])
        results = []
        for params in combos:
            trader = SimTrader(bars, scan.ts_code, 1_000_000.0)
            res = run_in_sandbox(s.code, bars, trader, params)
            if not res.get("ok"):
                continue  # 该参数组合跑不通（如周期不够）
            curve = equity_replay(bars, trader.trades)
            m = compute_metrics([p["equity"] for p in curve], trader.trades, 1_000_000.0)
            results.append({"params": params, "metrics": {
                k: round(v, 6) if isinstance(v, float) else v
                for k, v in m.items() if k in ("total_return", "max_drawdown",
                                               "sharpe", "win_rate", "trade_count")}})
            scan.results = results  # 实时可见进度
            db.commit()

        if not results:
            scan.status = "failed"
            scan.error = "所有参数组合均无法运行（检查参数范围与数据量）"
            db.commit()
            return
        best = max(results, key=lambda r: r["metrics"]["total_return"])
        diag = diagnose_overfit(results, scan.grid or [])
        scan.best = {**best, "diagnosis": diag}
        # 热力矩阵（支持双参数）
        if len(scan.grid or []) == 2:
            g1, g2 = scan.grid
            x_vals = sorted({r["params"][g1["name"]] for r in results})
            y_vals = sorted({r["params"][g2["name"]] for r in results})
            lm = {tuple(sorted(r["params"].items())): r["metrics"]["total_return"]
                  for r in results}
            matrix = [[lm.get(tuple(sorted({g1["name"]: x, g2["name"]: y}.items())))
                       for x in x_vals] for y in reversed(y_vals)]
            scan.heat = {"x_name": g1["name"], "y_name": g2["name"],
                         "x_vals": x_vals, "y_vals": list(reversed(y_vals)),
                         "metric": "total_return", "matrix": matrix}
        scan.status = "done"
        db.commit()
        log.info("参数寻优 #%d 完成: %d 组合, 最优 %s", scan_id, len(results), best["params"])
    except Exception as e:  # noqa: BLE001
        db.rollback()
        try:
            scan = db.get(ParamScan, scan_id)
            if scan:
                scan.status = "failed"
                scan.error = str(e)[:500]
                db.commit()
        except Exception:  # noqa: BLE001
            pass
        log.exception("参数寻优 #%d 失败", scan_id)
    finally:
        db.close()
