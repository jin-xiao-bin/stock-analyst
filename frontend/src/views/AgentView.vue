<template>
  <div class="agent">
    <!-- ===================== 个股详情视图 ===================== -->
    <template v-if="detailTs">
      <!-- 控制台（全局） -->
      <el-card v-if="status" shadow="never">
        <template #header>
          <div class="detail-head">
            <el-button size="small" @click="backToList">← 返回列表</el-button>
            <span class="detail-code">控制台</span>
            <div style="margin-left: auto; display: flex; gap: 8px; align-items: center">
              <el-tag v-if="pauseActive" type="warning" size="small">熔断暂停至 {{ status?.pause_until }}</el-tag>
              <el-tag :type="status?.status === 'running' ? 'success' : 'info'" size="small">
                {{ status?.status === 'running' ? '运行中' : '已停止' }}
              </el-tag>
              <el-button size="small" :type="status.status === 'running' ? 'danger' : 'success'"
                         @click="status.status === 'running' ? doStop() : doStart()">
                {{ status.status === 'running' ? '停止' : '启动' }}
              </el-button>
              <el-button size="small" type="danger" plain @click="doForceClose">强制清仓</el-button>
              <el-button size="small" @click="openConfig">配置</el-button>
            </div>
          </div>
        </template>
        <div class="ctrl-info">
          账户 #{{ status?.account_id }} · 总资产
          <b>{{ fmt(status?.account.total_value ?? 0) }}</b>
          <span :class="(status?.account.profit_pct ?? 0) >= 0 ? 'up' : 'down'">
            {{ (status?.account.profit_pct ?? 0) >= 0 ? '+' : '' }}{{ (status?.account.profit_pct ?? 0).toFixed(2) }}%
          </span>
          · 现金 {{ fmt(status?.account.cash ?? 0) }} · 风格 {{ styleLabel }} · 巡逻 {{ status?.patrol_freq }}分钟
        </div>
      </el-card>

      <el-card shadow="never">
        <template #header>
          <div class="detail-head">
            <el-button size="small" @click="backToList">← 返回列表</el-button>
            <b>{{ detailStock?.name ?? detailTs }}</b>
            <span class="detail-code">{{ detailTs }}</span>
            <el-tag v-if="detailStock" size="small" :type="detailStock.patrol_enabled ? 'success' : 'info'">
              {{ detailStock.patrol_enabled ? '巡盘中' : '已停止' }}
            </el-tag>
            <div class="detail-actions">
              <span class="switch-label">巡盘</span>
              <el-switch :model-value="detailStock?.patrol_enabled ?? false" @change="doToggle(detailTs)" />
              <el-button size="small" type="primary" plain :loading="runStockLoading === 'intraday'"
                         @click="runStockDecision('intraday')">盘中决策</el-button>
              <el-button size="small" type="warning" plain :loading="runStockLoading === 'daily'"
                         @click="runStockDecision('daily')">收盘深度</el-button>
              <el-button size="small" type="danger" plain @click="doRemove(detailTs)">移除出池</el-button>
            </div>
          </div>
        </template>

        <RealtimeQuoteBar :ts-code="detailTs" />

        <!-- 持仓卡 -->
        <div class="pos-card" v-if="detailStock?.position">
          <div class="pos-item"><span>数量</span><b>{{ detailStock.position.qty }} 股</b></div>
          <div class="pos-item"><span>成本</span><b>{{ detailStock.position.avg_cost.toFixed(2) }}</b></div>
          <div class="pos-item"><span>现价</span><b>{{ detailStock.position.last_price.toFixed(2) }}</b></div>
          <div class="pos-item"><span>市值</span><b>{{ fmt(detailStock.position.market_value) }}</b></div>
          <div class="pos-item"><span>浮盈亏</span>
            <b :class="detailStock.position.pnl_pct >= 0 ? 'up' : 'down'">
              {{ detailStock.position.pnl_pct >= 0 ? '+' : '' }}{{ detailStock.position.pnl_pct.toFixed(2) }}%
            </b>
          </div>
        </div>
        <div v-else class="no-pos-tip">当前无持仓</div>
      </el-card>

      <!-- 账户曲线（全账户维度，标注该股决策点） -->
      <el-card shadow="never">
        <template #header><span>账户曲线（标注 {{ detailTs }} 决策点）</span></template>
        <el-empty v-if="!equity.length" description="暂无净值数据" :image-size="60" />
        <CurveChart v-else :series="[{ name: 'agent账户', data: equity, initialCash: initialCash }]"
                    :markers="detailMarkers" :trades="detailTrades" />
      </el-card>

      <!-- 该股决策流水 -->
      <el-card shadow="never">
        <template #header><span>{{ detailTs }} 决策流水</span></template>
        <el-table :data="detDecisions" size="small" v-loading="detLoading"
                  @row-click="(row: AgentDecisionItem) => openDetail(row.id)" style="cursor: pointer">
          <el-table-column label="时间" width="150">
            <template #default="{ row }">{{ row.run_date }} {{ row.run_time }}</template>
          </el-table-column>
          <el-table-column prop="ts_code" label="股票" width="110" />
          <el-table-column label="类型" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.decision_type === 'daily' ? 'warning' : 'primary'">
                {{ row.decision_type }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="70">
            <template #default="{ row }">
              <el-tag size="small" :type="actionTagType(row.action)">{{ actionLabel(row.action) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="数量@价格" width="120">
            <template #default="{ row }">
              {{ row.qty && row.price ? `${row.qty} @ ${row.price}` : '—' }}
            </template>
          </el-table-column>
          <el-table-column label="状态" width="130">
            <template #default="{ row }">
              <el-tooltip :disabled="!row.risk_note" :content="row.risk_note" placement="top">
                <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column prop="reason" label="理由摘要" min-width="200" show-overflow-tooltip />
          <el-table-column label="操作" width="70">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openDetail(row.id)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination v-model:current-page="detPage" :page-size="pageSize" :total="detTotal"
                         layout="total, prev, pager, next" @current-change="loadDetDecisions" />
        </div>
      </el-card>
    </template>

    <!-- ===================== 主视图（股票池列表） ===================== -->
    <template v-else>
      <el-card shadow="never" class="toolbar">
        <div class="toolbar-line">
          <span class="toolbar-title">自主决策 · 巡盘股票池</span>
          <span class="status-line">
            <el-tag :type="status?.status === 'running' ? 'success' : 'info'" size="small">
              {{ status?.status === 'running' ? '运行中' : '已停止' }}
            </el-tag>
            <el-tag v-if="pauseActive" type="warning" size="small">熔断暂停至 {{ status?.pause_until }}</el-tag>
            <span class="hint">关联账户 #{{ status?.account_id }} · 总资产 {{ fmt(status?.account.total_value ?? 0) }}（{{ (status?.account.profit_pct ?? 0) >= 0 ? '+' : '' }}{{ (status?.account.profit_pct ?? 0).toFixed(2) }}%）</span>
          </span>
          <div style="margin-left: auto; display: flex; gap: 8px; align-items: center">
            <el-input v-model="filterCode" placeholder="股票代码筛选，如 601689" clearable style="width: 180px" />
            <el-select v-model="filterState" placeholder="启用状态" clearable style="width: 120px">
              <el-option label="巡盘中" value="on" />
              <el-option label="已停止" value="off" />
            </el-select>
            <el-button type="primary" @click="openAdd">新增</el-button>
            <el-button @click="refresh">刷新</el-button>
          </div>
        </div>
      </el-card>

      <!-- 巡盘股票池列表 -->
      <el-card shadow="never">
        <template #header><span>巡盘股票池（点击行进入详情：报价 / 持仓 / 账户曲线 / 决策流水 / 巡盘开关 / 配置）</span></template>
        <el-table :data="filteredPool" size="small" v-loading="!status" empty-text="池内暂无股票，点「新增」添加"
                  @row-click="(row: AgentPoolItem) => enterDetail(row.ts_code)" style="cursor: pointer">
          <el-table-column label="股票" min-width="160">
            <template #default="{ row }">
              <b>{{ row.name }}</b>
              <span class="pool-code">{{ row.ts_code }}</span>
            </template>
          </el-table-column>
          <el-table-column label="巡盘状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="row.patrol_enabled ? 'success' : 'info'">
                {{ row.patrol_enabled ? '巡盘中' : '已停止' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="持仓" width="170">
            <template #default="{ row }">
              <template v-if="row.position">
                <span>{{ row.position.qty }} @ {{ row.position.avg_cost.toFixed(2) }}</span>
                <span :class="row.position.pnl_pct >= 0 ? 'up' : 'down'" style="margin-left: 8px">
                  {{ row.position.pnl_pct >= 0 ? '+' : '' }}{{ row.position.pnl_pct.toFixed(2) }}%
                </span>
              </template>
              <span v-else class="no-pos">—</span>
            </template>
          </el-table-column>
          <el-table-column label="最近决策" min-width="180">
            <template #default="{ row }">
              <el-tooltip v-if="row.last_decision" placement="top" :content="row.last_decision.reason">
                <span>
                  <el-tag size="small" :type="actionTagType(row.last_decision.action)">
                    {{ actionLabel(row.last_decision.action) }}
                  </el-tag>
                  <span class="ld-time">{{ row.last_decision.run_time }}</span>
                </span>
              </el-tooltip>
              <span v-else class="no-pos">—</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="enterDetail(row.ts_code)">详情</el-button>
              <el-button link type="danger" size="small" @click.stop="doRemove(row.ts_code)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </template>

    <!-- 2. 配置抽屉（edit=编辑配置 / add=批量新增股票） -->
    <el-drawer v-model="configVisible" :title="configMode === 'add' ? '新增巡盘股票（批量）' : '自主决策配置'" size="520px">
      <el-form label-width="90px">
        <el-form-item label="股票池">
          <el-input v-model="configStocks" placeholder="逗号分隔，如 000001.SZ,600519.SH" />
          <div class="tags">
            <el-tag v-for="s in stockList" :key="s" size="small" style="margin: 2px">{{ s }}</el-tag>
          </div>
        </el-form-item>
        <el-form-item label="初始资金" v-if="configMode === 'add' && !status">
          <el-input-number v-model="config.initial_cash" :min="1000" :step="10000"
                           style="width: 180px" />
        </el-form-item>
        <el-form-item label="关联账户" v-if="configMode === 'edit'">
          <el-select v-model="config.account_id" style="width: 100%">
            <el-option v-for="a in allAccounts" :key="a.id"
                       :label="`#${a.id} ${a.name}（${a.mode}）`" :value="a.id" />
          </el-select>
          <div class="hint">agent 的所有自主决策将在该账户中执行；切换后历史决策流水保留</div>
        </el-form-item>
        <el-form-item label="风格">
          <el-radio-group v-model="config.style">
            <el-radio-button value="steady">稳健</el-radio-button>
            <el-radio-button value="balanced">均衡</el-radio-button>
            <el-radio-button value="aggressive">激进</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="巡逻频率">
          <el-input-number v-model="config.patrol_freq" :min="1" /> 分钟
        </el-form-item>
        <el-form-item label="风控参数">
          <div class="risk-grid">
            <div class="risk-item">
              <span>单票仓位上限%</span>
              <el-input-number v-model="config.risk_params.max_pos_pct" :min="1" :max="100" size="small" />
            </div>
            <div class="risk-item">
              <span>每日交易上限</span>
              <el-input-number v-model="config.risk_params.max_trades_per_day" :min="1" size="small" />
            </div>
            <div class="risk-item">
              <span>回撤熔断%</span>
              <el-input-number v-model="config.risk_params.max_drawdown_halt" :min="1" :max="100" size="small" />
            </div>
            <div class="risk-item">
              <span>熔断天数</span>
              <el-input-number v-model="config.risk_params.halt_days" :min="1" size="small" />
            </div>
            <div class="risk-item">
              <span>连亏次数上限</span>
              <el-input-number v-model="config.risk_params.loss_streak_limit" :min="1" size="small" />
            </div>
            <div class="risk-item">
              <span>冷却天数</span>
              <el-input-number v-model="config.risk_params.cooldown_days" :min="0" size="small" />
            </div>
          </div>
        </el-form-item>
        <el-form-item label="参考策略">
          <el-table :data="refRows" size="small" empty-text="先填写股票池">
            <el-table-column label="股票" width="120">
              <template #default="{ row }">{{ row.ts }}</template>
            </el-table-column>
            <el-table-column label="策略ID（逗号分隔）">
              <template #default="{ row }">
                <el-input v-model="row.ids" size="small" placeholder="如 1,3" />
              </template>
            </el-table-column>
          </el-table>
        </el-form-item>
        <el-form-item label="飞书通知">
          <div class="hint" style="margin-bottom: 4px">
            在飞书群添加「自定义机器人」后，把 Webhook 地址填入 backend/.env 的
            FEISHU_WEBHOOK_URL 并重启后端。重要事件（买卖/熔断/清仓/任务触发）会推送到群。
          </div>
          <el-button size="small" @click="testNotify">发送测试通知</el-button>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" @click="saveConfig">保存</el-button>
        </el-form-item>
      </el-form>
    </el-drawer>

    <!-- 决策详情抽屉 -->
    <el-drawer v-model="detailVisible" title="决策详情" size="640px">
      <div v-if="detail" class="detail">
        <div class="d-head">
          <b>{{ detail.ts_code }}</b>
          <el-tag size="small" :type="actionTagType(detail.action)">{{ actionLabel(detail.action) }}</el-tag>
          <el-tag size="small" :type="statusTagType(detail.status)">{{ statusLabel(detail.status) }}</el-tag>
          <span class="d-time">{{ detail.run_date }} {{ detail.run_time }}</span>
        </div>
        <div v-if="detail.thesis" class="d-sec"><h4>论证（Thesis）</h4><p>{{ detail.thesis }}</p></div>
        <div v-if="detail.invalidation" class="d-sec"><h4>失效条件</h4><p>{{ detail.invalidation }}</p></div>
        <div class="d-sec"><h4>理由</h4><p>{{ detail.reason }}</p></div>
        <div v-if="detail.risk_note" class="d-sec"><h4>风控备注</h4><p>{{ detail.risk_note }}</p></div>
        <div class="d-sec"><h4>完整分析</h4><div class="md" v-html="detailHtml"></div></div>
        <el-collapse>
          <el-collapse-item title="输入快照（inputs_snapshot）">
            <pre class="json">{{ JSON.stringify(detail.inputs_snapshot, null, 2) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import RealtimeQuoteBar from '../components/RealtimeQuoteBar.vue'
import CurveChart from '../components/CurveChart.vue'
import { api } from '../api'
import { md2html } from '../md'
import {
  forceCloseAgent, getAgentDecision, getAgentEquity, getAgentStatus,
  listAgentDecisions, listAccounts, removeAgentStock, runAgent, setupAgent,
  startAgent, stopAgent, toggleAgentStock,
  type Account, type AgentDecisionDetail, type AgentDecisionItem, type AgentPoolItem,
  type AgentStatus, type CurveMarker, type EquityPoint, type TradeRecord,
} from '../api'

const status = ref<AgentStatus | null>(null)

const equity = ref<EquityPoint[]>([])

const detailTs = ref('')
const pageSize = 20
const filterCode = ref('')
const filterState = ref<'' | 'on' | 'off'>('')
const detDecisions = ref<AgentDecisionItem[]>([])
const detLoading = ref(false)
const detPage = ref(1)
const detTotal = ref(0)
const detAll = ref<AgentDecisionItem[]>([]) // 用于曲线标注的全量决策
const runStockLoading = ref<'' | 'intraday' | 'daily'>('')

const configVisible = ref(false)
const configMode = ref<'edit' | 'add'>('edit')  // edit=编辑现有配置 add=批量新增股票
const saving = ref(false)
const configStocks = ref('')
const config = reactive({
  initial_cash: 100000,
  style: 'steady',
  patrol_freq: 60,
  account_id: null as number | null,  // 关联账户（方案A：可切换）
  risk_params: {
    max_pos_pct: 30,
    max_trades_per_day: 10,
    max_drawdown_halt: 10,
    halt_days: 3,
    loss_streak_limit: 3,
    cooldown_days: 2,
  } as Record<string, number | undefined>,
})
const allAccounts = ref<Account[]>([])
const refRows = ref<{ ts: string; ids: string }[]>([])

const detailVisible = ref(false)
const detail = ref<AgentDecisionDetail | null>(null)
const detailHtml = computed(() => (detail.value?.analysis_md ? md2html(detail.value.analysis_md) : ''))

const stockList = computed(() =>
  configStocks.value.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean))

const styleLabel = computed(() =>
  ({ steady: '稳健', balanced: '均衡', aggressive: '激进' })[status.value?.style as string] ?? status.value?.style)

const pauseActive = computed(() => {
  const p = status.value?.pause_until
  return !!p && p >= new Date().toISOString().slice(0, 10)
})

const initialCash = computed(() => status.value?.account.initial_cash ?? 100000)

/** 股票池列表：优先用后端 stock_pool，缺失时从 stocks+positions 兜底构造 */
const stockPool = computed<AgentPoolItem[]>(() => {
  const s = status.value
  if (!s) return []
  if (s.stock_pool?.length) return s.stock_pool
  const posMap = new Map((s.positions ?? []).map(p => [p.ts_code, p]))
  const decMap = new Map((s.recent_decisions ?? []).map(d => [d.ts_code, d]))
  return s.stocks.map(ts => ({
    ts_code: ts,
    name: ts,
    patrol_enabled: true,
    position: posMap.get(ts) ?? null,
    last_decision: decMap.get(ts) ?? null,
  }))
})

const filteredPool = computed(() => {
  const q = filterCode.value.trim().toLowerCase()
  return stockPool.value.filter(s =>
    (!q || s.ts_code.toLowerCase().includes(q) || (s.name ?? '').includes(filterCode.value.trim()))
    && (!filterState.value
        || (filterState.value === 'on' ? s.patrol_enabled : !s.patrol_enabled)))
})

const detailStock = computed(() => stockPool.value.find(s => s.ts_code === detailTs.value) ?? null)

/** 详情视图曲线标注：该股 executed 的买卖决策 */
const detailTrades = computed<TradeRecord[]>(() =>
  detAll.value
    .filter(d => d.status === 'executed' && (d.action === 'buy' || d.action === 'sell') && d.qty && d.price)
    .map(d => ({
      ts_code: d.ts_code,
      trade_date: d.run_date,
      side: d.action as 'buy' | 'sell',
      price: Number(d.price),
      qty: Number(d.qty),
      amount: Number(d.price) * Number(d.qty),
      fee: 0,
    })))

const detailMarkers = computed<CurveMarker[]>(() =>
  detailTrades.value.map(t => ({ date: t.trade_date, side: t.side })))

const fmt = (n: number) => Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 })

/** 提取后端 400 等错误的 detail，否则退回 message */
const errDetail = (e: unknown): string => {
  if (axios.isAxiosError(e)) {
    const d = e.response?.data as { detail?: string } | undefined
    if (d?.detail) return String(d.detail)
  }
  return (e as Error).message
}

const actionTagType = (a: string) =>
  a === 'buy' ? 'danger' : a === 'sell' ? 'success' : 'info'
const actionLabel = (a: string) => a === 'buy' ? '买' : a === 'sell' ? '卖' : 'hold'
const statusTagType = (s: string) =>
  s === 'executed' ? 'success' : s === 'rejected_by_risk' ? 'warning'
    : s === 'failed' ? 'danger' : 'info'
const statusLabel = (s: string) =>
  ({ executed: '已执行', rejected_by_risk: '风控拒绝', failed: '失败', hold: '观望' })[s] ?? s

const refresh = async () => {
  try {
    const arr = await getAgentStatus()
    status.value = arr.length ? arr[0] : null
  } catch (e) {
    ElMessage.error(`获取状态失败: ${(e as Error).message}`)
    return
  }
  // 账户曲线仅在个股详情展示
  if (detailTs.value) {
    try { equity.value = await getAgentEquity() } catch { equity.value = [] }
  }
}

const loadDetDecisions = async () => {
  if (!detailTs.value) return
  detLoading.value = true
  try {
    const r = await listAgentDecisions({ ts_code: detailTs.value, page: detPage.value, page_size: pageSize })
    detDecisions.value = r.items
    detTotal.value = r.total
  } catch (e) {
    ElMessage.error(`加载决策失败: ${(e as Error).message}`)
  } finally {
    detLoading.value = false
  }
}

const loadDetAllDecisions = async () => {
  if (!detailTs.value) return
  try {
    const r = await listAgentDecisions({ ts_code: detailTs.value, page: 1, page_size: 500 })
    detAll.value = r.items
  } catch {
    detAll.value = []
  }
}

const enterDetail = (tsCode: string) => {
  detailTs.value = tsCode
  detPage.value = 1
  detDecisions.value = []
  detAll.value = []
  void loadDetDecisions()
  void loadDetAllDecisions()
  void refresh()  // 详情页含账户曲线
}

const backToList = () => {
  detailTs.value = ''
}

const doToggle = async (tsCode: string) => {
  try {
    const r = await toggleAgentStock(tsCode)
    ElMessage.success(r.patrol_enabled ? '已开启巡盘' : '已停止巡盘')
  } catch (e) {
    ElMessage.error(`切换失败: ${errDetail(e)}`)
  }
  await refresh()
}

const doRemove = async (tsCode: string) => {
  try {
    await ElMessageBox.confirm(`确认将 ${tsCode} 移出股票池？`, '移除出池', { type: 'warning' })
  } catch { return }
  try {
    const r = await removeAgentStock(tsCode)
    if (r.removed) {
      ElMessage.success(`已移除 ${tsCode}`)
      if (detailTs.value === tsCode) backToList()
    } else {
      ElMessage.warning('未移除')
    }
  } catch (e) {
    ElMessage.error(`移除失败: ${errDetail(e)}`)
    return
  }
  await refresh()
}

const runStockDecision = async (mode: 'intraday' | 'daily') => {
  runStockLoading.value = mode
  try {
    const r = await runAgent({ ts_code: detailTs.value, mode })
    const first = r.results?.[0]
    ElMessage.success(first ? `已执行 ${first.ts_code}: ${first.action}（${first.status}）` : '已执行')
  } catch (e) {
    ElMessage.error(`触发失败: ${errDetail(e)}`)
    runStockLoading.value = ''
    return
  }
  runStockLoading.value = ''
  await refresh()
  await loadDetDecisions()
  await loadDetAllDecisions()
}

const doStart = async () => {
  try {
    await startAgent()
    ElMessage.success('已启动')
  } catch (e) { ElMessage.error(`启动失败: ${(e as Error).message}`) }
  await refresh()
}

const doStop = async () => {
  try {
    await stopAgent()
    ElMessage.success('已停止')
  } catch (e) { ElMessage.error(`停止失败: ${(e as Error).message}`) }
  await refresh()
}

const doForceClose = async () => {
  try {
    await ElMessageBox.confirm('确认强制清仓？将卖出全部持仓，不可恢复。', '强制清仓', { type: 'warning' })
  } catch { return }
  try {
    const r = await forceCloseAgent()
    ElMessage.success(r.msg || '已清仓')
  } catch (e) {
    ElMessage.error(`清仓失败: ${(e as Error).message}`)
    return
  }
  await refresh()
}

const openConfig = () => {
  configMode.value = 'edit'
  const s = status.value
  configStocks.value = s ? s.stocks.join(', ') : ''
  config.account_id = s?.account_id ?? null
  config.initial_cash = s?.account.initial_cash ?? 100000
  config.style = (s?.style as string) ?? 'steady'
  config.patrol_freq = s?.patrol_freq ?? 60
  const rp = (s?.risk_params ?? {}) as Record<string, number | undefined>
  for (const k of Object.keys(config.risk_params)) {
    if (rp[k] != null) config.risk_params[k] = rp[k]
  }
  const refs = (s?.reference_strategies ?? {}) as Record<string, unknown>
  refRows.value = stockList.value.map(ts => ({
    ts,
    ids: Array.isArray(refs[ts]) ? (refs[ts] as number[]).join(',') : '',
  }))
  configVisible.value = true
}

/** 批量新增：向池中追加股票（可多只），共用现有风格/风控/关联账户 */
const openAdd = async () => {
  configMode.value = 'add'
  configStocks.value = ''
  try { allAccounts.value = await listAccounts() } catch { allAccounts.value = [] }
  configVisible.value = true
}

watch(stockList, (list) => {
  // 同步参考策略行（保留已输入）
  const old = new Map(refRows.value.map(r => [r.ts, r.ids]))
  refRows.value = list.map(ts => ({ ts, ids: old.get(ts) ?? '' }))
})

const saveConfig = async () => {
  if (!stockList.value.length) {
    ElMessage.warning('股票池不能为空')
    return
  }
  const reference_strategies: Record<string, number[]> = {}
  for (const r of refRows.value) {
    const ids = r.ids.split(/[,，\s]+/).map(x => parseInt(x, 10)).filter(n => !isNaN(n))
    if (ids.length) reference_strategies[r.ts] = ids
  }
  saving.value = true
  try {
    if (configMode.value === 'add') {
      // 批量新增：合并进现有股票池（去重），关联账户沿用现有配置
      const merged = [...new Set([...(status.value?.stocks ?? []), ...stockList.value])]
      const r = await setupAgent({
        stocks: merged,
        style: config.style,
        patrol_freq: config.patrol_freq,
        risk_params: config.risk_params,
        reference_strategies,
      })
      status.value = r
    } else {
      const r = await setupAgent({
        stocks: stockList.value,
        initial_cash: status.value ? undefined : config.initial_cash,
        account_id: config.account_id ?? undefined,  // 方案A：切换关联账户
        style: config.style,
        patrol_freq: config.patrol_freq,
        risk_params: config.risk_params,
        reference_strategies,
      })
      status.value = r
    }
    configVisible.value = false
    ElMessage.success(configMode.value === 'add' ? '已加入巡盘池' : '配置已保存')
  } catch (e) {
    ElMessage.error(`保存失败: ${(e as Error).message}`)
  } finally {
    saving.value = false
  }
}

const testNotify = async () => {
  try {
    const r = await api.post('/agent/notify-test').then(x => x.data)
    if (r.ok) ElMessage.success(r.msg)
    else ElMessage.warning(r.msg)
  } catch (e) {
    ElMessage.error(`测试失败: ${(e as Error).message}`)
  }
}

const openDetail = async (id: number) => {
  detailVisible.value = true
  detail.value = null
  try {
    detail.value = await getAgentDecision(id)
  } catch (e) {
    ElMessage.error(`加载详情失败: ${(e as Error).message}`)
  }
}

onMounted(() => {
  void refresh()
})
</script>

<style scoped>
.agent { display: flex; flex-direction: column; gap: 12px; }
.empty-tip { color: #909399; }
.ctrl-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.ctrl-info { margin-top: 10px; color: #606266; font-size: 13px; }
.pool-code { color: #909399; font-size: 12px; margin-left: 6px; }
.no-pos { color: #c0c4cc; }
.ld-time { color: #909399; font-size: 12px; margin-left: 6px; }
.detail-head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.detail-code { color: #909399; font-size: 13px; }
.detail-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; }
.switch-label { font-size: 13px; color: #606266; }
.pos-card { display: flex; gap: 32px; margin-top: 12px; padding: 12px 14px;
  background: #f5f7fa; border-radius: 6px; flex-wrap: wrap; }
.pos-item { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: #909399; }
.pos-item b { font-size: 16px; color: #303133; }
.no-pos-tip { margin-top: 12px; color: #c0c4cc; font-size: 13px; }
.pager { display: flex; justify-content: flex-end; margin-top: 10px; }
.tags { margin-top: 6px; }
.hint { color: #909399; font-size: 12px; margin-top: 2px; }
.risk-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 16px; }
.risk-item { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: #606266; }
.detail .d-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.detail .d-time { color: #909399; font-size: 12px; }
.detail .d-sec h4 { margin: 12px 0 4px; }
.detail .d-sec p { margin: 0; color: #303133; font-size: 13px; white-space: pre-wrap; }
.json { background: #f5f7fa; padding: 8px; border-radius: 4px; font-size: 12px; overflow: auto; max-height: 300px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
</style>
