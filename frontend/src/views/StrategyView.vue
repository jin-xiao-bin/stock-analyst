<template>
  <div class="strategy">
    <!-- 列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>策略列表（版本链：← 指向父版本）</span>
          <span>
            <el-button size="small" @click="openDlg('create')">新建</el-button>
            <el-button size="small" @click="openDlg('import')">粘贴导入</el-button>
            <el-button size="small" type="warning" plain @click="jqDlg = true">导入聚宽策略</el-button>
            <el-button size="small" type="primary" @click="aiDlg = true">AI生成策略</el-button>
            <el-button size="small" @click="loadList">刷新</el-button>
          </span>
        </div>
      </template>
      <el-table :data="strategies" size="small" row-key="id">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column label="来源" width="90">
          <template #default="{ row }">
            <el-tag size="small" :type="row.source === 'agent' ? 'warning' : row.source === 'import' ? 'success' : 'info'">
              {{ row.source }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : row.status === 'deprecated' ? 'info' : 'danger'">
              {{ row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version_no" label="版本" width="60" />
        <el-table-column label="版本链" min-width="180">
          <template #default="{ row }">{{ chainText(row) }}</template>
        </el-table-column>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-body">
              <div><b>描述：</b>{{ row.description || '—' }}</div>
              <div><b>版本说明：</b>{{ row.version_note || '—' }}</div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="310">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="editStrategy(row.id)">编辑</el-button>
            <el-button link type="success" size="small" @click="openChat(row)">对话</el-button>
            <el-button link size="small" @click="openBacktest(row.id)">发起回测</el-button>
            <el-button link size="small" @click="openBtHistory(row)">查看回测</el-button>
            <el-button link type="warning" size="small" @click="openBind(row.id)">挂机绑定</el-button>
            <el-button v-if="row.status !== 'active'" link type="success" size="small" @click="setActive(row.id, true)">激活</el-button>
            <el-button v-else link type="info" size="small" @click="setActive(row.id, false)">停用</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 回测历史抽屉（按策略） -->
    <el-drawer v-model="btHistDlg" :title="`回测历史 · #${btHistStrategy?.id ?? ''} ${btHistStrategy?.name ?? ''}`" size="72%">
      <div class="bthist-toolbar">
        <el-button size="small" :disabled="btHistPicked.length < 2" type="primary" plain @click="compareBtRuns">
          对比选中({{ btHistPicked.length }})
        </el-button>
        <el-button size="small" @click="loadBtHistory">刷新</el-button>
        <span class="hint2">勾选多次回测可叠加对比收益曲线；点行查看详情</span>
      </div>
      <el-table :data="btHistList" size="small" v-loading="btHistLoading"
                row-key="id"
                @selection-change="(rows: BacktestListItem[]) => (btHistPicked = rows)"
                @row-click="(row: BacktestListItem) => showBtDetail(row.id)" style="cursor: pointer">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="id" label="Run" width="64" />
        <el-table-column label="区间" width="200">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column label="总收益" width="92">
          <template #default="{ row }">
            <span v-if="row.metrics" :class="row.metrics.total_return >= 0 ? 'up' : 'down'">
              {{ (row.metrics.total_return * 100).toFixed(2) }}%
            </span><span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column label="最大回撤" width="92">
          <template #default="{ row }">{{ row.metrics ? (row.metrics.max_drawdown * 100).toFixed(1) + '%' : '—' }}</template>
        </el-table-column>
        <el-table-column label="胜率" width="76">
          <template #default="{ row }">{{ row.metrics ? (row.metrics.win_rate * 100).toFixed(0) + '%' : '—' }}</template>
        </el-table-column>
        <el-table-column label="夏普" width="70">
          <template #default="{ row }">{{ row.metrics ? row.metrics.sharpe.toFixed(2) : '—' }}</template>
        </el-table-column>
        <el-table-column label="交易数" width="70">
          <template #default="{ row }">{{ row.metrics?.trade_count ?? '—' }}</template>
        </el-table-column>
        <el-table-column prop="created_at" label="时间" width="160" />
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click.stop="showBtDetail(row.id)">详情</el-button>
            <el-button link type="danger" size="small" @click.stop="deleteBtRun(row.id)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <!-- 单次回测详情 -->
      <div v-if="btHistDetail" class="bthist-detail">
        <h4 style="margin: 14px 0 8px">Run #{{ btHistDetail.id }} 详情（{{ btHistDetail.start_date }} ~ {{ btHistDetail.end_date }}）</h4>
        <el-row :gutter="8" style="margin-bottom: 8px">
          <el-col :span="3" v-for="m in btDetailMetrics" :key="m.label">
            <el-card shadow="never" class="mini"><div class="mini-lbl">{{ m.label }}</div>
              <b :class="m.up === undefined ? '' : m.up ? 'up' : 'down'">{{ m.text }}</b></el-card>
          </el-col>
        </el-row>
        <CurveChart
          :series="[{ name: `#run${btHistDetail.id}`, data: btHistDetail.equity_curve ?? [], initialCash: btHistDetail.initial_cash ?? 1000000 }]"
          :markers="(btHistDetail.trades ?? []).map(t => ({ date: t.trade_date, side: t.side }))"
          :trades="btHistDetail.trades ?? []"
        />
        <h4 style="margin: 12px 0 6px">交易明细（{{ btHistDetail.trades?.length ?? 0 }} 笔）</h4>
        <el-table :data="btHistDetail.trades" size="small" max-height="240">
          <el-table-column prop="trade_date" label="日期" width="110" />
          <el-table-column label="方向" width="70">
            <template #default="{ row: t }">
              <el-tag :type="t.side === 'buy' ? 'danger' : 'success'" size="small">{{ t.side === 'buy' ? '买' : '卖' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="price" label="价格" width="90" />
          <el-table-column prop="qty" label="数量" width="90" />
          <el-table-column prop="amount" label="金额" width="110" />
          <el-table-column prop="fee" label="费用" width="80" />
          <el-table-column prop="reason" label="信号" min-width="120" />
        </el-table>
      </div>
    </el-drawer>

    <!-- 回测对比对话框 -->
    <el-dialog v-model="btCmpDlg" title="回测对比（相对各自初始资金收益率%）" width="80%">
      <CurveChart v-if="btCmpSeries.length" :series="btCmpSeries" />
    </el-dialog>

    <!-- 策略对话抽屉 -->
    <el-drawer v-model="chatDlg" :title="`策略对话 · #${chatStrategy?.id ?? ''} ${chatStrategy?.name ?? ''}`" size="52%">
      <div class="chat-list">
        <el-empty v-if="!chatMsgs.length"
                  description="与 AI 讨论这个策略：质疑设计、要求修改（如'加5%止损'）、询问回撤原因…AI 会给出解释与新代码提案，确认后应用为新版本" :image-size="70" />
        <div v-for="m in chatMsgs" :key="m.id" class="chat-msg" :class="m.role">
          <div class="bubble">
            <div class="md-body" v-html="md2html(m.content)" />
            <div v-if="m.proposed_code" class="proposal">
              <div class="prop-head">
                <b>📋 新代码提案</b>
                <el-tag v-if="m.validation" size="small"
                        :type="m.validation.ok ? 'success' : 'danger'">
                  {{ m.validation.ok ? `沙箱校验通过（试跑${m.validation.trial_trades ?? 0}笔）` : '校验失败' }}
                </el-tag>
                <el-tag v-else size="small" type="info">未校验</el-tag>
              </div>
              <pre class="code">{{ m.proposed_code }}</pre>
              <el-button v-if="m.validation?.ok" size="small" type="primary"
                         @click="applyProposal(m)">应用为新版本</el-button>
            </div>
            <div class="msg-time">{{ m.created_at }}</div>
          </div>
        </div>
      </div>
      <div class="chat-input">
        <el-input v-model="chatInput" type="textarea" :rows="2" maxlength="2000"
                  placeholder="如：把快线改成EMA10并加5%止损 / 为什么最近回撤这么大？（Enter发送）"
                  @keydown.enter.exact.prevent="sendChatMsg" />
        <el-button type="primary" :loading="chatLoading" style="margin-top: 8px"
                   @click="sendChatMsg">发送</el-button>
      </div>
    </el-drawer>

    <!-- 聚宽策略导入对话框 -->
    <el-dialog v-model="jqDlg" title="导入聚宽(JoinQuant)策略" width="70%" top="4vh">
      <el-alert type="info" :closable="false" style="margin-bottom: 10px"
                title="支持直接粘贴 .py 代码或 .ipynb Notebook 的 JSON 源码"
                description="自动套聚宽兼容层运行（attribute_history/order_target等API自动桥接到单标的沙箱）；失败时 AI 自动改写兜底。多股票选股/组合类策略会被简化为单标的，建议导入后先回测验证。" />
      <el-form label-width="80px">
        <el-form-item label="策略名称">
          <el-input v-model="jqName" placeholder="如：聚宽均线策略" style="width: 300px" />
        </el-form-item>
        <el-form-item label="策略代码">
          <el-input v-model="jqCode" type="textarea" :rows="14" class="code-editor"
                    placeholder="粘贴聚宽策略代码（initialize/handle_data/调度函数），或整个 .ipynb 的 JSON" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="jqDlg = false">取消</el-button>
        <el-button type="primary" :loading="jqLoading" @click="doImportJq">导入并适配</el-button>
      </template>
    </el-dialog>

    <!-- 编辑对话框（新建/导入/编辑） -->
    <el-dialog v-model="editDlg" :title="dlgTitle" width="72%" top="4vh">      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="form.name" style="width: 360px" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" />
        </el-form-item>
        <el-form-item label="策略代码">
          <el-input
            v-model="form.code"
            type="textarea"
            :rows="16"
            spellcheck="false"
            class="code-editor"
            placeholder="def init(ctx): ...&#10;def on_bar(ctx, bar, i): ..."
          />
        </el-form-item>
        <el-form-item label="参数(JSON)">
          <el-input v-model="form.paramsJson" type="textarea" :rows="3" spellcheck="false" class="code-editor" placeholder='{"fast": 5, "slow": 20}' />
        </el-form-item>
      </el-form>
      <el-alert
        v-if="validateRes"
        :type="validateRes.ok ? 'success' : 'error'"
        :title="validateRes.ok ? '校验通过' : `校验失败`"
        :description="validateRes.error || ''"
        :closable="false"
        style="margin-bottom: 12px"
      />
      <template #footer>
        <el-button @click="validateRes = null; doValidate()" :loading="validating">校验</el-button>
        <el-button @click="editDlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- AI 生成对话框 -->
    <el-dialog v-model="aiDlg" title="AI 生成策略" width="68%" top="4vh">
      <el-input
        v-model="aiPrompt"
        type="textarea"
        :rows="3"
        placeholder="用自然语言描述你的策略需求，如：5日均线上穿20日均线全仓买入，死叉全部卖出"
      />
      <el-button type="primary" style="margin-top: 10px" :loading="aiGenerating" :disabled="!aiPrompt" @click="startGenerate">
        开始生成
      </el-button>
      <template v-if="aiStage">
        <el-divider content-position="left">生成状态：{{ aiStage }}</el-divider>
        <div v-if="aiCode" class="md-body"><pre class="ai-code">{{ aiCode }}</pre></div>
        <div v-if="aiExplain" class="md-body" v-html="md2html(aiExplain)" />
      </template>
    </el-dialog>

    <!-- 回测对话框 -->
    <el-dialog v-model="btDlg" title="发起回测" width="50%">
      <el-form label-width="90px">
        <el-form-item label="策略ID">{{ btForm.strategy_id }}</el-form-item>
        <el-form-item label="股票代码">
          <el-input v-model="btForm.ts_code" placeholder="如 000001.SZ" style="width: 220px" />
        </el-form-item>
        <el-form-item label="区间">
          <el-col :span="11">
            <el-date-picker v-model="btForm.start_date" type="date" value-format="YYYY-MM-DD" placeholder="开始" style="width: 100%" />
          </el-col>
          <el-col :span="2" class="center">至</el-col>
          <el-col :span="11">
            <el-date-picker v-model="btForm.end_date" type="date" value-format="YYYY-MM-DD" placeholder="结束" style="width: 100%" />
          </el-col>
        </el-form-item>
        <el-form-item label="初始资金">
          <el-input-number v-model="btForm.initial_cash" :min="10000" :step="100000" />
        </el-form-item>
        <el-form-item label="参数(JSON)">
          <el-input v-model="btForm.paramsJson" type="textarea" :rows="2" class="code-editor" placeholder="可选，覆盖默认参数" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="btDlg = false">取消</el-button>
        <el-button type="primary" :loading="btRunning" @click="runBt">开始回测</el-button>
      </template>
    </el-dialog>

    <!-- 回测结果（页内嵌） -->
    <el-card v-if="btResult" shadow="never">
      <template #header>
        <div class="card-head">
          <span>回测结果 #{{ btResult.id }}（{{ btResult.status }}）</span>
          <router-link v-if="btResult.id" to="/backtest" class="link">查看全部回测历史</router-link>
        </div>
      </template>
      <el-alert v-if="btResult.status === 'failed'" type="error" :title="btResult.error || '回测失败'" :closable="false" />
      <template v-else-if="btResult.metrics">
        <el-row :gutter="10" style="margin-bottom: 12px">
          <el-col :span="3" v-for="m in metricList" :key="m.label">
            <el-card shadow="never" class="mini">
              <div class="mini-lbl">{{ m.label }}</div>
              <b :class="m.up === undefined ? '' : m.up ? 'up' : 'down'">{{ m.text }}</b>
            </el-card>
          </el-col>
        </el-row>
        <h4>收益曲线（相对初始资金收益率；红B=买入 绿S=卖出{{ btResult.benchmark_curve?.length ? '；灰线=沪深300基准' : '' }}）</h4>
        <CurveChart
          v-if="btResult.equity_curve?.length"
          :series="[
            {
              name: `#${btResult.id}`,
              data: btResult.equity_curve ?? [],
              initialCash: btResult.initial_cash ?? 1000000,
            },
            ...(btResult.benchmark_curve?.length ? [{
              name: '沪深300基准',
              data: btResult.benchmark_curve ?? [],
              initialCash: btResult.initial_cash ?? 1000000,
              color: '#909399',
            }] : []),
          ]"
          :markers="(btResult.trades ?? []).map(t => ({ date: t.trade_date, side: t.side }))"
          :trades="btResult.trades ?? []"
        />
        <h4>交易明细（{{ btResult.trades?.length ?? 0 }} 笔）</h4>
        <el-table :data="btResult.trades" size="small" max-height="260">
          <el-table-column prop="trade_date" label="日期" width="110" />
          <el-table-column prop="side" label="方向" width="70">
            <template #default="{ row }">
              <el-tag :type="row.side === 'buy' ? 'danger' : 'success'" size="small">{{ row.side === 'buy' ? '买' : '卖' }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="price" label="价格" width="100" />
          <el-table-column prop="qty" label="数量" width="90" />
          <el-table-column prop="amount" label="金额" />
          <el-table-column prop="fee" label="费用" width="90" />
          <el-table-column prop="note" label="备注" min-width="140" />
        </el-table>
      </template>
    </el-card>

    <!-- 挂机绑定对话框（先展示已有绑定，再新增） -->
    <el-dialog v-model="bindDlg" title="挂机绑定（每日17:45自动执行）" width="560px">
      <h5 style="margin: 0 0 8px">已有绑定</h5>
      <el-empty v-if="!bindList.length" description="暂无绑定" :image-size="50" />
      <el-table v-else :data="bindList" size="small" style="margin-bottom: 14px">
        <el-table-column label="账户" min-width="140">
          <template #default="{ row }">
            {{ row.account_name }} <span class="lbl2">#{{ row.account_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="股票" min-width="150">
          <template #default="{ row }">{{ (row.ts_codes || []).join(', ') }}</template>
        </el-table-column>
        <el-table-column label="状态" width="80">
          <template #default="{ row }">
            <el-tag size="small" :type="row.status === 'active' ? 'success' : 'info'">
              {{ row.status === 'active' ? '运行中' : row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click="doUnbind(row.binding_id)">解绑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-divider style="margin: 8px 0" />
      <h5 style="margin: 0 0 8px">新增绑定</h5>
      <el-form label-width="90px">
        <el-form-item label="策略ID">{{ bindForm.strategy_id }}</el-form-item>
        <el-form-item label="账户">
          <el-select v-model="bindForm.account_id" style="width: 100%">
            <el-option v-for="a in accounts" :key="a.id" :label="`${a.name} (总资产 ${a.total_value})`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="股票代码">
          <el-input v-model="bindForm.ts_codes" placeholder="逗号分隔，如 000001.SZ,600519.SH" />
        </el-form-item>
        <el-form-item label="参数(JSON)">
          <el-input v-model="bindForm.paramsJson" type="textarea" :rows="2" class="code-editor" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bindDlg = false">关闭</el-button>
        <el-button type="primary" :loading="binding" @click="doBind">绑定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { api } from '../api'
import {
  activateStrategy, applyDiscussionCode, bindStrategy, createStrategy, deactivateStrategy,
  deleteBacktest, getBacktest, getStrategy, getStrategyDiscussion, listAccounts, listBacktests,
  listStrategies, postStrategyDiscussion, runBacktest, streamGenerateStrategy, unbindStrategy,
  updateStrategy, validateStrategy,
  type Account, type BacktestListItem, type BacktestResult, type CurveSeries, type StrategyDetail,
  type StrategyDiscussionMessage, type StrategyListItem, type ValidateResult,
} from '../api'
import CurveChart from '../components/CurveChart.vue'
import { md2html } from '../md'

const strategies = ref<StrategyListItem[]>([])

// ---------- 回测历史（按策略） ----------
const btHistDlg = ref(false)
const btHistStrategy = ref<StrategyListItem | null>(null)
const btHistList = ref<BacktestListItem[]>([])
const btHistPicked = ref<BacktestListItem[]>([])
const btHistLoading = ref(false)
const btHistDetail = ref<BacktestResult | null>(null)
const btCmpDlg = ref(false)
const btCmpSeries = ref<CurveSeries[]>([])

const btDetailMetrics = computed(() => {
  const m = btHistDetail.value?.metrics
  if (!m) return []
  const pct = (v: number) => `${(v * 100).toFixed(2)}%`
  const cards = [
    { label: '总收益', text: pct(m.total_return), up: m.total_return >= 0 },
    { label: '年化', text: pct(m.annual_return), up: m.annual_return >= 0 },
    { label: '最大回撤', text: pct(m.max_drawdown), up: false },
    { label: '夏普', text: m.sharpe.toFixed(2), up: m.sharpe >= 0 },
    { label: '胜率', text: pct(m.win_rate), up: undefined },
    { label: '交易数', text: String(m.trade_count), up: undefined },
    { label: '盈亏比', text: m.profit_factor.toFixed(2), up: undefined },
  ]
  if (m.benchmark_return !== undefined) {
    cards.push({ label: '基准收益', text: pct(m.benchmark_return), up: m.benchmark_return >= 0 })
  }
  if (m.excess_return !== undefined) {
    cards.push({ label: '超额收益', text: pct(m.excess_return), up: m.excess_return >= 0 })
  }
  return cards
})

// ---------- 聚宽导入 ----------
const jqDlg = ref(false)
const jqLoading = ref(false)
const jqName = ref('')
const jqCode = ref('')

const doImportJq = async () => {
  if (!jqCode.value.trim()) { ElMessage.warning('请粘贴聚宽策略代码'); return }
  jqLoading.value = true
  try {
    const r = await api.post('/strategies/import-jq',
      { code: jqCode.value, name: jqName.value || undefined }).then(x => x.data)
    const modeText = r.mode === 'shim' ? '兼容层直接运行（未消耗LLM）' : 'AI改写转换'
    ElMessage.success(`导入成功（${modeText}），策略 #${r.strategy_id}，请先发起回测验证`)
    jqDlg.value = false
    jqCode.value = ''
    jqName.value = ''
    if (r.warnings?.length) ElMessage.info(r.warnings.join('；'))
    await loadList()
  } catch (e) {
    const msg = axios.isAxiosError(e)
      ? String((e.response?.data as { detail?: string })?.detail ?? e.message)
      : (e as Error).message
    ElMessage({ message: `聚宽适配失败：${msg}`, type: 'error', duration: 8000 })
  } finally {
    jqLoading.value = false
  }
}

const openBtHistory = async (row: StrategyListItem) => {
  btHistStrategy.value = row
  btHistDetail.value = null
  btHistDlg.value = true
  await loadBtHistory()
}

const loadBtHistory = async () => {
  if (!btHistStrategy.value) return
  btHistLoading.value = true
  try {
    btHistList.value = await listBacktests(btHistStrategy.value.id)
  } catch (e) {
    ElMessage.error(`加载回测历史失败: ${(e as Error).message}`)
  } finally {
    btHistLoading.value = false
  }
}

const showBtDetail = async (id: number) => {
  try {
    btHistDetail.value = await getBacktest(id)
  } catch (e) {
    ElMessage.error(`加载详情失败: ${(e as Error).message}`)
  }
}

const deleteBtRun = async (id: number) => {
  try {
    await ElMessageBox.confirm(`确认删除回测 Run #${id}？不可恢复。`, '删除回测', { type: 'warning' })
  } catch { return }
  try {
    await deleteBacktest(id)
    ElMessage.success(`已删除 Run #${id}`)
    if (btHistDetail.value?.id === id) btHistDetail.value = null
    await loadBtHistory()
  } catch (e) {
    ElMessage.error(`删除失败: ${(e as Error).message}`)
  }
}

const CMP_COLORS = ['#409eff', '#e6a23c', '#67c23a', '#f56c6c', '#9c27b0', '#00bcd4']

const compareBtRuns = async () => {
  if (btHistPicked.value.length < 2) return
  try {
    const details = await Promise.all(btHistPicked.value.map(r => getBacktest(r.id)))
    btCmpSeries.value = details.map((r, i) => ({
      name: `#run${r.id} ${r.start_date}~${r.end_date}`,
      data: r.equity_curve ?? [],
      initialCash: r.initial_cash ?? 1000000,
      color: CMP_COLORS[i % CMP_COLORS.length],
    }))
    btCmpDlg.value = true
  } catch (e) {
    ElMessage.error(`加载对比失败: ${(e as Error).message}`)
  }
}

const chatDlg = ref(false)
const chatStrategy = ref<StrategyListItem | null>(null)
const chatMsgs = ref<(StrategyDiscussionMessage & { validation?: { ok: boolean; error?: string; trial_trades?: number } })[]>([])
const chatInput = ref('')
const chatLoading = ref(false)

const openChat = async (row: StrategyListItem) => {
  chatStrategy.value = row
  chatInput.value = ''
  try {
    const r = await getStrategyDiscussion(row.id)
    chatMsgs.value = r.messages
  } catch {
    chatMsgs.value = []
  }
  chatDlg.value = true
}

const sendChatMsg = async () => {
  if (!chatStrategy.value || !chatInput.value.trim() || chatLoading.value) return
  chatLoading.value = true
  const text = chatInput.value.trim()
  chatInput.value = ''
  chatMsgs.value.push({ id: -Date.now(), role: 'user', content: text, created_at: '刚刚' })
  try {
    const r = await postStrategyDiscussion(chatStrategy.value.id, text)
    chatMsgs.value.push({ ...r, created_at: '刚刚' })
    if (r.proposed_code) {
      ElMessage[r.validation?.ok ? 'success' : 'warning'](
        r.validation?.ok ? 'AI 已给出新代码提案（沙箱校验通过），可应用为新版本' : '代码提案未通过沙箱校验')
    }
  } catch (e) {
    ElMessage.error(`发送失败: ${(e as Error).message}`)
    chatMsgs.value = chatMsgs.value.filter(m => m.id > 0)
    chatInput.value = text
  } finally {
    chatLoading.value = false
  }
}

const applyProposal = async (m: StrategyDiscussionMessage) => {
  if (!chatStrategy.value) return
  try {
    await ElMessageBox.confirm(
      `将提案代码应用为新版本？当前版本保留，可在版本链中对比回看。`,
      '应用为新版本', { type: 'warning' })
  } catch { return }
  try {
    const r = await applyDiscussionCode(chatStrategy.value.id, m.id)
    ElMessage.success(`已创建新版本 #${r.new_strategy_id} v${r.version_no}`)
    chatDlg.value = false
    await loadList()
  } catch (e) {
    ElMessage.error(`应用失败: ${(e as Error).message}`)
  }
}


const chainText = (row: StrategyListItem): string => {
  const byId = new Map(strategies.value.map(s => [s.id, s]))
  const chain: string[] = [`#${row.id} v${row.version_no}`]
  let cur = row
  while (cur.parent_id != null) {
    const p = byId.get(cur.parent_id)
    if (!p) { chain.push(`← #${cur.parent_id}`); break }
    chain.push(`← #${p.id} v${p.version_no}`)
    cur = p
  }
  return chain.join(' ')
}

const loadList = async () => {
  try {
    strategies.value = await listStrategies()
  } catch (e) {
    ElMessage.error(`加载策略失败: ${(e as Error).message}`)
  }
}

// ---------- 编辑 ----------
type DlgMode = 'create' | 'import' | 'edit'
const editDlg = ref(false)
const dlgMode = ref<DlgMode>('create')
const dlgTitle = computed(() => ({ create: '新建策略', import: '粘贴导入策略', edit: '编辑策略' })[dlgMode.value])
const editingId = ref<number | null>(null)
const saving = ref(false)
const validating = ref(false)
const validateRes = ref<ValidateResult | null>(null)
const form = ref({ name: '', code: '', description: '', paramsJson: '{}' })

const openDlg = (mode: DlgMode) => {
  dlgMode.value = mode
  editingId.value = null
  validateRes.value = null
  form.value = { name: '', code: mode === 'import' ? '' : '', description: '', paramsJson: '{}' }
  editDlg.value = true
}

const editStrategy = async (id: number) => {
  try {
    const s = await getStrategy(id)
    dlgMode.value = 'edit'
    editingId.value = id
    validateRes.value = null
    form.value = {
      name: s.name,
      code: s.code,
      description: s.description ?? '',
      paramsJson: JSON.stringify(s.params ?? {}, null, 2),
    }
    editDlg.value = true
  } catch (e) {
    ElMessage.error(`加载策略失败: ${(e as Error).message}`)
  }
}

const parseParams = (): Record<string, unknown> | undefined => {
  const t = form.value.paramsJson.trim()
  if (!t) return undefined
  try { return JSON.parse(t) as Record<string, unknown> }
  catch { ElMessage.error('参数不是合法 JSON'); return undefined }
}

const doValidate = async () => {
  const params = parseParams()
  if (params === undefined && form.value.paramsJson.trim()) return
  validating.value = true
  try {
    const body: { code?: string; params?: Record<string, unknown> } = { code: form.value.code }
    if (params) body.params = params
    if (editingId.value != null) {
      validateRes.value = await validateStrategy(editingId.value, body)
    } else {
      ElMessage.warning('请先保存策略，再对新代码执行校验')
    }
  } catch (e) {
    ElMessage.error(`校验请求失败: ${(e as Error).message}`)
  } finally {
    validating.value = false
  }
}

const save = async () => {
  if (!form.value.name || !form.value.code.trim()) { ElMessage.warning('名称和代码必填'); return }
  const params = parseParams()
  if (params === undefined && form.value.paramsJson.trim()) return
  saving.value = true
  try {
    if (dlgMode.value === 'edit' && editingId.value != null) {
      await updateStrategy(editingId.value, {
        name: form.value.name, code: form.value.code,
        description: form.value.description || undefined, params,
      })
      ElMessage.success('已更新（生成新版本）')
    } else {
      await createStrategy({
        name: form.value.name, code: form.value.code,
        description: form.value.description || undefined, params,
        source: dlgMode.value === 'import' ? 'import' : 'manual',
      })
      ElMessage.success('已保存')
    }
    editDlg.value = false
    await loadList()
  } catch (e) {
    ElMessage.error(`保存失败: ${(e as Error).message}`)
  } finally {
    saving.value = false
  }
}

const setActive = async (id: number, active: boolean) => {
  try {
    if (active) await activateStrategy(id)
    else await deactivateStrategy(id)
    ElMessage.success(active ? '已激活（旧版本转为 deprecated）' : '已停用')
    await loadList()
  } catch (e) {
    ElMessage.error(`操作失败: ${(e as Error).message}`)
  }
}

// ---------- AI 生成 ----------
const aiDlg = ref(false)
const aiPrompt = ref('')
const aiGenerating = ref(false)
const aiStage = ref('')
const aiCode = ref('')
const aiExplain = ref('')

const startGenerate = async () => {
  aiGenerating.value = true
  aiStage.value = ''
  aiCode.value = ''
  aiExplain.value = ''
  try {
    await streamGenerateStrategy(aiPrompt.value, (event, data) => {
      const d = data as Record<string, unknown>
      if (event === 'status') aiStage.value = String(d.stage ?? d.msg ?? '')
      else if (event === 'section') {
        const role = String(d.role ?? '')
        const content = String(d.content ?? '')
        if (role.includes('code')) aiCode.value += content + '\n'
        else aiExplain.value += content + '\n'
      } else if (event === 'done') {
        aiStage.value = '完成'
        ElMessage.success(`策略已生成入库 #${d.strategy_id ?? ''}`)
        void loadList()
      } else if (event === 'error') {
        ElMessage.error(`生成失败: ${String(d.msg ?? '')}`)
      }
    })
  } catch (e) {
    ElMessage.error(`请求失败: ${(e as Error).message}`)
  } finally {
    aiGenerating.value = false
  }
}

// ---------- 回测 ----------
const btDlg = ref(false)
const btRunning = ref(false)
const btResult = ref<BacktestResult | null>(null)
const btForm = ref({
  strategy_id: 0, ts_code: '', start_date: '', end_date: '',
  initial_cash: 1000000, paramsJson: '',
})

const openBacktest = (id: number) => {
  btForm.value = { strategy_id: id, ts_code: '', start_date: '', end_date: '', initial_cash: 1000000, paramsJson: '' }
  btDlg.value = true
}

const metricList = computed(() => {
  const m = btResult.value?.metrics
  if (!m) return []
  const pct = (v: number) => `${(v * 100).toFixed(2)}%`
  return [
    { label: '总收益', text: pct(m.total_return), up: m.total_return >= 0 },
    { label: '年化收益', text: pct(m.annual_return), up: m.annual_return >= 0 },
    { label: '最大回撤', text: pct(m.max_drawdown), up: false },
    { label: '夏普', text: m.sharpe.toFixed(2), up: m.sharpe >= 0 },
    { label: '胜率', text: pct(m.win_rate), up: undefined },
    { label: '交易数', text: String(m.trade_count), up: undefined },
    { label: '盈亏比', text: m.profit_factor.toFixed(2), up: undefined },
  ]
})

// 裸6位数字自动补交易所后缀：6/9→.SH，0/3→.SZ，4/8→.BJ
const normTs = (s: string) => {
  const t = s.trim().toUpperCase()
  return (/^\d{6}$/.test(t)
    ? t + ('69'.includes(t[0]) ? '.SH' : '48'.includes(t[0]) ? '.BJ' : '.SZ')
    : t)
}

const runBt = async () => {
  if (!btForm.value.ts_code) { ElMessage.warning('请填写股票代码'); return }
  btRunning.value = true
  try {
    const params = btForm.value.paramsJson.trim()
      ? JSON.parse(btForm.value.paramsJson) as Record<string, unknown>
      : undefined
    btResult.value = await runBacktest({
      strategy_id: btForm.value.strategy_id,
      ts_code: normTs(btForm.value.ts_code),
      start_date: btForm.value.start_date || undefined,
      end_date: btForm.value.end_date || undefined,
      initial_cash: btForm.value.initial_cash,
      params,
    })
    if (btResult.value.status === 'failed') {
      // 失败：保留对话框并弹出完整原因（含本地可用数据范围提示）
      ElMessage.error(btResult.value.error || '回测失败')
      return
    }
    btDlg.value = false
    ElMessage.success('回测完成')
  } catch (e) {
    ElMessage.error(`回测失败: ${(e as Error).message}`)
  } finally {
    btRunning.value = false
  }
}

// ---------- 挂机绑定 ----------
const bindDlg = ref(false)
const binding = ref(false)
const accounts = ref<Account[]>([])
const bindForm = ref({ strategy_id: 0, account_id: null as number | null, ts_codes: '', paramsJson: '' })
const bindList = ref<{ binding_id: number; account_id: number; account_name: string; ts_codes: string[]; status: string }[]>([])

const loadBindings = async (sid: number) => {
  try {
    bindList.value = await api.get(`/strategies/${sid}/bindings`).then(r => r.data)
  } catch {
    bindList.value = []
  }
}

const openBind = async (id: number) => {
  bindForm.value = { strategy_id: id, account_id: null, ts_codes: '', paramsJson: '' }
  try { accounts.value = await listAccounts() } catch { /* ignore */ }
  await loadBindings(id)
  bindDlg.value = true
}

const doBind = async () => {
  if (!bindForm.value.account_id || !bindForm.value.ts_codes.trim()) {
    ElMessage.warning('请选择账户并填写股票代码'); return
  }
  binding.value = true
  try {
    const params = bindForm.value.paramsJson.trim()
      ? JSON.parse(bindForm.value.paramsJson) as Record<string, unknown>
      : undefined
    const r = await bindStrategy(bindForm.value.strategy_id, {
      account_id: bindForm.value.account_id,
      ts_codes: bindForm.value.ts_codes.split(/[,，\s]+/).filter(Boolean).map(normTs),
      params,
    })
    ElMessage.success(`绑定成功 binding_id=${(r as { binding_id: number }).binding_id}`)
    await loadBindings(bindForm.value.strategy_id)
  } catch (e) {
    ElMessage.error(`绑定失败: ${(e as Error).message}`)
  } finally {
    binding.value = false
  }
}

const doUnbind = async (bindingId: number) => {
  try {
    await ElMessageBox.confirm('解绑后该策略停止在此账户自动交易，历史交易保留。', '解绑确认', { type: 'warning' })
  } catch { return }
  try {
    await unbindStrategy(bindForm.value.strategy_id, bindingId)
    ElMessage.success('已解绑')
    await loadBindings(bindForm.value.strategy_id)
  } catch (e) {
    ElMessage.error(`解绑失败: ${(e as Error).message}`)
  }
}

onMounted(() => void loadList())
</script>

<style scoped>
.strategy { display: flex; flex-direction: column; gap: 12px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.expand-body { padding: 4px 12px; font-size: 13px; color: #606266; }
.expand-body div { margin: 4px 0; white-space: pre-wrap; }
.code-editor :deep(textarea) { font-family: Consolas, 'Courier New', monospace; font-size: 13px; }
.center { text-align: center; }
.mini { text-align: center; }
.mini .mini-lbl { color: #909399; font-size: 12px; margin-bottom: 4px; }
.equity-svg { width: 100%; height: 200px; background: #fafafa; border: 1px solid #ebeef5; }
.ai-code { background: #282c34; color: #abb2bf; padding: 12px; border-radius: 6px; font-family: Consolas, monospace; font-size: 13px; overflow-x: auto; white-space: pre-wrap; }
.md-body :deep(h4) { margin: 8px 0 4px; }
.md-body :deep(p) { margin: 4px 0; line-height: 1.6; }
.link { color: #409eff; text-decoration: none; font-size: 13px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
.chat-list { display: flex; flex-direction: column; gap: 10px; max-height: 56vh; overflow-y: auto; padding: 4px; }
.chat-msg { display: flex; }
.chat-msg.user { justify-content: flex-end; }
.chat-msg .bubble { max-width: 88%; padding: 8px 12px; border-radius: 8px; background: #f4f4f5; }
.chat-msg.user .bubble { background: #ecf5ff; }
.msg-time { color: #c0c4cc; font-size: 11px; margin-top: 4px; text-align: right; }
.chat-input { margin-top: 10px; display: flex; flex-direction: column; align-items: flex-end; }
.proposal { margin-top: 8px; border-top: 1px dashed #dcdfe6; padding-top: 8px; }
.prop-head { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; }
.code { background: #282c34; color: #abb2bf; padding: 10px; border-radius: 6px;
  font-family: Consolas, monospace; font-size: 12px; overflow-x: auto; white-space: pre-wrap;
  max-height: 300px; overflow-y: auto; }
.bthist-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.bthist-detail { border-top: 1px solid #ebeef5; margin-top: 12px; padding-top: 4px; }
.hint2 { color: #c0c4cc; font-size: 12px; }
.lbl2 { color: #909399; font-size: 12px; }
</style>
