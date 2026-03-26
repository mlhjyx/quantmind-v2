# 设计文档 vs 代码实现 审计报告（Part 2）

> 审计日期: 2026-03-26
> 审计范围: DEV_BACKTEST_ENGINE.md / DEV_FACTOR_MINING.md / DEV_AI_EVOLUTION.md
> 方法: 逐章节读设计文档，grep/glob在代码中搜索对应实现

---

## 文档3: DEV_BACKTEST_ENGINE.md（回测引擎）

### 二、已确认决策

| 决策 | 状态 | 说明 |
|------|------|------|
| #1 Hybrid架构(向量化信号+事件驱动执行) | ✅ 已实现 | `backend/engines/backtest_engine.py` SimpleBacktester采用先生成target_portfolios再逐日执行 |
| #2 成交价次日开盘 | ✅ 已实现 | `backtest_engine.py:177,217` execute_sell/execute_buy均用`row["open"]` |
| #3 滑点模型Volume-impact | ✅ 已实现 | `backend/engines/slippage_model.py` 完整的volume_impact_slippage函数 |
| #4 交易成本(佣金+印花税+过户费) | ✅ 已实现 | `backtest_engine.py:181-186,227-229` commission/stamp_tax/transfer_fee |
| #5 三步渐进(Step1信号验证→Step2执行模拟→Step3 WF) | ⚠️ 部分实现 | Step1(SimpleBacktester)✅ + Step3(WalkForward)✅, Step2(ExecutionSimulator)❌未实现 |
| #6 WF窗口 | ✅ 已实现 | `backend/engines/walk_forward.py` WFConfig支持可配置窗口 |
| #7 结果存储PG | ✅ 已实现 | `paper_broker.py` 写入trade_log/position_snapshot/performance_series |
| #8 Forward return 1/5/10/20日 | ✅ 已实现 | `backend/engines/factor_analyzer.py:353` _calc_ic_decay计算多周期IC |
| #9 因子预处理MAD→zscore→中性化 | ✅ 已实现 | `factor_engine.py:664-793` preprocess_pipeline: MAD→fill→neutralize→zscore |
| #10 未成交资金现金持有 | ✅ 已实现 | `backtest_engine.py:498` 封板时跳过买入，资金留在broker.cash |
| #11 停牌复牌 | ✅ 已实现 | `backtest_engine.py:132-133` volume=0时can_trade返回False |
| #12 涨跌停三级fallback | ✅ 已实现 | `backtest_engine.py:142-153` 优先用up_limit/down_limit字段，缺失时按price_limit推算 |
| #13 基准沪深300 | ✅ 已实现 | `backtest_engine.py:40` benchmark_code="000300.SH" |
| #14 超额收益对数相减 | ⚠️ 简化实现 | `factor_analyzer.py` IC用Spearman rank IC（等效但非对数相减），metrics.py用算术减法 |
| #15 调仓日历可配置 | ✅ 已实现 | `signal_engine.py:274-336` get_rebalance_dates支持weekly/biweekly/monthly |
| #16 不支持做空 | ✅ 已实现 | SimBroker只有buy/sell方向，无short逻辑 |
| #17 滑点k系数按市值分层 | ✅ 已实现 | `slippage_model.py:122-126` 小盘股惩罚, 市值<50亿额外1.2x |

### 三、后端架构

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §3.1 Hybrid数据流(Phase A向量化 + Phase B事件驱动) | ✅ 已实现 | `backtest_engine.py` target_portfolios(向量化) → 逐日循环执行(事件驱动) |
| §3.3 目录结构（设计文档规划的模块化目录） | ⚠️ 实际不同 | 设计规划了config/data/factors/signal/backtest/analysis等独立目录; 实际代码在backend/engines/下扁平组织 |

### 四、核心类接口

| 功能点 | 状态 | 文件:行号 |
|--------|------|-----------|
| §4.1 BacktestConfig | ⚠️ 简化版 | `backtest_engine.py:29-40` 实现了核心字段(capital/top_n/slippage/commission等)，但缺少设计文档中的universe/market/regime/WF等完整字段 |
| §4.1 SlippageConfig | ✅ 已实现 | `slippage_model.py` 独立文件实现了完整Volume-impact模型 |
| §4.1 CostConfig | ✅ 已实现 | `backtest_engine.py:35-38` commission_rate/stamp_tax_rate/transfer_fee_rate |
| §4.1 MarketRegimeConfig | ❌ 未实现 | 代码中无MarketRegimeConfig类，无MA120牛熊震荡判断逻辑 |
| §4.2 DataFeed | ❌ 未实现 | 无独立DataFeed类，数据加载分散在scripts/factor_engine中 |
| §4.3 UniverseFilter(8层过滤) | ❌ 未实现 | 代码中无UniverseFilter类，无8层过滤逻辑 |
| §4.4 涨跌停幅度按板块判定 | ✅ 已实现 | `backtest_engine.py:148-151` symbols_info中的price_limit字段 |
| §4.5 BaseFactor + FactorRegistry | ❌ 未实现 | 无BaseFactor抽象基类/FactorRegistry注册中心，因子用函数式实现(factor_engine.py各calc_*函数) |
| §4.6 FactorPreprocessor(MAD→zscore→中性化) | ✅ 已实现 | `factor_engine.py:664-793` 四个preprocess_*函数 + preprocess_pipeline |
| §4.7 SignalComposer | ✅ 已实现 | `signal_engine.py:114-164` 等权合成 + 方向调整 |
| §4.7 PortfolioBuilder | ✅ 已实现 | `signal_engine.py:167-271` top-N选股 + 行业约束 + 换手率约束 |
| §4.8 IBacktester Protocol | ❌ 未实现 | 无Protocol定义，SimpleBacktester直接实现 |
| §4.8 SimpleBacktester | ✅ 已实现 | `backtest_engine.py:277-654` 完整实现含封板补单 |
| §4.8 BacktestResult | ✅ 已实现 | `backtest_engine.py:86-97` 包含nav/returns/trades/holdings/turnover/pending_order_stats |
| §4.9 ExecutionSimulator(Step 2) | ❌ 未实现 | 无ExecutionSimulator类; SimBroker直接内嵌在SimpleBacktester中已包含大部分约束检查 |
| §4.9 ConstraintChecker | ❌ 未实现 | 无独立ConstraintChecker类; 约束检查内嵌在SimBroker.can_trade() |
| §4.10 SlippageModel(类) | ✅ 已实现 | `slippage_model.py` volume_impact_slippage函数（函数式非类式） |
| §4.11 CostModel(类) | ❌ 未实现 | 无独立CostModel类; 成本计算内嵌在SimBroker.execute_buy/sell中 |
| §4.12 WalkForwardEngine | ✅ 已实现 | `backend/engines/walk_forward.py` 完整WF引擎含splits/fold/combine |
| §4.12.1 DSR(Deflated Sharpe Ratio) | ✅ 已实现 | `backend/engines/dsr.py` 完整DSR实现 |
| §4.12.2 PBO(Probability of Backtest Overfitting) | ✅ 已实现 | `backend/engines/pbo.py` 完整CSCV方法实现 |
| §4.12.3 Celery Task模板(异步回测) | ❌ 未实现 | 代码中无astock_backtest_task, 无WebSocket进度推送 |
| §4.12.4 BaseStrategy接口 | ❌ 未实现 | 无BaseStrategy抽象基类 |

### 回测可信度规则（CLAUDE.md 6条强制规则）

| 规则 | 状态 | 文件:行号 |
|------|------|-----------|
| 规则1: 涨跌停封板处理 | ✅ 已实现 | `backtest_engine.py:118-166` can_trade()函数，含停牌/涨停/跌停判断 |
| 规则2: 整手约束 | ✅ 已实现 | `backtest_engine.py:222` floor(target/price/100)*100 |
| 规则2: 资金T+1 | ✅ 已实现 | `backtest_engine.py:116,195-196` _sell_proceeds_today跟踪 |
| 规则3: 确定性测试Parquet快照 | ⚠️ 部分实现 | `backend/tests/test_factor_determinism.py` 存在但实际是因子确定性测试，非Parquet快照回测 |
| 规则4: Bootstrap Sharpe CI | ✅ 已实现 | `backend/engines/metrics.py:149-175` bootstrap_sharpe_ci() |
| 规则5: 隔夜跳空统计 | ✅ 已实现 | `backend/engines/metrics.py:234-262` calc_open_gap_stats() |
| 规则6: 成本敏感性分析 | ✅ 已实现 | `backend/engines/metrics.py:302-313` 0.5x/1.0x/1.5x/2.0x |

### 绩效指标（CLAUDE.md 报告必含指标）

| 指标 | 状态 | 文件:行号 |
|------|------|-----------|
| Sharpe | ✅ | `metrics.py:61-66` |
| MDD | ✅ | `metrics.py:69-73` |
| Calmar | ✅ | `metrics.py:85-89` |
| Sortino | ✅ | `metrics.py:76-82` |
| Beta | ✅ | `metrics.py:92-99` |
| IR (信息比率) | ✅ | `metrics.py:102-110` |
| 胜率+盈亏比 | ✅ | `metrics.py:121-146` |
| 最大连续亏损天数 | ✅ | `metrics.py:113-118` |
| 月度收益热力图 | ✅ | `metrics.py:215-231` |
| 年度分解 | ✅ | `metrics.py:178-212` |
| Bootstrap CI | ✅ | `metrics.py:149-175` |
| 成本敏感性 | ✅ | `metrics.py:302-313` |
| 隔夜跳空 | ✅ | `metrics.py:234-262` |
| 实际vs理论仓位偏差 | ⚠️ TODO | `metrics.py:319` 字段存在但值固定为0.0 |
| 年化换手率 | ✅ | `metrics.py:296-297` |
| 市场状态分段(牛/熊/震荡) | ❌ 未实现 | 无regime分段代码 |

### 其他

| 功能点 | 状态 | 说明 |
|--------|------|------|
| Broker策略模式(SimBroker/MiniQMT/MT5) | ⚠️ 部分实现 | SimBroker✅ `backtest_engine.py`, MiniQMTBroker✅ `broker_qmt.py`, MT5Broker❌未实现; 无共用BaseBroker抽象基类 |
| PaperBroker(状态持久化) | ✅ 已实现 | `backend/engines/paper_broker.py` 完整实现load_state/save_state/execute_rebalance |
| 封板补单(PendingOrder) | ✅ 已实现 | `backtest_engine.py:59-83,522-654` 完整pending order机制 |
| QuantStats HTML报告 | ✅ 已实现 | `backend/wrappers/quantstats_wrapper.py` |
| Brinson归因 | ✅ 已实现 | `backend/engines/attribution.py` BrinsonAttribution类 |
| 回测API | ⚠️ 部分实现 | `backend/app/api/backtest.py` 存在但功能有限 |
| WebSocket进度推送 | ❌ 未实现 | 无WebSocket manager实现 |
| 压力测试接口(注入自定义数据) | ❌ 未实现 | SimpleBacktester接受price_data参数(可注入)，但无专门的压力测试封装 |

---

## 文档4: DEV_FACTOR_MINING.md（因子挖掘系统）

### 1. 架构总览（4引擎并行）

| 功能点 | 状态 | 说明 |
|--------|------|------|
| Engine 1: 暴力枚举 | ❌ 未实现 | 无暴力枚举引擎代码 |
| Engine 2: 开源因子库导入(Alpha158/Alpha101/TA-Lib) | ⚠️ 部分实现 | `backend/wrappers/ta_wrapper.py` TA-Lib wrapper存在; Alpha158/Alpha101无导入框架; KBAR系列因子在factor_engine.py中手动实现 |
| Engine 3: LLM三Agent闭环 | ❌ 未实现 | 无IdeaAgent/FactorAgent/EvalAgent代码 |
| Engine 4: GP遗传编程 | ❌ 未实现 | 无GP引擎代码（ml_engine.py中有deap/gplearn引用但用于LightGBM非因子GP） |
| 共享: 4层Gate Pipeline | ❌ 未实现 | 无Gate Pipeline代码 |
| 共享: mining_knowledge知识库 | ❌ 未实现 | 无mining_knowledge表或知识库代码 |

### 2. Engine 3: LLM三Agent闭环

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §2.1 Idea Agent System Prompt | ❌ 未实现 | 无Prompt定义代码 |
| §2.1.2 User Prompt动态构建 | ❌ 未实现 | |
| §2.1.3 搜索方向Hint(6个) | ❌ 未实现 | |
| §2.1.4 Few-shot经典案例 | ❌ 未实现 | |
| §2.2 Factor Agent | ❌ 未实现 | |
| §2.3 Eval Agent | ❌ 未实现 | |
| §2.4 反馈Prompt | ❌ 未实现 | |
| §2.5 输出格式校验 | ❌ 未实现 | |

### 3. Engine 4: GP遗传编程

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §3.1 GP配置(population/generations等) | ❌ 未实现 | |
| §3.2 适应度函数(IC×w1+IR×w2-corr×w3) | ❌ 未实现 | |

### 4. 调度器（UCB1 Multi-Armed Bandit）

| 功能点 | 状态 | 说明 |
|--------|------|------|
| MiningScheduler + UCB1方向选择 | ❌ 未实现 | |
| 6个搜索方向 + reward更新 | ❌ 未实现 | |

### 5. 一轮完整挖掘流程

| 功能点 | 状态 | 说明 |
|--------|------|------|
| 调度→上下文构建→LLM+GP并行→汇总→更新 | ❌ 未实现 | |

### 6. 知识库Schema

| 功能点 | 状态 | 说明 |
|--------|------|------|
| mining_knowledge表 | ❌ 未实现 | 无DDL或代码引用 |

### 10. 因子生命周期管理

| 功能点 | 状态 | 说明 |
|--------|------|------|
| 状态机(new→active→degraded→archived) | ⚠️ 部分实现 | `scripts/setup_factor_lifecycle.py` + `scripts/create_factor_lifecycle.sql` 创建了factor_lifecycle表; `scripts/monitor_factor_ic.py` 做IC监控; 但无自动状态转移逻辑 |
| 因子健康日检 | ✅ 已实现 | `scripts/factor_health_daily.py` + `backend/engines/factor_analyzer.py` 日检脚本 |

### 11. 工具函数库

| 功能点 | 状态 | 说明 |
|--------|------|------|
| ts_mean/ts_std/ts_rank等时序函数 | ❌ 未实现 | 无`factors/tools.py`; 因子直接用pandas rolling在factor_engine.py中 |
| cs_rank/cs_zscore等截面函数 | ❌ 未实现 | |

### 13. 补充设计

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §13.1 Factor Gate 8项检验(G1-G8) | ❌ 未实现 | 无8项Gate Pipeline代码; factor_analyzer.py做IC分析但非正式Gate |
| §13.1 FDR多重检验校正 | ✅ 已实现 | `backend/engines/config_guard.py` + `backend/tests/test_bh_fdr.py` BH-FDR实现 |
| §13.2 暴力枚举模板(50候选) | ❌ 未实现 | |
| §13.3 沙箱执行(FactorSandbox) | ❌ 未实现 | |

### 已实现但设计文档中有的因子计算

| 功能点 | 状态 | 文件 |
|--------|------|------|
| 18个Phase 0因子(momentum/reversal/vol/turnover/amihud/bp/ep等) | ✅ 已实现 | `factor_engine.py:25-120` |
| KBAR系列因子(kmid/ksft/kup) | ✅ 已实现 | `factor_engine.py:128-177` |
| 资金流因子(mf_divergence/large_order_ratio/money_flow_strength) | ✅ 已实现 | `factor_engine.py:182-237` |
| ML特征(LightGBM) | ✅ 已实现 | `backend/engines/ml_engine.py` |
| 因子IC分析(Spearman/衰减/分组) | ✅ 已实现 | `backend/engines/factor_analyzer.py` |
| 预处理管道(MAD→fill→neutralize→zscore) | ✅ 已实现 | `factor_engine.py:664-793` |
| 批量写入factor_values(单事务) | ✅ 已实现 | `factor_engine.py:991-1037` |

---

## 文档5: DEV_AI_EVOLUTION.md（AI演进闭环）

### 三、三层架构

| 功能点 | 状态 | 说明 |
|--------|------|------|
| Agent层(4个Agent) | ❌ 未实现 | 无任何Agent类代码 |
| 编排层(PipelineOrchestrator) | ❌ 未实现 | 无Pipeline状态机代码 |
| 执行层(已有模块) | ✅ 已实现 | 因子计算/回测/评估等底层模块已有 |

### 四、Pipeline完整流程

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §4.1 闭环流程(发现→评估→审批→构建→回测→风控→诊断) | ❌ 未实现 | |
| §4.2 PipelineState状态机(11个状态) | ❌ 未实现 | |
| §4.3 循环限制(max_loops=3) | ❌ 未实现 | |

### 五、四个Agent详细设计

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §5.1 FactorDiscoveryAgent | ❌ 未实现 | 无代码 |
| §5.1 DiscoveryContext/DiscoveryDecision | ❌ 未实现 | |
| §5.1 DiscoveryAgentConfig | ❌ 未实现 | |
| §5.2 StrategyBuildAgent | ❌ 未实现 | 无代码 |
| §5.2 StrategyContext/StrategyDecision | ❌ 未实现 | |
| §5.3 DiagnosticAgent(诊断树) | ❌ 未实现 | 无代码 |
| §5.3 DiagnosticContext/DiagnosticReport | ❌ 未实现 | |
| §5.4 RiskControlAgent | ❌ 未实现 | 无AI Agent代码; `risk_control_service.py`是规则版风控非AI Agent |
| §5.4 pre_deploy_check | ❌ 未实现 | |
| §5.4 daily_monitor | ❌ 未实现 | |

### 六、四级自动化控制

| 功能点 | 状态 | 说明 |
|--------|------|------|
| L0-L3 四级自动化 | ❌ 未实现 | |
| APPROVAL_RULES映射 | ❌ 未实现 | |

### 七、Pipeline Orchestrator

| 功能点 | 状态 | 说明 |
|--------|------|------|
| PipelineOrchestrator类 | ❌ 未实现 | |
| trigger/advance/on_approval | ❌ 未实现 | |
| _log_decision(写agent_decision_log) | ❌ 未实现 | |

### 十、后端API清单

| API端点 | 状态 | 说明 |
|---------|------|------|
| 10.1 因子挖掘API (16个) | ❌ 全部未实现 | /api/factor/mine/* 等均不存在 |
| 10.2 AI闭环API (10个) | ❌ 全部未实现 | /api/pipeline/* /api/agent/* 均不存在 |

### 十一、数据库表结构(6张新表)

| 表 | 状态 | 说明 |
|------|------|------|
| §11.1 factor_registry | ❌ 未实现 | 无DDL或代码引用 |
| §11.2 factor_evaluation | ❌ 未实现 | |
| §11.3 factor_mining_task | ❌ 未实现 | |
| §11.4 pipeline_run | ❌ 未实现 | |
| §11.5 agent_decision_log | ❌ 未实现 | |
| §11.6 approval_queue | ❌ 未实现 | |
| (补充) factor_lifecycle | ⚠️ 部分实现 | `scripts/create_factor_lifecycle.sql` DDL存在 |

---

## 汇总统计

### DEV_BACKTEST_ENGINE.md

| 状态 | 数量 | 占比 |
|------|------|------|
| ✅ 已实现 | 37 | 62% |
| ⚠️ 部分实现 | 8 | 13% |
| ❌ 未实现 | 15 | 25% |

**关键已实现**: SimBroker(涨跌停/整手/T+1)、SimpleBacktester、WalkForward、DSR、PBO、
全部15项绩效指标(Sharpe/MDD/Calmar/Sortino/Beta/IR/Bootstrap CI/成本敏感性/跳空等)、
SignalComposer、PortfolioBuilder、PaperBroker、封板补单、Brinson归因。

**关键未实现**: ExecutionSimulator(Step2)、UniverseFilter(8层)、DataFeed类、
ConstraintChecker独立类、CostModel独立类、MarketRegimeConfig(牛熊震荡)、
BaseFactor/FactorRegistry抽象层、WebSocket进度推送、Celery异步回测Task。

### DEV_FACTOR_MINING.md

| 状态 | 数量 | 占比 |
|------|------|------|
| ✅ 已实现 | 8 | 22% |
| ⚠️ 部分实现 | 2 | 5% |
| ❌ 未实现 | 27 | 73% |

**关键已实现**: 因子计算函数(18+KBAR+资金流)、预处理管道、IC分析器、BH-FDR校正、
因子健康日检、ML引擎(LightGBM)。

**关键未实现**: 4个引擎(暴力枚举/开源导入/LLM三Agent/GP)、Gate Pipeline、
知识库Schema、调度器(UCB1)、沙箱执行、工具函数库、完整因子生命周期状态机。

### DEV_AI_EVOLUTION.md

| 状态 | 数量 | 占比 |
|------|------|------|
| ✅ 已实现 | 1 | 3% |
| ⚠️ 部分实现 | 1 | 3% |
| ❌ 未实现 | 30 | 94% |

**唯一已实现**: 执行层底层模块(因子计算/回测引擎等)。

**全部未实现**: 4个AI Agent、PipelineOrchestrator、PipelineState状态机、
四级自动化控制、审批队列、6张新DB表(factor_registry/factor_evaluation/
factor_mining_task/pipeline_run/agent_decision_log/approval_queue)、
26个API端点、WebSocket推送。

---

## 总体评估

项目当前处于 **Phase 0 核心实现完成、Phase 1 AI模块尚未启动** 的阶段:

1. **回测引擎核心**: 高度完成。SimBroker + SimpleBacktester + WalkForward + 全套绩效指标已经可用于实际Paper Trading。虽然部分设计文档中的抽象层(Protocol/ABC/Registry)未实现，但功能已通过更直接的方式覆盖。

2. **因子系统**: 计算和分析部分完成度高，但自动化挖掘系统(4引擎+Gate+知识库)完全未启动。

3. **AI闭环**: 几乎完全未实现(94%未实现)。这是Phase 1的核心工作，当前仅有底层执行模块可复用。

**建议优先级**:
- P0: 补齐MarketRegimeConfig(牛熊震荡分段), 实际vs理论仓位偏差指标
- P1: 因子生命周期自动状态转移, Gate Pipeline
- P2: AI闭环系统(Phase 1正式启动时)
