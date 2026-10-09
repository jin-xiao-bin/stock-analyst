"""聚宽适配 E2E：用一个简单单标的聚宽策略（含 attribute_history + order_target_value + g + 调度）"""
import json
import urllib.request

JQ_CODE = '''
import jqdata

def initialize(context):
    g.fast = 5
    g.slow = 20
    set_benchmark('000300.XSHG')
    set_order_cost()
    run_daily(trade, time='every_bar')

def trade(context):
    sec = '601689.XSHG'
    df = attribute_history(sec, g.slow+1, '1d', ['close'])
    closes = df['close'].values
    fast = mean(closes[-g.fast:])
    slow = mean(closes[-g.slow:])
    price = closes[-1]
    target = context.portfolio.total_value if fast > slow else 0
    order_target_value(sec, target)
    log.info('fast=%s slow=%s target=%s' % (fast, slow, target))

def handle_data(context, data):
    pass
'''

req = urllib.request.Request(
    "http://127.0.0.1:8300/api/strategies/import-jq", method="POST",
    data=json.dumps({"code": JQ_CODE, "name": "聚宽均线策略测试"}).encode(),
    headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=600) as r:
    result = json.loads(r.read())
print(json.dumps(result, ensure_ascii=False, indent=2))

# 若成功 → 直接对 601689 回测验证能跑
if result.get("strategy_id"):
    bt_req = urllib.request.Request(
        "http://127.0.0.1:8300/api/backtests", method="POST",
        data=json.dumps({"strategy_id": result["strategy_id"],
                         "ts_code": "601689.SH",
                         "start_date": "2025-06-01", "end_date": "2026-09-30"}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(bt_req, timeout=600) as r:
        bt = json.loads(r.read())
    print("backtest:", bt.get("status"), "trades:", len(bt.get("trades") or []),
          "metrics:", json.dumps(bt.get("metrics") or {}, ensure_ascii=False)[:120])
