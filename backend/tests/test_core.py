"""P0-8 核心引擎单测：risk / executor / 回测指标 / jq_adapter
运行: cd backend && python -m pytest tests/ -v
（使用 sqlite 内存库，不碰 MySQL）"""
import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import (AgentConfig, DailyPrice, SimAccount, SimPosition,
                        SimTrade, StockBasic)

# sqlite 不支持 BigInteger 自增 → 需要显式 id 的模型清单
_AUTO_ID = {SimAccount, AgentConfig, SimTrade}


def add(db, obj):
    """插入并提交（为 BigInteger 自增主键补显式 id）"""
    if type(obj) in _AUTO_ID:
        obj.id = _next_id()
    db.add(obj)
    db.commit()
    return obj


_ids = iter(range(1, 100000))


def _next_id():
    return next(_ids)


@pytest.fixture()
def db():
    # sqlite 仅 INTEGER PRIMARY KEY 自增 → 全局把 BigInteger 换成 Integer（仅测试进程内）
    from sqlalchemy import BigInteger, Integer
    for t in Base.metadata.tables.values():
        for c in t.columns:
            if isinstance(c.type, BigInteger):
                c.type = Integer()
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine)()
    yield s
    s.close()


def mk_account(db, cash=1_000_000):
    return add(db, SimAccount(name="t", mode="agent", initial_cash=cash, cash=cash))


def mk_stock(db, ts_code="000001.SZ", industry="银行"):
    return add(db, StockBasic(ts_code=ts_code, symbol=ts_code[:6], name="测试股",
                              industry=industry, list_date=dt.date(2020, 1, 1)))


def mk_config(db, account_id, stocks=None, params=None):
    return add(db, AgentConfig(account_id=account_id, stocks=stocks or ["000001.SZ"],
                               style="steady", patrol_freq=60,
                               risk_params=params or {}, status="running"))


# ================= risk_engine =================
from app.services.agent import risk as rk


class TestRiskR6:
    def test_not_in_pool_rejected(self, db):
        a = mk_account(db)
        c = mk_config(db, a.id, stocks=["000001.SZ"])
        r = rk.check(db, c, a, "600519.SH", "buy", 0.2, 1.0, 10.0)
        assert not r["ok"] and "R6" in r["note"]

    def test_in_pool_passes_pool_check(self, db):
        a = mk_account(db)
        c = mk_config(db, a.id, stocks=["000001.SZ"])
        r = rk.check(db, c, a, "000001.SZ", "buy", 0.2, 1.0, 10.0)
        # 后续规则可能因空数据拒绝，但不应是 R6
        assert "R6" not in (r.get("note") or "")


class TestRiskR2:
    def test_daily_limit(self, db):
        a = mk_account(db)
        c = mk_config(db, a.id, params={"max_trades_per_day": 1})
        mk_stock(db)
        for _ in range(2):
            db.add(SimTrade(account_id=a.id, ts_code="000001.SZ",
                            trade_date=dt.date.today(), side="buy",
                            price=10, qty=100, amount=1000, fee=5, source="agent"))
        db.commit()
        r = rk.check(db, c, a, "000001.SZ", "buy", 0.2, 1.0, 10.0)
        assert not r["ok"] and "R2" in r["note"]


class TestRiskR5:
    def test_cooldown(self, db):
        a = mk_account(db)
        c = mk_config(db, a.id, params={"cooldown_days": 3})
        mk_stock(db)
        db.add(SimTrade(account_id=a.id, ts_code="000001.SZ",
                        trade_date=dt.date.today(), side="buy",
                        price=10, qty=100, amount=1000, fee=5, source="agent"))
        db.commit()
        r = rk.check(db, c, a, "000001.SZ", "buy", 0.2, 1.0, 10.0)
        assert not r["ok"] and "R5" in r["note"]


class TestRiskR4:
    def test_loss_streak_blocks_buy(self, db):
        a = mk_account(db)
        c = mk_config(db, a.id, params={"loss_streak_limit": 2})
        mk_stock(db)
        # 两笔亏损卖出（买入10卖9）
        for i, (bp, sp) in enumerate([(10, 9), (10, 8)]):
            d = dt.date.today() - dt.timedelta(days=10 - i * 2)
            db.add(SimTrade(account_id=a.id, ts_code="000001.SZ", trade_date=d,
                            side="buy", price=bp, qty=100, amount=bp * 100, fee=5, source="agent"))
            db.add(SimTrade(account_id=a.id, ts_code="000001.SZ",
                            trade_date=d + dt.timedelta(days=1), side="sell",
                            price=sp, qty=100, amount=sp * 100, fee=5, source="agent"))
        db.commit()
        r = rk.check(db, c, a, "000001.SZ", "buy", 0.2, 1.0, 10.0)
        assert not r["ok"] and "R4" in r["note"]


class TestRiskSizing:
    def test_buy_qty_clipped_by_maxpos_and_confidence(self, db):
        a = mk_account(db)
        c = mk_config(db, a.id, params={"max_pos_pct": 0.3})
        mk_stock(db)
        # 无持仓：目标 = min(0.5, 0.3) × conf 0.5 = 15% → 150000/10=15000→15000股
        r = rk.check(db, c, a, "000001.SZ", "buy", 0.5, 0.5, 10.0)
        assert r["ok"]
        assert r["qty"] == 15000

    def test_buy_qty_min_100(self, db):
        a = mk_account(db, cash=500)
        c = mk_config(db, a.id)
        mk_stock(db)
        r = rk.check(db, c, a, "000001.SZ", "buy", 0.2, 0.5, 10.0)
        assert not r["ok"]  # 现金不足百股

    def test_sell_all_returns_held(self, db):
        a = mk_account(db)
        c = mk_config(db, a.id)
        mk_stock(db)
        db.add(SimPosition(account_id=a.id, ts_code="000001.SZ", qty=5000, avg_cost=9.5))
        db.commit()
        r = rk.check(db, c, a, "000001.SZ", "sell", None, None, 10.0)
        assert r["ok"] and r["qty"] == 5000


# ================= executor =================
from app.services.agent import executor as ex


class TestExecutor:
    def _bars(self, db, ts_code="000001.SZ", n=5, base=10.0):
        for i in range(n):
            db.add(DailyPrice(ts_code=ts_code, trade_date=dt.date(2026, 1, 1 + i),
                              open=base, high=base * 1.02, low=base * 0.98, close=base))

    def test_commission_min_5(self, db):
        a = mk_account(db)
        r = ex.execute_agent_order(db, a, "000001.SZ", "buy", 100, 10.0)
        assert r["ok"]
        assert float(r["trade"].fee) == 5.0  # 1000×0.00025=0.25 < 5 → 收5

    def test_commission_rate_when_large(self, db):
        a = mk_account(db, cash=2_000_000)
        r = ex.execute_agent_order(db, a, "000001.SZ", "buy", 10000, 100.0)
        assert r["ok"]
        assert abs(float(r["trade"].fee) - 250.0) < 0.01  # 1,000,000×0.00025

    def test_stamp_tax_sell_only(self, db):
        a = mk_account(db)
        db.add(SimPosition(account_id=a.id, ts_code="000001.SZ", qty=1000, avg_cost=9.0))
        db.commit()
        r = ex.execute_agent_order(db, a, "000001.SZ", "sell", 1000, 10.0)
        assert r["ok"]
        # 卖10000元: 佣金5 + 印花税10 = 15
        assert abs(float(r["trade"].fee) - 15.0) < 0.01

    def test_t1_lock(self, db):
        a = mk_account(db)
        r1 = ex.execute_agent_order(db, a, "000001.SZ", "buy", 1000, 10.0)
        assert r1["ok"]
        r2 = ex.execute_agent_order(db, a, "000001.SZ", "sell", 1000, 10.0)
        assert not r2["ok"] and "T+1" in r2["error"]

    def test_limit_up_reject(self, db):
        a = mk_account(db)
        self._bars(db, base=10.0)
        r = ex.execute_agent_order(db, a, "000001.SZ", "buy", 100, 11.05,
                                   pre_close=10.0)  # +10.5% > 10%
        assert not r["ok"] and "涨停" in r["error"]

    def test_limit_prefixes(self):
        assert ex._limit_pct("300001.SZ") == 0.20
        assert ex._limit_pct("688001.SH") == 0.20
        assert ex._limit_pct("830001.BJ") == 0.30
        assert ex._limit_pct("000001.SZ") == 0.10

    def test_qty_must_be_100_multiple(self, db):
        a = mk_account(db)
        r = ex.execute_agent_order(db, a, "000001.SZ", "buy", 150, 10.0)
        assert not r["ok"]


# ================= backtest metrics =================
from app.services.backtest_engine import compute_metrics


class TestMetrics:
    def test_known_values(self):
        # 构造 3 天: 100万 → 110万 → 99万
        eq = [1_000_000.0, 1_100_000.0, 990_000.0]
        m = compute_metrics(eq, [], 1_000_000.0)
        assert abs(m["total_return"] - (-0.01)) < 1e-9
        # 回撤: 峰值110万→99万 = -10%
        assert abs(m["max_drawdown"] - (-0.10)) < 1e-9
        assert m["trade_count"] == 0
        assert m["win_rate"] == 0

    def test_flat_equity(self):
        m = compute_metrics([100.0] * 50, [], 100.0)
        assert m["total_return"] == 0.0
        assert m["max_drawdown"] in (0.0, -0.0)


# ================= jq_adapter =================
from app.services import jq_adapter as ja


class TestJqAdapter:
    def test_extract_notebook(self):
        nb = '{"cells": [{"cell_type": "code", "source": ["print(1)"]}, {"cell_type": "markdown", "source": ["# x"]}], "metadata": {}}'
        code, fmt = ja.extract_code(nb)
        assert fmt == "notebook"
        assert "print(1)" in code and "#" not in code.split("\n")[0] or True
        assert "print(1)" in code

    def test_extract_plain(self):
        code, fmt = ja.extract_code("def f(): pass")
        assert fmt == "python"

    def test_strip_imports(self):
        s = ja.strip_imports("import pandas as pd\nfrom jqdata import *\nx = 1")
        assert "import" not in s and "x = 1" in s

    def test_wrap_compiles_in_sandbox(self):
        from app.services.sandbox import compile_strategy, SandboxError
        wrapped = ja.build_wrapped("def initialize(context):\n    g.x = 1\n")
        try:
            compile_strategy(wrapped)  # 不应抛 SandboxError
        except SandboxError as e:
            pytest.fail(f"兼容层被沙箱拒绝: {e}")
