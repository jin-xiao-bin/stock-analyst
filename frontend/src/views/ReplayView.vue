<template>
  <div class="replay">
    <!-- 顶部：账户切换 + 持仓条 + 会话卡片 -->
    <el-card shadow="never">
      <div class="topbar">
        <span class="lbl">切换账户</span>
        <el-select v-model="accountFilter" style="width: 240px" @change="onAccountChange">
          <el-option label="全部账户" :value="0" />
          <el-option v-for="a in accountOptions" :key="a.id"
                     :label="`#${a.id} ${a.name}（${a.count}个回放）`" :value="a.id" />
        </el-select>
        <el-button type="primary" @click="openCreate">新建回放</el-button>
        <el-button :disabled="!sessionId" @click="reloadCurrent">查看交易</el-button>
        <el-button @click="refreshList">刷新</el-button>
        <span v-if="detail" class="session-info">
          {{ detail.session.ts_code }} · 起始 {{ detail.session.start_date }}
          · <el-tag size="small" type="info">账户 #{{ detail.session.account_id }}</el-tag>
        </span>
      </div>

      <!-- 选中账户的持仓条 -->
      <div v-if="accountFilter && posBar" class="pos-bar">
        <span class="lbl">账户 #{{ accountFilter }} 持仓（现金 {{ fmtMoney(posBar.cash) }}）：</span>
        <template v-if="posBar.positions.length">
          <span v-for="p in posBar.positions" :key="p.ts_code" class="pos-chip">
            {{ p.ts_code }} {{ p.qty }}股@{{ p.avg_cost.toFixed(2) }}
            现价{{ p.last_price.toFixed(2) }}
            <b :class="p.pnl_pct >= 0 ? 'up' : 'down'">{{ p.pnl_pct >= 0 ? '+' : '' }}{{ p.pnl_pct }}%</b>
          </span>
        </template>
        <span v-else class="lbl2">空仓</span>
      </div>

      <div class="session-cards">
        <el-empty v-if="!filteredSessions.length" description="该账户暂无回放会话" :image-size="60" />
        <div v-for="s in filteredSessions" :key="s.id"
             class="session-card" :class="{ active: s.id === sessionId }"
             @click="switchSession(s.id)">
          <div class="sc-head">
            <b>{{ s.name || s.ts_code }}</b>
            <el-tag size="small" :type="s.strategy_id ? 'warning' : 'info'">
              {{ s.strategy_id ? '挂策略' : '手动' }}
            </el-tag>
          </div>
          <div class="sc-account">账户 #{{ s.account_id }} {{ s.account_name }}</div>
          <div class="sc-body">
            <span class="sc-value">{{ s.total_value.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}</span>
            <span :class="(s.profit_pct ?? 0) >= 0 ? 'up' : 'down'">
              {{ (s.profit_pct ?? 0) >= 0 ? '+' : '' }}{{ s.profit_pct }}%
            </span>
          </div>
          <div class="sc-sub">{{ s.ts_code }} · 推进至 {{ s.cursor_date }}</div>
        </div>
      </div>
    </el-card>

    <template v-if="detail">
      <!-- 信息条 -->
      <el-card shadow="never" class="toolbar">
        <RealtimeQuoteBar :ts-code="detail.session.ts_code" :interval-ms="10000" />
        <div class="stat-row">
          <div class="stat"><span class="lbl">当前日期</span><b>{{ detail.session.cursor_date }}</b></div>
          <div class="stat"><span class="lbl">现金</span><b>{{ fmtMoney(detail.account.cash) }}</b></div>
          <div class="stat"><span class="lbl">总资产</span><b>{{ fmtMoney(detail.account.total_value) }}</b></div>
          <div class="stat">
            <span class="lbl">持仓盈亏</span>
            <b :class="detail.account.profit >= 0 ? 'up' : 'down'">
              {{ fmtMoney(detail.account.profit) }} ({{ detail.account.profit_pct.toFixed(2) }}%)
            </b>
          </div>
        </div>
      </el-card>

      <div class="main-area">
        <!-- 左侧 K线（仅渲染已推进的历史，推进后自动滚到最右） -->
        <el-card shadow="never" class="chart-card" :body-style="{ padding: '0' }">
          <div class="chart-wrap">
            <div ref="chartRef" class="chart" />
            <div v-if="hoverTradeInfo" class="trade-info" @mouseleave="hoverTradeInfo = ''">
              {{ hoverTradeInfo }}
            </div>
          </div>
        </el-card>

        <!-- 右侧 下单 + 推进控制 -->
        <el-card shadow="never" class="side-panel">
          <h4>下单（按当根收盘价成交）</h4>
          <el-radio-group v-model="orderSide">
            <el-radio-button value="buy">买入</el-radio-button>
            <el-radio-button value="sell">卖出</el-radio-button>
          </el-radio-group>
          <el-input-number
            v-model="orderQty"
            :min="100"
            :step="100"
            :step-strictly="true"
            style="width: 100%; margin-top: 10px"
            placeholder="股数(100整数倍)"
          />
          <el-button type="primary" style="width: 100%; margin-top: 10px" :loading="ordering" @click="submitOrder">
            下单
          </el-button>

          <el-divider />
          <h4>推进控制</h4>
          <div class="advance-row">
            <el-button :loading="advancing" @click="nextDay(1)">下一天</el-button>
          </div>
          <div class="advance-row">
            <el-input-number v-model="ffDays" :min="1" :max="250" size="small" style="width: 110px" />
            <el-button :loading="advancing" size="small" @click="nextDay(ffDays)">快进N天</el-button>
          </div>
          <div class="advance-row">
            <el-date-picker
              v-model="gotoDate"
              type="date"
              size="small"
              value-format="YYYY-MM-DD"
              placeholder="快进到日期"
              style="width: 150px"
            />
            <el-button size="small" @click="goto">跳转</el-button>
          </div>
          <div class="advance-row">
            <span>自动播放(1.5s/天)</span>
            <el-switch v-model="autoPlay" />
          </div>

          <el-divider />
          <h4>策略挂载</h4>
          <div v-if="detail.session.strategy_id" class="bound-strategy">
            <el-tag type="warning" size="small">已挂载</el-tag>
            {{ detail.session.strategy_name }}（#{{ detail.session.strategy_id }}）
            <el-button link type="danger" size="small" @click="unbindStrategy">卸载</el-button>
            <div class="hint2">推进日期时策略自动按当日收盘价下单（B/S 标记同手动单）</div>
          </div>
          <template v-else>
            <el-select v-model="strategyPick" placeholder="选择策略" size="small" style="width: 100%">
              <el-option v-for="s in strategies" :key="s.id" :label="`#${s.id} ${s.name}`" :value="s.id" />
            </el-select>
            <el-button size="small" type="primary" plain style="width: 100%; margin-top: 8px"
                       :disabled="!strategyPick" @click="bindStrategy">
              挂载（从当前日期起生效）
            </el-button>
          </template>

          <el-divider />
          <h4>持仓</h4>
          <el-table v-if="detail.positions.length" :data="detail.positions" size="small">
            <el-table-column prop="ts_code" label="代码" width="100" />
            <el-table-column prop="qty" label="数量" width="70" />
            <el-table-column label="盈亏" >
              <template #default="{ row }">
                <span :class="row.profit >= 0 ? 'up' : 'down'">{{ fmtMoney(row.profit) }}</span>
              </template>
            </el-table-column>
          </el-table>
          <div v-else class="empty">暂无持仓</div>
        </el-card>
      </div>

      <!-- summary 统计卡片 -->
      <el-row v-if="summary" :gutter="12" class="summary-row">
        <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">总盈亏</div><b :class="summary.total_profit >= 0 ? 'up' : 'down'">{{ fmtMoney(summary.total_profit) }}</b></el-card></el-col>
        <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">收益率</div><b>{{ summary.profit_pct.toFixed(2) }}%</b></el-card></el-col>
        <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">胜率</div><b>{{ (summary.win_rate * 100).toFixed(1) }}%</b></el-card></el-col>
        <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">最大回撤</div><b class="down">{{ (summary.max_drawdown * 100).toFixed(2) }}%</b></el-card></el-col>
        <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">买入次数</div><b>{{ summary.buy_count }}</b></el-card></el-col>
        <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">卖出次数</div><b>{{ summary.sell_count }}</b></el-card></el-col>
      </el-row>

      <!-- 交易明细 -->
      <el-card shadow="never">
        <template #header>交易明细（K线上 B/S 标记）</template>
        <el-table :data="detail.trades" size="small" max-height="320">
          <el-table-column prop="trade_date" label="日期" width="110" />
          <el-table-column prop="side" label="方向" width="70">
            <template #default="{ row }">
              <el-tag :type="row.side === 'buy' ? 'danger' : 'success'" size="small">{{ row.side === 'buy' ? '买' : '卖' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="price" label="价格" width="100" />
          <el-table-column prop="qty" label="数量" width="90" />
          <el-table-column prop="amount" label="金额" width="120" />
          <el-table-column prop="fee" label="费用" width="90" />
        </el-table>
      </el-card>
    </template>

    <el-empty v-else-if="!loading" description="暂无回放会话，点击「新建回放」开始" />

    <!-- 新建回放对话框 -->
    <el-dialog v-model="createDlg" title="新建回放会话" width="480px">
      <el-form label-width="90px">
        <el-form-item label="股票">
          <el-select
            v-model="createForm.ts_code"
            filterable
            remote
            clearable
            placeholder="搜索代码/名称"
            :remote-method="doSearch"
            :loading="searching"
            style="width: 100%"
          >
            <el-option v-for="s in options" :key="s.ts_code" :label="`${s.name} (${s.ts_code})`" :value="s.ts_code" />
          </el-select>
        </el-form-item>
        <el-form-item label="起始日期">
          <el-date-picker v-model="createForm.start_date" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
        </el-form-item>
        <el-form-item label="账户">
          <el-radio-group v-model="createForm.accountMode">
            <el-radio-button value="new">新建专属账户</el-radio-button>
            <el-radio-button value="link">关联已有账户</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="createForm.accountMode === 'new'" label="初始资金">
          <el-input-number v-model="createForm.initial_cash" :min="10000" :step="100000" style="width: 100%" />
        </el-form-item>
        <el-form-item v-else label="选择账户">
          <el-select v-model="createForm.account_id" style="width: 100%" placeholder="选择要关联的账户">
            <el-option v-for="a in allAccounts" :key="a.id"
                       :label="`#${a.id} ${a.name}（${a.mode}，总资产 ${Math.round(a.total_value)}）`" :value="a.id" />
          </el-select>
          <div class="form-hint">关联账户的现金/持仓与本回放共用，交易互相可见</div>
        </el-form-item>
        <el-form-item label="会话名称">
          <el-input v-model="createForm.name" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDlg = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { init, dispose, type Chart } from 'klinecharts'
import RealtimeQuoteBar from '../components/RealtimeQuoteBar.vue'
import {
  bindReplayStrategy, createReplay, getAccountPositions, getReplay, getReplaySummary,
  listAccounts, listReplays,
  listStrategies, replayGoto, replayNext, replayOrder, searchStocks, unbindReplayStrategy,
  type Account, type AccountPositions, type Bar, type ReplayDetail, type ReplayListItem,
  type ReplaySummary, type StockInfo, type StrategyListItem,
} from '../api'

const sessions = ref<ReplayListItem[]>([])
const sessionId = ref<number | null>(null)
const detail = ref<ReplayDetail | null>(null)
const summary = ref<ReplaySummary | null>(null)
const loading = ref(false)
const ordering = ref(false)
const advancing = ref(false)

// 下单
const orderSide = ref<'buy' | 'sell'>('buy')
const orderQty = ref(100)

// 推进
const ffDays = ref(5)
const gotoDate = ref('')
const autoPlay = ref(false)
let playTimer: ReturnType<typeof setInterval> | null = null

// 新建
const createDlg = ref(false)
const creating = ref(false)
const searching = ref(false)
const options = ref<StockInfo[]>([])
const createForm = ref({ ts_code: '', start_date: '', initial_cash: 1000000, name: '',
                         accountMode: 'new' as 'new' | 'link', account_id: null as number | null })
const allAccounts = ref<Account[]>([])

// 账户筛选与持仓条
const accountFilter = ref(0)  // 0=全部
const posBar = ref<AccountPositions | null>(null)
const switchAccounts = ref<Account[]>([])

const accountOptions = computed(() => {
  const counts = new Map<number, number>()
  for (const s of sessions.value) {
    counts.set(s.account_id!, (counts.get(s.account_id!) ?? 0) + 1)
  }
  const names = new Map(switchAccounts.value.map(a => [a.id, a]))
  // 全部账户（含未建回放的），会话列表里出现但账户接口缺失的也补上
  const ids = new Set<number>([...names.keys(), ...counts.keys()])
  return [...ids].sort((a, b) => b - a).map(id => ({
    id,
    name: names.get(id)?.name ?? `#${id}`,
    count: counts.get(id) ?? 0,
  }))
})

const filteredSessions = computed(() =>
  accountFilter.value === 0 ? sessions.value
    : sessions.value.filter(s => s.account_id === accountFilter.value))

const loadPosBar = async () => {
  if (!accountFilter.value) { posBar.value = null; return }
  try {
    posBar.value = await getAccountPositions(accountFilter.value)
  } catch {
    posBar.value = null
  }
}

const onAccountChange = async () => {
  await loadPosBar()
  // 联动切换会话：跳到该账户最近的回放会话（K线/交易明细随之刷新）；无会话则清空
  if (accountFilter.value === 0) return
  const latest = filteredSessions.value[0]
  if (latest) {
    if (latest.id !== sessionId.value) await switchSession(latest.id)
  } else {
    sessionId.value = null
    detail.value = null
    summary.value = null
  }
}

const openCreate = async () => {
  createForm.value = { ts_code: '', start_date: '', initial_cash: 1000000, name: '',
                       accountMode: 'new', account_id: null }
  try { allAccounts.value = await listAccounts() } catch { allAccounts.value = [] }
  createDlg.value = true
}

// K线
const chartRef = ref<HTMLDivElement>()
let chart: Chart | null = null

const fmtMoney = (n: number) => n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })

const cursorIndex = computed(() => {
  if (!detail.value || detail.value.bars.length === 0) return -1
  const bars = detail.value.bars
  const cursor = detail.value.session.cursor_date
  let idx = -1
  for (let i = 0; i < bars.length; i++) {
    if (bars[i].date <= cursor) idx = i
    else break
  }
  return idx
})

// 十字光标信息条：悬停到含交易的蜡烛时显示该日交易详情
const hoverTradeInfo = ref('')

/** 交易日落在假期/停牌（无对应K线）时，吸附到 ≤该日的最近一根K线 */
const snapToDate = (tradeDate: string, dates: string[]): string | null => {
  if (!dates.length) return null
  let best: string | null = null
  for (const d of dates) {
    if (d <= tradeDate) best = d
    else break
  }
  return best ?? dates[0]  // 早于首根K线的挂首根
}

const onCrosshair = (data?: { dataIndex?: number }) => {
  const d = detail.value
  if (!d || data?.dataIndex == null) { hoverTradeInfo.value = ''; return }
  const idx = cursorIndex.value
  const visible = idx >= 0 ? d.bars.slice(0, idx + 1) : []
  const bar = visible[data.dataIndex]
  if (!bar) { hoverTradeInfo.value = ''; return }
  const dates = visible.map(b => b.date)
  // 交易按吸附后日期匹配（假期交易吸附到前一根K线）
  const dayTrades = d.trades.filter(t => snapToDate(t.trade_date, dates) === bar.date)
  hoverTradeInfo.value = dayTrades.length
    ? dayTrades.map(t =>
        `${t.trade_date}${t.trade_date !== bar.date ? `（无K线，标记于${bar.date}）` : ''}` +
        ` ｜ ${t.side === 'buy' ? '🔴买入' : '🟢卖出'} ${t.qty}股 @${t.price}` +
        `（金额${t.amount} 费用${t.fee} 来源${t.source === 'strategy' ? '策略' : t.source === 'agent' ? 'Agent' : '手动'}${t.note ? ' ' + t.note : ''}）`,
      ).join('；')
    : ''
}

let chartEl: HTMLDivElement | null = null  // chart 实例绑定的容器（检测DOM重建）

const ensureChart = () => {
  // 容器被 v-if 销毁重建后，旧 chart 实例挂在孤儿DOM上 → 必须销毁重建
  if (chart && chartEl && chartRef.value && chartEl !== chartRef.value) {
    try { dispose(chartEl) } catch { /* 忽略 */ }
    chart = null
    chartEl = null
  }
  if (chart || !chartRef.value) return chart
  const c = init(chartRef.value)
  if (c) {
    chart = c
    chartEl = chartRef.value
    c.createIndicator('MA', false, { id: 'candle_pane' })
    c.createIndicator('VOL')
    c.subscribeAction('onCrosshairChange' as never, onCrosshair)
  }
  return chart
}

const renderChart = () => {
  const d = detail.value
  // 会话异步加载后容器才出现，这里懒初始化
  const c = ensureChart()
  if (!d || !c) return
  const idx = cursorIndex.value
  const visible = idx >= 0 ? d.bars.slice(0, idx + 1) : []
  c.removeOverlay()
  c.applyNewData(
    visible.map(b => ({
      timestamp: new Date(b.date + 'T00:00:00').getTime(),
      open: Number(b.open), high: Number(b.high), low: Number(b.low), close: Number(b.close),
      volume: Number(b.volume ?? 0),
    })),
  )
  // 滚动到最右（最新一根）
  if (visible.length > 0) {
    try { c.scrollToDataIndex(visible.length - 1) } catch { /* 忽略滚动异常 */ }
  }
  // 交易点 B/S 标记（悬停/点击显示交易详情；假期/无K线日吸附到前一根）
  const visibleDates = visible.map(b => b.date)
  for (const t of d.trades) {
    const markerDate = snapToDate(t.trade_date, visibleDates)
    if (!markerDate) continue
    const detailMsg =
      `${t.trade_date}${t.trade_date !== markerDate ? `（当日无K线，标记于${markerDate}）` : ''}` +
      ` ${t.side === 'buy' ? '买入' : '卖出'} ${t.qty} 股 @${t.price}` +
      `｜金额 ${t.amount?.toLocaleString?.() ?? t.amount} 费用 ${t.fee}` +
      `｜来源 ${t.source === 'strategy' ? `策略#${t.strategy_id ?? ''}` : t.source === 'agent' ? 'Agent' : '手动'}` +
      (t.note ? `｜${t.note}` : '')
    c.createOverlay({
      name: 'simpleAnnotation',
      points: [{ timestamp: new Date(markerDate + 'T00:00:00').getTime(), value: Number(t.price) }],
      extendData: t.side === 'buy' ? 'B' : 'S',
      onMouseEnter: () => {
        ElMessage({ message: detailMsg, type: t.side === 'buy' ? 'warning' : 'success', duration: 2500, grouping: true })
        return false
      },
      onClick: () => {
        ElMessage({ message: detailMsg, type: t.side === 'buy' ? 'warning' : 'success', duration: 4000, grouping: true })
        return false
      },
      styles: t.side === 'buy'
        ? { annotation: { symbol: { style: 'stroke', color: '#f56c6c' } } }
        : { annotation: { symbol: { style: 'stroke', color: '#67c23a' } } },
    })
  }
}

const applyDetail = (d: ReplayDetail) => {
  detail.value = d
  // detail 赋值后容器（v-if）要等下一次 DOM 更新才存在，先 nextTick 再渲染图表
  void nextTick(() => renderChart())
}

const loadSession = async (id: number) => {
  loading.value = true
  try {
    applyDetail(await getReplay(id))
    summary.value = await getReplaySummary(id)
  } catch (e) {
    ElMessage.error(`加载会话失败: ${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

const switchSession = (id: number) => {
  if (id === sessionId.value) return
  sessionId.value = id
  detail.value = null
  summary.value = null
  void loadSession(id)
}

const reloadCurrent = () => {
  if (sessionId.value) void loadSession(sessionId.value)
}

const refreshList = async (selectFirst = false) => {
  try {
    sessions.value = await listReplays()
    // 同步刷新账户选项与持仓条（其他页面可能新建/删除了账户）
    try { switchAccounts.value = await listAccounts() } catch { /* ignore */ }
    if (accountFilter.value) await loadPosBar()
    if (selectFirst && sessions.value.length > 0) {
      sessionId.value = sessions.value[0].id
      await loadSession(sessionId.value)
    }
  } catch (e) {
    ElMessage.error(`加载会话列表失败: ${(e as Error).message}`)
  }
}

const nextDay = async (days: number) => {
  if (!sessionId.value) return
  advancing.value = true
  try {
    applyDetail(await replayNext(sessionId.value, days))
    summary.value = await getReplaySummary(sessionId.value)
  } catch (e) {
    ElMessage.error(`推进失败: ${(e as Error).message}`)
    autoPlay.value = false
  } finally {
    advancing.value = false
  }
}

const goto = async () => {
  if (!sessionId.value || !gotoDate.value) return
  advancing.value = true
  try {
    applyDetail(await replayGoto(sessionId.value, gotoDate.value))
    summary.value = await getReplaySummary(sessionId.value)
  } catch (e) {
    ElMessage.error(`跳转失败: ${(e as Error).message}`)
  } finally {
    advancing.value = false
  }
}

const submitOrder = async () => {
  if (!sessionId.value) return
  ordering.value = true
  try {
    await replayOrder(sessionId.value, orderSide.value, orderQty.value)
    ElMessage.success('下单成功')
    applyDetail(await getReplay(sessionId.value))
    summary.value = await getReplaySummary(sessionId.value)
  } catch (e) {
    ElMessage.error(`下单失败: ${(e as Error).message}`)
  } finally {
    ordering.value = false
  }
}

const stopPlay = () => {
  if (playTimer) { clearInterval(playTimer); playTimer = null }
}

watch(autoPlay, v => {
  stopPlay()
  if (v) {
    playTimer = setInterval(() => {
      if (!advancing.value && sessionId.value) void nextDay(1)
    }, 1500)
  }
})

watch(detail, () => renderChart())

const doSearch = async (q: string) => {
  if (!q) { options.value = []; return }
  searching.value = true
  try {
    options.value = await searchStocks(q)
  } finally {
    searching.value = false
  }
}

const submitCreate = async () => {
  const f = createForm.value
  if (!f.ts_code || !f.start_date) { ElMessage.warning('请选择股票和起始日期'); return }
  if (f.accountMode === 'link' && !f.account_id) { ElMessage.warning('请选择要关联的账户'); return }
  creating.value = true
  try {
    const s = await createReplay({
      ts_code: f.ts_code,
      start_date: f.start_date,
      initial_cash: f.accountMode === 'new' ? f.initial_cash : undefined,
      name: f.name || undefined,
      account_id: f.accountMode === 'link' ? (f.account_id ?? undefined) : undefined,
    })
    createDlg.value = false
    ElMessage.success('回放会话已创建')
    await refreshList()
    sessionId.value = s.id
    // 新会话属于某账户时，筛选器自动切到该账户
    if (s.account_id) { accountFilter.value = s.account_id; await loadPosBar() }
    await loadSession(s.id)
  } catch (e) {
    ElMessage.error(`创建失败: ${(e as Error).message}`)
  } finally {
    creating.value = false
  }
}

// 策略挂载
const strategies = ref<StrategyListItem[]>([])
const strategyPick = ref<number | null>(null)

const bindStrategy = async () => {
  if (!sessionId.value || !strategyPick.value) return
  try {
    await bindReplayStrategy(sessionId.value, strategyPick.value)
    ElMessage.success('策略已挂载，从当前日期起对后续推进生效')
    await loadSession(sessionId.value)
  } catch (e) {
    ElMessage.error(`挂载失败: ${(e as Error).message}`)
  }
}

const unbindStrategy = async () => {
  if (!sessionId.value) return
  try {
    await unbindReplayStrategy(sessionId.value)
    ElMessage.success('已卸载策略')
    await loadSession(sessionId.value)
  } catch (e) {
    ElMessage.error(`卸载失败: ${(e as Error).message}`)
  }
}

onMounted(async () => {
  // 图表懒初始化在 renderChart/ensureChart 中完成（容器随 detail 渲染）
  try { strategies.value = await listStrategies() } catch { /* ignore */ }
  try { switchAccounts.value = await listAccounts() } catch { /* ignore */ }
  await refreshList(true)
  // 默认选中最近活跃账户并显示其持仓
  if (sessions.value.length) {
    accountFilter.value = sessions.value[0].account_id ?? 0
    await loadPosBar()
  }
})

onBeforeUnmount(() => {
  stopPlay()
  if (chartRef.value) dispose(chartRef.value)
})
</script>

<style scoped>
.replay { display: flex; flex-direction: column; gap: 12px; }
.toolbar { display: flex; align-items: center; gap: 12px; }
.session-info { margin-left: auto; color: #909399; }
.topbar { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.session-cards { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 4px; }
.session-card {
  min-width: 210px; cursor: pointer; border: 1px solid #e4e7ed; border-radius: 8px;
  padding: 10px 14px; background: #fff; flex-shrink: 0;
}
.session-card:hover { border-color: #c0c4cc; }
.session-card.active { border-color: #409eff; box-shadow: 0 0 0 1px #409eff inset; }
.sc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
.sc-account { color: #909399; font-size: 12px; margin-bottom: 6px; }
.sc-body { display: flex; justify-content: space-between; align-items: baseline; }
.sc-value { font-size: 18px; font-weight: 700; }
.sc-sub { color: #c0c4cc; font-size: 12px; margin-top: 4px; }
.pos-bar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  padding: 8px 12px; margin-bottom: 10px; background: #f5f7fa; border-radius: 6px; font-size: 13px; }
.pos-chip { background: #fff; border: 1px solid #e4e7ed; border-radius: 4px; padding: 2px 8px; }
.form-hint { color: #909399; font-size: 12px; margin-top: 2px; }
.lbl2 { color: #c0c4cc; }
.stat-row { display: flex; gap: 32px; }
.stat { display: flex; flex-direction: column; }
.stat .lbl { color: #909399; font-size: 12px; }
.main-area { display: flex; gap: 12px; align-items: stretch; }
.chart-card { flex: 1; min-width: 0; }
.chart-wrap { position: relative; }
.trade-info {
  position: absolute; top: 6px; left: 8px; right: 8px; z-index: 5;
  background: rgba(255, 255, 255, 0.94); border: 1px solid #e6a23c; border-radius: 4px;
  padding: 4px 10px; font-size: 12px; color: #606266;
  pointer-events: none; word-break: break-all;
}
.chart { width: 100%; height: 520px; }
.side-panel { width: 300px; flex-shrink: 0; }
.side-panel h4 { margin: 4px 0 10px; }
.advance-row { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; justify-content: space-between; }
.summary-row { margin-top: 2px; }
.mini { text-align: center; }
.mini .mini-lbl { color: #909399; font-size: 12px; margin-bottom: 4px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
.empty { color: #c0c4cc; font-size: 13px; text-align: center; padding: 12px 0; }
.bound-strategy { font-size: 13px; line-height: 1.8; }
.hint2 { color: #c0c4cc; font-size: 12px; margin-top: 4px; }
</style>
