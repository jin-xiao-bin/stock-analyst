<template>
  <div class="review">
    <!-- 发起审查 -->
    <el-card shadow="never">
      <template #header>发起交易审查</template>
      <el-form :inline="true">
        <el-form-item label="账户">
          <el-select v-model="form.account_id" style="width: 220px">
            <el-option v-for="a in accounts" :key="a.id" :label="`${a.name} (#${a.id})`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="范围">
          <el-radio-group v-model="form.scope">
            <el-radio-button value="manual">手动交易</el-radio-button>
            <el-radio-button value="strategy">策略交易</el-radio-button>
            <el-radio-button value="all">全部</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.scope === 'strategy'" label="策略">
          <el-select v-model="form.strategy_id" style="width: 200px">
            <el-option v-for="s in strategies" :key="s.id" :label="`#${s.id} ${s.name}`" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="时段">
          <el-date-picker v-model="form.period_start" type="date" value-format="YYYY-MM-DD" placeholder="开始" />
          <span style="margin: 0 6px">至</span>
          <el-date-picker v-model="form.period_end" type="date" value-format="YYYY-MM-DD" placeholder="结束" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="running" :disabled="!form.account_id" @click="startReview">
            开始审查
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 流式渲染 -->
    <el-card v-if="stage || sections.length" shadow="never">
      <template #header>
        审查进度：{{ stage || '—' }}
        <el-progress v-if="running" :indeterminate="true" :show-text="false" style="width: 200px; float: right" />
      </template>
      <div v-for="(s, i) in sections" :key="i" class="md-body" v-html="md2html(s)" />
    </el-card>

    <!-- 审查历史 -->
    <el-card shadow="never">
      <template #header>审查历史</template>
      <el-table :data="history" size="small">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="scope" label="范围" width="90" />
        <el-table-column prop="period_start" label="时段起" width="110" />
        <el-table-column prop="period_end" label="时段止" width="110" />
        <el-table-column prop="followup" label="跟进" width="100" />
        <el-table-column prop="created_at" label="时间" width="180" />
        <el-table-column label="操作">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="loadReview(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 建议列表 -->
    <el-card v-if="review" shadow="never">
      <template #header>
        <div class="card-head">
          <span>审查报告 #{{ review.id }} · 建议（{{ suggestions.length }}）</span>
          <span>
            <el-tag v-if="review.followup" size="small" :type="review.followup === 'adopted' ? 'success' : 'info'">{{ review.followup }}</el-tag>
            <el-button v-else size="small" @click="setFollowup('adopted')">采纳</el-button>
            <el-button v-if="!review.followup" size="small" @click="setFollowup('dismissed')">不采纳</el-button>
          </span>
        </div>
      </template>
      <div class="md-body" v-html="md2html(review.content)" />
      <el-divider />
      <div v-for="(sg, i) in suggestions" :key="i" class="suggestion">
        <el-tag size="small" :type="sg.type === 'param_adjust' ? 'warning' : sg.type === 'risk_control' ? 'danger' : 'info'">
          {{ sg.type }}
        </el-tag>
        <div class="sg-detail">{{ sg.detail }}</div>
        <div v-if="sg.proposed_action" class="sg-action">建议动作：{{ sg.proposed_action }}</div>
        <el-button
          v-if="sg.type === 'param_adjust'"
          type="warning" size="small" style="margin-top: 6px"
          :loading="applyingIndex === i"
          @click="applySuggestion(i)"
        >生成优化版本</el-button>

        <!-- apply 结果 -->
        <el-card v-if="applyRes" shadow="never" class="apply-res">
          <template #header>
            <div class="card-head">
              <span>优化版本：新策略 #{{ applyRes.new_strategy_id }}（回测 Run #{{ applyRes.old_run_id }} → #{{ applyRes.new_run_id }}）</span>
              <el-button type="success" size="small" @click="activateNew(applyRes.new_strategy_id)">激活新版本</el-button>
            </div>
          </template>
          <h4>版本说明（5段式迭代说明）</h4>
          <div class="md-body" v-html="md2html(applyRes.version_note)" />
          <h4>新旧回测对比</h4>
          <table class="cmp-table" v-if="cmpRows.length">
            <tr>
              <th>指标</th><th>旧 Run #{{ applyRes.old_run_id }}</th><th>新 Run #{{ applyRes.new_run_id }}</th><th>变化</th>
            </tr>
            <tr v-for="r in cmpRows" :key="r.label">
              <td>{{ r.label }}</td><td>{{ r.a }}</td><td>{{ r.b }}</td>
              <td :class="r.deltaClass">{{ r.delta }}</td>
            </tr>
          </table>
        </el-card>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  activateStrategy, applyReviewSuggestion, getBacktest, getReview, listAccounts, listReviews,
  listStrategies, reviewFollowup, streamReview,
  type Account, type BacktestResult, type ReviewApplyResult, type ReviewDetail,
  type ReviewListItem, type ReviewSuggestion, type StrategyListItem,
} from '../api'
import { md2html } from '../md'

const accounts = ref<Account[]>([])
const strategies = ref<StrategyListItem[]>([])
const history = ref<ReviewListItem[]>([])

const form = ref<{
  account_id: number | null
  scope: 'manual' | 'strategy' | 'all'
  strategy_id: number | null
  period_start: string
  period_end: string
}>({ account_id: null, scope: 'all', strategy_id: null, period_start: '', period_end: '' })

const running = ref(false)
const stage = ref('')
const sections = ref<string[]>([])
const review = ref<ReviewDetail | null>(null)
const applyingIndex = ref(-1)
const applyRes = ref<ReviewApplyResult | null>(null)
const oldRun = ref<BacktestResult | null>(null)
const newRun = ref<BacktestResult | null>(null)

const suggestions = computed<ReviewSuggestion[]>(() => review.value?.suggestions ?? [])

const cmpRows = computed(() => {
  const a = oldRun.value?.metrics
  const b = newRun.value?.metrics
  if (!a || !b) return []
  const pct = (v: number) => (v * 100).toFixed(2) + '%'
  const mk = (label: string, av: string, bv: string, delta: string, deltaClass: string) => ({ label, a: av, b: bv, delta, deltaClass })
  return [
    mk('总收益', pct(a.total_return), pct(b.total_return),
      (b.total_return - a.total_return >= 0 ? '+' : '') + pct(b.total_return - a.total_return),
      b.total_return >= a.total_return ? 'up' : 'down'),
    mk('最大回撤', pct(a.max_drawdown), pct(b.max_drawdown),
      (b.max_drawdown - a.max_drawdown >= 0 ? '+' : '') + pct(b.max_drawdown - a.max_drawdown),
      b.max_drawdown <= a.max_drawdown ? 'up' : 'down'),
    mk('夏普', a.sharpe.toFixed(2), b.sharpe.toFixed(2),
      (b.sharpe - a.sharpe >= 0 ? '+' : '') + (b.sharpe - a.sharpe).toFixed(2),
      b.sharpe >= a.sharpe ? 'up' : 'down'),
    mk('胜率', pct(a.win_rate), pct(b.win_rate),
      (b.win_rate - a.win_rate >= 0 ? '+' : '') + pct(b.win_rate - a.win_rate),
      b.win_rate >= a.win_rate ? 'up' : 'down'),
    mk('交易数', String(a.trade_count), String(b.trade_count), String(b.trade_count - a.trade_count), ''),
  ]
})

const startReview = async () => {
  if (!form.value.account_id) return
  running.value = true
  stage.value = ''
  sections.value = []
  review.value = null
  applyRes.value = null
  try {
    await streamReview({
      account_id: form.value.account_id,
      scope: form.value.scope,
      strategy_id: form.value.scope === 'strategy' ? (form.value.strategy_id ?? undefined) : undefined,
      period_start: form.value.period_start || undefined,
      period_end: form.value.period_end || undefined,
    }, (event, data) => {
      const d = data as Record<string, unknown>
      if (event === 'status') stage.value = String(d.stage ?? d.msg ?? '')
      else if (event === 'section') sections.value.push(String(d.content ?? ''))
      else if (event === 'done') {
        stage.value = '完成'
        ElMessage.success(`审查完成 #${d.review_id ?? ''}`)
        void loadHistory()
        if (d.review_id != null) void loadReview(Number(d.review_id))
      } else if (event === 'error') {
        ElMessage.error(`审查失败: ${String(d.msg ?? '')}`)
      }
    })
  } catch (e) {
    ElMessage.error(`请求失败: ${(e as Error).message}`)
  } finally {
    running.value = false
  }
}

const loadHistory = async () => {
  try {
    history.value = await listReviews(form.value.account_id ?? undefined)
  } catch { /* ignore */ }
}

const loadReview = async (id: number) => {
  try {
    review.value = await getReview(id)
    applyRes.value = null
  } catch (e) {
    ElMessage.error(`加载审查报告失败: ${(e as Error).message}`)
  }
}

const setFollowup = async (f: 'adopted' | 'dismissed') => {
  if (!review.value) return
  try {
    await reviewFollowup(review.value.id, f)
    review.value = { ...review.value, followup: f }
    ElMessage.success('已记录')
  } catch (e) {
    ElMessage.error(`操作失败: ${(e as Error).message}`)
  }
}

const applySuggestion = async (index: number) => {
  if (!review.value) return
  applyingIndex.value = index
  try {
    const res = await applyReviewSuggestion(review.value.id, index)
    applyRes.value = res
    const [o, n] = await Promise.all([getBacktest(res.old_run_id), getBacktest(res.new_run_id)])
    oldRun.value = o
    newRun.value = n
    ElMessage.success('优化版本已生成并通过沙箱校验（未自动替换挂机）')
  } catch (e) {
    ElMessage.error(`生成优化版本失败: ${(e as Error).message}`)
  } finally {
    applyingIndex.value = -1
  }
}

const activateNew = async (id: number) => {
  try {
    await activateStrategy(id)
    ElMessage.success(`策略 #${id} 已激活，旧版本转为 deprecated`)
  } catch (e) {
    ElMessage.error(`激活失败: ${(e as Error).message}`)
  }
}

onMounted(async () => {
  try {
    accounts.value = await listAccounts()
    if (accounts.value.length && !form.value.account_id) form.value.account_id = accounts.value[0].id
  } catch { /* ignore */ }
  try { strategies.value = await listStrategies() } catch { /* ignore */ }
  await loadHistory()
})
</script>

<style scoped>
.review { display: flex; flex-direction: column; gap: 12px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.suggestion { border: 1px solid #ebeef5; border-radius: 6px; padding: 10px 14px; margin-bottom: 10px; }
.sg-detail { margin-top: 6px; font-size: 13px; }
.sg-action { margin-top: 4px; font-size: 12px; color: #e6a23c; }
.apply-res { margin-top: 10px; }
.cmp-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.cmp-table th, .cmp-table td { border: 1px solid #ebeef5; padding: 6px 10px; text-align: center; }
.md-body :deep(h4) { margin: 8px 0 4px; }
.md-body :deep(p) { margin: 6px 0; line-height: 1.7; }
.md-body :deep(code) { background: #f4f4f5; padding: 1px 5px; border-radius: 3px; font-family: Consolas, monospace; }
.md-body :deep(ul), .md-body :deep(ol) { padding-left: 20px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
</style>
