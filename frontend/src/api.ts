import axios from 'axios'
import { parseSSE, type SSEHandler } from './sse'

export const api = axios.create({ baseURL: '/api', timeout: 120000 })

// ---------- 通用类型 ----------

export interface StockInfo {
  ts_code: string
  symbol: string
  name: string
  area?: string
  industry?: string
  market?: string
  list_date?: string
}

export interface Bar {
  date: string
  open: number
  high: number
  low: number
  close: number
  pre_close?: number
  volume?: number
  amount?: number
  pct_chg?: number
}

export interface TradeRecord {
  id?: number
  account_id?: number
  ts_code: string
  name?: string
  trade_date: string
  side: 'buy' | 'sell'
  price: number
  qty: number
  amount: number
  fee: number
  source?: string
  strategy_id?: number | null
  note?: string
}

// ---------- SSE ----------

async function postSSE(url: string, body: unknown, onEvent: SSEHandler): Promise<void> {
  const resp = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
  })
  await parseSSE(resp, onEvent)
}

// ---------- 行情 ----------

export const searchStocks = (q: string) =>
  api.get<StockInfo[]>('/stocks', { params: { q } }).then(r => r.data)

export const getDaily = (tsCode: string, adjust: string, start?: string, end?: string) =>
  api.get<Bar[]>(`/stocks/${tsCode}/daily`, { params: { adjust, start, end } }).then(r => r.data)

// ---------- 回放交易 ----------

export interface ReplaySession {
  id: number
  ts_code: string
  name?: string
  account_id?: number
  start_date: string
  cursor_date: string
  auto_play?: boolean
  strategy_id?: number | null
  strategy_name?: string | null
  params?: Record<string, unknown> | null
}

export interface AccountSummary {
  cash: number
  market_value: number
  total_value: number
  profit: number
  profit_pct: number
}

export interface Position {
  ts_code: string
  name: string
  qty: number
  avg_cost: number
  last_price: number
  market_value: number
  profit: number
  profit_pct: number
}

export interface ReplayDetail {
  session: ReplaySession
  account: AccountSummary
  positions: Position[]
  bars: Bar[]
  trades: TradeRecord[]
}

export interface ReplayListItem {
  id: number
  ts_code: string
  name?: string
  account_id?: number
  account_name?: string
  profit_pct?: number
  strategy_id?: number | null
  start_date: string
  cursor_date: string
  total_value: number
  updated_at: string
}

export interface ReplaySummary {
  trades: TradeRecord[]
  win_rate: number
  total_profit: number
  profit_pct: number
  max_drawdown: number
  buy_count: number
  sell_count: number
}

export const listReplays = () => api.get<ReplayListItem[]>('/replay').then(r => r.data)
export const createReplay = (payload: { ts_code: string; start_date: string; initial_cash?: number; name?: string; account_id?: number }) =>
  api.post<ReplaySession>('/replay', payload).then(r => r.data)
export interface AccountPositions {
  account_id: number
  cash: number
  positions: { ts_code: string; qty: number; avg_cost: number; last_price: number; market_value: number; pnl: number; pnl_pct: number }[]
}
export const getAccountPositions = (id: number) =>
  api.get<AccountPositions>(`/accounts/${id}/positions`).then(r => r.data)
export const getReplay = (id: number) => api.get<ReplayDetail>(`/replay/${id}`).then(r => r.data)
export const replayNext = (id: number, days = 1) =>
  api.post<ReplayDetail>(`/replay/${id}/next`, { days }).then(r => r.data)
export const replayOrder = (id: number, side: 'buy' | 'sell', qty: number) =>
  api.post<{ trade: TradeRecord; account: AccountSummary; positions: Position[] }>(`/replay/${id}/order`, { side, qty }).then(r => r.data)
export const replayGoto = (id: number, date: string) =>
  api.post<ReplayDetail>(`/replay/${id}/goto`, { date }).then(r => r.data)
export const bindReplayStrategy = (id: number, strategyId: number, params?: Record<string, unknown>) =>
  api.post(`/replay/${id}/strategy`, { strategy_id: strategyId, params }).then(r => r.data)
export const unbindReplayStrategy = (id: number) =>
  api.delete(`/replay/${id}/strategy`).then(r => r.data)
export const deleteReplay = (id: number) => api.delete(`/replay/${id}`).then(r => r.data)
export const getReplaySummary = (id: number) =>
  api.get<ReplaySummary>(`/replay/${id}/summary`).then(r => r.data)

// ---------- 账户 / 交易记录 ----------

export interface Account {
  id: number
  name: string
  mode: string
  cash: number
  market_value: number
  total_value: number
  initial_cash: number
  profit: number
  profit_pct: number
  created_at: string
}

export const listAccounts = () => api.get<Account[]>('/accounts').then(r => r.data)
export const deleteAccount = (id: number) => api.delete(`/accounts/${id}`).then(r => r.data)
export const createAccount = (payload: { name: string; mode: string; initial_cash: number }) =>
  api.post<{ id: number; name: string; mode: string; initial_cash: number; cash: number }>('/accounts', payload).then(r => r.data)

export interface TradesQuery {
  account_id?: number
  ts_code?: string
  source?: string
  side?: string
  start?: string
  end?: string
  page?: number
  page_size?: number
}

export interface TradesResult {
  total: number
  items: TradeRecord[]
}

export const listTrades = (params: TradesQuery) =>
  api.get<TradesResult>('/trades', { params }).then(r => r.data)

export interface TradesStats {
  count: number
  buy_count: number
  sell_count: number
  win_rate: number
  total_fee: number
  total_amount: number
}

export const tradesStats = (params: { account_id?: number; start?: string; end?: string }) =>
  api.get<TradesStats>('/trades/stats', { params }).then(r => r.data)

// ---------- AI 分析 ----------

export interface AnalysisSection {
  role: string
  title: string
  content: string
}

export interface ReportListItem {
  id: number
  ts_code?: string
  stock_name?: string
  as_of_date: string
  title: string
  report_type?: string
  created_at: string
}

export interface ReportStructured {
  score: number
  bullish_points: string[]
  bearish_points: string[]
  key_levels: { support: number[]; resistance: number[] }
  watch_items: { task_type: string; condition: string; expect: string }[]
}

export interface ReportDetail extends ReportListItem {
  ts_code: string
  content: string
  structured: ReportStructured
  merged_content?: string | null
  merged_updated_at?: string | null
  discussion_count?: number
}

export interface DiscussionMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  created_at: string
}

export interface DiscussionResp {
  messages: DiscussionMessage[]
  merged_content: string | null
  merged_updated_at: string | null
}

export interface ReportChainItem {
  report_id: number
  as_of_date: string
  title: string
  prev_report_id: number | null
}

export interface ReportDiff {  a: ReportDetail
  b: ReportDetail
  score_delta: number
  key_levels_a: { support: number[]; resistance: number[] }
  key_levels_b: { support: number[]; resistance: number[] }
  bullish_new: string[]
  bearish_new: string[]
}

export const listReports = (tsCode: string) =>
  api.get<ReportListItem[]>(`/analysis/${tsCode}/reports`).then(r => r.data)
export const listAllReports = () =>
  api.get<ReportListItem[]>('/analysis/all-reports').then(r => r.data)
export const deleteReport = (id: number) =>
  api.delete(`/analysis/reports/${id}`).then(r => r.data)
export const getReport = (id: number) =>
  api.get<ReportDetail>(`/analysis/reports/${id}`).then(r => r.data)
export const getDiscussion = (id: number) =>
  api.get<DiscussionResp>(`/analysis/reports/${id}/discussion`).then(r => r.data)
export const postDiscussion = (id: number, content: string) =>
  api.post<DiscussionResp & { reply: string }>(`/analysis/reports/${id}/discussion`, { content }).then(r => r.data)
export const getReportChain = (tsCode: string) =>
  api.get<ReportChainItem[]>(`/analysis/${tsCode}/chain`).then(r => r.data)
export const diffReports = (a: number, b: number) =>
  api.get<ReportDiff>('/analysis/diff', { params: { report_a: a, report_b: b } }).then(r => r.data)

export function streamAnalysis(tsCode: string, onEvent: SSEHandler): Promise<void> {
  return postSSE(`/api/analysis/${tsCode}`, {}, onEvent)
}
export function streamSynthesis(tsCode: string, onEvent: SSEHandler): Promise<void> {
  return postSSE(`/api/analysis/${tsCode}/synthesis`, {}, onEvent)
}

// ---------- 策略中心 ----------

export interface StrategyListItem {
  id: number
  name: string
  source: string
  status: string
  version_no: number
  parent_id: number | null
  version_note?: string
  description?: string
  created_at: string
}

export interface StrategyDetail extends StrategyListItem {
  code: string
  params: Record<string, unknown>
}

export interface ValidateResult {
  ok: boolean
  error?: string
  backtest?: unknown
}

export interface Binding {
  binding_id: number
  [k: string]: unknown
}

export const listStrategies = () => api.get<StrategyListItem[]>('/strategies').then(r => r.data)
export const createStrategy = (payload: { name: string; code: string; description?: string; params?: Record<string, unknown>; source: string }) =>
  api.post<StrategyDetail>('/strategies', payload).then(r => r.data)
export const getStrategy = (id: number) => api.get<StrategyDetail>(`/strategies/${id}`).then(r => r.data)
export const updateStrategy = (id: number, payload: { name?: string; code?: string; description?: string; params?: Record<string, unknown> }) =>
  api.put<StrategyDetail>(`/strategies/${id}`, payload).then(r => r.data)
export const validateStrategy = (id: number, payload: { code?: string; params?: Record<string, unknown> }) =>
  api.post<ValidateResult>(`/strategies/${id}/validate`, payload).then(r => r.data)
export const bindStrategy = (id: number, payload: { account_id: number; ts_codes: string[]; params?: Record<string, unknown> }) =>
  api.post<Binding>(`/strategies/${id}/bind`, payload).then(r => r.data)
export const unbindStrategy = (id: number, bindingId: number) =>
  api.delete(`/strategies/${id}/bind/${bindingId}`).then(r => r.data)
export const activateStrategy = (id: number) =>
  api.post(`/strategies/${id}/activate`).then(r => r.data)

// ---------- 策略对话 ----------
export interface StrategyDiscussionMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  proposed_code?: string | null
  created_at: string
}

export const getStrategyDiscussion = (id: number) =>
  api.get<{ messages: StrategyDiscussionMessage[] }>(`/strategies/${id}/discussion`).then(r => r.data)
export const postStrategyDiscussion = (id: number, content: string) =>
  api.post<StrategyDiscussionMessage & { validation?: { ok: boolean; error?: string; trial_trades?: number } }>(
    `/strategies/${id}/discussion`, { content }).then(r => r.data)
export const applyDiscussionCode = (id: number, msgId: number) =>
  api.post<{ ok: boolean; new_strategy_id: number; version_no: number; parent_id: number }>(
    `/strategies/${id}/discussion/${msgId}/apply`).then(r => r.data)
export const deactivateStrategy = (id: number) =>
  api.post(`/strategies/${id}/deactivate`).then(r => r.data)

export function streamGenerateStrategy(prompt: string, onEvent: SSEHandler): Promise<void> {
  return postSSE('/api/strategies/generate', { prompt }, onEvent)
}

// ---------- 回测 ----------

export interface BacktestMetrics {
  total_return: number
  annual_return: number
  max_drawdown: number
  sharpe: number
  win_rate: number
  trade_count: number
  profit_factor: number
}

export interface EquityPoint {
  date: string
  equity: number
}

export interface CurveSeries {
  name: string
  color?: string
  data: EquityPoint[]
  initialCash: number
}

export interface CurveMarker {
  date: string
  side: string
}

export interface BacktestResult {
  id: number
  strategy_id: number
  strategy_name?: string
  ts_code?: string
  stock_name?: string
  initial_cash?: number
  start_date?: string
  end_date?: string
  status: string
  error?: string
  metrics?: BacktestMetrics & {
    benchmark_return?: number
    excess_return?: number
    win_days_pct?: number
  }
  equity_curve?: EquityPoint[]
  benchmark_curve?: EquityPoint[]
  trades?: TradeRecord[]
}

export interface BacktestListItem {
  id: number
  strategy_id: number
  strategy_name?: string
  ts_code?: string
  stock_name?: string
  start_date?: string
  end_date?: string
  status: string
  metrics?: BacktestMetrics
  created_at?: string
}

export const runBacktest = (payload: { strategy_id: number; ts_code: string; start_date?: string; end_date?: string; initial_cash?: number; params?: Record<string, unknown> }) =>
  api.post<BacktestResult>('/backtests', payload).then(r => r.data)
export const listBacktests = (strategyId?: number) =>
  api.get<BacktestListItem[]>('/backtests', { params: strategyId ? { strategy_id: strategyId } : {} }).then(r => r.data)
export const getBacktest = (id: number) => api.get<BacktestResult>(`/backtests/${id}`).then(r => r.data)
export const deleteBacktest = (id: number) => api.delete(`/backtests/${id}`).then(r => r.data)

// ---------- 任务监控 ----------

export interface WatchTask {
  id: number
  ts_code: string
  source_report_id: number | null
  task_type: string
  condition_json: unknown
  expect_json: unknown
  status: string
  trigger_date?: string | null
  trigger_detail?: string | null
  expire_date?: string | null
}

export interface WatchTasksResult {
  total: number
  items: WatchTask[]
}

export const listWatchTasks = (params: { status?: string; ts_code?: string; source_report_id?: number; page?: number; page_size?: number }) =>
  api.get<WatchTasksResult>('/watch-tasks', { params }).then(r => r.data)
export const cancelWatchTask = (id: number) =>
  api.put(`/watch-tasks/${id}/cancel`).then(r => r.data)
export const verifyWatchTasks = () => api.post('/watch-tasks/verify').then(r => r.data)

export interface KLineMarker {
  date: string
  type: 'watch_triggered' | 'buy' | 'sell'
  label: string
  detail?: string
  ref_id?: number
}

export const getStockMarkers = (tsCode: string) =>
  api.get<KLineMarker[]>(`/stocks/${tsCode}/markers`).then(r => r.data)

// ---------- 交易审查 ----------

export interface ReviewSuggestion {
  type: 'behavior' | 'risk_control' | 'param_adjust'
  detail: string
  proposed_action?: string
}

export interface ReviewListItem {
  id: number
  scope: string
  period_start?: string | null
  period_end?: string | null
  followup?: string
  created_at: string
}

export interface ReviewDetail extends ReviewListItem {
  account_id: number
  content: string
  suggestions: ReviewSuggestion[]
}

export const listReviews = (accountId?: number) =>
  api.get<ReviewListItem[]>('/reviews', { params: accountId ? { account_id: accountId } : {} }).then(r => r.data)
export const getReview = (id: number) => api.get<ReviewDetail>(`/reviews/${id}`).then(r => r.data)
export const reviewFollowup = (id: number, followup: 'adopted' | 'dismissed') =>
  api.put(`/reviews/${id}/followup`, { followup }).then(r => r.data)

export interface ReviewApplyResult {
  new_strategy_id: number
  old_run_id: number
  new_run_id: number
  version_note: string
}

export const applyReviewSuggestion = (id: number, suggestionIndex: number) =>
  api.post<ReviewApplyResult>(`/reviews/${id}/apply`, { suggestion_index: suggestionIndex }).then(r => r.data)

export function streamReview(payload: { account_id: number; scope: 'manual' | 'strategy' | 'all'; strategy_id?: number; period_start?: string; period_end?: string }, onEvent: SSEHandler): Promise<void> {
  return postSSE('/api/reviews', payload, onEvent)
}

// ---------- 自主决策 ----------

export interface AgentRiskParams {
  max_pos_pct?: number
  max_trades_per_day?: number
  max_drawdown_halt?: number
  halt_days?: number
  loss_streak_limit?: number
  cooldown_days?: number
}

export interface AgentAccount {
  cash: number
  initial_cash: number
  total_value: number
  profit_pct: number
}

export interface AgentPosition {
  ts_code: string
  qty: number
  avg_cost: number
  last_price: number
  market_value: number
  pnl_pct: number
}

export interface AgentRecentDecision {
  id: number
  ts_code: string
  action: string
  status: string
  decision_type: string
  run_time: string
  reason: string
}

export interface AgentPoolItem {
  ts_code: string
  name: string
  patrol_enabled: boolean
  position: AgentPosition | null
  last_decision: { action: string; status: string; run_time: string; reason: string } | null
}

export interface AgentStatus {
  id: number
  account_id: number
  status: 'running' | 'stopped' | string
  stocks: string[]
  stock_pool?: AgentPoolItem[]
  style: 'steady' | 'balanced' | 'aggressive' | string
  patrol_freq: number
  risk_params: AgentRiskParams
  reference_strategies: { ts: number[] } & Record<string, unknown>
  pause_until: string | null
  account: AgentAccount
  positions: AgentPosition[]
  recent_decisions: AgentRecentDecision[]
}

export interface AgentSetupPayload {
  stocks: string[]
  initial_cash?: number
  style?: string
  patrol_freq?: number
  risk_params?: AgentRiskParams
  reference_strategies?: Record<string, number[]>
  account_id?: number  // 方案A：关联已有账户
}

export interface AgentRunResult {
  results: {
    ts_code: string
    decision_id: number
    action: string
    status: string
    qty?: number
    risk_note?: string
  }[]
}

export interface AgentDecisionItem {
  id: number
  ts_code: string
  run_date: string
  run_time: string
  decision_type: 'intraday' | 'daily' | string
  action: 'buy' | 'sell' | 'hold' | string
  status: 'executed' | 'rejected_by_risk' | 'failed' | 'hold' | string
  qty?: number
  price?: number
  risk_note?: string
  reason: string
  thesis?: string
}

export interface AgentDecisionsResult {
  total: number
  items: AgentDecisionItem[]
}

export interface AgentDecisionDetail extends AgentDecisionItem {
  analysis_md: string
  inputs_snapshot: unknown
  invalidation?: string
}

export const getAgentStatus = () => api.get<AgentStatus[]>('/agent/status').then(r => r.data)
export const setupAgent = (payload: AgentSetupPayload) =>
  api.post<AgentStatus>('/agent/setup', payload).then(r => r.data)
export const startAgent = () => api.post<{ ok: boolean; status: string }>('/agent/start').then(r => r.data)
export const stopAgent = () => api.post<{ ok: boolean; status: string }>('/agent/stop').then(r => r.data)
export const runAgent = (payload: { ts_code?: string; mode: 'intraday' | 'daily' }) =>
  api.post<AgentRunResult>('/agent/run', payload).then(r => r.data)
export const forceCloseAgent = () => api.post<{ ok: boolean; msg: string }>('/agent/force-close').then(r => r.data)
export const listAgentDecisions = (params: { ts_code?: string; page?: number; page_size?: number }) =>
  api.get<AgentDecisionsResult>('/agent/decisions', { params }).then(r => r.data)
export const getAgentDecision = (id: number) =>
  api.get<AgentDecisionDetail>(`/agent/decisions/${id}`).then(r => r.data)
export const getAgentEquity = () => api.get<EquityPoint[]>('/agent/equity').then(r => r.data)
export const toggleAgentStock = (tsCode: string) =>
  api.post<{ ok: boolean; ts_code: string; patrol_enabled: boolean }>(`/agent/stock/${tsCode}/toggle`).then(r => r.data)
export const removeAgentStock = (tsCode: string) =>
  api.delete<{ ok: boolean; removed: boolean }>(`/agent/stock/${tsCode}`).then(r => r.data)
