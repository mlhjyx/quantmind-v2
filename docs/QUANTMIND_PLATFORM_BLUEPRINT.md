# QuantMind Platform Blueprint (QPB v1.3)

> **本文件**: QuantMind V2 平台化蓝图 — 从"脚本堆"到"Core Platform + Applications"的演进规划
> **创建**: 2026-04-17 v1.0 → v1.1 (+#11 ROF + U6) → v1.2 (4 主决策) → **v1.3 P0 补丁 (依赖循环/event hooks/AI 示例/时间现实化/DR)**
> **作者**: Architect pass (Opus)
> **状态**: 草案 v1.3 (12 Framework + 6 升维 + 15 MVP), 每个 Wave 完成后回填实际产出
> **参考**:
>   - `docs/QUANTMIND_V2_SYSTEM_BLUEPRINT.md` (当前系统设计真相源)
>   - `docs/DEV_AI_EVOLUTION.md` (AI 闭环设计，作为 Platform 的 Application)
>   - `CLAUDE.md` (35 条铁律，本蓝图所有框架必须兑现)

---

## Part 0 · Executive Summary

### 问题识别（3 层根因）

**表层**（可观测的事故）:
- Sharpe 基线从 1.24→0.94→0.53→0.36 漂移 (cache 覆盖无血缘)
- vwap_deviation_20 / reversal_20 / P0 SN 三起 "改一处漏他处" 事故
- Phase 2.1 sim-to-real gap 282% (研究 vs 生产不同构)
- 5 次 ML/portfolio 优化 NO-GO + 1 次微结构 NO-GO (等权单策略触顶)

**中层**（架构缺口）:
- 因子元数据散落 5+ 处，无 SSOT
- 数据拉取/入库/缓存/消费无统一契约
- 策略作为隐式概念，没有一等公民
- 监控 6 个脚本碎片化
- 32 个测试历史债被忽略

**深层**（设计范式缺失）:
- 规则补丁模式（35 条铁律但持续出事故）
- 无研究-生产同构 (Research-Production Parity)
- 无事件溯源 (Event Sourcing)
- 无数据血缘 (Data Lineage)
- 无归因 (Performance Attribution)
- 无 Platform/Application 边界

### 解决策略

**从规则补丁 → 架构改造**:
1. **12 个统一框架**: 把散点组织成契约化 Platform 能力 (含 #11 Resource Orchestration + #12 Backup & DR)
2. **6 个升维原则**: 改变 "系统能力" 本身 (含 U6 Resource Awareness)
3. **Platform/Application 分层**: 让新能力可独立演进不污染生产

### 核心原则

| 原则 | 说明 |
|---|---|
| 契约先于实现 | 每个框架先写 `interface.py` + 单测, 再写实现 (铁律 23 兑现) |
| MVP 优先 | 每个 Framework 先 2 页设计 + 2-3 周落地 (铁律 24 兑现) |
| 禁破坏 PT | 新路径上线前老路径保留, regression_test max_diff=0 (铁律 15) |
| 开源优先 | 自建前先搜开源方案 (铁律 21), 列出 alternatives 对比 |
| 事故爆炸半径局限 | 新零件出 bug 只影响自身, 不污染其他模块 |

---

## Part 1 · Platform/Application 分层总架构

### 架构图

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 4: Applications (可独立演进, 互不影响)                   │
│                                                                │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │
│  │ PaperTrd │  │ GP Mining│  │ Research │  │AI ClosedLp│     │
│  │  (A股)   │  │          │  │          │  │ (V2.1)   │     │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘     │
│  ┌──────────┐  ┌──────────┐                                  │
│  │  Forex   │  │ (Future) │                                  │
│  │ (未来)    │  │          │                                  │
│  └──────────┘  └──────────┘                                  │
│                    ↓ 通过 SDK 调用 (禁止裸访问 Layer 3)            │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│  Layer 3: QuantMind Core Platform (QCP)                       │
│                                                                │
│  Wave 1 (架构基础):                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │
│  │ Factor FW   │  │ Config Mgmt │  │ Knowledge   │           │
│  │ (#2)        │  │ (#8)        │  │ (#10)       │           │
│  └─────────────┘  └─────────────┘  └─────────────┘           │
│                                                                │
│  Wave 2 (数据 + 研究生产打通):                                    │
│  ┌─────────────┐  ┌─────────────┐                            │
│  │ Data FW     │  │ Backtest FW │                            │
│  │ (#1)        │  │ (#5)        │                            │
│  └─────────────┘  └─────────────┘                            │
│                                                                │
│  Wave 3 (资源调度 + 多策略 + 事件驱动):                           │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │
│  │ Resource    │  │ Strategy FW │  │ Signal/Exec │           │
│  │ Orch (#11)  │  │ (#3)        │  │ FW (#6)     │           │
│  └─────────────┘  └─────────────┘  └─────────────┘           │
│  ┌─────────────┐                                              │
│  │ Eval Gate   │                                              │
│  │ FW (#4)     │                                              │
│  └─────────────┘                                              │
│                                                                │
│  Wave 4 (可观测 + 归因 + DR + 生产就绪):                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐           │
│  │Observability│  │ CI/CD + Test│  │ Backup & DR │           │
│  │  (#7)       │  │  (#9)       │  │  (#12) v1.3 │           │
│  └─────────────┘  └─────────────┘  └─────────────┘           │
│                                                                │
│  Cross-cutting (贯穿所有框架的升维能力):                         │
│  💎 Research-Production Parity    (U1, Wave 2)                 │
│  💎 Event Sourcing / Audit Trail  (U2, Wave 3)                 │
│  💎 Data Lineage                  (U3, Wave 2)                 │
│  💎 Platform/Application 分层     (U4, Wave 1 起)              │
│  💎 Performance Attribution       (U5, Wave 4)                 │
│  💎 Resource Awareness            (U6, Wave 3)                 │
│                                                                │
│         ↓ 依赖 Layer 2                                          │
└──────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────┐
│  Layer 2: Infrastructure (不变)                                │
│  PostgreSQL 16 + TimescaleDB / Redis 5 / Celery / Servy       │
│  QMT / Tushare / Baostock / RTX 5070                          │
└──────────────────────────────────────────────────────────────┘
```

### 依赖规则（强制）

```
Application → Platform SDK → Platform internals
                                  ↓
                           Infrastructure

禁止:
❌ Application 直连 PG / Redis / 裸 read_sql
❌ Application 互相 import
❌ Platform 反向依赖 Application
❌ 跨 Framework 互相 import (通过 Event Bus 协作)
```

### Platform SDK 导出面

```python
from quantmind.platform import (
    # Data Framework
    DataSource, DataContract, DataAccessLayer, FactorCache,

    # Factor Framework
    FactorRegistry, FactorOnboardingPipeline, FactorLifecycle,

    # Strategy Framework
    Strategy, StrategyRegistry, CapitalAllocator,

    # Signal/Execution
    SignalPipeline, OrderRouter, ExecutionAudit,

    # Backtest
    BacktestRunner, BacktestMode, BacktestRegistry,

    # Eval
    EvaluationPipeline, Verdict, GateResult,

    # Observability
    MetricExporter, AlertRouter, EventBus,

    # Config
    ConfigSchema, ConfigAuditor, FeatureFlag,

    # Knowledge
    ExperimentRegistry, FailedDirectionDB, ADR,

    # Resource Orchestration (#11) + U6
    ResourceManager, ResourceProfile, Priority,
    requires_resources, AdmissionController, BudgetGuard,

    # Backup & Disaster Recovery (#12, v1.3)
    BackupManager, DisasterRecoveryRunner, BackupResult, RestoreResult,
)
```

---

## Part 2 · 12 Core Frameworks (Platform)

> **格式**: 每个 Framework 1 页，含 (目标 / 接口 / MVP 范围 / 成本 / 依赖 / 成功指标)

### Application Usage Patterns (v1.3 新增, AI Agent/App 调用示例)

> **问题**: 原 Blueprint 多次说 "AI 闭环 V2.1 是 Application 调 Platform SDK", 但无具体代码示例. v1.3 补.

#### Pattern A: 因子研究 Application (AI Agent 或人工研究)
```python
from backend.platform import (
    FactorRegistry, FactorOnboardingPipeline, EvaluationPipeline,
    BacktestRunner, BacktestMode, ExperimentRegistry, requires_resources, Priority,
)

@requires_resources(ram_gb=4, exclusive_pools=["heavy_data"],
                    priority=Priority.RESEARCH_ACTIVE)
def research_new_factor(hypothesis: str, factor_spec: FactorSpec):
    # 1. 查重 (防重复踩坑, 铁律 12 G9 + 知识库)
    similar = ExperimentRegistry().search_similar(hypothesis)
    if similar: return f"已做过类似实验: {similar[0].verdict}"

    # 2. 注册因子 (强制 onboarding, 铁律 17)
    factor_id = FactorRegistry().register(factor_spec)

    # 3. 走 Onboarding 一条龙 (compute + neutralize + IC + G_robust)
    result = FactorOnboardingPipeline().onboard(factor_spec)

    # 4. 评估 Gate (铁律 4/5/12/13/19/20)
    verdict = EvaluationPipeline().evaluate_factor(factor_spec.name)
    if not verdict.passed: return verdict.blockers

    # 5. 快速回测 (U1 Parity 保证同一 SignalPipeline 用在 research/PT)
    bt = BacktestRunner().run(mode=BacktestMode.QUICK_1Y, config={"factors": [factor_spec.name]})

    # 6. 记入实验库 (铁律 38 Blueprint 长期记忆 + 知识沉淀)
    ExperimentRegistry().complete(factor_id, {"bt": bt, "verdict": verdict}, "success")
```

#### Pattern B: AI 闭环 Idea Agent (V2.1 §4.2)
```python
from backend.platform import FactorRegistry, FailedDirectionDB

class IdeaAgent:
    def generate_hypothesis(self, market_context: dict) -> Hypothesis:
        # 先问知识库: 这方向做过吗?
        failed = FailedDirectionDB().check_similar(self.current_direction)
        if failed: return Hypothesis.switch_direction(failed)

        # 基于当前 factor pool + regime 生成
        active_factors = FactorRegistry().get_active()
        return self._llm_generate(active_factors, market_context)
```

#### Pattern C: PaperTrading Application (当前 PT 重构后)
```python
from backend.platform import (
    Strategy, StrategyRegistry, SignalPipeline, OrderRouter,
    EventBus, MetricExporter, ConfigSchema,
)

class MonthlyRankingStrategy(Strategy):
    """S1 策略 (CORE3+dv_ttm), 现 PT 的重构版."""
    strategy_id = "S1_monthly_ranking"
    factor_pool = ["turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm"]
    rebalance_freq = RebalanceFreq.MONTHLY

    def generate_signals(self, ctx: StrategyContext) -> list[Signal]:
        # 读因子值通过 Platform DAL (禁止裸 SQL, 铁律 17)
        signals = SignalPipeline().compose(self.factor_pool, ctx.trade_date)
        # event_bus 预埋 (MVP 3.3 后激活)
        EventBus().publish("signal.generated", {"strategy": self.strategy_id, "count": len(signals)})
        return signals

# 调度 (Task Scheduler / Celery Beat)
def daily_signal_task():
    for strategy in StrategyRegistry().get_live():
        orders = OrderRouter().route(strategy.generate_signals(ctx))
```

#### Pattern D: GP Mining Application (当前 GP, AlphaZero 升级版)
```python
from backend.platform import (
    FactorRegistry, FactorOnboardingPipeline, EvaluationPipeline,
    requires_resources, Priority, ExperimentRegistry,
)

@requires_resources(ram_gb=16, cpu_cores=7, exclusive_pools=["heavy_data"],
                    priority=Priority.GP_MINING)
def gp_weekly_mining():
    # GP 生成候选 → 走统一 Onboarding + Eval 路径
    for candidate in gp_engine.evolve():
        # G9 Gate 去重 (铁律 12), G10 经济机制 (铁律 13)
        if not FactorRegistry().novelty_check(candidate): continue
        result = FactorOnboardingPipeline().onboard(candidate)
        verdict = EvaluationPipeline().evaluate_factor(candidate.name)
        ExperimentRegistry().complete(candidate.id, result, verdict.summary())
```

**这 4 个 Pattern 覆盖**: Research (人工/AI) / AI Agent / PT 生产 / GP 挖掘. 其他 Application (Forex / AI 闭环 Factor/Strategy/Eval Agent) 模式类似, 由对应 MVP 落地时补充示例到各自设计文档.

---

### Framework #1: Data Framework

**目标**: 从源头到消费统一数据契约，消除 "数据改了没人知道" / "缓存过期" / "单位漂移"

**核心接口:**
```python
class DataSource(ABC):
    @abstractmethod
    def fetch(self, contract: DataContract, since: date) -> pd.DataFrame: ...
    @abstractmethod
    def validate(self, df: pd.DataFrame) -> ValidationResult: ...

class DataAccessLayer:
    def read_factor(self, factor: str, start: date, end: date, column: str) -> pd.DataFrame
    def read_ohlc(self, codes: list[str], start: date, end: date) -> pd.DataFrame
    def read_fundamentals(self, codes: list[str], fields: list[str]) -> pd.DataFrame
    # 禁止其他读路径
```

**MVP 范围:**
- 把 Tushare/Baostock/QMT 三个 fetcher 收编到 `DataSource` 实现
- 扩展 `contracts.py` 覆盖全部 10 张生产表
- 把 `FactorCache` 提升为 `DataAccessLayer` 的唯一读入口
- 实现 Cache Coherency Protocol: DB max_date 校对 + TTL + content hash invalidation
- 13 处直连 SQL 全迁 (P2 审计清单)

**成本**: 1.5-2 周 | **依赖**: 无 (基础框架) | **成功指标**: `grep "SELECT.*FROM factor_values"` 产出 ≤ 3 处 (sanctioned) | **关联铁律**: 17/30/31/34

---

### Framework #2: Factor Framework

**目标**: 因子从 idea → active → warning → retired 全生命周期机器可控

**核心接口:**
```python
class FactorRegistry:
    def register(self, name, hypothesis, expression, direction, category, pool) -> UUID
    def get_active(self) -> list[FactorMeta]
    def get_direction(self, name) -> int  # 替代所有 hardcoded dict
    def update_status(self, name, new_status, reason) -> None

class FactorOnboardingPipeline:
    """一条龙: register → compute → neutralize → IC → G_robust → gate"""
    def onboard(self, factor_spec: FactorSpec) -> OnboardResult

class FactorLifecycleMonitor:  # 本轮 MVP A 已落地一半
    def evaluate_all(self) -> list[TransitionDecision]
```

**MVP 范围:**
- 从 `_constants.py` 所有 DIRECTION dict **启动时 load 自 DB**（删除 hardcoded）
- `factor_onboarding` 变**强制路径**: 新因子不 register → DataPipeline 拒写
- 回填 101 因子到 `factor_registry`
- lifecycle monitor 扩展 warning→0.5x 权重联动 (MVP B, 需 WF 验证)

**成本**: 3-5 天（已有 MVP A 基础） | **依赖**: #1 DataFramework | **成功指标**: DB registry = factor_values.DISTINCT | **关联铁律**: 11/12/13/34

---

### Framework #3: Strategy Framework

**目标**: "策略" 成为一等公民，支持 multi-strategy

**核心接口:**
```python
class Strategy(ABC):
    strategy_id: str
    factor_pool: list[str]
    rebalance_freq: RebalanceFreq  # DAILY/WEEKLY/MONTHLY/EVENT
    capital: Decimal
    status: StrategyStatus

    @abstractmethod
    def generate_signals(self, context: StrategyContext) -> list[Signal]: ...

class StrategyRegistry:
    def register(self, strategy: Strategy) -> None
    def get_live(self) -> list[Strategy]

class CapitalAllocator:
    """跨策略 Risk Budgeting"""
    def allocate(self, strategies: list[Strategy], regime: Regime) -> dict[str, Decimal]
```

**MVP 范围:**
- 定义 Strategy 基类 + Registry DB 表
- 当前 PT 重构为 `MonthlyRankingStrategy(factor_pool=CORE3+dv_ttm)`，登记为 S1
- 引入第二个策略候选 (Minute Intraday / PEAD Event-driven, 其一)
- Capital Allocator 先实现等权 (1/N), 后 Risk Budgeting

**成本**: 2-3 周 | **依赖**: #1, #2 | **成功指标**: 两个策略同时跑 PT, 互不干扰 | **关联铁律**: 16/18

---

### Framework #4: Evaluation Gate Framework

**目标**: 因子/策略评估一键化，消除重复实现

**核心接口:**
```python
class EvaluationPipeline:
    def evaluate_factor(self, factor_name: str) -> FactorVerdict:
        # 跑 IC / G_robust / novelty(G9) / economic(G10) / paired_bootstrap
        # 自动 BH-FDR (M 从 factor_test_registry 表读)
        # 返回统一 Verdict 对象

class StrategyEvaluator:
    def evaluate_strategy(self, strategy_id: str, years: int) -> StrategyVerdict
```

**MVP 范围:**
- 把 `batch_gate.py` / `batch_gate_v2.py` / 散落 Gate 逻辑合并为 `EvaluationPipeline`
- 自动 BH-FDR: `factor_test_registry` DB 表追踪 M, 插入新因子自动递增
- VerdictObject 统一 schema: `{p_value, ic_mean, ic_decay, novelty_score, economic_meaning, verdict, blockers}`

**成本**: 1 周 | **依赖**: #1, #2 | **成功指标**: 新因子一命令评估 | **关联铁律**: 5/12/13

---

### Framework #5: Backtest Framework (合入 U1 Research-Production Parity)

**目标**: 同一套 `SignalPipeline` 跑研究和生产，quick/full/batch 三种模式

**核心接口:**
```python
class BacktestRunner:
    def run(self, mode: BacktestMode, config: BacktestConfig) -> BacktestResult
    # modes: QUICK_1Y (simplified cost, ~1s) / FULL_5Y / FULL_12Y / WF_5FOLD

class BacktestRegistry:  # 自动记录
    def log_run(self, config_hash, git_commit, metrics, artifacts) -> BacktestRunID

class BatchBacktestExecutor:
    def run_batch(self, configs: list[BacktestConfig]) -> list[BacktestResult]
    # 串行尊重 32GB 约束
```

**MVP 范围:**
- 引入 `BacktestMode` enum，现有 `run_hybrid_backtest` 改为 `BacktestRunner.run`
- 新增 QUICK_1Y 模式（AI 闭环需要的内循环淘汰）
- `backtest_run` DB 表替代散落 JSON (hash 定位, 可查询)
- 保留 regression_test 锚点 (铁律 15)

**成本**: 1.5-2 周 (含 U1 parity) | **依赖**: #1, #3 | **成功指标**: 研究脚本全部改用 BacktestRunner, 无独立 runner | **关联铁律**: 14/15/16/18

---

### Framework #6: Signal & Execution Framework

**目标**: 唯一信号→订单路径，配置真正 SSOT

**核心接口:**
```python
class SignalPipeline:
    def generate(self, strategy: Strategy, data_context: DataContext) -> list[Signal]
    # offline (回测) / online (PT) 同一个方法

class OrderRouter:
    def route(self, signals: list[Signal], capital_allocation: dict) -> list[Order]

class ExecutionAuditTrail:
    def trace(self, fill_id: str) -> AuditChain
    # fill → order → signal → strategy → factor 反向追溯
```

**MVP 范围:**
- 收编 `PAPER_TRADING_CONFIG` 硬编码 + `pt_live.yaml` → 统一 `StrategyConfig`
- `config_guard` 扩展检查 Strategy SDK 使用的所有参数
- OrderIdempotencyGuard (order_id hash)
- 审计日志走 Event Sourcing (U2 配合)

**成本**: 1-2 周 | **依赖**: #3, #8 | **成功指标**: PT 配置任何改动必须走 Strategy.config, 无绕路 | **关联铁律**: 16/26/32/34

---

### Framework #7: Observability Framework

**目标**: 告别 6 个散点监控 + DingTalk 疲劳, 统一 metric + alert + dashboard

**核心接口:**
```python
class MetricExporter:
    def emit(self, metric: str, value: float, labels: dict) -> None
    # Prometheus exporter endpoint

class AlertRouter:
    def alert(self, severity: Severity, payload: dict) -> None
    # P0 → SMS+DingTalk, P1 → DingTalk, P2 → log
    # 7 天内同 key 自动 dedup

class EventBus:  # 升级自 StreamBus
    def publish(self, event: Event) -> EventID
    def subscribe(self, pattern: str, handler: Callable) -> None
```

**MVP 范围:**
- 装 Prometheus + Grafana (本地, 不暴露外网)
- 6 个监控脚本改为 MetricExporter 上报（保留 backward compat）
- AlertRulesEngine (yaml 驱动): `configs/alert_rules.yaml`
- Dashboard: PT 总览 + 因子健康 + 系统资源

**成本**: 1-2 周 | **依赖**: 无 (可独立做) | **成功指标**: 告警去重率 ≥ 80%, P0 触达 < 30s | **关联铁律**: 28

---

### Framework #8: Config Management Framework

**目标**: env/yaml/code/DB 四套配置统一, precedence 明确

**核心接口:**
```python
class ConfigSchema(BaseModel):  # Pydantic
    # 全部可配置参数在一处声明
    database: DatabaseConfig
    pt: PaperTradingConfig
    gp: GPMiningConfig
    ai_loop: AILoopConfig
    # ...

class ConfigLoader:
    precedence = ["env", "yaml", "code_defaults"]
    def load(self) -> ConfigSchema

class ConfigAuditor:
    def dump_on_startup(self) -> None
    # 启动 dump 全配置 + hash → 审计日志
```

**MVP 范围:**
- Pydantic 统一全部可配置参数（约 150 项）
- `config_guard` 扩展为 Schema 校验（不只是 6 参数）
- FeatureFlag 支持灰度发布
- 每次服务启动 dump config + hash → `logs/config_audit_{date}.json`

**成本**: 3-5 天 | **依赖**: 无 | **成功指标**: 配置不一致启动 RAISE | **关联铁律**: 34

---

### Framework #9: Test & CI/CD Framework

**目标**: 32 个测试历史债止血, 自动 CI, 部署安全

**核心接口:**
```
pre-commit: ruff + pytest fast + config check
CI (GitHub Actions / 本地 Git hook):
  - pytest 全量 (禁止新增 fail)
  - regression_test max_diff=0
  - coverage ≥ 80% (核心路径)
  - ruff check + format
  - 安全扫描 (secret scan)

Deployment:
  - staging 先跑 smoke test
  - 自动 rollback on smoke fail
```

**MVP 范围:**
- 修复 32 个 fail 测试 (S4 audit 列表: F51-F60 DEPRECATED路径)
- 引入 pre-commit hook
- 建立 CI pipeline (本地 pre-push hook 或 GitHub Actions)
- coverage 工具 (pytest-cov) + 核心路径 80% gate
- smoke test suite (回测 1 年 + 信号生成 + PT dry-run)

**成本**: 1-2 周 | **依赖**: 无 | **成功指标**: 0 fail 测试, 部署后自动 smoke | **关联铁律**: 22/25/26/27

---

### Framework #10: Knowledge & Experiment Registry

**目标**: 失败方向机器记忆, 实验自动入库, 防重复踩坑

**核心接口:**
```python
class ExperimentRegistry:  # DB 表 + API
    def start(self, hypothesis: str, config: dict) -> ExperimentID
    def complete(self, exp_id: str, result: dict, verdict: str) -> None
    def search_similar(self, hypothesis: str) -> list[Experiment]

class FailedDirectionDB:
    def add(self, direction: str, evidence: dict) -> None
    def check_similar(self, new_direction: str) -> list[FailedMatch]
    # 新实验前自动 dedup, 避免重跑已证伪方向

class ADRRegistry:
    def record(self, decision: ArchitectureDecision) -> None
    # 类似 Nygard ADR
```

**MVP 范围:**
- `experiments` DB 表: hypothesis / config_hash / metrics / verdict / git_commit
- 改造 CLAUDE.md "已知失败方向" 为 FailedDirectionDB 自动生成
- research-kb 目录升级为 DB-backed + search
- ADR 模板 + 把近期重大决策 (CORE3+dv 切换 / SN b=0.50 / Qlib 路线 C) 补录

**成本**: 1 周 | **依赖**: 无 | **成功指标**: 新实验启动 → 自动 dedup 告警 | **关联铁律**: 22

---

### Framework #11: Resource Orchestration Framework (ROF)

**目标**: 7 类资源统一调度 (CPU/GPU/RAM/DB/API/时间窗口/锁), 替代铁律 9 的人工判断。multi-strategy 上线前必须就位。

**7 类资源:**

| 类 | 实例 | 当前管理 |
|---|---|---|
| 计算 | 12C/24T CPU + 12GB VRAM + 32GB RAM + NVMe IO | 铁律 9 人工 (只覆盖 RAM) |
| DB | PG max_connections=100 + shared_buffers=2GB + 锁 | 凭经验 |
| API 配额 | Tushare rate / QMT 连接 / DingTalk / LLM budget | 重试 + 无上限 |
| 时间窗口 | 盘前/盘中/盘后 + 交易日 + 节假日 | Task Scheduler cron 错开 |
| 人工干预 | L1/L2/L3/L4 审批 QPM + 告警疲劳预算 | 无 |
| 储存 | DB 159GB / Parquet 20GB cap / 日志 | 部分 (FactorCache cap) |
| 并发/锁 | 文件锁 / DDL 锁 / 服务生命周期 | 局部 (FactorCache msvcrt) |

**核心接口:**
```python
from enum import Enum

class Priority(Enum):
    PT_CRITICAL = 1         # 09:31 执行, 不可抢占
    PT_SUPPORT = 2          # 盘前/盘后健康检查
    PRODUCTION_BATCH = 3    # 日度数据 pipeline
    GP_MINING = 5
    RESEARCH_ACTIVE = 7
    RESEARCH_BACKGROUND = 9

@dataclass
class ResourceProfile:
    ram_gb: float
    vram_gb: float = 0
    cpu_cores: int = 1           # 物理核数 (SMT 不额外提供真实并发)
    db_connections: int = 1
    api_quotas: dict[str, int] = field(default_factory=dict)
    exclusive_pools: list[str] = field(default_factory=list)
    time_windows: list[TimeWindow] = field(default_factory=list)
    estimated_duration_sec: int = 60
    priority: Priority = Priority.RESEARCH_ACTIVE

class ResourceManager:
    """全局资源状态 + 准入控制 + 超限防御."""
    def request(self, profile: ResourceProfile, timeout_sec: int = 300) -> Allocation
    def release(self, alloc: Allocation) -> None
    def current_usage(self) -> ResourceSnapshot
    def preempt(self, low_priority_alloc: Allocation, reason: str) -> bool
    def emit_metrics(self) -> None  # Prometheus

# 使用: decorator 风格
@requires_resources(ram_gb=4, cpu_cores=2,
                    exclusive_pools=["heavy_data"],
                    priority=Priority.GP_MINING)
def run_gp_mining(...):
    ...
```

**5 大能力:**
- **Inventory**: 全局资源实时状态 API
- **Admission**: 任务启动前 `can_admit()` 检查, 不足→排队/拒绝
- **Preemption**: 高优抢占低优 (研究让路 PT)
- **Budget Enforcement**: 运行中超限→kill + 告警
- **Graceful Degradation**: OOM 逼近自动降低并发 / 暂停低优任务

**资源池示例 (基于 R9-9900X3D 12C/24T + 32GB + RTX 5070 12GB):**
```yaml
# configs/resource_pools.yaml
pools:
  heavy_data:                     # 替代铁律 9 人工判断
    capacity: 2                   # 最多 2 并发
    per_task_ram_gb: 4
  gpu_exclusive:                  # GPU 独占 (无 MPS/MIG 支持)
    capacity: 1
    vram_gb: 12
  cpu_light:                      # 轻任务池, SMT 可到 20
    capacity: 20
    per_task_ram_gb: 0.5
  cpu_heavy:                      # 重 CPU (回测/GP), 物理核上限
    capacity: 10                  # 留 2 核给 OS + services
    per_task_ram_gb: 3
  db_ddl:                         # DDL 互斥 (ALTER/CREATE INDEX)
    capacity: 1
    time_windows: [["17:00", "09:00"]]   # 禁盘中
  api_tushare:                    # rate limit
    rate_per_min: 500
  api_llm:                        # 月度预算
    budget_usd_per_month: 100

reservations:                     # 时间窗口保留
  - pools: [pt_executor]
    times: [["09:30", "09:40"]]   # PT 执行独占, 其他让路
  - pools: [db_ddl]
    times: [["09:30", "15:10"]]   # 盘中禁 DDL
```

**MVP 范围 (MVP 3.0, 1-2 周):**
- Phase 1: Inventory 观测 (Prometheus metric, 不拦截) — 3 天
- Phase 2: Admission control (单机锁) — 1 周
- Phase 3: Preemption + Budget Enforcement — 1-2 周 (可延后)
- Phase 4: 集成 Celery queue 分层 — 3-5 天

**集成:**
- Celery: `heavy` queue concurrency=2, `light` queue concurrency=20
- Windows Task Scheduler: 入口脚本加 `@requires_resources` gate
- StreamBus: `qm:resource:admitted/rejected/preempted/exhausted`

**开源参考 (铁律 21):**
- Airflow resource pools (借鉴 API 设计)
- Slurm (优先级 + 抢占经验)
- Ray (过重, 不采用)
- asyncio.Semaphore (过简, 只单进程内)

**成本**: 1-2 周 (Phase 1+2) | **依赖**: #7 Observability (metric), #8 Config (pool 定义) | **成功指标**: OOM 事件 0 (6 月内); 铁律 9 从"人工判断"升级为系统强制 | **关联铁律**: 9/18/28/33

---

### Framework #12: Backup & Disaster Recovery (v1.3 新增)

**目标**: 生产数据 (PG 159GB factor_values + klines + ...) 损坏时的恢复能力. 定义 RPO/RTO SLO, 自动备份 + 定期演练.

**问题背景** (v1.3 新增原因):
- 35 条 → 41 条铁律里 **0 条涉及 DR**
- `pg_backup.py` 存在但**调度状态未验证**
- 单机单 PG, 无 replica, 无 offsite
- RPO/RTO 从未定义
- `docs/SOP_DISASTER_RECOVERY.md` (272 行) 未链入 Blueprint, 20+ 天未更新

**核心接口:**
```python
class BackupManager:
    """自动备份 + 验证 + 恢复."""
    def full_backup(self, target: Path) -> BackupResult
    def wal_incremental(self) -> BackupResult
    def restore(self, backup: Path, target_db: str) -> RestoreResult
    def verify_integrity(self, backup: Path) -> VerifyResult
    # 每周 auto: 恢复到 quantmind_v2_test 库 + run regression_test

class DisasterRecoveryRunner:
    """DR 演练编排."""
    def quarterly_drill(self) -> DrillResult
    # 随机杀场景 (数据目录损坏 / PG 进程 kill / disk full), 测 RTO
```

**SLO 定义:**
| 维度 | 目标 |
|---|---|
| RPO (Recovery Point Objective) | ≤ 6h (最近 WAL 增量) |
| RTO (Recovery Time Objective) | ≤ 4h (全量恢复) |
| Backup Frequency | 全量每日 02:00 + WAL 增量 6h |
| Verification Frequency | 每周一次自动恢复 + regression test |
| Offsite Replication | 至少 1 份 (外置 HDD / 云) |
| Drill Frequency | 每季度一次手动演练 |

**MVP 范围 (MVP 4.4):**
- `pg_backup.py` 接入 Task Scheduler, 每日 02:00 全量
- WAL archiving 开启 (PG `archive_mode=on`, `archive_command`)
- 每周恢复验证脚本 `scripts/backup_verify.py`
- Offsite 备份 (外置 HDD 或 S3-compatible)
- Runbook 更新 + 链入 Blueprint
- 首次 DR 演练 (记录 actual RTO)

**Application 使用示例:**
```python
# Celery Beat 自动触发 (不需 Application 手动调)
from backend.platform.backup import BackupManager

mgr = BackupManager()
result = mgr.full_backup(Path("D:/backups/pg_2026_04_17"))
assert result.size_gb > 100  # 159GB 预期
assert mgr.verify_integrity(result.path).passed
```

**成本**: 1-2 周 | **依赖**: 无 (可并行 Wave 4 其他 MVP) | **成功指标**: 随机杀 PG 数据目录, 4h 内恢复完整 | **关联铁律**: 10 (基础设施改动全链路验证), 29 (数据完整性)

---

## Part 3 · 6 升维建议 (Cross-Cutting)

### 💎 U1: Research-Production Parity

**核心**: 同一套 `SignalPipeline` 跑研究和 PT，通过 `mode=offline|online` 切换，内部实现 100% 一致

**关键设计**:
```python
class SignalPipeline:
    def generate(self, context: PipelineContext) -> list[Signal]:
        # 无论 offline / online, 内部实现完全一样
        pass

# Research (offline):
context = OfflineContext(start=date(2014,1,1), end=date(2026,4,1))
pipeline.generate(context)  # 返回历史每个 rebalance date 的 signals

# PT (online):
context = OnlineContext(today=date.today(), universe=load_universe())
pipeline.generate(context)  # 返回今日 signals
```

**解决什么**:
- Phase 2.1 sim-to-real gap 282% 的根因消除
- "研究 PASS / 实盘崩" 的可能性从架构上消除

**落地**: 合并到 Framework #5 Backtest + #6 Signal，不单独做

---

### 💎 U2: Event Sourcing + Audit Trail

**核心**: 所有状态变化是不可变事件流，当前状态 = 事件流折叠

**关键设计**:
```
核心事件 (Redis Streams + PG append-only):
  qm:event:factor:computed
  qm:event:factor:neutralized
  qm:event:signal:generated
  qm:event:order:placed
  qm:event:order:filled
  qm:event:pms:triggered
  qm:event:strategy:activated
  qm:event:factor_registry:transitioned
  qm:event:config:changed

当前状态 = Materialized View (PG 表, 从 event stream 投影)
```

**解决什么**:
- 铁律 15 可复现: 给定 event stream + git commit → bit-for-bit 重放
- Debug: 任意历史时刻重放系统状态
- AI 闭环 V2.1 candidate retry / rollback 天然支持
- 审计/合规一劳永逸

**落地 Wave**: Wave 3 (配合 Strategy Framework + 监控)

---

### 💎 U3: Data Lineage

**核心**: 每个 factor_value / signal / order 携带 `lineage_id`, 可追溯到源数据 + 代码版本 + 参数

**关键设计**:
```python
@dataclass
class Lineage:
    inputs: list[LineageRef]  # [{table, version_hash, row_range}]
    code: CodeRef  # {git_commit, function, module}
    params: dict
    timestamp: datetime
    parent_lineage_ids: list[str]  # 链式追溯

# 每个派生表/因子都记录
CREATE TABLE data_lineage (
    lineage_id UUID PRIMARY KEY,
    lineage_data JSONB,
    created_at TIMESTAMPTZ
);
```

**解决什么**:
- 5yr/12yr baseline drift 发现慢的根因
- 源数据修正 (Tushare 回溯) → 下游自动 stale 标记
- 铁律 15 真正兑现
- 开源参考: OpenLineage / Marquez / DataHub

**落地 Wave**: Wave 2 (配合 Data Framework)

---

### 💎 U4: Platform/Application 分层

**核心**: Platform 提供能力, Applications 消费能力, 禁止跨层裸访问

**关键设计**: (见 Part 1 架构图)

**解决什么**:
- AI 闭环 V2.1 0% 落地的根因: 没有 Platform 边界可依托
- PT 崩不影响 GP / Research / Forex 独立演进
- 测试边界清晰

**落地 Wave**: Wave 1 第 1 件事 (目录重组 + SDK 抽象，贯穿所有后续 Wave)

---

### 💎 U5: Performance Attribution

**核心**: 每日自动产出归因分解，不仅知道赚亏多少，还知道为什么

**关键设计**:
```python
@dataclass
class DailyAttribution:
    by_factor: dict[str, float]    # {turnover: +0.12%, vol: +0.08%, ...}
    by_sector: dict[str, float]    # {electronics: +0.3%, banking: -0.1%, ...}
    by_regime: RegimeInfo           # {detected: low_vol, expected_perf: ...}
    by_cost: dict[str, float]       # {commission: -0.05%, slippage: -0.08%, ...}
    alpha_vs_benchmark: float
    unexplained_residual: float     # 归因残差

# 异常检测:
if residual > threshold: flag("regime shift or model drift")
```

**解决什么**:
- 研究方向自动有焦点（哪个因子真贡献 alpha vs 噪声）
- Regime shift 自动 flag
- 成本 drift 可见（铁律 18 持续监控）

**落地 Wave**: Wave 4 (配合监控 + 知识管理)

---

### 💎 U6: Resource Awareness

**核心**: 所有执行路径声明资源消耗, 系统全局感知 + 准入控制 + 优雅降级

**关键设计**:
```python
# Platform SDK 所有耗资源接口默认含 ResourceProfile
class BacktestRunner:
    def run(self, mode: BacktestMode, config: BacktestConfig,
            profile: ResourceProfile | None = None) -> BacktestResult
    # profile=None 时自动推断: QUICK_1Y → 0.5GB, FULL_12Y → 4GB

class FactorOnboardingPipeline:
    def onboard(self, spec: FactorSpec,
                profile: ResourceProfile | None = None) -> OnboardResult

class ExperimentRegistry:
    def start(self, hypothesis: str, config: dict,
              profile: ResourceProfile | None = None) -> ExperimentID
```

**行为**:
1. 任何进入 Platform 的操作都经过 ResourceManager 准入
2. 资源不足 → 排队 / 拒绝 / 降级 (精确到 MVP 而不是全局停摆)
3. 高优任务可抢占 (PT 执行 09:31 必然拿到资源)
4. 运行中超预算 → kill + 告警 (防失控消耗)

**解决什么**:
- 铁律 9 "人工判断并发数" 升级为代码强制
- 2026-04-03 OOM 类事件可以从架构层避免
- multi-strategy 上线后的资源冲突自动仲裁
- AI 闭环并发跑 N 实验不撞资源

**落地 Wave**: Wave 3 开头 (MVP 3.0, 先于 Strategy Framework 落地)

---

## Part 4 · PR/MVP 拆分 + 推进路径

### 总览时间线

```
Wave 1 (5-7 周): 架构基础
 ├─ MVP 1.1:  Platform 目录重组 + SDK 骨架        (3 天)
 ├─ MVP 1.2:  Config Management (#8)              (3-5 天)
 ├─ MVP 1.2a: DAL Minimal (read-only, Wave 2 前置) (3-5 天)  ← v1.3 新增
 ├─ MVP 1.3:  Factor Framework (#2)               (1.5-2 周, 现实化)
 └─ MVP 1.4:  Knowledge Registry MVP (#10)        (3 天)

Wave 2 (7-9 周): 数据 + 研究生产打通
 ├─ MVP 2.1:  Data Framework (#1) 完整版          (2-3 周, 现实化)
 ├─ MVP 2.2:  Data Lineage (U3)                   (1-1.5 周)
 └─ MVP 2.3:  Backtest Framework + U1 Parity (#5) (3-4 周, 现实化)

Wave 3 (10-13 周): 资源调度 + PEAD 前置 + 多策略 + 事件驱动
 ├─ MVP 3.0:  Resource Orchestration (#11, U6)        (1-2 周) ┐
 ├─ MVP 3.0a: PEAD 前置 (PIT + PMS v2 + cost H0-v2)    (3 周)    ├─ 并行
 ├─ MVP 3.1:  Strategy Framework (#3)                  (3-4 周, 现实化)
 ├─ MVP 3.2:  Signal & Execution (#6) + event hooks    (2 周)
 ├─ MVP 3.3:  Event Sourcing (U2) + outbox/snapshot/ver (3-4 周, 并行)
 └─ MVP 3.4:  Evaluation Gate (#4)                     (1-1.5 周)

Wave 4 (4-6 周): 可观测 + 归因 + DR + 生产就绪
 ├─ MVP 4.1:  Observability (#7)             (1-2 周)
 ├─ MVP 4.2:  Performance Attribution (U5)   (1-2 周)
 ├─ MVP 4.3:  CI/CD (#9)                     (1-2 周, 并行)
 └─ MVP 4.4:  Backup & DR (#12)              (1-2 周, 并行)  ← v1.3 新增

总计: 26-35 周 (6.5-8.75 月)
```

> **v1.3 时间估算改动**: 原 20-26 周过度乐观 (基于 "单个 MVP 3-5 天" 的不现实假设).
> 参考业界 sim-to-real parity 实施 (Uber Michelangelo / Netflix Metaflow) 需数个季度,
> 多策略框架搭建 (Two Sigma / Citadel) 均为季度级工程. 现实化后更可执行.

### MVP 详细定义

每个 MVP 必须满足 (铁律 23/24):
- ≤ 2 页设计文档 (单独存放 `docs/mvp/MVP_*.md`)
- 独立可执行: 不依赖未实现模块
- 验收标准明确 (metric + test)
- 2-3 周内完成
- 不破坏 PT (regression_test PASS)

#### Wave 1 详细

**MVP 1.1: Platform 目录重组 + SDK 骨架**

- **范围**: 创建 `backend/quantmind/platform/` 子包，定义 10 个 Framework 的 `interface.py` (只签名 + docstring)
- **产物**: 空壳 SDK (所有接口抛 `NotImplementedError`)，但导入可用
- **验收**: `from quantmind.platform import *` 成功, mypy 通过
- **不做**: 实际实现, 保留老代码 100% 不动
- **耗时**: 3 天
- **设计文档**: `docs/mvp/MVP_1_1_platform_skeleton.md` (≤ 2 页)

**MVP 1.2: Config Management (#8)**

- **范围**: Pydantic ConfigSchema 统一声明 150 项参数, ConfigLoader 实现 env>yaml>code 优先级, ConfigAuditor 启动 dump
- **产物**: `quantmind.platform.config` 可用, `config_guard` 扩展为 Schema 校验
- **验收**: 启动时 config 不对齐 → RAISE; 审计日志 `logs/config_audit_*.json` 生成
- **耗时**: 3-5 天
- **设计文档**: `docs/mvp/MVP_1_2_config_management.md`

**MVP 1.3: Factor Framework (#2)**

- **范围**: factor_registry 回填 101 因子, _constants.py DIRECTION 启动 load from DB, factor_onboarding 变强制, lifecycle monitor 集成（本轮 MVP A 基础）
- **产物**: `FactorRegistry`, `FactorOnboardingPipeline`, `FactorLifecycleMonitor` 可用
- **验收**: DB registry = factor_values.DISTINCT (101 = 101); 新因子不 register → DataPipeline 拒写
- **耗时**: 1.5-2 周 (v1.3 现实化: 原 3-5 天过度乐观, 实际含 registry 回填 + _constants 改造 + onboarding 强制化 + lifecycle 集成四块)
- **依赖**: MVP 1.2 Config + **MVP 1.2a DAL Minimal** (铁律 17: registry 读 DB 必走 DAL)
- **设计文档**: `docs/mvp/MVP_1_3_factor_framework.md`

**MVP 1.2a: DAL Minimal (v1.3 新增, Wave 1→2 衔接层)**

- **问题**: MVP 1.3 Factor Framework 要回填 101 因子到 `factor_registry`, 要读 `factor_values.DISTINCT` — 但完整 Data Framework (#1) 在 Wave 2. 直接裸 SQL 违反铁律 17. 不提前做 DAL 就会死锁.
- **范围**: 最小 Read-Only DAL:
  - `backend.platform.data.DataAccessLayer` (read_factor / read_ohlc / read_registry)
  - 只读路径, 不含 DataSource / DataContract 抽象 (留给 MVP 2.1)
  - FactorCache 接入 (已有, 不重写)
  - Write 路径继续用现有 `DataPipeline` (不改)
- **产物**: `DataAccessLayer` read API 可用, MVP 1.3 / 1.4 不用裸 SQL
- **验收**: `grep -rn "SELECT.*FROM factor_values" backend/platform/` = 0 (Platform 层内部不许裸 SQL); `read_factor("turnover_mean_20", start, end)` 返回正确
- **耗时**: 3-5 天
- **依赖**: MVP 1.1
- **升级路径**: MVP 2.1 Data Framework 完整版落地后, DAL Minimal 吸收进完整 Framework (API 接口不变, 内部实现扩展)

**MVP 1.4: Knowledge Registry MVP (#10)**

- **范围**: `experiments` DB 表 + API，CLAUDE.md "已知失败方向" 迁移入库，ADR 模板 + 补录 5 个重大决策
- **产物**: `ExperimentRegistry`, `FailedDirectionDB` 可用
- **验收**: 新实验启动 API 调用, 查询过去 3 个月实验 < 1s
- **耗时**: 3 天
- **设计文档**: `docs/mvp/MVP_1_4_knowledge_registry.md`

#### Wave 2 详细

**MVP 2.1: Data Framework (#1) 完整版**

- **范围**: DataSource 抽象 + 3 个实现 (Tushare/Baostock/QMT), DataContract 扩展全 10 表, DataAccessLayer **完整版** (扩展 MVP 1.2a Minimal 版), Cache Coherency Protocol
- **验收**: 13 处直连 SQL 清零, grep 验证; FactorCache 自动失效检测 test PASS
- **耗时**: 2-3 周 (v1.3 现实化: 原 1.5-2 周过度乐观, 含 3 个 fetcher 抽象 + 13 处迁移 + cache coherency 工程复杂度)
- **依赖**: MVP 1.2a DAL Minimal
- **设计文档**: `docs/mvp/MVP_2_1_data_framework.md`

**MVP 2.2: Data Lineage (U3)**

- **范围**: `data_lineage` 表 + Lineage dataclass, DataPipeline.ingest 自动记录, FactorCompute 记录代码版本
- **验收**: 随机 factor_value → 可 JSON 追溯到源数据 + git commit
- **耗时**: 1 周 (配合 2.1)
- **设计文档**: `docs/mvp/MVP_2_2_data_lineage.md`

**MVP 2.3: Backtest Framework + U1 Parity**

- **范围**: BacktestMode enum, BacktestRunner 统一入口, QUICK_1Y 模式新增, backtest_run DB 表自动记录, SignalPipeline offline/online 同构
- **验收**: 研究脚本全部改用 BacktestRunner, regression_test max_diff=0
- **耗时**: 3-4 周 (v1.3 现实化: **sim-to-real parity 是 MLOps 圣杯**, Uber/Airbnb/Netflix 均为季度级工程, 原 1.5-2 周不现实. 单是保证 research/PT 代码 bit-identical 就需要全链路 trace + 校验层)
- **风险**: 此 MVP 是 Phase 2.1 sim-to-real gap 282% 的根因解决方案, 如做不彻底则 Wave 3 策略验证全部白做. 建议分 2 阶段: Phase 1 "同构架构" (2 周) + Phase 2 "实盘锚点对齐" (1-2 周)
- **设计文档**: `docs/mvp/MVP_2_3_backtest_parity.md`

#### Wave 3 详细

**MVP 3.0: Resource Orchestration Framework (#11) + U6 Resource Awareness**

- **范围**: ResourceManager (7 类资源) + `@requires_resources` 装饰器 + `configs/resource_pools.yaml` + 5 预置池 (heavy_data/gpu_exclusive/cpu_light/cpu_heavy/db_ddl) + Admission Control + Prometheus metric exporter
- **Phase 1**: Inventory 观测 (不拦截, 仅上报) — 3 天
- **Phase 2**: Admission control (单机锁, 不足→排队/timeout) — 1 周
- **Phase 3 (可延后)**: Preemption + Budget Enforcement → 1-2 周
- **集成**: Celery `heavy`/`light` queue 分层 + Task Scheduler 入口脚本 gate
- **产物**: `quantmind.platform.resource` 可用, 铁律 9 从"人工"升级"代码强制"
- **验收**: 并发启动 3 个 heavy_data 任务 → 第 3 个排队; 超 ram_gb → kill + 告警; Prometheus `/metrics` 暴露 7 类 pool 状态
- **耗时**: 1-2 周 (Phase 1+2 必做, Phase 3 可 Wave 4 再做)
- **依赖**: #7 Observability (Wave 4 前可先用日志替代 Prometheus), #8 Config
- **设计文档**: `docs/mvp/MVP_3_0_resource_orchestration.md`
- **硬件基础**: R9-9900X3D 12C/24T + RTX 5070 12GB + 32GB DDR5, 见 memory/reference_hardware.md

**MVP 3.1: Strategy Framework (#3)**

- **范围**: Strategy 基类 + Registry, 当前 PT 重构为 S1 MonthlyRanking, 引入 S2 (PEAD Event-driven, v1.2 已决策), CapitalAllocator 等权
- **验收**: PT 跑 S1+S2 两策略同时, 独立 NAV/订单, 互不干扰
- **耗时**: 3-4 周 (v1.3 现实化: 含 strategy isolation / capital allocation / risk isolation / 两策略并跑验证, 原 2-3 周低估)
- **依赖**: MVP 3.0 ROF + MVP 3.0a PEAD 前置 + MVP 2.3 BacktestRunner
- **设计文档**: `docs/mvp/MVP_3_1_strategy_framework.md`

**MVP 3.2: Signal & Execution (#6) + Event Hooks 预埋**

- **范围**: SignalPipeline 收编 hardcoded config, OrderIdempotencyGuard, ExecutionAuditTrail
- **v1.3 新增 Event Hooks 预埋 (避免 MVP 3.3 回来改 3.2)**:
  - 所有写操作 (signal.generated / order.placed / order.filled / order.rejected / pms.triggered)
    必须调用 `event_bus.publish(event_type, payload)` 占位
  - MVP 3.3 前 event_bus 是 no-op 实现 (只 log 不持久化)
  - MVP 3.3 后 event_bus 激活 outbox pattern 写 PG + 发 Redis
- **验收**: 重复下单 test 自动过滤, 任意 fill 可追溯到 signal/strategy/factor; 所有写路径有 event_bus.publish() 调用点 (grep 验证)
- **耗时**: 2 周 (v1.3: 含 event hooks 预埋工作量)
- **依赖**: MVP 3.1 Strategy Framework
- **设计文档**: `docs/mvp/MVP_3_2_signal_execution.md`

**MVP 3.3: Event Sourcing (U2) + outbox/snapshot/versioning**

- **范围**: 9 种核心事件发布方 + 消费方, Materialized View 投影, Event Replay 工具
- **v1.2 决议必配 3 工程组件**:
  - Outbox pattern: 业务写 PG 时同事务写 `event_outbox` 表, 单独 worker 发 Redis + 存 `event_log` PG 表
  - Snapshot policy: 每月每策略 state snapshot, 重放从最近 snapshot 开始
  - Event versioning: 每事件带 `schema_version`, upgrader 至少 N-1 版本向下兼容
- **验收**: 重放过去 30 天事件 → 当前状态 bit-identical; outbox 表 consumer 7 天内清空 (v1.2 副决策 3a)
- **耗时**: 3-4 周 (v1.3 现实化: 3 工程组件齐全, event sourcing 工程复杂度高)
- **依赖**: MVP 3.2 event hooks 已预埋; 与 MVP 3.1 并行可能 (策略层不干扰)
- **设计文档**: `docs/mvp/MVP_3_3_event_sourcing.md`

**MVP 3.4: Evaluation Gate (#4)**

- **范围**: EvaluationPipeline 合并 batch_gate 逻辑, BH-FDR 自动化, VerdictObject schema
- **验收**: 新因子一命令 Verdict 返回, M 自动递增
- **耗时**: 1 周
- **设计文档**: `docs/mvp/MVP_3_4_eval_gate.md`

#### Wave 4 详细

**MVP 4.1: Observability (#7)**

- **范围**: Prometheus + Grafana 装好, 6 监控脚本迁 MetricExporter, AlertRouter yaml 驱动, 告警 dedup
- **验收**: Grafana dashboard 上线, 告警去重率 ≥ 80%
- **耗时**: 1-2 周
- **设计文档**: `docs/mvp/MVP_4_1_observability.md`

**MVP 4.2: Performance Attribution (U5)**

- **范围**: 每日自动产出 DailyAttribution JSON, 按因子/板块/regime/成本拆解, 归因残差异常告警
- **验收**: PT 日报含完整归因, 残差 > 阈值自动 flag
- **耗时**: 1-2 周
- **设计文档**: `docs/mvp/MVP_4_2_attribution.md`

**MVP 4.3: CI/CD (#9) — 3 层防线 (v1.2 决议)**

- **范围**:
  - Layer 1 pre-commit: ruff check + ruff format + 快测 (<30s, 仅改动模块)
  - Layer 2 pre-push: regression_test --years 5 (max_diff=0 硬门)
  - Layer 3 Celery Beat 03:00 daily full pytest (2100 tests), 失败 DingTalk P1 告警, **不 block PT** (v1.2 副决策 4a)
  - 32 fail 测试修复, coverage gate 80%, smoke test suite
- **验收**: git push 自动跑测试, 0 fail, 部署后 smoke PASS, 铁律 40 "测试债务不得增长" 落地
- **耗时**: 1-2 周 (与 4.1 并行)
- **设计文档**: `docs/mvp/MVP_4_3_ci_cd.md`

**MVP 4.4: Backup & Disaster Recovery (Framework #12, v1.3 新增)**

- **问题**: 35 条 → 41 条铁律里 0 条涉及 DR, 159GB DB 若损坏无恢复流程, `pg_backup.py` 存在未验证调度, RPO/RTO 未定义.
- **范围**:
  - **Backup Automation**: `pg_backup.py` 接入 Task Scheduler, 每日 02:00 全量 + 6h WAL 增量
  - **Backup Verification**: 每周自动恢复一次到 `quantmind_v2_test` 库验证完整性
  - **RPO/RTO 定义**: RPO ≤ 6h (WAL), RTO ≤ 4h (全量恢复)
  - **Offsite Replication**: 本地 NVMe → 外置 HDD / 云备份 (至少其一, 防本地灾难)
  - **Runbook**: `docs/SOP_DISASTER_RECOVERY.md` 对照实际流程更新 + 链入 Blueprint
  - **DR Drill**: 每季度一次演练, 确认 RTO 达标
- **产物**: `backend.platform.backup` SDK + 自动化 + Runbook
- **验收**: 随机杀 PG 数据目录, 4h 内恢复完整 (含最近 6h 数据)
- **耗时**: 1-2 周
- **依赖**: 无 (可并行 4.1/4.2/4.3)
- **设计文档**: `docs/mvp/MVP_4_4_backup_dr.md`

### 依赖图

```
MVP 1.1 (Platform Skeleton)
    ├──→ MVP 1.2 (Config) ──┐
    ├──→ MVP 1.3 (Factor) ──┤
    └──→ MVP 1.4 (Knowledge)┤
                             │
                             ↓
                        MVP 2.1 (Data) ──→ MVP 2.2 (Lineage)
                             │                   │
                             ↓                   ↓
                        MVP 2.3 (Backtest + Parity)
                             │
                             ↓
                        MVP 3.1 (Strategy) ──→ MVP 3.2 (Signal/Exec)
                             │                       │
                             ├── MVP 3.3 (Event Sourcing, 并行)
                             │
                             ↓
                        MVP 3.4 (Eval Gate)
                             │
                             ↓
                        MVP 4.1 (Observability) ─┐
                        MVP 4.2 (Attribution) ───┤ 并行
                        MVP 4.3 (CI/CD) ─────────┘
```

---

## Part 5 · 铁律 Mapping

> 每条铁律应有至少一个 Framework 兑现，否则是"纸上规则"

| 铁律 | 兑现 Framework | 兑现机制 |
|---|---|---|
| 1-3 工作原则 | #9 CI/CD + #10 Knowledge | pre-commit 强制 + ADR 记录 |
| 4 生产基线+中性化 | #4 Eval Gate | VerdictObject 必含 neutralized IC |
| 5 paired bootstrap | #4 Eval Gate | Pipeline 自动跑 bootstrap |
| 6 策略匹配 | #3 Strategy Framework | Strategy.freq 强类型声明 |
| 7 数据地基 | #1 Data Framework | DataAccessLayer 禁裸访问 |
| 8 OOS 验证 | #5 Backtest Framework | WF mode 是默认 |
| 9 重数据串行 | #11 ROF (主) + #5 BatchExecutor | ResourceManager `heavy_data` pool capacity=2 强制 + U6 声明式资源需求 |
| 10 全链路验证 | #9 CI/CD smoke test | 部署后自动 smoke |
| 11 IC 入库 | #2 Factor Framework | Onboarding Pipeline 必走 |
| 12 G9 Novelty | #4 Eval Gate | Verdict 含 novelty_score |
| 13 G10 Economic | #2 Factor Registry | hypothesis 字段必填 |
| 14 回测不清洗 | #1 Data Framework | DataPipeline 唯一清洗点 |
| 15 回测可复现 | #5 Backtest Registry + U3 Lineage | config_hash + git_commit 绑定 |
| 16 信号路径唯一 | #6 Signal Framework | SignalPipeline 唯一入口 |
| 17 DataPipeline 入库 | #1 Data Framework | DAL 封装 |
| 18 成本对齐 | #7 Attribution + #4 Eval | 每日成本归因 + 实盘校验 |
| 19 IC 口径统一 | #4 Eval Gate | Pipeline 内置 ic_calculator |
| 20 G_robust | #4 Eval Gate | Pipeline 含 noise robustness |
| 21 开源优先 | #10 ADR | 每个 Framework 设计记录 alternatives |
| 22 文档跟随 | #9 CI/CD + #10 Knowledge | PR 强制更新 doc hash |
| 23 独立可执行 | 全部 MVP | 本 Blueprint 拆分保证 |
| 24 设计≤2页 | 全部 MVP | 本 Blueprint 模板保证 |
| 25-28 CC 执行纪律 | #9 CI/CD | pre-commit + review bot |
| 29 禁 NaN 写 DB | #1 Data Framework | DataPipeline 校验 |
| 30 中性化后重建 cache | #1 Cache Coherency | 自动失效 |
| 31 Engine 纯计算 | 目录重组 + Linter 规则 | import check |
| 32 Service 不 commit | #6 Signal + ADR | 静态扫描规则 |
| 33 禁 silent failure | #7 Observability + linter | fail-loud 包装器 |
| 34 Config SSOT | #8 Config Management | Pydantic Schema |
| 35 Secrets env var | #8 Config + secret scanner | CI 扫描 |

**产出**: 每条铁律从"人工 review" → "自动执行"

---

## Part 6 · 风险 + 回滚

### 主要风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 重构打断 PT | 中 | 高 | 每个 MVP 保留老路径, regression max_diff=0 方可切换 |
| 时间超预算 | 高 | 中 | MVP ≤ 3 周硬门; 每 Wave 结束 retro 调整 |
| 设计过度 | 中 | 中 | ≤ 2 页设计, 代码少于设计的 3x |
| AI 闭环诱惑提前上马 | 中 | 中 | 明确 Wave 3 才动, 之前零实现 |
| 单人 ownership | 高 | 低 | 铁律 22 文档跟随 + 知识库 MVP (1.4) 早启动 |
| PT 配置漂移 | 低 | 高 | Config Management (#8) 第 2 个做 |

### 回滚策略

每个 MVP 必须:
1. 老路径代码保留 (直到下个 Wave 验证稳定)
2. 功能开关 (FeatureFlag) 控制切换
3. 每次 PR 可独立 revert (不 squash commit)
4. regression_test.py 是终极守门人 (max_diff=0)

### 紧急中止

若任何 MVP 完成后:
- PT Sharpe 连续 5 日偏离基线 > 30% → 回滚该 MVP
- regression_test max_diff > 0 → PR 不合入
- 任何生产事故 → 冻结新 MVP, 先根因分析

---

## Part 7 · 成功指标 (Success Metrics)

### Platform 成熟度指标

| 维度 | 当前 | 目标 (4 Wave 完成后) |
|---|---|---|
| SQL 直连 factor_values | 13 处 | 0 处 (全走 DAL) |
| 因子 direction 定义位置 | 5+ 处 | 1 处 (DB registry) |
| 回测可复现性 | 5yr/12yr 锚点 | 任意历史时刻 bit-identical |
| 策略数 | 1 (隐式) | 2+ (显式登记) |
| 测试 fail 数 | 32 | 0 |
| 监控脚本分散 | 6 个 | 统一 Observability |
| 告警去重率 | 无 | ≥ 80% |
| 配置不一致检测 | 6 参数 | 全 Schema |
| 资源冲突管控 | 铁律 9 人工判断 | ROF 代码强制 + 准入控制 |
| OOM 事件 | 历史 1 次 (2026-04-03) | 0 次 (ROF 启用后 6 月内) |
| 可观测资源池数 | 0 | 7 类 (CPU/GPU/RAM/DB/API/时间/锁) |
| AI 闭环 0% 实现 | 0% | SDK 就绪 + 1 个 Agent MVP |

### 业务指标 (不是本 Blueprint 直接目标, 但是验证成效)

| 指标 | 当前 | 平台化后期望 |
|---|---|---|
| 新策略上线耗时 | 2 周 | 2 天 |
| 新因子评估耗时 | 1 天 (手工) | 10 分钟 (自动 Verdict) |
| Sim-to-real gap | 282% (Phase 2.1 实测) | < 20% |
| 重大事故后 RCA 耗时 | 数小时 (查 log) | 10 分钟 (Event replay) |
| 同时运行策略数 | 1 | 3-5 |

---

## Part 8 · Decisions (已决议 2026-04-17)

> **4 主决策 + 4 副决策 已由用户敲定, 不再讨论**. 见 memory/project_platform_decisions.md.

### 主决策

| # | 问题 | **决策** | 理由 |
|---|---|---|---|
| 1 | Platform 包名 | **`backend.platform`** | 不开源, 作 backend/app + backend/engines 平级, 零 import 路径改动, 避免 `quantmind` namespace 引入工程债 |
| 2 | Wave 3 第 2 策略 | **PEAD Event-driven** (+3 周前置) | 正交维度 (基本面+事件), 破 4 因子等权天花板 (Phase 3E-II 证伪). 前置必做: PIT bias 修复 / PMS v2 设计 / cost model H0-v2 验证 |
| 3 | Event Sourcing 存储 | **StreamBus + PG** (配套 3 组件) | 不引 EventStoreDB. **必配**: outbox pattern (事务原子性) + snapshot policy (每月/每策略) + event versioning |
| 4 | CI 平台 | **3 层本地** | Layer 1 pre-commit (ruff + 快测, <30s) / Layer 2 pre-push (regression_test max_diff=0) / Layer 3 每日 03:00 full pytest (Celery Beat). 不引 GitHub Actions |

### 副决策 (因修正引入)

- **1a**: `backend.platform` vs `backend.core` → **`platform`** (明确定位)
- **2a**: PEAD 3 前置项 (PIT/PMS v2/cost) → **并行做**, 不是串行
- **3a**: `event_outbox` 表保留多久 → **7 天** (消费完即清)
- **4a**: Layer 3 full pytest 失败 → **告警但不 block PT** (避免告警→PT停摆死锁)

### 约束 (来自用户)

- **不开源**: 保持私有, 不做 `pip install namespace 化`
- **单机单人**: 不引入多人协作工具 (GitHub Actions / EventStoreDB / Gitea 等一律不装)

### 对其他 Framework 设计的影响

- **Framework #1 Data**: DAL 路径用 `backend.platform.data`
- **Framework #3 Strategy**: 支持 event-driven 策略, 不只 monthly ranking (PEAD 是第一个非-ranking case)
- **Framework #7 Observability**: CI Layer 3 告警走 MetricExporter
- **Framework #9 Test & CI/CD**: 3 层防线规范写入 MVP 4.3

### 新增 MVP (Wave 3 前置)

**MVP 3.0a: PEAD 前置工程 (并行 3 周)**
- PIT bias 修复 (衍生因子 diff/ranking 严格 PIT)
- PMS v2 设计 (event-driven 短持仓兼容规则)
- Cost model H0-v2 (event-driven 专用回测↔实盘对齐)
- 位于 MVP 3.1 Strategy Framework 前置, 与 MVP 3.0 ROF 并行

---

## Part 9 · 迁移原则 (每个 MVP 都必须遵守)

### 新老路径共存期

```
Phase A: 新框架骨架 + 接口 (老代码不动)
Phase B: 新框架实现 (parallel to 老代码)
Phase C: 关键 App 切换到新框架 (PT/GP 之一先切)
Phase D: 全部 App 切换, 老代码标 @deprecated
Phase E: 老代码删除 (至少 2 周稳定期后)
```

### 禁忌

- ❌ Big-bang 切换 (一次性替换, 必崩)
- ❌ 跳过 regression_test (max_diff 验收必做)
- ❌ 在老代码上加临时补丁 (铁律 21: 先看框架是否能承载)
- ❌ 绕过 Framework 裸调用 (违反 Platform/App 边界)

### PR 模板

每个 MVP 拆多 PR, 每 PR 必须:

```markdown
## 所属 MVP
MVP X.Y — <MVP name>

## 范围
- [ ] Platform 骨架 (interface only)
- [ ] Platform 实现
- [ ] Application 迁移
- [ ] 老代码 @deprecated 标记
- [ ] 老代码删除 (通常独立 PR)

## 验收
- [ ] regression_test max_diff=0
- [ ] 单测 coverage ≥ 80% (改动模块)
- [ ] 设计文档 <= 2 页 (`docs/mvp/MVP_X_Y_*.md`)
- [ ] CLAUDE.md / SYSTEM_STATUS.md 同步

## 风险
- 爆炸半径: <指定>
- 回滚路径: <指定>
- 对 PT 影响: None / Low / Medium / High

## 依赖
- 依赖 MVP: <列出>
- 被依赖 MVP: <列出>
```

---

## Part 10 · 下一步行动 (Immediate Actions)

### Session 结束后待办

1. ✅ 本 Blueprint 落盘 (`docs/QUANTMIND_PLATFORM_BLUEPRINT.md`)
2. ⏳ 更新 `CLAUDE.md` 文档查阅索引 (下次 session 或用户确认后)
3. ⏳ 更新 `MEMORY.md` 索引添加 Blueprint 引用
4. ⏳ 更新 `project_sprint_state.md` 标记平台化阶段启动

### GP 完成后的 Wave 1 启动顺序

1. **MVP 1.1** (Platform Skeleton, 3 天)
   - 创建 `backend/quantmind/platform/{data,factor,strategy,signal,backtest,eval,observability,config,ci,knowledge}/interface.py`
   - 全部 `NotImplementedError` 占位
   - `__init__.py` 导出
   - 单测 `test_platform_skeleton.py` 验证 import 通过

2. **MVP 1.2** (Config Management, 3-5 天)
3. **MVP 1.3** (Factor Framework, 3-5 天)
4. **MVP 1.4** (Knowledge Registry, 3 天)

4 个 MVP 完成标志 Wave 1 结束 (约 3-4 周)

### 本 session 可做 (GP 运行期, 不依赖 DB)

- ✅ 本 Blueprint 文档
- 可选: MVP 1.1 的 interface.py 骨架预写 (纯代码, 无 DB)
- 可选: `docs/mvp/` 目录 + 4 个 Wave 1 MVP 设计文档初稿

---

## 附录 A: 与 DEV_AI_EVOLUTION 的关系

DEV_AI_EVOLUTION V2.1 (705 行) 在本 Blueprint 框架下是:
- **Application**, 不是 Platform 特性
- 依赖 Platform 的: #1 Data / #2 Factor / #3 Strategy / #4 Eval / #5 Backtest / #6 Signal
- 4 Agents (Idea/Factor/Strategy/Eval) = Application 内部组件
- Wave 1-4 完成后 AI 闭环落地成本大幅降低 (≈ 不到 2 周可出 MVP)

## 附录 B: 与 SYSTEM_BLUEPRINT 的关系

- `QUANTMIND_V2_SYSTEM_BLUEPRINT.md` = **当前系统真相源** (现状)
- `QUANTMIND_PLATFORM_BLUEPRINT.md` (本文件) = **演进目标** (未来 6 个月)
- 每个 Wave 完成后同步更新 SYSTEM_BLUEPRINT 的相关章节

## 附录 C: 参考架构 (开源方案对比, 铁律 21)

| 领域 | 开源方案 | 是否借鉴 |
|---|---|---|
| Feature Store | Feast / Tecton | 部分 (数据契约) |
| Event Sourcing | EventStoreDB / Axon | API 借鉴, 存储用 PG+Redis |
| Data Lineage | OpenLineage / Marquez / DataHub | 借鉴 schema |
| Workflow | Airflow / Prefect / Dagster | 观望 (Celery 够用) |
| Monitoring | Prometheus + Grafana | 采用 |
| Experiment Tracking | MLflow / W&B | 参考 Registry schema |
| Backtesting | Qlib / vectorbt / zipline | Qlib Alpha158 因子, 其他自建 |
| ADR | Nygard template | 采用 |

---

## 变更记录

- 2026-04-17 v1.0 初稿 (架构 pass, Opus)
- 2026-04-17 v1.1 新增 Framework #11 Resource Orchestration + U6 Resource Awareness + MVP 3.0 (用户提出资源调度盲点, 扩展到 7 类资源)
  - 硬件规格澄清: R9-9900X3D 12C/24T (SMT)
  - Wave 3 从 6-8 周 → 7-9 周
  - 总体 18-23 周 → 19-24 周
  - 铁律 9 从"人工判断"升级为 ROF 代码强制
- 2026-04-17 v1.2 用户决议 4 主 + 4 副 open questions (思维严谨复审后)
  - **Q1 包名**: `quantmind.platform` ❌ → **`backend.platform`** (不开源, 平级 app/engines)
  - **Q2 第 2 策略**: PEAD ✅ 但加 3 周前置 (PIT + PMS v2 + cost H0-v2)
  - **Q3 Event Sourcing**: StreamBus+PG ✅ 配套 outbox + snapshot + versioning
  - **Q4 CI**: 单层 pre-commit ❌ → **3 层防线** (pre-commit + pre-push regression + 每日 full pytest)
  - 新增 MVP 3.0a PEAD 前置 (并行 3 周)
  - Wave 3 从 7-9 周 → 8-10 周
  - 总体 19-24 周 → 20-26 周
  - Part 8 Open Questions → Decisions (已决议)
- 2026-04-17 v1.3 P0 补丁 (用户要求严谨复审: "Blueprint 是给我看的"):
  - **依赖循环**: Wave 1 加 MVP 1.2a DAL Minimal (Factor Framework 不再裸 SQL 违反铁律 17)
  - **MVP 3.2/3.3 耦合**: MVP 3.2 必须预埋 `event_bus.publish()` 占位, MVP 3.3 前 no-op, 避免回头改 3.2
  - **AI Agent SDK 示例**: Part 2 顶部新增 4 Pattern (Research/AI Agent/PT/GP) 代码示例, 原 "AI 闭环是 Application" 从口号变可执行
  - **MVP 时间估算现实化**: MVP 1.3 / 2.1 / 2.3 / 3.1 / 3.3 全部扩展 (参考 Uber/Netflix MLOps 季度级), Wave 3 8-10→10-13 周, Wave 4 3-4→4-6 周
  - **DR 零覆盖**: 新增 **Framework #12 Backup & Disaster Recovery** + MVP 4.4, 定义 RPO≤6h / RTO≤4h / 季度演练
  - Framework 数: 11 → 12, MVP 数: 14 → 16 (含 1.2a / 4.4)
  - 总体 20-26 周 → 26-35 周 (现实化)
  - 配套铁律 v2 (CLAUDE.md 35 → 40 条全局原则) 同步落地

---

**END of QuantMind Platform Blueprint v1.3**

下一个 session 开始前务必读本文件的 Part 0 Executive Summary + Part 4 MVP 拆分。
