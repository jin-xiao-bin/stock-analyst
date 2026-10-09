from app.db import SessionLocal
from sqlalchemy import select
from app.models import ReplaySession, SimTrade

db = SessionLocal()
for s in db.scalars(select(ReplaySession).order_by(ReplaySession.id.desc())).all():
    print(f"session#{s.id} acc={s.account_id} {s.ts_code} start={s.start_date} cursor={s.cursor_date}")
print("---")
for t in db.scalars(select(SimTrade).where(SimTrade.ts_code.like("601689%"),
                                          SimTrade.account_id == 5)).all():
    print(f"trade#{t.id} acc5 {t.side} {t.qty}@{t.price} trade_date={t.trade_date} src={t.source}")
db.close()
