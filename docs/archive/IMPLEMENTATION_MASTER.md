# QuantMind V2 实施总纲（全项目版）

> **版本**: v2.0
> **日期**: 2026-03-28
> **状态**: 生效中
> **定位**: 唯一的"下一步做什么"操作文档，覆盖全项目所有模块（后端+前端+基础设施）
> **基础文档**: DEVELOPMENT_BLUEPRINT.md(135功能审计) + R1-R7研究报告(73条) + DEV_FRONTEND_UI.md(12页面)
> **约束**: Paper Trading v1.1运行中(Day 3/60)，绝对不可中断
> **前版本**: v1.0仅覆盖R1-R7新增条目，已废弃

---

## 1. 执行摘要

### 1.1 当前状态

| 维度 | 状态 |
|------|------|
| Phase 0完成度 | 62%（135个设计功能中79完成、9部分、44缺失） |
| Phase 1完成度 | ~5%（仅ML引擎基础版和因子生命周期表） |
| Paper Trading | v1.1 Day 3/60, NAV=995,281(+1.63%), 链路正常 |
| 基线配置 | 5因子等权 + Top15 + 月度 + 行业25%, Sharpe=0.91(volume-impact) |
| 后端 | 128 Python文件, ~40K LOC, 27个Engine, 8个Service, 8个API Router |
| 前端 | 11文件, 868 LOC, 1/12页面(Dashboard ~50%), 0 WebSocket |
| 测试 | 43个测试文件, ~13K LOC, 718个测试函数 |
| 研究储备 | R1-R7全部完成, 73项可执行条目 |
| 已关闭方向 | 等权线性合成(9种全败)/基本面delta(10种穷举)/Forecast因子/RSRS单因子/HMM regime |

### 1.2 两类工作

本文档合并两个来源的缺口：

| 来源 | 条目数 | 性质 | 示例 |
|------|--------|------|------|
| DEVELOPMENT_BLUEPRINT | 44+9=53项 | 关闭现有设计-代码差距 | WebSocket、Service层补全、前端12页面、参数系统 |
| R1-R7研究报告 | 73项 | 新增能力 | FactorClassifier、CompositeStrategy、GP引擎、LLM Agent |
| **合计** | **~117项** | — | — |

### 1.3 目标路径

```
当前(62%) ─── PT毕业 ──── 实盘过渡 ──── AI增强 ──── 完整闭环(100%)
             (60天)       (1周)        (持续)       (Phase 1完成)
```

**核心目标（三步走战略，2026-03-28确认）**:
1. **Step 1 — PT赚钱（Sprint 1.13-1.15）**: v1.1 PT毕业→实盘，不需AI闭环也能赚钱。NSSM服务化+备份+监控=生产级
2. **Step 2 — GP最小闭环（Sprint 1.16-1.17）**: Warm Start GP + FactorGate G1-G8 + SimBroker反馈循环。GP-first不上LLM（零成本、确定性高）
3. **Step 3 — 完整AI闭环（Sprint 1.18+）**: LLM Agent层 + 知识森林 + PipelineOrchestrator + 因子+模型联合优化
4. **前端上线**: 12页面从13%→100%，WebSocket实时推送（与Step 1-3并行）
5. **实盘过渡**: miniQMT切换，1股最小单位dry run后渐进切换

**关键原则**: 每一步独立创造价值。GP跑不通→LLM也跑不通。PT不毕业→闭环救不了。
**外部框架决策**: RD-Agent借鉴思想不集成(依赖Azure/A股不适配)。Qlib Alpha158做DSL算子参考，不集成回测。Warm Start GP(arxiv 2412.00896)优于随机DEAP。

### 1.4 时间线: 10个Sprint = 20周

```
Sprint 1.13 ─ 1.14 ─ 1.15 ─ 1.16 ─ 1.17 ─ 1.18 ─ 1.19 ─ 1.20 ─ 1.21 ─ 1.22
 前端基础+    回测前端   回测结果  因子前端   因子挖掘  AI Pipeline 系统设置  PT监控   联调E2E  实盘过渡
 策略核心     +Engine1  +策略验证 +GP引擎   前端+LLM  前端+编排   +Dashboard +生产加固 +PT毕业  +文档
 (2w)        (2w)     (2w)    (2w)     (2w)    (2w)     (2w)     (2w)     (2w)    (2w)
```

**为什么比v1.0多2个Sprint**: 前端从"附属品"升级为"共等优先"后，工作量显著增加——12个页面+基础设施+WebSocket+API对齐总计需要额外~4周。

### 1.5 五条并行轨道

| 轨道 | 缩写 | 覆盖来源 | 核心交付物 |
|------|------|----------|-----------|
| Track A: 策略框架 | TrA | R1+R3+BLUEPRINT-C | FactorClassifier/CompositeStrategy/Modifiers/多频率策略 |
| Track B: 因子挖掘 | TrB | R2+R7+BLUEPRINT-K | Factor Sandbox/BruteForce/GP/LLM 3-Agent/Gate Pipeline |
| Track C: PT+生产 | TrC | R4+R5+R6+BLUEPRINT-G | 滑点改进/信号回放/NSSM/备份/PT毕业/实盘切换 |
| Track D: 前端 | TrD | BLUEPRINT-J+DEV_FRONTEND_UI | 12个页面+React基础设施+WebSocket+通知系统 |
| Track E: 基础设施 | TrE | BLUEPRINT-H/I+技术债务 | Service层补全/DB迁移/测试策略/CI |

**轨道间依赖关系**:
```
Track E (基础设施) ─→ 所有轨道依赖 (Service层/WebSocket/DB)
     ↓
Track A (策略框架)
  ↓ FactorClassifier → Track B需要分类结果路由策略
  ↓ CompositeStrategy → Track C的PT需要验证composite信号
Track B (因子挖掘)
  ↓ Gate Pipeline → Track A的新因子通过Gate
  ↓ 挖掘结果 → Track D展示
Track C (PT+生产)
  ↓ PT数据 → Track A的滑点校准
  ↓ NSSM服务化 → 所有轨道的运行时基础
Track D (前端)
  ← 依赖其他轨道的API，但可独立开发UI骨架
```

---

## 2. 全项目差距分析

### 2.0 总体完成度矩阵

> 来源: DEVELOPMENT_BLUEPRINT 1.1节审计 + R1-R7新增能力

| 模块 | 设计功能 | 完成 | 部分 | 缺失 | 新增(R1-R7) | 总缺口 | 完成度 |
|------|---------|------|------|------|------------|--------|--------|
| A. 数据管道 | 9 | 7 | 0 | 2 | 0 | 2 | 78% |
| B. 因子引擎 | 17 | 10 | 2 | 5 | 11 | 18 | 36% |
| C. 信号/组合 | 8 | 5 | 1 | 2 | 10 | 13 | 24% |
| D. 回测引擎 | 18 | 14 | 2 | 2 | 7 | 11 | 52% |
| E. 风控 | 9 | 7 | 0 | 0 | 0 | 0 | 100%(P0) |
| F. 执行层 | 8 | 7 | 0 | 0 | 3 | 3 | 73% |
| G. 调度运维 | 9 | 4 | 0 | 5 | 13 | 18 | 18% |
| H. 通知告警 | 9 | 4 | 3 | 2 | 0 | 5 | 44% |
| I. 参数系统 | 9 | 5 | 1 | 3 | 0 | 4 | 56% |
| J. 前端 | 15 | 2 | 0 | 13 | 5 | 18 | 10% |
| K. AI/ML | 11 | 2 | 0 | 9 | 24 | 33 | 6% |
| **总计** | **135** | **79** | **9** | **44** | **73** | **117+** | — |

### 2.1 前端差距（最大缺口，13%→100%）

**当前状态**: 12页面设计完成(DEV_FRONTEND_UI.md, 695行)，仅Dashboard页面部分构建（4个组件: KPICards/NAVChart/PositionTable/CircuitBreaker）。

**缺失基础设施**:

| 基础设施 | 设计文档位置 | 现状 | 优先级 |
|----------|------------|------|--------|
| React Router v6 | DEV_FRONTEND_UI §9 | 无路由配置 | P0 |
| Zustand状态管理 | DEV_FRONTEND_UI §1.1 | 无Store | P0 |
| Axios + React Query | DEV_FRONTEND_UI §1.1 | 无API client层 | P0 |
| socket.io-client | DEV_FRONTEND_UI §11 | 无WebSocket | P0 |
| shadcn/ui组件库 | DEV_FRONTEND_UI §1.1 | 未安装 | P0 |
| Monaco Editor | DEV_FRONTEND_UI §2.1/3.1 | 未安装 | P1 |
| ECharts + Recharts | DEV_FRONTEND_UI §1.4 | 仅Recharts部分 | P0 |
| 深色主题+毛玻璃 | DEV_FRONTEND_UI §1.2/10 | 仅基础暗色 | P1 |
| 通知系统(铃铛+Toast) | DEV_FRONTEND_UI §13 | 无 | P1 |

**12页面详细差距分析**:

| # | 页面 | 路由 | 设计文档 | 后端API状态 | 前端状态 | Sprint |
|---|------|------|---------|------------|---------|--------|
| 1 | 总览(Dashboard) | `/dashboard` | §8 | 5/11端点已有 | ~50% | 1.19 |
| 2 | A股详情 | `/dashboard/astock` | §8.3 | 共用Dashboard API | 0% | 1.19 |
| 3 | 外汇详情 | `/dashboard/forex` | §8.4 | 0/9端点(Phase 2) | 0% | Phase 2 |
| 4 | 策略工作台 | `/strategy` | §2.1 | 2/5端点(CRUD部分) | 0% | 1.14 |
| 5 | 回测配置 | `/backtest/config` | §2.2 | 1/3端点(run) | 0% | 1.14 |
| 6 | 回测运行监控 | `/backtest/:runId` | §2.3 | 0/1(无WS) | 0% | 1.15 |
| 7 | 回测结果分析 | `/backtest/:runId/result` | §2.4 | 3/8端点 | 0% | 1.15 |
| 8 | 策略库 | `/backtest/history` | §2.5 | 1/2端点 | 0% | 1.15 |
| 9 | 因子库 | `/factors` | §3.4 | 2/5端点 | 0% | 1.16 |
| 10 | 因子评估报告 | `/factors/:id` | §3.3 | 1/4端点 | 0% | 1.16 |
| 11 | 因子实验室 | `/mining` | §3.1 | 0/6端点 | 0% | 1.17 |
| 12 | 挖掘任务中心 | `/mining/tasks` | §3.2 | 0/3端点(无WS) | 0% | 1.17 |
| 13 | Pipeline控制台 | `/pipeline` | §4.1 | 0/7端点 | 0% | 1.18 |
| 14 | Agent配置 | `/pipeline/agents` | §4.2 | 0/3端点 | 0% | 1.18 |
| 15 | 系统设置 | `/settings` | §5.1 | 2/8端点 | 0% | 1.19 |

**API差距**: 设计57个端点(A股48+外汇9)，后端已实现~30个，前端对接~5个。

### 2.2 后端Service层差距

**Service层现状**:

| Service | 文件 | 状态 | 缺失功能 |
|---------|------|------|---------|
| DashboardService | `dashboard_service.py` | ✅已实现 | 月度热力图、行业分布时序 |
| ExecutionService | `execution_service.py` | ✅已实现 | — |
| NotificationService | `notification_service.py` | ⚠️部分 | 32模板仅部分实现,无WebSocket推送 |
| PaperTradingService | `paper_trading_service.py` | ✅已实现 | — |
| ParamService | `param_service.py` | ⚠️部分 | 220参数仅注册~50个 |
| RiskControlService | `risk_control_service.py` | ✅已实现 | — |
| SignalService | `signal_service.py` | ✅已实现 | CompositeStrategy信号集成 |
| StrategyService | `strategy_service.py` | ✅已实现 | 多策略版本管理 |
| **DataService** | 不存在 | ❌缺失 | 数据拉取集中化(当前散落在scripts) |
| **FactorService** | 不存在 | ❌缺失 | 因子计算/分析的Service封装 |
| **BacktestService** | 不存在 | ❌缺失 | 回测引擎的Service封装 |
| **PortfolioService** | 不存在 | ❌缺失 | 组合构建/优化Service |
| **MiningService** | 不存在 | ❌缺失 | 因子挖掘Pipeline Service |
| **PipelineService** | 不存在 | ❌缺失 | AI闭环Pipeline Service |
| **SchedulerService** | 不存在 | ❌缺失 | 调度任务管理Service |

**API Router层现状**: 8个Router已实现(health/dashboard/backtest/notifications/paper_trading/params/risk/strategies)。缺失: factor/mining/pipeline/agent/system/approval。

### 2.3 R1-R7新增架构组件

| 组件 | 来源 | 文件路径(计划) | 依赖 |
|------|------|--------------|------|
| FactorClassifier | R1 | `engines/factor_classifier.py` | factor_analyzer, ic_decay数据 |
| FastRankingStrategy | R1 | `engines/strategies/fast_ranking.py` | base_strategy |
| EventStrategy | R1 | `engines/strategies/event_strategy.py` | base_strategy |
| CompositeStrategy | R3 | `engines/strategies/composite.py` | base_strategy, modifiers |
| ModifierBase ABC | R3 | `engines/modifiers/base_modifier.py` | — |
| RegimeModifier | R3 | `engines/modifiers/regime_modifier.py` | vol_regime |
| FactorSandbox | R2 | `engines/mining/factor_sandbox.py` | — |
| BruteForceEngine | R2 | `engines/mining/bruteforce_engine.py` | factor_engine |
| GPEngine(DEAP) | R2 | `engines/mining/gp_engine.py` | factor_dsl, DEAP |
| FactorDSL | R2 | `engines/mining/factor_dsl.py` | — |
| ASTDedup | R2 | `engines/mining/ast_dedup.py` | — |
| FactorGatePipeline | R2 | `engines/factor_gate.py` | factor_analyzer |
| PipelineOrchestrator | R2 | `engines/mining/pipeline_orchestrator.py` | 三引擎+Gate |
| DeepSeekClient | R7 | `engines/mining/deepseek_client.py` | httpx |
| ModelRouter | R7 | `engines/mining/model_router.py` | — |
| IdeaAgent | R7 | `engines/mining/agents/idea_agent.py` | model_router |
| FactorAgent | R7 | `engines/mining/agents/factor_agent.py` | model_router |
| EvalAgent | R7 | `engines/mining/agents/eval_agent.py` | model_router |
| ThompsonScheduler | R2 | `engines/mining/scheduler.py` | — |
| overnight_gap_cost | R4 | `engines/slippage_model.py`(修改) | — |
| 信号回放验证器 | R5 | `scripts/pt_signal_replay.py` | signals表, trade_log表 |

### 2.4 技术债务清单

| # | 债务 | 风险 | 修复成本 | Sprint |
|---|------|------|---------|--------|
| 1 | 任务依赖链缺失(health失败不阻塞signal) | P0 | 1天 | 1.13 |
| 2 | Alembic迁移未配置 | P1 | 0.5天 | 1.13 |
| 3 | WebSocket完全缺失 | P1 | 2天 | 1.15 |
| 4 | Celery单队列(设计8个) | P2 | 0.5天 | 1.15 |
| 5 | AKShare备用源缺失 | P1 | 2天 | 1.16 |
| 6 | loguru vs logging不一致 | P3 | 1天 | 1.15 |
| 7 | ORM模型为空(全部raw SQL) | P2 | 3天 | 可延后 |
| 8 | 因子Gate Pipeline非自动化 | P1 | 2天 | 1.14 |
| 9 | 审计报告7处过时 | P3 | 0.5天 | 1.13 |

---

## 3. 架构决策（R1-R7精华）

> 每条决策标注原始研究编号和与DESIGN_V5的关系。
> SUPERSEDE = R1-R7结论取代DESIGN_V5原始设计。UPDATE = 在原设计基础上细化。NEW = 全新增组件。

### 3.1 多频率策略: Modifier叠加而非子策略拆分 [R3]

> **SUPERSEDE**: DESIGN_V5 §6原设计为"多策略+PortfolioAggregator资金分配"

**核心结论**: 资金规模不足时，不拆独立子策略，用"核心策略+Modifier叠加"三层架构。

**整手约束是关键瓶颈**:
```
单策略(可配置资金) → Top15 → 每股~6.67万 → 整手误差 ~3-4%
拆2个子策略(各50%) → 各Top15 → 每股~3.33万 → 整手误差 ~6-8%
```

**三层架构**:
```
Layer 1: 核心策略 (100%资金, v1.1 EqualWeight不变)
         ↓ 产出: {code: weight} 目标持仓
Layer 2: Modifier调节器 (不选股, 只调节Layer 1的权重)
         ├── RegimeModifier: 高波→全仓位×0.7 (30%转现金)
         ├── VwapModifier: VWAP偏离→个股权重±20% [未来]
         └── EventModifier: RSRS/PEAD触发→临时加减仓 [未来]
         ↓ 产出: 修改后的 {code: weight}
Layer 3: 全组合风控 (L1-L4 + PreTradeValidator, 已有)
         ↓ 产出: 最终执行指令
```

**资金规模阈值**: 资金量可配置(非固定100万)，达到300万+时可切换为独立子策略模式。

### 3.2 因子挖掘: 三引擎+统一Gate Pipeline [R2]

> **SUPERSEDE**: DESIGN_V5 §9原设计为4引擎，R2精简为3引擎
> R2研究发现: BruteForce+GP已覆盖"规则化组合"的绝大部分空间，
> 暴力枚举模式与GP的搜索空间高度重叠，合并为参数化BruteForce更高效。
> LLM补充GP难以发现的"非标因子"(如事件型、跨周期组合)。

| 引擎 | 实现基础 | 产出速率 | 成本 | 优先级 | 适用场景 |
|------|----------|----------|------|--------|---------|
| Engine 1: BruteForce | 50模板×参数网格 | ~150因子/小时 | 0(纯CPU) | P0 | 已知模板的参数搜索 |
| Engine 2: GP遗传编程 | DEAP岛屿模型(4子群×500) | ~20因子/小时 | 0(CPU/GPU) | P1 | 因子表达式组合搜索 |
| Engine 3: LLM 3-Agent | DeepSeek R1+V3混合 | ~5因子/小时 | ~$5/session | P1 | 非标因子/经济学直觉 |

**R2关键改进**:
1. 逻辑/参数分离(FactorEngine模式) — GP效率提升，逻辑树只编码组合方式
2. AST去重(AlphaAgent模式) — 准确率+81%，避免重复搜索已知失败的组合
3. Thompson Sampling引擎调度 — 基于Beta后验自动偏向高产引擎
4. 复杂度惩罚 — `fitness = IC×0.4 + IR×0.3 + novelty×0.2 - C×0.1`

**Thompson Sampling调度机制**:
```python
# 每次Pipeline运行时选择引擎
class ThompsonScheduler:
    """基于成功率的Beta分布后验采样。

    每个引擎维护(success, failure)计数:
    - success: 产出通过G4(t>2.5)的因子数
    - failure: 产出未通过G4的因子数
    - 选择: 从Beta(s+1, f+1)采样，选最高值的引擎

    初始: 均匀先验Beta(1,1)
    收敛: ~30次运行后偏好开始稳定
    """
    def select_engine(self) -> str: ...
```

**统一Gate Pipeline (G1-G8)**:
```
G1: Success   — 无错误，执行时间<10s
G2: Coverage  — 有效值覆盖>1000只股票/截面
G3: IC        — 全样本均值IC > 0.015
G4: t-stat    — t > 2.5 (Harvey Liu Zhu 2016)
G5: Neutral   — 中性化后IC不归零
G6: Dedup     — AST结构去重 + Spearman<0.7
G7: Stability — 滚动12月IC稳定性
G8: Turnover  — 隐含换手率 < 200%年化
```

### 3.3 滑点模型: 三组件精细化 [R4]

> **UPDATE**: 增加第三组件overnight_gap_cost，base_bps分层

```
当前: total_slippage = base_bps(5) + impact_bps(Bouchaud)
改进: total_slippage = tiered_base_bps + impact_bps(Bouchaud) + overnight_gap_cost
```

| 组件 | 公式 | 估计贡献 |
|------|------|----------|
| tiered_base_bps | large=3, mid=5, small=8 (bps) | ~10-15bps |
| impact_bps | Y × sigma_daily × sqrt(Q/V) × 10000 | ~25-35bps |
| overnight_gap_cost | overnight_return × direction_alignment | ~10-15bps |

### 3.4 部署架构: NSSM + Task Scheduler + Tailscale [R6]

> **SUPERSEDE**: DESIGN_V5 §12原设计为Celery Beat + Docker

| 组件 | 方案 | 优势 |
|------|------|------|
| 进程管理 | NSSM | 崩溃自动重启，OS级可靠性 |
| 定时调度 | Task Scheduler | OS级别，不依赖Python进程 |
| 监控告警 | PG表 + 钉钉 (P0/P1/P2) | 轻量，零外部依赖 |
| 远程访问 | Tailscale VPN + FastAPI | 安全隧道 |
| 日志 | structlog JSON + RotatingFileHandler | 结构化，~1.25GB上限 |
| 备份 | pg_dump日全量(7天滚转) + 月永久 | 双保险 |

### 3.5 AI选型: DeepSeek混合架构 [R7]

> **UPDATE**: 精确到4个Agent各自最优模型选择

| Agent | 模型 | 部署方式 | 原因 |
|-------|------|----------|------|
| Idea Agent | DeepSeek-R1 | API | 深度推理+中文金融 |
| Factor Agent | Qwen3-Coder-30B-A3B | 本地RTX 5070 | 零API成本 |
| Eval Agent | DeepSeek-V3.2 | API | 快速统计分析 |
| Diagnosis Agent | DeepSeek-R1 | API | 根因分析 |

**月度成本**: ~$65-95（混合架构），有效因子成本~$6.5-9.5/个

### 3.6 回测-实盘对齐: T+1开盘执行+信号回放 [R5]

**8个gap来源（按Sharpe影响排序）**:

| # | Gap来源 | Sharpe影响 | 状态 |
|---|---------|-----------|------|
| 1 | 交易成本模型偏差 | -0.10~-0.20 | 已部分解决(volume-impact) |
| 2 | 隔夜跳空 | -0.05~-0.15 | 待加overnight_gap_cost |
| 3 | 信号Alpha衰减(16h) | -0.03~-0.08 | 需信号回放验证 |
| 4 | 部分成交/封板 | -0.02~-0.05 | can_trade()已实现 |
| 5 | 集合竞价机制偏差 | -0.01~-0.03 | 用T+1 open |
| 6 | Look-ahead残余 | -0.01~-0.02 | 15项检查清单待执行 |
| 7 | 数据延迟/修正 | -0.005~-0.01 | Tushare 16:00后完整 |
| 8 | 存活偏差残余 | -0.005~-0.01 | 已处理 |

### 3.7 因子分类: FactorClassifier路由机制 [R1]

> **NEW**: DESIGN_V5无此组件

| 维度 | 度量方式 | 路由规则 |
|------|----------|----------|
| IC衰减半衰期 | ic_decay曲线拟合 | <5天→FastRanking, 5-15天→Standard, >15天→SlowRanking |
| 信号分布形态 | 截面偏度/峰度 | 正态→Ranking, 稀疏→Event, 双模态→Conditional |
| 触发机制 | 自相关分析 | 持续型→Ranking, 脉冲型→Event, 条件型→Modifier |

### 3.8 前后端API对齐策略

**原则**: Backend API First → Frontend Page → Integration Test

```
Phase 1: API Router先于Page实现
  ├── 每个Sprint先完成后端API端点
  ├── 前端用Mock数据开发UI骨架
  └── Sprint结束时集成联调

Phase 2: WebSocket并行建设
  ├── Socket.IO server嵌入FastAPI (python-socketio)
  ├── 5个WS通道: backtest/factor-mine/pipeline/notifications/forex
  └── 前端useWebSocket hook统一管理

Phase 3: 状态管理标准化
  ├── React Query管理服务端状态(API数据)
  ├── Zustand管理客户端状态(UI状态/用户偏好)
  └── 不混合: 服务端数据不存Zustand
```

### 3.9 Service层架构补全

**为什么需要Service封装**: Engine层是纯计算(DataFrame输入输出)，Service层负责DB IO + 权限 + 事务 + 错误处理。前端不能直接调Engine。

| 缺失Service | 封装的Engine | 优先级 | Sprint |
|-------------|-------------|--------|--------|
| FactorService | factor_engine + factor_analyzer + factor_profile | P0 | 1.13 |
| BacktestService | backtest_engine + metrics + walk_forward | P0 | 1.13 |
| MiningService | mining/* + factor_gate | P1 | 1.18 |
| PipelineService | pipeline_orchestrator | P1 | 1.18 |
| SchedulerService | Task Scheduler管理 | P1 | 1.19 |

---

## 4. 运行时架构（底层如何运行）

### 4.1 日常调度链路

```
                    T日调度链路
                    ===========

16:25 ┌─────────────────────────────────────────────────┐
      │  HealthCheck (Task Scheduler触发)                │
      │  ├── PG连接 ✓                                   │
      │  ├── Redis连接 ✓                                │
      │  ├── 昨日数据已更新 ✓                             │
      │  ├── 因子NaN抽样 ✓ (10只股票)                    │
      │  ├── 磁盘空间 > 100GB ✓                         │
      │  └── Celery workers在线 ✓                       │
      │  ✗ → P0告警 + 暂停当日链路                       │
      └────────────────────┬────────────────────────────┘
                           │ PASS
16:30 ┌────────────────────▼────────────────────────────┐
      │  数据拉取 (Celery task)                          │
      │  Tushare klines_daily + daily_basic + moneyflow  │
      │  超时: 15min → 重试3次 → 切AKShare → P0告警      │
      └────────────────────┬────────────────────────────┘
                           │
17:00 ┌────────────────────▼────────────────────────────┐
      │  因子计算 (单事务批量写入)                         │
      │  5因子 × Universe → MAD → fill → neutralize → z  │
      │  写入 factor_values表 (当日全股票全因子1事务)      │
      └────────────────────┬────────────────────────────┘
                           │
17:10 ┌────────────────────▼────────────────────────────┐
      │  信号生成                                        │
      │  CompositeStrategy.generate_signals(context)     │
      │  ├── core: EqualWeightStrategy (仅调仓日)        │
      │  ├── modifier: RegimeModifier (每日评估)          │
      │  └── 权重归一化 (cash_buffer=3%)                  │
      └────────────────────┬────────────────────────────┘
                           │
17:20 ┌────────────────────▼────────────────────────────┐
      │  风控检查                                        │
      │  L1-L4 + PreTradeValidator 5项 + 跳空预检        │
      └────────────────────┬────────────────────────────┘
                           │
17:25 ┌────────────────────▼────────────────────────────┐
      │  调仓指令入库 + 钉钉通知                          │
      └────────────────────┬────────────────────────────┘
                           │
20:00 ┌────────────────────▼────────────────────────────┐
      │  Watchdog心跳检查                                │
      │  信号已生成? 通知已发送? ✗ → P0告警               │
      └────────────────────────────────────────────────┘

                ─── 隔夜 ───

T+1日
09:00 ┌─────────────────────────────────────────────────┐
      │  执行 (config_guard检查 → SimBroker/QMT执行)     │
      │  写入 trade_log + position_snapshot               │
      └─────────────────────────────────────────────────┘

02:00 ┌─────────────────────────────────────────────────┐
      │  PG备份 (7天滚动 + 月永久)                       │
      └─────────────────────────────────────────────────┘
```

### 4.2 CompositeStrategy运行时

```
CompositeStrategy.generate_signals(context) -> dict[str, float]
│
├── Step 1: Core策略执行
│   core = EqualWeightStrategy
│   ├── 是调仓日? YES → generate_signals() → {code: weight}
│   └── 是调仓日? NO  → prev_holdings (不动)
│
├── Step 2: Modifier逐个评估并叠加
│   for modifier in [RegimeModifier, VwapModifier(未来), ...]:
│   ├── should_evaluate(date)?
│   │   ├── RegimeModifier: 每日 → True
│   │   ├── VwapModifier: 周五 → True [未来]
│   │   └── EventModifier: 有信号 → True [未来]
│   ├── YES → result = modifier.evaluate(context, weights)
│   │         RegimeModifier: vol > 1.5x → scale=0.7
│   └── weights = apply_modifier(weights, result)
│
├── Step 3: 归一化与约束
│   ├── sum → 1.0 - cash_buffer(3%)
│   ├── 单股≤15%
│   └── 行业≤25%
│
└── Step 4: 风控检查 → 返回最终权重
```

### 4.3 因子挖掘Pipeline状态机

```
PipelineOrchestrator (8节点)
│
├── Node 1: SELECT_ENGINE
│   Thompson Sampling(Beta后验) → BruteForce/GP/LLM
│
├── Node 2: GENERATE_CANDIDATES
│   ├── BruteForce: 50模板×参数 → ~150/h
│   ├── GP DEAP: 4岛×500 → ~20/h
│   └── LLM: Idea→Factor→Eval → ~5/h
│
├── Node 3: SANDBOX_EXECUTE
│   AST安全检查 → subprocess隔离 → 5s超时 → 2GB内存
│
├── Node 4: GATE_PIPELINE (G1-G8)
│   快速短路: G1 FAIL → 不继续G2
│
├── Node 5: CLASSIFY
│   FactorClassifier → strategy_type + frequency
│
├── Node 6: BACKTEST
│   用推荐策略框架 → SimBroker → Sharpe/MDD/CI
│
├── Node 7: APPROVAL_QUEUE
│   写入DB → 钉钉通知 → 人工approve/reject
│
└── Node 8: ACTIVATE
    factor_lifecycle='candidate' → 全历史回填 → PT验证
```

### 4.4 多频率协调机制

```
因子 ic_decay 半衰期          策略路由
──────────────────────────────────────
< 5 天 (快衰减)        →  FastRankingStrategy (周度)
5-15 天 (中等)         →  RankingStrategy (月度, v1.1)
> 15 天 (慢衰减)       →  SlowRankingStrategy (季度) [未来]
稀疏极端分布            →  EventStrategy (事件触发)
条件依赖                →  作为Modifier使用
```

### 4.5 Windows部署架构

```
Windows 11 Pro (R9-9900X3D + RTX 5070 12GB + 32GB DDR5-6000)
│
├── NSSM Services (崩溃自动重启)
│   ├── quantmind-api (uvicorn :8000)
│   ├── quantmind-celery-worker-1 (-c 4 -Q default)
│   ├── quantmind-celery-worker-2 (-c 2 -Q factor_calc)
│   ├── quantmind-frontend (npx serve :3000)
│   └── quantmind-qwen3 (ollama :11434) [Phase 1]
│
├── Windows Services
│   ├── postgresql-x64-16 (D:\pgdata16 :5432)
│   └── Redis (:6379, 512MB)
│
├── Task Scheduler (OS级调度)
│   ├── QM-HealthCheck (交易日 16:25)
│   ├── QM-Signal (交易日 16:30)
│   ├── QM-Execute (交易日 09:00)
│   ├── QM-Watchdog (交易日 20:00)
│   ├── QM-Backup (每日 02:00)
│   ├── QM-FactorHealth (交易日 17:30)
│   └── QM-QMT-Autostart (用户登录) [实盘]
│
├── miniQMT (D:\国金QMT, 实盘时启动)
└── Tailscale VPN (远程监控)
```

**资源预算**:
```
总内存 32GB = OS+QMT(8GB) + PG(4GB) + Redis(0.5GB) + API+Services(4GB)
            + Celery(2GB) + Frontend(0.25GB) + Qwen3(4GB) + 剩余(9GB)
```

### 4.5.1 NSSM服务配置详情

```powershell
# 安装脚本: scripts/nssm_setup.ps1

# 1. API服务
nssm install quantmind-api "D:\quantmind-v2\.venv\Scripts\uvicorn.exe"
nssm set quantmind-api AppParameters "backend.app.main:app --host 0.0.0.0 --port 8000 --workers 2"
nssm set quantmind-api AppDirectory "D:\quantmind-v2"
nssm set quantmind-api AppStdout "D:\quantmind-v2\logs\api.log"
nssm set quantmind-api AppStderr "D:\quantmind-v2\logs\api-error.log"
nssm set quantmind-api AppRotateFiles 1
nssm set quantmind-api AppRotateBytes 52428800  # 50MB
nssm set quantmind-api AppRestartDelay 3000      # 3秒后重启

# 2. Celery Worker (default队列)
nssm install quantmind-celery-1 "D:\quantmind-v2\.venv\Scripts\celery.exe"
nssm set quantmind-celery-1 AppParameters "worker -A backend.app.tasks -c 4 -Q default --loglevel=INFO"

# 3. Celery Worker (factor_calc队列)
nssm install quantmind-celery-2 "D:\quantmind-v2\.venv\Scripts\celery.exe"
nssm set quantmind-celery-2 AppParameters "worker -A backend.app.tasks -c 2 -Q factor_calc --loglevel=INFO"

# 4. 前端静态服务
nssm install quantmind-frontend "D:\quantmind-v2\frontend\node_modules\.bin\serve.cmd"
nssm set quantmind-frontend AppParameters "-s D:\quantmind-v2\frontend\dist -l 3000"
```

**Task Scheduler任务配置**:
```xml
<!-- QM-Signal (交易日16:30) -->
<Task>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T16:30:00</StartBoundary>
      <ScheduleByWeek><DaysOfWeek>
        <Monday/><Tuesday/><Wednesday/><Thursday/><Friday/>
      </DaysOfWeek></ScheduleByWeek>
    </CalendarTrigger>
  </Triggers>
  <Actions>
    <Exec>
      <Command>D:\quantmind-v2\.venv\Scripts\python.exe</Command>
      <Arguments>-m backend.scripts.run_paper_trading --stage signal</Arguments>
      <WorkingDirectory>D:\quantmind-v2</WorkingDirectory>
    </Exec>
  </Actions>
  <Settings>
    <ExecutionTimeLimit>PT30M</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT5M</Interval><Count>3</Count></RestartOnFailure>
  </Settings>
</Task>
```

### 4.5.2 错误处理与恢复策略

```
错误级别与处理方式:
═══════════════════

P0 (立即处理，阻塞链路):
├── PG连接失败 → 重试3次(间隔5s) → 钉钉P0告警 → 暂停当日链路
├── Tushare数据拉取全失败(含AKShare备用) → P0告警 → 暂停
├── 因子计算事务失败 → 回滚 → 重试1次 → P0告警
└── 信号生成异常 → 用昨日信号(不调仓) → P0告警

P1 (需处理，不阻塞):
├── 部分股票数据缺失 → 记录缺失列表 → 因子计算跳过这些股票
├── Redis连接失败 → 降级(跳过缓存) → P1告警
├── 通知发送失败 → 重试3次 → 记录到notification_failures表
└── Celery worker崩溃 → NSSM自动重启 → P1告警

P2 (可延后):
├── 备份超时 → 次日重试
├── 日志轮转失败 → 记录
└── 前端构建缓存过期 → 下次部署处理
```

**关键恢复流程——因子计算失败**:
```python
async def safe_daily_factor_calc(date: date):
    """因子计算的容错wrapper。

    事务性: 所有因子写入在同一事务中，要么全成功要么全回滚。
    重试: 最多重试1次(可能是临时PG连接问题)。
    降级: 重试仍失败则使用上一交易日因子值(风控标记为"stale")。
    """
    for attempt in range(2):
        try:
            async with session.begin():
                factor_df = await factor_engine.calculate_all(date)
                await bulk_upsert_factors(date, factor_df)
                logger.info(f"因子计算成功: {date}, {len(factor_df)}行")
                return
        except Exception as e:
            logger.error(f"因子计算失败(attempt={attempt}): {e}")
            if attempt == 0:
                await asyncio.sleep(5)

    # 两次都失败: 降级处理
    logger.critical(f"因子计算降级: 使用上一交易日数据")
    await notify_p0(f"因子计算失败，降级使用{prev_trade_date}数据")
    await copy_previous_factors(prev_trade_date, date)
```

### 4.6 前端数据流架构

```
┌─────────────────────────────────────────────────────────┐
│  React 18 Application                                    │
│                                                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │  React Query  │  │   Zustand    │  │  Socket.IO   │  │
│  │  (服务端状态)  │  │  (客户端状态) │  │  (实时推送)   │  │
│  │              │  │              │  │              │  │
│  │ - API数据缓存 │  │ - UI状态     │  │ - 回测进度   │  │
│  │ - 自动重试    │  │ - 用户偏好   │  │ - 挖掘进度   │  │
│  │ - 后台刷新    │  │ - 市场切换   │  │ - Pipeline   │  │
│  │ - staleTime  │  │ - 主题/涨跌色 │  │ - 通知推送   │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  │
│         │                 │                 │           │
│         └─────────────────┼─────────────────┘           │
│                           │                             │
│              ┌────────────▼────────────┐                │
│              │     Page Components     │                │
│              │   (12页面 + 子视图)      │                │
│              └─────────────────────────┘                │
└─────────────────────────────────────────────────────────┘
         │ HTTP                        │ WebSocket
┌────────▼────────────────────────────▼───────────────────┐
│  FastAPI Backend                                         │
│  REST API (57端点) + Socket.IO Server (5通道)            │
└─────────────────────────────────────────────────────────┘
```

### 4.7 前后端通信模式

| 模式 | 技术 | 适用场景 | 示例 |
|------|------|---------|------|
| REST | Axios + React Query | 读写CRUD，80%的交互 | 策略CRUD、因子列表、参数配置 |
| WebSocket | Socket.IO | 长时间运行任务进度 | 回测运行、GP进化、Pipeline |
| WebSocket | Socket.IO | 实时通知 | 系统告警、审批、外汇行情 |
| SSE | — | 暂不使用(Socket.IO覆盖) | — |

**WebSocket通道(DEV_FRONTEND_UI §11)**:
```
/ws/backtest/{runId}      — 回测进度/实时净值/运行日志
/ws/factor-mine/{taskId}  — GP进化曲线/候选列表/完成通知
/ws/pipeline/{runId}      — Pipeline状态/Agent日志
/ws/notifications         — 全局通知推送(app级,始终连接)
/ws/forex/realtime        — 外汇实时行情(Phase 2)
```

---

## 5. 接口规格

### 5.1 FactorClassifier

```python
# 文件: backend/engines/factor_classifier.py

class StrategyType(str, Enum):
    RANKING = "ranking"           # 月度截面排序 Top-N
    FAST_RANKING = "fast_ranking" # 周度截面排序 Top-N
    EVENT = "event"               # 事件触发加减仓
    MODIFIER = "modifier"         # 调节型，不独立选股

@dataclass
class ClassificationResult:
    factor_name: str
    strategy_type: StrategyType
    frequency: str                    # "daily"/"weekly"/"monthly"/"event"
    confidence: float                 # 0-1
    reasoning: str                    # 分类理由的文字说明
    ic_decay_halflife: float          # IC衰减半衰期(天)
    signal_kurtosis: float            # 信号分布峰度
    signal_skewness: float            # 信号分布偏度
    feature_vector: list[float]       # 用于分类的特征向量(调试用)

class FactorClassifier:
    """因子→策略路由分类器。

    根据因子的IC衰减特性和信号分布形态，自动推荐最适合的策略框架。

    分类逻辑:
    1. 计算ic_decay半衰期 → 决定调仓频率
    2. 分析截面信号分布 → 区分连续型/稀疏型/条件型
    3. 综合判定 → RANKING/FAST_RANKING/EVENT/MODIFIER

    阈值说明:
    - FAST_DECAY_THRESHOLD: 半衰期<5天的因子IC衰减太快，需要周度调仓
    - SLOW_DECAY_THRESHOLD: 半衰期>15天的因子适合月度甚至季度
    - SPARSE_KURTOSIS: 峰度>5.0说明信号分布有尖峰厚尾，可能是事件型
    """

    FAST_DECAY_THRESHOLD: float = 5.0    # 快衰减阈值(交易日)
    SLOW_DECAY_THRESHOLD: float = 15.0   # 慢衰减阈值(交易日)
    SPARSE_KURTOSIS: float = 5.0         # 稀疏分布峰度阈值
    MIN_CONFIDENCE: float = 0.6          # 最低置信度，低于此值标记为uncertain

    def classify(self, factor_name: str, factor_values: pd.DataFrame,
                 forward_returns: pd.DataFrame) -> ClassificationResult:
        """分类单个因子。

        Args:
            factor_name: 因子名称
            factor_values: DataFrame(index=date, columns=symbol_id, values=因子值)
            forward_returns: DataFrame(与factor_values同结构，值为forward超额收益)

        Returns:
            ClassificationResult

        Raises:
            ValueError: factor_values为空或全NaN
            ValueError: forward_returns与factor_values日期不对齐
        """
        ...

    def classify_batch(self, factors: dict[str, pd.DataFrame],
                       forward_returns: pd.DataFrame) -> dict[str, ClassificationResult]:
        """批量分类多个因子。

        Args:
            factors: {因子名: 因子值DataFrame}
            forward_returns: 共享的forward return DataFrame

        Returns:
            {因子名: ClassificationResult}
        """
        ...

    def _compute_ic_decay(self, factor_values: pd.DataFrame,
                          forward_returns: pd.DataFrame,
                          max_lag: int = 30) -> tuple[np.ndarray, float]:
        """计算IC衰减曲线和半衰期。

        Returns:
            (ic_curve: shape=(max_lag,), halflife: float)
        """
        ...

    def _analyze_signal_distribution(self, factor_values: pd.DataFrame
                                      ) -> tuple[float, float, str]:
        """分析截面信号分布形态。

        Returns:
            (kurtosis, skewness, distribution_type: "normal"/"sparse"/"bimodal")
        """
        ...
```

**使用示例**:
```python
classifier = FactorClassifier()

# 单因子分类
result = classifier.classify("reversal_20", reversal_data, fwd_returns)
print(f"{result.factor_name}: {result.strategy_type.value} ({result.frequency})")
print(f"  半衰期: {result.ic_decay_halflife:.1f}天, 置信度: {result.confidence:.2f}")
# 输出: reversal_20: ranking (monthly)
#        半衰期: 12.3天, 置信度: 0.85

# 批量分类5个Active因子
results = classifier.classify_batch(active_factors, fwd_returns)
for name, r in results.items():
    print(f"{name}: {r.strategy_type.value} → {r.frequency}")
```

### 5.2 ModifierBase ABC

```python
# 文件: backend/engines/modifiers/base_modifier.py

@dataclass
class ModifierResult:
    """Modifier评估结果。

    scale_factor: 全局仓位缩放系数
        - 1.0 = 不调节
        - 0.7 = 降仓30%(多余资金转现金)
        - 1.2 = 增仓20%(使用现金缓冲)
        - 硬限制: clip到[SCALE_CLIP_LOW, SCALE_CLIP_HIGH]

    per_stock_adj: 个股级别调节(可选)
        - {"600519": 1.1, "000001": 0.8} = 茅台增10%，平安降20%
        - None表示不做个股调节，仅使用scale_factor

    confidence: Modifier对自身判断的置信度
        - 0.0~1.0, 低置信度时CompositeStrategy可选择忽略
    """
    scale_factor: float           # 全局仓位缩放 (0.3 ~ 1.5)
    per_stock_adj: Optional[dict[str, float]] = None  # 个股级调节
    reason: str = ""              # 触发原因描述(写入日志)
    confidence: float = 1.0       # 判断置信度
    raw_signal: float = 0.0       # 原始信号值(调试用)

class ModifierBase(ABC):
    """Modifier抽象基类。

    所有Modifier必须实现:
    1. should_evaluate(): 在当前日期是否需要评估(频率控制)
    2. evaluate(): 给定上下文和核心权重，返回调节结果

    Modifier不选股，只调节核心策略的权重分配。

    约束:
    - scale_factor硬限制在[0.3, 1.5]，防止极端调节
    - per_stock_adj总和变化≤20%
    - 多个Modifier按列表顺序叠加(后面的在前面的基础上调节)
    """

    SCALE_CLIP_LOW: float = 0.3   # scale_factor下限(最多降仓70%)
    SCALE_CLIP_HIGH: float = 1.5  # scale_factor上限(最多加仓50%)

    @abstractmethod
    def should_evaluate(self, current_date: date) -> bool:
        """判断在current_date是否需要评估此Modifier。

        频率控制示例:
        - RegimeModifier: 每日→True
        - VwapModifier: 仅周五→True
        - EventModifier: 有新事件信号→True
        """
        ...

    @abstractmethod
    def evaluate(self, context: StrategyContext,
                 core_weights: dict[str, float]) -> ModifierResult:
        """评估并返回调节结果。

        Args:
            context: 包含当前日期/行情/因子值/持仓/风控状态的上下文
            core_weights: 核心策略产出的{symbol: weight}

        Returns:
            ModifierResult

        注意: evaluate()不应修改core_weights本身，修改由CompositeStrategy统一应用。
        """
        ...

    def clip_scale(self, scale: float) -> float:
        """安全裁剪scale_factor到合法范围。"""
        return max(self.SCALE_CLIP_LOW, min(self.SCALE_CLIP_HIGH, scale))
```

**RegimeModifier实现示例**:
```python
# 文件: backend/engines/modifiers/regime_modifier.py

class RegimeModifier(ModifierBase):
    """基于波动率regime的全仓位缩放Modifier。

    逻辑: 当20日波动率超过中位数baseline的1.5倍时，降仓至70%。
    实现已有基础: vol_regime.py中的regime检测逻辑可复用。
    """

    def __init__(self, vol_threshold: float = 1.5,
                 low_scale: float = 0.7,
                 lookback: int = 60):
        self.vol_threshold = vol_threshold  # 触发降仓的波动率倍数
        self.low_scale = low_scale          # 高波时缩放系数
        self.lookback = lookback            # 波动率baseline计算窗口

    def should_evaluate(self, current_date: date) -> bool:
        return True  # 每日评估

    def evaluate(self, context: StrategyContext,
                 core_weights: dict[str, float]) -> ModifierResult:
        vol_ratio = context.current_vol / context.median_vol
        if vol_ratio > self.vol_threshold:
            return ModifierResult(
                scale_factor=self.low_scale,
                reason=f"高波动regime: vol_ratio={vol_ratio:.2f}>{self.vol_threshold}",
                confidence=min(1.0, (vol_ratio - self.vol_threshold) / 0.5),
                raw_signal=vol_ratio,
            )
        return ModifierResult(scale_factor=1.0, reason="正常regime")
```

### 5.3 CompositeStrategy

```python
# 文件: backend/engines/strategies/composite.py

class CompositeStrategy(BaseStrategy):
    """核心策略+Modifier叠加的组合策略。

    不同于多策略资金拆分(DESIGN_V5原设计)，CompositeStrategy保持单一核心策略
    使用100%资金，Modifier只调节权重，不独立选股。

    执行流程:
    Step 1: core_strategy.generate_signals() → 基础权重
    Step 2: 逐个Modifier评估叠加(仅should_evaluate为True的)
    Step 3: 权重归一化(总和=1-cash_buffer, 单股≤15%, 行业≤25%)
    Step 4: 风控检查后返回最终权重

    关键设计:
    - Modifier按列表顺序叠加，顺序可通过配置调整
    - 非调仓日: 核心策略不重算(用上期持仓)，Modifier仍然每日评估
    - 所有Modifier的scale_factor叠加: final_scale = prod(all_scales)
    """

    def __init__(self, core_strategy: BaseStrategy,
                 modifiers: list[ModifierBase],
                 cash_buffer: float = 0.03,
                 max_single_stock: float = 0.15,
                 max_industry: float = 0.25):
        self.core_strategy = core_strategy
        self.modifiers = modifiers
        self.cash_buffer = cash_buffer
        self.max_single_stock = max_single_stock
        self.max_industry = max_industry

    def generate_signals(self, context: StrategyContext) -> dict[str, float]:
        """生成组合信号。

        Args:
            context: 策略上下文(日期/行情/因子/持仓/风控)

        Returns:
            {symbol: weight} 最终目标权重
        """
        # Step 1: 核心策略
        core_weights = self.core_strategy.generate_signals(context)

        # Step 2: Modifier叠加
        cumulative_scale = 1.0
        modifier_log = []
        for modifier in self.modifiers:
            if modifier.should_evaluate(context.current_date):
                result = modifier.evaluate(context, core_weights)
                cumulative_scale *= result.scale_factor
                if result.per_stock_adj:
                    core_weights = self._apply_per_stock(core_weights, result.per_stock_adj)
                modifier_log.append((modifier.__class__.__name__, result))

        # 应用全局缩放
        core_weights = {k: v * cumulative_scale for k, v in core_weights.items()}

        # Step 3: 归一化
        target_sum = 1.0 - self.cash_buffer
        core_weights = self._normalize(core_weights, target_sum)
        core_weights = self._apply_constraints(core_weights, context)

        # Step 4: 记录日志
        self._log_modifier_actions(context.current_date, modifier_log)

        return core_weights

    def _normalize(self, weights: dict[str, float], target_sum: float) -> dict[str, float]:
        """归一化权重使总和等于target_sum。"""
        ...

    def _apply_constraints(self, weights: dict[str, float],
                           context: StrategyContext) -> dict[str, float]:
        """应用单股上限+行业上限约束。"""
        ...

    def _apply_per_stock(self, weights: dict[str, float],
                         adjustments: dict[str, float]) -> dict[str, float]:
        """应用个股级别调节。"""
        ...

    def _log_modifier_actions(self, date: date,
                              log: list[tuple[str, ModifierResult]]) -> None:
        """记录Modifier触发日志到modifier_action_log表。"""
        ...
```

**集成示例**:
```python
# 构建CompositeStrategy
from backend.engines.strategies.equal_weight import EqualWeightStrategy
from backend.engines.modifiers.regime_modifier import RegimeModifier

core = EqualWeightStrategy(
    factors=["turnover_mean_20", "volatility_20", "reversal_20", "amihud_20", "bp_ratio"],
    top_n=15, rebalance_freq="monthly", industry_cap=0.25
)
modifiers = [RegimeModifier(vol_threshold=1.5, low_scale=0.7)]
composite = CompositeStrategy(core, modifiers, cash_buffer=0.03)

# 回测中使用
weights = composite.generate_signals(context)
# 输出: {"600519": 0.063, "000001": 0.065, ...} (总和≈0.97)
```

### 5.4 Factor Gate Pipeline

```python
# 文件: backend/engines/factor_gate.py

class GateStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"    # 条件通过(需额外经济学解释)

@dataclass
class GateCheck:
    """单个Gate的检查结果。"""
    gate_id: str              # "G1"~"G8"
    gate_name: str            # 人类可读名称
    status: GateStatus
    value: float              # 实际测量值
    threshold: float          # 阈值
    details: str              # 详细说明

@dataclass
class GateResult:
    """Gate Pipeline整体结果。"""
    factor_name: str
    passed: bool                                          # 全部PASS才True
    gate_results: list[GateCheck]                         # G1-G8逐项结果
    classification: Optional[ClassificationResult] = None  # G8后自动分类
    failure_reason: Optional[dict] = None                  # 结构化失败原因
    execution_time_sec: float = 0.0                       # 总执行时间

class FactorGatePipeline:
    """因子质量关卡管道。

    8个Gate按顺序执行，短路策略: 任一Gate FAIL则后续不执行(节省计算)。
    WARN状态不短路，继续执行但在结果中标注。

    Gate详细说明:
    G1: Success   — 因子计算无错误，执行时间<10秒
    G2: Coverage  — 因子有效值覆盖>1000只股票/截面(Universe约5000)
    G3: IC        — 全样本均值IC > 0.015(宽松入池门槛)
    G4: t-stat    — t > 2.5(Harvey Liu Zhu 2016硬性下限)
                    t 2.0-2.5 → WARN(需经济学解释)
                    t < 2.0 → FAIL
    G5: Neutral   — 中性化(市值+行业)后IC不归零(排除虚假因子)
    G6: Dedup     — AST结构去重 + 与现有因子Spearman相关性<0.7
    G7: Stability — 滚动12月IC变异系数<2.0(信号稳定性)
    G8: Turnover  — 隐含换手率<200%年化(过高换手说明噪声信号)
    """

    # Gate阈值配置
    G1_TIMEOUT_SEC: float = 10.0
    G2_MIN_COVERAGE: int = 1000
    G3_MIN_IC: float = 0.015
    G4_HARD_T: float = 2.5
    G4_SOFT_T: float = 2.0
    G5_NEUTRAL_IC_MIN: float = 0.005
    G6_MAX_CORR: float = 0.7
    G7_MAX_CV: float = 2.0
    G8_MAX_TURNOVER: float = 2.0  # 200%年化

    def run_gate(self, factor_name: str, factor_data: pd.DataFrame,
                 forward_returns: pd.DataFrame,
                 existing_factors: Optional[dict[str, pd.DataFrame]] = None,
                 short_circuit: bool = True) -> GateResult:
        """运行完整Gate Pipeline。

        Args:
            factor_name: 因子名称
            factor_data: 因子值DataFrame
            forward_returns: Forward超额收益
            existing_factors: 已有因子(G6去重用)
            short_circuit: 是否启用短路(默认True)

        Returns:
            GateResult(passed=True当且仅当所有Gate PASS或WARN)
        """
        ...

    def run_single_gate(self, gate_id: str, ...) -> GateCheck:
        """运行单个Gate(调试用)。"""
        ...
```

**Gate Pipeline输出示例**:
```
Factor: mf_divergence
G1: PASS  (execution=2.3s < 10.0s)
G2: PASS  (coverage=4,231 > 1,000)
G3: PASS  (IC=0.091 > 0.015)
G4: PASS  (t=3.82 > 2.5)
G5: PASS  (neutral_IC=0.065 > 0.005)
G6: PASS  (max_corr=0.23 < 0.7 vs turnover_mean_20)
G7: PASS  (IC_CV=0.89 < 2.0)
G8: PASS  (turnover=147% < 200%)
Overall: PASS (8/8)
Classification: RANKING (monthly), confidence=0.82
```

### 5.5 Mining Pipeline Orchestrator

```python
# 文件: backend/engines/mining/pipeline_orchestrator.py

class PipelineState(str, Enum):
    SELECT_ENGINE = "select_engine"          # Node 1: Thompson Sampling选引擎
    GENERATE_CANDIDATES = "generate_candidates"  # Node 2: 引擎产出候选因子
    SANDBOX_EXECUTE = "sandbox_execute"      # Node 3: 沙箱安全执行
    GATE_PIPELINE = "gate_pipeline"          # Node 4: G1-G8质量关卡
    CLASSIFY = "classify"                    # Node 5: FactorClassifier分类
    BACKTEST = "backtest"                    # Node 6: 推荐策略框架回测
    APPROVAL_QUEUE = "approval_queue"        # Node 7: 人工审批队列
    ACTIVATE = "activate"                    # Node 8: 激活(全历史回填+PT)

@dataclass
class PipelineRun:
    """Pipeline单次运行的状态记录。"""
    run_id: str
    state: PipelineState
    engine_used: str                          # bruteforce/gp/llm
    candidates_generated: int = 0
    candidates_passed_gate: int = 0
    candidates_approved: int = 0
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    error: Optional[str] = None

class PipelineOrchestrator:
    """因子挖掘Pipeline编排器。

    管理8节点状态机的完整生命周期:
    1. 选择引擎(Thompson Sampling或手动指定)
    2. 生成候选因子(时间预算限制)
    3. 沙箱安全执行(AST检查+subprocess隔离)
    4. Gate Pipeline质量检查(G1-G8，短路策略)
    5. FactorClassifier自动分类
    6. 用推荐策略框架回测(SimBroker, 最近1年快速验证)
    7. 通过因子进入审批队列(钉钉通知+Web界面)
    8. 审批通过后激活(全历史回填factor_values + PT观察)

    关键约束:
    - 时间预算: 默认2小时，超时后停止生成但继续处理已有候选
    - 内存预算: 单因子计算<2GB，总pipeline<8GB
    - 并发: 同一时间只运行一个Pipeline实例
    - 通知: 每个状态转换通过WebSocket推送到前端
    """

    def __init__(self, thompson: ThompsonScheduler,
                 gate: FactorGatePipeline,
                 classifier: FactorClassifier,
                 sandbox: FactorSandbox):
        self.thompson = thompson
        self.gate = gate
        self.classifier = classifier
        self.sandbox = sandbox

    async def run_pipeline(self, engine: Optional[str] = None,
                           budget_hours: float = 2.0) -> list[FactorCandidate]:
        """运行完整Pipeline。

        Args:
            engine: 指定引擎名称(None=Thompson Sampling自动选择)
            budget_hours: 时间预算(小时)

        Returns:
            通过审批的因子候选列表

        WebSocket events:
            state_change: {from: "select_engine", to: "generate_candidates"}
            candidate: {name: "factor_xxx", status: "passed_gate"}
            approval_required: {factor_name: "factor_xxx", ic: 0.045}
            complete: {total: 150, passed: 3, approved: 1}
        """
        ...

    async def _notify_state_change(self, old_state: PipelineState,
                                    new_state: PipelineState,
                                    run: PipelineRun) -> None:
        """通过WebSocket推送状态变化。"""
        ...
```

### 5.6 DeepSeek Model Router

```python
# 文件: backend/engines/mining/model_router.py

class TaskType(str, Enum):
    IDEA_GENERATION = "idea_generation"    # 因子Idea创意生成
    FACTOR_CODING = "factor_coding"        # 因子代码编写
    EVAL_ANALYSIS = "eval_analysis"        # 统计评估分析
    DIAGNOSIS = "diagnosis"                # 绩效衰退诊断

@dataclass
class ModelConfig:
    """模型配置。"""
    model_name: str              # 模型标识符
    api_endpoint: str            # API地址或"local"
    local: bool = False          # 是否本地部署
    max_tokens: int = 4096
    temperature: float = 0.7
    cost_per_1k_tokens: float = 0.0  # 本地=0
    timeout_sec: int = 60

class ModelRouter:
    """AI模型智能路由器。

    根据任务类型自动选择最合适的模型:
    - Idea生成: 需要深度推理+中文金融知识 → DeepSeek-R1 (API)
    - 因子编码: 代码生成为主，延迟敏感 → Qwen3-Coder (本地RTX 5070)
    - 评估分析: 快速统计报告 → DeepSeek-V3.2 (API，速度快)
    - 诊断分析: 复杂根因分析 → DeepSeek-R1 (API)

    Fallback机制:
    - 本地模型不可用(显存不足/ollama未启动) → 切API
    - API超时(>60秒) → 重试1次 → 切备用模型 → 报错
    - 月度成本监控: 超$100/月 → P1告警

    R7研究结论:
    - DeepSeek-R1: 中文金融+推理能力最强，API ~$0.55/1M tokens
    - Qwen3-Coder-30B-A3B: 代码生成质量高，本地Q4量化~4GB VRAM
    - DeepSeek-V3.2: 速度最快(10x R1)，适合轻量分析
    """

    ROUTE_TABLE: dict[TaskType, ModelConfig] = {
        TaskType.IDEA_GENERATION: ModelConfig(
            "deepseek-r1", "https://api.deepseek.com/v1",
            temperature=0.8, max_tokens=8192, cost_per_1k_tokens=0.55
        ),
        TaskType.FACTOR_CODING: ModelConfig(
            "qwen3-coder-30b-a3b", "http://localhost:11434",
            local=True, temperature=0.3, max_tokens=4096
        ),
        TaskType.EVAL_ANALYSIS: ModelConfig(
            "deepseek-v3.2", "https://api.deepseek.com/v1",
            temperature=0.5, max_tokens=4096, cost_per_1k_tokens=0.14
        ),
        TaskType.DIAGNOSIS: ModelConfig(
            "deepseek-r1", "https://api.deepseek.com/v1",
            temperature=0.6, max_tokens=8192, cost_per_1k_tokens=0.55
        ),
    }

    def route(self, task_type: TaskType) -> ModelConfig:
        """获取任务对应的模型配置。"""
        config = self.ROUTE_TABLE[task_type]
        if config.local and not self._is_local_available():
            return self._get_fallback(task_type)
        return config

    def _is_local_available(self) -> bool:
        """检查本地ollama是否运行且显存充足。"""
        ...

    def _get_fallback(self, task_type: TaskType) -> ModelConfig:
        """本地不可用时的API fallback。"""
        ...

    def get_monthly_cost(self) -> float:
        """计算当月API累计成本。"""
        ...
```

### 5.7 WebSocket协议规格

> 对应DEV_FRONTEND_UI.md §11

```python
# 文件: backend/app/websocket/server.py (python-socketio)

# 消息格式 (所有通道统一)
{
    "type": "progress" | "data" | "error" | "complete",
    "payload": { ... },
    "timestamp": "2026-03-28T17:00:00+08:00"
}

# 通道1: /ws/backtest/{runId}
# 事件: progress(percentage/eta), metric(sharpe/mdd实时), log(text), complete(result_id)

# 通道2: /ws/factor-mine/{taskId}
# 事件: progress(generated/passed/failed), evolution(generation/best_fitness), candidate(name/ic), complete

# 通道3: /ws/pipeline/{runId}
# 事件: state_change(from/to), agent_log(agent/message), approval_required(factor_name), complete

# 通道4: /ws/notifications (app级，始终连接)
# 事件: notification(level/title/content/link)

# 通道5: /ws/forex/realtime (Phase 2)
# 事件: tick(symbol/bid/ask), position_update(pnl), margin_update(level)
```

### 5.8 前端状态Store设计

```typescript
// Zustand stores

// store/useAuthStore.ts — 用户偏好
interface AuthStore {
  theme: 'dark' | 'light';
  upDownColor: 'cn' | 'intl';
  market: 'astock' | 'forex';
  setMarket: (m: string) => void;
}

// store/useNotificationStore.ts — 通知状态
interface NotificationStore {
  unreadCount: number;
  notifications: Notification[];
  markRead: (id: string) => void;
}

// store/useBacktestStore.ts — 回测会话状态
interface BacktestStore {
  activeRunId: string | null;
  config: BacktestConfig | null;
  setConfig: (c: BacktestConfig) => void;
}

// store/useMiningStore.ts — 挖掘任务状态
interface MiningStore {
  activeTasks: MiningTask[];
  gpProgress: GPProgress | null;
}

// React Query用于所有API数据:
// useQuery(['factors'], fetchFactors)
// useQuery(['backtest', runId, 'result'], fetchResult)
// useMutation(submitBacktest)
```

---

## 6. DEV_FRONTEND_UI.md更新计划

> DEV_FRONTEND_UI.md(695行)是前端实现的权威设计文档。R1-R7研究结果引入了新的架构组件
> (FactorClassifier/CompositeStrategy/Gate Pipeline/三引擎/ModelRouter)，需要同步更新UI设计。
> 以下列出每处更新的当前内容、新增内容和具体变更说明。

### 6.1 策略相关页面更新 (§2.x)

**§2.1 策略工作台** → Sprint 1.14
- **当前**: 单一策略编辑(因子面板+参数面板+AI助手)
- **新增**:
  - CompositeStrategy配置面板: core策略选择 + modifier列表(拖拽排序)
  - Modifier参数面板: scale_clip范围/评估频率/启用开关
  - 策略类型标签: Ranking / FastRanking / Event / Composite
- **UI变更**: 左侧Tab从"因子列表/参数配置"扩展为"因子列表/参数配置/Modifier配置/组合预览"

**§2.2 回测配置** → Sprint 1.14
- **当前**: 6个Tab(基本/数据/策略/费用/风控/高级)
- **新增**:
  - Tab 3策略: 增加策略类型选择下拉框(Ranking/FastRanking/Event/Composite)
  - Tab 3策略: 根据策略类型动态显示对应参数(如FastRanking显示周度参数)
  - Tab 6高级: 动态仓位开关与Modifier联动(启用后自动添加RegimeModifier)
- **UI变更**: Tab 3从静态参数面板变为动态表单，根据strategy_type切换字段

**§2.4 回测结果** → Sprint 1.15
- **当前**: 8个Tab(概览/收益/交易/持仓/因子/风险/成本/仓位)
- **新增**:
  - Tab 8仓位分析: 增加Modifier触发时间线(在持仓变化图上叠加regime切换标记)
  - 新增Tab 9: 策略归因(core策略 vs modifier贡献分解，堆叠面积图)
- **UI变更**: Tab导航从8个增加到9个，Tab 9使用ECharts堆叠面积图

### 6.2 因子相关页面更新 (§3.x)

**§3.1 因子实验室** → Sprint 1.17
- **当前**: 5个模式Tab(手动输入/表达式/GP遗传/LLM/批量枚举)
- **新增**:
  - 模式C GP参数: 岛屿数量(默认4)×每岛种群(200-500)，复杂度惩罚系数(w4)配置
  - 模式D LLM: Model Router选择面板(DeepSeek-R1/V3.2/Qwen3-Coder)
  - 模式D LLM: 3-Agent链路可视化(Idea→Factor→Eval进度条)
- **UI变更**: 模式C增加"高级参数"折叠面板；模式D增加模型选择下拉框和Agent进度条

**§3.2 挖掘任务中心** → Sprint 1.17
- **当前**: 基础进度展示(任务列表+状态)
- **新增**:
  - Thompson Sampling可视化: 三引擎的Beta分布后验图(ECharts折线图)
  - 引擎切换历史: 时间轴展示每次Pipeline选择了哪个引擎及理由
  - 引擎产出对比: BruteForce/GP/LLM各自的因子产出数/通过率柱状图
- **UI变更**: 页面从单一任务列表变为左列(任务列表)+右列(引擎统计+Thompson分布)

**§3.3 因子评估** → Sprint 1.16
- **当前**: 6+6 Tab(IC分析/分组收益/衰减/相关性/分年度/分状态 × 基础/详细)
- **新增**:
  - Gate Pipeline G1-G8结果展示: 8个圆形指示灯(绿PASS/红FAIL/黄WARN)
  - FactorClassifier分类结果: strategy_type标签 + frequency + confidence进度条
  - 分类特征向量雷达图(ic_decay/kurtosis/skewness三维)
- **UI变更**: 页面顶部新增"Gate结果"横幅(8个圆形指示灯) + "分类结果"卡片

**§3.4 因子库** → Sprint 1.16
- **当前**: 基础表格(因子名/IC/IR/状态/健康度)
- **新增**:
  - 新增列: strategy_type(Ranking/FastRanking/Event/Modifier)
  - 新增列: Gate得分(PASS数/总Gate数，如 "7/8")
  - 新增列: 推荐调仓频率(daily/weekly/monthly)
  - 筛选器: 按strategy_type筛选
- **UI变更**: 表格从5列扩展到8列，增加strategy_type筛选器

### 6.3 AI/Pipeline相关页面更新 (§4.x)

**§4.1 Pipeline控制台** → Sprint 1.18
- **当前**: 8节点流程图(DESIGN_V5原版)
- **新增**:
  - 更新为R2精简版8节点(SELECT_ENGINE→GENERATE→SANDBOX→GATE→CLASSIFY→BACKTEST→APPROVAL→ACTIVATE)
  - Thompson Sampling引擎分配可视化(饼图: 近期各引擎被选择的比例)
  - 审批队列: approve/reject/hold三按钮 + 审批历史
- **UI变更**: 流程图重新设计以匹配R2 Pipeline，增加右侧引擎统计面板

**§4.2 Agent配置** → Sprint 1.18
- **当前**: 4个Agent Tab(Idea/Factor/Eval/Diagnosis)
- **新增**:
  - 更新模型名称: DeepSeek-R1/DeepSeek-V3.2/Qwen3-Coder-30B-A3B(R7选型结果)
  - ModelRouter配置面板: 每个Agent可切换模型、调整temperature/max_tokens
  - 本地模型状态: Qwen3运行状态/显存占用/推理速度
- **UI变更**: 每个Agent Tab增加"模型配置"子面板(下拉选择+参数滑块)

### 6.4 系统级页面更新 (§5.x, §8, §10, §11)

**§5.1 系统设置** → Sprint 1.19
- **当前**: 5个Tab(数据源/通知/调度/健康/偏好)
- **新增**:
  - Tab 1数据源: 增加DeepSeek API密钥配置(密码输入框+验证按钮)
  - Tab 1数据源: 增加本地Qwen3状态展示(运行/停止/显存使用)
  - 新增Tab 6: Modifier参数(RegimeModifier阈值/VwapModifier参数/全局scale_clip)
- **UI变更**: Tab从5个增加到6个

**§8 总览页** → Sprint 1.19
- **当前**: 总组合概览(NAV+持仓+因子) + 市场快照
- **新增**:
  - CompositeStrategy状态卡片: 核心策略名称/Modifier列表/当前scale_factor
  - Modifier最近触发记录: 最近5次触发的日期/原因/scale变化
  - 策略类型分布: 活跃因子按strategy_type分类的饼图
- **UI变更**: Dashboard右上角增加"策略状态"卡片(GlassCard)

**§10 组件规范** → Sprint 1.16
- **当前**: GlassCard / MetricCard / StatusBadge / NAVChart / PositionTable
- **新增**: 4个新组件
  - `ModifierStatusCard`: 显示Modifier名称/当前scale/最近触发(GlassCard嵌入)
  - `GatePipelineResult`: 8个圆形指示灯+每Gate详细hover tooltip
  - `ClassifierBadge`: strategy_type标签(颜色编码: Ranking蓝/Event橙/Modifier绿)
  - `ThompsonChart`: 三引擎Beta分布后验曲线(ECharts)

**§11 实时数据** → Sprint 1.15
- **当前**: 3种更新(REST轮询/WebSocket推送/SSE)
- **新增**:
  - Modifier状态变化推送: RegimeModifier切换regime时通过`/ws/notifications`推送
  - 推送消息格式: `{type: "modifier_trigger", modifier: "regime", old_scale: 1.0, new_scale: 0.7}`
  - 前端处理: ModifierStatusCard自动刷新 + Toast通知

---

## 7. Sprint计划（10个Sprint = 10个PR边界）

> **关键变更**: 每个Sprint必须同时交付后端和前端成果。不允许纯后端Sprint。

### Sprint 1.13: 前端基础设施 + 策略框架核心 (2周)

**目标**: 前端可导航所有页面(即使空)；策略框架核心组件可用。

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | React Router v6 + 12页面路由 + 侧边栏导航 | `frontend/src/router.tsx` + `Layout.tsx` | TrD | 1.5 |
| 2 | Zustand stores (auth/notification/backtest/mining) | `frontend/src/store/*.ts` | TrD | 1 |
| 3 | shadcn/ui安装 + GlassCard/MetricCard/Button基础组件 | `frontend/src/components/ui/*` | TrD | 1.5 |
| 4 | Axios API client层 + React Query Provider | `frontend/src/api/client.ts` + `QueryProvider` | TrD | 1 |
| 5 | 12页面stub(标题+空状态) + 面包屑 | `frontend/src/pages/*.tsx` | TrD | 1 |
| 6 | FactorClassifier实现 | `backend/engines/factor_classifier.py` | TrA | 2 |
| 7 | FastRankingStrategy(周度) | `backend/engines/strategies/fast_ranking.py` | TrA | 1.5 |
| 8 | EventStrategy框架 | `backend/engines/strategies/event_strategy.py` | TrA | 2 |
| 9 | ModifierBase + RegimeModifier | `backend/engines/modifiers/*.py` | TrA | 1.5 |
| 10 | CompositeStrategy编排器 | `backend/engines/strategies/composite.py` | TrA | 2 |
| 11 | FactorService + BacktestService wrapper | `backend/app/services/factor_service.py` + `backtest_service.py` | TrE | 1.5 |
| 12 | Alembic迁移配置 | `backend/alembic/` | TrE | 0.5 |
| 13 | 文档清理(删除过期文件) | — | — | 0.5 |

**成败标准**:
- [ ] 前端可在12个页面间导航(侧边栏+路由)，每页显示标题和空状态
- [ ] FactorClassifier对5个Active因子分类结果与R1预期一致
- [ ] CompositeStrategy(EqualWeight+RegimeModifier)回测可运行
- [ ] FactorService封装factor_engine，API可调用
- [ ] `ruff check` PASS + 现有测试不退化

**依赖关系**:
- 无前置Sprint依赖(首个Sprint)
- PT v1.1运行中: 不触碰`run_paper_trading.py`/`signal_engine.py`/`paper_broker.py`
- Alembic配置需要先确认PG连接参数(使用现有.env)

**风险与回滚**:
- 前端基础设施失败: React Router/Zustand是独立于后端的，不影响PT
- FactorClassifier分类不准: 不影响v1.1(仅新增文件)，可延后到1.15调优
- CompositeStrategy回测结果差: 正常，仅验证框架可运行，不要求优于v1.1

**新增测试**: ~30个(FactorClassifier单元+CompositeStrategy单元+Service wrapper)

---

### Sprint 1.14: 回测模块前端 + 因子挖掘Engine1 (2周)

**目标**: 从前端可配置和运行回测；BruteForce引擎产出第一批因子。

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | 策略工作台页面(因子面板+策略编辑+AI助手占位) | `frontend/src/pages/StrategyWorkspace.tsx` | TrD | 3 |
| 2 | 回测配置页面(6个Tab) | `frontend/src/pages/BacktestConfig.tsx` | TrD | 2.5 |
| 3 | 策略CRUD API补全 | `backend/app/api/strategies.py`(修改) | TrE | 1 |
| 4 | Factor Sandbox(AST安全检查+subprocess隔离) | `backend/engines/mining/factor_sandbox.py` | TrB | 2 |
| 5 | BruteForce引擎(50模板+参数网格) | `backend/engines/mining/bruteforce_engine.py` | TrB | 3 |
| 6 | AST去重器 | `backend/engines/mining/ast_dedup.py` | TrB | 1.5 |
| 7 | overnight_gap_cost + tiered_base_bps | `backend/engines/slippage_model.py`(修改) | TrC | 1.5 |

**成败标准**:
- [ ] 策略工作台可勾选因子、配置参数、保存策略
- [ ] 回测配置6个Tab可填写参数并点击"运行回测"(调用API)
- [ ] BruteForce产出 >= 5个通过G1-G3的因子候选
- [ ] 滑点模型三组件合计与PT实测64.5bps偏差 < 15%

**依赖关系**:
- Sprint 1.13: 前端基础设施(Router/Zustand/API client)必须就绪
- Sprint 1.13: FactorClassifier(用于策略类型选择下拉框的选项)
- 策略CRUD API: 已有基础版，本Sprint补全PUT/DELETE

**风险与回滚**:
- 前端策略工作台: 独立页面，不影响现有Dashboard
- BruteForce低产出: 调整模板和参数范围即可，Engine架构不变
- 滑点三组件偏差大: overnight_gap_cost是新增组件，回退=设为0(回到两组件)

**新增测试**: ~25个(Sandbox安全检查+BruteForce模板+AST去重+滑点分解)

---

### Sprint 1.15: 回测结果前端 + 策略验证 (2周)

**目标**: 前端完整回测流程(配置→运行→结果)；策略验证回测。

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | 回测运行监控页面(进度条+实时净值) | `frontend/src/pages/BacktestRunner.tsx` | TrD | 2 |
| 2 | 回测结果分析页面(8个Tab) | `frontend/src/pages/BacktestResults.tsx` | TrD | 3 |
| 3 | 策略库页面(列表+筛选+对比模式) | `frontend/src/pages/StrategyLibrary.tsx` | TrD | 2 |
| 4 | WebSocket基础设施(python-socketio + socket.io-client) | `backend/app/websocket/` + `frontend/src/hooks/useWebSocket.ts` | TrE | 2 |
| 5 | Factor Gate Pipeline G1-G8实现 | `backend/engines/factor_gate.py` | TrB | 2.5 |
| 6 | CompositeStrategy回测验证(v1.1+RegimeModifier) | `scripts/backtest_composite_v1.py` | TrA | 1.5 |
| 7 | PT信号回放验证器 | `scripts/pt_signal_replay.py` | TrC | 2 |
| 8 | structlog JSON结构化日志 | `backend/app/logging_config.py` | TrC | 1 |

**成败标准**:
- [ ] 前端完整回测流程: 配置→运行(WebSocket进度)→结果(8 Tab展示)
- [ ] 策略库可列出历史回测、筛选、2个策略对比
- [ ] Gate Pipeline G1-G8对已知因子判定与历史结论一致
- [ ] CompositeStrategy回测MDD优于纯v1.1(改善>5%)

**依赖关系**:
- Sprint 1.14: 回测配置页面(本Sprint扩展到运行+结果)
- Sprint 1.13: CompositeStrategy(本Sprint验证其回测表现)
- WebSocket: 首次引入Socket.IO，前后端同时建设

**风险与回滚**:
- WebSocket连接不稳: 降级方案=REST轮询(每2秒GET /api/backtest/{id}/progress)
- Gate Pipeline判定不一致: 逐Gate调参，FACTOR_TEST_REGISTRY.md有历史数据可对照
- CompositeStrategy MDD无改善: 不影响v1.1 PT，Modifier效果需长期验证
- 策略对比功能: 如API复杂度高可简化为只展示，不做交互对比

**新增测试**: ~30个(Gate G1-G8+WebSocket消息+回测API端到端+信号回放)

---

### Sprint 1.16: 因子模块前端 + GP最小闭环核心 (2周)

**目标**: 前端可查看因子库和评估报告；**Warm Start GP引擎+Gate+SimBroker反馈闭环跑通**。
**战略定位**: Step 2核心Sprint — 详见 `docs/GP_CLOSED_LOOP_DESIGN.md`

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | 因子库页面(表格+健康度面板+相关性热力图) | `frontend/src/pages/FactorLibrary.tsx` | TrD | 2.5 |
| 2 | 因子评估报告页面(6+6 Tab) | `frontend/src/pages/FactorEvaluation.tsx` | TrD | 3 |
| 3 | Factor API Router(library/report/health-check) | `backend/app/api/factors.py`(新) | TrE | 1.5 |
| 4 | **FactorDSL(Qlib Alpha158兼容算子集+表达式树+量纲约束)** | `backend/engines/mining/factor_dsl.py` | TrB | 2 |
| 5 | **Warm Start GP引擎(5因子模板初始化+岛屿模型+逻辑参数分离)** | `backend/engines/mining/gp_engine.py` | TrB | 3 |
| 6 | **QuickBacktester(GP适应度用1年快速回测)** | `backend/engines/mining/quick_backtester.py` | TrB | 1 |
| 7 | **GP适应度=SimBroker Sharpe×(1-复杂度)+正交性奖励** | `gp_engine.py`内 | TrB | 0.5 |

**成败标准**:
- [ ] 因子库展示5个Active因子状态/IC/IR/Gate得分
- [ ] 因子评估6 Tab(IC分析/分组收益/衰减/相关性/分年度/分状态)
- [ ] **GP引擎2小时内产出 >= 10个通过快速Gate(G1-G4)的因子候选**
- [ ] **其中 >= 3个通过完整Gate(G1-G8)**
- [ ] DSL支持 >= 20个算子
- [ ] **Warm Start首代适应度 > 随机初始化首代适应度(验证Warm Start有效)**

**依赖关系**:
- Sprint 1.15: Gate Pipeline(因子库展示Gate得分)
- Sprint 1.13: FactorClassifier(因子库展示strategy_type)
- Sprint 1.15: WebSocket(GP进化曲线实时推送，但本Sprint可用REST轮询备用)

**风险与回滚**:
- GP引擎产出低: R2预计~20因子/小时，2小时10个是保守目标；低于此则调整种群/适应度
- DSL算子不足: 优先实现高频使用的算子(ts_mean/ts_std/cs_rank/ts_corr等)
- GP训练不收敛: 增加子群多样性、降低交叉率、增加变异率

**新增测试**: ~25个(GP引擎+DSL算子+Factor API+因子库集成)

---

### Sprint 1.17: 因子挖掘前端 + GP闭环自动化 + LLM基础 (2周)

**目标**: GP闭环每周自动运行（Task Scheduler）；前端可监控挖掘进度；LLM基础链路。
**战略定位**: Step 2收尾 + Step 3起步 — 详见 `docs/GP_CLOSED_LOOP_DESIGN.md`

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | 因子实验室页面(GP/LLM/枚举模式) | `frontend/src/pages/FactorLab.tsx` | TrD | 3 |
| 2 | 挖掘任务中心页面(WebSocket进度) | `frontend/src/pages/MiningTaskCenter.tsx` | TrD | 2 |
| 3 | **GP Pipeline入口脚本(§6完整流程)** | `scripts/run_gp_pipeline.py` | TrB | 1.5 |
| 4 | **pipeline_runs + approval_queue表DDL+模型** | DDL_FINAL.sql + models/ | TrB | 1 |
| 5 | **GP每周Task Scheduler注册+钉钉通知** | `scripts/register_gp_task.ps1` | TrC | 0.5 |
| 6 | **跨轮次学习: 上轮Top因子→下轮种子+黑名单注入** | `gp_engine.py`(修改) | TrB | 1.5 |
| 7 | DeepSeek API客户端 | `backend/engines/mining/deepseek_client.py` | TrB | 1.5 |
| 8 | Idea Agent(假设生成，Step 3基础) | `backend/engines/mining/agents/idea_agent.py` | TrB | 2 |
| 9 | Mining API Router(mine/tasks/evaluate) | `backend/app/api/mining.py`(新) | TrE | 1 |
| 10 | **前置研究: 读AlphaForgeBench+AlphaPROBE论文** | 产出: LLM prompt模板+DAG剪枝策略 | TrA | 1 |

**成败标准**:
- [ ] **GP Pipeline每周自动运行(Task Scheduler)，无人工干预**
- [ ] **运行结果自动写入pipeline_runs + approval_queue**
- [ ] **钉钉自动通知候选因子**
- [ ] **第2轮GP种群初始化包含第1轮Top因子(跨轮次学习)**
- [ ] 因子实验室可切换GP/LLM模式并查看进度
- [ ] DeepSeek API连通，Idea Agent可生成因子假设

**依赖关系**:
- Sprint 1.15: WebSocket基础设施(GP进化实时推送)
- Sprint 1.16: GP引擎+DSL(因子实验室GP模式需要调用)
- Sprint 1.15: Factor Gate Pipeline(LLM产出进Gate验证)

**风险与回滚**:
- DeepSeek API不稳定: 本地Qwen3作为fallback，ModelRouter自动切换
- LLM产出质量低: 增加Idea Agent的knowledge注入(失败因子历史)
- RTX 5070显存不足: Qwen3-30B用Q4_K_M量化(约4GB)，如仍不够则纯API模式
- Monaco Editor集成: 如体积过大(5MB+)可延后，先用textarea+代码高亮

**新增测试**: ~20个(LLM Agent mock+ModelRouter+Thompson Sampling+Mining API)

---

### Sprint 1.18: AI Pipeline前端 + Pipeline编排 (2周)

**目标**: 前端可查看Pipeline状态和审批；Pipeline状态机编排三引擎。

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | Pipeline控制台页面(8节点流程图+审批队列) | `frontend/src/pages/PipelineConsole.tsx` | TrD | 3 |
| 2 | Agent配置页面(4 Agent Tab+模型配置) | `frontend/src/pages/AgentConfig.tsx` | TrD | 2 |
| 3 | PipelineOrchestrator(8节点状态机) | `backend/engines/mining/pipeline_orchestrator.py` | TrB | 3 |
| 4 | approval_queue表 + API | `backend/app/api/approval.py`(新) | TrB | 1.5 |
| 5 | Pipeline API Router | `backend/app/api/pipeline.py`(新) | TrE | 1.5 |
| 6 | 滑点分解脚本(三组件分析) | `scripts/slippage_decompose.py` | TrC | 1.5 |
| 7 | mining_knowledge表+失败记录 | `backend/app/models/mining_knowledge.py` | TrB | 1 |
| 8 | SHAP可解释性集成(LightGBM因子重要性+特征贡献) | `backend/engines/ml_explainer.py`(新) | TrC | 2 |
| 9 | LightGBM ranking loss(lambdarank+group+NDCG评估) | `backend/engines/ml_engine.py` | TrC | 2 |

**成败标准**:
- [ ] Pipeline控制台展示8节点状态流程图，当前节点高亮
- [ ] 审批队列支持approve/reject/hold三种操作
- [ ] PipelineOrchestrator端到端: BruteForce→Sandbox→Gate→分类→审批
- [ ] Agent配置可切换模型(DeepSeek-R1/V3.2/Qwen3)
- [ ] SHAP: LightGBM模型可输出因子重要性排序+单预测特征贡献分解
- [ ] LightGBM lambdarank: IC(rank correlation)作为评估指标，NDCG@15优于regression baseline

**依赖关系**:
- Sprint 1.17: LLM 3-Agent(Pipeline编排三引擎)
- Sprint 1.16: GP引擎(Pipeline的Engine 2)
- Sprint 1.14: BruteForce(Pipeline的Engine 1)
- Sprint 1.15: Gate Pipeline(Pipeline的Node 4)

**风险与回滚**:
- Pipeline状态机复杂: 先实现BruteForce单引擎流程，GP/LLM逐步接入
- 审批队列: 简化方案=钉钉通知+CLI审批(Web审批是增强项)
- mining_knowledge表设计: 可先用简单JSON字段，后续迭代结构化
- 流程图渲染: ECharts自定义图/reactflow二选一，reactflow更适合但体积较大

**新增测试**: ~20个(Pipeline状态机+审批流程+mining_knowledge+滑点分解)

---

### Sprint 1.19: 系统设置 + Dashboard增强 + 生产加固 (2周)

**目标**: 系统设置页面上线；Dashboard完善；生产基础设施就位。

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | 系统设置页面(5个Tab) | `frontend/src/pages/SystemSettings.tsx` | TrD | 3 |
| 2 | Dashboard增强(市场快照+行业分布+月度热力图) | `frontend/src/pages/Dashboard.tsx`(修改) | TrD | 2 |
| 3 | A股详情子视图 | `frontend/src/pages/DashboardAStock.tsx` | TrD | 1.5 |
| 4 | 通知系统前端(铃铛+Toast+通知中心) | `frontend/src/components/NotificationSystem.tsx` | TrD | 2 |
| 5 | System API Router(datasources/health/scheduler) | `backend/app/api/system.py`(新) | TrE | 1.5 |
| 6 | NSSM安装+服务化 | `scripts/nssm_setup.ps1` | TrC | 1 |
| 7 | PG备份自动化(7天滚动+月永久) | `scripts/pg_backup.py`(修改) | TrC | 1 |

**成败标准**:
- [ ] 系统设置5 Tab(数据源/通知/调度/健康/偏好)可查看和修改
- [ ] Dashboard展示完整: NAV+持仓+因子健康+行业分布+月度热力图
- [ ] 通知铃铛实时显示未读数，Toast弹窗正常
- [ ] NSSM服务kill后3秒自动重启
- [ ] 备份Task Scheduler每日02:00运行

**依赖关系**:
- Sprint 1.15: WebSocket(通知推送)
- Sprint 1.13: 前端基础设施(所有页面stub已存在)
- NSSM独立于前端，可并行实施

**风险与回滚**:
- NSSM安装复杂: 准备PowerShell安装脚本，预期30分钟内完成
- Dashboard月度热力图: 需DashboardService新增API(月度汇总)
- 通知系统复杂: 先实现WebSocket推送+Toast，铃铛+通知中心可延后
- 备份自动化: pg_dump已有脚本基础，Task Scheduler配置是增量

**新增测试**: ~15个(NSSM健康检查+备份恢复+通知API+系统设置)

---

### Sprint 1.20: PT监控前端 + 生产加固 (2周)

**目标**: PT毕业指标前端可见；灾备和远程监控就位。

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | PT毕业Dashboard(9项指标实时展示) | `frontend/src/pages/PTGraduation.tsx` | TrD | 2.5 |
| 2 | Dashboard待处理事项(审批/预警/完成) | `frontend/src/pages/Dashboard.tsx`(修改) | TrD | 1.5 |
| 3 | Bayesian滑点校准(PT数据更新Y参数) | `scripts/bayesian_slippage_calibration.py` | TrC | 2 |
| 4 | Tailscale + 远程状态API | `backend/app/api/remote_status.py` | TrC | 1 |
| 5 | 灾备恢复SOP + 验证脚本 | `scripts/disaster_recovery_verify.py` | TrC | 1.5 |
| 6 | 因子生命周期自动迁移 | `scripts/factor_health_daily.py`(修改) | TrC | 0.5 |
| 7 | 参数系统补全(220参数分批注册) | `backend/app/services/param_defaults.py`(修改) | TrE | 1.5 |

**成败标准**:
- [ ] PT毕业Dashboard实时展示9项指标(达标绿/不达标红)
- [ ] Bayesian校准后滑点偏差 < 10%
- [ ] Tailscale远程可访问 /api/v1/status
- [ ] 灾备恢复SOP可在2小时内恢复

**依赖关系**:
- PT v1.1运行至Day ~50+: 此时应有足够数据做Bayesian校准
- Sprint 1.14: 滑点三组件(Bayesian校准的前置)
- Sprint 1.19: NSSM(Tailscale与服务化并行)

**风险与回滚**:
- PT数据不足: Day 50如遇长假(国庆/春节)实际交易日可能仅35-40天，需评估
- Bayesian校准: MCMC收敛慢→增加样本/简化先验
- Tailscale网络配置: 需要在路由器开放端口或使用relay模式
- 灾备SOP: 需要实际演练一次(在测试环境)

**新增测试**: ~10个(PT毕业指标计算+Bayesian+灾备恢复+参数注册)

---

### Sprint 1.21: 联调 + E2E测试 + PT毕业 (2周)

**目标**: 前后端联调完成；E2E测试通过；PT毕业正式评估。

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | E2E测试套件(前端+后端全链路) | `backend/tests/test_e2e_full_chain.py` | TrE | 3 |
| 2 | 前端集成测试(API→页面) | `frontend/src/__tests__/` | TrE | 2 |
| 3 | PT毕业正式评估(9项指标逐项审查) | `scripts/pt_graduation_assessment.py` | TrC | 1 |
| 4 | miniQMT实盘dry run(1股) | `scripts/verify_qmt_broker.py`(修改) | TrC | 2 |
| 5 | 12页面polish(边缘case+响应式) | `frontend/src/pages/*` | TrD | 3 |
| 6 | 性能优化(首屏加载/React Query缓存) | `frontend/` | TrD | 1 |

**成败标准**:
- [ ] E2E测试: 数据→因子→信号→风控→执行→归因 全链路自动化PASS
- [ ] 12页面全部可正常访问(核心功能+边缘case)
- [ ] PT毕业9项指标全部达标(或有降级标准书面审批)
- [ ] miniQMT 1股买入→持有→卖出成功

**依赖关系**:
- 所有前置Sprint基本完成(这是集成Sprint)
- PT v1.1运行至Day 60: 正式毕业评估
- miniQMT: 需要在交易时间(09:30-15:00)测试

**风险与回滚**:
- PT毕业不达标: 按CLAUDE.md毕业标准，降低需书面记录理由
- E2E测试覆盖不全: 优先覆盖关键路径(数据→信号→执行)，非关键可延后
- miniQMT 1股失败: 排查verify_qmt_broker.py日志，可能是连接/权限/资金问题
- 前端边缘case: 记录已知问题列表，非阻塞项延后修复

**新增测试**: ~30个(E2E全链路+前端集成+miniQMT dry run+性能)

---

### Sprint 1.22: 实盘过渡 + 文档收尾 (2周)

**目标**: 系统ready for live trading；文档与代码完全同步。

| # | 任务 | 文件路径 | 轨道 | 天数 |
|---|------|---------|------|------|
| 1 | 实盘切换SOP(SimBroker→MiniQMTBroker) | `docs/SOP_LIVE_CUTOVER.md` | TrC | 1 |
| 2 | 实盘dry run(10%资金→50%→100%渐进) | — | TrC | 3 |
| 3 | 前端最终polish + 深浅主题完善 | `frontend/` | TrD | 2 |
| 4 | 性能优化(Bundle size/Code splitting) | `frontend/` | TrD | 1 |
| 5 | DEV文档全量同步 | `docs/DEV_*.md` | TrE | 2 |
| 6 | IMPLEMENTATION_MASTER最终更新 | `docs/IMPLEMENTATION_MASTER.md` | TrE | 0.5 |
| 7 | CompositeStrategy最终回测 | `scripts/backtest_composite_final.py` | TrA | 1.5 |

**成败标准**:
- [ ] 实盘切换SOP步骤清晰，切换时间 < 30分钟
- [ ] 全量资金dry run无异常
- [ ] 所有DEV文档与代码实际状态一致
- [ ] 前端bundle < 3MB(gzip)

**依赖关系**:
- Sprint 1.21: PT毕业通过(实盘切换的前提)
- Sprint 1.21: miniQMT 1股验证通过
- Sprint 1.19: NSSM服务化(实盘需要OS级进程管理)

**风险与回滚**:
- 实盘切换: SOP文档明确回退步骤(30分钟内从MiniQMTBroker切回SimBroker)
- 渐进切换(10%→50%→100%): 每阶段运行≥3天确认无异常再升级
- 文档不同步: 用脚本扫描代码中的TODO/FIXME与文档对比
- Bundle过大: Code splitting + 懒加载 + 分离大依赖(ECharts/Monaco)

**新增测试**: ~10个(实盘dry run+性能+Bundle size+文档一致性)

---

## 8. 前后端API对齐矩阵

> 对应DEV_FRONTEND_UI.md §7全部端点

### 回测模块(14个端点)

| 端点 | 方法 | 前端页面 | 后端状态 | 前端状态 | Sprint |
|------|------|---------|---------|---------|--------|
| /api/strategy | POST | 策略工作台 | ✅已有 | ❌ | 1.14 |
| /api/strategy | GET | 策略工作台 | ✅已有 | ❌ | 1.14 |
| /api/strategy/{id} | GET/PUT/DELETE | 策略工作台 | ⚠️部分 | ❌ | 1.14 |
| /api/factors/summary | GET | 策略工作台 | ❌ | ❌ | 1.14 |
| /api/ai/strategy-assist | POST | 策略工作台 | ❌ | ❌ | 1.18 |
| /api/backtest/run | POST | 回测配置 | ✅已有 | ❌ | 1.14 |
| /api/backtest/{id}/result | GET | 回测结果 | ✅已有 | ❌ | 1.15 |
| /api/backtest/{id}/trades | GET | 回测结果 | ✅已有 | ❌ | 1.15 |
| /api/backtest/{id}/holdings/{date} | GET | 回测结果 | ❌ | ❌ | 1.15 |
| /api/backtest/{id}/sensitivity | POST | 回测结果 | ❌ | ❌ | 1.15 |
| /api/backtest/{id}/live-compare | GET | 回测结果 | ❌ | ❌ | 1.15 |
| /api/backtest/compare | POST | 策略库 | ❌ | ❌ | 1.15 |
| /api/backtest/history | GET | 策略库 | ✅已有 | ❌ | 1.15 |
| /ws/backtest/{runId} | WS | 回测运行 | ❌ | ❌ | 1.15 |

### 因子挖掘模块(15个端点)

| 端点 | 方法 | 前端页面 | 后端状态 | 前端状态 | Sprint |
|------|------|---------|---------|---------|--------|
| /api/factor/create | POST | 因子实验室 | ❌ | ❌ | 1.16 |
| /api/factor/validate | POST | 因子实验室 | ❌ | ❌ | 1.16 |
| /api/factor/mine/gp | POST | 因子实验室 | ❌ | ❌ | 1.17 |
| /api/factor/mine/llm | POST | 因子实验室 | ❌ | ❌ | 1.17 |
| /api/factor/mine/brute | POST | 因子实验室 | ❌ | ❌ | 1.17 |
| /api/ai/factor-assist | POST | 因子实验室 | ❌ | ❌ | 1.18 |
| /api/factor/tasks | GET | 任务中心 | ❌ | ❌ | 1.17 |
| /api/factor/tasks/{id} | GET/DELETE | 任务中心 | ❌ | ❌ | 1.17 |
| /api/factor/{id}/report | GET | 因子评估 | ❌ | ❌ | 1.16 |
| /api/factor/evaluate/batch | POST | 因子评估 | ❌ | ❌ | 1.16 |
| /api/factor/library | GET | 因子库 | ❌ | ❌ | 1.16 |
| /api/factor/{id}/archive | POST | 因子库 | ❌ | ❌ | 1.16 |
| /api/factor/health-check | POST | 因子库 | ❌ | ❌ | 1.16 |
| /api/factor/correlation-prune | POST | 因子库 | ❌ | ❌ | 1.16 |
| /ws/factor-mine/{taskId} | WS | 任务中心 | ❌ | ❌ | 1.17 |

### AI闭环模块(10个端点)

| 端点 | 方法 | 前端页面 | 后端状态 | 前端状态 | Sprint |
|------|------|---------|---------|---------|--------|
| /api/pipeline/status | GET | Pipeline控制台 | ❌ | ❌ | 1.18 |
| /api/pipeline/trigger | POST | Pipeline控制台 | ❌ | ❌ | 1.18 |
| /api/pipeline/pause | POST | Pipeline控制台 | ❌ | ❌ | 1.18 |
| /api/pipeline/history | GET | Pipeline控制台 | ❌ | ❌ | 1.18 |
| /api/pipeline/pending | GET | Pipeline控制台 | ❌ | ❌ | 1.18 |
| /api/pipeline/approve/{id} | POST | Pipeline控制台 | ❌ | ❌ | 1.18 |
| /api/pipeline/reject/{id} | POST | Pipeline控制台 | ❌ | ❌ | 1.18 |
| /api/agent/{name}/config | GET/PUT | Agent配置 | ❌ | ❌ | 1.18 |
| /api/agent/{name}/logs | GET | Agent配置 | ❌ | ❌ | 1.18 |
| /ws/pipeline/{runId} | WS | Pipeline控制台 | ❌ | ❌ | 1.18 |

### 系统设置模块(8个端点)

| 端点 | 方法 | 前端页面 | 后端状态 | 前端状态 | Sprint |
|------|------|---------|---------|---------|--------|
| /api/system/datasources | GET | 系统设置 | ❌ | ❌ | 1.19 |
| /api/system/datasources/{name}/test | POST | 系统设置 | ❌ | ❌ | 1.19 |
| /api/system/health | GET | 系统设置 | ✅已有(health API) | ❌ | 1.19 |
| /api/system/scheduler | GET | 系统设置 | ❌ | ❌ | 1.19 |
| /api/system/scheduler/{task}/trigger | POST | 系统设置 | ❌ | ❌ | 1.19 |
| /api/system/preferences | GET/PUT | 系统设置 | ❌ | ❌ | 1.19 |
| /api/system/notifications/config | GET/PUT | 系统设置 | ⚠️部分 | ❌ | 1.19 |
| /api/system/notifications/test | POST | 系统设置 | ❌ | ❌ | 1.19 |

### Dashboard模块(11个端点)

| 端点 | 方法 | 前端页面 | 后端状态 | 前端状态 | Sprint |
|------|------|---------|---------|---------|--------|
| /api/dashboard/summary | GET | 总览 | ✅已有 | ✅已用 | 1.19 |
| /api/dashboard/nav-series | GET | 总览 | ✅已有 | ✅已用 | 1.19 |
| /api/dashboard/pending-actions | GET | 总览 | ❌ | ❌ | 1.20 |
| /api/dashboard/industry-distribution | GET | 总览 | ❌ | ❌ | 1.19 |
| /api/dashboard/monthly-returns | GET | 总览 | ❌ | ❌ | 1.19 |
| /api/pipeline/status | GET | 总览 | ❌ | ❌ | 1.18 |
| /api/notifications | GET | 全局 | ✅已有 | ❌ | 1.19 |
| /api/notifications/{id}/read | PUT | 全局 | ❌ | ❌ | 1.19 |
| /api/notifications/unread-count | GET | 全局 | ❌ | ❌ | 1.19 |
| /ws/notifications | WS | 全局 | ❌ | ❌ | 1.19 |
| /api/pt/graduation | GET | PT毕业 | ✅(CLI) | ❌ | 1.20 |

---

## 9. R-Item + BLUEPRINT Gap 追踪矩阵

> 合并两个来源: BLUEPRINT 44缺失+9部分 = 53项 + R1-R7 73项 = ~117项总缺口

### 9.1 BLUEPRINT现有缺口 (来源: DEVELOPMENT_BLUEPRINT 1.1节)

> 来源: 135功能审计中44缺失+9部分 = 53项缺口。
> 每个条目对应DEVELOPMENT_BLUEPRINT中的具体功能项，ID前缀BP表示BLUEPRINT来源。
> 按模块分组排列，与§2.0总体完成度矩阵对应。

**模块A: 数据管道 (2项缺口, 完成度78%)**

| ID | 模块 | 描述 | 优先级 | Sprint | 状态 |
|----|------|------|--------|--------|------|
| BP-A01 | 数据管道 | DataService集中化(当前散落scripts) | P1 | 1.13 | TODO |
| BP-A02 | 数据管道 | AKShare备用源 | P1 | 1.16 | TODO |

**模块B: 因子引擎 (5项缺口, 完成度59%)**

| ID | 模块 | 描述 | 优先级 | Sprint | 状态 |
|----|------|------|--------|--------|------|
| BP-B01 | 因子引擎 | UniverseFilter独立模块 | P1 | 1.13 | TODO |
| BP-B02 | 因子引擎 | 因子Gate Pipeline自动化 | P0 | 1.15 | TODO |
| BP-B03 | 因子引擎 | 因子生命周期自动转换 | P1 | 1.20 | TODO |
| BP-B04 | 因子引擎 | north_flow因子接入 | P1 | 未排 | TODO |
| BP-B05 | 因子引擎 | margin因子接入 | P1 | 未排 | TODO |

**模块C: 信号/组合 (2项缺口, 完成度63%)**

| ID | 模块 | 描述 | 优先级 | Sprint | 状态 |
|----|------|------|--------|--------|------|
| BP-C01 | 信号/组合 | 多策略PortfolioManager | P0 | 1.13 | TODO |
| BP-C02 | 信号/组合 | IC加权对比版 | P2 | 未排 | SKIP(等权最优) |

**模块G: 调度运维 (5项缺口, 完成度44%)**

| ID | 模块 | 描述 | 优先级 | Sprint | 状态 |
|----|------|------|--------|--------|------|
| BP-G01 | 调度运维 | 任务依赖链(Redis gate) | P0 | 1.13 | TODO |
| BP-G02 | 调度运维 | Celery多队列(8个) | P2 | 1.15 | TODO |
| BP-G03 | 调度运维 | PG备份自动化 | P0 | 1.19 | TODO |
| BP-G04 | 调度运维 | 备份恢复验证 | P0 | 1.20 | TODO |
| BP-G05 | 调度运维 | 磁盘空间监控+清理 | P2 | 未排 | TODO |

**模块H: 通知告警 (2项缺口, 完成度44%)**

| ID | 模块 | 描述 | 优先级 | Sprint | 状态 |
|----|------|------|--------|--------|------|
| BP-H01 | 通知告警 | WebSocket推送 | P1 | 1.15 | TODO |
| BP-H02 | 通知告警 | 32通知模板补全 | P2 | 1.19 | TODO |

**模块I: 参数系统 (3项缺口, 完成度56%)**

| ID | 模块 | 描述 | 优先级 | Sprint | 状态 |
|----|------|------|--------|--------|------|
| BP-I01 | 参数系统 | 220参数全量注册 | P1 | 1.20 | TODO |
| BP-I02 | 参数系统 | 参数变更审计日志 | P2 | 未排 | TODO |
| BP-I03 | 参数系统 | Alembic迁移配置 | P1 | 1.13 | TODO |

**模块J: 前端 (13项缺口, 完成度13% — 最大缺口)**

| ID | 模块 | 描述 | 优先级 | Sprint | 状态 |
|----|------|------|--------|--------|------|
| BP-J01 | 前端 | React Router + 12页面路由 | P0 | 1.13 | TODO |
| BP-J02 | 前端 | Zustand状态管理 | P0 | 1.13 | TODO |
| BP-J03 | 前端 | shadcn/ui组件库 | P0 | 1.13 | TODO |
| BP-J04 | 前端 | API client + React Query | P0 | 1.13 | TODO |
| BP-J05 | 前端 | 策略工作台 | P0 | 1.14 | TODO |
| BP-J06 | 前端 | 回测配置+运行+结果 | P0 | 1.14-1.15 | TODO |
| BP-J07 | 前端 | 策略库 | P1 | 1.15 | TODO |
| BP-J08 | 前端 | 因子库 | P1 | 1.16 | TODO |
| BP-J09 | 前端 | 因子评估报告 | P1 | 1.16 | TODO |
| BP-J10 | 前端 | 因子实验室 | P1 | 1.17 | TODO |
| BP-J11 | 前端 | 挖掘任务中心 | P1 | 1.17 | TODO |
| BP-J12 | 前端 | Pipeline控制台 | P1 | 1.18 | TODO |
| BP-J13 | 前端 | Agent配置 | P2 | 1.18 | TODO |
| BP-J14 | 前端 | 系统设置 | P1 | 1.19 | TODO |
| BP-J15 | 前端 | Dashboard完善 | P0 | 1.19 | TODO |

**模块K: AI/ML (9项缺口, 完成度18%)**

| ID | 模块 | 描述 | 优先级 | Sprint | 状态 |
|----|------|------|--------|--------|------|
| BP-K01 | AI/ML | GP遗传编程引擎 | P1 | 1.16 | TODO |
| BP-K02 | AI/ML | LLM 3-Agent因子发现 | P1 | 1.17 | TODO |
| BP-K03 | AI/ML | PipelineOrchestrator | P1 | 1.18 | TODO |
| BP-K04 | AI/ML | approval_queue + decision_log | P1 | 1.18 | TODO |
| BP-K05 | AI/ML | 14个AI参数渐进替换 | P2 | 未排 | TODO |
| BP-K06 | AI/ML | SHAP可解释性集成(因子重要性+特征贡献可视化) | P1 | 1.18 | TODO |
| BP-K07 | AI/ML | Autoencoder异常检测(替代HMM regime，双路径架构) | P1 | 未排 | TODO |
| BP-K08 | AI/ML | 双路径架构(不同市场体制用不同因子权重/选股逻辑) | P2 | 未排 | TODO |
| BP-K09 | AI/ML | GPU加速GP因子挖掘(RTX 5070 CUDA/PyTorch) | P3 | 未排 | TODO |
| BP-K10 | AI/ML | LightGBM ranking loss替代regression(lambdarank+NDCG) | P1 | 1.18 | TODO |
| BP-K11 | AI/ML | GARCH(1,1)条件方差增强RegimeModifier | P2 | 未排 | TODO |
| BP-K12 | AI/ML | K-Means聚类特征增强因子模型(股票风格分组距离) | P3 | 未排 | TODO |

### 9.2 R1-R7新增条目

> 来源: R1-R7研究报告的73项可执行条目。
> ID前缀对应研究报告编号(R1=因子-策略匹配, R2=因子挖掘前沿, R3=多策略组合,
> R4=A股微观结构, R5=回测-实盘对齐, R6=生产架构, R7=AI模型选型)。

**R1: 因子-策略匹配 (11项)** — FactorClassifier + 多频率策略框架

| ID | 描述 | 优先级 | Sprint | 状态 |
|----|------|--------|--------|------|
| R1-01 | FactorClassifier类实现 | P0 | 1.13 | TODO |
| R1-02 | ic_decay半衰期计算 | P0 | 1.13 | TODO |
| R1-03 | 信号分布形态分析 | P0 | 1.13 | TODO |
| R1-04 | FastRankingStrategy(周度) | P0 | 1.13 | TODO |
| R1-05 | EventStrategy(事件触发) | P0 | 1.13 | TODO |
| R1-06 | SlowRankingStrategy(季度) | P2 | 未排 | TODO |
| R1-07 | 5 Active因子分类验证 | P0 | 1.13 | TODO |
| R1-08 | 8 Reserve因子分类验证 | P1 | 1.15 | TODO |
| R1-09 | 因子生命周期自动迁移 | P1 | 1.20 | TODO |
| R1-10 | 拥挤度监控(架构预留) | P2 | 未排 | TODO |
| R1-11 | 分类置信度阈值调优 | P2 | 未排 | TODO |

**R2: 因子挖掘前沿 (15项)** — 三引擎+Gate Pipeline+知识库

| ID | 描述 | 优先级 | Sprint | 状态 |
|----|------|--------|--------|------|
| R2-01 | Factor Sandbox | P0 | 1.14 | TODO |
| R2-02 | BruteForce引擎(50模板) | P0 | 1.14 | TODO |
| R2-03 | AST结构去重器 | P0 | 1.14 | TODO |
| R2-04 | Factor Gate Pipeline G1-G8 | P0 | 1.15 | TODO |
| R2-05 | 因子表达式DSL | P0 | 1.16 | TODO |
| R2-06 | DEAP GP引擎(岛屿模型) | P0 | 1.16 | TODO |
| R2-07 | GP复杂度惩罚 | P1 | 1.16 | TODO |
| R2-08 | LLM 3-Agent(Idea/Factor/Eval) | P0 | 1.17 | TODO |
| R2-09 | mining_knowledge表+失败注入 | P1 | 1.18 | TODO |
| R2-10 | Thompson Sampling调度 | P1 | 1.17 | TODO |
| R2-11 | PipelineOrchestrator状态机 | P0 | 1.18 | TODO |
| R2-12 | approval_queue审批流程 | P1 | 1.18 | TODO |
| R2-13 | Alpha158缺口补充 | P2 | 未排 | TODO |
| R2-14 | 经验链注入 | P2 | 未排 | TODO |
| R2-15 | 多样化规划 | P2 | 未排 | TODO |

**R3: 多策略组合 (10项)** — CompositeStrategy + Modifier叠加

| ID | 描述 | 优先级 | Sprint | 状态 |
|----|------|--------|--------|------|
| R3-01 | CompositeStrategy编排器 | P0 | 1.13 | TODO |
| R3-02 | ModifierBase ABC | P0 | 1.13 | TODO |
| R3-03 | RegimeModifier | P0 | 1.13 | TODO |
| R3-04 | VwapModifier | P1 | 未排 | TODO |
| R3-05 | EventModifier | P1 | 未排 | TODO |
| R3-06 | 资金规模可配置 | P0 | 1.13 | TODO |
| R3-07 | 子策略模式切换(300万+) | P2 | 未排 | TODO |
| R3-08 | Modifier scale边界保护 | P0 | 1.13 | TODO |
| R3-09 | CompositeStrategy回测验证 | P0 | 1.15 | TODO |
| R3-10 | 最优modifier配置搜索 | P1 | 1.22 | TODO |

**R4: A股微观结构 (7项)** — 滑点三组件精细化

| ID | 描述 | 优先级 | Sprint | 状态 |
|----|------|--------|--------|------|
| R4-01 | overnight_gap_cost | P0 | 1.14 | TODO |
| R4-02 | tiered_base_bps | P0 | 1.14 | TODO |
| R4-03 | 滑点分解脚本 | P1 | 1.18 | TODO |
| R4-04 | Bayesian滑点校准 | P1 | 1.20 | TODO |
| R4-05 | Y_small 1.5→1.8 | P2 | 1.14 | TODO |
| R4-06 | sell_penalty 1.2→1.3 | P2 | 1.14 | TODO |
| R4-07 | 集合竞价建模 | P2 | 未排 | TODO |

**R5: 回测-实盘对齐 (7项)** — 信号回放+look-ahead检查

| ID | 描述 | 优先级 | Sprint | 状态 |
|----|------|--------|--------|------|
| R5-01 | PT信号回放验证器 | P0 | 1.15 | TODO |
| R5-02 | 15项look-ahead检查执行 | P0 | 1.15 | TODO |
| R5-03 | T+1 open执行价格确认 | P0 | — | DONE |
| R5-04 | PT数据分析三阶段 | P1 | 1.20 | TODO |
| R5-05 | fill_rate统计 | P1 | 1.15 | TODO |
| R5-06 | 信号Alpha衰减量化 | P2 | 未排 | TODO |
| R5-07 | 部分成交影响分析 | P2 | 未排 | TODO |

**R6: 生产架构 (13项)** — NSSM+Task Scheduler+备份+远程监控

| ID | 描述 | 优先级 | Sprint | 状态 |
|----|------|--------|--------|------|
| R6-01 | NSSM安装+服务注册 | P0 | 1.19 | TODO |
| R6-02 | Task Scheduler完整配置 | P0 | 1.19 | TODO |
| R6-03 | PG备份自动化 | P0 | 1.19 | TODO |
| R6-04 | Parquet周快照 | P1 | 1.19 | TODO |
| R6-05 | 备份恢复验证 | P0 | 1.20 | TODO |
| R6-06 | structlog JSON | P1 | 1.15 | TODO |
| R6-07 | RotatingFileHandler | P1 | 1.15 | TODO |
| R6-08 | Tailscale VPN | P1 | 1.20 | TODO |
| R6-09 | 远程状态API | P1 | 1.20 | TODO |
| R6-10 | 灾备恢复SOP | P0 | 1.20 | TODO |
| R6-11 | DingTalk告警优化 | P2 | 未排 | TODO |
| R6-12 | 磁盘自动清理 | P2 | 未排 | TODO |
| R6-13 | health_checks持久化 | P1 | 1.15 | TODO |

**R7: AI模型选型 (7项)** — DeepSeek+Qwen3+ModelRouter

| ID | 描述 | 优先级 | Sprint | 状态 |
|----|------|--------|--------|------|
| R7-01 | DeepSeek API客户端 | P0 | 1.17 | TODO |
| R7-02 | ModelRouter | P0 | 1.17 | TODO |
| R7-03 | Qwen3本地部署 | P1 | 1.17 | TODO |
| R7-04 | 本地推理检测+fallback | P1 | 1.17 | TODO |
| R7-05 | 月度成本统计 | P2 | 1.18 | TODO |
| R7-06 | 模型benchmark | P2 | 未排 | TODO |
| R7-07 | Prompt模板管理 | P2 | 未排 | TODO |

**统计**:
- P0: 38项
- P1: 42项
- P2: 37项
- DONE: 1项
- SKIP: 1项
- **排入Sprint**: ~80项
- **未排**: ~37项(P2延后或方向待定)

---

## 10. DEV文档更新清单

| 文档 | 当前行数 | 当前状态 | 需更新内容 | Sprint |
|------|---------|---------|-----------|--------|
| QUANTMIND_V2_DESIGN_V5.md | ~3000 | 架构参考(不修改) | 保持不变,作为原始设计参考 | — |
| DEV_BACKEND.md | ~800 | 后端服务层 | 新增6个Service描述(Factor/Backtest/Mining/Pipeline/Scheduler/Data) | 1.13 |
| DEV_BACKTEST_ENGINE.md | ~900 | 回测引擎 | 新增FastRanking/Event策略; 滑点三组件(R4); CompositeStrategy回测 | 1.13-1.15 |
| DEV_FACTOR_MINING.md | ~600 | 因子挖掘 | 更新Gate G1-G8(R2); GP岛屿模型; LLM 3-Agent; Pipeline 8节点 | 1.14-1.18 |
| DEV_AI_EVOLUTION.md | ~700 | AI闭环 | LLM Agent实现(R7); ModelRouter; Pipeline编排; approval_queue | 1.17-1.18 |
| DEV_PARAM_CONFIG.md | ~500 | 参数系统 | Modifier参数(R3); NSSM参数(R6); 220参数全量 | 1.13/1.19 |
| DEV_FRONTEND_UI.md | 695 | 前端UI | R1-R7导致的12处更新(见§6) | 1.14-1.19 |
| DEV_SCHEDULER.md | ~400 | 调度运维 | Task Scheduler完整配置(R6); NSSM设置; 备份策略 | 1.19 |
| DEV_NOTIFICATIONS.md | ~300 | 通知告警 | WebSocket通知推送; 32模板状态更新 | 1.15/1.19 |
| DEV_FOREX.md | ~400 | 外汇(Phase 2) | 不在scope内,保持不变 | — |
| QUANTMIND_V2_FOREX_DESIGN.md | ~800 | 外汇设计(Phase 2) | 不在scope内 | — |
| TUSHARE_DATA_SOURCE_CHECKLIST.md | 716 | 数据源checklist | 保持不变(已完整) | — |

---

## 11. 测试策略

### 11.1 现有测试覆盖

| 层 | 测试文件 | 测试函数 | 覆盖范围 | 缺口 |
|----|---------|---------|---------|------|
| 引擎层 | 30+ | ~500 | factor_engine/signal_engine/backtest_engine/slippage/metrics/risk | FactorClassifier/CompositeStrategy/GP/Gate |
| Service层 | 5 | ~80 | risk_control/signal/dashboard/param | factor/backtest/mining/pipeline |
| API层 | 3 | ~50 | health/backtest/params | factor/mining/pipeline/system |
| 集成 | 5 | ~80 | e2e chain/paper_trading | 前后端联调/WebSocket |
| 前端 | 0 | 0 | — | 全部 |

### 11.2 测试补全计划

| Sprint | 测试类型 | 数量 | 覆盖模块 |
|--------|---------|------|---------|
| 1.13 | 单元测试 | ~30 | FactorClassifier/CompositeStrategy/Modifier/Service wrappers |
| 1.14 | 单元测试 | ~25 | Sandbox/BruteForce/ASTDedup/策略工作台API |
| 1.15 | 单元+集成 | ~30 | Gate Pipeline G1-G8/WebSocket/回测API端到端 |
| 1.16 | 单元测试 | ~25 | GP引擎/DSL/Factor API |
| 1.17 | 单元+集成 | ~20 | LLM Agent/ModelRouter/DeepSeek mock |
| 1.18 | 集成测试 | ~20 | Pipeline状态机/审批流程/API |
| 1.19 | 系统测试 | ~15 | NSSM/备份/通知 |
| 1.20 | 系统测试 | ~10 | PT毕业/灾备恢复 |
| 1.21 | E2E测试 | ~30 | 前后端联调/全链路/前端集成 |
| 1.22 | 验收测试 | ~10 | 实盘dry run/性能 |
| **总计** | — | **~215** | 从718→~933测试函数 |

### 11.3 测试原则

- **单元测试**: Engine层纯函数，DataFrame输入输出，mock DB
- **集成测试**: Service→Engine→DB，用test DB(非生产)
- **E2E测试**: 前端→API→Service→Engine→DB全链路
- **性能测试**: 因子计算<15min(5因子×全Universe)，回测<5min(5年)
- **WebSocket测试**: 用pytest-socketio + mock client
- **回归测试**: 每Sprint确保现有718测试不退化

### 11.4 关键测试用例示例

**FactorClassifier测试**:
```python
# tests/test_factor_classifier.py

class TestFactorClassifier:
    def test_fast_decay_routes_to_fast_ranking(self, mock_fast_decay_factor):
        """IC半衰期<5天的因子应路由到FastRankingStrategy。"""
        result = classifier.classify("test_factor", mock_fast_decay_factor, fwd_returns)
        assert result.strategy_type == StrategyType.FAST_RANKING
        assert result.frequency == "weekly"
        assert result.ic_decay_halflife < 5.0

    def test_sparse_signal_routes_to_event(self, mock_sparse_factor):
        """峰度>5.0的稀疏分布因子应路由到EventStrategy。"""
        result = classifier.classify("sparse_factor", mock_sparse_factor, fwd_returns)
        assert result.strategy_type == StrategyType.EVENT
        assert result.signal_kurtosis > 5.0

    def test_active_5_factors_classification(self, active_5_factors):
        """验证5个Active因子的分类结果与R1研究预期一致。"""
        results = classifier.classify_batch(active_5_factors, fwd_returns)
        # v1.1的5因子都应是月度Ranking类型
        for name, r in results.items():
            assert r.strategy_type == StrategyType.RANKING
            assert r.frequency == "monthly"

    def test_empty_factor_raises_error(self):
        """空因子值应抛出ValueError。"""
        with pytest.raises(ValueError, match="factor_values为空"):
            classifier.classify("empty", pd.DataFrame(), fwd_returns)
```

**CompositeStrategy测试**:
```python
# tests/test_composite_strategy.py

class TestCompositeStrategy:
    def test_no_modifier_equals_core(self, core_strategy, context):
        """无Modifier时，CompositeStrategy输出应与核心策略一致(仅差cash_buffer)。"""
        composite = CompositeStrategy(core_strategy, modifiers=[])
        weights = composite.generate_signals(context)
        core_weights = core_strategy.generate_signals(context)
        # 总和应约等于1-cash_buffer
        assert abs(sum(weights.values()) - 0.97) < 0.01

    def test_regime_modifier_reduces_position(self, core_strategy, high_vol_context):
        """高波动时RegimeModifier应降低总仓位。"""
        modifier = RegimeModifier(vol_threshold=1.5, low_scale=0.7)
        composite = CompositeStrategy(core_strategy, [modifier])
        weights = composite.generate_signals(high_vol_context)
        assert sum(weights.values()) < 0.70  # 0.97 * 0.7 ≈ 0.68

    def test_scale_clip_enforced(self, core_strategy, extreme_context):
        """极端情况下scale_factor不应超出[0.3, 1.5]。"""
        modifier = MockExtremeModifier(scale=0.1)  # 试图降到10%
        composite = CompositeStrategy(core_strategy, [modifier])
        weights = composite.generate_signals(extreme_context)
        assert sum(weights.values()) >= 0.27  # 0.97 * 0.3 - tolerance
```

**Gate Pipeline测试**:
```python
# tests/test_factor_gate.py

class TestFactorGatePipeline:
    def test_known_factor_passes_all_gates(self, mf_divergence_data):
        """mf_divergence(IC=9.1%)应通过全部8个Gate。"""
        result = pipeline.run_gate("mf_divergence", mf_divergence_data, fwd_returns)
        assert result.passed is True
        assert len([g for g in result.gate_results if g.status == GateStatus.PASS]) == 8

    def test_noise_factor_fails_g3(self, random_noise_factor):
        """随机噪声因子应在G3(IC)处被拦截。"""
        result = pipeline.run_gate("noise", random_noise_factor, fwd_returns)
        assert result.passed is False
        g3 = next(g for g in result.gate_results if g.gate_id == "G3")
        assert g3.status == GateStatus.FAIL

    def test_short_circuit_stops_early(self, noise_factor):
        """短路模式下G1失败后不应继续G2-G8。"""
        result = pipeline.run_gate("bad", noise_factor, fwd_returns, short_circuit=True)
        executed = [g for g in result.gate_results]
        assert len(executed) < 8  # 短路未执行全部

    def test_big_small_consensus_fails_g5(self, big_small_data):
        """big_small_consensus中性化后IC归零，应在G5被拦截(LL-014验证)。"""
        result = pipeline.run_gate("big_small_consensus", big_small_data, fwd_returns)
        g5 = next(g for g in result.gate_results if g.gate_id == "G5")
        assert g5.status == GateStatus.FAIL
```

**WebSocket集成测试**:
```python
# tests/test_websocket.py

@pytest.mark.asyncio
class TestWebSocket:
    async def test_backtest_progress_stream(self, sio_client, running_backtest):
        """回测运行时应通过WebSocket推送进度消息。"""
        messages = []
        sio_client.on("progress", lambda data: messages.append(data))
        await sio_client.emit("join", {"room": f"backtest:{running_backtest.id}"})
        await asyncio.sleep(5)
        assert len(messages) > 0
        assert messages[0]["type"] == "progress"
        assert 0 <= messages[0]["payload"]["percentage"] <= 100

    async def test_notification_push(self, sio_client, notification_trigger):
        """系统通知应推送到/ws/notifications通道。"""
        received = []
        sio_client.on("notification", lambda data: received.append(data))
        await sio_client.emit("join", {"room": "notifications"})
        await notification_trigger.send_p1_alert("测试告警")
        await asyncio.sleep(1)
        assert len(received) == 1
        assert received[0]["payload"]["level"] == "P1"
```

### 11.5 测试数据管理

| 数据类型 | 来源 | 存储 | 用途 |
|---------|------|------|------|
| 因子快照 | 生产DB导出(2024-01~2025-03) | `tests/fixtures/factor_snapshot.parquet` | 因子计算确定性验证 |
| 行情快照 | Tushare导出(100只股票×1年) | `tests/fixtures/klines_100stock_1y.parquet` | 回测引擎确定性 |
| 回测基准 | v1.1跑出的hash | `tests/fixtures/baseline_result_hash.json` | 回归检测 |
| Mock因子 | 合成数据(正态/稀疏/双模态) | `tests/fixtures/mock_factors/` | 分类器单元测试 |
| Gate验证 | 已知因子(mf_divergence等) | `tests/fixtures/gate_known_factors/` | Gate Pipeline |

---

## 12. 风险登记簿

| # | 风险 | 概率 | 影响 | 缓解措施 |
|---|------|------|------|----------|
| 1 | **PT中断**(最高风险) | 低 | 极高 | 所有开发在独立分支/文件; 不修改run_paper_trading.py核心链路; config_guard拦截 |
| 2 | **前端开发瓶颈** | 高 | 中 | 前端基础设施Sprint 1.13最先完成; 12页面stub优先; 功能逐步充实 |
| 3 | **API向后兼容** | 中 | 中 | 新API用新Router文件; 不修改已有API签名; 版本化(/api/v2/)如必要 |
| 4 | **数据库迁移安全** | 中 | 高 | Alembic管理; 先备份再迁移; 新表优先(不改现有表schema) |
| 5 | PT v1.1不达标 | 中 | 高 | Day 30评估; 不达标分析原因; 有降级标准选项 |
| 6 | GP引擎低产出 | 中 | 中 | BruteForce先行验证Gate; GP是增量 |
| 7 | DeepSeek不稳定 | 低 | 中 | Qwen3本地优先; API仅Idea/Eval |
| 8 | 32GB内存不够 | 低 | 中 | Q4_K_M量化; 不够则纯API |
| 9 | RegimeModifier无增量 | 中 | 低 | Modifier可选叠加,不影响core |
| 10 | miniQMT切换出问题 | 低 | 高 | 1股dry run → 10%→50%→100%渐进 |

---

## 13. 文档同步日志

> 每Sprint完成后记录文档更新。

| Sprint | 文档 | 更新内容 | 状态 |
|--------|------|---------|------|
| 1.13 | DEV_BACKEND.md | 新增FactorService/BacktestService描述 | TODO |
| 1.13 | DEV_BACKTEST_ENGINE.md | 新增FastRanking/Event策略接口 | TODO |
| 1.13 | CLAUDE.md 技术决策表 | FactorClassifier/CompositeStrategy行 | TODO |
| 1.14 | DEV_FRONTEND_UI.md §2.1-2.2 | CompositeStrategy配置UI更新 | TODO |
| 1.14 | CLAUDE.md 技术决策表 | overnight_gap_cost/tiered_base_bps行 | TODO |
| 1.15 | DEV_FACTOR_MINING.md §3-5 | Gate Pipeline G1-G8规格 | TODO |
| 1.15 | LESSONS_LEARNED.md | CompositeStrategy/FastRanking验证结论 | TODO |
| 1.15 | PROGRESS.md | PT毕业进度更新 | TODO |
| 1.16 | DEV_FACTOR_MINING.md §6 | GP引擎+DSL实现细节 | TODO |
| 1.16 | DEV_FRONTEND_UI.md §3.3-3.4 | Gate/Classifier前端展示 | TODO |
| 1.17 | DEV_AI_EVOLUTION.md §2-4 | LLM Agent实现细节 | TODO |
| 1.17 | CLAUDE.md 技术决策表 | DeepSeek/Qwen3选型行 | TODO |
| 1.17 | DEV_FRONTEND_UI.md §3.1-3.2 | GP/LLM参数更新 | TODO |
| 1.18 | DEV_FACTOR_MINING.md §7 | Pipeline完整流程 | TODO |
| 1.18 | DEV_FRONTEND_UI.md §4.1-4.2 | Pipeline/Agent页面更新 | TODO |
| 1.19 | DEV_SCHEDULER.md | Task Scheduler完整配置 | TODO |
| 1.19 | DEV_FRONTEND_UI.md §5.1/§8 | 系统设置/总览页更新 | TODO |
| 1.20 | CLAUDE.md PT毕业标准 | 9项指标实际值 | TODO |
| 1.21 | PROGRESS.md | PT毕业评估结果 | TODO |
| 1.22 | CLAUDE.md 策略版本化 | v1.1→v1.2(如升级) | TODO |
| 1.22 | IMPLEMENTATION_MASTER.md | 最终更新(全Sprint结果) | TODO |

---

## 14. 版本历史

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v1.0 | 2026-03-28 | 初版，仅覆盖R1-R7(73项)。8个Sprint，4条轨道。已废弃。 |
| v2.0 | 2026-03-28 | **全项目版**。合并BLUEPRINT(53项)+R1-R7(73项)=117+项。10个Sprint，5条轨道。前端从附属升级为共等优先。新增: 全项目差距分析(§2)/前后端API对齐(§8)/测试策略(§11)/BLUEPRINT Gap矩阵(§9.1)/DEV_FRONTEND_UI更新计划(§6)/WebSocket协议(§5.7)/前端数据流(§4.6)/Service层差距(§2.2)。 |

---

## 附录A: 关键文件索引

### 现有核心文件

| 文件 | 路径 | 说明 |
|------|------|------|
| BaseStrategy | `backend/engines/base_strategy.py` | 策略抽象基类 |
| StrategyRegistry | `backend/engines/strategy_registry.py` | 策略注册表 |
| EqualWeight | `backend/engines/strategies/equal_weight.py` | v1.1核心策略 |
| BaseBroker | `backend/engines/base_broker.py` | Broker抽象基类 |
| SimBroker | `backend/engines/backtest_engine.py` | 回测Broker |
| PaperBroker | `backend/engines/paper_broker.py` | PT Broker |
| MiniQMTBroker | `backend/engines/broker_qmt.py` | 国金QMT Broker |
| FactorEngine | `backend/engines/factor_engine.py` | 因子计算引擎 |
| SignalEngine | `backend/engines/signal_engine.py` | 信号合成引擎 |
| SlippageModel | `backend/engines/slippage_model.py` | 滑点模型 |
| VolRegime | `backend/engines/vol_regime.py` | 波动率regime |
| RiskControl | `backend/app/services/risk_control_service.py` | 风控L1-L4 |
| PreTradeValidator | `backend/engines/pre_trade_validator.py` | 交易前验证5项 |
| FactorAnalyzer | `backend/engines/factor_analyzer.py` | 因子IC/t分析 |
| ConfigGuard | `backend/engines/config_guard.py` | 配置一致性检查 |
| Metrics | `backend/engines/metrics.py` | 绩效指标计算 |
| Attribution | `backend/engines/attribution.py` | 归因分析 |
| RegimeDetector | `backend/engines/regime_detector.py` | HMM regime(研究模块) |
| MLEngine | `backend/engines/ml_engine.py` | LightGBM引擎 |
| WalkForward | `backend/engines/walk_forward.py` | Walk-Forward验证 |

### 新建文件计划

| 文件 | 路径 | Sprint |
|------|------|--------|
| FactorClassifier | `backend/engines/factor_classifier.py` | 1.13 |
| FastRankingStrategy | `backend/engines/strategies/fast_ranking.py` | 1.13 |
| EventStrategy | `backend/engines/strategies/event_strategy.py` | 1.13 |
| ModifierBase | `backend/engines/modifiers/__init__.py` | 1.13 |
| RegimeModifier | `backend/engines/modifiers/regime_modifier.py` | 1.13 |
| CompositeStrategy | `backend/engines/strategies/composite.py` | 1.13 |
| FactorService | `backend/app/services/factor_service.py` | 1.13 |
| BacktestService | `backend/app/services/backtest_service.py` | 1.13 |
| FactorSandbox | `backend/engines/mining/factor_sandbox.py` | 1.14 |
| BruteForceEngine | `backend/engines/mining/bruteforce_engine.py` | 1.14 |
| ASTDedup | `backend/engines/mining/ast_dedup.py` | 1.14 |
| FactorGatePipeline | `backend/engines/factor_gate.py` | 1.15 |
| WebSocket Server | `backend/app/websocket/server.py` | 1.15 |
| LoggingConfig | `backend/app/logging_config.py` | 1.15 |
| FactorDSL | `backend/engines/mining/factor_dsl.py` | 1.16 |
| GPEngine | `backend/engines/mining/gp_engine.py` | 1.16 |
| Factor API | `backend/app/api/factors.py` | 1.16 |
| DeepSeekClient | `backend/engines/mining/deepseek_client.py` | 1.17 |
| ModelRouter | `backend/engines/mining/model_router.py` | 1.17 |
| IdeaAgent | `backend/engines/mining/agents/idea_agent.py` | 1.17 |
| FactorAgent | `backend/engines/mining/agents/factor_agent.py` | 1.17 |
| EvalAgent | `backend/engines/mining/agents/eval_agent.py` | 1.17 |
| Mining API | `backend/app/api/mining.py` | 1.17 |
| PipelineOrchestrator | `backend/engines/mining/pipeline_orchestrator.py` | 1.18 |
| Pipeline API | `backend/app/api/pipeline.py` | 1.18 |
| Approval API | `backend/app/api/approval.py` | 1.18 |
| System API | `backend/app/api/system.py` | 1.19 |
| RemoteStatusAPI | `backend/app/api/remote_status.py` | 1.20 |
| Router Config | `frontend/src/router.tsx` | 1.13 |
| Layout+Sidebar | `frontend/src/components/Layout.tsx` | 1.13 |
| Zustand Stores | `frontend/src/store/*.ts` | 1.13 |
| API Client | `frontend/src/api/client.ts` | 1.13 |
| 12 Page Files | `frontend/src/pages/*.tsx` | 1.13-1.19 |
| useWebSocket | `frontend/src/hooks/useWebSocket.ts` | 1.15 |
| NotificationSystem | `frontend/src/components/NotificationSystem.tsx` | 1.19 |

### 研究报告

| 文件 | 路径 |
|------|------|
| R1 因子-策略匹配 | `docs/research/R1_factor_strategy_matching.md` |
| R2 因子挖掘前沿 | `docs/research/R2_factor_mining_frontier.md` |
| R3 多策略组合 | `docs/research/R3_multi_strategy_framework.md` |
| R4 微观结构 | `docs/research/R4_A股微观结构特性.md` |
| R5 回测-实盘对齐 | `docs/research/R5_backtest_live_alignment.md` |
| R6 生产架构 | `docs/research/R6_production_architecture.md` |
| R7 AI模型选型 | `docs/research/R7_ai_model_selection.md` |

---

## 附录B: 术语表

| 术语 | 含义 |
|------|------|
| PT | Paper Trading，模拟交易 |
| Gate | 因子质量关卡，G1-G8 |
| Modifier | 权重调节器，不独立选股 |
| CompositeStrategy | 核心策略+Modifier叠加的组合策略 |
| FactorClassifier | 因子→策略匹配的自动分类器 |
| ic_decay | 因子IC随持有期增长的衰减曲线 |
| Thompson Sampling | 基于Beta分布后验的多臂老虎机算法 |
| AST去重 | 基于抽象语法树的因子表达式结构去重 |
| NSSM | Non-Sucking Service Manager，Windows服务管理器 |
| overnight_gap_cost | 隔夜跳空成本 |
| tiered_base_bps | 分市值档位的基础滑点 |
| Bayesian校准 | 用PT实测数据更新模型参数 |
| island model | GP多子群独立进化+周期性交换 |
| mining_knowledge | 因子挖掘知识库表 |
| shadcn/ui | 基于Radix UI的React组件库 |
| Zustand | 轻量级React状态管理库 |
| React Query | 服务端状态管理(缓存/重试/后台刷新) |
| Socket.IO | WebSocket封装库(自动重连/房间/事件) |
| GlassCard | 毛玻璃卡片组件(DEV_FRONTEND_UI §10.2) |
