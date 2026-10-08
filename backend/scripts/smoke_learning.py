"""A4 验收：学习闭环真实生成"""
from app.services.agent.learning import weekly_learning
from app.db import SessionLocal
from app.models import AgentConfig

ok = weekly_learning()
db = SessionLocal()
config = db.query(AgentConfig).first()
notes = config.prompt_notes or ""
print("learning ok:", ok)
print("notes len:", len(notes))
print(notes[:400])
db.close()
