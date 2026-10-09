from app.db import SessionLocal
from sqlalchemy import select
from app.models import AgentDecision

db = SessionLocal()
rows = db.scalars(select(AgentDecision).order_by(AgentDecision.id.desc()).limit(6)).all()
for d in rows:
    print(f"#{d.id} {d.ts_code} {d.action}/{d.status} qty={d.qty} price={d.price} "
          f"run_date={d.run_date} run_time={d.run_time} risk={d.risk_note}")
db.close()
