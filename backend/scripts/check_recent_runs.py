from app.db import SessionLocal
from sqlalchemy import select
from app.models import BacktestRun

db = SessionLocal()
rows = db.scalars(select(BacktestRun).order_by(BacktestRun.id.desc()).limit(3)).all()
for r in rows:
    print(f"run#{r.id} status={r.status} ts_codes={r.ts_codes} error={str(r.error)[:100]}")
db.close()
