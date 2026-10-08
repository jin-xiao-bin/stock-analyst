<template>
  <div class="watch">
    <el-card shadow="never" class="toolbar">
      <el-input v-model="filterTs" placeholder="按代码筛选，如 000001.SZ" clearable style="width: 220px" @input="loadAll" />
      <el-button @click="loadAll">刷新</el-button>
      <el-button type="primary" plain :loading="verifying" @click="verifyNow">手动触发核验</el-button>
      <span class="hint">任务由分析报告自动创建；每日 17:30 自动核验，触发后标记到对应股票K线；点击股票卡片查看其任务明细</span>
    </el-card>

    <!-- 股票维度汇总卡片 -->
    <el-card shadow="never">
      <template #header>
        <span>按股票分组（点击查看该股任务明细）</span>
        <el-tag size="small" style="float: right">{{ stockGroups.length }} 只股票</el-tag>
      </template>
      <el-empty v-if="!stockGroups.length" description="暂无任务" :image-size="70" />
      <el-row v-else :gutter="12">
        <el-col v-for="g in stockGroups" :key="g.ts_code" :span="8" style="margin-bottom: 12px">
          <el-card shadow="hover" class="stock-card" @click="openStock(g.ts_code)">
            <div class="stock-head">
              <b>{{ g.ts_code }}</b>
              <el-tag v-if="g.waiting" type="primary" size="small">待触发 {{ g.waiting }}</el-tag>
            </div>
            <div class="stock-stats">
              <span class="w"><i class="dot waiting" />等待 {{ g.waiting }}</span>
              <span class="w"><i class="dot triggered" />已触发 {{ g.triggered }}</span>
              <span class="w"><i class="dot closed" />关闭 {{ g.closed }}</span>
            </div>
            <div class="stock-preview">
              {{ g.preview }}
            </div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <!-- 个股任务明细抽屉 -->
    <el-drawer v-model="drawer" :title="`${selected} · 观察任务明细`" size="55%">
      <template v-for="sec in sections" :key="sec.key">
        <h4 class="sec-title" :class="sec.key">{{ sec.title }}（{{ sec.items.length }}）</h4>
        <el-empty v-if="!sec.items.length" description="无" :image-size="40" />
        <el-card v-for="t in sec.items" :key="t.id" shadow="never" class="task-card">
          <div class="task-head">
            <el-tag size="small" type="info">{{ t.task_type }}</el-tag>
            <span v-if="t.expire_date" class="lbl">到期 {{ t.expire_date }}</span>
          </div>
          <div class="task-line"><span class="lbl">条件</span>{{ condText(t) }}</div>
          <div class="task-line"><span class="lbl">预期</span>{{ expectText(t) }}</div>
          <div v-if="t.trigger_date" class="task-line">
            <span class="lbl">触发</span>{{ t.trigger_date }} {{ t.trigger_detail || '' }}
          </div>
          <div class="task-foot">
            <router-link v-if="t.source_report_id" :to="`/analysis?report=${t.source_report_id}`" class="link">
              来源报告 #{{ t.source_report_id }}
            </router-link>
            <span v-else class="lbl">无来源</span>
            <el-button v-if="t.status === 'waiting'" link type="danger" size="small" @click="cancel(t.id)">
              取消
            </el-button>
          </div>
        </el-card>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { cancelWatchTask, listWatchTasks, verifyWatchTasks, type WatchTask } from '../api'

const filterTs = ref('')
const tasks = ref<WatchTask[]>([])
const verifying = ref(false)
const loading = ref(false)

const drawer = ref(false)
const selected = ref('')

interface StockGroup {
  ts_code: string
  waiting: number
  triggered: number
  closed: number
  preview: string
}

const stockGroups = computed<StockGroup[]>(() => {
  const map = new Map<string, WatchTask[]>()
  for (const t of tasks.value) {
    const arr = map.get(t.ts_code) || []
    arr.push(t)
    map.set(t.ts_code, arr)
  }
  const groups: StockGroup[] = []
  for (const [ts_code, arr] of map) {
    const waiting = arr.filter(t => t.status === 'waiting').length
    groups.push({
      ts_code,
      waiting,
      triggered: arr.filter(t => t.status === 'triggered').length,
      closed: arr.filter(t => t.status === 'expired' || t.status === 'cancelled').length,
      preview: firstWaitingText(arr),
    })
  }
  return groups.sort((a, b) => b.waiting - a.waiting || b.triggered - a.triggered)
})

const firstWaitingText = (arr: WatchTask[]): string => {
  const w = arr.find(t => t.status === 'waiting')
  if (!w) {
    const any = arr[0]
    return any ? `最近任务：${condText(any).slice(0, 60)}` : ''
  }
  return `最近待触发：${condText(w).slice(0, 60)}`
}

const tasksForStock = computed(() =>
  selected.value ? tasks.value.filter(t => t.ts_code === selected.value) : [],
)

const sections = computed(() => [
  { key: 'waiting', title: '等待触发', items: tasksForStock.value.filter(t => t.status === 'waiting') },
  { key: 'triggered', title: '已触发', items: tasksForStock.value.filter(t => t.status === 'triggered') },
  {
    key: 'closed',
    title: '已过期/已取消',
    items: tasksForStock.value.filter(t => t.status === 'expired' || t.status === 'cancelled'),
  },
])

const openStock = (tsCode: string) => {
  selected.value = tsCode
  drawer.value = true
}

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
  if (e && typeof e === 'object' && !Array.isArray(e)) {
    if (typeof e.expect === 'string') return e.expect
    const parts = Object.entries(e).map(([k, v]) => `${k}=${pretty(v)}`)
    if (parts.length) return parts.join(' ')
  }
  return pretty(t.expect_json)
}

const loadAll = async () => {
  loading.value = true
  try {
    let page = 1
    let total = Infinity
    const items: WatchTask[] = []
    while (items.length < total) {
      const r = await listWatchTasks({ ts_code: filterTs.value || undefined, page, page_size: 100 })
      total = r.total
      items.push(...r.items)
      if (r.items.length === 0) break
      page++
    }
    tasks.value = items
  } catch (e) {
    ElMessage.error(`加载任务失败: ${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

const cancel = async (id: number) => {
  try {
    await cancelWatchTask(id)
    ElMessage.success('已取消')
    await loadAll()
  } catch (e) {
    ElMessage.error(`取消失败: ${(e as Error).message}`)
  }
}

const verifyNow = async () => {
  verifying.value = true
  try {
    await verifyWatchTasks()
    ElMessage.success('核验已触发（后台异步执行），稍后点「刷新」查看结果')
  } catch (e) {
    ElMessage.error(`触发核验失败: ${(e as Error).message}`)
  } finally {
    verifying.value = false
  }
}

onMounted(() => void loadAll())
</script>

<style scoped>
.watch { display: flex; flex-direction: column; gap: 12px; }
.toolbar { display: flex; align-items: center; gap: 12px; }
.hint { color: #c0c4cc; font-size: 12px; }
.stock-card { cursor: pointer; }
.stock-card :deep(.el-card__body) { padding: 12px 14px; }
.stock-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.stock-stats { display: flex; gap: 14px; font-size: 13px; color: #606266; margin-bottom: 8px; }
.stock-stats .w { display: inline-flex; align-items: center; gap: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.waiting { background: #409eff; }
.dot.triggered { background: #e6a23c; }
.dot.closed { background: #c0c4cc; }
.stock-preview { color: #909399; font-size: 12px; word-break: break-all; }
.sec-title { margin: 14px 0 8px; }
.sec-title.waiting { color: #409eff; }
.sec-title.triggered { color: #e6a23c; }
.sec-title.closed { color: #909399; }
.task-card { margin-bottom: 10px; }
.task-card :deep(.el-card__body) { padding: 10px 12px; }
.task-head { display: flex; justify-content: space-between; margin-bottom: 6px; }
.task-line { font-size: 13px; margin: 3px 0; word-break: break-all; }
.task-line .lbl { color: #909399; margin-right: 6px; }
.task-foot { display: flex; justify-content: space-between; align-items: center; margin-top: 8px; }
.link { color: #409eff; font-size: 13px; text-decoration: none; }
.lbl { color: #909399; font-size: 12px; }
</style>
