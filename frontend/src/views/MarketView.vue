<template>
  <div class="market">
    <RealtimeQuoteBar v-if="selected" :ts-code="selected" />
    <el-card shadow="never" class="toolbar">
      <el-select
        v-model="selected"
        filterable
        remote
        clearable
        placeholder="输入代码/名称搜索，如 000001 或 平安银行"
        :remote-method="doSearch"
        :loading="searching"
        style="width: 360px"
        @change="loadChart"
      >
        <el-option
          v-for="s in options"
          :key="s.ts_code"
          :label="`${s.name} (${s.ts_code})`"
          :value="s.ts_code"
        />
      </el-select>
      <el-radio-group v-model="adjust" @change="loadChart">
        <el-radio-button value="qfq">前复权</el-radio-button>
        <el-radio-button value="hfq">后复权</el-radio-button>
        <el-radio-button value="none">不复权</el-radio-button>
      </el-radio-group>
      <el-button :loading="loading" @click="loadChart">刷新</el-button>
      <span v-if="currentStock" class="stock-title">
        {{ currentStock.name }} · {{ currentStock.ts_code }}
        <el-tag v-if="currentStock.industry" size="small">{{ currentStock.industry }}</el-tag>
      </span>
    </el-card>

    <el-card shadow="never" class="chart-card">
      <div ref="chartRef" class="chart" />
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { init, dispose, type Chart } from 'klinecharts'
import RealtimeQuoteBar from '../components/RealtimeQuoteBar.vue'
import { api, getDaily, searchStocks, type StockInfo } from '../api'

const selected = ref('')
const adjust = ref('qfq')
const options = ref<StockInfo[]>([])
const currentStock = ref<StockInfo | null>(null)
const searching = ref(false)
const loading = ref(false)
const chartRef = ref<HTMLDivElement>()
let chart: Chart | null = null

const doSearch = async (q: string) => {
  if (!q) { options.value = []; return }
  searching.value = true
  try {
    options.value = await searchStocks(q)
  } finally {
    searching.value = false
  }
}

const loadChart = async () => {
  if (!selected.value || !chart) return
  loading.value = true
  try {
    const bars = await getDaily(selected.value, adjust.value)
    chart.applyNewData(
      bars.map(b => ({
        timestamp: new Date(b.date + 'T00:00:00').getTime(),
        open: Number(b.open), high: Number(b.high), low: Number(b.low), close: Number(b.close),
        volume: Number(b.volume ?? 0),
        turnover: b.amount != null ? Number(b.amount) : undefined,
      })),
    )
    chart.resize()
    currentStock.value = options.value.find(s => s.ts_code === selected.value) ?? null
  } catch (e) {
    ElMessage.error(`加载K线失败: ${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

watch(selected, () => { currentStock.value = options.value.find(s => s.ts_code === selected.value) ?? null })

onMounted(async () => {
  if (chartRef.value) {
    chart = init(chartRef.value)
    if (chart) {
      chart.createIndicator('MA', false, { id: 'candle_pane' })
      chart.createIndicator('VOL')
    }
  }
  // 预置一只股票，开箱即看
  try {
    options.value = await searchStocks('000001.SZ')
    selected.value = '000001.SZ'
    await loadChart()
  } catch { /* ignore */ }
})

onBeforeUnmount(() => {
  if (chartRef.value) dispose(chartRef.value)
})
</script>

<style scoped>
.market { display: flex; flex-direction: column; gap: 12px; }
.toolbar { display: flex; align-items: center; gap: 16px; }
.stock-title { font-size: 16px; font-weight: 600; }
.chart-card { padding: 0; }
.chart { width: 100%; height: 560px; }
</style>
