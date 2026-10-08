"""自回归优化服务：apply(review_id, suggestion_index)

deepseek-chat 依据建议生成新策略代码 + 5段式 version_note
  → 沙箱校验 → 用旧策略最近一次回测同区间跑新回测
  → version_note 补验证结果 → 建 strategy(parent_id, version_no+1, source=agent)
旧策略不动，等用户调 activate 切换。
"""
from __future__ import annotations

import json
import re

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

try:
    from ..services.deepseek_client import client as ds_client

    def _chat(messages, model=None, **kw) -> str:
        return ds_client.chat(messages, model=model, **kw)
except ImportError:  # 降级 stub
    def _chat(messages, model=None, **kw) -> str:
        raise RuntimeError("deepseek_client 未就绪")

from ..agents.review_agent import SYSTEM_PROMPT  # noqa: F401 复用说明
from ..models import BacktestRun, Strategy, TradeReview
from .backtest_engine import run_backtest, validate_strategy_code

GEN_SYSTEM = """你是量化策略迭代工程师。基于旧策略代码和审查建议，生成改进版策略代码。
沙箱 API 约束（严格遵守，禁止 import/open/eval/exec/__ 开头名字）：
- def init(ctx) / def on_bar(ctx, bar, i)
- ctx.get/set/params、ctx.close/open/high/low/volume(i)（i可为负）
- ctx.ema/ma/rsi(period)→序列list、ctx.macd()→{"dif","dea","hist"}
- ctx.crossover/crossunder(a,b,i)、ctx.buy(ratio,reason)/sell(qty,reason)/sell_all(reason)
- ctx.position_qty/cash/bar_count
输出格式（严格遵守）：
1. 一个 ```python 代码块（改进后的完整策略代码）；
2. 一个 ```note 代码块，内容为5段式说明（每段一行，格式为「段名: 内容」）：
触发来源 / 变更内容(old→new) / 变更依据 / 预期效果 / 验证结果
其中「验证结果」写占位「待回测」。
"""


def _parse_gen(text: str) -> tuple[str | None, str]:
    code_m = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    code = code_m[0].strip() if code_m else None
    note_m = re.findall(r"```note\s*\n(.*?)```", text, re.S)
    note = note_m[0].strip() if note_m else text.strip()[:2000]
    return code, note


def apply_suggestion(db: Session, review_id: int, suggestion_index: int) -> dict:
    """执行审查建议 → 新版本策略 + 同区间回测对比。返回对比 dict。"""
    review = db.get(TradeReview, review_id)
    if review is None:
        raise HTTPException(404, f"审查 {review_id} 不存在")
    suggestions = review.suggestions or []
    if not (0 <= suggestion_index < len(suggestions)):
        raise HTTPException(400, f"suggestion_index 越界（共{len(suggestions)}条）")
    sug = suggestions[suggestion_index]
    if not review.strategy_id:
        raise HTTPException(400, "该审查未绑定策略，无法自回归（scope 需为 strategy）")

    old = db.get(Strategy, review.strategy_id)
    if old is None:
        raise HTTPException(404, f"策略 {review.strategy_id} 不存在")

    user = (f"旧策略代码：\n```python\n{old.code}\n```\n\n"
            f"审查建议（第{suggestion_index}条）：{json.dumps(sug, ensure_ascii=False)}\n"
            f"审查报告摘要：{(review.content or '')[:800]}\n请生成改进版。")
    try:
        text = _chat([{"role": "system", "content": GEN_SYSTEM},
                      {"role": "user", "content": user}],
                     model="deepseek-chat", temperature=0.4, max_tokens=4096)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"DeepSeek 调用失败: {e}") from e
    code, note = _parse_gen(text)
    if not code:
        raise HTTPException(502, "生成失败：未解析到策略代码")

    # 沙箱校验
    v = validate_strategy_code(db, code, old.params)
    if not v.get("ok"):
        raise HTTPException(400, f"新代码沙箱校验失败: {v.get('error')}")

    # 同区间回测（旧策略最近一次成功回测）
    old_run = db.scalars(select(BacktestRun)
                         .where(BacktestRun.strategy_id == old.id,
                                BacktestRun.status == "success")
                         .order_by(BacktestRun.id.desc())).first()
    ts_code = (old_run.ts_codes or ["000001.SZ"])[0] if old_run else "000001.SZ"
    new_run_res = run_backtest(db, code, old.params, ts_code,
                               old_run.start_date if old_run else None,
                               old_run.end_date if old_run else None,
                               float(old_run.initial_cash) if old_run else 1_000_000.0)

    # version_note 补验证结果
    verify = ("验证结果: " + (
        f"同区间回测 new({new_run_res['metrics']['total_return']:+.2%} 收益, "
        f"回撤{new_run_res['metrics']['max_drawdown']:.2%}, 夏普{new_run_res['metrics']['sharpe']})"
        if new_run_res.get("status") == "success"
        else f"回测失败: {new_run_res.get('error')}"))
    note = re.sub(r"验证结果\s*:.*", verify, note) or verify
    if "验证结果" not in note:
        note = f"{note}\n{verify}"

    # 新版本策略入库（旧策略不动）
    new_s = Strategy(name=old.name, source="agent", code=code,
                     description=f"自回归优化：{sug.get('detail', '')[:100]}",
                     params=old.params, parent_id=old.id,
                     version_no=(old.version_no or 1) + 1,
                     version_note=note, status="draft")
    db.add(new_s)
    db.commit()
    db.refresh(new_s)

    return {"new_strategy_id": new_s.id,
            "old_run_id": old_run.id if old_run else None,
            "new_run_id": new_run_res.get("id"),
            "version_note": note,
            "old_metrics": old_run.metrics if old_run else None,
            "new_metrics": new_run_res.get("metrics")}
