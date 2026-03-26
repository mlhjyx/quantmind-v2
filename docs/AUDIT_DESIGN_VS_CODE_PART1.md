# 设计文档 vs 代码实现 审计报告 (Part 1)

> **审计日期**: 2026-03-26
> **审计范围**: QUANTMIND_V2_DESIGN_V5.md (主设计文档) + DEV_BACKEND.md (后端开发文档)
> **方法**: 逐章读设计文档 → grep/glob代码验证 → 标注实现状态

**图例**: ✅已实现 | ⚠️部分实现 | ❌未实现 | 🔲Phase 2+ (设计阶段未开始)

---

## 文档1: QUANTMIND_V2_DESIGN_V5.md

### 第一章: 战略决策总览

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §1.1 25项核心决策记录 | ✅ | CLAUDE.md技术决策快查表有60+条决策记录 |
| §1.2 14个AI动态参数 | ⚠️ | ai_parameters表DDL存在; ParamService实现了读写(app/services/param_service.py); 但AI自动调整逻辑未实现(Phase 1) |

### 第三章: 系统总体架构

| 功能点 | 状态 | 代码位置 |
|--------|------|----------|
| §3.1 FastAPI入口 | ✅ | backend/app/main.py |
| §3.1 CORS中间件 | ✅ | backend/app/main.py:34-40 |
| §3.1 Lifespan(启动/关闭) | ✅ | backend/app/main.py:21-24 |
| §3.2 pydantic-settings配置 | ✅ | backend/app/config.py (Settings类) |
| §3.2 PostgreSQL+asyncpg | ✅ | backend/app/db.py (SQLAlchemy async engine) |
| §3.2 Redis | ✅ | config.py有REDIS_URL, celery_app.py使用 |
| §3.2 Celery+Redis | ✅ | backend/app/tasks/celery_app.py |
| §3.2 Celery Beat调度 | ✅ | backend/app/tasks/beat_schedule.py (3个任务) |
| §3.2 React 18前端 | ⚠️ | frontend/存在, 但仅1个页面(Dashboard.tsx) |
| §3.2 Rust回测引擎 | ❌ | 无rust_engine/目录, 回测用纯Python(engines/backtest_engine.py) |
| §3.2 LightGBM+Optuna | ✅ | backend/engines/ml_engine.py |
| §3.2 DeepSeek/Claude LLM | ⚠️ | config.py有DEEPSEEK_API_KEY, 但无integrations/deepseek_client.py或anthropic_client.py |
| §3.2 miniQMT执行 | ✅ | backend/engines/broker_qmt.py (MiniQMTBroker类) |
| §3.2 MT5 Adapter | ❌ | 无mt5_adapter/目录 (Phase 2) |
| §3.2 WebSocket通道 | ❌ | 无websocket/目录, backtest.py中有一处import但无WS路由 |
| §3.2 loguru日志 | ❌ | 代码使用标准logging模块, 非loguru |
| §3.4 Router→Service→Repo分层 | ✅ | 严格分层: app/api/ → app/services/ → app/repositories/ |
| §3.5 start_all.sh启动脚本 | ❌ | 无scripts/start_all.sh (Windows用Task Scheduler) |
| §3.5 tmux多窗格 | ❌ | Windows环境, 不适用 |

### 第四章: A股因子体系

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §4.2 34个核心因子定义 | ⚠️ | engines/factor_engine.py实现了~20个因子函数(价量+流动性+基本面); financial_factors.py实现3个财务因子; 缺少: north_flow相关、margin相关、chip_distribution相关 |
| §4.2 类别①价量技术(12个) | ⚠️ | 实现: reversal/momentum/volatility/volume_price_corr/KMID等; 缺少: idio_vol_20(FF3残差), max_ret_20, KSFT, CNTP_20, RSV_20 |
| §4.2 类别②流动性(6个) | ✅ | turnover_mean/std/amihud/volume_ratio/amount_std/zscore均有对应实现 |
| §4.2 类别③资金流向(6个) | ⚠️ | mf_momentum_divergence已实现(scripts中); 缺少: north_flow_net_20, big_order_ratio, margin_balance_chg, short_ratio, winner_rate |
| §4.2 类别④基本面价值(8个) | ⚠️ | bp_ratio, ep_ratio已实现; financial_factors.py有roe_change/revenue_accel/accrual; 缺少: div_yield因子函数, roe_ttm, gross_margin, roa_ttm, debt_to_asset, current_ratio |
| §4.2 ln_float_cap规模因子 | ✅ | factor_engine.py:76 calc_ln_mcap() |
| §4.2 sw_industry_1行业 | ✅ | data_fetcher/industry_merge_map.json + 中性化回归用行业哑变量 |
| §4.4 预处理顺序(MAD→fill→中性化→zscore) | ✅ | factor_engine.py文件头注释明确标注; 代码中有preprocess_factors实现 |
| §4.5 因子衰减L1/L2/L3 | ⚠️ | factor_analyzer.py有IC监控; scripts/factor_health_daily.py实现健康检查; 但自动降权/退出逻辑未在production pipeline中实现 |
| §4.6 因子择时权重调整 | ❌ | 当前锁定等权, 无因子择时逻辑 (Phase 1) |
| §4.7 GP遗传编程搜索空间 | ❌ | 无engines/gp_engine.py (Phase 1) |

### 第五章: Universe构建

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §5.1 8层过滤规则 | ⚠️ | signal_engine.py处理了涨跌停/停牌/ST; 但无独立的universe_daily表写入逻辑, 过滤内嵌在信号生成中 |
| §5.2 AI动态门槛 | ❌ | 当前硬编码, 无AI动态调整 (Phase 1) |
| §5.3 三种涨跌停规则 | ✅ | backtest_engine.py:118-166 can_trade()区分主板/创业板/科创板 |
| §5.4 防前视偏差(PIT) | ✅ | financial_factors.py用actual_ann_date做PIT; 因子用T日及之前数据 |
| §5.5 已持仓保护 | ✅ | signal_engine.py中调仓逻辑保留现有持仓 |

### 第六章: 组合构建逻辑

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §6.1 7步链路 | ⚠️ | 等权Top-N + 行业约束 + 换手控制 + 整手处理已实现; IC加权/HRP/MVO未实现 |
| §6.2 Alpha Score等权合成 | ✅ | signal_engine.py: 等权zscore求和 |
| §6.2 IC加权/LightGBM合成 | ⚠️ | ml_engine.py可生成ML预测; IC加权方案在技术决策表中已Reverted |
| §6.3 排名选股Top-N | ✅ | signal_engine.py, PAPER_TRADING_CONFIG: top_n=15 |
| §6.4 等权1/N | ✅ | signal_engine.py: weight_method="equal" |
| §6.5 行业约束25% | ✅ | signal_engine.py: industry_cap=0.25 |
| §6.5 单股权重上限 | ⚠️ | 等权下自然满足(1/15=6.7%), 但无显式单股weight cap检查 |
| §6.6 换手率控制50% | ✅ | signal_engine.py: turnover_cap=0.50 |
| §6.7 整手处理(100股) | ✅ | backtest_engine.py: lot_size=100, floor取整 |
| §6.8 执行顺序(先卖后买) | ✅ | backtest_engine.py中先执行sells再buys |

### 第七章: AI智能层

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §7.1 L1/L2/L3分层授权 | ⚠️ | ai_parameters DDL有authorization_level字段; RiskControlService有L4审批流; 完整分层授权框架未实现 |
| §7.2 模块化替换 | ❌ | 当前全部用规则版 (Phase 1) |
| §7.3 层级Fallback | ❌ | 无AI→规则→清仓的fallback链 (Phase 1) |
| §7.4 模型训练触发 | ⚠️ | ml_engine.py有Walk-Forward训练框架; 但无自动触发逻辑 |
| §7.5 LLM三Agent挖掘 | ❌ | 无mining_service.py, 无Idea/Factor/Eval Agent (Phase 1) |
| §7.5.4 GP遗传编程引擎 | ❌ | 无gp_engine.py (Phase 1) |
| §7.5.5 UCB1搜索方向调度 | ❌ | (Phase 1) |
| §7.5.6 mining_knowledge表 | ✅ | DDL中有CREATE TABLE mining_knowledge |
| §7.6 参数可配置体系 | ⚠️ | ParamService + ParamRepository + API endpoints已实现; 前端参数面板未实现 |

### 第八章: 风控体系

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §8.1 硬规则(单股15%/行业35%) | ⚠️ | 行业25%已实现; 硬上限检查在等权模式下隐式满足, 无显式硬上限guard |
| §8.1 熔断L1-L4 | ✅ | app/services/risk_control_service.py: CircuitBreakerLevel枚举, 完整状态机 |
| §8.1 L1单策略日亏>3% | ✅ | risk_control_service.py |
| §8.1 L2总组合日亏>5% | ✅ | risk_control_service.py |
| §8.1 L3月亏>10%降仓 | ✅ | risk_control_service.py |
| §8.1 L4累计>25%停止 | ✅ | risk_control_service.py + L4审批API |
| §8.2 外汇风控5项 | 🔲 | Phase 2 未开始 |
| §8.3 跨市场风控 | 🔲 | Phase 2 未开始 |

### 第九章: 数据层(DataHub)

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §9.1 Tushare Pro数据拉取 | ✅ | data_fetcher/tushare_fetcher.py + tushare_client.py |
| §9.1 AKShare补充源 | ❌ | 无integrations/akshare_client.py |
| §9.2 Data Contract YAML | ❌ | 无YAML契约文件, 但docs/TUSHARE_DATA_SOURCE_CHECKLIST.md作为替代 |
| §9.3 幂等写入(UPSERT) | ✅ | tushare_fetcher.py使用INSERT ON CONFLICT |
| §9.3 PIT时间对齐 | ✅ | financial_factors.py用actual_ann_date |
| §9.4 不复权+adj_factor存储 | ✅ | tushare_fetcher.py明确注释: 存原始价格+adj_factor |
| §9.5 指数基准数据 | ✅ | DDL有index_daily表; tushare_fetcher有index_daily拉取 |
| §9.6 交易日历 | ✅ | DDL有trading_calendar表 |

### 第十章: 数据库Schema

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §10 DDL 43张表(设计说41+新增) | ✅ | DDL_FINAL.sql有43个CREATE TABLE语句 |
| 域1 基础数据(5表) | ✅ | symbols, klines_daily, forex_bars, daily_basic, trading_calendar |
| 域2 另类数据(5表) | ✅ | moneyflow_daily, northbound_holdings, margin_data, chip_distribution, financial_indicators |
| 域3 因子(3表) | ✅ | factor_registry, factor_values, factor_ic_history |
| 域4 Universe与信号(3表) | ✅ | universe_daily, signals, index_daily |
| 域5 交易执行(3表) | ✅ | trade_log, position_snapshot, performance_series |
| 域6 AI模型(3表) | ✅ | model_registry, ai_parameters, experiments |
| 域7 系统运维(4表) | ✅ | 包括strategy_configs, notifications, health_checks, scheduler_task_log |
| 域8 外汇(2表) | ✅ | forex_swap_rates, forex_events (DDL存在, Phase 2使用) |
| 域9 回测(6表) | ✅ | strategy, backtest_run, backtest_daily_nav, backtest_trades, backtest_holdings, backtest_wf_windows |
| 域10 因子挖掘(3表) | ✅ | factor_evaluation, factor_mining_task, mining_knowledge |
| 域11 AI闭环(3表) | ✅ | pipeline_run, agent_decision_log, approval_queue |
| 额外: param_change_log | ✅ | DDL中有CREATE TABLE param_change_log |
| ORM模型映射 | ❌ | backend/app/models/__init__.py为空, 无SQLAlchemy ORM模型定义; 代码直接用raw SQL |

### 第十一章: 回测层

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §11.1 Hybrid架构(向量化+事件驱动) | ⚠️ | Python实现完成(engines/backtest_engine.py), 但无Rust向量化层 |
| §11.2 次日开盘价成交 | ✅ | backtest_engine.py:177 price=row["open"] |
| §11.2 Volume-impact滑点 | ✅ | engines/slippage_model.py (独立双因素模型) |
| §11.2 交易成本(佣金+印花税+过户费) | ✅ | BacktestConfig: commission_rate/stamp_tax_rate/transfer_fee_rate |
| §11.2 涨跌停判断(三级fallback) | ✅ | SimBroker.can_trade(): up_limit数据优先→board推算 |
| §11.2 Walk-Forward | ✅ | engines/walk_forward.py (WFConfig, 5折时序分割) |
| §11.4 回测前端5页面 | ❌ | 仅Dashboard.tsx, 无策略工作台/回测配置/运行监控/结果分析/策略库 |

### 第十二章: 执行层

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §12.1 SimBroker(回测) | ✅ | engines/backtest_engine.py: SimBroker类 |
| §12.1 PaperBroker(Paper Trading) | ✅ | engines/paper_broker.py: PaperBroker类 |
| §12.1 MiniQMTBroker(实盘) | ✅ | engines/broker_qmt.py: MiniQMTBroker类 |
| §12.1 策略模式切换 | ⚠️ | 三种Broker并行存在, 但无统一BaseBroker抽象基类和工厂函数get_broker() |
| §12.2 Paper Trading验证逻辑 | ✅ | app/services/paper_trading_service.py: 毕业标准评估 |
| §12.3 MT5外汇执行 | 🔲 | Phase 2 |

### 第十三章: 验证层

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §13 DSR(Deflated Sharpe Ratio) | ✅ | engines/dsr.py + tests/test_dsr.py |
| §13 PBO(过拟合概率) | ✅ | engines/pbo.py + tests/test_pbo.py |
| §13 因子Gate(IC/单调性等) | ✅ | config_guard.py (BH-FDR校正) + factor_analyzer.py |
| §13 确定性测试 | ✅ | tests/test_factor_determinism.py |
| §13 Walk-Forward | ✅ | engines/walk_forward.py |
| §13 CI门禁(确定性) | ⚠️ | 有测试文件, 但未见CI配置(无.github/workflows或类似) |

### 第十四章: 归因分析

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §14 Brinson-Fachler归因 | ✅ | engines/attribution.py: BrinsonAttribution类 + tests/test_attribution.py |
| §14 市场状态分段(牛/熊/震荡) | ✅ | engines/attribution.py中包含MarketStateDetector |

### 第十五章: 前端层

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §15.1 React 18 + Tailwind | ✅ | frontend/package.json + vite.config.ts |
| §15.2 12个页面(设计说11) | ❌ | 仅实现1个: Dashboard.tsx |
| 策略工作台 | ❌ | |
| 回测配置面板 | ❌ | |
| 回测运行监控 | ❌ | |
| 回测结果分析 | ❌ | |
| 策略库 | ❌ | |
| 因子实验室 | ❌ | |
| 挖掘任务中心 | ❌ | |
| 因子评估报告 | ❌ | |
| 因子库 | ❌ | |
| Pipeline控制台 | ❌ | |
| Agent配置 | ❌ | |

### 第十六章: 外汇 → 🔲 Phase 2 未开始

### 第十七章: AI进化闭环

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §17.1 4个Agent | ❌ | Phase 1 |
| §17.2 4级自动化 | ❌ | Phase 1 |
| §17.3 完整闭环流程 | ❌ | Phase 1 |
| §17.4 agent_decision_log审计 | ✅ | DDL表已建 |

### 第十八~二十二章: [待讨论] → 部分实现

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §18 每日调度时序 | ✅ | beat_schedule.py: 16:25预检/16:30信号/09:00执行 |
| §18 健康预检 | ✅ | daily_pipeline.py: _async_health_check() |
| §19 通知P0/P1/P2分级 | ✅ | notification_service.py + notification_templates.py |
| §19 钉钉Webhook | ✅ | services/dispatchers/dingtalk.py |
| §19 防洪泛(throttler) | ✅ | notification_throttler.py |
| §20 策略配置版本化 | ✅ | strategy_configs表 + StrategyService |
| §20 param_change_log | ✅ | DDL + ParamService |
| §21 miniQMT对接 | ✅ | engines/broker_qmt.py |
| §22 高级特性(GP/GNN等) | ❌ | Phase 1+ |

### 第二十三章: MVP定义

| MVP要求 | 状态 | 说明 |
|---------|------|------|
| PostgreSQL+TimescaleDB+43表 | ✅ | DDL完整 |
| Tushare全量数据 | ✅ | tushare_fetcher.py |
| 指数基准 | ✅ | index_daily表+拉取逻辑 |
| 交易日历 | ✅ | trading_calendar表 |
| 复权处理 | ✅ | 不复权+adj_factor |
| 34个因子 | ⚠️ | 约20个已实现, 14个缺失(主要是资金流/北向/融资融券/部分基本面) |
| 因子Gate Pipeline | ⚠️ | config_guard.py有BH-FDR; factor_analyzer.py有IC分析; 但无完整8项Gate自动管道 |
| Rust回测引擎 | ❌ | 用Python替代, 性能足够 |
| 等权Top-N组合 | ✅ | signal_engine.py: PAPER_TRADING_CONFIG |
| Paper Trading | ✅ | paper_broker.py + run_paper_trading.py + daily_pipeline.py |
| 钉钉通知 | ✅ | 完整实现 |
| FastAPI后端 | ✅ | 完整REST API |
| React前端12页面 | ❌ | 仅1页面 |
| Celery调度15任务 | ⚠️ | 3个任务(预检/信号/执行), 非设计的15个 |
| 确定性测试 | ✅ | test_factor_determinism.py |

---

## 文档2: DEV_BACKEND.md

### 一、项目目录结构

| 设计目录 | 状态 | 实际情况 |
|---------|------|----------|
| backend/main.py | ✅ | 实际路径: backend/app/main.py (多了app层) |
| backend/config.py | ✅ | backend/app/config.py |
| backend/database.py | ✅ | 实际叫backend/app/db.py |
| routers/(10个文件) | ⚠️ | 实际8个: backtest/dashboard/health/notifications/paper_trading/params/risk/strategies; 缺少: factors/mining/pipeline/forex/settings/websocket |
| services/(17个Service) | ⚠️ | 实际6个: DashboardService/NotificationService/PaperTradingService/ParamService/RiskControlService/StrategyService; 缺少: DataService/FactorService/SignalService/BacktestService/PortfolioService/MiningService/PipelineService/ForexSignalService/ForexBrokerService/ForexRiskService/LLMService |
| repositories/(9个Repo) | ✅ | 实际11个: Base/Factor/Health/MarketData/Param/Performance/Position/Risk/Signal/Strategy/Trade |
| schemas/(8个) | ❌ | 无独立schemas目录, Pydantic模型内联在API文件中(backtest.py有) |
| models/(7个ORM文件) | ❌ | models/__init__.py为空, 无ORM模型; 代码用raw SQL |
| tasks/(6个文件) | ⚠️ | 实际3个: celery_app/beat_schedule/daily_pipeline; 缺少: astock_tasks/forex_tasks/ai_tasks/system_tasks/task_utils |
| engines/(9个文件) | ✅ | 实际15个: attribution/backtest_engine/beta_hedge/broker_qmt/config_guard/dsr/factor_analyzer/factor_engine/financial_factors/metrics/ml_engine/paper_broker/pbo/signal_engine/slippage_model/walk_forward |
| integrations/(7个文件) | ❌ | 无独立integrations/目录; tushare在data_fetcher/; 钉钉在services/dispatchers/; 缺少: akshare/mt5/deepseek/anthropic/miniqmt独立客户端 |
| websocket/(6个文件) | ❌ | 无websocket/目录 |
| utils/(4个文件) | ❌ | 无独立utils/目录; 部分工具散布在services/price_utils.py等 |
| alembic/ | ❌ | 无数据库迁移目录 |
| tests/ | ✅ | backend/tests/有25个测试文件 |
| wrappers/ | ✅ | backend/wrappers/: quantstats_wrapper.py + ta_wrapper.py |

### 二、FastAPI应用结构

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §2.1 路由注册(10个模块) | ⚠️ | 实际注册8个: health/backtest/dashboard/notifications/paper_trading/params/risk/strategies |
| §2.2 config.py完整配置 | ⚠️ | 有核心配置; 缺少: DATABASE_POOL_SIZE/CELERY_BROKER独立/AKSHARE_ENABLED/MT5_ADAPTER_URL/FOREX_ENABLED/LOG_FILE |
| §2.3 database.py | ✅ | db.py实现, 含get_db()和get_async_session() |

### 三、服务层分层架构

| 功能点 | 状态 | 说明 |
|--------|------|------|
| §3.1 Router不含业务逻辑 | ✅ | API文件只做参数验证+调用Service |
| §3.1 Service调用Repo | ✅ | Service通过Repository读写数据 |
| §3.1 Engine纯计算无IO | ⚠️ | 大部分遵守, 但financial_factors.py/factor_analyzer.py直接做DB读取 |
| §3.1 Integration封装外部API | ⚠️ | tushare_fetcher有, 但缺少统一的integrations/层 |

### 四、端到端数据流

| 数据流步骤 | 状态 | 说明 |
|-----------|------|------|
| §4.1 T1数据拉取 | ✅ | tushare_fetcher.py + scripts/calc_factors.py |
| §4.1 T2数据质量检查 | ✅ | scripts/data_quality_check.py |
| §4.1 T3 Universe构建 | ⚠️ | 内嵌在信号生成中, 无独立universe_daily写入步骤 |
| §4.1 T4因子计算 | ✅ | factor_engine.py + scripts/calc_factors.py |
| §4.1 T6 ML预测 | ⚠️ | ml_engine.py存在, 但未集成到daily pipeline |
| §4.1 T7信号生成 | ✅ | daily_pipeline.py → signal task |
| §4.1 T8调仓决策 | ✅ | daily_pipeline.py → execute task |
| §4.1 T10交易执行 | ✅ | paper_broker.py(Paper) / broker_qmt.py(实盘) |
| §4.1 T13盘后更新 | ✅ | run_paper_trading.py写position_snapshot/performance_series |
| §4.1 T14-15绩效日报 | ✅ | notification_service发钉钉 |
| §4.2 外汇数据流 | 🔲 | Phase 2 |

---

## 汇总统计

| 类别 | ✅已实现 | ⚠️部分实现 | ❌未实现 | 🔲Phase 2+ |
|------|---------|-----------|---------|-----------|
| 第三章 系统架构 | 10 | 2 | 5 | 0 |
| 第四章 因子体系 | 4 | 4 | 2 | 0 |
| 第五章 Universe | 3 | 1 | 1 | 0 |
| 第六章 组合构建 | 7 | 2 | 0 | 0 |
| 第七章 AI智能层 | 1 | 2 | 5 | 0 |
| 第八章 风控 | 5 | 1 | 0 | 2 |
| 第九章 数据层 | 4 | 0 | 2 | 0 |
| 第十章 DB Schema | 12 | 0 | 1 | 0 |
| 第十一~十四章 回测/执行/验证/归因 | 14 | 3 | 1 | 1 |
| 第十五章 前端 | 1 | 0 | 11 | 0 |
| 第十七章 AI闭环 | 1 | 0 | 3 | 0 |
| 第十八~二十二章 调度/通知/配置 | 7 | 0 | 1 | 0 |
| DEV_BACKEND目录结构 | 5 | 4 | 6 | 0 |
| DEV_BACKEND服务层 | 4 | 2 | 0 | 0 |
| DEV_BACKEND数据流 | 7 | 2 | 0 | 1 |
| **合计** | **85** | **23** | **38** | **4** |

---

## 关键发现

### 核心能力已就绪 (Phase 0 生产可用)
1. **回测引擎**: SimBroker完整(涨跌停/整手/T+1) + 绩效指标 + 归因分析 + Walk-Forward + DSR/PBO
2. **Paper Trading**: PaperBroker + daily pipeline(预检/信号/执行) + 钉钉通知 + 毕业标准评估
3. **因子引擎**: 核心5因子(v1.1配置) + 预处理管道 + 中性化 + BH-FDR校正
4. **风控**: 4级熔断状态机完整(L1-L4) + API + 审批流
5. **数据管道**: Tushare拉取 + 复权处理 + 指数基准
6. **DB Schema**: 43张表DDL完整
7. **API层**: 8个路由模块 + 50+端点 + 分层架构

### 主要Gap (设计有但未实现)
1. **前端**: 设计12页面, 仅实现Dashboard (最大的gap)
2. **因子覆盖**: 设计34个, 实现约20个(缺资金流/北向/融资融券类)
3. **架构偏差**: 无ORM模型(raw SQL替代)、无schemas目录、无integrations统一层、无WebSocket
4. **AI模块**: LLM Agent/GP/暴力枚举/Pipeline全未实现 (Phase 1计划内)
5. **Rust引擎**: 设计为Hybrid(Rust+Python), 实际纯Python (性能足够故未迁移)
6. **AKShare备用源**: 未实现(单一Tushare数据源)

### 架构偏差 (实际 vs 设计)
1. **路径**: 设计`backend/main.py`, 实际`backend/app/main.py` (多一层app)
2. **ORM**: 设计用SQLAlchemy ORM映射51张表, 实际用raw SQL + BaseRepository
3. **数据库文件**: 设计叫`database.py`, 实际叫`db.py`
4. **日志**: 设计用loguru, 实际用标准logging
5. **Engine层**: 设计说纯计算无IO, 实际有些engine直接读DB(financial_factors.py, factor_analyzer.py)
6. **Celery任务**: 设计15+任务链, 实际3个(精简够用)
7. **环境**: 设计基于Mac, 实际已迁移到Windows 11 (Task Scheduler替代crontab)
