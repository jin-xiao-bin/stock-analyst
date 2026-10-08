# Stock Analyst · AI 驱动的股票分析模拟交易平台

> ⚠️ **免责声明**：本项目所有交易均为**模拟交易**，仅供 AI 应用开发学习研究，不构成任何投资建议。

一个全链路 AI 驱动的 A 股研究练习平台：

- 📊 **多 Agent 投研报告**：数据建模（区分公司披露/分析假设/判断）→ 技术/基本面/舆情三路并行 → 首席交易员汇总，SSE 流式生成
- 💬 **人机协同分析**：与报告对话讨论，你的判断自动融合进"人机综合分析"，归纳总结复盘"你和 AI 谁看得准"
- 🤖 **自主决策 Agent**：盘中巡逻 + 收盘深度双路径决策，纯代码风控闸门（仓位/熔断/冷却等 6 条规则），thesis 失效条件自动跟踪
- 📈 **策略中心**：手写 / 导入 / AI 联网生成策略，沙箱安全执行，回测对比，挂机自动交易，对话式策略修改
- ⏪ **历史回放练习**：防未来函数裁剪，T+1 / 涨跌停 / 佣金印花税仿真撮合，可挂策略对比
- 📱 **飞书双向**：重要事件推送（买卖/熔断/任务触发）+ 群内自然语言指挥买卖 + 消息利弊分析

## 功能架构

```
行情链 · 回放链 · 分析链(人机融合) · 任务链 · 策略链(沙箱+版本链)
审查链(自回归优化) · 自主决策链(风控闸门) · 账户链
```

技术栈：**Python 3.11+ / FastAPI / SQLAlchemy** · **Vue3 / Vite / TypeScript / Element Plus / klinecharts** · **MySQL**（必需）· Milvus + bge-m3 / Redis（可选降级）· DeepSeek / 博查 / Tushare

---

## 🚀 快速部署

### 1. 环境要求

| 组件 | 版本 | 必须 | 说明 |
|---|---|---|---|
| Python | ≥ 3.11 | ✅ | |
| Node.js + pnpm | ≥ 18 / ≥ 8 | ✅ | 前端构建 |
| MySQL | ≥ 8.0 | ✅ | 核心业务库 |
| Milvus | 任意 | ❌ | 不装自动降级（报告向量检索跳过） |
| Redis | 任意 | ❌ | 不装自动降级（直查 MySQL） |
| bge-m3 模型 | — | ❌ | 不配则向量功能降级 |

**需要的 API Key**（都注册即得）：
- [DeepSeek](https://platform.deepseek.com)（必须——LLM 分析/决策）
- [Tushare Pro](https://tushare.pro)（必须——行情/财务数据）
- [博查](https://bocha.ai)（可选——新闻搜索，不配走东财公开接口）

### 2. 克隆与后端

```bash
git clone <你的仓库地址>
cd stock-analyst/backend

# 安装依赖
pip install -r requirements.txt

# 配置密钥（复制模板后填写）
cp ../.env.example .env    # Windows: copy ..\.env.example .env
# 编辑 .env 填入 MYSQL_URL / TUSHARE_TOKEN / DEEPSEEK_API_KEY 等

# 创建数据库（表结构启动时自动创建）
mysql -uroot -p -e "CREATE DATABASE IF NOT EXISTS stock_analyst DEFAULT CHARACTER SET utf8mb4"

# 启动
python -m uvicorn app.main:app --host 127.0.0.1 --port 8300
```

启动日志出现 `已加载路由` 系列 INFO 且无 ERROR 即成功。首次查询某只股票时会自动从 Tushare 全量拉取历史（懒加载），之后每日 17:10 自动增量同步（另有启动追补 + 查询自愈双保险）。

### 3. 前端

```bash
cd ../frontend
pnpm install
pnpm run dev          # 打开 http://localhost:5173
```

### 4. 首跑体验路径

1. **行情页**：搜索 `000001` 看K线（首次拉取约几秒）
2. **AI分析**：选股 → 生成分析（流式，2-3 分钟）→ 报告里「讨论」标签发表你的观点 → 看自动融合的综合分析
3. **回放交易**：新建回放（如 601689 从 2025-01-02）→ 逐日推进 → 手动买卖 → 挂策略对比
4. **自主决策**：配置股票池+风控 → 启动 → 看决策流水（每笔带 thesis 与理由）
5. **策略中心**：AI生成或手写策略 → 发起回测 → 「对话」让 AI 改策略 → 沙箱校验应用新版本

### 5. 可选组件

**Milvus + bge-m3**（报告/新闻向量检索）：
- 部署 Milvus 后填 `MILVUS_URI`；下载 bge-m3 模型到本地纯英文路径，填 `BGE_M3_PATH`
- 不配置完全不影响主流程

**飞书通知/指令**：
1. 通知：飞书群 → 添加「自定义机器人」→ Webhook 填 `FEISHU_WEBHOOK_URL`
2. 指令：[开放平台](https://open.feishu.cn)创建自建应用 → 开机器人能力 → 开 `im:message` 权限 → 事件订阅选「长连接」订阅接收消息 → 发布 → App ID/Secret 填入 `.env` → 把机器人拉进群
3. 群里发 `帮助` 查看指令集；发任意文本获得 AI 利弊分析

### 6. 每日自动任务（后端内置调度）

| 时间 | 任务 |
|---|---|
| 交易日盘中每 5 分钟检查 | Agent 盘中巡逻（按配置频率，如每小时） |
| 15:30 | Agent 收盘深度决策 |
| 17:10 | 行情增量同步（+启动追补+查询自愈） |
| 17:30 | 观察任务核验（价位/事件 LLM 判定） |
| 17:45 | 挂机策略按收盘价执行 |
| 周日 18:00 | Agent 学习笔记生成并注入下周决策 |

## ⚠️ 上线前检查

- `.env` 已在 `.gitignore`，**切勿提交真实密钥**；仓库只含 `.env.example` 模板
- Tushare 需一定积分档位（财务/实时接口）；若用第三方中转，`TUSHARE_API_URL` 填中转地址
- LLM 调用产生费用：单股深度分析约 17k token；自主决策 Agent 3 只股票每日约 96k token

## 目录结构

```
stock-analyst/
├── backend/            # FastAPI 后端
│   ├── app/
│   │   ├── api/        # 路由层（行情/回放/分析/策略/回测/审查/agent/飞书）
│   │   ├── agents/     # AI Agent（公司分析/归纳/策略生成/审查）
│   │   ├── services/   # 业务层（Tushare/DeepSeek/博查/沙箱/回测/风控/通知…）
│   │   └── models.py   # 18 张表 ORM
│   ├── scripts/        # 冒烟测试脚本
│   └── .env            # 密钥配置（gitignore）
├── frontend/           # Vue3 前端（9 个页面 + SSE 流式渲染）
├── desktop/            # 桌面宠物客户端（可选）
└── docs/               # 设计文档 + API 契约
```

## 已知限制

- 分钟级数据不可用（依赖数据源限频），全系统为日级 + 实时快照
- A 股专用（代码归一化、涨跌停规则按 A 股）
- 多用户/鉴权未设计（单机单用户使用场景）

## License

MIT（自行决定，可删除）
