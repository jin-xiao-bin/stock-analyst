import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/market' },
    { path: '/market', component: () => import('./views/MarketView.vue'), meta: { title: '行情' } },
    { path: '/replay', component: () => import('./views/ReplayView.vue'), meta: { title: '回放交易' } },
    { path: '/analysis', component: () => import('./views/AnalysisView.vue'), meta: { title: 'AI分析' } },
    { path: '/agent', component: () => import('./views/AgentView.vue'), meta: { title: '自主决策' } },
    // 任务监控已并入 AI分析（报告操作列「任务」按钮）；/watch 重定向避免旧链接 404
    { path: '/watch', redirect: '/analysis' },
    { path: '/strategy', component: () => import('./views/StrategyView.vue'), meta: { title: '策略中心' } },
    // 回测历史已并入 策略中心（策略行「查看回测」）；/backtest 重定向避免旧链接 404
    { path: '/backtest', redirect: '/strategy' },
    { path: '/review', component: () => import('./views/ReviewView.vue'), meta: { title: '交易审查' } },
    { path: '/trades', component: () => import('./views/TradesView.vue'), meta: { title: '交易记录' } },
    // 账户复盘已并入 交易记录 页（顶部账户卡片）；/accounts 重定向避免旧链接 404
    { path: '/accounts', redirect: '/trades' },
  ],
})
