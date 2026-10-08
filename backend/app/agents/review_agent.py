"""交易审查 Agent（SSE generator，deepseek-reasoner）

输入：时段内交易明细 + 每笔交易前后20日close摘要 +（策略单）策略代码与最近回测指标
输出：markdown content + ```json suggestions:[{type,detail,proposed_action}]```
yield 事件：{"event": "status"|"section"|"error"|"done", "data": {...}}
"""
from __future__ import annotations

import json
import re
from typing import Any, Generator

from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from ..services.deepseek_client import client as ds_client

    def _chat(messages, model=None, **kw) -> str:
        return ds_client.chat(messages, model=model, **kw)
except ImportError:  # 降级 stub
    def _chat(messages, model=None, **kw) -> str:
        return ("## 审查报告（降级stub）\n\n交易行为基本正常。\n\n"
                '```json\n[{"type":"param_adjust","detail":"均线周期偏短，噪音大",'
                '"proposed_action":"将fast=5/slow=20调整为fast=10/slow=60"}]\n```')

SYSTEM_PROMPT = """你是资深量化交易审查官。基于给定的模拟交易记录、每笔交易前后约20个交易日的收盘价走势、
以及（如提供）策略代码与最近回测指标，输出交易审查报告。

输出格式（严格遵守）：
1. markdown 正文：## 行为分析 / ## 风险控制 / ## 参数与改进建议 各一节；
2. 最后一个 ```json 代码块，内容为数组：
   [{"type":"behavior"|"risk_control"|"param_adjust","detail":"问题说明","proposed_action":"具体可执行的建议"}]
type 含义：behavior=交易行为问题，risk_control=风控问题，param_adjust=参数调整（可被 apply 自动执行生成新版本策略）。
"""


def _build_review_data(db: Session, account_id: int, scope: str,
                       strategy_id: int | None,
                       period_start, period_end) -> dict:
    """组装审查输入数据（不修改数据库）"""
    from ..models import DailyPrice, SimTrade, Strategy, BacktestRun
    stmt = select(SimTrade).where(SimTrade.account_id == account_id)
    if period_start:
        stmt = stmt.where(SimTrade.trade_date >= period_start)
    if period_end:
        stmt = stmt.where(SimTrade.trade_date <= period_end)
    if scope == "manual":
        stmt = stmt.where(SimTrade.source == "manual")
    elif scope == "strategy" and strategy_id:
        stmt = stmt.where(SimTrade.strategy_id == strategy_id)
    trades = db.scalars(stmt.order_by(SimTrade.trade_date)).all()

    close_map: dict[str, list] = {}
    codes = sorted({t.ts_code for t in trades})
    for code in codes:
        rows = db.scalars(select(DailyPrice).where(DailyPrice.ts_code == code)
                          .order_by(DailyPrice.trade_date)).all()
        close_map[code] = [{"d": r.trade_date.isoformat(), "c": float(r.close)} for r in rows]

    def price_window(code: str, date, n: int = 20) -> str:
        seq = close_map.get(code, [])
        idx = next((i for i, p in enumerate(seq) if p["d"] >= date.isoformat()), None)
        if idx is None:
            idx = len(seq) - 1
        w = seq[max(0, idx - n): idx + n + 1]
        return ", ".join(f'{p["d"][5:]}:{p["c"]:.2f}' for p in w) or "（无数据）"

    trade_lines = []
    for t in trades:
        trade_lines.append(
            f"- {t.trade_date} {t.ts_code} {t.side} {t.qty}股 @ {float(t.price):.2f} "
            f"金额{float(t.amount):.0f} 费用{float(t.fee):.2f} 来源{t.source} 备注:{t.note or ''}\n"
            f"  前后走势: {price_window(t.ts_code, t.trade_date)}")

    strat_info = ""
    if strategy_id:
        s = db.get(Strategy, strategy_id)
        if s:
            bt = db.scalars(select(BacktestRun)
                            .where(BacktestRun.strategy_id == strategy_id,
                                   BacktestRun.status == "success")
                            .order_by(BacktestRun.id.desc())).first()
            strat_info = f"\n策略代码：\n```python\n{s.code}\n```\n"
            if bt and bt.metrics:
                strat_info += f"最近回测指标: {json.dumps(bt.metrics, ensure_ascii=False)}\n"

    return {"account_id": account_id, "scope": scope,
            "period": f"{period_start or '开始'} ~ {period_end or '最新'}",
            "trade_count": len(trades),
            "trades": "\n".join(trade_lines) or "（无交易记录）",
            "strategy": strat_info}


def run_review(db: Session, account_id: int, scope: str, strategy_id: int | None,
               period_start=None, period_end=None) -> Generator[dict, None, Any]:
    """执行审查流程：LLM 分析 → 落库 trade_review；yield SSE 事件"""
    from ..models import TradeReview

    yield {"event": "status", "data": {"stage": "gathering", "msg": "汇总交易与K线数据…"}}
    data = _build_review_data(db, account_id, scope, strategy_id, period_start, period_end)
    user = (f"账户 {account_id}（scope={scope}，区间 {data['period']}）共 {data['trade_count']} 笔交易：\n"
            f"{data['trades']}\n{data['strategy']}")

    yield {"event": "status", "data": {"stage": "reviewing", "msg": "deepseek-reasoner 审查分析中…"}}
    try:
        text = _chat([{"role": "system", "content": SYSTEM_PROMPT},
                      {"role": "user", "content": user}],
                     model="deepseek-reasoner", max_tokens=8192)
    except Exception as e:  # noqa: BLE001
        yield {"event": "error", "data": {"msg": f"DeepSeek 调用失败: {e}"}}
        return

    content = re.sub(r"```json\s*\n.*?```", "", text, flags=re.S).strip()
    suggestions: list[dict] = []
    m = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.S)
    for blk in m:
        try:
            parsed = json.loads(blk)
            if isinstance(parsed, list):
                suggestions = [s for s in parsed if isinstance(s, dict) and "type" in s]
                break
        except json.JSONDecodeError:
            continue

    yield {"event": "section", "data": {"role": "review", "title": "审查报告",
                                        "content": content}}
    yield {"event": "section", "data": {"role": "suggestions", "title": "改进建议",
                                        "content": suggestions}}

    review = TradeReview(account_id=account_id, scope=scope, strategy_id=strategy_id,
                         period_start=period_start, period_end=period_end,
                         content=content, suggestions=suggestions, followup="pending")
    db.add(review)
    db.commit()
    db.refresh(review)
    yield {"event": "done", "data": {"review_id": review.id}}
