"""通用工具：股票代码归一化（A股：输入统一支持裸6位代码）"""


def normalize_ts_code(raw: str) -> str:
    """裸6位数字补全交易所后缀：6/9开头→.SH，0/3开头→.SZ，4/8开头→.BJ；其余原样返回"""
    s = (raw or "").strip().upper()
    if s.isdigit() and len(s) == 6:
        if s[0] in ("6", "9"):
            return s + ".SH"
        if s[0] in ("4", "8"):
            return s + ".BJ"
        return s + ".SZ"
    return s


def resolve_ts_code(db, raw: str) -> str | None:
    """补后缀 + 后缀纠错（按6位代码唯一反查）+ 存在校验。不存在返回 None。"""
    from sqlalchemy import select as _select

    from .models import StockBasic
    ts_code = normalize_ts_code(raw)
    if db.get(StockBasic, ts_code):
        return ts_code
    symbol = ts_code.split(".")[0]
    alts = db.scalars(_select(StockBasic).where(StockBasic.symbol == symbol)).all()
    if len(alts) == 1:
        return alts[0].ts_code
    return None
