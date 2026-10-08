<template>
  <div class="accounts">
    <el-card shadow="never" class="toolbar">
      <el-button @click="load">刷新</el-button>
      <span class="hint">资金曲线（equity）待后端提供后接入；当前展示账户统计</span>
    </el-card>

    <el-empty v-if="!accounts.length" description="暂无账户" />
    <el-row :gutter="12">
      <el-col v-for="a in accounts" :key="a.id" :span="8">
        <el-card shadow="hover" class="account-card">
          <template #header>
            <div class="card-head">
              <b>{{ a.name }}</b>
              <el-tag size="small" :type="a.mode === 'sim' ? 'warning' : 'info'">{{ a.mode }}</el-tag>
            </div>
          </template>
          <div class="big-num">{{ fmt(a.total_value) }}</div>
          <div class="sub">总资产</div>
          <el-descriptions :column="2" border size="small" style="margin-top: 10px">
            <el-descriptions-item label="现金">{{ fmt(a.cash) }}</el-descriptions-item>
            <el-descriptions-item label="市值">{{ fmt(a.market_value) }}</el-descriptions-item>
            <el-descriptions-item label="初始资金">{{ fmt(a.initial_cash) }}</el-descriptions-item>
            <el-descriptions-item label="收益">
              <span :class="a.profit >= 0 ? 'up' : 'down'">{{ fmt(a.profit) }} ({{ a.profit_pct.toFixed(2) }}%)</span>
            </el-descriptions-item>
          </el-descriptions>
          <div class="foot">
            <span class="lbl">创建于 {{ a.created_at?.slice(0, 10) || '—' }}</span>
            <router-link to="/trades" class="link">查看交易记录</router-link>
          </div>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { listAccounts, type Account } from '../api'

const accounts = ref<Account[]>([])

const fmt = (n: number) => Number(n).toLocaleString('zh-CN', { maximumFractionDigits: 2 })

const load = async () => {
  try {
    accounts.value = await listAccounts()
  } catch (e) {
    ElMessage.error(`加载账户失败: ${(e as Error).message}`)
  }
}

onMounted(() => void load())
</script>

<style scoped>
.accounts { display: flex; flex-direction: column; gap: 12px; }
.toolbar { display: flex; align-items: center; gap: 12px; }
.hint { color: #c0c4cc; font-size: 12px; }
.account-card { margin-bottom: 12px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.big-num { font-size: 26px; font-weight: 700; text-align: center; }
.sub { color: #909399; font-size: 12px; text-align: center; }
.foot { display: flex; justify-content: space-between; align-items: center; margin-top: 10px; }
.lbl { color: #c0c4cc; font-size: 12px; }
.link { color: #409eff; text-decoration: none; font-size: 13px; }
.up { color: #f56c6c; }
.down { color: #67c23a; }
</style>
