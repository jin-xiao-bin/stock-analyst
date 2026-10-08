<template>
  <div class="analysis">
    <!-- 顶部：股票选择 + 生成 -->
    <el-card shadow="never" class="toolbar">
      <el-select
        v-model="tsCode"
        filterable
        remote
        clearable
        placeholder="搜索代码/名称"
        :remote-method="doSearch"
        :loading="searching"
        style="width: 340px"
      >
        <el-option v-for="s in options" :key="s.ts_code" :label="`${s.name} (${s.ts_code})`" :value="s.ts_code" />
      </el-select>
      <el-button type="primary" :disabled="!tsCode" :loading="generating" @click="generate">
        生成分析
      </el-button>
      <el-button :disabled="!tsCode" :loading="synthesising" @click="synthesis">
        归纳总结
      </el-button>
      <el-button @click="loadReports">刷新列表</el-button>
    </el-card>

    <!-- 生成进度 -->
    <el-card v-if="generating || synthesising || stage !== ''" shadow="never" class="progress-card">
      <div class="progress-row">
        <span>当前阶段：{{ stageLabel }}</span>
        <el-progress :percentage="stageProgress" style="flex: 1" />
      </div>
    </el-card>

    <!-- 流式 section 渲染 -->
    <el-row v-if="sections.length" :gutter="12">
      <el-col v-for="(s, i) in sections" :key="i" :span="12">
        <el-card shadow="never" class="section-card">
          <template #header>
            <el-tag size="small">{{ s.role }}</el-tag> {{ s.title }}
          </template>
          <div class="md-body" v-html="md2html(s.content)" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 综合分析列表（全局，默认展示全部） -->
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>综合分析列表（点击行查看全文；「查看归纳」看该股观点归纳；勾选两份可对比）</span>
          <span>
            <el-button size="small" :disabled="picked.length !== 2" @click="doDiff">对比选中报告</el-button>
            <el-button size="small" type="danger" :disabled="!picked.length" @click="deletePicked">
              删除选中({{ picked.length }})
            </el-button>
            <el-button size="small" @click="loadReports">刷新</el-button>
          </span>
        </div>
      </template>
      <div class="filter-row">
        <el-input v-model="filterCode" placeholder="按股票代码筛选，如 601689" clearable style="width: 200px" />
        <el-input v-model="filterName" placeholder="按公司名称筛选，如 拓普" clearable style="width: 200px" />
      </div>
      <el-table
        :data="companyReports"
        size="small"
        @selection-change="(rows: ReportListItem[]) => (picked = rows)"
        @row-click="(row: ReportListItem) => viewReport(row.id)"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column prop="ts_code" label="股票代码" width="110" />
        <el-table-column prop="stock_name" label="公司名称" width="120" />
        <el-table-column prop="as_of_date" label="截止日期" width="120" />
        <el-table-column prop="title" label="标题" min-width="200" />
        <el-table-column prop="created_at" label="生成时间" width="180" />
        <el-table-column label="操作" width="230">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click.stop="viewReport(row.id)">查看</el-button>
            <el-tooltip
              :content="synthesisFor(row) ? '查看该股观点归纳总结' : '尚未生成归纳总结'"
              placement="top"
            >
              <span>
                <el-button
                  link
                  type="warning"
                  size="small"
                  :disabled="!synthesisFor(row)"
                  @click.stop="synthesisFor(row) && viewReport(synthesisFor(row)!.id)"
                >查看归纳</el-button>
              </span>
            </el-tooltip>
            <el-button link type="info" size="small" @click.stop="openTasks(row.id)">任务</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 报告查看抽屉（AI分析 / 综合分析 / 讨论） -->
    <el-drawer v-model="reportDlg" :title="report?.title || '报告'" size="58%">
      <div v-if="report">
        <el-descriptions :column="3" border size="small" style="margin-bottom: 8px">
          <el-descriptions-item label="股票">{{ report.ts_code }}</el-descriptions-item>
          <el-descriptions-item label="截止日期">{{ report.as_of_date }}</el-descriptions-item>
          <el-descriptions-item label="评分">
            <el-rate :model-value="report.structured?.score ?? 0" disabled />
          </el-descriptions-item>
        </el-descriptions>
        <el-tabs v-model="reportTab">
          <el-tab-pane label="AI分析" name="ai">
            <el-card v-if="report.structured" shadow="never" class="struct-card">
              <div>看多：{{ (report.structured.bullish_points || []).join('；') || '—' }}</div>
              <div>看空：{{ (report.structured.bearish_points || []).join('；') || '—' }}</div>
              <div>支撑：{{ (report.structured.key_levels?.support || []).join(' / ') || '—' }}；
                压力：{{ (report.structured.key_levels?.resistance || []).join(' / ') || '—' }}</div>
            </el-card>
            <div class="md-body" v-html="md2html(report.content)" />
          </el-tab-pane>
          <el-tab-pane :label="discussion.merged_content ? '综合分析（人机融合）' : '综合分析（未生成）'"
                       name="merged" :disabled="!discussion.merged_content">
            <div v-if="discussion.merged_content">
              <div class="hint3">融合原始AI报告与你的讨论观点 · 更新于 {{ discussion.merged_updated_at }}</div>
              <div class="md-body" v-html="md2html(discussion.merged_content)" />
            </div>
          </el-tab-pane>
          <el-tab-pane :label="`讨论（${discussion.messages.length}）`" name="discuss">
            <div class="chat-list">
              <el-empty v-if="!discussion.messages.length"
                        description="还没有讨论——在下方发言，提出你的判断或质疑，AI会回应并自动融合进综合分析" :image-size="60" />
              <div v-for="m in discussion.messages" :key="m.id"
                   class="chat-msg" :class="m.role">
                <div class="bubble">
                  <div class="md-body" v-html="md2html(m.content)" />
                  <div class="msg-time">{{ m.created_at }}</div>
                </div>
              </div>
            </div>
            <div class="chat-input">
              <el-input v-model="chatInput" type="textarea" :rows="2" maxlength="2000"
                        placeholder="输入你的判断/质疑/问题，如：我认为支撑位10.5过于乐观，因为…（Enter 发送，Shift+Enter 换行）"
                        @keydown.enter.exact.prevent="sendChat" />
              <el-button type="primary" :loading="chatLoading" style="margin-top: 8px"
                         @click="sendChat">发送</el-button>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <!-- 该报告的监控任务抽屉 -->
    <el-drawer v-model="tasksDlg" :title="`报告 #${tasksReportId} 的监控任务`" size="46%">
      <div class="tasks-toolbar">
        <el-button size="small" @click="openTasks(tasksReportId)">刷新</el-button>
        <el-button size="small" type="primary" plain @click="verifyTasks">手动核验</el-button>
        <span class="hint">任务由本报告自动创建；每日 17:30 自动核验，触发后标记到该股K线</span>
      </div>
      <el-empty v-if="!tasksList.length" description="该报告没有创建监控任务" :image-size="70" />
      <el-card v-for="t in tasksList" :key="t.id" shadow="never" class="task-card">
        <div class="task-head">
          <el-tag size="small" :type="t.status === 'waiting' ? 'primary' : t.status === 'triggered' ? 'warning' : 'info'">
            {{ statusLabel(t.status) }}
          </el-tag>
          <el-tag size="small" type="info">{{ t.task_type }}</el-tag>
          <span v-if="t.expire_date" class="lbl">到期 {{ t.expire_date }}</span>
        </div>
        <div class="task-line"><span class="lbl">条件</span>{{ condText(t) }}</div>
        <div class="task-line"><span class="lbl">预期</span>{{ expectText(t) }}</div>
        <div v-if="t.trigger_date" class="task-line">
          <span class="lbl">触发</span>{{ t.trigger_date }} {{ t.trigger_detail || '' }}
        </div>
        <div v-if="t.status === 'waiting'" class="task-foot">
          <span />
          <el-button link type="danger" size="small" @click="cancelTask(t.id)">取消任务</el-button>
        </div>
      </el-card>
    </el-drawer>

    <!-- 对比对话框 -->
    <el-dialog v-model="diffDlg" title="报告对比" width="70%">
      <template v-if="diff">
        <el-row :gutter="12" style="margin-bottom: 12px">
          <el-col :span="8">
            <el-card shadow="never" class="mini"><div class="mini-lbl">评分变化</div>
              <b :class="diff.score_delta >= 0 ? 'up' : 'down'">
                {{ diff.a.structured?.score ?? '-' }} → {{ diff.b.structured?.score ?? '-' }}
                ({{ diff.score_delta >= 0 ? '+' : '' }}{{ diff.score_delta }})
              </b></el-card>
          </el-col>
          <el-col :span="16">
            <el-card shadow="never" class="mini">
              <div class="mini-lbl">多空观点新增</div>
              <div class="new-points">
                <div v-for="(p, i) in diff.bullish_new" :key="'b' + i" class="up">▲ 新增多头：{{ p }}</div>
                <div v-for="(p, i) in diff.bearish_new" :key="'s' + i" class="down">▼ 新增空头：{{ p }}</div>
                <span v-if="!diff.bullish_new.length && !diff.bearish_new.length">无新增观点</span>
              </div>
            </el-card>
          </el-col>
        </el-row>
        <h4>关键价位对照</h4>
        <el-table size="small" border>
          <el-table-column label="报告A" :formatter="() => reportLabel(diff!.a)" />
          <el-table-column label="报告B" :formatter="() => reportLabel(diff!.b)" />
          <el-table-column label="支撑位">
            <template #default>
              A: {{ levelsText(diff.key_levels_a.support) }}<br />B: {{ levelsText(diff.key_levels_b.support) }}
            </template>
          </el-table-column>
          <el-table-column label="压力位">
            <template #default>
              A: {{ levelsText(diff.key_levels_a.resistance) }}<br />B: {{ levelsText(diff.key_levels_b.resistance) }}
            </template>
          </el-table-column>
        </el-table>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cancelWatchTask, deleteReport, diffReports, getDiscussion, getReport, listAllReports,
  listWatchTasks, postDiscussion, searchStocks, streamAnalysis, streamSynthesis, verifyWatchTasks,
  type ReportDetail, type ReportDiff, type ReportListItem, type StockInfo, type WatchTask,
} from '../api'
import { md2html } from '../md'

interface Section { role: string; title: string; content: string }

const tsCode = ref('')
const searching = ref(false)
const options = ref<StockInfo[]>([])

const generating = ref(false)
const synthesising = ref(false)
const stage = ref('')
const sections = ref<Section[]>([])

const reports = ref<ReportListItem[]>([])
const filterCode = ref('')
const filterName = ref('')
const companyReports = computed(() =>
  reports.value.filter(r =>
    r.report_type === 'company'
    && (!filterCode.value || (r.ts_code ?? '').toLowerCase().includes(filterCode.value.toLowerCase()))
    && (!filterName.value || (r.stock_name ?? '').includes(filterName.value)
        || (r.title ?? '').includes(filterName.value)),
  ),
)

/** 该股最新的归纳总结报告（列表按 id 降序，取第一条命中） */
const synthesisFor = (row: ReportListItem): ReportListItem | undefined =>
  reports.value.find(r => r.report_type === 'synthesis' && r.ts_code === row.ts_code)
const picked = ref<ReportListItem[]>([])
const reportDlg = ref(false)
const report = ref<ReportDetail | null>(null)
const diffDlg = ref(false)
const diff = ref<ReportDiff | null>(null)

const STAGES = ['gathering', 'modeling', 'technical', 'fundamental', 'sentiment', 'chief', 'verifying', 'updating', 'done']
const stageLabel = computed(() => stage.value || '未开始')
const stageProgress = computed(() => {
  const i = STAGES.indexOf(stage.value)
  return i < 0 ? 0 : Math.round(((i + 1) / STAGES.length) * 100)
})

const doSearch = async (q: string) => {
  if (!q) { options.value = []; return }
  searching.value = true
  try { options.value = await searchStocks(q) } finally { searching.value = false }
}

const handleEvent = (event: string, data: unknown) => {
  const d = data as Record<string, unknown>
  if (event === 'status') {
    stage.value = String(d.stage ?? '')
  } else if (event === 'section') {
    const role = String(d.role ?? '')
    const title = String(d.title ?? '')
    const content = String(d.content ?? '')
    const found = sections.value.find(s => s.role === role)
    if (found) { found.title = title; found.content += content }
    else sections.value.push({ role, title, content })
  } else if (event === 'done') {
    const d2 = d as { report_id?: number; watch_tasks?: unknown[]; data_issues?: string[]; company_updated?: boolean }
    let msg = `报告 #${d2.report_id} 已入库`
    if (d2.data_issues && d2.data_issues.length) {
      msg += `；发现 ${d2.data_issues.length} 项数据问题：${d2.data_issues.slice(0, 3).join('；')}`
    }
    if (d2.company_updated) msg += '；已自动更新公司分析报告'
    ElMessage.success(msg)
    stage.value = 'done'
    void loadReports()
  } else if (event === 'error') {
    ElMessage.error(`生成失败: ${String(d.msg ?? '未知错误')}`)
  }
}

const generate = async () => {
  if (!tsCode.value) return
  generating.value = true
  sections.value = []
  stage.value = ''
  try {
    await streamAnalysis(tsCode.value, handleEvent)
  } catch (e) {
    ElMessage.error(`请求失败: ${(e as Error).message}`)
  } finally {
    generating.value = false
  }
}

const synthesis = async () => {
  if (!tsCode.value) return
  synthesising.value = true
  sections.value = []
  stage.value = ''
  try {
    await streamSynthesis(tsCode.value, handleEvent)
  } catch (e) {
    ElMessage.error(`请求失败: ${(e as Error).message}`)
  } finally {
    synthesising.value = false
  }
}

const loadReports = async () => {
  try {
    reports.value = await listAllReports()
  } catch (e) {
    ElMessage.error(`加载报告列表失败: ${(e as Error).message}`)
  }
}

const viewReport = async (id: number) => {
  try {
    report.value = await getReport(id)
    reportDlg.value = true
    reportTab.value = 'ai'
    // 加载讨论与综合分析
    try {
      const d = await getDiscussion(id)
      discussion.value = d
    } catch {
      discussion.value = { messages: [], merged_content: null, merged_updated_at: null }
    }
  } catch (e) {
    ElMessage.error(`加载报告失败: ${(e as Error).message}`)
  }
}

// ---------- 报告讨论（用户观点收集 → 自动融合综合分析） ----------
const reportTab = ref<'ai' | 'merged' | 'discuss'>('ai')
const discussion = ref<{ messages: { id: number; role: string; content: string; created_at: string }[]; merged_content: string | null; merged_updated_at: string | null }>({ messages: [], merged_content: null, merged_updated_at: null })
const chatInput = ref('')
const chatLoading = ref(false)

const sendChat = async () => {
  if (!report.value || !chatInput.value.trim() || chatLoading.value) return
  chatLoading.value = true
  const text = chatInput.value.trim()
  chatInput.value = ''
  // 乐观追加用户消息
  discussion.value.messages.push({ id: Date.now(), role: 'user', content: text, created_at: '刚刚' })
  try {
    const r = await postDiscussion(report.value.id, text)
    discussion.value.messages.push({ id: Date.now() + 1, role: 'assistant', content: r.reply, created_at: '刚刚' })
    discussion.value.merged_content = r.merged_content
    discussion.value.merged_updated_at = r.merged_updated_at
    if (r.merged_content) {
      ElMessage.success('AI已回应，综合分析已自动更新')
      reportTab.value = 'merged'
    }
  } catch (e) {
    ElMessage.error(`发送失败: ${(e as Error).message}`)
    discussion.value.messages = discussion.value.messages.filter(m => m.content !== text)
    chatInput.value = text
  } finally {
    chatLoading.value = false
  }
}

const doDiff = async () => {
  if (picked.value.length !== 2) return
  try {
    diff.value = await diffReports(picked.value[0].id, picked.value[1].id)
    diffDlg.value = true
  } catch (e) {
    ElMessage.error(`对比失败: ${(e as Error).message}`)
  }
}

const deletePicked = async () => {
  if (!picked.value.length) return
  try {
    await ElMessageBox.confirm(
      `确认删除选中的 ${picked.value.length} 份报告？其关联的观察任务与版本链记录将一并删除。`,
      '删除确认', { type: 'warning' },
    )
  } catch { return }
  let ok = 0
  for (const r of picked.value) {
    try {
      await deleteReport(r.id)
      ok++
    } catch (e) {
      ElMessage.error(`删除报告 #${r.id} 失败: ${(e as Error).message}`)
    }
  }
  if (ok) ElMessage.success(`已删除 ${ok} 份报告`)
  await loadReports()
}

const reportLabel = (r: ReportDetail) => `${r.as_of_date} ${r.title}`

// ---------- 报告监控任务 ----------
const tasksDlg = ref(false)
const tasksReportId = ref(0)
const tasksList = ref<WatchTask[]>([])

const statusLabel = (s: string) =>
  s === 'waiting' ? '等待' : s === 'triggered' ? '已触发' : s === 'cancelled' ? '已取消' : '已过期'

const pretty = (v: unknown): string => {
  if (v == null) return '—'
  if (typeof v === 'string') return v
  try { return JSON.stringify(v) } catch { return String(v) }
}

const condText = (t: WatchTask) => {
  const c = t.condition_json as Record<string, unknown> | null
  if (c && typeof c === 'object' && !Array.isArray(c)) {
    const parts = Object.entries(c).map(([k, v]) => `${k}=${pretty(v)}`)
    if (parts.length) return parts.join(' ')
  }
  return pretty(t.condition_json)
}

const expectText = (t: WatchTask) => {
  const e = t.expect_json as Record<string, unknown> | null
  if (e && typeof e === 'object' && !Array.isArray(e) && typeof e.expect === 'string') return e.expect
  return pretty(t.expect_json)
}

const openTasks = async (reportId: number) => {
  tasksReportId.value = reportId
  try {
    const r = await listWatchTasks({ source_report_id: reportId, page_size: 100 })
    tasksList.value = r.items
  } catch (e) {
    ElMessage.error(`加载任务失败: ${(e as Error).message}`)
  }
  tasksDlg.value = true
}

const cancelTask = async (id: number) => {
  try {
    await cancelWatchTask(id)
    ElMessage.success('已取消')
    await openTasks(tasksReportId.value)
    tasksDlg.value = true
  } catch (e) {
    ElMessage.error(`取消失败: ${(e as Error).message}`)
  }
}

const verifyTasks = async () => {
  try {
    await verifyWatchTasks()
    ElMessage.success('核验已提交后台执行，稍后点「刷新」')
  } catch (e) {
    ElMessage.error(`触发核验失败: ${(e as Error).message}`)
  }
}
const levelsText = (arr: number[] | undefined) => (arr ?? []).join(' / ') || '—'

onMounted(() => { void loadReports() })
</script>

<style scoped>
.analysis { display: flex; flex-direction: column; gap: 12px; }
.filter-row { display: flex; gap: 12px; margin-bottom: 10px; }
.hint3 { color: #909399; font-size: 12px; margin-bottom: 8px; }
.chat-list { display: flex; flex-direction: column; gap: 10px; max-height: 46vh; overflow-y: auto; padding: 4px; }
.chat-msg { display: flex; }
.chat-msg.user { justify-content: flex-end; }
.chat-msg .bubble { max-width: 86%; padding: 8px 12px; border-radius: 8px; background: #f4f4f5; }
.chat-msg.user .bubble { background: #ecf5ff; }
.msg-time { color: #c0c4cc; font-size: 11px; margin-top: 4px; text-align: right; }
.chat-input { margin-top: 10px; display: flex; flex-direction: column; align-items: flex-end; }
.tasks-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.tasks-toolbar .hint { color: #c0c4cc; font-size: 12px; }
.task-card { margin-bottom: 10px; }
.task-card :deep(.el-card__body) { padding: 10px 12px; }
.task-head { display: flex; gap: 8px; align-items: center; margin-bottom: 6px; }
.task-line { font-size: 13px; margin: 3px 0; word-break: break-all; }
.task-line .lbl { color: #909399; margin-right: 6px; }
.task-foot { display: flex; justify-content: flex-end; margin-top: 6px; }
.lbl { color: #909399; font-size: 12px; }
.toolbar { display: flex; align-items: center; gap: 12px; }
.progress-card .progress-row { display: flex; align-items: center; gap: 16px; }
.section-card { margin-bottom: 12px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.md-body :deep(h1), .md-body :deep(h2), .md-body :deep(h3), .md-body :deep(h4) { margin: 10px 0 6px; }
.md-body :deep(p) { margin: 6px 0; line-height: 1.7; }
.md-body :deep(code) { background: #f4f4f5; padding: 1px 5px; border-radius: 3px; font-family: Consolas, monospace; }
.md-body :deep(pre) { background: #282c34; color: #abb2bf; padding: 12px; border-radius: 6px; overflow-x: auto; }
.md-body :deep(pre code) { background: none; color: inherit; padding: 0; }
.md-body :deep(blockquote) { border-left: 4px solid #dcdfe6; margin: 6px 0; padding: 4px 12px; color: #909399; }
.mini { text-align: center; }
.mini .mini-lbl { color: #909399; font-size: 12px; margin-bottom: 4px; }
.new-points { text-align: left; font-size: 13px; }
.struct-card { margin-bottom: 12px; font-size: 13px; }
.struct-card div { margin: 4px 0; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
</style>
