"""聚宽(JoinQuant)策略适配器：把聚宽策略转换为沙箱可运行代码

双轨：① 兼容层(shim)确定性桥接 ② LLM转换兜底
限制：多股票组合选股类策略受单标的沙箱限制，订单仅作用于回测标的
"""
import json
import logging
import re

from ..config import settings

log = logging.getLogger(__name__)

# ---------------- 预处理 ----------------

def extract_code(raw: str) -> tuple[str, str]:
    """返回 (代码, 格式说明)。支持 .ipynb JSON 源码与纯 Python"""
    s = (raw or "").strip()
    if s.startswith("{") and '"cells"' in s:
        try:
            nb = json.loads(s)
            parts = []
            for cell in nb.get("cells", []):
                if cell.get("cell_type") == "code":
                    src = "".join(cell.get("source", []))
                    parts.append(src)
            code = "\n\n".join(parts)
            return code, "notebook"
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"Notebook 解析失败: {e}") from e
    return s, "python"


def strip_imports(code: str) -> str:
    """剥离聚宽环境的 import 行（jqdata/pandas/numpy/datetime/math 等，兼容层内置替代）"""
    lines = []
    for line in code.splitlines():
        if re.match(r"\s*(import|from)\s+(jqdata|jqfactor|pandas|numpy|datetime|math| "
                    r"sqlalchemy|six|collections)\b", line):
            continue
        if re.match(r"\s*(import|from)\s+\w+", line) and not line.strip().startswith("#"):
            # 其他 import 也剥离（沙箱禁），保留注释掉的
            continue
        lines.append(line)
    return "\n".join(lines)


# ---------------- 兼容层 v2（纯 Python；math 在沙箱白名单；源码零 dunder 属性访问） ----------------

SHIM = '''
# ==== 聚宽(JQ)兼容层 · 自动生成 ====
class _NS:
    pass

g = _NS()

# --- np 精简实现（math 白名单可用）---
def _mean(xs):
    return sum(xs) / len(xs) if len(xs) else 0.0

def _arange(n):
    return list(range(int(n)))

def _var(xs, ddof=1):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return sum((x - m) ** 2 for x in xs) / max(1, len(xs) - ddof)

def _polyfit(x, y, deg):
    # 一元线性最小二乘（deg=1），返回 [slope, intercept]
    n = len(x)
    if n < 2:
        return [0.0, float(y[0]) if len(y) else 0.0]
    mx, my = sum(x) / n, sum(y) / n
    sxy = sum((x[k] - mx) * (y[k] - my) for k in range(n))
    sxx = sum((x[k] - mx) ** 2 for k in range(n))
    slope = sxy / sxx if sxx else 0.0
    return [slope, my - slope * mx]

np = _NS()
np.log = math.log
np.exp = math.exp
np.pow = pow
np.sqrt = math.sqrt
np.mean = _mean
np.min = min
np.max = max
np.abs = abs
np.sum = sum
np.arange = _arange
np.var = _var
np.polyfit = _polyfit

# 聚宽 jqdata 全局直出的数学函数
mean = _mean

# --- pd 精简实现 ---
class _FS(list):
    pass

def _ser(xs=None, index=None, dtype=None, **k):
    s = _FS(xs if xs is not None else [])
    s.values = list(s)
    return s

class _Frame:
    def __init__(self, d):
        self._d = d
    def __getitem__(self, k):
        return self._d[k]
    def __getattr__(self, k):
        return self._d[k]
    def keys(self):
        return list(self._d.keys())

def _frame(d=None, index=None, **k):
    return _Frame(d or {})

pd = _NS()
pd.Series = _ser
pd.DataFrame = _frame
pd.concat = lambda objs, axis=1, sort=False: _frame(objs[0]._d if objs and isinstance(objs[0], _Frame) else {})

# --- log ---
class _Log:
    def info(self, *a): print("[INFO]", *a)
    def warn(self, *a): print("[WARN]", *a)
    def error(self, *a): print("[ERROR]", *a)
log = _Log()

def set_benchmark(*a, **k): pass
def set_option(*a, **k): pass
def set_order_cost(*a, **k): pass
def set_slippage(*a, **k): pass
def set_stop_loss(*a, **k): pass
def get_security_info(code, *a):
    i = _NS(); i.display_name = str(code); return i

# ---- 桥接状态 ----
_S = _NS()
_S.scheduled = []
_S.sec = None

def _cur(ctx):
    return ctx.close(-1) if ctx.bar_count else None

def _hist_series(ctx, field, count):
    getter = {"open": ctx.open, "high": ctx.high, "low": ctx.low,
              "close": ctx.close, "volume": ctx.volume,
              "money": ctx.volume, "avg": ctx.close, "price": ctx.close}.get(field, ctx.close)
    n = ctx.bar_count
    take = min(int(count), n)
    return _ser([getter(n - take + k) for k in range(take)])

def attribute_history(security, count, unit="1d",
                      fields=("open", "close", "high", "low", "volume", "money"), **k):
    ctx = _S.ctx
    if isinstance(fields, str):
        fields = (fields,)
    return _frame({f: _hist_series(ctx, f, count) for f in fields})

def history(count, unit="1d", field="close", security_list=None, df=True, **k):
    return _hist_series(_S.ctx, field, count)

def get_price(security, end_date=None, frequency="daily", count=None,
              fields=("close",), panel=False, **k):
    ctx = _S.ctx
    if isinstance(fields, str):
        fields = (fields,)
    n = count or min(ctx.bar_count, 25)
    return _frame({f: _hist_series(ctx, f, n) for f in fields})

def get_current_data():
    return _DATA

class _Data:
    def __getitem__(self, sec):
        ctx = _S.ctx
        d = _NS()
        d.close = _cur(ctx); d.open = ctx.open(-1) if ctx.bar_count else None
        d.high = ctx.high(-1) if ctx.bar_count else None
        d.low = ctx.low(-1) if ctx.bar_count else None
        d.volume = ctx.volume(-1) if ctx.bar_count else None
        d.paused = False
        return d

_DATA = _Data()

def _sync_pos_from_ctx(ctx):
    _S.pos_qty = ctx.position_qty

def _buy_qty(ctx, qty, reason="jq"):
    px = _cur(ctx)
    if not px or qty < 100:
        return
    need = qty * px
    if ctx.cash > 0:
        ctx.buy(min(1.0, need / ctx.cash), reason)

def _sell_qty(ctx, qty, reason="jq"):
    qty = int(min(qty, ctx.position_qty) / 100) * 100
    if qty >= 100:
        ctx.sell(qty, reason)

def order(security, amount, style=None, **k):
    ctx = _S.ctx
    if amount > 0:
        _buy_qty(ctx, int(amount / 100) * 100, "jq:order")
    elif amount < 0:
        _sell_qty(ctx, -amount, "jq:order")

def order_value(security, value, style=None, **k):
    ctx = _S.ctx
    px = _cur(ctx)
    if not px:
        return
    if value > 0:
        _buy_qty(ctx, int(value / px / 100) * 100, "jq:order_value")
    elif value < 0:
        _sell_qty(ctx, int(-value / px / 100) * 100, "jq:order_value")

def order_target(security, tqty, **k):
    ctx = _S.ctx
    _sync_pos_from_ctx(ctx)
    delta = tqty - ctx.position_qty
    if delta > 0:
        _buy_qty(ctx, int(delta / 100) * 100, "jq:order_target")
    elif delta < 0:
        _sell_qty(ctx, -delta, "jq:order_target")

def order_target_value(security, tvalue, **k):
    ctx = _S.ctx
    px = _cur(ctx)
    if not px:
        return
    _sync_pos_from_ctx(ctx)
    delta = tvalue - ctx.position_qty * px
    if delta > 0:
        _buy_qty(ctx, int(delta / px / 100) * 100, "jq:order_target_value")
    elif delta < 0:
        _sell_qty(ctx, int(-delta / px / 100) * 100, "jq:order_target_value")

def run_daily(func=None, time="every_bar", **k):
    if func is not None:
        _S.scheduled.append(func)

class _Portfolio:
    pass

_jq_ctx = _NS()
_jq_ctx.portfolio = _Portfolio()
_jq_ctx.previous_date = None
_jq_ctx.current_dt = None

def _refresh_portfolio(ctx, date_str):
    p = _jq_ctx.portfolio
    _sync_pos_from_ctx(ctx)
    px = _cur(ctx) or 0
    p.cash = ctx.cash
    p.positions_value = ctx.position_qty * px
    p.total_value = p.cash + p.positions_value
    p.invested_value = p.positions_value
    p.portfolio_value = p.total_value
    pos = _NS()
    pos.closeable_amount = ctx.position_qty
    pos.total_amount = ctx.position_qty
    pos.price = px
    p.positions = {"target": pos}
    _jq_ctx.current_dt = date_str
'''


def build_wrapped(jq_code: str, target_sec_note: str = "") -> str:
    """兼容层 + 用户代码(剥离import) + 桥接入口"""
    user = strip_imports(jq_code)
    bridge = '''

# ==== 桥接入口（本平台沙箱 → 聚宽生命周期） ====
def init(ctx):
    _S.ctx = ctx
    try:
        initialize(_jq_ctx)
    except NameError:
        pass

def on_bar(ctx, bar, i):
    _S.ctx = ctx
    _refresh_portfolio(ctx, bar.get("date") if isinstance(bar, dict) else None)
    for fn in list(_S.scheduled):
        fn(_jq_ctx)
    try:
        handle_data(_jq_ctx, _DATA)
    except NameError:
        pass
'''
    return f"{SHIM}\n\n# ==== 用户聚宽策略 ====\n{user}\n{bridge}"


# ---------------- LLM 转换兜底 ----------------

API_DOC = """本平台策略规范（沙箱，禁 import/open/eval/exec）：
def init(ctx): ...   # 可选
def on_bar(ctx, bar, i): ...   # 必须有
ctx API：ctx.get(k)/ctx.set(k,v)/ctx.params；序列：ctx.close(i)/.open(i)/.high(i)/.low(i)/.volume(i)
  （i 为 bar 序号，可为负=从当前bar倒数）；指标：ctx.ma(p)/ctx.ema(p)/ctx.rsi(p)/ctx.macd()
  交叉：ctx.crossover(a,b,i)/ctx.crossunder(a,b,i)；交易：ctx.buy(ratio,reason)/ctx.sell(qty,reason)/
  ctx.sell_all(reason)；状态：ctx.position_qty/.cash/.bar_count
bar 为 dict：{date,open,high,low,close,volume}。单标的策略（当前回测的股票）。
内置：abs/min/max/sum/len/range/sorted/enumerate/print；指标返回 list（None 补齐头部）。
"""

LLM_SYSTEM = (
    "你是量化策略移植工程师。把聚宽(JoinQuant)平台的策略代码改写为本平台沙箱可运行的等价策略。"
    "规则：只保留对单一标的有效的逻辑（本平台是单股票逐bar模型，多股票选股/组合部分请省略并注释说明）；"
    "把聚宽的 initialize/handle_data/调度函数改写为 init(ctx)/on_bar(ctx,bar,i)；"
    "attribute_history/history 等历史数据改用 ctx.close(i) 等序列；"
    "order/order_target 等下单改用 ctx.buy/sell/sell_all；context.portfolio 改用 ctx.cash/ctx.position_qty；"
    "禁止任何 import。输出：先3行内说明改写要点，然后一个 ```python 代码块包含完整策略。"
)


def convert_via_llm(jq_code: str, error_hint: str = "") -> str | None:
    """LLM 转换聚宽代码为本平台代码；返回代码或 None"""
    from .deepseek_client import client as ds_client
    try:
        content = ds_client.chat(
            [{"role": "system", "content": LLM_SYSTEM},
             {"role": "user",
              "content": (f"=== 本平台API ===\n{API_DOC}\n=== 聚宽策略代码 ===\n{jq_code[:9000]}"
                          + (f"\n\n注意：直接套兼容层运行失败：{error_hint[:300]}，请修正该问题"
                             if error_hint else ""))}],
            model=settings.reasoner_model, max_tokens=4000)
    except Exception as e:  # noqa: BLE001
        log.warning("聚宽LLM转换失败: %s", e)
        return None
    blocks = re.findall(r"```python\s*(.*?)\s*```", content, re.DOTALL)
    return blocks[-1] if blocks else None
