# QuantMind V2 — 完整开发蓝图 (Development Blueprint)

> **生成日期**: 2026-03-27
> **基于**: 11个设计文档(400KB+) + 3份审计报告 + 代码扫描(235文件/80K行)
> **目的**: 梳理全项目功能协同、底层运行机制、多策略架构、完整开发路线
>
> **实施计划**: 本文档的44项缺失 + R1-R7的73项新增 = 117项，已整合入 **`IMPLEMENTATION_MASTER.md`** v2.0（10 Sprint / 5轨道），作为唯一操作文档。

---

## 一、项目全景：设计 vs 现状

### 1.1 总体完成度

| 模块 | 设计功能 | ✅完成 | ⚠️部分 | ❌缺失 | 完成度 |
|------|---------|--------|--------|--------|--------|
| A. 数据管道 | 9 | 7 | 0 | 2 | 78% |
| B. 因子引擎 | 17 | 10 | 2 | 5 | 65% |
| C. 信号/组合 | 8 | 5 | 1 | 2 | 69% |
| D. 回测引擎 | 18 | 14 | 2 | 2 | 83% |
| E. 风控 | 9 | 7 | 0 | 0 | 100%(Phase0) |
| F. 执行层 | 8 | 7 | 0 | 0 | 100%(Phase0) |
| G. 调度运维 | 9 | 4 | 0 | 5 | 44% |
| H. 通知告警 | 9 | 4 | 3 | 2 | 61% |
| I. 参数系统 | 9 | 5 | 1 | 3 | 61% |
| J. 前端 | 15 | 2 | 0 | 13 | 13% |
| K. AI/ML | 11 | 2 | 0 | 9 | 18% |
| **总计** | **135** | **79** | **9** | **44** | **62%** |

### 1.2 代码规模

| 层 | 文件数 | 代码行 |
|---|--------|--------|
| backend/app/ (服务/API/仓库/任务) | 51 | 11,692 |
| backend/engines/ (计算引擎) | 29 | 11,599 |
| backend/tests/ | 42 | 13,071 (718个测试函数) |
| scripts/ (研究/运维/数据) | 99 | 42,790 |
| frontend/src/ | 11 | 683 |
| **总计** | **235** | **~80,135** |

---

## 二、系统架构：底层运行机制

### 2.1 六层架构

```
┌─────────────────────────────────────────────────────┐
│  Layer 1: 前端展现层 (React 18 + TypeScript)        │
│  12页面 + 57 API + 5 WebSocket                     │
│  当前: 1/12页面(Dashboard), 0 WebSocket            │
└─────────────────────┬───────────────────────────────┘
                      │ HTTP/WS
┌─────────────────────▼───────────────────────────────┐
│  Layer 2: API网关层 (FastAPI)                       │
│  8个Router组: health/dashboard/backtest/            │
│  notifications/paper_trading/params/risk/strategies │
│  当前: 8个Router已实现, ~30个端点                    │
└──────┬──────────────┬───────────────────────────────┘
       │              │
┌──────▼──────┐ ┌─────▼──────────────────────────────┐
│ Layer 3:    │ │ Layer 3b: 异步任务层 (Celery)       │
│ 服务层(8个) │ │ 3个定时任务(Beat) + 4个Worker       │
│ 业务逻辑    │ │ 8个队列(设计) → 当前1个default      │
└──────┬──────┘ └─────┬──────────────────────────────┘
       │              │
┌──────▼──────────────▼───────────────────────────────┐
│  Layer 4: 计算引擎层 (29个纯计算模块)                │
│  factor_engine / signal_engine / backtest_engine    │
│  slippage_model / metrics / walk_forward / ml_engine│
│  attribution / regime_detector / vol_regime         │
│  ★ 无IO依赖, 纯DataFrame输入输出, 可独立测试       │
└──────┬──────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│  Layer 5: 数据持久层                                │
│  PostgreSQL 16 + TimescaleDB (43表)                │
│  Redis (Celery Broker + 缓存)                      │
│  11个Repository (SQL封装)                          │
└──────┬──────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────┐
│  Layer 6: 外部集成层                                │
│  Tushare Pro / AKShare(备用) / miniQMT / MT5(Phase2)│
│  DeepSeek API(Phase1) / 钉钉Webhook               │
└─────────────────────────────────────────────────────┘
```

### 2.2 数据流全景（端到端）

```
[外部数据源]
Tushare API ──→ tushare_fetcher.py ──→ klines_daily / daily_basic
                                        / fina_indicator / moneyflow_daily
                                                │
                                                ▼
[因子计算] factor_engine.py (31个calc_*函数)
           │
           ▼
[预处理] MAD → 缺失值填充 → 中性化(市值+行业) → zscore
           │
           ▼
[因子存储] factor_values表 (TimescaleDB, 1.38亿行)
           │
           ├──→ [因子分析] factor_analyzer.py → factor_ic_history
           │
           ├──→ [信号合成] signal_engine.py
           │      等权zscore求和 → Top-15 → 行业25%上限
           │      → 换手50%上限 → 整手约束 → target_holdings
           │                                    │
           │                                    ▼
           │    [风控检查] risk_control_service.py
           │      L1-L4熔断 + PreTradeValidator 5项
           │                                    │
           │                                    ▼
           │    [执行] BaseBroker (SimBroker / PaperBroker / MiniQMTBroker)
           │                                    │
           │                                    ▼
           │    [记录] trade_log / position_snapshot / performance_series
           │
           └──→ [ML] ml_engine.py (LightGBM + Walk-Forward)
```

### 2.3 调度时序（A股日常链路）

```
T日 16:00  ┌─ T0 健康预检(PG/Redis/数据/磁盘/Celery) ─ 失败→P0暂停
     16:30 ├─ T1 数据更新(Tushare) ─ 超时30min
     17:00 ├─ T2 数据质量检查(>3000股/无NULL/价格合理)
     17:05 ├─ T3 Universe构建(8层过滤)
     17:10 ├─ T4 因子计算(5因子×Universe)
     17:25 ├─ T5 因子体检(周一, 近60日IC/IR)
     17:35 ├─ T6 ML预测(LightGBM, 如启用)
     17:40 ├─ T7 信号生成(等权→Top-15+风控)
     17:45 ├─ T8 调仓决策(存库)
     17:50 └─ T9 通知推送(含明日调仓明细)

T+1 08:30  ┌─ T10 读取调仓指令→确认
     09:25 ├─ 盘前跳空预检
     09:30 ├─ T11 开盘执行
     15:00 ├─ T13 收盘确认(成交/滑点)
     15:30 └─ T14 绩效计算

每日 16:30  L1-L4风控日终评估(非仅调仓日)
每周日 22:00  AI闭环Pipeline
每周日 03:00  数据库维护(VACUUM/备份)
```

### 2.4 服务协同矩阵

```
调用方 ↓  被调方→    Data  Factor Signal Bt  Port Risk Mining Pipe Notif LLM  ML
DataService          -     -      -     -   -    -    -      -    call  -    -
FactorService       call   -      -     -   -    -    -      -    call  -    -
SignalService        -    call     -     -   -   call  -      -     -    -   call
BacktestService      -     -      -     -   -    -    -      -    call  -    -
PortfolioService     -     -     call    -   -   call  -      -    call  -    -
RiskService          -     -      -     -   -    -    -      -     -    -    -
MiningService        -    call    -     -   -    -    -      -    call call   -
PipelineService      -    call   call  call  -   -   call    -    call call  call
```

**关键特征**：
- RiskService是纯验证（不调用任何服务）→ 安全隔离正确
- NotificationService是万能接收器（被所有服务调用）
- PipelineService扇出最大（调用7个服务）→ 最后实现，集成测试最重

---

## 三、多策略框架设计（新架构）

### 3.1 问题诊断

当前v1.1用单一策略（等权Top-15月度）验证所有因子：
- RSRS(事件型, t=-4.35) → 月度等权 → Sharpe=0.15 **失败**
- VWAP(趋势型) → 月度等权 → 无增量
- 9种线性合成 → 全部劣于等权

**根因**: 不同因子有不同的信号特征（频率/持续性/触发方式），用同一策略框架测试是方法论错误。

### 3.2 因子-策略匹配矩阵

| 因子类型 | 代表因子 | 信号特征 | 适配策略类型 | 调仓频率 | 选股方式 |
|---------|---------|---------|-------------|---------|---------|
| 排序型(截面) | turnover/vol/amihud/bp | 截面排名稳定 | 等权Top-N | 月度 | 综合排名 |
| 事件型(时序) | RSRS/PEAD | 阈值突破 | 事件触发+信号强度 | 事件驱动 | 突破即入 |
| 动量型(趋势) | VWAP/momentum | 趋势跟随 | 趋势策略+止盈止损 | 周度/日度 | 动态持有 |
| 价值型(低频) | bp_ratio/div_yield | 低频轮动 | 价值轮动 | 季度 | 估值分位 |
| 资金流型 | mf_divergence/north_flow | 资金异动 | 异动跟踪 | 周度 | 异动确认 |

### 3.3 多策略引擎架构

```
┌─────────────────────────────────────────────────────┐
│  策略组合管理器 (StrategyPortfolioManager)           │
│  负责: 策略间资金分配 / 风险预算 / 总仓位控制       │
│                                                     │
│  v1.1等权策略(60%)  事件策略(20%)  动量策略(20%)    │
└──────┬──────────────────┬──────────────┬────────────┘
       │                  │              │
┌──────▼──────┐  ┌────────▼───────┐  ┌──▼─────────────┐
│ BaseStrategy │  │ BaseStrategy   │  │ BaseStrategy   │
│ (已有ABC)    │  │ EventStrategy  │  │ TrendStrategy  │
│              │  │                │  │                │
│ EqualWeight  │  │ ·阈值触发     │  │ ·趋势跟随     │
│ Strategy     │  │ ·信号强度加权  │  │ ·动态止盈止损  │
│              │  │ ·持有至衰减    │  │ ·周度轮动     │
│ ·月度调仓    │  │ ·事件驱动调仓  │  │               │
│ ·等权Top-N   │  │               │  │               │
│ ·行业约束    │  │               │  │               │
└──────────────┘  └───────────────┘  └───────────────┘
       │                  │              │
       └──────────────────┼──────────────┘
                          ▼
              ┌───────────────────────┐
              │ 统一执行层            │
              │ RiskService → Broker  │
              │ trade_log汇总        │
              └───────────────────────┘
```

### 3.4 BaseStrategy已有接口（可复用）

```python
# backend/engines/base_strategy.py:101 — 已实现
class BaseStrategy(ABC):
    @abstractmethod
    def compute_alpha(self, data: dict, date: date) -> pd.Series: ...

    @abstractmethod
    def filter_universe(self, universe: list[str], data: dict, date: date) -> list[str]: ...

    def on_rebalance(self, date: date, holdings: dict, signals: pd.Series) -> dict: ...

# backend/engines/strategy_registry.py:14 — 已实现
class StrategyRegistry:
    def register(self, name: str, strategy_cls: type[BaseStrategy]): ...
    def get(self, name: str) -> BaseStrategy: ...
```

**需要扩展**:
1. `BaseStrategy`增加`get_rebalance_dates()`方法（让策略自定义调仓频率）
2. `BaseStrategy`增加`get_position_sizing()`方法（让策略自定义仓位方式）
3. 新增`StrategyPortfolioManager`类（管理多策略间资金分配）
4. `SignalConfig`增加`strategy_type`字段

### 3.5 实现路径

```
Phase A (当前): 架构基础
  ├─ 扩展BaseStrategy接口(+调仓频率/+仓位方式)
  ├─ 实现StrategyPortfolioManager
  ├─ 实现EventStrategy(RSRS用)
  └─ 回测验证: RSRS事件策略 vs RSRS月度等权

Phase B: 策略丰富
  ├─ 实现TrendStrategy(VWAP/momentum用)
  ├─ 实现ValueStrategy(bp_ratio/div_yield用)
  ├─ 实现FlowStrategy(mf_divergence/north_flow用)
  └─ 每种策略独立回测验证

Phase C: 组合优化
  ├─ 策略间资金分配优化(等权/风险预算/HRP)
  ├─ 跨策略风控(总仓位/相关性/换手预算)
  └─ 统一报告(策略归因+组合归因)
```

---

## 四、14个AI动态参数（Phase 1核心）

| # | 参数 | 搜索范围 | 默认值(规则) | 授权 | 模块 |
|---|------|---------|------------|------|------|
| 1 | 跨市场资金分配 | A股50-90%/外汇10-50% | A70%/F30% | L2 | PortfolioService |
| 2 | Universe市值门槛 | 5亿-50亿 | 20亿 | L1 | UniverseFilter |
| 3 | Universe日均金额门槛 | 200万-2000万 | 500万 | L1 | UniverseFilter |
| 4 | Universe停牌天数 | 3-30天 | 10天 | L1 | UniverseFilter |
| 5 | 因子中性化方法 | 按因子决定 | 市值+行业 | L1 | FactorPreprocessor |
| 6 | 因子权重/择时 | [0.5x, 1.5x] | 等权1.0 | L1 | SignalComposer |
| 7 | Alpha合成方法 | {等权/IC/LightGBM} | 等权 | L2 | SignalComposer |
| 8 | 持仓数量N | 10-50 | 15 | L1 | PortfolioBuilder |
| 9 | 权重方式 | {等权/alpha/HRP} | 等权 | L2 | PortfolioBuilder |
| 10 | 单股权重上限 | 3%-15% | 8% | L1 | PortfolioBuilder |
| 11 | 行业权重上限 | 10%-35% | 25% | L1 | PortfolioBuilder |
| 12 | 换手率上限 | 10%-80% | 50% | L1 | PortfolioService |
| 13 | 总仓位比例 | 0%-100% | 规则决定 | L1/L2 | RiskService |
| 14 | 调仓频率 | {周/双周/月}+事件 | 月度 | L2 | RebalanceCalendar |

**AI授权三级制**:
- L1(自主): AI直接调参, 下次信号生效, 事后记录
- L2(简报): AI建议→快速回测验证→人工审批→生效
- L3(双重): AI+人工双重确认(仅风控相关)

---

## 五、功能协同关系图

### 5.1 模块间数据依赖

```
数据管道 ──→ 因子引擎 ──→ 信号/组合 ──→ 风控 ──→ 执行
  │              │            │           │         │
  │              ▼            │           │         ▼
  │         因子分析器         │           │     trade_log
  │              │            │           │         │
  │              ▼            │           │         ▼
  │         因子生命周期       │           │    绩效分析
  │              │            │           │         │
  │              ▼            ▼           │         ▼
  │         因子挖掘(Phase1) ←── AI闭环 ──┘    performance_series
  │                                                  │
  │                                                  ▼
  └──────────────────────────────────────────── 前端展示
                                                     │
                                                     ▼
                                                 通知推送
```

### 5.2 功能实现依赖链（必须按此顺序）

```
第0层(基础,已完成): PG/Redis → 数据拉取 → 因子计算 → 信号 → 回测 → 风控 → 执行

第1层(基础设施补全):
  ├─ 数据服务集中化(DataService) ← 当前散落在scripts中
  ├─ UniverseFilter独立模块 ← 当前内嵌signal_engine
  ├─ 任务依赖链(Redis gate) ← 当前health失败不阻塞signal
  └─ WebSocket基础设施 ← 前端/通知/回测进度都需要

第2层(多策略+因子扩展):
  ├─ BaseStrategy扩展 → StrategyPortfolioManager
  ├─ EventStrategy / TrendStrategy / ValueStrategy
  ├─ 新因子接入(north_flow/margin/大单) ← 需要DataService先就位
  └─ 因子Gate Pipeline自动化 ← 需要因子生命周期自动转换

第3层(AI闭环):
  ├─ GP遗传编程引擎
  ├─ LLM 3-Agent因子发现(DeepSeek)
  ├─ PipelineOrchestrator(8节点状态机)
  ├─ approval_queue + agent_decision_log
  └─ 14个AI参数渐进替换

第4层(前端+运维):
  ├─ 前端12页面(依赖后端API全部就绪)
  ├─ 完整通知系统(32模板+WebSocket)
  ├─ 参数系统补全(220+参数)
  └─ 压力测试/CI-CD/监控
```

---

## 六、完整开发路线（Sprint计划）

### Phase 0 收尾（预计2-3个Sprint，PT期间执行）

#### Sprint 1.13: 基础设施补全 + 多策略框架（2周）

| # | 任务 | 文件 | 工作量 | 依赖 |
|---|------|------|--------|------|
| 1 | DataService集中化 | `app/services/data_service.py`(新) | 2天 | 无 |
| 2 | UniverseFilter独立 | `engines/universe_filter.py`(新) | 1天 | 无 |
| 3 | BaseStrategy扩展(+调仓频率/+仓位方式) | `engines/base_strategy.py` | 1天 | 无 |
| 4 | StrategyPortfolioManager | `engines/strategy_portfolio.py`(新) | 2天 | #3 |
| 5 | EventStrategy(RSRS适配) | `engines/strategies/event_strategy.py`(新) | 2天 | #3,#4 |
| 6 | RSRS事件策略回测验证 | `scripts/backtest_event_strategy.py`(新) | 1天 | #5 |
| 7 | 任务依赖链(Redis gate) | `app/tasks/daily_pipeline.py` | 1天 | 无 |
| 8 | miniQMT卖出验证 | `scripts/test_qmt_sell.py` | 0.5天 | 交易时间 |

**验收标准**: RSRS事件策略Sharpe与月度等权对比有统计差异 / Redis gate阻塞测试PASS

#### Sprint 1.14: 因子扩展 + 策略丰富（2周）

| # | 任务 | 文件 | 工作量 | 依赖 |
|---|------|------|--------|------|
| 1 | north_flow因子接入(Tushare hk_hold) | `data_fetcher/` + `factor_engine.py` | 2天 | DataService |
| 2 | margin因子接入 | `data_fetcher/` + `factor_engine.py` | 1天 | DataService |
| 3 | 大单比因子(moneyflow已有) | `factor_engine.py` | 0.5天 | 无 |
| 4 | TrendStrategy(VWAP适配) | `engines/strategies/trend_strategy.py`(新) | 2天 | BaseStrategy |
| 5 | FlowStrategy(资金流适配) | `engines/strategies/flow_strategy.py`(新) | 2天 | #1,#3 |
| 6 | 因子Gate Pipeline自动化 | `engines/factor_gate.py`(新) | 2天 | 无 |
| 7 | 因子生命周期自动转换 | `services/factor_lifecycle_service.py`(新) | 1天 | #6 |
| 8 | 新因子全部过Gate | 脚本 | 1天 | #1-#3,#6 |

**验收标准**: ≥3个新因子通过Gate(t>2.5) / 每种策略类型至少1个实例 / 生命周期自动转换测试PASS

#### Sprint 1.15: 回测引擎升级 + 压力测试（2周）

| # | 任务 | 文件 | 工作量 | 依赖 |
|---|------|------|--------|------|
| 1 | ExecutionSimulator(Step 2) | `engines/execution_simulator.py`(新) | 3天 | 无 |
| 2 | DataFeed统一类 | `engines/data_feed.py`(新) | 1天 | 无 |
| 3 | 压力测试脚本(5场景) | `scripts/stress_test.py`(新) | 2天 | #2 |
| 4 | Walk-Forward集成到回测脚本 | `scripts/run_backtest.py` | 1天 | 无 |
| 5 | WebSocket基础设施 | `app/websocket/`(新) | 2天 | 无 |
| 6 | 回测进度WebSocket推送 | `app/tasks/` + WS | 1天 | #5 |

**验收标准**: ExecutionSimulator vs SimpleBacktester偏差<1% / 5个压力场景全部运行通过

### Phase 1: AI闭环（预计4-5个Sprint）

#### Sprint 1.16: GP因子挖掘引擎（2周）

| # | 任务 | 文件 | 工作量 |
|---|------|------|--------|
| 1 | GP遗传编程引擎(岛屿模型) | `engines/gp_engine.py`(新) | 5天 |
| 2 | 因子表达式DSL(参考Qlib) | `engines/factor_dsl.py`(新) | 2天 |
| 3 | GP搜索空间定义(量纲剪枝) | `engines/gp_config.py`(新) | 1天 |
| 4 | GP产出因子自动Gate+入库 | 集成 | 1天 |
| 5 | GPU加速(RTX 5070) | 配置 | 1天 |

#### Sprint 1.17: LLM因子发现（2周）

| # | 任务 | 文件 | 工作量 |
|---|------|------|--------|
| 1 | DeepSeek API集成 | `integrations/deepseek_client.py`(新) | 1天 |
| 2 | Idea Agent(方向生成) | `app/agents/idea_agent.py`(新) | 2天 |
| 3 | Factor Agent(代码生成+验证) | `app/agents/factor_agent.py`(新) | 2天 |
| 4 | Eval Agent(自动评估) | `app/agents/eval_agent.py`(新) | 2天 |
| 5 | mining_knowledge表+去重 | DB + 逻辑 | 1天 |
| 6 | UCB1搜索方向调度器 | `engines/ucb1_scheduler.py`(新) | 1天 |

#### Sprint 1.18: AI闭环Pipeline（2周）

| # | 任务 | 文件 | 工作量 |
|---|------|------|--------|
| 1 | PipelineOrchestrator(8节点状态机) | `app/services/pipeline_service.py`(新) | 3天 |
| 2 | approval_queue + agent_decision_log | DB + API | 2天 |
| 3 | 14个AI参数L1/L2/L3授权逻辑 | `app/services/param_service.py` | 2天 |
| 4 | AI变更三步验证(建议→回测→审批) | 集成 | 2天 |
| 5 | Pipeline控制台API(10端点) | `app/api/pipeline.py`(新) | 1天 |

#### Sprint 1.19-1.20: AI参数渐进替换 + 验证

- 每个参数: 规则版 vs AI版 OOS对比
- 3个月验证期, 只有AI≥规则才切换
- 目标: 14个参数中至少5个AI接管

### Phase 1 并行: 前端开发（与AI闭环并行）

#### Sprint F1: 核心页面（2周）

| 页面 | 路由 | 依赖API | 工作量 |
|------|------|---------|--------|
| Dashboard完善 | `/dashboard` | 已有 | 2天 |
| 策略工作台 | `/strategy` | strategy CRUD | 3天 |
| 回测配置+运行+结果 | `/backtest/*` | backtest API | 5天 |

#### Sprint F2: 因子+AI页面（2周）

| 页面 | 路由 | 依赖API | 工作量 |
|------|------|---------|--------|
| 因子库 | `/factors` | factor API | 2天 |
| 因子评估报告 | `/factors/:id` | factor report API | 3天 |
| 因子实验室 | `/mining` | mining API | 3天 |
| 策略库 | `/backtest/history` | backtest history API | 2天 |

#### Sprint F3: 系统+AI闭环页面（2周）

| 页面 | 路由 | 依赖API | 工作量 |
|------|------|---------|--------|
| Pipeline控制台 | `/pipeline` | pipeline API | 3天 |
| Agent配置 | `/pipeline/agents` | agent API | 2天 |
| 系统设置 | `/settings` | system API | 3天 |
| 挖掘任务中心 | `/mining/tasks` | mining tasks API | 2天 |

---

## 七、通知系统完整设计

### 7.1 32个通知模板

| 类别 | 数量 | 级别分布 | 已实现 |
|------|------|---------|--------|
| 风控类 | 7 | P0×3, P1×4 | 部分 |
| 交易类 | 6 | P1×1, P2×4, P3×1 | 部分 |
| 因子类 | 2 | P1×1, P2×1 | 部分 |
| 回测类 | 2 | P1×1, P2×1 | 无 |
| AI闭环类 | 2 | P2×2 | 无 |
| 系统类 | 7 | P0×3, P1×3, P2×1 | 部分 |
| Review补丁 | 6 | P0×1, P1×2, P2×3 | 部分 |

### 7.2 防洪泛规则

关键: `risk.drawdown_warning`最小5min / `risk.daily_loss`最小24h / `system.mt5_disconnect`最小1min

---

## 八、参数系统路线图

| 阶段 | 参数数量 | 覆盖范围 |
|------|---------|---------|
| 当前 | ~50 | Phase 0核心(因子/信号/风控/滑点) |
| Sprint 1.13 | +30 | 多策略参数(调仓频率/仓位方式/止损) |
| Sprint 1.16-1.18 | +60 | AI/GP/LLM参数 |
| Sprint F1-F3 | +80 | 前端偏好/通知配置 |
| **总计** | **~220** | 全覆盖 |

---

## 九、技术债务清单

| # | 债务 | 风险 | 修复成本 | Sprint |
|---|------|------|---------|--------|
| 1 | 任务依赖链缺失(health失败不阻塞signal) | P0 | 1天 | 1.13 |
| 2 | ORM模型为空(全部raw SQL) | P2 | 3天 | 可延后 |
| 3 | Alembic迁移未配置 | P1 | 0.5天 | 1.13 |
| 4 | Celery单队列(设计8个) | P2 | 0.5天 | 1.15 |
| 5 | AKShare备用源缺失 | P1 | 2天 | 1.14 |
| 6 | loguru vs logging不一致 | P3 | 1天 | 可延后 |
| 7 | WebSocket完全缺失 | P1 | 2天 | 1.15 |
| 8 | 因子Gate Pipeline非自动化 | P1 | 2天 | 1.14 |
| 9 | 审计报告7处过时 | P3 | 0.5天 | 1.13 |

---

## 十、风险登记

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| PT期间v1.1表现不及预期 | 中 | 高 | 多策略框架分散风险,不依赖单一策略 |
| 新因子全部不过Gate | 低 | 中 | 34个设计因子中只实现14.7%，空间很大 |
| AI闭环过拟合 | 中 | 高 | 铁律7 OOS验证+DSR+PBO |
| 前端开发拖延 | 高 | 低 | 前端不影响策略运行,可后置 |
| Tushare积分/限速 | 低 | 中 | AKShare备用源(Sprint 1.14) |
| GPU内存不足(12GB) | 低 | 低 | LightGBM轻量,GP可分批 |

---

## 十一、关键决策待确认

在启动实施前，需要用户确认以下方向性决策：

1. **多策略资金分配**: v1.1等权策略占多大比例？新策略如何分配？
2. **AI闭环优先级**: 先做GP(自动化高)还是先做LLM(灵活性高)？
3. **前端与后端并行度**: 前端是否与Phase 1并行？还是Phase 1完成后再做？
4. **PT期间可执行范围**: 哪些改动允许在PT运行时做（不影响v1.1配置）？
5. **外汇Phase 2启动时间**: 是否等A股Phase 1完成再开始？

---

## 十二、系统性错误复盘（从30个LL中提炼）

### 12.1 反复犯的7类错误

| # | 错误模式 | 频次 | 代表案例 | 根因 |
|---|---------|------|---------|------|
| 1 | **单一框架思维** | 10+ | 所有因子塞等权Top15月度(RSRS/PEAD/mf_divergence全部失败)；9种线性合成；HMM替换vol_regime | 没有因子-策略匹配理论框架，把"策略"和"因子"混为一谈 |
| 2 | **执行靠记忆不靠机制** | 5次 | LL-015/016"说了没做"；PROGRESS.md五天没更新；管理仪表板执行率<30% | 规则写入宪法但无强制触发机制 |
| 3 | **不做外部研究** | 3次 | LL-022只靠脑子想；没搜QuantaAlpha/RD-Agent/FactorEngine；没读券商研报 | 把"已知"当全部，缺少"可能不知道更重要的东西"意识 |
| 4 | **隐含假设未显式化** | 5个bug | 数据排序方向(LL-003)；自然日vs交易日(LL-004)；因子方向(LL-001)；execute覆盖signal(LL-005) | 开发时脑中假设没写成代码断言 |
| 5 | **Proxy代替正式验证** | 2次 | LL-011 Proxy分析差1.1个Sharpe；因子IC强≠组合增量(LL-017) | 图快跳过SimBroker正式回测 |
| 6 | **反复尝试已证伪方向** | 多次 | 等权升级(v1.2)反复4次；基本面10种方式穷举；线性合成9种方法 | 没有"方向关闭"的止损机制 |
| 7 | **缺乏标准化流程** | 持续 | 因子开发无标准流程；策略验证无checklist；研究无方法论 | 每次从零开始，不积累可复用流程 |

### 12.2 应该有但一直缺的标准化流程

**因子开发标准流程（当前缺失）**:
```
Step 1: 假设生成 — 经济学逻辑+文献支撑
Step 2: 小样本验证 — 100只股票×1年(<10秒) → IC>0.015?方向对?
Step 3: 全量计算+Gate Pipeline — 8步自动化检查(G1-G8)
Step 4: 策略匹配 — 根据ic_decay/信号分布确定适配策略类型(铁律8)
Step 5: SimBroker回测 — 用匹配的策略类型回测(不是默认等权月度)
Step 6: 统计检验 — Bootstrap CI + paired比较 + Bonferroni校正
Step 7: 压力测试 — 5个历史极端场景
Step 8: 影子模式 — 60天PT期间只记录不使用
Step 9: 入池/拒绝 — 写入决策表+更新FACTOR_TEST_REGISTRY
```

**策略验证标准流程（当前缺失）**:
```
Step 1: 因子特性分析 — ic_decay曲线/信号持续性/换手特征/截面分布
Step 2: 策略类型选择 — 排序型/事件型/动量型/价值型/资金流型
Step 3: 参数设计 — 调仓频率/选股方式/仓位管理/止盈止损
Step 4: 参数搜索 — Optuna(限制搜索空间防过拟合)
Step 5: OOS回测 — Rolling fit，严格无look-ahead
Step 6: 统计对比 — 与基线paired bootstrap
Step 7: 压力测试 — 5个历史场景 + 成本敏感性
Step 8: 多策略组合验证 — 与已有策略的相关性 + 资金分配优化
```

**错误避免checklist（从30个LL提炼，每次研究前必过）**:
- [ ] 是否用了正确的策略框架测试这个因子？(不是默认等权月度)
- [ ] 基线配置是否与PAPER_TRADING_CONFIG一致？(LL-010/013)
- [ ] 是否做了中性化后IC验证？(LL-014)
- [ ] 是否跑了正式回测（非Proxy）？(LL-011)
- [ ] Bootstrap CI下界是否>0？(回测可信度规则4)
- [ ] 是否搜索了最新外部方法？(LL-022)
- [ ] 选股月收益corr是否<0.3？(LL-009，因子corr≠选股corr)
- [ ] 这个方向是否已被证伪？(检查决策表)

---

## 十三、外部前沿研究与差距分析

### 13.1 因子挖掘前沿（2025-2026，我们的设计已落后）

| 项目 | 核心思想 | 与我们的差距 | 来源 |
|------|---------|------------|------|
| QuantaAlpha | LLM+进化策略，轨迹级mutation/crossover，GPT-5.2达IC=0.1501 | 我们的LLM 3-Agent设计缺少轨迹进化 | arXiv 2602.07085 |
| RD-Agent-Quant | 多Agent因子+模型联合优化，5阶段迭代闭环 | 我们的因子挖掘和模型训练是分离的 | Microsoft 2025 |
| FactorEngine | 程序级因子，宏观-微观协同进化，逻辑vs参数分离 | 我们的GP引擎没有这种分离 | arXiv 2603.16365 |
| AlphaAgent | 正则化探索抗Alpha衰减，AST去重+假设对齐 | 我们的去重只计划了embedding相似度 | KDD 2025 |
| FactorMiner | 自进化Agent，技能+经验记忆 | 我们没有跨轮次的经验积累机制 | arXiv 2602.14670 |

### 13.2 策略与组合前沿

| 发现 | 核心思想 | 对我们的启示 | 来源 |
|------|---------|------------|------|
| 因子舒适区 | 个股级因子预测有效性，连续舒适度得分 | 因子在不同股票上表现不同，不能一刀切 | 华安证券2025 |
| 从多因子走向多策略 | 子策略间风险收益互补 | 验证了我们多策略方向的正确性 | BigQuant研究 |
| 因子择时回归 | 逻辑驱动择时优于黑箱 | 我们的HMM(黑箱)失败印证了这一点 | 知乎/券商研报 |
| 量化私募2026趋势 | AI从辅助→核心，多资产多策略 | 行业方向与我们一致 | 第一财经 |

### 13.3 外部项目评估与决策（2026-03-28确认）

| 项目 | 优点 | 已知问题/限制 | **决策** |
|------|------|-------------|---------|
| QuantaAlpha | IC=0.1501(GPT-5.2)，轨迹级进化 | 依赖GPT-5.2(成本高)；A股实证有限 | Step 3借鉴轨迹进化思想 |
| Qlib | Alpha158算子集完整，qrun一键回测 | 回测不支持A股整手约束/涨跌停封板 | **Alpha158做FactorDSL算子参考，不集成回测** |
| AlphaAgent | 正则化探索抗Alpha衰减，AST去重 | 3-Agent结构与我们设计相似 | 借鉴AST去重+假设对齐 |
| RD-Agent | 5单元闭环，知识森林，因子+模型联合优化 | 框架依赖Azure，较重 | **借鉴核心思想(知识森林/联合优化/Co-STEER)，不直接集成** |
| Warm Start GP | 模板初始化，结构约束，A股2020-2024验证 | 搜索空间较窄 | **Step 2核心引擎，用现有5因子做模板** |

**三步走落地路径**: Step 1 PT赚钱(不需AI) → Step 2 GP最小闭环(Warm Start GP+Gate+SimBroker反馈) → Step 3 完整AI闭环(LLM Agent+知识森林+Pipeline)

---

## 十四、研究方法论

### 14.1 研究原则

1. **带着问题搜索，不是漫无目的浏览** — 每次研究必须先明确"要解决什么问题"
2. **系统性覆盖，不是零散抓取** — 每个维度覆盖: 论文+GitHub+券商研报+中文社区+生产案例
3. **批判性评估，不是盲目采用** — 每个发现都要问: A股成立吗？100万可行吗？issue/限制是什么？
4. **落地优先，不是纸上谈兵** — 每个发现必须产出: 改哪个文件 → 工作量 → 预期收益 → 风险
5. **积累复用，不是每次从零** — 研究成果写入标准报告，下次直接引用不重复搜索

### 14.2 六维度深度研究计划

| 维度 | 核心问题 | 查阅范围 | 产出 |
|------|---------|---------|------|
| R1: 因子-策略匹配 | 因子特性如何决定策略类型？判断标准？ | 因子舒适区论文/券商研报/Qlib策略模板/BigQuant案例 | 匹配框架+决策树 |
| R2: 因子挖掘前沿 | QuantaAlpha/AlphaAgent/FactorEngine/RD-Agent哪个最适合？ | 4个GitHub完整代码+论文+issue+实验复现 | 技术选型报告 |
| R3: 多策略组合 | 100万多策略如何分配？风险预算怎么做？ | HRP/风险平价/Kelly/券商多策略研报/实盘案例 | 资金分配方案 |
| R4: A股微观结构 | 滑点/流动性/涨跌停精确建模？ | 上交所报告/Bouchaud/学术实证/PT实测数据 | 校准成本模型 |
| R5: 回测-实盘对齐 | 如何缩小gap？哪些偏差最大？ | MLOps/Qlib部署/PT数据分析/实盘复盘 | 对齐检查清单 |
| R6: 生产架构 | 个人系统如何稳定运行？ | Qlib/vnpy架构/运维实践/故障案例 | 运维SOP |

### 14.3 每维度查阅路径

```
1. 学术论文(arxiv/SSRN/KDD/ICAIF/NeurIPS)
   → 理论基础+最新方法
   → 关注: 假设条件/数据需求/计算复杂度/A股适用性

2. 开源项目(GitHub)
   → 实际实现(不只看README，要读源码)
   → 关注: 架构/测试覆盖/issue列表(暴露真实问题)/最近commit活跃度

3. 券商金工研报(国金/华安/中信/海通/广发)
   → A股特定的实证结果
   → 关注: 因子有效性周期/交易成本假设/样本期/回测方法

4. 中文社区(知乎/微信公众号/掘金/BigQuant/看海量化)
   → 实践者踩坑经验
   → 关注: 遇到什么问题/怎么解决/哪些方法实际有效

5. 生产系统案例(Qlib/vnpy/QuantConnect/Zipline)
   → 架构设计和工程实践
   → 关注: 如何处理我们遇到的同样问题
```

### 14.4 研究报告标准格式

每份研究报告必须包含：

```
1. 问题定义 — 我们遇到了什么具体问题？为什么当前方案不行？
2. 文献综述 — 找到了哪些方法？各自原理/优劣/适用条件？
3. A股适用性 — 哪些能用？哪些不能？T+1/涨跌停/政策驱动的影响？
4. 资金量级适用性 — 100万vs机构的区别？容量约束？成本占比？
5. 竞品对比 — 已有开源项目做得怎么样？问题在哪？
6. 推荐方案 — 选哪个？怎么改？为什么？
7. 落地计划 — 改哪些文件/函数？工作量？依赖？
8. 测试方案 — 怎么验证方案有效？OOS标准？
9. 风险评估 — 最坏情况？fallback方案？
10. 参考文献 — 完整链接，后续可追溯
```

### 14.5 方法论补充（易遗漏的关键点）

**① 竞品实盘跟踪，不只看论文回测**
- 论文都展示最优结果，实盘可能完全不同
- 追踪公开净值：券商量化产品(国金量化多因子C/华安Smart Beta)验证研报方法是否真实有效
- GitHub项目有无公开的live trading业绩？如果没有，要对回测结果打折
- Qlib benchmark在2025-2026实际A股表现如何？

**② 失败案例研究（和成功案例同等重要）**
- GitHub上停更/归档的量化项目为什么失败？
- 知乎/公众号"我的策略为什么失效了"类文章是最真实的踩坑记录
- 我们自己的30个LL是最好的失败案例库——每次研究前先重读相关LL

**③ AI模型选型研究（AI闭环核心依赖）**
- 月预算可根据实际需求弹性调整，不设固定上限
- 需要系统性评估：哪款AI模型最适合量化研究的AI闭环？
- 评估维度：

| 评估维度 | 具体指标 |
|---------|---------|
| 因子代码生成质量 | 生成的Python代码一次通过率、bug率 |
| 金融领域知识深度 | 对A股因子/交易规则/风控逻辑的理解准确度 |
| 推理与假设生成 | 能否提出有经济学逻辑的新因子假设 |
| 成本效率 | 每个有效因子的API成本（不只看单次调用价格） |
| 上下文窗口 | 能否一次性消化因子知识库+失败历史+搜索方向 |
| 延迟 | 单轮生成时间（影响GP+LLM混合pipeline的吞吐） |
| 本地部署可行性 | RTX 5070 12GB能否跑量化的本地模型(Qwen2.5/DeepSeek-Coder等) |

- 候选模型清单（需逐一评估）：

| 模型 | 优势 | 劣势 | 适用场景 |
|------|------|------|---------|
| DeepSeek R1/V3 | 成本低、中文理解强、推理能力好 | 金融专业知识待验证 | Idea Agent假设生成 |
| Claude Opus/Sonnet | 长上下文、代码质量高、推理强 | 成本较高 | 复杂因子设计、诊断分析 |
| GPT-4o/5系列 | 全能、工具调用成熟 | 成本最高、中文可能弱于DeepSeek | 需要多工具协作的Agent |
| Qwen2.5-Coder-32B | 可本地部署(RTX 5070)、代码专精 | 推理能力弱于闭源大模型 | Factor Agent代码生成(低成本高吞吐) |
| 混合方案 | 不同Agent用不同模型、成本最优 | 集成复杂度高 | 生产环境推荐 |

- **推荐研究路径**: 先用相同的10个因子生成任务benchmark不同模型，比较一次通过率/IC/成本，再决定AI闭环的模型架构

**④ 方法的时效性评估**
- A股因子半衰期通常3-5年
- 2020年有效的方法2025年可能已拥挤（reversal_20已被MSCI标记为机械因子拥挤风险1.7x）
- 研究时关注：方法发表时间 → 当前是否已被广泛采用 → 拥挤度如何

**⑤ 与已有代码的兼容性评估**
- 不是"方法好不好"而是"能不能嵌入我们80K行代码"
- 接口兼容性（DataFrame格式/factor_values表schema）
- 依赖库冲突（hmmlearn/lightgbm/torch版本）
- 测试体系是否能覆盖新模块

**⑥ 渐进验证，不是一步到位**
- 每个研究维度先做**最小可行验证**（1天），确认方向对了再深入
- 用"假设→最小实验→结论→决策"循环，避免"研究3周写报告但方向错了"
- 参考铁律3：先SimBroker回测验证，不要在理论层面纠缠太久

---

## 附录A：34个因子完整定义

### 类别①价量技术（12个）

| # | 因子名 | 公式 | 方向 | 数据源 | 状态 |
|---|--------|------|------|--------|------|
| 1 | reversal_5 | 5日收益率 | 负 | klines_daily | ✅已实现 |
| 2 | reversal_20 | 20日收益率 | 负 | klines_daily | ✅v1.1活跃 |
| 3 | momentum_60 | 60日收益率 | 正 | klines_daily | ✅已实现(Deprecated) |
| 4 | momentum_120 | 120日收益率(跳过近20日) | 正 | klines_daily | ✅已实现(Deprecated) |
| 5 | volatility_20 | 20日收益率标准差 | 负 | klines_daily | ✅v1.1活跃 |
| 6 | idio_vol_20 | FF3残差波动率 | 负 | klines_daily | ❌未实现 |
| 7 | max_ret_20 | 20日最大单日涨幅 | 负 | klines_daily | ❌未实现 |
| 8 | volume_price_corr | 量价相关性(20日) | 负 | klines_daily | ✅已实现 |
| 9 | KMID | (close-open)/open | 正 | klines_daily | ✅已实现(KBAR) |
| 10 | KSFT | (2*close-high-low)/open | 正 | klines_daily | ✅已实现(KBAR) |
| 11 | CNTP_20 | 20日上涨天数比例 | 正 | klines_daily | ❌未实现 |
| 12 | RSV_20 | 相对强度值 | 正 | klines_daily | ❌未实现 |

### 类别②流动性（6个）

| # | 因子名 | 公式 | 方向 | 数据源 | 状态 |
|---|--------|------|------|--------|------|
| 13 | turnover_mean_20 | 20日平均换手率 | 负 | daily_basic | ✅v1.1活跃 |
| 14 | turnover_std_20 | 换手率波动性(20日std) | 负 | daily_basic | ✅已实现 |
| 15 | amihud_20 | Amihud非流动性(\|ret\|/amount) | 正 | klines_daily | ✅v1.1活跃 |
| 16 | volume_ratio_20 | 量比(vol/vol_ma60) | 负 | klines_daily | ❌未实现 |
| 17 | amount_std_20 | 成交额波动性(20日) | 负 | klines_daily | ✅已实现 |
| 18 | turnover_zscore_20 | 标准化换手率 | 负 | daily_basic | ✅已实现 |

### 类别③资金流向（6个）

| # | 因子名 | 公式 | 方向 | 数据源 | 状态 |
|---|--------|------|------|--------|------|
| 19 | north_flow_net_20 | 北向资金20日净买入 | 正 | hk_hold | ❌未实现 |
| 20 | north_flow_change | 北向资金变化率 | 正 | hk_hold | ❌未实现 |
| 21 | big_order_ratio | 大单净流入比 | 正 | moneyflow | ✅已实现 |
| 22 | margin_balance_chg | 融资余额变化率 | 正 | margin_data | ❌未实现 |
| 23 | short_ratio | 做空比 | 负 | margin_data | ❌未实现 |
| 24 | winner_rate | 获利盘比例 | 负 | cyq_perf | ❌未实现 |

### 类别④基本面价值（8个）

| # | 因子名 | 公式 | 方向 | 数据源 | 状态 |
|---|--------|------|------|--------|------|
| 25 | ep_ratio | 1/PE_TTM | 正 | daily_basic | ✅已实现 |
| 26 | bp_ratio | 1/PB | 正 | daily_basic | ✅v1.1活跃 |
| 27 | div_yield | 股息率TTM | 正 | daily_basic | ❌未实现 |
| 28 | roe_ttm | ROE TTM | 正 | fina_indicator | ❌未实现 |
| 29 | gross_margin | 毛利率 | 正 | fina_indicator | ❌未实现 |
| 30 | roa_ttm | ROA TTM | 正 | fina_indicator | ❌未实现 |
| 31 | debt_to_asset | 资产负债率 | 负 | fina_indicator | ❌未实现 |
| 32 | current_ratio | 速动比率 | 正 | fina_indicator | ❌未实现 |

### 类别⑤规模（1个）+ 类别⑥行业（1个）

| # | 因子名 | 用途 | 状态 |
|---|--------|------|------|
| 33 | ln_float_cap | 规模因子(中性化用) | ✅已实现 |
| 34 | sw_industry_1 | 行业因子(中性化/归因用) | ✅已实现 |

**统计**: 34个设计因子中 ✅已实现20个(含KBAR/mf_divergence等额外因子) / ❌未实现14个

---

## 附录B：因子Gate Pipeline（8步自动化）

| # | 检查项 | 阈值 | 失败动作 |
|---|--------|------|---------|
| G1 | IC均值 | \|IC_mean\| > 0.02 | 拒绝 |
| G2 | IC信息比 | IC_IR > 0.3 | 拒绝 |
| G3 | IC胜率 | > 55% | 拒绝 |
| G4 | 单调性 | > 0.7 (5组) | 拒绝 |
| G5 | 半衰期 | > 5天 | 候选(不拒绝) |
| G6 | 相关性 | max_corr < 0.7(与活跃因子) | 拒绝 |
| G7 | 覆盖率 | > 80% | 拒绝 |
| G8 | 综合评分 | ≥70(IC×30+IR×20+win×15+mono×15+半衰×10+覆盖×10) | <50拒绝, 50-70候选 |

FDR校正: total_tested > 20时, adjusted_t = base_t + log(N)×0.3

---

## 附录C：AI闭环Pipeline 12状态机

```
IDLE → FACTOR_DISCOVERY → FACTOR_EVALUATION → FACTOR_APPROVAL_PENDING
  ↑                                                      │
  │                                          ┌───────────▼
  │                                          │ STRATEGY_BUILD
  │                                          │      │
  │                                          │      ▼
  │                                    BACKTEST_RUNNING
  │                                          │
  │                                          ▼
  │                                    RESULT_ANALYSIS
  │                                          │
  │                                          ▼
  │                                    RISK_CHECK
  │                                     │      │
  │                                     │      ▼
  │                                     │ DEPLOY_APPROVAL_PENDING
  │                                     │      │
  │                                     ▼      ▼
  │                                  DIAGNOSIS  COMPLETED
  │                                     │
  └─────────────────────────────────────┘ (max 3 loops)
                                          │
                                          ▼
                                       FAILED
```

触发方式: 每周日22:00定时 / 绩效衰退>阈值事件驱动 / 手动触发

---

## 附录D：完整API端点清单（~67个 + 5 WebSocket）

| 模块 | 端点数 | 已实现 | 缺失 |
|------|--------|--------|------|
| Dashboard | 11 | ~5 | 6 |
| 回测 | 14 | ~8 | 6 |
| 因子挖掘 | 15 | 0 | 15 |
| AI闭环 | 10 | 0 | 10 |
| 通知 | 9 | 4 | 5 |
| 系统设置 | 8 | ~3 | 5 |
| WebSocket | 5 | 0 | 5 |
| **总计** | **72** | **~20** | **~52** |

---

## 附录E：前端12页面组件体系

**通用高频组件**: GlassCard(4变体) / MetricCard(4变体) / Button(5变体) / TabBar(3变体) / Input(5变体) / Select / Slider / Table(5变体) / Badge(5色) / Loading(4变体)

**通用中频组件**: Sidebar(2态) / Breadcrumb / Modal(3变体) / Toast(4类型) / Tooltip / Switch / DatePicker / Progress(4变体) / EmptyState(4类型)

**专业组件**: CodeEditor(Monaco) / FlowNode / ChatBubble(AI助手) / ChartWrapper(ECharts) / ApprovalCard / StrategyCard

**A股专属**: StockPositionTable / IndustryPieChart / FactorICChart / LimitUpDownBadge / DynamicPositionBar

---

*本文档是项目的完整开发蓝图，所有Sprint任务均可直接转化为具体编码任务。每个Sprint启动前应按V3.3宪法spawn角色团队。*
