# QuantMind V2 架构审计报告 (2026-Q1)

> **审计日期**: 2026-03-29
> **审计范围**: 54份设计文档(~550KB) + 全部代码(~100K LOC) 逐行对照
> **审计方法**: 5组并行Agent逐行通读全部文档 + Grep/Glob验证代码存在性 + 运行时验证
> **结论**: 综合实现率约60-65%，PT链路可用，架构基础扎实但存在设计-实现偏差

---

## 一、项目规模

| 维度 | 数量 |
|------|------|
| 设计文档 | 54份(docs/19 + research/9 + archive/15 + root/8 + superpowers/3) |
| 设计文档总量 | ~550KB, ~15000行 |
| 代码文件 | ~280个(Python ~200 + TypeScript ~80) |
| 代码总行数 | ~100K LOC |
| 后端测试 | 1760个(1760 passed) |
| 数据库表 | DDL定义43张，ORM映射18张 |
| API端点 | 设计57个，实现~45个 |
| 前端页面 | 设计12个，实际17个(含6个设计外页面) |

---

## 二、逐模块真实状态

> "文件存在"≠"功能完整"≠"端到端可用"。本报告区分三个层次。

| 模块 | 文件存在 | 功能完整 | E2E可用 | 关键证据 |
|------|---------|---------|---------|---------|
| 数据管道 | 95% | 90% | ✅ | Tushare日增量运行中，5482股日更新 |
| 因子计算(34因子) | 95% | 85% | ✅ | factor_engine.py 1716行+72单测 |
| 信号生成 | 90% | 80% | ✅ | signal_service→SignalComposer→PortfolioBuilder |
| 回测引擎(Python) | 85% | 70% | ✅ | SimpleBacktester+SimBroker+WalkForward |
| 风控L1-L4 | 96% | 90% | ✅ | 状态机+熔断+API+前端组件 |
| Paper Trading | 80% | 75% | ✅ | PaperBroker+watchdog，Day 3/60运行中 |
| 参数系统(220+) | 95% | 85% | ⚠️ | param_service+defaults存在，前端控制不完整 |
| 前端页面(17个) | 97% | 50% | ⚠️ | 页面文件全在，但多数依赖mock数据 |
| GP引擎 | 97% | 60% | ⚠️ | DSL+WarmStartGP+Gate全在，缺自动化触发 |
| ML WalkForward | 90% | 70% | ⚠️ | LightGBM+7折存在，未集成PT链路 |
| 因子挖掘Pipeline | 85% | 50% | ⚠️ | Gate+sandbox+orchestrator在，完整闭环未跑通 |
| 调度自动化 | 80% | 60% | ⚠️ | Task Scheduler手动配，Beat定义未激活 |
| QMT交易对接 | 70% | 40% | ⚠️ | broker_qmt.py 552行，未接入PT链路 |
| WebSocket | 70% | 30% | ❌ | manager存在但引擎不emit |
| AI闭环 | 50% | 15% | ❌ | 模型/API框架在，业务逻辑空壳 |
| 灾备自动化 | 70% | 50% | ⚠️ | 脚本有，自动演练未配置 |
| 外汇模块 | 5% | 0% | ❌ | Phase 2，仅设计文档 |

**综合实现率: ~60-65%**

---

## 三、设计文档 vs 实际实现的偏差

### 3.1 实现超出设计的（需要反向更新文档）

| 实际实现 | 设计文档 | 说明 |
|---------|---------|------|
| 17个前端页面 | DEV_FRONTEND_UI只设计12个 | Portfolio/Risk/Market/Execution/Report/PTGraduation额外实现 |
| 18个API Router | DEV_BACKEND设计10个 | approval/execution/market/portfolio/remote_status/report/system额外实现 |
| broker_qmt.py 552行 | DESIGN_V5提及但未标实现 | QMT Broker已完整实现 |
| 72个factor_engine测试 | 无设计要求 | Sprint 1.25补全 |
| schemas/层8文件 | DEV_BACKEND设计但之前缺失 | Sprint 1.25补全 |
| ORM models 18表 | DEV_BACKEND设计但之前仅3文件 | Sprint 1.25补全 |

### 3.2 设计了但未实现的

| 设计内容 | 文档来源 | 状态 |
|---------|---------|------|
| Rust回测引擎 | DESIGN_V5 §3 | 放弃，纯Python替代(性能足够) |
| Forex全模块 | FOREX_DESIGN 18KB | Phase 2，未开始 |
| AI闭环4Agent | DEV_AI_EVOLUTION 38KB | 框架有，逻辑空 |
| LLM Service(DeepSeek/Claude) | DEV_BACKEND §二 | 未实现 |
| WebSocket 5通道集成 | DEV_FRONTEND_UI §11 | 基础设施在但未集成 |
| Alembic数据库迁移 | DEV_BACKEND §一 | 未配置 |
| shadcn/ui组件库 | DEV_FRONTEND_UI §1.1 | 手写替代 |
| Monaco Editor | DEV_FRONTEND_UI §2.1 | 未安装 |
| scripts/run_gp_pipeline.py | GP_CLOSED_LOOP §7 | 未创建 |
| 自动备份演练 | SOP §6 | 脚本有，自动化未配 |

### 3.3 需要更新的决策记录

| 决策 | 原设计 | 实际选择 | 应记入TECH_DECISIONS |
|------|--------|---------|---------------------|
| 回测引擎 | Rust+Python混合 | 纯Python | 性能足够，维护成本低 |
| ORM vs Raw SQL | ORM | Raw SQL为主+ORM模型共存 | 性能+灵活性 |
| 组件库 | shadcn/ui | 手写GlassCard/Button等 | 毛玻璃风格自定义需求 |
| 导航结构 | 7项 | 11项(按生产频率) | 交易页面是每日必用 |

---

## 四、PT链路验证（铁律5——验代码不信文档）

### 4.1 Task Scheduler实际注册状态
```
✅ QuantMind_DailySignal   → 周一-五 16:30 → run_paper_trading.py signal
✅ QuantMind_DailyExecute  → 周一-五 09:00 → run_paper_trading.py execute
✅ QuantMind_DataQualityCheck → 每日 17:00
✅ QuantMind_DailyBackup   → 每日 02:00
✅ QuantMind_PTWatchdog    → 周一-五 20:00 (Sprint 1.25新增)
❌ QuantMind_MiniQMT_AutoStart → 未运行
```

### 4.2 最近5天绩效数据（DB实查）
```
3/23  NAV=958,637  日收益-4.14%  ← 首日建仓
3/24  NAV=979,294  日收益+2.15%
3/25  NAV=995,281  日收益+1.63%
3/26  NAV=988,817  日收益-0.65%
3/27  NAV=995,338  日收益+0.66%  ← Day 3/60
```

### 4.3 链路问题
- Celery Beat定义了但**未激活**，PT靠Task Scheduler→scripts直接执行
- 日志文件paper_trading.log为空(Windows迁移后日志路径问题)
- 钉钉webhook未配置(告警跳过)

---

## 五、Sprint 1.25 架构对齐成果

| 修复项 | 改动 |
|--------|------|
| 涨跌颜色 | A股惯例(涨红跌绿) |
| schemas/层 | +8文件，API类型契约 |
| ORM models | +7文件，15张核心表映射 |
| utils/层 | +3模块(date/math/validation) |
| 导航重组 | 按生产频率分6组11项 |
| PT watchdog | SQL bug修复+DB检查+钉钉告警+Task Scheduler注册 |
| Mock清理 | FactorLibrary/StrategyWorkspace改ErrorBanner |
| factor_engine测试 | +72个单元测试 |
| 死代码 | 删除Dashboard.tsx(-268行) |
| CRLF标准化 | Mac→Windows 135文件换行符统一 |
