# QuantMind V2 — 完整项目落地计划（修正版）

> 基于12份文档（10765行/213个章节）逐项比对后重写。
> 覆盖率：旧版25% → 本版100%。
> 每个Sprint标注：输入文档章节 → 开发任务 → 代码产出 → 验收标准。

---

## 全局路线图

```
Phase 0 收尾      [1-2周]      Sprint 0.1-0.2
Phase 1 A股完整   [14-18周]    Sprint 1.0-1.10
Phase 2 外汇MT5   [6-8周]      Sprint 2.0-2.4
Phase 3 AI闭环    [6-8周]      Sprint 3.0-3.3
Phase 4 迁移      [1-2周]      Sprint 4.0
```

---

# Phase 0 收尾

## Sprint 0.1: P0-Bug修复 + Paper Trading启动 [3-5天]

**输入**: CLAUDE.md回测可信度规则、DEV_BACKTEST_ENGINE.md补丁、DEV_SCHEDULER.md补丁P1

| # | 任务 | 文档来源 | 负责 | 工时 |
|---|------|---------|------|------|
| 1 | R4 调仓日SQL修复 | DEV_BACKTEST_ENGINE §4.9 | arch | 5min |
| 2 | R7 pg_advisory_lock并发保护 | DEV_BACKEND补丁P2 | arch | 15min |
| 3 | R3 Cash直接存DB | DEV_BACKTEST_ENGINE补丁P3 | arch | 30min |
| 4 | R1 两阶段pipeline(T日信号→T+1执行) | DEV_SCHEDULER补丁P1 | arch | 4h |
| 5 | R2 pre-trade-hedge回测确认真实Sharpe | CLAUDE.md回测可信度 | strategy | 1h |
| 6 | quant审查+qa验证全部修复 | TEAM_CHARTER §2.2 | quant+qa | 2h |
| 7 | 安装crontab启动Paper Trading | — | arch | 10min |

**验收**: quant撤销否决 + qa测试通过 + R2真实Sharpe确认 + Paper Trading首日运行成功

## Sprint 0.2: P1-Bug修复 + Paper Trading首周 [1周]

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | R5 退市股检测+强制平仓 | CLAUDE.md、DESIGN_V5补丁P1 | arch+data |
| 2 | R6 Tushare数据过时验证 | TUSHARE_CHECKLIST §4 | data |
| 3 | R8 健康预检扩展(7项全覆盖) | DESIGN_V5补丁P4、DEV_SCHEDULER补丁P2 | data |
| 4 | R9 Benchmark NAV归一化 | DEV_BACKTEST_ENGINE §4.15 | arch |
| 5 | R10 毕业标准重新校准 | DESIGN_V5 §12.2 | quant+strategy |
| 6 | YELLOW级bug批量修复 | 6-Agent审查报告 | arch |
| 7 | Paper Trading三项偏差指标自动监控 | **DESIGN_V5 §12.2** (旧版遗漏) | qa |
| 8 | 交易日历年初导入+每日验证脚本 | **DESIGN_V5补丁P5** (旧版遗漏) | data |

**验收**: 健康预检7/7通过 + 偏差监控自动运行 + Paper Trading连续5天无异常

---

# Phase 1: A股完整 + AI + 实盘

> Paper Trading运行60天期间，团队100%投入Phase 1开发。
> Paper Trading由qa自动监控，周五简报用户。

## Sprint 1.0: 工程基础设施 [1-2周]

**输入**: DEV_BACKEND.md全文、DEV_SCHEDULER.md全文

| # | 任务 | 文档来源(精确到章节) | 负责 |
|---|------|---------------------|------|
| 1 | Service→Repository完整分层重构 | DEV_BACKEND §三.1调用规则 | arch |
| 2 | FastAPI Service依赖注入改造 | DEV_BACKEND补丁P1 | arch |
| 3 | Celery完整调度链路(T日盘后时序) | DEV_SCHEDULER补丁P1全部 | arch |
| 4 | Celery Beat配置(A股7个定时任务) | DEV_SCHEDULER §四 | arch |
| 5 | Redis任务状态键管理 | DEV_SCHEDULER §五 | arch |
| 6 | **日志框架(structlog+JSON格式)** | **DEV_BACKEND §八** (旧版遗漏) | arch |
| 7 | **全局错误处理中间件** | **DEV_BACKEND §九** (旧版遗漏) | arch |
| 8 | **测试框架搭建(4层:单元/集成/回归/E2E)** | **DEV_BACKEND §七** (旧版遗漏) | qa |
| 9 | **WebSocket Manager** | **DEV_BACKEND §十** (旧版遗漏) | arch |
| 10 | 4条端到端数据流验证 | DEV_BACKEND §四.1-§四.4 | arch+data |
| 11 | **异常处理+重试策略** | **DEV_SCHEDULER §七** (旧版遗漏) | arch |
| 12 | **优雅停机+状态恢复** | **DEV_SCHEDULER补丁P5** (旧版遗漏) | arch |

**代码产出**:
```
backend/app/
  ├── repositories/         — Repository层(新建)
  ├── middleware/
  │   ├── error_handler.py  — 全局错误处理
  │   └── logging.py        — structlog配置
  ├── websocket/
  │   └── manager.py        — WebSocket Manager
  ├── tasks/
  │   ├── celery_config.py  — Beat配置
  │   ├── daily_pipeline.py — 完整T日链路
  │   └── health_check.py   — 7项预检
  └── tests/
      ├── unit/
      ├── integration/
      └── conftest.py       — pytest fixtures
```

## Sprint 1.1: 通知系统 + 参数配置 + 风控 [1-2周]

**输入**: DEV_NOTIFICATIONS.md全文、DEV_PARAM_CONFIG.md全文、DESIGN_V5 §八

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | NotificationService统一入口 | DEV_NOTIFICATIONS §二 | arch |
| 2 | 钉钉Webhook推送 | DEV_NOTIFICATIONS §三.1 | arch |
| 3 | 25+通知模板(含补丁P1追加) | DEV_NOTIFICATIONS §四+补丁P1 | arch |
| 4 | 防洪泛Throttler(含补丁P2) | DEV_NOTIFICATIONS §五+补丁P2 | arch |
| 5 | **通知生命周期(创建→发送→确认→归档)** | **DEV_NOTIFICATIONS §六** (旧版遗漏) | arch |
| 6 | 通知API(9个端点) | DEV_NOTIFICATIONS §八 | arch |
| 7 | ai_parameters 14旋钮初始化 | DEV_PARAM_CONFIG §五 | arch+strategy |
| 8 | 11模块220+参数完整初始化 | DEV_PARAM_CONFIG §三.1-§三.11 | arch |
| 9 | **V2新增参数(回测22+AI闭环28=50个)** | **DEV_PARAM_CONFIG §六** (旧版遗漏) | arch |
| 10 | 参数变更日志param_change_log | DEV_PARAM_CONFIG补丁P1 | arch |
| 11 | **参数变更安全机制(即时检查+影响预估+版本+回滚)** | **DEV_PARAM_CONFIG §四** (旧版遗漏) | arch |
| 12 | **参数变更约束规则** | **DEV_PARAM_CONFIG §七** (旧版遗漏) | arch |
| 13 | **A股4级熔断机制(L1-L4)代码实现** | **DESIGN_V5 §8.1** (旧版遗漏) | arch+quant |
| 14 | **模块协同通知调用点(25处)** | **DEV_BACKEND §五.2** (旧版遗漏) | arch |

**代码产出**:
```
backend/app/
  ├── services/
  │   ├── notification_service.py
  │   ├── notification_throttler.py
  │   ├── notification_templates.py
  │   ├── param_service.py
  │   ├── risk_control_service.py  — 4级熔断(新建)
  │   └── dispatchers/dingtalk.py
  ├── api/
  │   ├── notifications.py (9端点)
  │   └── params.py
```

## Sprint 1.2: 回测引擎升级(Hybrid Step 2+3) [2-3周]

**输入**: DEV_BACKTEST_ENGINE.md §四-§五全部

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | **双因素滑点模型(Volume-impact)** | **DEV_BACKTEST §4.10** (旧版遗漏) | arch+quant |
| 2 | **UniverseFilter 8层完整实现** | **DEV_BACKTEST §4.3** (旧版遗漏) | arch |
| 3 | Universe AI动态门槛 | DESIGN_V5 §5.2 | arch+strategy |
| 4 | **FactorAnalyzer完整实现(IC/分组/衰减/相关/行业)** | **DEV_BACKTEST §4.13** (旧版遗漏) | arch+factor |
| 5 | **市场状态检测(牛/熊/震荡)** | **DEV_BACKTEST §4.14** (旧版遗漏) | arch+strategy |
| 6 | **Walk-Forward完整引擎** | **DEV_BACKTEST §4.12** (旧版遗漏) | arch |
| 7 | **Deflated Sharpe Ratio (DSR)** | **DEV_BACKTEST §4.12.1** (旧版遗漏) | quant+arch |
| 8 | **Probability of Backtest Overfitting (PBO)** | **DEV_BACKTEST §4.12.2** (旧版遗漏) | quant+arch |
| 9 | **回测Celery异步任务化** | **DEV_BACKTEST §4.12.3** (旧版遗漏) | arch |
| 10 | **BaseStrategy接口(可视化/代码双模式)** | **DEV_BACKTEST §4.12.4** (旧版遗漏) | arch |
| 11 | **一键验证管道** | **DESIGN_V5 §十三** (旧版遗漏) | qa |
| 12 | **归因分析模块(Brinson因子/行业/时间/成本)** | **DESIGN_V5 §十四** (旧版遗漏) | strategy+arch |
| 13 | 组合构建7步完整链路 | DESIGN_V5 §6.1-§6.8 | arch+strategy |
| 14 | **回测API(14个端点)** | **DEV_BACKTEST §七** (旧版遗漏) | arch |

**代码产出**:
```
backend/app/
  ├── services/
  │   ├── backtest/
  │   │   ├── hybrid_backtester.py     — Hybrid架构
  │   │   ├── walk_forward_engine.py   — WF完整引擎
  │   │   ├── execution_simulator.py   — Step 2完整
  │   │   ├── slippage_model.py        — 双因素滑点
  │   │   └── dsr_pbo.py              — DSR+PBO
  │   ├── factor_analyzer.py           — 单因子完整分析
  │   ├── market_state.py              — 市场状态检测
  │   ├── attribution.py               — Brinson归因
  │   ├── universe_filter.py           — 8层过滤
  │   └── portfolio_builder.py         — 7步组合构建
  ├── api/backtest.py (14端点)
```

## Sprint 1.3: Phase 1数据源 + 因子扩展 [1周]

**输入**: TUSHARE_CHECKLIST §2.9-§2.11、DESIGN_V5 §4.2-§4.7

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | **forecast(业绩预告)数据接入** | **TUSHARE_CHECKLIST §2.9** (旧版遗漏) | data |
| 2 | **share_float(限售解禁)数据接入** | **TUSHARE_CHECKLIST §2.10** (旧版遗漏) | data |
| 3 | **stk_holdernumber(股东人数)数据接入** | **TUSHARE_CHECKLIST §2.11** (旧版遗漏) | data |
| 4 | **AKShare备用数据源映射建立** | **TUSHARE_CHECKLIST §八** (旧版遗漏) | data |
| 5 | northbound_holdings数据接入(AKShare) | DESIGN_V5 §9.1 | data |
| 6 | moneyflow数据完善 | TUSHARE_CHECKLIST §2.7 | data |
| 7 | **因子衰减处置流程实现** | **DESIGN_V5 §4.5** (旧版遗漏) | factor+arch |
| 8 | **因子择时机制** | **DESIGN_V5 §4.6** (旧版遗漏) | factor+strategy |
| 9 | 新因子实现(资金流/北向/事件驱动) | DESIGN_V5 §4.2类别③-④ | factor+arch |
| 10 | **Data Contract YAML机制** | **DESIGN_V5 §9.2** (旧版遗漏) | data |
| 11 | **因子计算跨表单位对齐规范** | **TUSHARE_CHECKLIST §六** (旧版遗漏) | data+quant |

## Sprint 1.4: 前端Dashboard + 核心页面 [2-3周]

**输入**: DEV_FRONTEND_UI.md全文

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | React项目搭建(Vite+Tailwind+Zustand) | DEV_FRONTEND §一.1 | arch |
| 2 | **设计系统(Design Token+色彩+字体+间距+动效)** | **DEV_FRONTEND §十** (旧版遗漏) | arch |
| 3 | **前端路由体系+导航栏+面包屑** | **DEV_FRONTEND §九** (旧版遗漏) | arch |
| 4 | **空/加载/错误态处理(3级)** | **DEV_FRONTEND §十二** (旧版遗漏) | arch |
| 5 | **实时数据更新策略(WS/轮询/SSE)** | **DEV_FRONTEND §十一** (旧版遗漏) | arch |
| 6 | Dashboard/总览页(方案C) | DEV_FRONTEND §八 | arch |
| 7 | 回测结果分析页(8Tab含归因+WF+敏感性) | DEV_FRONTEND §2.4+补丁P1 | arch |
| 8 | 因子库页面(IC热力图+生命周期) | DEV_FRONTEND §3.4 | arch |
| 9 | 系统设置页(参数+调度+通知偏好) | DEV_FRONTEND §5.1 | arch |
| 10 | 通知中心(Toast+铃铛+跳转映射) | DEV_FRONTEND §十三 | arch |
| 11 | **Paper Trading状态展示** | DEV_FRONTEND补丁P2 | arch |
| 12 | **全局交互规范(资金约束提示/FDR/移动端)** | **DEV_FRONTEND §六** (旧版遗漏) | arch |
| 13 | **涨跌颜色可配置** | **DEV_FRONTEND §一.3** (旧版遗漏) | arch |
| 14 | **48个API端点对接** | **DEV_FRONTEND §七** (旧版遗漏) | arch |

## Sprint 1.5: miniQMT实盘对接 [2周]

**输入**: DEV_BACKEND补丁P3、DESIGN_V5 §十二

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | BaseBroker ABC定义 | DEV_BACKEND补丁P3 | arch |
| 2 | SimBroker重构(继承BaseBroker) | DEV_BACKEND补丁P3 | arch |
| 3 | MiniQMTBroker实现 | DEV_BACKEND补丁P3 | arch |
| 4 | get_broker()工厂+EXECUTION_MODE切换 | DEV_BACKEND补丁P3 | arch |
| 5 | **策略版本管理(JSONB+active_version+回滚)** | **DEV_BACKEND补丁P4** (旧版遗漏) | arch |
| 6 | TWAP/VWAP分拆下单 | DESIGN_V5 §12.1 | arch+strategy |
| 7 | 1手真实下单测试 | — | qa |

**Agent Teams任务**: Playbook #10 压力测试方案设计、#11 实盘上线前终审

## Sprint 1.6: AI因子挖掘(3引擎完整) [3-4周]

**输入**: DEV_FACTOR_MINING.md全文

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | 暴力枚举引擎(+剪枝) | DEV_FACTOR_MINING §13.2+补丁P4 | arch+factor |
| 2 | GP遗传编程引擎(+复杂度惩罚+岛屿模型) | DEV_FACTOR_MINING §3+补丁P3 | arch+factor |
| 3 | Idea Agent(System Prompt+User Prompt动态构建) | DEV_FACTOR_MINING §2.1全部 | arch |
| 4 | Factor Agent(代码模板+重试Prompt) | DEV_FACTOR_MINING §2.2全部 | arch |
| 5 | **Eval Agent(自动化评估管道)** | **DEV_FACTOR_MINING §2.3** (旧版遗漏) | arch |
| 6 | **反馈Prompt+输出格式校验** | **DEV_FACTOR_MINING §2.4+§2.5** (旧版遗漏) | arch |
| 7 | Gate Pipeline(IC/IR/单调/t检验) | DEV_FACTOR_MINING §13.1 | quant+arch |
| 8 | **UCB1 Multi-Armed Bandit调度器** | **DEV_FACTOR_MINING §四** (旧版遗漏) | arch |
| 9 | **沙箱安全执行环境(exec+资源限制+超时)** | **DEV_FACTOR_MINING §13.3** (旧版遗漏) | arch |
| 10 | **因子工具函数库(时序+截面)** | **DEV_FACTOR_MINING §十一** (旧版遗漏) | arch+factor |
| 11 | 知识库mining_knowledge(Spearman去重) | DEV_FACTOR_MINING §六+补丁P6 | data |
| 12 | **因子生命周期状态机(完整转换触发)** | **DEV_FACTOR_MINING §13.4+补丁P7** (旧版遗漏) | factor+arch |
| 13 | **因子拥挤度监控** | **DEV_FACTOR_MINING补丁P8** (旧版遗漏) | factor |
| 14 | **LLM三Agent质量控制** | **DEV_FACTOR_MINING补丁P5** (旧版遗漏) | quant |
| 15 | **Prompt版本管理+A/B测试** | **DEV_FACTOR_MINING §八** (旧版遗漏) | arch |
| 16 | **一轮完整挖掘流程编排** | **DEV_FACTOR_MINING §五** (旧版遗漏) | arch |
| 17 | DeepSeek API集成+成本追踪 | DEV_AI_EVOLUTION §七 | arch |
| 18 | **LLM调用参数配置(temperature等)** | **DEV_FACTOR_MINING §七** (旧版遗漏) | arch |

## Sprint 1.7: AI闭环 + 诊断 [2-3周]

**输入**: DEV_AI_EVOLUTION.md全文

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | Pipeline Orchestrator状态机(8个状态) | DEV_AI_EVOLUTION §四.2+§七 | arch |
| 2 | 因子发现Agent完整(阈值+Prompt+输出解析) | DEV_AI_EVOLUTION §5.1+§16.1 | arch+factor |
| 3 | **策略构建Agent(Optuna搜索空间20+参数)** | **DEV_AI_EVOLUTION §5.2+§16.2** (旧版遗漏) | arch+strategy |
| 4 | 诊断Agent(事件驱动触发+阈值表10项) | DEV_AI_EVOLUTION补丁P1+§16.1 | arch+quant |
| 5 | 风控Agent(审查+一票否决) | DEV_AI_EVOLUTION §5.4 | arch+quant |
| 6 | **Agent输入context组装逻辑** | **DEV_AI_EVOLUTION补丁P2** (旧版遗漏) | arch |
| 7 | 变更→快速回测→审批三步流程 | DEV_AI_EVOLUTION补丁P3 | arch |
| 8 | **四级自动化控制(L0→L3切换)** | **DEV_AI_EVOLUTION §六** (旧版遗漏) | arch |
| 9 | **循环限制(max_rounds=3)** | **DEV_AI_EVOLUTION §四.3** (旧版遗漏) | arch |
| 10 | Agent冲突仲裁(风控一票否决) | DEV_AI_EVOLUTION补丁P4 | quant |
| 11 | **月度成本追踪器(¥500预算)** | **DESIGN_V5 §25** (旧版遗漏) | arch |
| 12 | 审批队列approval_queue完整流程 | DEV_AI_EVOLUTION §11.6 | arch |
| 13 | **AI闭环Celery Beat调度** | **DEV_AI_EVOLUTION §十三** (旧版遗漏) | arch |
| 14 | **AI闭环API(20+端点)** | **DEV_AI_EVOLUTION §十** (旧版遗漏) | arch |
| 15 | 滚动绩效视图(20/60/120天) | DEV_AI_EVOLUTION补丁P1 | data |

## Sprint 1.8: ML模型体系 [2周]

**输入**: DEV_BACKEND §十二

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | **BaseMLPredictor基类** | **DEV_BACKEND §12.4** (旧版遗漏) | arch |
| 2 | **LightGBM因子合成(替代等权)** | **DEV_BACKEND §12.2 Phase 1** (旧版遗漏) | arch+factor |
| 3 | **随机森林baseline** | **DEV_BACKEND §12.2 Phase 1** (旧版遗漏) | arch |
| 4 | **Optuna超参搜索(LightGBM+策略参数)** | **DEV_BACKEND §12.2 Phase 1** (旧版遗漏) | arch+strategy |
| 5 | Purged K-Fold / Walk-Forward验证 | DEV_BACKEND §12.2约束 | quant |
| 6 | Top 10 feature importance可解释性 | DEV_BACKEND §12.2约束 | factor |
| 7 | model_registry表CRUD | DESIGN_V5 §10域6 | arch |
| 8 | ML→等权A/B测试(ML必须>等权10%Sharpe) | DEV_BACKEND §12.2 | strategy |

## Sprint 1.9: 前端完善(回测5页面+因子3页面) [2-3周]

**输入**: DEV_FRONTEND_UI §二-§三

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | **策略工作台(因子面板+双模式+AI助手)** | **DEV_FRONTEND §2.1** (旧版遗漏) | arch |
| 2 | **回测配置面板(5个Tab)** | **DEV_FRONTEND §2.2** (旧版遗漏) | arch |
| 3 | **回测运行监控(WS实时进度)** | **DEV_FRONTEND §2.3** (旧版遗漏) | arch |
| 4 | **策略库(列表+对比+历史)** | **DEV_FRONTEND §2.5** (旧版遗漏) | arch |
| 5 | **因子实验室(5种创建方式)** | **DEV_FRONTEND §3.1** (旧版遗漏) | arch |
| 6 | **挖掘任务中心(监控+进度+统计)** | **DEV_FRONTEND §3.2** (旧版遗漏) | arch |
| 7 | **因子评估报告(6个Tab)** | **DEV_FRONTEND §3.3** (旧版遗漏) | arch |

## Sprint 1.10: Phase 1收尾 + 实盘切换 [1-2周]

**输入**: AGENT_TEAMS_PLAYBOOK、DESIGN_V5 §26

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | Paper Trading 60天毕业评估 | DESIGN_V5 §12.2 | quant+strategy |
| 2 | **Agent Teams #5 代码全面审计(4角度)** | **PLAYBOOK任务5** (旧版遗漏) | Agent Teams |
| 3 | **Agent Teams #10 压力测试** | **PLAYBOOK任务10** (旧版遗漏) | Agent Teams |
| 4 | **Agent Teams #11 实盘上线终审** | **PLAYBOOK任务11** (旧版遗漏) | Agent Teams |
| 5 | EXECUTION_MODE: paper→live切换 | DEV_BACKEND补丁P3 | arch |
| 6 | **心理纪律5条铁律写入运维手册** | **DESIGN_V5 §26** (旧版遗漏) | Team Lead |
| 7 | Phase 1复盘→LESSONS_LEARNED.md | TEAM_CHARTER §6.1 | 全员 |
| 8 | **Agent Teams #7 AI闭环架构辩论(为Phase 3预研)** | **PLAYBOOK任务7** (旧版遗漏) | Agent Teams |

---

# Phase 2: 外汇MT5

> 前置: Agent Teams #9 跨市场风险分析

## Sprint 2.0: 外汇基础设施 [1-2周]

**输入**: DEV_FOREX.md §一-§三、QUANTMIND_V2_FOREX_DESIGN.md全文

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | MT5Broker(继承BaseBroker) | DEV_FOREX §十 | arch |
| 2 | MT5数据适配器(D1/H4/H1/M15) | DEV_FOREX §三.3 | data |
| 3 | HistData.com回测数据导入 | DEV_FOREX §三.2 | data |
| 4 | forex_bars/forex_events/forex_swap_rates拉取 | DEV_FOREX §三.1 | data |
| 5 | **外汇数据质量验证checklist** | **DEV_FOREX §三.5** (旧版遗漏) | data |
| 6 | 外汇交易日历(UTC+夏令时) | DEV_SCHEDULER §三 | data |
| 7 | 外汇调度链路(UTC 22:00) | DEV_SCHEDULER §三+周末特殊 | arch |
| 8 | **MT5 retcode处理+filling_type兼容** | **DEV_FOREX §10.4-§10.5** (旧版遗漏) | arch |
| 9 | **MT5持仓同步+异常重连** | **DEV_FOREX §10.6-§10.7** (旧版遗漏) | arch |
| 10 | A股外汇共享组件路由 | DEV_BACKEND §五.3 | arch |

## Sprint 2.1: 外汇因子 + 信号 + 风控 [2周]

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | 宏观因子Layer 1(利率差/PMI/CPI 6因子) | DEV_FOREX §4.2 | factor |
| 2 | 技术因子Layer 2(15因子×14品种) | DEV_FOREX §4.3 | factor |
| 3 | 信号合成(宏观+技术) | DEV_FOREX §4.5 | strategy |
| 4 | **外汇4层纵深风控(14项)** | **DEV_FOREX §八** (旧版遗漏) | quant+arch |
| 5 | **组合仓位管理(单笔/相关性/货币暴露/保证金)** | **DEV_FOREX §七** (旧版遗漏) | strategy+arch |
| 6 | **14品种成本模型(点差+Swap+滑点+TCA)** | **DEV_FOREX §九** (旧版遗漏) | data+strategy |
| 7 | 跨市场风控(A股+外汇相关性监控) | DESIGN_V5 §8.3 | quant |
| 8 | 关联敞口限制(corr>0.7合并计算) | DESIGN_V5 §8.3 | quant |

## Sprint 2.2: 外汇回测 + ML [1-2周]

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | 外汇回测引擎(SimBroker外汇版) | DEV_FOREX §六 | arch |
| 2 | **日内SL/TP精度** | **DEV_FOREX §6.4** (旧版遗漏) | arch |
| 3 | 外汇Walk-Forward | DEV_FOREX §6.5 | arch |
| 4 | **外汇因子挖掘适配(Prompt/模板/Gate/GP)** | **DEV_FOREX §十一** (旧版遗漏) | factor+arch |
| 5 | **外汇ML(LightGBM+Optuna+RF)** | **DEV_FOREX §十二** (旧版遗漏) | arch |
| 6 | **外汇LLM选型(可配置多模型)** | **DEV_FOREX §十三** (旧版遗漏) | arch |
| 7 | **A股ML同步升级** | **DEV_FOREX §十四** (旧版遗漏) | arch |
| 8 | 跨市场资金分配(A70%/外30%) | DEV_FOREX §7.6 | strategy |

## Sprint 2.3: 外汇Paper Trading + 上线 [1-2周]

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | 外汇Paper Trading(MT5 demo) | DEV_FOREX §15.1 | arch |
| 2 | **外汇实盘切换检查清单** | **DEV_FOREX §15.2** (旧版遗漏) | qa |
| 3 | **切换操作+回退方案** | **DEV_FOREX §15.3-§15.4** (旧版遗漏) | arch |
| 4 | Agent Teams #9 跨市场风险分析 | PLAYBOOK任务9 | Agent Teams |
| 5 | 外汇实盘上线 | — | 用户审批 |
| 6 | Phase 2复盘 | TEAM_CHARTER §6.1 | 全员 |

---

# Phase 3: AI闭环完整 + 多策略 + 前端完整

## Sprint 3.0: AI完全自动化 [2周]

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | AI闭环L1→L2→L3升级 | DEV_AI_EVOLUTION §六 | arch |
| 2 | **交互因子搜索空间(AI闭环探索)** | **DESIGN_V5 §4.7** (旧版遗漏) | factor+arch |
| 3 | Phase 3 ML集成(XGBoost+MLP+GRU) | DEV_BACKEND §12.2 Phase 3 | arch |
| 4 | 集成投票(3模型加权+共识度) | DEV_BACKEND §12.2 Phase 3 | arch+strategy |

## Sprint 3.1: 多策略组合 [2周]

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | 多子策略框架(动量+价值+反转) | DESIGN_V5 §6 | arch+strategy |
| 2 | 策略间资金分配(等权/风险平价) | DESIGN_V5 §6.4 | strategy |
| 3 | 策略相关性监控 | DESIGN_V5 §8 | quant |
| 4 | 组合层面风控 | DESIGN_V5 §8.1 | quant+arch |

## Sprint 3.2: 前端完整(剩余5页面) [2周]

**输入**: DEV_FRONTEND_UI §四-§五

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | Pipeline控制台(4级自动化+审批) | DEV_FRONTEND §4.1 | arch |
| 2 | Agent配置页(4Agent参数面板) | DEV_FRONTEND §4.2 | arch |
| 3 | 外汇交易面板 | DEV_FRONTEND §十外汇 | arch |
| 4 | **Figma审查改进落地** | **DEV_FRONTEND §十四** (旧版遗漏) | arch |
| 5 | **Celery Flower/监控Dashboard** | **DEV_SCHEDULER §八** (旧版遗漏) | arch |

## Sprint 3.3: Phase 3收尾 [1周]

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | 全系统集成测试(A股+外汇+AI) | DEV_BACKEND §七 | qa |
| 2 | 压力测试(A股+外汇同时) | PLAYBOOK #10 | Agent Teams |
| 3 | 运维手册完善 | DEV_SCHEDULER全文 | Team Lead |
| 4 | **月度策略review流程建立** | **PLAYBOOK任务12** (旧版遗漏) | 全员 |
| 5 | Phase 3复盘 | TEAM_CHARTER §6.1 | 全员 |

---

# Phase 4: Mac Studio迁移

## Sprint 4.0 [1-2周]

| # | 任务 | 文档来源 | 负责 |
|---|------|---------|------|
| 1 | Mac Studio环境搭建 | DESIGN_V5 §3.3 | arch |
| 2 | pg_dump→pg_restore迁移 | DEV_SCHEDULER补丁P3 | data |
| 3 | launchd替代crontab | — | arch |
| 4 | Phase 4 ML(GRU/Transformer/GNN) | DEV_BACKEND §12.2 Phase 4 | arch |
| 5 | MLX本地模型(替代DeepSeek API) | DESIGN_V5 §3.2 | arch |
| 6 | 全链路验证 | — | qa |

---

# 文档→Sprint 完整映射（验证100%覆盖）

| 文档 | 覆盖Sprint |
|------|-----------|
| CLAUDE.md | 全程(每次启动读) |
| TEAM_CHARTER.md | 全程(团队宪法) |
| DDL_FINAL.sql | Phase 0✅已落地 |
| TUSHARE_CHECKLIST §1-§2.8 | Phase 0✅已落地 |
| TUSHARE_CHECKLIST §2.9-§2.11,§6,§8 | Sprint 1.3 |
| DESIGN_V5 §1-§3 | 全程参考 |
| DESIGN_V5 §4(因子) | Phase 0部分 + Sprint 1.3+1.6 |
| DESIGN_V5 §5(Universe) | Phase 0简化 + Sprint 1.2 |
| DESIGN_V5 §6(组合) | Phase 0简化 + Sprint 1.2 |
| DESIGN_V5 §7(AI层) | Sprint 1.6+1.7 |
| DESIGN_V5 §8(风控) | Sprint 1.1+2.1+3.1 |
| DESIGN_V5 §9(DataHub) | Phase 0+Sprint 1.3 |
| DESIGN_V5 §10(Schema) | Phase 0✅ |
| DESIGN_V5 §11(回测) | Phase 0简化+Sprint 1.2 |
| DESIGN_V5 §12(执行) | Sprint 0.2+1.5 |
| DESIGN_V5 §13(验证) | Sprint 1.2 |
| DESIGN_V5 §14(归因) | Sprint 1.2 |
| DESIGN_V5 §15(前端) | Sprint 1.4+1.9+3.2 |
| DESIGN_V5 §17(AI闭环) | Sprint 1.7 |
| DESIGN_V5 §25(成本) | Sprint 1.7 |
| DESIGN_V5 §26(心理纪律) | Sprint 1.10 |
| DESIGN_V5 §27(协作) | TEAM_CHARTER |
| DESIGN_V5补丁P1-P7 | Sprint 0.2+1.0+1.2 |
| DEV_BACKEND §1-§6 | Sprint 1.0 |
| DEV_BACKEND §7-§10 | Sprint 1.0 |
| DEV_BACKEND §11 | 参考 |
| DEV_BACKEND §12(ML) | Sprint 1.8 |
| DEV_BACKEND补丁P1-P4 | Sprint 1.0+1.5 |
| DEV_BACKTEST §1-§5 | Phase 0简化+Sprint 1.2 |
| DEV_BACKTEST §6-§8 | Sprint 1.4(前端)+DDL |
| DEV_BACKTEST补丁P1-P10 | Phase 0+Sprint 1.2 |
| DEV_FACTOR_MINING全文 | Sprint 1.6 |
| DEV_AI_EVOLUTION全文 | Sprint 1.7 |
| DEV_FRONTEND §1-§13 | Sprint 1.4+1.9+3.2 |
| DEV_FRONTEND §14(Figma) | Sprint 3.2 |
| DEV_SCHEDULER全文 | Sprint 1.0+2.0 |
| DEV_NOTIFICATIONS全文 | Sprint 1.1 |
| DEV_PARAM_CONFIG全文 | Sprint 1.1 |
| DEV_FOREX全文 | Sprint 2.0-2.3 |
| FOREX_DESIGN全文 | Sprint 2.0(参考) |
| PLAYBOOK #1-5 | Phase 0✅ |
| PLAYBOOK #6 | Paper Trading Day 30 |
| PLAYBOOK #7-8 | Sprint 1.10(预研Phase 3) |
| PLAYBOOK #9 | Sprint 2.3前 |
| PLAYBOOK #10-11 | Sprint 1.10 |
| PLAYBOOK #12 | Sprint 3.3起持续 |

---

# 用户决策点

| Sprint | 决策内容 | §3.6级别 |
|--------|---------|---------|
| 0.1 | R2真实Sharpe+毕业标准 | §3.6.3 |
| 1.0 | PHASE_1_PLAN.md审批 | §3.6.3 |
| Day 30 | Paper Trading中期评估 | §3.6.3 |
| Day 60 | Paper Trading毕业评估 | §3.6.3 |
| 1.5 | miniQMT真实下单授权 | §3.6.3 |
| 1.8 | ML替代等权决策 | §3.6.3 |
| 1.10 | A股实盘上线审批 | §3.6.3 |
| 2.3 | 外汇实盘上线审批 | §3.6.3 |
| 攻关时 | 3天未解决上报 | §3.6.3 |
| 其余 | 团队自主 | §3.6.1-2 |
