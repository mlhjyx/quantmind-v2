# SYSTEM_RUNBOOK.md — QuantMind V2 系统运行手册

> **用途**: 给 Claude Code 的技术实施指南。描述系统**当前真实状态**，不是设计愿景。
> **更新时间**: 2026-04-06 (系统诊断修复后)
> **配合文档**: CLAUDE.md（规则约束）、DEV_*.md（详细设计参考）
> **总设计文档**: docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md (v3.8.1)
> **注意**: §10标注了设计文档与实际实现的已知差异。编码以"实际"列为准。

---

## 1. 系统当前状态快照

| 维度 | 实际状态 |
|------|---------|
| 阶段 | Phase 1, Sprint 1.35 完成, PT Day 4/60 |
| PT状态 | v1.2 QMT live, Top-20+无行业约束+PMS v1.0, NAV≈¥968,163 |
| 后端 | 128+ Python 文件, ~40K LOC, sync psycopg2 (Service层) + async asyncpg (部分) |
| 前端 | 35 页面, 53 共享组件, ~13K LOC |
| 测试 | 2076+ passed (90个test文件) |
| 调度 | Task Scheduler=PT主链(12任务), Beat=GP+PMS平台任务, Servy=进程托管 |
| 数据库 | PostgreSQL 16.8 + TimescaleDB 2.26.0 @ D:\pgdata16, user=xin, 62+张表 |
| 基线 | 5因子等权, **Top-20**, 月度, **无行业约束(1.0)**, Sharpe=**1.15**, MDD=-35.1%, Calmar=0.83 |
| GP状态 | 全链路验证通过, Beat周日22:00自动触发 |

---

## 2. 启动链路（如何跑起来）

### 2.1 基础服务（Servy管理，自动启动）

```bash
# 生产环境: 所有服务由 Servy v7.6 管理，开机自启动
# 查看状态: powershell -File scripts\service_manager.ps1 status
# 重启单个: powershell -File scripts\service_manager.ps1 restart fastapi
# 重启全部: powershell -File scripts\service_manager.ps1 restart all

# Servy管理的服务（启动顺序由依赖自动决定）:
#   QuantMind-FastAPI    — uvicorn --workers 2, port 8000
#   QuantMind-Celery     — celery worker --pool=solo
#   QuantMind-CeleryBeat — celery beat (GP+PMS，不含PT主链)
#   QuantMind-QMTData    — qmt_data_service.py (QMT→Redis缓存)

# 原生Windows服务（不由Servy管理）:
#   PostgreSQL16 — D:\pgdata16, 端口5432, 用户xin, 数据库quantmind_v2
#   Redis        — 端口6379

# 开发调试时手动启动（需先停Servy服务避免端口冲突）:
#   D:\tools\Servy\servy-cli.exe stop --name="QuantMind-FastAPI"
cd D:\quantmind-v2\backend
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
#   验证: curl http://localhost:8000/api/health → {"status": "ok"}

# React 前端
cd D:\quantmind-v2\frontend
npm run dev
#   访问: http://localhost:3000
#    API代理: VITE_API_BASE_URL 默认 /api，由Vite devServer代理到8000端口
```

### 2.2 调度链路（Windows Task Scheduler, 2026-04-02更新）

**设计原则**: Tushare=因子计算唯一数据源(与回测一致), xtdata=交易执行+实时持仓

| 时间 | 任务名 | 执行命令 | 用途 |
|------|--------|---------|------|
| 每小时 | SmokeTest | `python scripts/smoke_test.py --auto-restart` | 62个GET端点冒烟测试+自动重启 |
| 02:00 | DailyBackup | `python scripts/pg_backup.py` | PG全量备份(7天滚动+月永久) |
| 09:31 | DailyExecute | `python scripts/run_paper_trading.py execute --execution-mode live` | QMT live执行 |
| 09:35-15:00 | IntradayMonitor | `python scripts/intraday_monitor.py` (每5分钟) | 盘中风控 |
| 15:10 | DailyReconciliation | `python scripts/daily_reconciliation.py` | QMT对账+写入live持仓快照+performance_series |
| 16:25 | HealthCheck | `python scripts/health_check.py` | 系统健康检查 |
| 16:40 | DataQualityCheck | `python scripts/data_quality_check.py` | 数据完整性巡检(第一轮) |
| 17:00 | DailyMoneyflow | `python scripts/pull_moneyflow.py` | moneyflow拉取(含重试3次×10min) |
| 17:15 | DailySignal | `python scripts/run_paper_trading.py signal` | 信号生成(Step1内含daily/basic/index拉取) |
| 17:30 | FactorHealthDaily | `python scripts/factor_health_daily.py` | 因子衰减检测(L0/L1/L2) |
| 20:00 | PTWatchdog | `python scripts/pt_watchdog.py` | 心跳监控(DB级3维度+钉钉P0) |

**数据依赖链**: 数据拉取(16:30) → 数据巡检(16:40) → 信号生成(16:50) → 因子检测(17:30)

**NSSM服务管理**:
- 生产模式: `D:\tools\nssm\win64\nssm.exe restart QuantMind-FastAPI` (代码修改后需手动重启)
- 开发模式: `cd backend && uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`
- 服务参数: `--host 0.0.0.0 --port 8000 --workers 2`

**live数据写入链路** (2026-04-02新增):
- 09:31 QMT执行 → trade_log (execution_mode='live')
- 15:10 对账 → position_snapshot (execution_mode='live') + performance_series (execution_mode='live')
- 前端 → realtime API (QMT直连) 或 DB fallback (execution_mode='live')

### 2.3 GP 因子挖掘调度（Celery Beat）

| 任务 | 触发 | 配置 |
|------|------|------|
| GP 自动运行 | 每周日 22:00 | population=100, generations=50 |

手动触发:
```bash
celery -A backend.app.tasks.celery_app call backend.app.tasks.mining_tasks.run_gp_evolution
```
Sprint 1.32验证: pipeline_runs状态完整。已知问题: population=20/generations=5时产出0因子（太小+缺pb/circ_mv字段）。

---

## 3. 架构分层规则

> 来源: DEV_BACKEND.md §3.1。**实际代码中部分模块未严格遵循此分层**——这是已知技术债。

```
Router层 (backend/app/api/):
  ✓ 参数验证(Pydantic schema)
  ✓ 调用Service层
  ✓ 返回Response schema
  ✗ 不包含业务逻辑, 不直接访问数据库

Service层 (backend/app/services/):
  ✓ 所有业务逻辑
  ✓ 调用Engine层做计算
  ✓ 调用其他Service
  ✓ Service内部不commit，调用方管理事务
  ✗ 不处理HTTP请求/响应格式

Engine层 (backend/engines/):
  ✓ 纯计算（无IO、无数据库访问）
  ✓ 输入DataFrame/dict，输出DataFrame/dict
  ✗ 不访问数据库, 不调用外部API

Integration层 (backend/app/data_fetcher/ 等):
  ✓ 封装外部API调用(Tushare/AKShare/钉钉等)
  ✓ 处理重试/超时/错误
```

---

## 4. 核心数据流

### 4.1 A股 Paper Trading 每日链路

```
T日 16:30 — Signal Phase（信号生成）
┌──────────────────────────────────────────────────────────┐
│ scripts/run_paper_trading.py signal                      │
│                                                          │
│ 1. TushareFetcher 拉取当日行情                            │
│    → klines_daily, daily_basic 表                        │
│                                                          │
│ 2. UniverseBuilder 8层过滤                                │
│    读: klines_daily(ST/停牌/涨跌停), daily_basic(市值/成交额)│
│    写: universe_daily 表                                  │
│    8层: ST剔除→次新60日→停牌→涨停→跌停→流通市值            │
│          →20日均成交额→连续停牌                            │
│                                                          │
│ 3. FactorEngine 计算5因子                                │
│    读: klines_daily, daily_basic                         │
│    计算: turnover_mean_20, volatility_20, reversal_20,   │
│          amihud_20, bp_ratio                             │
│    写: factor_values 表                                  │
│                                                          │
│ 4. SignalService.generate_signals()                      │
│    读: factor_values + universe_daily                    │
│    预处理(顺序不可变):                                    │
│      去极值(MAD 5σ) → 缺失填充(行业中位数)               │
│      → 中性化(行业+市值WLS回归取残差)                     │
│      → z-score标准化                                     │
│    合成: 等权平均 → alpha_score                          │
│    选股: 排序取 Top15                                    │
│    约束: 单行业上限 25%                                   │
│    写: signals 表                                        │
│                                                          │
│ 5. NotificationService → 钉钉: 信号摘要                  │
└──────────────────────────────────────────────────────────┘
                          │
                          ▼
T+1日 09:00 — Execute Phase（执行）
┌──────────────────────────────────────────────────────────┐
│ scripts/run_paper_trading.py execute                     │
│                                                          │
│ 1. 读 signals 表最新信号                                 │
│    信号过时检查: >5天则跳过                               │
│                                                          │
│ 2. ExecutionService.execute()                            │
│    读: position_snapshot (当前持仓)                       │
│                                                          │
│    风控: RiskControlService.check_circuit_breaker_sync()  │
│      L1: 单策略日亏>3% → 暂停1天(次日自动恢复)           │
│      L2: 总组合日亏>5% → 全部暂停(次日自动恢复)          │
│      L3: 滚动5日亏>7% OR 滚动20日亏>10% → 降仓50%(连续3天盈利>1.5%恢复) │
│      L4: 累计亏损>25% → 停止交易(人工审批恢复)           │
│                                                          │
│    涨跌停过滤(SimBroker.can_trade, 三级fallback):        │
│      1. 数据源up_limit/down_limit字段(优先)              │
│      2. symbols_info.price_limit(含ST 5%)                │
│      3. _infer_price_limit(code)按代码推断板块:           │
│         主板±10%/创业板(300/301)±20%/科创板(688)±20%     │
│         /北交所(8/4)±30%/ST需symbols_info覆盖            │
│      封板条件: abs(close-limit)<0.015 且 换手率<1%        │
│                                                          │
│    交易指令: 目标 vs 现有 → 买卖清单                      │
│    换手控制: ≤50% (边际改善排序)                          │
│    整手处理: 100股取整 (floor)                            │
│    执行: SimBroker / MiniQMT                             │
│    写: trade_log + position_snapshot                     │
│                                                          │
│ 3. PaperTradingService.update_nav()                      │
│    写: performance_series                                │
│                                                          │
│ 4. NotificationService → 钉钉: 执行结果                  │
└──────────────────────────────────────────────────────────┘
```

### 4.2 回测数据流

```
前端配置 → POST /api/backtest/run
  → BacktestService.submit_backtest() → 创建backtest_run(status='pending')
  → 提交Celery异步任务
  → Celery Worker:
      更新status='running'
      BacktestEngine.run(config):
        Hybrid架构:
          Phase A (向量化): 因子计算→预处理→合成→排序→目标持仓
          Phase B (事件驱动): 逐交易日循环→执行约束→滑点+成本→持仓更新
        WebSocket推送进度(如已连接)
      写入: backtest_run(结果) + backtest_trades(明细)
      更新status='completed'
  → 前端: GET /api/backtest/{runId}/result
```

### 4.3 GP因子挖掘数据流

```
触发: Celery Beat周日22:00 或 手动call
  → mining_tasks.run_gp_evolution()
  → pipeline_utils.py (backend/engines/mining/, 5个公开函数, Sprint 1.32新增)
  → GPEngine.evolve():
      FactorDSL算子集(Qlib Alpha158兼容): 
        时序(ts_mean/std/max/min/rank/delay/delta + ts_corr/cov)
        截面(cs_rank/cs_zscore)
        数学(abs/log/sign/add/sub/mul/div)
        基础价量(open/high/low/close/volume/amount/turnover等)
      进化: DEAP库, Warm Start(arxiv 2412.00896)
      适应度: SimBroker回测结果
  → 写入 pipeline_runs (status: running→completed/failed)
  → 候选因子 → PipelineConsole审批(Approve/Reject)
  → 审批通过 → Celery task → FactorOnboardingService.onboard_factor(approval_queue_id):
      流程: 读审批记录→写registry→计算历史值→计算IC→更新gate统计
      中性化: 调用 FactorNeutralizer 共享模块 (Sprint 1.32, 铁律2合规)
```

---

## 5. 模块依赖关系图

```
Layer 0: 基础设施
  backend/app/services/db.py       — sync psycopg2 统一连接(22行)
  backend/app/config.py            — pydantic-settings, 读.env
  backend/app/services/trading_calendar.py — 交易日工具(60行)

Layer 1: 数据层
  TushareFetcher/AKShareClient     → klines_daily, daily_basic, index_daily
  FactorEngine (34因子计算函数)      → factor_values
  UniverseBuilder (8层过滤)         → universe_daily

Layer 2: 策略层
  FactorNeutralizer (行业+截面中性化共享模块, Sprint 1.32)
    ← 被 SignalService + FactorOnboardingService 统一调用
  SignalService (信号生成)          ← FactorEngine + UniverseBuilder
  RiskControlService (L1-L4风控)   ← performance_series
  ExecutionService (交易执行)       ← SignalService + RiskControlService

Layer 3: 分析层
  BacktestEngine (Hybrid: 向量化+事件驱动) ← FactorEngine + SimBroker
  FactorAnalyzer (IC/IR/衰减分析)   ← factor_values + klines_daily
  CostModel (佣金+印花税+过户费, 内嵌在BacktestConfig)
  SlippageModel (slippage_model.py, 三因素: base+impact+overnight_gap)

Layer 4: AI层
  GPEngine (backend/engines/mining/, DEAP+Warm Start+岛屿模型+FactorDSL)
  pipeline_utils.py (backend/engines/mining/, 5个GP管道公开函数, Sprint 1.32)
  FactorOnboardingService (async, 调用FactorNeutralizer)
  PipelineOrchestrator (闭环编排, 部分实现)

Layer 5: 展示层
  FastAPI Routers (API, prefix=/api)  ← 所有 Service
  WebSocket Manager (manager.py)      — 通道+房间模式, 回测/挖掘进度推送
  React Frontend (Vite + React 18)   ← FastAPI API + WebSocket
```

---

## 6. Service 接口契约

> **原则**: Service 内部不 commit，调用方管理事务。
> **混合模式**: SignalService/ExecutionService 使用 sync psycopg2; FactorOnboardingService/pipeline_utils 使用 async asyncpg; RiskControlService 类是 async(AsyncSession) 但有独立sync函数。
> **注意**: 以下签名已于 2026-03-29 与实际代码核对校正。

### 6.1 SignalService (`backend/app/services/signal_service.py`, ~419行)

```python
class SignalService:
    def generate_signals(
        self, conn, strategy_id: str, trade_date: date,
        factor_df: pd.DataFrame, ...
    ) -> SignalResult:
        """
        输入: conn(psycopg2连接), strategy_id, trade_date, factor_df(预计算因子)
        依赖: SignalComposer + PortfolioBuilder (engines/signal_engine.py)
        输出: SignalResult(target_weights, signals_list, beta, is_rebalance)
        调用方: run_paper_trading.py signal阶段
        内部流程: compose → build → 4项验证 → Beta → 写signals表
        """
```

### 6.2 ExecutionService (`backend/app/services/execution_service.py`, ~655行)

```python
class ExecutionService:
    def execute_rebalance(
        self, conn, strategy_id: str, exec_date: date,
        target_weights: dict[str, float], ...
    ) -> ExecutionResult:
        """
        输入: conn(psycopg2连接), strategy_id, exec_date, target_weights(目标权重)
        依赖: PaperBroker / QMTExecutionAdapter, check_circuit_breaker_sync()
        输出: ExecutionResult(fills, nav, daily_return, position_count, cb_level)
        流程: 熔断检查→CB调整→Broker执行→封板补单→写trade_log
        注意: 信任signal的rebalance标记(LL-005)
        支持: paper模式(PaperBroker) / live模式(QMTExecutionAdapter)
        """
```

### 6.3 RiskControlService (`backend/app/services/risk_control_service.py`, ~1680行)

```python
# 注意: 存在两套接口——
# 1. RiskControlService 类 (async, 依赖 AsyncSession + RiskRepository)
# 2. check_circuit_breaker_sync() 独立函数 (sync, 被 run_paper_trading.py 调用)

class RiskControlService:
    """async版本, 依赖AsyncSession + RiskRepository"""

# PT实际使用的是这个独立sync函数:
def check_circuit_breaker_sync(
    conn: Any, strategy_id: str, exec_date: date, initial_capital: float
) -> dict[str, Any]:
    """
    4级熔断检查（来源: DESIGN_V5 §8.1）

    L1 PAUSED:  单策略日亏 >3% → 暂停1天, 次日自动恢复
    L2 HALTED:  总组合日亏 >5% → 全部暂停, 次日自动恢复
    L3 REDUCED: 滚动5日亏 >7% OR 滚动20日亏 >10% → 降仓50%, 连续3天盈利>1.5%恢复
    L4 STOPPED: 累计亏损 >25% → 停止交易, 人工审批恢复

    输出: {"level": 0-4, "action": "normal|pause|halt|reduce|stop"}
    """
```

### 6.4 FactorEngine (`backend/engines/factor_engine.py`)

```python
# Engine层 = 纯计算, 无IO, 无数据库访问
# 因子计算函数命名: calc_xxx(series, window) -> pd.Series
# 例:
def calc_reversal(close_adj: pd.Series, window: int) -> pd.Series
def calc_volatility(close_adj: pd.Series, window: int) -> pd.Series
def calc_volume_std(volume: pd.Series, window: int) -> pd.Series
# 输入: 单列Series(非整个DataFrame), 按个股分组后调用
# 输出: pd.Series (因子原始值)
# 要求: 全向量化, 禁止逐行循环

# v1.1 Active 5因子:
# turnover_mean_20, volatility_20, reversal_20, amihud_20, bp_ratio
# 每个因子有direction属性: +1(正向,越大越好) / -1(反向,越小越好)

# 预处理管道 preprocess_pipeline(factor_series, ln_mcap, industry):
#   Step1: MAD去极值(5σ)
#   Step2: 缺失值填充(行业中位数→0)
#   Step3: WLS中性化(行业+市值加权回归, w_i=√market_cap=√exp(ln_mcap))
#          DESIGN_V5 §4.4 标准实现（A1修复，Sprint 1.33）
#   Step4: zscore标准化
#   Step5: clip(±3) — 截断|z|>3的极端值（A8修复，Sprint 1.33）
#   返回: (raw_value, neutral_value)

# _infer_price_limit(code): 板块涨跌幅推断（见backtest_engine.py）
```

### 6.5 FactorNeutralizer (`backend/engines/neutralizer.py`, ~200行, Sprint 1.32新增)

```python
class FactorNeutralizer:
    """
    [DEPRECATED for new code] 行业+截面双重中性化共享模块（LL-036）
    无状态工具类，不依赖DB连接，纯pandas计算。
    处理: Winsorize(MAD 5σ截断) → 行业内zscore → 截面zscore
    调用方: FactorOnboardingService(GP因子入库，无ln_mcap数据)
    注意: 使用行业内zscore近似，非WLS回归。有ln_mcap时应用preprocess_pipeline。
    行业组最小样本: 5（低于此值fallback到截面zscore）
    _WINSORIZE_K: 5.0 (Sprint 1.33对齐preprocess_mad，原3.0)
    """
    def neutralize(self, raw_values: pd.Series, industry: pd.Series) -> pd.Series:
```

### 6.6 BacktestEngine (`backend/engines/backtest_engine.py`)

```python
# 实际BacktestConfig（与设计文档有差异，以此为准）:
@dataclass
class BacktestConfig:
    initial_capital: float = 1_000_000.0
    top_n: int = 20
    rebalance_freq: str = "biweekly"      # 'daily'|'weekly'|'biweekly'|'monthly'
    slippage_bps: float = 10.0            # 基础滑点(bps), fixed模式使用
    slippage_mode: str = "volume_impact"  # 'volume_impact' | 'fixed'
    slippage_config: SlippageConfig = ... # 三因素滑点配置
    commission_rate: float = 0.0000854    # 佣金万0.854（国金实际费率）
    stamp_tax_rate: float = 0.0005        # 印花税千0.5(仅卖出)
    transfer_fee_rate: float = 0.00001    # 过户费万0.1
    lot_size: int = 100                   # A股最小交易单位
    turnover_cap: float = 0.50
    benchmark_code: str = "000300.SH"

# 注意: 设计文档(DEV_BACKTEST_ENGINE §4.1)描述了更多字段(market/universe_preset/
# start_date/end_date/exec_price/weight_method/industry_cap_pct等)，实际未实现。

# 架构: SimpleBacktester + SimBroker（非设计文档描述的Hybrid Phase A/B）

# ⚠️ 2026-04-07审计发现的已知问题（加固计划Phase 1修复中）:
# - 缺分红除权处理（5年累计~10%偏差）
# - 印花税固定0.05%（2023-08-28前应为0.1%）
# - 无最低佣金5元/笔
# - overnight_gap滑点未接入SimBroker（slippage_model.py中是死代码）
# - pre_close缺失时can_trade静默返回False（已修复校验）
# - Phase A无z-score clip±3
# - BacktestResult无内置metrics/DSR/benchmark相对指标
# 详见: docs/BACKTEST_ENGINE_HARDENING_PLAN.md
```

### 6.7 GPEngine (`backend/engines/mining/gp_engine.py`, ~1262行)

```python
class GPEngine:
    def evolve(
        self, market_data: pd.DataFrame, forward_returns: pd.Series, ...
    ) -> list[dict]:
        """
        GP因子挖掘 (DEAP + 岛屿模型 + Warm Start)
        输入: market_data(行情宽表), forward_returns(前瞻收益)
        FactorDSL算子集: 时序(ts_mean/std/max/min/rank/delay/delta/ts_corr)
                        + 截面(cs_rank/cs_zscore) + 数学(abs/log/sign/四则)
                        + 基础价量(open/high/low/close/volume/amount/turnover等)
        适应度: Sharpe×(1-0.1×complexity) + 0.3×novelty
        已知问题: 小参数(pop=20/gen=5)产出0因子, 需加大+补充market data字段
        """

# 便捷入口（被mining_tasks.py调用）:
def run_gp_pipeline(
    market_data: pd.DataFrame, forward_returns: pd.Series,
    existing_factor_data: dict[str, pd.Series] | None = None, ...
) -> ...:
```

### 6.8 FactorOnboardingService (`backend/app/services/factor_onboarding.py`)

```python
class FactorOnboardingService:
    async def onboard_factor(self, approval_queue_id: int) -> dict[str, Any]:
        """
        入库审批通过的因子（async, Celery worker通过asyncio.run()调用）
        输入: approval_queue_id (approval_queue表的ID, 非因子dict)
        依赖: asyncpg直连 + FactorDSL计算
        流程: 读审批记录→写factor_registry→计算历史值→计算IC→更新gate统计
        中性化: 调用FactorNeutralizer共享模块 (Sprint 1.32, 铁律2合规)
        """
```

### 6.9 pipeline_utils.py (`backend/engines/mining/pipeline_utils.py`, ~386行, Sprint 1.32新增)

```python
# 5个GP管道公开函数（从scripts私有函数提取, 消除QA F2问题）
# 被 mining_tasks.py 调用
# 注意: 使用 structlog (非标准logging), 使用 asyncpg (非psycopg2)

async def load_market_data(db_url: str, lookback_days: int = 365) -> pd.DataFrame
async def load_existing_factor_data(db_url: str) -> dict[str, pd.Series]
def compute_forward_returns(market_data: pd.DataFrame, ...) -> pd.Series
def run_full_gate(candidates: list[Any], ...) -> ...
def send_dingtalk_notification(webhook_url: str, ...) -> ...
```

### 6.10 滑点模型 (`backend/engines/slippage_model.py`, 独立文件)

```python
@dataclass(frozen=True)
class SlippageConfig:
    """三因素滑点配置（R4研究成果: PT实测64.5bps分解）"""

def volume_impact_slippage(
    trade_amount: float, daily_volume: float, daily_amount: float,
    market_cap: float, direction: str, ...
) -> SlippageResult:
    """三因素模型: total = base_bps + impact_bps + overnight_gap_bps

    1. base_bps: 按市值分档bid-ask spread
       大盘(>500亿)=3bps / 中盘(100-500亿)=5bps / 小盘(<100亿)=8bps
    2. impact_bps: Bouchaud 2018 square-root law
       impact = Y × sigma_daily × sqrt(Q/V) × 10000
    3. overnight_gap_bps: 隔夜跳空成本(T日信号→T+1开盘)
       gap_cost = abs(open/prev_close - 1) × gap_penalty_factor × 10000
    """
```

---

## 7. 数据库核心表关系

```
行情数据:
  symbols          (~5000行, 股票代码/名称/板块/行业)
  klines_daily     (~600万行, OHLCV+复权因子+涨跌停标记)
  daily_basic      (PE/PB/换手率/流通市值/总市值)
  index_daily      (沪深300/中证500等指数日线)
  trading_calendar (交易日历, trade_date+is_open)
  moneyflow_daily  (~614万行, 资金流向)

因子数据:
  factor_registry    (因子注册: 名称/状态active|candidate|retired/IC/配置)
  factor_values      (~1.38亿行, symbol_id×date×factor_id, TimescaleDB月分区)
  factor_ic_history  (因子IC历史, 按日, Sprint 1.30B计算了5因子×538天=2632行)

策略与交易:
  strategy_configs   (策略配置JSONB, 版本化, v1.1当前)
  signals            (每日信号: 目标持仓)
  universe_daily     (每日选股Universe, 8层过滤结果)
  trade_log          (交易记录)
  position_snapshot  (持仓快照)
  performance_series (NAV序列, PT连续5天数据)

回测:
  backtest_run    (回测运行记录, status: pending→running→completed/failed)
  backtest_trades (回测交易明细)

AI/GP:
  pipeline_runs    (Pipeline运行记录, Sprint 1.31完整状态同步)
  mining_tasks     (挖掘任务)
  approval_queue   (审批队列, Sprint 1.31新增审批API)

风控:
  circuit_breaker_state (熔断状态机, 设计中, 实际是否已建表待核实)
  circuit_breaker_log   (熔断状态变更历史)

完整DDL: docs/QUANTMIND_V2_DDL_FINAL.sql (43张表)
```

---

## 8. 前端-后端 API 映射

| 前端页面 | 后端路由前缀 | 数据状态 | 备注 |
|---------|------------|---------|------|
| DashboardOverview | /api/dashboard/* | ✅ 真实数据 | 系统状态面板30s轮询 |
| DashboardAstock | /api/dashboard/portfolio | ✅ 真实数据 | 持仓/现金/仓位%真实计算 |
| StrategyWorkspace | /api/strategies/* | ✅ 真实数据 | |
| BacktestConfig | /api/backtest/* | ✅ 真实数据 | |
| BacktestRunner | /api/backtest/{runId} | ✅ 真实数据 | WebSocket进度(基础设施就绪,引擎端未emit) |
| BacktestResults | /api/backtest/{runId}/result | ✅ 真实数据 | |
| FactorLibrary | /api/factors | ✅ 真实数据 | Sprint 1.28路径对齐 |
| FactorEvaluation | /api/factors/{name}/report | ✅ 真实数据 | IC已计算(5因子×538天) |
| MiningTaskCenter | /api/mining/* | ✅ 真实数据 | Sprint 1.28路径对齐 |
| PipelineConsole | /api/pipeline/* | ✅ 审批可用 | Approve/Reject按钮 Sprint 1.31 |
| PTGraduation | /api/paper-trading/* | ✅ 真实数据 | 9项指标全部从API获取 |
| SystemSettings | /api/system/* | ⚠️ 部分 | health可用, data-sources未实现 |
| AgentConfig | /api/agent/* | ❌ 404 | 后端路由未实现 |
| DashboardForex | — | ❌ 存根 | Phase 2 |
| MarketData | — | ⚠️ 骨架 | 设计外新增, API待实现 |
| ReportCenter | — | ⚠️ 骨架 | 设计外新增 |
| RiskManagement | — | ⚠️ 骨架 | 设计外新增 |

前端技术栈: React 18.3.1 + react-router-dom 7.13.2 + Zustand 5.0.12 + @tanstack/react-query 5.95.2 + ECharts 5.6.0 + Recharts 3.8.1 + Tailwind 4.1.3 + socket.io-client 4.8.3 + Vite 6.3.1

---

## 9. 关键文件清单（改代码前必看）

| 你要改什么 | 关键文件 | 注意事项 |
|-----------|---------|---------|
| PT信号逻辑 | `scripts/run_paper_trading.py` (~1126行) | **PT运行期间禁止修改v1.1链路** |
| 信号生成 | `backend/app/services/signal_service.py` | 预处理顺序不可变, 调用FactorNeutralizer |
| 交易执行 | `backend/app/services/execution_service.py` | 信任signal的rebalance标记(LL-005) |
| 风控 | `backend/app/services/risk_control_service.py` | 唯一风控入口, L1-L4状态机 |
| 因子计算 | `backend/engines/factor_engine.py` | Engine=纯计算无IO, direction声明在顶部 |
| 中性化 | `backend/engines/neutralizer.py` | FactorNeutralizer类, 改动影响信号+入库两条链路 |
| 回测 | `backend/engines/backtest_engine.py` | Hybrid架构, 6条可信度硬规则 |
| 滑点模型 | `backend/engines/slippage_model.py` | 三因素模型(base+impact+overnight_gap), R4研究参数 |
| GP引擎 | `backend/engines/mining/gp_engine.py` | DEAP+Warm Start+岛屿模型, FactorDSL算子集 |
| GP管道 | `backend/engines/mining/pipeline_utils.py` | 5个公开函数, Sprint 1.32新增 |
| 因子入库 | `backend/app/services/factor_onboarding.py` | async, 调用FactorNeutralizer, 铁律2 |
| 挖掘任务 | `backend/app/tasks/mining_tasks.py` | import pipeline_utils, DB URL=xin |
| 策略配置 | DB: strategy_configs表 | v1.1配置为权威来源, JSONB版本化 |
| 前端API层 | `frontend/src/api/*.ts` | 必须做响应格式转换+null guard(LL-035) |
| 前端状态 | `frontend/src/store/*.ts` | Zustand 4个store(auth/backtest/mining/notification) |
| 数据库DDL | `docs/QUANTMIND_V2_DDL_FINAL.sql` | 唯一建表来源, 43张表 |

---

## 10. 设计 vs 实际 差异速查

> **编码时以"实际"列为准。** "设计"列是未来目标或已废弃的方案。

| 维度 | 设计文档描述 | 实际实现 | 来源 |
|------|------------|---------|------|
| DB连接 | async asyncpg + async_sessionmaker | **混合**: PT链路用sync psycopg2(db.py), GP/onboarding用async asyncpg | Sprint 1.8a决策 |
| 调度 | Celery Beat全部(8队列) | **Task Scheduler**(PT) + Celery Beat(GP) | R6生产架构 |
| 因子数 | 34+个(8类) | **5 Active** + 19 Reserve | 因子审批限制 |
| 前端页面 | 12个 | **22个**(含6个设计外新增) | Sprint 1.13-1.27 |
| 调度时序 | 06:00-22:00 T1-T17(17步) | **16:30信号/09:00执行** (2步简化版) | PT实际配置 |
| Service层 | async, Depends注入 | **sync**, 部分手动实例化 | Sprint 1.8a |
| AI闭环 | 4 Agent + PipelineOrchestrator | **GP单引擎**, LLM Agent 未实现 | Step 2阶段 |
| 目录结构 | backend/services/ | **backend/app/services/** | 实际代码 |
| 回测引擎 | Rust(A股) + Python(外汇) | **Python only** (Rust版废弃) | Sprint 1.8a |
| 中性化 | 各模块独立实现 | **FactorNeutralizer共享模块** (neutralizer.py) | Sprint 1.32 |
| 日志 | loguru (DEV_BACKEND §8) | **混合**: Service层用`logging`, API路由+pipeline_utils用`structlog` | R6/Sprint 1.15 |
| Broker | BaseBroker抽象+3实现 | **PaperBroker(SimBroker包装) + broker_qmt.py** | Sprint 1.7 |
| Service注入 | FastAPI Depends链 | **部分Depends, 部分手动** | 技术债 |

---

## 11. 已知问题与待修复

| 问题 | 严重程度 | 来源 | 下一步 |
|------|---------|------|--------|
| GP产出0因子 | ⚠️ 中 | population太小+缺pb/circ_mv字段 | 加大参数+补充daily_basic字段 |
| AgentConfig页面404 | ⚠️ 低 | /agent/*路由未实现 | 低优先级 |
| SystemSettings data-sources | ⚠️ 低 | 端点未实现 | 低优先级 |
| WebSocket回测推送 | ⚠️ 中 | 基础设施就绪但引擎端未emit | Sprint 1.13遗留 |
| stores.test.ts TS errors | ⚠️ 低 | pre-existing | 低优先级 |
| ~~api/mock.ts文件残留~~ | ✅ 已清理 | 文件已删除 | — |
| circuit_breaker_state表 | ⚠️ 中 | 设计完成, 是否已建表待核实 | 核对DDL |
| Service注入不统一 | ⚠️ 中 | 部分Depends/部分手动 | 技术债 |

---

## 12. 常见操作指南

### 12.1 运行全部测试
```bash
cd D:\quantmind-v2
pytest backend/tests/ -x -q    # 快速, 失败即停
pytest backend/tests/ -v       # 详细
```

### 12.2 代码检查
```bash
ruff check backend/
ruff format backend/
```

### 12.3 手动触发GP
```bash
celery -A backend.app.tasks.celery_app call backend.app.tasks.mining_tasks.run_gp_evolution
```

### 12.4 查看PT状态
```sql
-- 最近5天NAV
SELECT trade_date, nav, daily_return FROM performance_series 
ORDER BY trade_date DESC LIMIT 5;

-- 当前持仓
SELECT s.ts_code, ps.weight, ps.market_value 
FROM position_snapshot ps JOIN symbols s ON ps.symbol_id = s.id
WHERE ps.snapshot_date = (SELECT MAX(snapshot_date) FROM position_snapshot);
```
