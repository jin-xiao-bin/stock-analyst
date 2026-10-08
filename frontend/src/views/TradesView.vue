<template>
  <div class="trades">
    <!-- 账户复盘卡片（点击即筛选该账户流水） -->
    <el-card shadow="never">
      <template #header>
        <span>账户复盘（点击账户卡片查看其交易）</span>
        <el-button size="small" type="primary" plain style="float: right" @click="addDlg = true">新增账户</el-button>
        <el-button size="small" style="float: right; margin-right: 8px" @click="loadAll">刷新</el-button>
      </template>
      <el-empty v-if="!accounts.length" description="暂无账户" :image-size="60" />
      <el-row v-else :gutter="12">
        <el-col v-for="a in accounts" :key="a.id" :span="6">
          <el-card shadow="hover" class="account-card"
                   :class="{ active: query.account_id === a.id }" @click="pickAccount(a.id)">
            <div class="acc-head">
              <b>{{ a.name }}</b>
              <span>
                <el-tag size="small" type="info">#{{ a.id }} {{ a.mode }}</el-tag>
                <el-button link type="danger" size="small"
                           @click.stop="removeAccount(a)">删除</el-button>
              </span>
            </div>
            <div class="acc-body">
              <span class="acc-num">{{ fmt(a.total_value) }}</span>
              <span :class="a.profit >= 0 ? 'up' : 'down'">
                {{ a.profit >= 0 ? '+' : '' }}{{ a.profit_pct.toFixed(2) }}%
              </span>
            </div>
            <div class="acc-sub">现金 {{ fmt(a.cash) }} · 市值 {{ fmt(a.market_value) }}</div>
          </el-card>
        </el-col>
      </el-row>
    </el-card>

    <!-- 筛选表单 -->
    <el-card shadow="never">
      <el-form :inline="true">
        <el-form-item label="账户">
          <el-select v-model="query.account_id" clearable style="width: 200px" @change="search">
            <el-option v-for="a in accounts" :key="a.id" :label="`${a.name} (#${a.id})`" :value="a.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="代码">
          <el-input v-model="query.ts_code" placeholder="000001.SZ" clearable style="width: 150px" @change="search" />
        </el-form-item>
        <el-form-item label="来源">
          <el-select v-model="query.source" clearable style="width: 130px" @change="search">
            <el-option label="手动下单" value="manual" />
            <el-option label="回放策略" value="strategy" />
            <el-option label="自主决策Agent" value="agent" />
            <el-option label="回放预留" value="replay" />
          </el-select>
        </el-form-item>
        <el-form-item label="方向">
          <el-select v-model="query.side" clearable style="width: 90px" @change="search">
            <el-option label="买入" value="buy" />
            <el-option label="卖出" value="sell" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker v-model="query.start" type="date" value-format="YYYY-MM-DD" placeholder="开始" @change="search" />
          <span style="margin: 0 4px">至</span>
          <el-date-picker v-model="query.end" type="date" value-format="YYYY-MM-DD" placeholder="结束" @change="search" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 新增账户对话框 -->
    <el-dialog v-model="addDlg" title="新增模拟账户" width="420px">
      <el-form label-width="90px">
        <el-form-item label="账户名称">
          <el-input v-model="addForm.name" placeholder="如：策略试验2号" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="addForm.mode" style="width: 100%">
            <el-option label="通用模拟 (sim)" value="sim" />
            <el-option label="回放账户 (replay)" value="replay" />
            <el-option label="Agent专属 (agent)" value="agent" />
          </el-select>
        </el-form-item>
        <el-form-item label="初始资金">
          <el-input-number v-model="addForm.initial_cash" :min="1000" :step="10000"
                           style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addDlg = false">取消</el-button>
        <el-button type="primary" :loading="adding" @click="doAdd">创建</el-button>
      </template>
    </el-dialog>

    <!-- 统计卡片 -->
    <el-row :gutter="12">
      <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">总笔数</div><b>{{ stats?.count ?? '—' }}</b></el-card></el-col>
      <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">买入</div><b class="up">{{ stats?.buy_count ?? '—' }}</b></el-card></el-col>
      <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">卖出</div><b class="down">{{ stats?.sell_count ?? '—' }}</b></el-card></el-col>
      <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">胜率</div><b>{{ stats ? (stats.win_rate * 100).toFixed(1) + '%' : '—' }}</b></el-card></el-col>
      <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">总费用</div><b>{{ stats?.total_fee?.toFixed(2) ?? '—' }}</b></el-card></el-col>
      <el-col :span="4"><el-card shadow="never" class="mini"><div class="mini-lbl">总金额</div><b>{{ stats?.total_amount?.toLocaleString() ?? '—' }}</b></el-card></el-col>
    </el-row>

    <!-- 交易表格 -->
    <el-card shadow="never">
      <el-table :data="items" size="small" v-loading="loading">
        <el-table-column prop="id" label="ID" width="70" />
        <el-table-column prop="account_id" label="账户" width="70" />
        <el-table-column prop="ts_code" label="代码" width="100" />
        <el-table-column prop="name" label="名称" width="100" />
        <el-table-column prop="trade_date" label="日期" width="105" />
        <el-table-column prop="side" label="方向" width="70">
          <template #default="{ row }">
            <el-tag :type="row.side === 'buy' ? 'danger' : 'success'" size="small">{{ row.side === 'buy' ? '买' : '卖' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="price" label="价格" width="90" />
        <el-table-column prop="qty" label="数量" width="90" />
        <el-table-column prop="amount" label="金额" width="120" />
        <el-table-column prop="fee" label="费用" width="80" />
        <el-table-column prop="source" label="来源" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.source === 'agent' ? 'warning' : row.source === 'strategy' ? 'success' : 'info'">
              {{ sourceLabel(row.source) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="strategy_id" label="策略" width="70" />
        <el-table-column prop="note" label="备注" min-width="140" show-overflow-tooltip />
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next, sizes"
          :page-sizes="[20, 50, 100]"
          @current-change="load"
          @size-change="(s: number) => { pageSize = s; search() }"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createAccount, deleteAccount, listAccounts, listTrades, tradesStats,
  type Account, type TradeRecord, type TradesStats,
} from '../api'

const accounts = ref<Account[]>([])
const items = ref<TradeRecord[]>([])
const stats = ref<TradesStats | null>(null)
const loading = ref(false)
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)

const query = reactive<{
  account_id: number | null
  ts_code: string
  source: string
  side: string
  start: string
  end: string
}>({ account_id: null, ts_code: '', source: '', side: '', start: '', end: '' })

const load = async () => {
  loading.value = true
  try {
    const r = await listTrades({
      account_id: query.account_id ?? undefined,
      ts_code: query.ts_code || undefined,
      source: query.source || undefined,
      side: query.side || undefined,
      start: query.start || undefined,
      end: query.end || undefined,
      page: page.value,
      page_size: pageSize.value,
    })
    items.value = r.items
    total.value = r.total
    stats.value = await tradesStats({
      account_id: query.account_id ?? undefined,
      start: query.start || undefined,
      end: query.end || undefined,
    })
  } catch (e) {
    ElMessage.error(`加载交易记录失败: ${(e as Error).message}`)
  } finally {
    loading.value = false
  }
}

const search = () => {
  page.value = 1
  void load()
}

const fmt = (n: number) => Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 })

const sourceLabel = (s: string) =>
  ({ manual: '手动', strategy: '策略', agent: '自主决策', replay: '回放' })[s] ?? s

const pickAccount = (id: number) => {
  query.account_id = query.account_id === id ? null : id  // 再点一次取消筛选
  search()
}

const loadAll = async () => {
  try { accounts.value = await listAccounts() } catch { /* ignore */ }
  await load()
}

// ---------- 新增账户 ----------
const addDlg = ref(false)
const adding = ref(false)
const addForm = reactive({ name: '', mode: 'sim', initial_cash: 100000 })

const doAdd = async () => {
  adding.value = true
  try {
    const r = await createAccount({
      name: addForm.name || '模拟账户',
      mode: addForm.mode,
      initial_cash: addForm.initial_cash,
    })
    ElMessage.success(`账户 #${r.id} 已创建`)
    addDlg.value = false
    addForm.name = ''
    await loadAll()
  } catch (e) {
    ElMessage.error(`创建失败: ${(e as Error).message}`)
  } finally {
    adding.value = false
  }
}

const removeAccount = async (a: Account) => {  try {
    await ElMessageBox.confirm(
      `确认删除账户「${a.name}」(#${a.id})？其全部交易记录、持仓、回放会话将一并删除，不可恢复。`,
      '删除账户', { type: 'warning' },
    )
  } catch { return }
  try {
    const r = await deleteAccount(a.id)
    ElMessage.success(`账户已删除（清除 ${r.trades_removed} 笔交易）`)
    if (query.account_id === a.id) query.account_id = null
    await loadAll()
  } catch (e) {
    ElMessage.error(`删除失败: ${(e as Error).message}`)
  }
}

onMounted(() => void loadAll())
</script>

<style scoped>
.trades { display: flex; flex-direction: column; gap: 12px; }
.mini { text-align: center; }
.mini .mini-lbl { color: #909399; font-size: 12px; margin-bottom: 4px; }
.pager { display: flex; justify-content: flex-end; margin-top: 10px; }
.account-card { cursor: pointer; margin-bottom: 12px; border: 1px solid #e4e7ed; }
.account-card.active { border-color: #409eff; box-shadow: 0 0 0 1px #409eff inset; }
.account-card :deep(.el-card__body) { padding: 10px 14px; }
.acc-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; }
.acc-body { display: flex; justify-content: space-between; align-items: baseline; }
.acc-num { font-size: 20px; font-weight: 700; }
.acc-sub { color: #909399; font-size: 12px; margin-top: 4px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
</style>
