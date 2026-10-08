<template>
  <div v-if="quote" class="rt-bar" :class="{ closed: isClosed }">
    <template v-if="quote.price != null">
      <b class="rt-name">{{ quote.name || tsCode }}</b>
      <span class="rt-price" :class="(quote.pct_chg ?? 0) >= 0 ? 'up' : 'down'">
        {{ quote.price.toFixed(2) }}
      </span>
      <span class="rt-pct" :class="(quote.pct_chg ?? 0) >= 0 ? 'up' : 'down'">
        {{ (quote.pct_chg ?? 0) >= 0 ? '+' : '' }}{{ quote.pct_chg?.toFixed(2) }}%
      </span>
      <span class="rt-item">开 {{ quote.open?.toFixed(2) ?? '—' }}</span>
      <span class="rt-item">高 {{ quote.high?.toFixed(2) ?? '—' }}</span>
      <span class="rt-item">低 {{ quote.low?.toFixed(2) ?? '—' }}</span>
      <span class="rt-item">昨收 {{ quote.pre_close?.toFixed(2) ?? '—' }}</span>
      <span class="rt-item">量 {{ fmtVol(quote.volume) }}手</span>
      <span class="rt-item">额 {{ fmtVol(quote.amount) }}万</span>
      <span v-if="quote.bid != null" class="rt-item">买一 {{ quote.bid }} / 卖一 {{ quote.ask }}</span>
      <span class="rt-meta">
        {{ isClosed ? '已收盘 ·' : '' }}{{ quote.time || '' }} · {{ sourceLabel }} · {{ status }}
      </span>
    </template>
    <template v-else>
      <span class="rt-meta">实时数据不可用，展示本地收盘数据</span>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api } from '../api'

interface RealtimeQuote {
  name?: string
  price?: number | null
  open?: number | null
  high?: number | null
  low?: number | null
  pre_close?: number | null
  pct_chg?: number | null
  volume?: number | null
  amount?: number | null
  bid?: number | null
  ask?: number | null
  time?: string | null
  source?: string
}

const props = defineProps<{ tsCode: string; intervalMs?: number }>()

const quote = ref<RealtimeQuote | null>(null)
const status = ref('')
let timer: ReturnType<typeof setInterval> | null = null
let loading = false

const sourceLabel = computed(() =>
  quote.value?.source === 'tushare' ? 'Tushare' : quote.value?.source === 'eastmoney' ? '东财' : '')

const isClosed = computed(() => {
  const t = quote.value?.time
  if (!t) return false
  const hm = t.slice(-8, 5)
  return hm >= '15:00' || hm < '09:30'
})

const fmtVol = (v: number | null | undefined) =>
  v == null ? '—' : v >= 10000 ? (v / 10000).toFixed(2) + '万' : Math.round(v).toLocaleString()

const fetchQuote = async () => {
  if (!props.tsCode || loading) return
  loading = true
  try {
    quote.value = await api.get<RealtimeQuote>(`/stocks/${props.tsCode}/realtime`).then(r => r.data)
    status.value = `更新于 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`
  } catch {
    status.value = '获取失败'
  } finally {
    loading = false
  }
}

onMounted(() => {
  void fetchQuote()
  timer = setInterval(fetchQuote, props.intervalMs ?? 5000)
})

onBeforeUnmount(() => { if (timer) clearInterval(timer) })
</script>

<style scoped>
.rt-bar {
  display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap;
  padding: 8px 14px; background: #fff; border: 1px solid #e4e7ed; border-radius: 6px;
  font-size: 13px;
}
.rt-bar.closed { opacity: 0.85; }
.rt-name { font-size: 15px; }
.rt-price { font-size: 22px; font-weight: 700; }
.rt-pct { font-size: 15px; font-weight: 600; }
.rt-item { color: #606266; }
.rt-meta { margin-left: auto; color: #c0c4cc; font-size: 12px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
</style>
