from app.db import SessionLocal
from app.services import jq_adapter
from app.services.backtest_engine import validate_strategy_code

jq = """
def initialize(context):
    g.fast = 5
    run_daily(trade, time='every_bar')

def trade(context):
    df = attribute_history('601689.XSHG', 30, '1d', ['close'])
    closes = df['close'].values
    log.info(closes[-1])

def handle_data(context, data):
    pass
"""
wrapped = jq_adapter.build_wrapped(jq)
db = SessionLocal()
v = validate_strategy_code(db, wrapped)
print("ok:", v.get("ok"), "error:", str(v.get("error"))[:300])
db.close()
