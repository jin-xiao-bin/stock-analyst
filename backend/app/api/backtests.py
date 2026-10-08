"""回测 API（契约第5节，同步执行）"""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import BacktestRun, Strategy, StockBasic
from ..services.backtest_engine import run_backtest


def _resolve_stock(db: Session, ts_code: str) -> str:
    """校验并纠错股票代码：后缀写错时按6位代码自动纠正；不存在时报400"""
    if db.get(StockBasic, ts_code):
        return ts_code
    symbol = ts_code.split(".")[0]
    alts = db.scalars(select(StockBasic).where(StockBasic.symbol == symbol)).all()
    if len(alts) == 1:
        return alts[0].ts_code
    raise HTTPException(400, f"股票代码 {ts_code} 不存在，请检查是否输入正确（可在行情页搜索确认）")

router = APIRouter(prefix="/api/backtests", tags=["backtests"])
r1 = router  # 兼容别名


class BacktestCreate(BaseModel):
    strategy_id: int
    ts_code: str
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    initial_cash: float = 1_000_000.0
    params: dict | None = None
    ts_codes: list[str] | None = None  # 兼容多标的入参，仅取第一个


def _serialize(r: BacktestRun, full: bool = False, names: dict | None = None) -> dict:
    names = names or {}
    codes = r.ts_codes or []
    d: dict = {"id": r.id, "strategy_id": r.strategy_id,
               "strategy_name": names.get("strategy", {}).get(r.strategy_id, f"#{r.strategy_id}"),
               "ts_code": codes[0] if codes else None,
               "stock_name": names.get("stock", {}).get(codes[0] if codes else "", ""),
               "status": r.status,
               "ts_codes": r.ts_codes, "start_date": r.start_date.isoformat() if r.start_date else None,
               "end_date": r.end_date.isoformat() if r.end_date else None,
               "initial_cash": float(r.initial_cash), "params": r.params,
               "metrics": r.metrics, "error": r.error,
               "created_at": r.created_at.isoformat()}
    if full:
        d["equity_curve"] = r.equity_curve or []
        d["trades"] = r.trades_json or []
    return d


def _name_maps(db: Session, runs: list[BacktestRun]) -> dict:
    strategy_ids = {r.strategy_id for r in runs if r.strategy_id}
    strategies = {s.id: s.name for s in db.scalars(
        select(Strategy).where(Strategy.id.in_(strategy_ids))).all()} if strategy_ids else {}
    codes = {code for r in runs for code in (r.ts_codes or [])}
    stocks = {s.ts_code: s.name for s in db.scalars(
        select(StockBasic).where(StockBasic.ts_code.in_(codes))).all()} if codes else {}
    return {"strategy": strategies, "stock": stocks}


@router.post("")
def create_backtest(body: BacktestCreate, db: Session = Depends(get_db)):
    from ..utils import normalize_ts_code
    s = db.get(Strategy, body.strategy_id)
    if s is None:
        raise HTTPException(404, f"策略 {body.strategy_id} 不存在")
    ts_code = normalize_ts_code(body.ts_codes[0] if body.ts_codes and not body.ts_code
                                else body.ts_code)
    ts_code = _resolve_stock(db, ts_code)
    result = run_backtest(db, s.code, body.params, ts_code,
                          body.start_date, body.end_date,
                          body.initial_cash, strategy_id=s.id)
    if result.get("status") == "failed":
        return result  # 契约：失败返回 {status:"failed", error}
    run = db.get(BacktestRun, result["id"])
    return _serialize(run, full=True)


@router.get("")
def list_backtests(strategy_id: int | None = None, db: Session = Depends(get_db)):
    stmt = select(BacktestRun).order_by(BacktestRun.id.desc()).limit(50)
    if strategy_id:
        stmt = stmt.where(BacktestRun.strategy_id == strategy_id)
    runs = db.scalars(stmt).all()
    names = _name_maps(db, runs)
    return [_serialize(r, names=names) for r in runs]


@router.get("/{rid}")
def get_backtest(rid: int, db: Session = Depends(get_db)):
    r = db.get(BacktestRun, rid)
    if r is None:
        raise HTTPException(404, f"回测 {rid} 不存在")
    return _serialize(r, full=True, names=_name_maps(db, [r]))


@router.delete("/{rid}")
def delete_backtest(rid: int, db: Session = Depends(get_db)):
    r = db.get(BacktestRun, rid)
    if r is None:
        raise HTTPException(404, f"回测 {rid} 不存在")
    db.delete(r)
    db.commit()
    return {"ok": True, "deleted": rid}
