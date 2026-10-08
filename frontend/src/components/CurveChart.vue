<template>
  <div class="curve-chart" ref="wrapRef">
    <div v-if="series.length > 1" class="legend">
      <span v-for="s in series" :key="s.name" class="legend-item">
        <i :style="{ background: s.color }" /> {{ s.name }}
      </span>
    </div>
    <svg :viewBox="`0 0 ${W} ${H}`" class="svg" @mousemove="onMove" @mouseleave="hover = null">
      <!-- 横向网格 + Y轴刻度 -->
      <g v-for="(tick, i) in yTicks" :key="'y' + i">
        <line :x1="PAD_L" :x2="W - PAD_R" :y1="yPos(tick)" :y2="yPos(tick)"
              stroke="#e4e7ed" stroke-dasharray="3,3" />
        <text :x="PAD_L - 6" :y="yPos(tick) + 3" text-anchor="end" class="tick">{{ fmtTick(tick) }}</text>
      </g>
      <!-- 零轴 -->
      <line v-if="0 >= minV && 0 <= maxV" :x1="PAD_L" :x2="W - PAD_R"
            :y1="yPos(0)" :y2="yPos(0)" stroke="#909399" />
      <!-- X轴刻度 -->
      <text v-for="(t, i) in xTicks" :key="'x' + i"
            :x="PAD_L + (W - PAD_L - PAD_R) * (i / (xTicks.length - 1))"
            :y="H - 6" :text-anchor="i === 0 ? 'start' : i === xTicks.length - 1 ? 'end' : 'middle'"
            class="tick">{{ t }}</text>
      <!-- 曲线 -->
      <polyline v-for="s in series" :key="'l' + s.name"
                :points="polyPoints(s)" fill="none"
                :stroke="s.color || '#409eff'" stroke-width="1.5" />
      <!-- 交易点标记（红=买 绿=卖），标注在对应序列曲线上 -->
      <template v-for="(m, i) in markerPoints" :key="'m' + i">
        <circle :cx="m.x" :cy="m.y" r="3.5"
                :fill="m.side === 'buy' ? '#f56c6c' : '#67c23a'"
                stroke="#fff" stroke-width="1" />
        <text :x="m.x" :y="m.side === 'buy' ? m.y - 7 : m.y + 13" text-anchor="middle" class="mark">
          {{ m.side === 'buy' ? 'B' : 'S' }}
        </text>
      </template>
      <!-- 悬浮十字线 + 高亮点 -->
      <template v-if="hover">
        <line :x1="hover.xSvg" :x2="hover.xSvg" :y1="PAD_T" :y2="H - PAD_B"
              stroke="#c0c4cc" stroke-dasharray="4,3" />
        <circle v-for="p in hover.points" :key="'h' + p.name"
                :cx="hover.xSvg" :cy="p.y" r="4"
                :fill="p.color" stroke="#fff" stroke-width="1.5" />
      </template>
    </svg>
    <!-- 跟随数据框 -->
    <div v-if="hover" class="tooltip" :style="{ left: hover.tx + 'px', top: hover.ty + 'px' }">
      <div class="tt-date">{{ hover.date }}</div>
      <div v-for="p in hover.points" :key="'tt' + p.name" class="tt-row">
        <i :style="{ background: p.color }" />
        <span class="tt-name">{{ p.name }}</span>
        <b :class="p.pct >= 0 ? 'up' : 'down'">{{ p.pct >= 0 ? '+' : '' }}{{ p.pct.toFixed(2) }}%</b>
        <span class="tt-eq">（{{ p.equity.toLocaleString('zh-CN', { maximumFractionDigits: 0 }) }}）</span>
      </div>
      <div v-if="hover.trade" class="tt-trade">
        当日交易：{{ hover.trade.side === 'buy' ? '🔴 买入' : '🟢 卖出' }}
        {{ hover.trade.qty }} 股 @{{ hover.trade.price }}
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import type { CurveMarker, CurveSeries, TradeRecord } from '../api'

const props = defineProps<{
  series: CurveSeries[]
  markers?: CurveMarker[]
  trades?: TradeRecord[]
}>()

const W = 920
const H = 280
const PAD_L = 64
const PAD_R = 16
const PAD_T = 12
const PAD_B = 24

const COLORS = ['#409eff', '#e6a23c', '#67c23a', '#f56c6c', '#9c27b0', '#00bcd4']

const wrapRef = ref<HTMLDivElement>()
const hover = ref<{
  xSvg: number
  date: string
  points: { name: string; color: string; y: number; pct: number; equity: number }[]
  trade?: { side: string; qty: number; price: number }
  tx: number
  ty: number
} | null>(null)

const pctOf = (s: CurveSeries) =>
  s.data.map(p => (s.initialCash ? (p.equity / s.initialCash - 1) * 100 : 0))

const allPcts = computed(() => props.series.flatMap(pctOf))
const minV = computed(() => (allPcts.value.length ? Math.min(0, ...allPcts.value) : 0))
const maxV = computed(() => (allPcts.value.length ? Math.max(0, ...allPcts.value) : 1))

const yPos = (v: number) => {
  const span = maxV.value - minV.value || 1
  return PAD_T + (H - PAD_T - PAD_B) * (1 - (v - minV.value) / span)
}

const yTicks = computed(() => {
  const span = maxV.value - minV.value
  const step = span / 4 || 1
  return Array.from({ length: 5 }, (_, i) => minV.value + step * i)
})

const fmtTick = (v: number) => `${v.toFixed(1)}%`

const longest = computed(() =>
  props.series.reduce((a, b) => (b.data.length > a.data.length ? b : a),
    { name: '', data: [] as { date: string; equity: number }[], initialCash: 1 }))

const xTicks = computed(() => {
  const n = longest.value.data.length
  if (!n) return ['']
  const idx = [0, Math.floor(n * 0.25), Math.floor(n * 0.5), Math.floor(n * 0.75), n - 1]
  return [...new Set(idx)].map(i => longest.value.data[i].date.slice(0, 10))
})

const polyPoints = (s: CurveSeries) => {
  const pcts = pctOf(s)
  const n = pcts.length
  if (n < 2) return ''
  return pcts
    .map((v, i) => `${PAD_L + ((W - PAD_L - PAD_R) * i) / (n - 1)},${yPos(v)}`)
    .join(' ')
}

/** 交易点标记：定位到第一条序列曲线上对应日期的位置 */
const markerPoints = computed(() => {
  const out: { x: number; y: number; side: string }[] = []
  const s = props.series[0]
  if (!s || !props.markers?.length || s.data.length < 2) return out
  const pcts = pctOf(s)
  const n = s.data.length
  const dateIdx = new Map<string, number>()
  s.data.forEach((p, i) => dateIdx.set(p.date.slice(0, 10), i))
  for (const m of props.markers) {
    const i = dateIdx.get(String(m.date).slice(0, 10))
    if (i == null) continue
    out.push({
      x: PAD_L + ((W - PAD_L - PAD_R) * i) / (n - 1),
      y: yPos(pcts[i]),
      side: m.side,
    })
  }
  return out
})

const onMove = (e: MouseEvent) => {
  const svg = e.currentTarget as SVGSVGElement
  const rect = svg.getBoundingClientRect()
  const xSvg = ((e.clientX - rect.left) / rect.width) * W
  const nLong = longest.value.data.length
  if (nLong < 2) return
  const f = Math.min(1, Math.max(0, (xSvg - PAD_L) / (W - PAD_L - PAD_R)))
  const iLong = Math.round(f * (nLong - 1))
  const date = longest.value.data[iLong].date.slice(0, 10)

  const points = props.series.map((s, idx) => {
    const i = Math.min(s.data.length - 1, Math.round(f * Math.max(0, s.data.length - 1)))
    const p = s.data[i]
    return {
      name: s.name,
      color: s.color || COLORS[idx % COLORS.length],
      y: yPos(pctOf(s)[i]),
      pct: s.initialCash ? (p.equity / s.initialCash - 1) * 100 : 0,
      equity: p.equity,
    }
  })

  const trade = (props.trades ?? []).find(t => String(t.trade_date).slice(0, 10) === date)

  // tooltip 定位：跟随鼠标，超出右半时翻转到左侧
  const wrapRect = wrapRef.value?.getBoundingClientRect()
  const relX = e.clientX - (wrapRect?.left ?? 0)
  const relY = e.clientY - (wrapRect?.top ?? 0)
  const tx = relX > (wrapRect?.width ?? 600) / 2 ? relX - 190 : relX + 14

  hover.value = {
    xSvg: PAD_L + ((W - PAD_L - PAD_R) * iLong) / (nLong - 1),
    date,
    points,
    trade: trade ? { side: trade.side, qty: trade.qty, price: Number(trade.price) } : undefined,
    tx,
    ty: Math.max(0, relY - 20),
  }
}

// 序列无色时按序分配
props.series.forEach((s, i) => { if (!s.color) s.color = COLORS[i % COLORS.length] })
</script>

<style scoped>
.curve-chart { width: 100%; position: relative; }
.legend { display: flex; gap: 16px; margin-bottom: 4px; flex-wrap: wrap; }
.legend-item { font-size: 12px; color: #606266; display: inline-flex; align-items: center; gap: 4px; }
.legend-item i { width: 14px; height: 3px; display: inline-block; }
.svg { width: 100%; height: auto; }
.tick { font-size: 10px; fill: #909399; }
.mark { font-size: 9px; font-weight: 700; fill: #606266; }
.tooltip {
  position: absolute; z-index: 10; pointer-events: none;
  background: rgba(255, 255, 255, 0.96); border: 1px solid #dcdfe6; border-radius: 6px;
  padding: 8px 10px; box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
  min-width: 170px; font-size: 12px;
}
.tt-date { font-weight: 700; margin-bottom: 4px; color: #303133; }
.tt-row { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
.tt-row i { width: 10px; height: 3px; display: inline-block; flex-shrink: 0; }
.tt-name { color: #606266; max-width: 110px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.tt-eq { color: #909399; font-size: 11px; }
.tt-trade { margin-top: 4px; padding-top: 4px; border-top: 1px dashed #e4e7ed; color: #606266; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
</style>
