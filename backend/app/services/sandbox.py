"""策略代码沙箱执行（契约第4节沙箱 API）

受限 exec：
- 编译期 AST 检查：禁止 import / 含 "__" 的名字与属性
- 运行期 __builtins__ 白名单（无 __import__/open/eval/exec）
- __name__ = "__sandbox__"，只有 init(ctx) / on_bar(ctx, bar, i) 两个入口
- 整次执行超时：threading + join(timeout)，上限 = bar数 * 0.05s（最低 5s）
"""
from __future__ import annotations

import ast
import math
import threading
from typing import Any, Callable

import pandas as pd


class SandboxError(Exception):
    """沙箱违规 / 策略错误"""


# ---------------------------------------------------------------- 白名单 builtins
SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs, "min": min, "max": max, "len": len, "sum": sum,
    "range": range, "sorted": sorted, "reversed": reversed,
    "enumerate": enumerate, "zip": zip, "map": map, "filter": filter,
    "print": print, "round": round, "pow": pow, "divmod": divmod,
    "int": int, "float": float, "bool": bool, "str": str,
    "list": list, "dict": dict, "tuple": tuple, "set": set,
    "isinstance": isinstance, "any": any, "all": all,
    "Exception": Exception, "ValueError": ValueError,
    "TypeError": TypeError, "ZeroDivisionError": ZeroDivisionError,
    "IndexError": IndexError, "KeyError": KeyError,
    "ArithmeticError": ArithmeticError, "RuntimeError": RuntimeError,
    "StopIteration": StopIteration, "True": True, "False": False, "None": None,
    "math": math,
    "__build_class__": __build_class__,  # 允许 class 语句（兼容层/用户类定义；危险调用仍被AST拦截）
}


# ---------------------------------------------------------------- AST 检查
def _check_code(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SandboxError(f"语法错误: {e}") from e
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise SandboxError("沙箱禁止 import")
        if isinstance(node, ast.Name) and "__" in node.id:
            raise SandboxError(f"沙箱禁止访问保留名: {node.id}")
        if isinstance(node, ast.Attribute) and "__" in node.attr:
            raise SandboxError(f"沙箱禁止访问保留属性: {node.attr}")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("eval", "exec", "compile", "open", "__import__"):
            raise SandboxError(f"沙箱禁止调用: {node.func.id}()")


def compile_strategy(code: str) -> tuple[Callable | None, Callable]:
    """编译策略代码，返回 (init, on_bar)。违规抛 SandboxError。"""
    _check_code(code)
    g: dict[str, Any] = {"__builtins__": SAFE_BUILTINS, "__name__": "__sandbox__"}
    try:
        exec(compile(code, "<strategy>", "exec"), g)  # noqa: S102 受限沙箱
    except SandboxError:
        raise
    except Exception as e:  # noqa: BLE001
        raise SandboxError(f"策略代码执行失败: {e}") from e
    init = g.get("init")
    on_bar = g.get("on_bar")
    if not callable(on_bar):
        raise SandboxError("策略代码必须定义 on_bar(ctx, bar, i)")
    if init is not None and not callable(init):
        raise SandboxError("init 必须是可调用对象")
    return init, on_bar


# ---------------------------------------------------------------- Ctx（契约第4节）
class Ctx:
    """策略可见上下文：数据只到当前 bar（防未来函数）"""

    def __init__(self, bars: list[dict], trader: Any, params: dict | None = None):
        self._bars = bars                     # [{date,open,high,low,close,volume,pre_close?}]
        self._trader = trader                 # 需提供 buy/sell/sell_all/position_qty/cash
        self._params = dict(params or {})
        self._store: dict[str, Any] = {}
        self._i = -1                          # 当前 bar 下标（引擎设置）
        self._cache: dict[tuple, list] = {}

    # ---- 状态 ----
    @property
    def bar_count(self) -> int:
        return self._i + 1

    @property
    def position_qty(self) -> int:
        return self._trader.position_qty

    @property
    def cash(self) -> float:
        return self._trader.cash

    @property
    def params(self) -> dict:
        return self._params

    def get(self, k: str, default: Any = None) -> Any:
        return self._store.get(k, default)

    def set(self, k: str, v: Any) -> None:
        self._store[k] = v

    # ---- 行情访问（i 可为负，从当前 bar 往回数；禁止 > 当前 i）----
    def _idx(self, i: int = 0) -> int:
        idx = i if i >= 0 else self._i + 1 + i
        if idx < 0 or idx > self._i:
            raise SandboxError(f"索引越界或穿越未来: i={i} (当前 bar={self._i})")
        return idx

    def _get(self, key: str, i: int = 0) -> float:
        return float(self._bars[self._idx(i)][key])

    def close(self, i: int = 0) -> float:
        return self._get("close", i)

    def open(self, i: int = 0) -> float:
        return self._get("open", i)

    def high(self, i: int = 0) -> float:
        return self._get("high", i)

    def low(self, i: int = 0) -> float:
        return self._get("low", i)

    def volume(self, i: int = 0) -> float:
        return self._get("volume", i)

    def date(self, i: int = 0) -> str:
        return str(self._bars[self._idx(i)]["date"])

    # ---- 指标（基于截至当前 bar 的完整序列，与 bar 对齐，未成熟处为 None）----
    def _closes(self) -> list[float]:
        return [float(b["close"]) for b in self._bars[: self._i + 1]]

    def _ind(self, key: str, period: int | None = None) -> list:
        ck = (key, period, self._i)
        if ck in self._cache:
            return self._cache[ck]
        s = pd.Series(self._closes(), dtype=float)
        if key == "ma":
            r = s.rolling(period).mean()
        elif key == "ema":
            r = s.ewm(span=period, adjust=False).mean()
        elif key == "rsi":
            delta = s.diff()
            gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
            loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
            rs = gain / loss.replace(0, pd.NA)
            r = 100 - 100 / (1 + rs)
            r = r.fillna(100.0).where(loss.notna(), 100.0)
            r = r.where(s.notna())
        elif key == "macd":  # 不应直接走到这里
            raise SandboxError("macd 请用 ctx.macd()")
        else:
            raise SandboxError(f"未知指标: {key}")
        out = [None if pd.isna(v) else round(float(v), 6) for v in r]
        self._cache[ck] = out
        return out

    def _macd_full(self) -> tuple[list, list, list]:
        ck = ("macdfull", None, self._i)
        if ck in self._cache:
            return self._cache[ck]
        s = pd.Series(self._closes(), dtype=float)
        ema12 = s.ewm(span=12, adjust=False).mean()
        ema26 = s.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = (dif - dea) * 2  # 国内惯例 MACD 柱 = 2*(DIF-DEA)
        conv = lambda ser: [None if pd.isna(v) else round(float(v), 6) for v in ser]  # noqa: E731
        out = (conv(dif), conv(dea), conv(hist))
        self._cache[ck] = out
        return out

    def ma(self, period: int) -> list:
        return self._ind("ma", period)

    def ema(self, period: int) -> list:
        return self._ind("ema", period)

    def rsi(self, period: int = 14) -> list:
        return self._ind("rsi", period)

    def macd(self) -> dict:
        dif, dea, hist = self._macd_full()
        return {"dif": dif, "dea": dea, "hist": hist}

    # ---- 交叉判断（a/b 为与 bar 对齐的序列 list）----
    def crossover(self, a: list, b: list, i: int | None = None) -> bool:
        i = self._i if i is None else i
        if i < 1 or i >= len(a) or i >= len(b):
            return False
        a0, a1, b0, b1 = a[i - 1], a[i], b[i - 1], b[i]
        if None in (a0, a1, b0, b1):
            return False
        return a0 <= b0 and a1 > b1

    def crossunder(self, a: list, b: list, i: int | None = None) -> bool:
        i = self._i if i is None else i
        if i < 1 or i >= len(a) or i >= len(b):
            return False
        a0, a1, b0, b1 = a[i - 1], a[i], b[i - 1], b[i]
        if None in (a0, a1, b0, b1):
            return False
        return a0 >= b0 and a1 < b1

    # ---- 交易（委托 trader，按当根收盘价）----
    def buy(self, ratio: float = 1.0, reason: str = "") -> None:
        self._trader.buy(float(ratio), reason)

    def sell_all(self, reason: str = "") -> None:
        self._trader.sell_all(reason)

    def sell(self, qty: int, reason: str = "") -> None:
        self._trader.sell(int(qty), reason)


# ---------------------------------------------------------------- 执行器
def run_in_sandbox(
    code: str,
    bars: list[dict],
    trader: Any,
    params: dict | None = None,
    per_bar_seconds: float = 0.05,
    min_seconds: float = 5.0,
) -> dict:
    """逐 bar 进程内执行。返回 {"ok": bool, "error": str|None, "stopped_at": int}"""
    result: dict[str, Any] = {"ok": False, "error": None, "stopped_at": None}
    if not bars:
        result["error"] = "无K线数据"
        return result
    timeout = max(min_seconds, len(bars) * per_bar_seconds)
    deadline = threading.Event()

    def worker():
        ctx: Ctx | None = None
        try:
            init, on_bar = compile_strategy(code)
            ctx = Ctx(bars, trader, params)
            trader.attach(ctx)
            if init is not None:
                init(ctx)
            for i, bar in enumerate(bars):
                if deadline.is_set():
                    return
                ctx._i = i
                ctx._cache.clear()  # 每根 bar 指标需基于新截面重算
                on_bar(ctx, bar, i)
            result["ok"] = True
        except SandboxError as e:
            result["error"] = str(e)
            result["stopped_at"] = ctx._i if ctx else None
        except Exception as e:  # noqa: BLE001 单次 on_bar 异常终止回测
            result["error"] = f"{type(e).__name__}: {e}"
            result["stopped_at"] = ctx._i if ctx else None

    t = threading.Thread(target=worker, daemon=True, name="sandbox-run")
    t.start()
    t.join(timeout)
    if t.is_alive():
        deadline.set()
        result["error"] = f"执行超时(>{timeout:.1f}s)已终止"
        result["ok"] = False
    return result
