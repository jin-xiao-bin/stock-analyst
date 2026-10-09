from app.db import SessionLocal
from sqlalchemy import select
from app.models import SimTrade

db = SessionLocal()
rows = db.scalars(select(SimTrade).order_by(SimTrade.id.desc()).limit(15)).all()
for t in rows:
    print(f"#{t.id} acc={t.account_id} {t.ts_code} {t.side} {t.qty}@{t.price} "
          f"trade_date={t.trade_date} created_at={t.created_at} src={t.source} note={str(t.note)[:40]}")
db.close()
