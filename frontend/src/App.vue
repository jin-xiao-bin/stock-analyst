<template>
  <el-container class="layout">
    <el-header class="header">
      <div class="brand">📈 Stock Analyst</div>
      <nav class="nav">
        <router-link to="/market">行情</router-link>
        <router-link to="/replay">回放交易</router-link>
        <router-link to="/analysis">AI分析</router-link>
        <router-link to="/agent">自主决策</router-link>
        <router-link to="/strategy">策略中心</router-link>
        <router-link to="/review">交易审查</router-link>
        <router-link to="/trades">交易记录</router-link>
      </nav>
      <el-tag type="warning" size="small">模拟交易 · 仅供学习研究，不构成投资建议</el-tag>
    </el-header>
    <el-main class="main">
      <router-view />
    </el-main>
  </el-container>
</template>

<style>
body { margin: 0; background: #f5f7fa; }
.layout { min-height: 100vh; }
.header {
  display: flex; align-items: center; gap: 24px;
  background: #fff; border-bottom: 1px solid #e4e7ed;
}
.brand { font-weight: 700; font-size: 18px; white-space: nowrap; }
.nav { display: flex; gap: 16px; flex: 1; }
.nav a { color: #409eff; text-decoration: none; }
.nav a.router-link-active { font-weight: 600; }
.nav .todo { color: #c0c4cc; cursor: not-allowed; }
.main { max-width: 1400px; margin: 0 auto; width: 100%; }
</style>
