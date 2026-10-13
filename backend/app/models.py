"""ORM 模型（全量 schema，M1 起一次性建齐）"""
import datetime as dt

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, DECIMAL, Index, Integer, JSON,
    String, Text, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def today() -> dt.date:
    return dt.date.today()


class StockBasic(Base):
    __tablename__ = "stock_basic"
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(12))
    name: Mapped[str] = mapped_column(String(32), index=True)
    area: Mapped[str | None] = mapped_column(String(16))
    industry: Mapped[str | None] = mapped_column(String(32))
    market: Mapped[str | None] = mapped_column(String(16))
    list_date: Mapped[dt.date | None] = mapped_column(Date)

    __table_args__ = (Index("idx_name", "name"),)


class DailyPrice(Base):
    """不复权日线原始数据"""
    __tablename__ = "daily_price"
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(DECIMAL(12, 4))
    high: Mapped[float] = mapped_column(DECIMAL(12, 4))
    low: Mapped[float] = mapped_column(DECIMAL(12, 4))
    close: Mapped[float] = mapped_column(DECIMAL(12, 4))
    pre_close: Mapped[float | None] = mapped_column(DECIMAL(12, 4))
    vol: Mapped[float | None] = mapped_column(DECIMAL(20, 2))     # 手
    amount: Mapped[float | None] = mapped_column(DECIMAL(20, 2))  # 千元
    pct_chg: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    simulation_only: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    __table_args__ = (Index("idx_daily_date", "trade_date"),)


class AdjFactor(Base):
    """复权因子"""
    __tablename__ = "adj_factor"
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    adj_factor: Mapped[float] = mapped_column(DECIMAL(16, 6))


class DailyBasic(Base):
    """每日估值指标：PE/PB/换手率/量比/市值"""
    __tablename__ = "daily_basic"
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    pe: Mapped[float | None] = mapped_column(DECIMAL(12, 4))       # 市盈率(动)
    pe_ttm: Mapped[float | None] = mapped_column(DECIMAL(12, 4))   # 市盈率TTM
    pb: Mapped[float | None] = mapped_column(DECIMAL(12, 4))       # 市净率
    turn_rate: Mapped[float | None] = mapped_column(DECIMAL(10, 4))  # 换手率%
    volume_ratio: Mapped[float | None] = mapped_column(DECIMAL(10, 4))  # 量比
    total_mv: Mapped[float | None] = mapped_column(DECIMAL(18, 2))   # 总市值(万元)
    circ_mv: Mapped[float | None] = mapped_column(DECIMAL(18, 2))    # 流通市值(万元)


class IndexDaily(Base):
    """指数日线（benchmark 对比用）"""
    __tablename__ = "index_daily"
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    trade_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    open: Mapped[float] = mapped_column(DECIMAL(12, 4))
    high: Mapped[float] = mapped_column(DECIMAL(12, 4))
    low: Mapped[float] = mapped_column(DECIMAL(12, 4))
    close: Mapped[float] = mapped_column(DECIMAL(12, 4))
    pct_chg: Mapped[float | None] = mapped_column(DECIMAL(10, 4))


class EventCalendar(Base):
    """事件日历：财报/解禁/除权除息（P0-3，agent 自动规避）"""
    __tablename__ = "event_calendar"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    event_type: Mapped[str] = mapped_column(String(24))  # earnings_forecast/earnings/unlock/ex_dividend
    event_date: Mapped[dt.date] = mapped_column(Date, index=True)
    detail: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(16), default="tushare")
    __table_args__ = (UniqueConstraint("ts_code", "event_type", "event_date",
                                       "detail", name="uk_event"),)


class FeishuUser(Base):
    """飞书用户（鉴权主体）"""
    __tablename__ = "feishu_user"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    open_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))     # admin / trader / viewer
    account_id: Mapped[int | None] = mapped_column(BigInteger)  # trader绑定的sim_account
    status: Mapped[str] = mapped_column(String(8), default="active")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.now, onupdate=dt.datetime.now)


class OperationLog(Base):
    """操作审计：所有飞书指令留痕"""
    __tablename__ = "operation_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    user_name: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(32))
    detail: Mapped[dict | None] = mapped_column(JSON)
    account_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.now, index=True)


class FinancialSnapshot(Base):
    __tablename__ = "financial_snapshot"
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    end_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    roe: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    eps: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    gross_margin: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    net_margin: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    debt_ratio: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    revenue_yoy: Mapped[float | None] = mapped_column(DECIMAL(10, 4))
    net_profit_yoy: Mapped[float | None] = mapped_column(DECIMAL(10, 4))


class SimAccount(Base):
    __tablename__ = "sim_account"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))  # replay / strategy
    initial_cash: Mapped[float] = mapped_column(DECIMAL(18, 2))
    cash: Mapped[float] = mapped_column(DECIMAL(18, 2))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class SimPosition(Base):
    __tablename__ = "sim_position"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, index=True)
    ts_code: Mapped[str] = mapped_column(String(16))
    qty: Mapped[int] = mapped_column(Integer)
    avg_cost: Mapped[float] = mapped_column(DECIMAL(12, 4))
    __table_args__ = (UniqueConstraint("account_id", "ts_code", name="uk_acc_stock"),)


class SimTrade(Base):
    __tablename__ = "sim_trade"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, index=True)
    ts_code: Mapped[str] = mapped_column(String(16))
    trade_date: Mapped[dt.date] = mapped_column(Date)
    side: Mapped[str] = mapped_column(String(4))  # buy/sell
    price: Mapped[float] = mapped_column(DECIMAL(12, 4))
    qty: Mapped[int] = mapped_column(Integer)
    amount: Mapped[float] = mapped_column(DECIMAL(18, 2))
    fee: Mapped[float] = mapped_column(DECIMAL(10, 2))
    source: Mapped[str] = mapped_column(String(16))  # manual / strategy
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    note: Mapped[str | None] = mapped_column(String(255))
    simulation_only: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class ReplaySession(Base):
    __tablename__ = "replay_session"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger)
    ts_code: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[dt.date] = mapped_column(Date)
    cursor_date: Mapped[dt.date] = mapped_column(Date)
    auto_play: Mapped[bool] = mapped_column(Boolean, default=False)
    speed_days: Mapped[int] = mapped_column(Integer, default=1)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    strategy_last_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now, onupdate=dt.datetime.now)


class Strategy(Base):
    __tablename__ = "strategy"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    source: Mapped[str] = mapped_column(String(16))  # agent / import / manual
    code: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    params: Mapped[dict | None] = mapped_column(JSON)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    version_note: Mapped[str | None] = mapped_column(Text)
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now, onupdate=dt.datetime.now)


class BacktestRun(Base):
    __tablename__ = "backtest_run"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    ts_codes: Mapped[dict | None] = mapped_column(JSON)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    initial_cash: Mapped[float] = mapped_column(DECIMAL(18, 2))
    params: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="running")
    metrics: Mapped[dict | None] = mapped_column(JSON)
    equity_curve: Mapped[dict | None] = mapped_column(JSON)
    trades_json: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class StrategyBinding(Base):
    __tablename__ = "strategy_binding"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(BigInteger)
    account_id: Mapped[int] = mapped_column(BigInteger)
    ts_codes: Mapped[dict | None] = mapped_column(JSON)
    params: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="active")
    __table_args__ = (UniqueConstraint("strategy_id", "account_id", name="uk_strat_acc"),)


class StrategyDiscussion(Base):
    """策略对话线程：用户与AI讨论策略；AI 可附新代码提案（proposed_code）"""
    __tablename__ = "strategy_discussion"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    proposed_code: Mapped[str | None] = mapped_column(Text)  # assistant 消息携带的新代码
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class ParamScan(Base):
    """参数寻优任务：网格扫描 + 过拟合诊断"""
    __tablename__ = "param_scan"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id: Mapped[int] = mapped_column(BigInteger, index=True)
    ts_code: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    grid: Mapped[dict | None] = mapped_column(JSON)        # [{name,start,end,step}]
    status: Mapped[str] = mapped_column(String(16))         # running/done/failed
    results: Mapped[dict | None] = mapped_column(JSON)      # [{params:{}, metrics:{}}]
    best: Mapped[dict | None] = mapped_column(JSON)         # {params, metrics, overfit_risk, plain_center}
    heat: Mapped[dict | None] = mapped_column(JSON)         # {x_name,y_name,x_vals,y_vals,matrix}
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class AnalysisReport(Base):
    __tablename__ = "analysis_report"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    as_of_date: Mapped[dt.date] = mapped_column(Date)
    report_type: Mapped[str] = mapped_column(String(16))  # company/strategy_gen/review/synthesis
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(64))
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    simulation_only: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class ReportChain(Base):
    __tablename__ = "report_chain"
    ts_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    report_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prev_report_id: Mapped[int | None] = mapped_column(BigInteger)


class ReportDiscussion(Base):
    """报告讨论线程：用户与AI就某份报告的多轮对话"""
    __tablename__ = "report_discussion"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(BigInteger, index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class ReportMerge(Base):
    """人机综合分析：原始AI报告 + 用户讨论 自动融合（每报告一份，随讨论自动更新）"""
    __tablename__ = "report_merge"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    report_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime, default=dt.datetime.now, onupdate=dt.datetime.now)


class WatchTask(Base):
    __tablename__ = "watch_task"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    source_report_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    task_type: Mapped[str] = mapped_column(String(16))  # price_level/event/indicator
    condition_json: Mapped[dict | None] = mapped_column(JSON)
    expect_json: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="waiting", index=True)
    trigger_date: Mapped[dt.date | None] = mapped_column(Date)
    trigger_detail: Mapped[str | None] = mapped_column(String(255))
    expire_date: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now, onupdate=dt.datetime.now)


class TradeReview(Base):
    __tablename__ = "trade_review"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, index=True)
    scope: Mapped[str] = mapped_column(String(16))  # manual/strategy/all
    strategy_id: Mapped[int | None] = mapped_column(BigInteger)
    period_start: Mapped[dt.date | None] = mapped_column(Date)
    period_end: Mapped[dt.date | None] = mapped_column(Date)
    content: Mapped[str] = mapped_column(Text)
    suggestions: Mapped[dict | None] = mapped_column(JSON)
    followup: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class NewsItem(Base):
    __tablename__ = "news_item"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_code: Mapped[str | None] = mapped_column(String(16), index=True)
    source: Mapped[str] = mapped_column(String(16))  # tushare_news/tushare_ann/bocha
    external_id: Mapped[str] = mapped_column(String(128))
    title: Mapped[str] = mapped_column(String(512))
    content: Mapped[str | None] = mapped_column(Text)
    pub_time: Mapped[dt.datetime | None] = mapped_column(DateTime)
    sentiment: Mapped[str | None] = mapped_column(String(8))  # pos/neu/neg
    __table_args__ = (UniqueConstraint("source", "external_id", name="uk_src_ext"),)


class AgentConfig(Base):
    """自主交易 agent 配置（股票池/参考策略/风格/风控/启停）"""
    __tablename__ = "agent_config"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    stocks: Mapped[dict | None] = mapped_column(JSON)          # ["000001.SZ", ...]
    disabled_stocks: Mapped[dict | None] = mapped_column(JSON, default=list)  # 停止巡盘的股票
    reference_strategies: Mapped[dict | None] = mapped_column(JSON)  # {"000001.SZ": [1,2]}
    style: Mapped[str] = mapped_column(String(8), default="steady")
    patrol_freq: Mapped[int] = mapped_column(Integer, default=60)   # 盘中巡逻间隔(分钟)
    risk_params: Mapped[dict | None] = mapped_column(JSON)
    prompt_notes: Mapped[str | None] = mapped_column(Text)     # 审查/学习注入区
    status: Mapped[str] = mapped_column(String(8), default="stopped")
    pause_until: Mapped[dt.date | None] = mapped_column(Date)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now, onupdate=dt.datetime.now)


class AgentDecision(Base):
    """agent 决策留痕（含 hold 与被风控拒绝）"""
    __tablename__ = "agent_decision"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    account_id: Mapped[int] = mapped_column(BigInteger, index=True)
    ts_code: Mapped[str] = mapped_column(String(16))
    run_date: Mapped[dt.date] = mapped_column(Date)
    run_time: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
    decision_type: Mapped[str] = mapped_column(String(8))      # intraday/daily
    action: Mapped[str] = mapped_column(String(8))             # buy/sell/hold
    qty: Mapped[int | None] = mapped_column(Integer)
    target_pos_pct: Mapped[float | None] = mapped_column(Integer)
    price: Mapped[float | None] = mapped_column(DECIMAL(12, 4))
    status: Mapped[str] = mapped_column(String(16))            # executed/rejected_by_risk/failed/hold
    risk_note: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(Text)
    thesis: Mapped[str | None] = mapped_column(Text)
    invalidation: Mapped[dict | None] = mapped_column(JSON)
    analysis_md: Mapped[str | None] = mapped_column(Text)
    inputs_snapshot: Mapped[dict | None] = mapped_column(JSON)
    trade_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class PetWatchlist(Base):
    """桌面宠物自选股清单"""
    __tablename__ = "pet_watchlist"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), unique=True)
    added_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class PetAlertRule(Base):
    """桌面宠物警报规则：threshold(涨跌幅)/cross(价格线)/spike(快速异动)"""
    __tablename__ = "pet_alert_rules"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts_code: Mapped[str] = mapped_column(String(16), index=True)
    rule_type: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict | None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_fired_at: Mapped[dt.datetime | None] = mapped_column(DateTime)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)
