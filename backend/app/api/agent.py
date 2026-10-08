"""自主交易 Agent API"""
import datetime as dt
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (AgentConfig, AgentDecision, DailyPrice, SimAccount,
                      SimPosition, SimTrade, Strategy)
from ..services.agent import risk as risk_engine
from ..services.agent.trader import run_daily, run_intraday

router = APIRouter(prefix="/api/agent", tags=["agent"])


class SetupReq(BaseModel):
    stocks: list[str]
    initial_cash: float = 100_000
    style: str = "steady"
    patrol_freq: int = 60
    risk_params: dict | None = None
    reference_strategies: dict[str, list[int]] | None = None
    account_id: int | None = None  # 关联已有账户（方案A共用账户）；空则新建专属账户


class RunReq(BaseModel):
    ts_code: str | None = None
    mode: str = "intraday"  # intraday/daily


def _config_out(db: Session, c: AgentConfig) -> dict:
    account = db.get(SimAccount, c.account_id)
    value = risk_engine.account_value(db, account) if account else 0
    positions = []
    pos_map: dict[str, dict] = {}
    for p in db.scalars(select(SimPosition).where(
            SimPosition.account_id == c.account_id)).all():
        last = db.scalar(select(DailyPrice.close).where(DailyPrice.ts_code == p.ts_code)
                         .order_by(DailyPrice.trade_date.desc()).limit(1))
        px = float(last or 0)
        avg = float(p.avg_cost)
        item = {"ts_code": p.ts_code, "qty": p.qty, "avg_cost": avg,
                "last_price": px, "market_value": round(px * p.qty, 2),
                "pnl_pct": round((px / avg - 1) * 100, 2) if avg else 0}
        positions.append(item)
        pos_map[p.ts_code] = item
    last_decisions = db.scalars(select(AgentDecision).where(
        AgentDecision.account_id == c.account_id)
        .order_by(AgentDecision.id.desc()).limit(5)).all()
    disabled = c.disabled_stocks or []
    # 股票池逐股状态（列表页展示）
    from ..models import StockBasic
    names = dict(db.execute(select(StockBasic.ts_code, StockBasic.name)).all())
    stock_pool = []
    for code in (c.stocks or []):
        last_d = db.scalar(select(AgentDecision).where(
            AgentDecision.account_id == c.account_id, AgentDecision.ts_code == code)
            .order_by(AgentDecision.id.desc()).limit(1))
        stock_pool.append({
            "ts_code": code, "name": names.get(code, ""),
            "patrol_enabled": code not in disabled,
            "position": pos_map.get(code),
            "last_decision": (
                {"action": last_d.action, "status": last_d.status,
                 "run_time": last_d.run_time.isoformat(timespec="minutes") if last_d.run_time else None,
                 "reason": (last_d.reason or "")[:80]} if last_d else None),
        })
    return {
        "id": c.id, "account_id": c.account_id, "status": c.status,
        "stocks": c.stocks or [], "style": c.style, "patrol_freq": c.patrol_freq,
        "risk_params": c.risk_params, "reference_strategies": c.reference_strategies or {},
        "pause_until": c.pause_until.isoformat() if c.pause_until else None,
        "account": {"cash": float(account.cash) if account else 0,
                    "initial_cash": float(account.initial_cash) if account else 0,
                    "total_value": round(value, 2),
                    "profit_pct": round((value / float(account.initial_cash) - 1) * 100, 2)
                    if account else 0},
        "positions": positions,
        "stock_pool": stock_pool,
        "recent_decisions": [
            {"id": d.id, "ts_code": d.ts_code, "action": d.action, "status": d.status,
             "decision_type": d.decision_type,
             "run_time": d.run_time.isoformat(timespec="minutes") if d.run_time else None,
             "reason": (d.reason or "")[:100]} for d in last_decisions],
    }


@router.get("/status")
def status(db: Session = Depends(get_db)):
    configs = db.query(AgentConfig).all()
    return [_config_out(db, c) for c in configs]


@router.post("/setup")
def setup(req: SetupReq, db: Session = Depends(get_db)):
    """创建或更新配置（每用户单配置：取第一条）。股票代码支持裸6位，自动补全/纠错。"""
    from ..utils import resolve_ts_code
    stocks = []
    for s in req.stocks:
        code = resolve_ts_code(db, s)
        if code is None:
            raise HTTPException(400, f"股票代码 {s} 不存在")
        if code not in stocks:
            stocks.append(code)
    ref_strategies = {}
    for code_in, sids in (req.reference_strategies or {}).items():
        code = resolve_ts_code(db, code_in) or code_in
        for sid in sids:
            if db.get(Strategy, sid) is None:
                raise HTTPException(400, f"参考策略 {sid} 不存在")
        ref_strategies[code] = sids
    c = db.query(AgentConfig).first()
    if c is None:
        if req.account_id:
            # 首次配置即关联已有账户
            linked = db.get(SimAccount, req.account_id)
            if linked is None:
                raise HTTPException(404, f"账户 {req.account_id} 不存在")
            c = AgentConfig(account_id=linked.id)
        else:
            account = SimAccount(name="自主交易Agent", mode="agent",
                                 initial_cash=req.initial_cash, cash=req.initial_cash)
            db.add(account)
            db.flush()
            c = AgentConfig(account_id=account.id)
        db.add(c)
    else:
        # 方案A：支持切换关联账户（须显式传 account_id）
        if req.account_id and req.account_id != c.account_id:
            linked = db.get(SimAccount, req.account_id)
            if linked is None:
                raise HTTPException(404, f"账户 {req.account_id} 不存在")
            c.account_id = linked.id
        account = db.get(SimAccount, c.account_id)
    c.stocks = stocks
    c.style = req.style if req.style in ("steady", "balanced", "aggressive") else "steady"
    c.patrol_freq = max(15, req.patrol_freq)
    c.risk_params = req.risk_params
    c.reference_strategies = ref_strategies
    db.commit()
    db.refresh(c)
    return _config_out(db, c)


@router.post("/start")
def start(db: Session = Depends(get_db)):
    c = db.query(AgentConfig).first()
    if c is None:
        raise HTTPException(400, "请先 setup 配置")
    if not c.stocks:
        raise HTTPException(400, "股票池为空")
    c.status = "running"
    db.commit()
    return {"ok": True, "status": "running"}


@router.post("/stop")
def stop(db: Session = Depends(get_db)):
    c = db.query(AgentConfig).first()
    if c:
        c.status = "stopped"
        db.commit()
    return {"ok": True, "status": "stopped"}


@router.post("/run")
def run(req: RunReq, background: BackgroundTasks, db: Session = Depends(get_db)):
    """手动触发（同步执行单只 / 后台执行全池）"""
    c = db.query(AgentConfig).first()
    if c is None or not c.stocks:
        raise HTTPException(400, "未配置或股票池为空")
    account = db.get(SimAccount, c.account_id)
    if account is None:
        raise HTTPException(400, "账户不存在")
    if req.ts_code:
        from ..utils import resolve_ts_code
        code = resolve_ts_code(db, req.ts_code)
        if code is None or code not in c.stocks:
            raise HTTPException(400, f"{req.ts_code} 不在股票池")
        req_ts = code
        fn = run_intraday if req.mode == "intraday" else run_daily
        r = fn(db, c, account, req_ts)
        return {"results": [{"ts_code": req_ts, **r}]}
    from ..services.agent.trader import run_pool
    background.add_task(run_pool, req.mode, None)
    return {"status": "started", "mode": req.mode}


@router.post("/force-close")
def force_close(background: BackgroundTasks, db: Session = Depends(get_db)):
    """强制清仓（后台逐股按实时价卖出）"""

    def _job():
        from ..services.agent.executor import execute_agent_order
        from ..services.realtime import get_realtime
        s = SessionLocal()
        try:
            c = s.query(AgentConfig).first()
            if not c:
                return
            account = s.get(SimAccount, c.account_id)
            for p in s.scalars(select(SimPosition).where(
                    SimPosition.account_id == c.account_id)).all():
                rt = get_realtime(p.ts_code) or {}
                px = rt.get("price")
                if not px:
                    continue
                res = execute_agent_order(s, account, p.ts_code, "sell", p.qty,
                                          float(px), rt.get("pre_close"), note="agent:force_close")
                if res["ok"]:
                    s.commit()
                else:
                    s.rollback()
        finally:
            s.close()

    from ..db import SessionLocal
    background.add_task(_job)
    return {"ok": True, "msg": "清仓已提交后台执行"}


@router.post("/stock/{ts_code}/toggle")
def toggle_stock(ts_code: str, db: Session = Depends(get_db)):
    """开启/停止单只股票的巡盘"""
    from ..utils import resolve_ts_code
    code = resolve_ts_code(db, ts_code)
    c = db.query(AgentConfig).first()
    if c is None or not c.stocks:
        raise HTTPException(400, "未配置股票池")
    if code not in c.stocks:
        raise HTTPException(404, f"{ts_code} 不在股票池")
    disabled = list(c.disabled_stocks or [])
    if code in disabled:
        disabled.remove(code)
        state = "enabled"
    else:
        disabled.append(code)
        state = "disabled"
    c.disabled_stocks = disabled
    db.commit()
    return {"ok": True, "ts_code": code, "patrol_enabled": state == "enabled"}


@router.delete("/stock/{ts_code}")
def remove_stock(ts_code: str, db: Session = Depends(get_db)):
    """从股票池移除（决策历史保留；有持仓时拒绝，需先清仓该股）"""
    from ..utils import resolve_ts_code
    code = resolve_ts_code(db, ts_code)
    c = db.query(AgentConfig).first()
    if c is None or not c.stocks:
        raise HTTPException(400, "未配置股票池")
    if code not in c.stocks:
        raise HTTPException(404, f"{ts_code} 不在股票池")
    pos = db.scalar(select(SimPosition).where(
        SimPosition.account_id == c.account_id, SimPosition.ts_code == code))
    if pos:
        raise HTTPException(400, f"{code} 仍有持仓 {pos.qty} 股，请先清仓再移除")
    stocks = list(c.stocks)
    stocks.remove(code)
    c.stocks = stocks
    refs = dict(c.reference_strategies or {})
    refs.pop(code, None)
    c.reference_strategies = refs
    disabled = list(c.disabled_stocks or [])
    if code in disabled:
        disabled.remove(code)
        c.disabled_stocks = disabled
    db.commit()
    return {"ok": True, "removed": code}


@router.post("/notify-test")
def notify_test():
    """飞书通知链路测试"""
    from ..services.notify import notify_test
    return notify_test()


@router.get("/decisions")
def decisions(account_id: int | None = None, ts_code: str | None = None,
              page: int = 1, page_size: int = 20, db: Session = Depends(get_db)):
    c = db.query(AgentConfig).first()
    aid = account_id or (c.account_id if c else None)
    if aid is None:
        return {"total": 0, "items": []}
    stmt = select(AgentDecision).where(AgentDecision.account_id == aid)
    if ts_code:
        from ..utils import resolve_ts_code
        ts_code = resolve_ts_code(db, ts_code) or ts_code
        stmt = stmt.where(AgentDecision.ts_code == ts_code)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AgentDecision.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return {"total": total, "items": [{
        "id": r.id, "ts_code": r.ts_code, "run_date": r.run_date.isoformat(),
        "run_time": r.run_time.isoformat(timespec="minutes") if r.run_time else None,
        "decision_type": r.decision_type, "action": r.action, "status": r.status,
        "qty": r.qty, "price": float(r.price) if r.price else None,
        "risk_note": r.risk_note, "reason": (r.reason or "")[:300],
        "thesis": (r.thesis or "")[:300],
    } for r in rows]}


@router.get("/decisions/{decision_id}")
def decision_detail(decision_id: int, db: Session = Depends(get_db)):
    r = db.get(AgentDecision, decision_id)
    if r is None:
        raise HTTPException(404, "决策不存在")
    return {
        "id": r.id, "ts_code": r.ts_code, "run_date": r.run_date.isoformat(),
        "run_time": r.run_time.isoformat() if r.run_time else None,
        "decision_type": r.decision_type, "action": r.action, "status": r.status,
        "qty": r.qty, "price": float(r.price) if r.price else None,
        "target_pos_pct": r.target_pos_pct, "risk_note": r.risk_note,
        "reason": r.reason, "thesis": r.thesis,
        "invalidation": r.invalidation, "analysis_md": r.analysis_md,
        "inputs_snapshot": r.inputs_snapshot, "trade_id": r.trade_id,
    }


@router.get("/equity")
def equity(db: Session = Depends(get_db)):
    """账户每日权益曲线：重演全部交易（按成交价+最新收盘估值当日）"""
    c = db.query(AgentConfig).first()
    if c is None:
        return []
    trades = db.scalars(select(SimTrade).where(
        SimTrade.account_id == c.account_id)
        .order_by(SimTrade.trade_date, SimTrade.id)).all()
    account = db.get(SimAccount, c.account_id)
    dates = sorted({t.trade_date for t in trades}) or []
    curve = []
    cash = float(account.initial_cash)
    pos: dict[str, tuple[int, float]] = {}
    ti = 0
    # 无交易时给一个点
    if not dates:
        return [{"date": dt.date.today().isoformat(),
                 "equity": round(risk_engine.account_value(db, account), 2)}]
    for d in dates:
        while ti < len(trades) and trades[ti].trade_date == d:
            t = trades[ti]
            if t.side == "buy":
                cash -= float(t.amount) + float(t.fee)
                q, avg = pos.get(t.ts_code, (0, 0.0))
                cost = avg * q + float(t.amount) + float(t.fee)
                pos[t.ts_code] = (q + t.qty, cost / (q + t.qty))
            else:
                cash += float(t.amount) - float(t.fee)
                q, avg = pos.get(t.ts_code, (0, 0.0))
                pos[t.ts_code] = (max(0, q - t.qty), avg)
            ti += 1
        value = cash
        for code, (q, _) in pos.items():
            if q <= 0:
                continue
            last = db.scalar(select(DailyPrice.close).where(
                DailyPrice.ts_code == code, DailyPrice.trade_date <= d)
                .order_by(DailyPrice.trade_date.desc()).limit(1))
            value += float(last or 0) * q
        curve.append({"date": d.isoformat(), "equity": round(value, 2)})
    return curve
