"""策略生成 Agent（SSE generator）

流程：博查搜 "quantitative trading strategy {prompt}" 参考资料
  → deepseek-chat 生成符合沙箱 API 的策略代码 + 说明
  → 沙箱试跑（近120交易日），失败则带错误让 LLM 修复重试（最多2次）
yield 事件：{"event": "status"|"section"|"error"|"done", "data": {...}}
"""
from __future__ import annotations

import json
import re
from typing import Any, Generator

from sqlalchemy.orm import Session

try:
    from ..services.deepseek_client import client as ds_client

    def _chat(messages, model=None, **kw) -> str:
        return ds_client.chat(messages, model=model, **kw)
except ImportError:  # 降级 stub（并行 agent 未完成时自测用）
    def _chat(messages, model=None, **kw) -> str:
        return (
            "```python\n" + SAMPLE_STRATEGY + "```\n\n示例均线交叉策略（降级stub输出）。"
        )

try:
    from ..services.bocha_search import web_search
except ImportError:  # 降级 stub
    def web_search(query: str, count: int = 10, freshness: str = "oneMonth") -> list:
        return []


SAMPLE_STRATEGY = '''
def init(ctx):
    ctx.set("fast", ctx.params.get("fast", 5))
    ctx.set("slow", ctx.params.get("slow", 20))

def on_bar(ctx, bar, i):
    if i < ctx.get("slow") + 1:
        return
    fast = ctx.ema(ctx.get("fast"))
    slow = ctx.ema(ctx.get("slow"))
    if ctx.crossover(fast, slow, i):
        ctx.buy(1.0, "金叉")
    elif ctx.crossunder(fast, slow, i):
        ctx.sell_all("死叉")
'''

SYSTEM_PROMPT = """你是量化策略工程师。为A股模拟交易平台生成策略代码。
沙箱 API 严格限制如下，只能用这些能力：
- 必须定义 def init(ctx): ... 和 def on_bar(ctx, bar, i): ...
- ctx.get(k)/ctx.set(k,v)/ctx.params(dict)
- ctx.close(i)/open(i)/high(i)/low(i)/volume(i)  历史行情(i可为负数回看，禁止访问未来)
- ctx.ema(period)/ma(period)/rsi(period) 返回与bar对齐的序列list（未成熟为None）；ctx.macd() 返回 {"dif":[],"dea":[],"hist":[]}
- ctx.crossover(a,b,i)/crossunder(a,b,i)
- ctx.buy(ratio=1.0, reason="")/ctx.sell_all(reason="")/ctx.sell(qty, reason="")
- ctx.position_qty/ctx.cash/ctx.bar_count
- bar 是 dict: {date, open, high, low, close, volume}
禁止：import、open、eval、exec、任何以__开头的名字。可用内置: abs/min/max/len/sum/range/sorted/enumerate/print/round/int/float/math 等。
输出格式（严格遵守）：
先一段不超过200字的中文策略说明；
然后一个 ```python 代码块，只含 init/on_bar 两个函数（可加普通辅助函数）。
"""


def _extract_code(text: str) -> str | None:
    m = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    return m[0].strip() if m else None


def generate_strategy(db: Session, prompt: str) -> Generator[dict, None, Any]:
    """生成策略并入库（source=agent），yield SSE 事件 dict"""
    from ..models import Strategy
    from ..services.backtest_engine import validate_strategy_code

    yield {"event": "status", "data": {"stage": "searching", "msg": "搜索策略参考资料…"}}
    refs = web_search(f"quantitative trading strategy {prompt}", count=8)
    ref_text = "\n".join(f"- {r.get('title', '')}: {r.get('snippet', '')[:150]}"
                         for r in refs[:6]) or "（无搜索结果）"

    code: str | None = None
    desc = ""
    last_err = None
    for attempt in range(3):  # 首次 + 2次修复
        if attempt == 0:
            yield {"event": "status", "data": {"stage": "generating",
                                               "msg": "DeepSeek 生成策略代码…"}}
            user = f"用户需求：{prompt}\n\n参考资料：\n{ref_text}"
        else:
            yield {"event": "status", "data": {"stage": "fixing",
                                               "msg": f"沙箱校验失败，第{attempt}次修复…"}}
            user = (f"之前生成的策略在沙箱校验失败。\n错误：{last_err}\n"
                    f"请修复并重新输出（说明+```python代码块```).\n上次输出：\n{code}")
        try:
            text = _chat([{"role": "system", "content": SYSTEM_PROMPT},
                          {"role": "user", "content": user}],
                         model="deepseek-chat", temperature=0.5, max_tokens=4096)
        except Exception as e:  # noqa: BLE001
            yield {"event": "error", "data": {"msg": f"DeepSeek 调用失败: {e}"}}
            return
        code = _extract_code(text)
        desc = (text.split("```")[0]).strip()[:2000] or "AI生成策略"
        if code is None:
            last_err = "未找到```python代码块"
            continue
        yield {"event": "section", "data": {"role": "code", "title": "策略代码",
                                            "content": code}}
        yield {"event": "section", "data": {"role": "description", "title": "策略说明",
                                            "content": desc}}
        yield {"event": "status", "data": {"stage": "validating", "msg": "沙箱试跑校验…"}}
        v = validate_strategy_code(db, code)
        if v.get("ok"):
            strat = Strategy(name=prompt[:60] or "AI策略", source="agent",
                             code=code, description=desc,
                             params={"fast": 5, "slow": 20}, status="draft")
            db.add(strat)
            db.commit()
            db.refresh(strat)
            yield {"event": "done", "data": {"strategy_id": strat.id,
                                             "validation": v}}
            return
        last_err = v.get("error")

    yield {"event": "error", "data": {"msg": f"策略生成失败（重试2次仍未通过沙箱校验）: {last_err}"}}
