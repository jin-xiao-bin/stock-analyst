"""合成决策验证执行链路：风控→实时价成交→留痕→观察任务（不依赖LLM随机性）"""
import datetime as dt

from app.db import SessionLocal
from app.models import AgentConfig, SimAccount, SimTrade, WatchTask
from app.services.agent.trader import _run_and_execute

db = SessionLocal()
config = db.query(AgentConfig).first()
account = db.get(SimAccount, config.account_id)

snapshot = {
    "realtime": {"price": 11.0, "pre_close": 11.35},
    "latest_local_close": 11.57,
    "position": None, "account": {"cash": account.cash},
}
decision = {"action": "buy", "target_pos_pct": 0.2, "confidence": 0.8,
            "reason": "合成测试：验证执行链路", "thesis": "测试买入逻辑",
            "invalidation": {"kind": "price_below", "value": 10.0}}
row = _run_and_execute(db, config, account, "000001.SZ", decision,
                       analysis_md="synthetic", snapshot=snapshot,
                       decision_type="intraday")
db.commit()
print("decision:", row.id, row.action, row.status, "qty:", row.qty,
      "price:", row.price, "risk:", row.risk_note)
print("cash now:", account.cash)

# 重复执行再测一次（应被R5冷却期拒绝）
row2 = _run_and_execute(db, config, account, "000001.SZ", decision,
                        analysis_md="synthetic2", snapshot=snapshot,
                        decision_type="intraday")
db.commit()
print("second decision:", row2.id, row2.action, row2.status, "risk:", row2.risk_note)

# thesis 失效条件建观察任务了吗
n = db.query(WatchTask).filter(WatchTask.ts_code == "000001.SZ",
                               WatchTask.status == "waiting").count()
print("waiting watch tasks:", n)
trades = db.query(SimTrade).filter(SimTrade.source == "agent").count()
print("agent trades total:", trades)
db.close()
