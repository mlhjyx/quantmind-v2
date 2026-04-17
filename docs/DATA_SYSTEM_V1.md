# QuantMind V2 数据系统标准 v1.0

> **版本**: v1.0 | **日期**: 2026-04-17 | **状态**: ✅ **全部 16 任务实施完成** (P0 6/6 + P1 4/4 + P2 4/4 + Step 1 方向修正 + Step 4 GP 跑中)
> **完成日期**: 2026-04-17 (P0+P1+P2 16/16) + 本文件保留作实现参考 (21 处代码注释引用)
> **后续演进**: 本文档作为 Data Framework 基础, 升级路径见 `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Wave 2 (MVP 2.1 Data Framework + MVP 2.2 Data Lineage)
> **目标**: 统一数据从拉取到使用的全链路治理，消除碎片化数据加载，建立增量+质量+缓存的标准体系
> **范围**: L1 原始表 → L4 分析数据（不含 L5 决策执行，L5 有独立风控治理）
> **适用性**: 覆盖因子/行情/基本面/微结构数据，不覆盖交易订单/持仓

## 0. 核心决策（v1.0 拍板）

| # | 议题 | 选项 | 决策 | 理由 |
|---|------|------|------|------|
| D1 | 因子版本化 | A加列 / B外挂表 | **B外挂表** | 零schema变更，不影响165GB factor_values |
| D2 | 并发度 | A严格串行 / B跨因子并行 / C跨年份并行 | **A严格串行** | 先稳定跑通，P2阶段评估并行收益 |
| D3 | Universe filter | A各自过滤 / B Orchestrator内置 | **B内置** | 一致性保证，避免下游口径漂移 |

---

## 1. 执行摘要

### 1.1 问题
当前数据操作碎片化：至少5条独立读取路径（fast_neutralize / eval_ic / factor_profiler / research scripts / 直接SQL），各自加载行业+市值+价格，重复IO每次30-90s。无增量机制、无输出验证、无checkpoint追踪。结果：6因子中性化需50+分钟，其中IO占90%时间。

### 1.2 目标
建立**统一数据治理层**，使所有数据操作走标准入口：
- 读：`factor_repository` + `FactorCache`（Parquet）
- 写：`DataPipeline.ingest()`（铁律17）
- 编排：`DataOrchestrator`
- 验证：`QualityValidator` 三级
- 增量：`CheckpointTracker`

### 1.3 核心指标
| 指标 | 当前 | 目标 | 验收方式 |
|------|------|------|----------|
| 10因子中性化总耗时 | ~50 min | **< 10 min** | 实测 |
| SELECT单因子全量 | 90s | **< 10s** | EXPLAIN + 实测 |
| 重复数据加载次数 | 每操作1次 | **会话级1次** | 代码审计 |
| 增量处理支持 | 0个asset | **所有L2+** | 跑第二次<30s完成 |
| 自动质量检查 | 0 | **L1+L2+L3** | 定时任务日报 |
| 数据资产注册 | 0 | **20+ 核心表** | DATA_CATALOG.yaml |

### 1.4 不做
- ❌ 引入Dagster/Prefect/Airflow（过度设计）
- ❌ 改 factor_values 主键/分区（165GB重建风险太高）
- ❌ 改 factor_engine/ 纯函数（Phase C 稳定期）
- ❌ L5 决策层数据（有独立治理）
- ❌ 血缘可视化前端（先做后端）

---

## 2. 目标架构

### 2.1 物理分层

```
┌─────────────────────────────────────────────────────────────────┐
│                    Data Consumers (读取方)                       │
│  neutralize / profiler / ic_eval / backtest / signal / research │
└───────────────────┬─────────────────────────────────────────────┘
                    ↓ (统一入口)
┌─────────────────────────────────────────────────────────────────┐
│              DataOrchestrator (编排层)                           │
│  ┌─────────────┐  ┌──────────────────┐  ┌──────────────────┐   │
│  │SharedDataPool│  │CheckpointTracker │  │QualityValidator  │   │
│  └─────────────┘  └──────────────────┘  └──────────────────┘   │
└───────────────────┬─────────────────────────────────────────────┘
                    ↓
┌──────────────────────────────┬──────────────────────────────────┐
│ FactorCache (读缓存)          │  factor_repository (读入口)      │
│ - Parquet按因子+年分区        │  - load_bulk_data               │
│ - 自动增量刷新                │  - load_shared_context          │
│ - 内存二级缓存                │  - 其他 load_* 函数             │
└──────────────┬───────────────┴──────────────┬──────────────────┘
               ↓                              ↓
┌────────────────────────┐     ┌───────────────────────────────┐
│  Parquet Files         │     │  PostgreSQL + TimescaleDB     │
│  cache/factor_values/  │     │  权威存储                      │
│  cache/backtest/       │     │  + covering indexes           │
└────────────────────────┘     └────────────┬──────────────────┘
                                            ↑
                                   DataPipeline.ingest() (写入口, 铁律17)
                                            ↑
                                   Data Producers (写入方)
                                   factor_compute_service / fetchers / etc.
```

### 2.2 五层数据模型

| 层 | 存储 | 示例 | 更新频率 | 拥有者 |
|----|------|------|----------|--------|
| L0 Sources | 外部 | Tushare/Baostock/QMT | 交易日 | 外部 |
| L1 Raw | DB | klines_daily, minute_bars, daily_basic, moneyflow_daily, symbols | 每交易日 16:15 | data_fetcher |
| L2 Derived | DB(raw_value) + Parquet缓存 | factor_values.raw_value, stock_status_daily | 每交易日 16:30 | factor_compute_service |
| L3 Processed | DB(neutral_value) + Parquet缓存 | factor_values.neutral_value | 每交易日 17:30 | fast_neutralize |
| L4 Analytics | DB | factor_ic_history, factor_profile, backtest_run | 按需/每日 | ic_calculator, profiler |

**铁律**: 下游消费者必须通过 **factor_repository 或 FactorCache** 读取，禁止直连 DB。

### 2.3 数据流程标准（7阶段）

```
PULL (拉取)
  ↓
VALIDATE (Contract schema + 值域)
  ↓
INGEST (DataPipeline.ingest → IngestResult)
  ↓
CACHE (自动追加 FactorCache Parquet)
  ↓
SERVE (通过 factor_repository 统一读取)
  ↓
QUALITY (L1/L2/L3 三级验证)
  ↓
MONITOR (freshness/completeness 定时检查)
```

每阶段**必须输出可观测日志**，格式：`[STAGE][ASSET] rows=X, elapsed=Ys, status=PASS/FAIL`

---

## 3. 技术规范

### 3.1 数据库索引策略

**核心决策：新建 covering index，保留所有旧索引**。

```sql
-- 立即执行（在线建索引，不锁表）
CREATE INDEX CONCURRENTLY idx_fv_factor_date_covering
ON factor_values (factor_name, trade_date)
INCLUDE (raw_value, neutral_value)
WHERE raw_value IS NOT NULL;
```

**为什么 INCLUDE 两个列**:
- Index-only scan 覆盖 neutralize 读 raw、downstream 读 neutral 两种场景
- 磁盘代价：+60GB（D盘796GB空闲充足）

**四个查询模式已覆盖**:
| 模式 | 索引 | 典型查询 |
|------|------|----------|
| 单因子时序 | `(factor_name, trade_date) INCLUDE(raw,neutral)` ⭐NEW | 中性化、画像 |
| 单股时序 | `(code, trade_date)` | PT信号、个股分析 |
| 截面多因子 | `(trade_date, factor_name)` | IC计算、日度信号 |
| 最新N天 | `(trade_date DESC)` | 实时监控 |

### 3.2 Parquet 缓存结构

```
cache/
├── factor_values/              ← NEW (本次建)
│   ├── {factor_name}/
│   │   ├── raw_2019.parquet
│   │   ├── raw_2020.parquet
│   │   ├── ...
│   │   ├── neutral_2019.parquet
│   │   └── neutral_2020.parquet
│   └── _meta.json              ← 版本/最后更新时间
├── backtest/                   ← 已有，保持
│   ├── 2014/{price,factor,benchmark}.parquet
│   └── ...
├── baseline/                   ← 已有，保持
└── minute_bars/                ← 已有，保持
```

**Parquet格式规范**:
- Schema: `(code: str, trade_date: date, value: float64)`（不存factor_name, 文件名即因子名）
- 压缩: `snappy`（读优先）
- 按年分区: 每年一文件，每因子独立
- 存储成本: 每因子每年 ~5-10MB，100因子×7年 ≈ 5GB（磁盘可忽略）

### 3.3 Redis 使用规范

| Key模式 | 用途 | TTL |
|---------|------|-----|
| `market:latest:{code}` | 实时价格 | 90s |
| `portfolio:current` | QMT持仓快照 | 无(60s覆写) |
| `qm:{domain}:{event}` | StreamBus事件 | maxlen=10000 |
| `health:signal_task` | 健康检查阻塞标志 | 24h |
| `checkpoint:{asset}` | 增量处理checkpoint | 30d |

### 3.4 并发访问策略（P0新增）

**基于铁律9（重数据任务max 2并发, PG OOM事件 2026-04-03）与实测内存**:

**并发规则**:
| 操作类型 | 最大并发 | 内存估算 | 执行模式 |
|---------|---------|---------|---------|
| 重数据 Python 进程（加载 factor_values >1M行） | **2** | ~4GB/进程 | 串行或严格限 |
| DataOrchestrator.neutralize（单会话多因子） | **1（串行）** | SharedDataPool ~8GB | D2决策：严格串行 |
| FactorCache refresh（Parquet写入） | **1/因子** | 单文件写锁 | 文件锁保护 |
| DB只读查询 | ≤4 | ~500MB/连接 | 连接池限制 |

**证据**:
- SharedDataPool实测加载：`6,098,863 mv_rows + 5,821 industries (6.8s)` → mv_lookup ~6GB内存（实测日志 2026-04-17 00:01:11）
- PG OOM 2026-04-03 事件（CLAUDE.md铁律9）：2个因子计算进程各4GB同时加载 → PG shared_buffers 2GB 被挤爆
- 当前`fast_neutralize_batch`profile数据（update_db=False, 1月）：SQL 0.958s / merge 0.027s / WLS总 0.037s，计算本身快，IO为瓶颈

**文件锁机制**:
```python
# FactorCache.refresh 内部
import fcntl  # POSIX; Windows 用 msvcrt.locking

lock_file = f"{parquet_path}.lock"
with open(lock_file, "w") as lf:
    try:
        # Windows msvcrt 或 Linux fcntl
        _acquire_exclusive_lock(lf)
        # do refresh
    finally:
        _release_lock(lf)
```

**DB连接池配置**（无需改动，当前已合理）:
- 当前：每个 `get_sync_conn()` 创建新连接，函数结束关闭
- 评估：PT 日常并发 < 4 个脚本，PG默认 max_connections=100 足够
- P2 才评估 pgbouncer

### 3.5 Transaction 边界（P0新增）

**明确事务粒度**:

| 操作 | 事务边界 | 失败隔离 |
|------|---------|---------|
| `DataPipeline.ingest(df, contract)` | 单表单批单事务（已有） | bad rows 拒绝，good rows 提交 |
| `compute_daily_factors` + `save_daily_factors` | 单日单因子集单事务 | 一日失败不影响其他日期 |
| `neutralize_factors(['f1','f2',...])` | **每因子独立事务** | f1 成功 commit 后 f2 失败不回滚 f1 |
| `fast_neutralize_batch(single_factor)` | 已有 `_update_db_neutral_values` 内部按年 commit | 年级粒度隔离 |
| `FactorCache.refresh(factor)` | 写 Parquet 原子性（写 tmp 再 rename） | 损坏自动 fallback DB |

**证据**:
- `fast_neutralize.py:121-164` `_update_db_neutral_values()` 按年分批 commit（已实现）
- `factor_compute_service.save_daily_factors()` 单次 `DataPipeline.ingest()` 一次 commit（已实现）

**失败处理**:
```python
# DataOrchestrator.neutralize_factors 内部（已实现）
for factor_name in factor_names:
    try:
        n_rows = fast_neutralize_batch([factor_name], ...)
        result.stages[factor_name] = StageResult(status="success", ...)
    except Exception as e:
        result.stages[factor_name] = StageResult(status="failed", error=str(e))
        continue  # 不中断其他因子
```
**验证**: `data_orchestrator.py:263-294` 已有此逻辑。

### 3.6 因子版本化与血缘（P0新增 - 决策D1: 外挂表）

**目的**: 满足铁律15（回测可复现），使 `neutral_value` 可追溯到具体计算版本。

**方案**: 零 schema 变更，新建外挂 metadata 表。

**DDL**:
```sql
CREATE TABLE IF NOT EXISTS factor_compute_version (
    factor_name     VARCHAR(60) NOT NULL,
    version         SMALLINT NOT NULL DEFAULT 1,
    compute_commit  VARCHAR(40),        -- git commit hash
    compute_start   DATE NOT NULL,      -- 此版本生效起始交易日
    compute_end     DATE,               -- NULL = 当前生效
    algorithm_desc  TEXT,               -- 人工描述变化内容
    created_at      TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (factor_name, version)
);

CREATE INDEX idx_fcv_factor_active
    ON factor_compute_version (factor_name)
    WHERE compute_end IS NULL;
```

**使用场景**:
1. **因子计算逻辑改变**（如 `high_freq_volatility_20` 公式从 sum(r²) 改为 √sum(r²)）:
   - 在 `factor_compute_version` 插入新版本 (v2, commit=xxx, start=new_start_date)
   - 更新旧版本 `compute_end = new_start_date - 1`
   - 回测时 join 此表获知每段数据用的是哪个算法

2. **因子废弃**:
   - 不删 DB 数据
   - `compute_end` 设为 deprecation date
   - 新算法用新 `factor_name` 避免混淆

**证据**:
- 铁律15（CLAUDE.md §27）: "任何回测结果必须可复现, backtest_run 表已有 (config_yaml_hash, git_commit)"
- 当前痛点: factor_values 只有 code/date/name/value，没有算法版本字段，无法追溯"RSQR_20 NaN事件"类型的历史污染
- 铁律29事件（2026-04-12 RSQR_20 11.5M行NaN未被发现）: 缺版本追踪直接导致事件延迟发现

### 3.7 Universe Filter 标准（P0新增 - 决策D3: 内置）

**目的**: 所有消费者用同一套过滤规则，避免IC计算/回测/中性化口径漂移。

**标准universe定义**（硬编码在 DataOrchestrator）:
```python
class Universe:
    """标准A股universe过滤规则（CLAUDE.md铁律7: 数据地基一致）"""

    EXCLUDE_BOARDS = {"bse"}                 # 排除北交所
    EXCLUDE_ST = True                         # 排除 ST 股票（stock_status_daily.is_st=true）
    EXCLUDE_SUSPENDED = True                  # 排除停牌（is_suspended=true）
    EXCLUDE_NEW_LISTED_DAYS = 60              # 排除上市<60天
    EXCLUDE_LIMIT_UP_DOWN = False             # 涨跌停默认不排除（仅回测时由strategy指定）

    @classmethod
    def get_valid_codes(cls, trade_date: date, conn) -> set[str]:
        """返回当日universe有效的code集合。"""
        cur = conn.cursor()
        cur.execute("""
            SELECT s.code FROM symbols s
            LEFT JOIN stock_status_daily ssd
              ON ssd.code = s.code AND ssd.trade_date = %s
            WHERE s.market = 'astock'
              AND (s.board IS NULL OR s.board NOT IN %s)
              AND (ssd.is_st IS NULL OR ssd.is_st = false)
              AND (ssd.is_suspended IS NULL OR ssd.is_suspended = false)
              AND (s.list_date IS NULL OR s.list_date <= %s::date - INTERVAL %s)
        """, (trade_date, tuple(cls.EXCLUDE_BOARDS), trade_date,
              f"{cls.EXCLUDE_NEW_LISTED_DAYS} days"))
        return {r[0] for r in cur.fetchall()}
```

**证据**:
- CLAUDE.md 策略配置: `排除: 北交所BJ股 + ST + 停牌 + 新股(list<60天)` — 已有规则但散落在各处
- `backend/engines/backtest/validators.py` 已实现但回测专用
- `fast_neutralize._wls_neutralize` 无universe过滤 → 可能用脏数据估计回归系数
- Phase 2.3 市值诊断发现: `无SN=纯微盘91.5%` 就是universe没统一过滤导致

**集成点**:
- `DataOrchestrator.neutralize_factors(..., universe_filter=Universe)` 默认启用
- `DataOrchestrator.compute_ic(..., universe_filter=Universe)` 默认启用
- 研究场景可传 `universe_filter=None` 关闭

### 3.8 命名规范

**表名**: `snake_case`, 复数形式
- 事实表: `klines_daily`, `minute_bars`, `moneyflow_daily`
- 计算表: `factor_values`, `factor_ic_history`
- 状态表: `stock_status_daily`
- 日志表: `backtest_run`, `pipeline_runs`

**列名**: 单位后缀必须
- 价格(元): `close`, `open`, `adj_close`, `vwap`
- 金额(元): `amount`, `total_mv`, `buy_lg_amount`
- 量(手): `volume`
- 比率(无量纲): `turnover_rate`, `pb`, `pe_ttm`, `dv_ttm`
- 日期: `trade_date`, `trade_time`, `created_at`

**索引名**:
- 单实体时序: `idx_{table}_{entity}_date`
- 时序覆盖: `idx_{table}_{cat}_date_covering`
- 截面: `idx_{table}_date_{cat}`

**Parquet文件**: `{factor_name}/raw_{year}.parquet`, `{factor_name}/neutral_{year}.parquet`

---

## 4. 代码架构

### 4.1 模块清单

| 模块 | 路径 | 状态 | 职责 |
|------|------|------|------|
| DataPipeline | `backend/app/data_fetcher/pipeline.py` | ✅ 已有 | 入库管道，Contract校验 |
| Data Contracts | `backend/app/data_fetcher/contracts.py` | ✅ 已有 | Table schema定义 |
| factor_repository | `backend/app/services/factor_repository.py` | ✅ 已有(+load_shared_context本轮新增) | DB读取统一入口 |
| **DataOrchestrator** | `backend/app/services/data_orchestrator.py` | 🔧 本轮部分完成 | 编排层 |
| SharedDataPool | 同上 | 🔧 本轮部分完成 | 会话级共享数据 |
| CheckpointTracker | 同上 | 🔧 本轮部分完成 | 增量追踪 |
| QualityValidator | 同上 | 🔧 本轮需扩展 | 质量验证 |
| **FactorCache** | `backend/data/factor_cache.py` | 🆕 本次新建 | Parquet读缓存 |
| **QualityReporter** | `scripts/data_quality_report.py` | 🆕 本次新建 | 定时质量报告 |

### 4.2 DataOrchestrator 最终接口

```python
class DataOrchestrator:
    """统一数据编排层。"""

    def __init__(self, start_date, end_date, conn=None):
        self._pool = SharedDataPool(start_date, end_date, conn)
        self._cache = FactorCache()
        self._checkpoint = CheckpointTracker(conn)
        self._validator = QualityValidator(conn)

    # --- 读取 ---
    def get_raw_values(self, factor_name, start=None, end=None) -> pd.DataFrame:
        """读 raw_value: 优先Parquet, miss则从DB+自动cache。"""

    def get_neutral_values(self, factor_name, start=None, end=None) -> pd.DataFrame:
        """读 neutral_value: 同上。"""

    @property
    def shared_pool(self) -> SharedDataPool: ...

    # --- 处理 ---
    def neutralize_factors(
        self, factor_names: list[str], incremental=True, validate=True
    ) -> PipelineResult:
        """中性化多因子，走共享池+增量+质量。"""

    def compute_ic(
        self, factor_names: list[str], horizon=20, universe_filter=None
    ) -> PipelineResult:
        """IC评估，写入 factor_ic_history。"""

    # --- 监控 ---
    def check_freshness(self, asset_names: list[str]) -> dict:
        """检查各 asset 是否满足 freshness SLA。"""

    def run_daily_quality(self) -> dict:
        """日常质量检查（L1+L2+L3），输出报告。"""
```

### 4.3 FactorCache 接口

```python
class FactorCache:
    """Parquet 读缓存，按 {factor}/{column}_{year}.parquet 分区。"""

    CACHE_DIR = Path("cache/factor_values")

    def load(
        self, factor_name: str, column: str = "raw_value",
        start: date = None, end: date = None, conn = None,
    ) -> pd.DataFrame:
        """
        读取因子值。流程:
          1. 确定需要的年份
          2. 对每年检查Parquet是否存在 + 是否最新
          3. 不存在/过期 → 从DB加载+写Parquet
          4. 返回合并DataFrame
        """

    def refresh(self, factor_name: str, conn) -> int:
        """检查DB最新日期 vs Parquet最新日期, 追加增量。"""

    def invalidate(self, factor_name: str, column: str = None):
        """删除Parquet触发下次重建（数据修正后调用）。"""

    def build(self, factor_names: list[str], years: list[int], conn) -> dict:
        """批量从DB构建Parquet（首次初始化/全量重建）。"""

    def stats(self) -> dict:
        """返回所有缓存的因子列表、大小、最后更新时间。"""
```

**缓存一致性策略**:
- 读取时先对比 `SELECT MAX(trade_date) FROM factor_values WHERE factor_name=X` 和 Parquet最后日期
- 差异 > 1天 → 自动refresh
- 完整性: 记录每年的 row_count 到 `_meta.json`, 对比不一致触发重建

### 4.4 QualityValidator 三级扩展

```python
class QualityValidator:
    """三级质量检查。"""

    # L1: 原始数据校验（ingest前）
    def validate_raw_ingest(self, df: pd.DataFrame, contract) -> dict:
        """
        - Schema匹配
        - PK非空
        - 值域合规（close>0, high>=low, volume>=0）
        - 交易日合规（trade_date ∈ trading_calendar）
        """

    # L2: 单asset输出校验
    def validate_factor_raw(self, factor_name: str, sample_dates=None) -> dict:
        """raw_value: NaN率<5%, coverage>90%, 无Inf"""

    def validate_factor_neutral(self, factor_name: str, sample_dates=None) -> dict:
        """neutral_value: NaN率<5%, mean≈0, std∈[0.5,2], |v|<3"""

    # L3: 跨源对账
    def reconcile_row_counts(self, trade_date: date) -> dict:
        """klines_daily vs daily_basic vs moneyflow_daily 行数差异 < 8%"""

    def reconcile_date_alignment(self, tables: list[str]) -> dict:
        """所有交易表的 MAX(trade_date) 应一致"""

    def reconcile_factor_coverage(self, factor_name: str) -> dict:
        """neutral_value 覆盖率 > raw_value 的 95%"""

    # --- 聚合报告 ---
    def daily_report(self, trade_date: date = None) -> dict:
        """汇总所有检查，输出 PASS/WARN/FAIL 报告"""
```

**报告格式**（每日17:40自动触发）:
```json
{
  "trade_date": "2026-04-17",
  "overall": "PASS",
  "l1_ingest": {"klines_daily": "PASS", "daily_basic": "PASS", ...},
  "l2_factor_raw": {"high_freq_volatility_20": "PASS", ...},
  "l2_factor_neutral": {"high_freq_volatility_20": "PASS", ...},
  "l3_reconcile": {
    "row_counts": "PASS",
    "date_alignment": "PASS",
    "factor_coverage": {"high_freq_volatility_20": 0.98, ...}
  },
  "warnings": [],
  "failures": []
}
```

### 4.5 CheckpointTracker 已定义

```python
class CheckpointTracker:
    def get_pending_neutralize_dates(factor_name) -> list[date]: ...  # ✅ 已有
    def get_pending_compute_dates(factor_name) -> list[date]: ...     # 🆕 新增
    def count_neutral_coverage(factor_name) -> dict: ...              # ✅ 已有
    def last_success(asset_name) -> datetime: ...                     # 🆕 新增
    def mark_success(asset_name, trade_date, row_count): ...          # 🆕 新增
```

---

## 5. 实施计划

### 5.1 阶段划分

**阶段 P0**: 立即执行（本次会话内完成）
**阶段 P1**: 完善工具层（下次会话）
**阶段 P2**: 存量迁移（之后）

### 5.2 阶段 P0 — 立即执行（本次）

**目标**: 覆盖index + FactorCache MVP + QualityValidator扩展 + 10因子中性化完成

**任务清单**（按执行顺序）:

**P0-1. 数据库索引**（30-60min 后台）
- [ ] 执行 `CREATE INDEX CONCURRENTLY idx_fv_factor_date_covering ...`
- [ ] 验证 EXPLAIN 使用了新索引
- [ ] 实测单因子SELECT从90s降到<10s
- 回滚: `DROP INDEX CONCURRENTLY idx_fv_factor_date_covering`

**P0-2. FactorCache MVP**（~200行）
- [ ] 新建 `backend/data/factor_cache.py`
- [ ] 实现 `load` / `refresh` / `invalidate` / `build` / `stats`
- [ ] 集成到 `SharedDataPool.get_raw_values()` 和 `get_neutral_values()`

**P0-3. QualityValidator 扩展**（~150行）
- [ ] 新增 `validate_factor_raw` 方法
- [ ] 新增 `reconcile_row_counts`, `reconcile_date_alignment`, `reconcile_factor_coverage`
- [ ] 新增 `daily_report` 聚合方法

**P0-4. DataOrchestrator 完善**（~100行）
- [ ] 新增 `get_raw_values` / `get_neutral_values` 方法
- [ ] 新增 `run_daily_quality` 方法
- [ ] 单元测试

**P0-5. 完成10因子中性化**
- [ ] 用新的 DataOrchestrator 跑剩下6个因子
- [ ] 目标时间: < 10分钟（验证索引+cache有效）
- [ ] 检查 QualityValidator 所有因子PASS

**P0-6. Neutral IC 评估 + 噪声鲁棒性**
- [ ] 跑 neutral IC 评估（铁律19）
- [ ] 跑 G_robust 噪声测试（铁律20）
- [ ] 记录所有10因子 neutral IC 到 factor_ic_history

**验收标准 P0**:
- ✅ covering index建成，单因子SELECT < 10s
- ✅ 10因子都有 neutral_value
- ✅ QualityValidator `daily_report` 跑通
- ✅ 所有新代码有单元测试
- ✅ 16/16 原有测试仍PASS

### 5.3 阶段 P1 — 完善工具层（下次会话）

**目标**: DATA_CATALOG + 自动化监控 + 存量代码部分迁移

**任务清单**:

**P1-1. 数据资产目录**（~1小时）
- [ ] 新建 `docs/DATA_CATALOG.yaml`
- [ ] 登记20+ 核心表（klines_daily, factor_values, ...）
- [ ] 标注 depends_on / downstream / freshness_sla

**P1-2. 定时质量报告**（~150行）
- [ ] 新建 `scripts/data_quality_report.py`
- [ ] 集成到 Celery Beat（每日17:40触发）
- [ ] 失败告警通过 StreamBus

**P1-3. L1 入库 sanity checks**（~100行）
- [ ] 扩展 `DataPipeline` 在 ingest 前做 sanity check
- [ ] 价格合理性、量合理性、日期合理性
- [ ] 超阈值拒绝并记录

**P1-4. 部分存量代码迁移**
- [ ] `eval_minute_ic.py` 改走 DataOrchestrator.compute_ic
- [ ] `factor_profiler` 改走 FactorCache 读 neutral_value
- [ ] 2-3 个 research scripts 改造

**验收标准 P1**:
- ✅ DATA_CATALOG.yaml 完整
- ✅ 每日自动质量报告正常产出
- ✅ L1 sanity checks 覆盖核心表
- ✅ 3个存量代码改造完成

### 5.4 阶段 P2 — 存量迁移（长期）

**目标**: 所有数据读取统一走标准入口

**任务清单**:
- [ ] 剩余 fast_neutralize 调用方迁移
- [ ] 所有 research scripts 改造
- [ ] 直连 SQL 代码审计 + 清理
- [ ] DATA_CATALOG 扩展到所有表

**验收标准 P2**:
- ✅ `grep -rn "SELECT.*FROM factor_values" backend scripts` 无生产代码
- ✅ 所有读取都走 factor_repository 或 FactorCache
- ✅ 代码审计报告：统一化率 > 95%

---

## 6. 迁移指南

### 6.1 现有代码改造清单

**`fast_neutralize_batch` 调用方**（6个, P2处理）:
- [x] DataOrchestrator.neutralize_factors（✅ P0完成）
- [ ] `scripts/compute_factor_phase21.py` （P2）
- [ ] `scripts/research/neutralize_minute_factors.py` （P2，可删除用Orchestrator替代）
- [ ] `scripts/research/phase3b_neutralize_significant.py` （P2）
- [ ] `scripts/research/phase3e_neutralize.py` （P2）
- [ ] `scripts/migrate_neutralize_sw1.py` （历史脚本，标记deprecated）

**独立SQL查询 factor_values 的代码**（9+处）:
- [ ] `backend/engines/factor_profiler.py` L211 / L539 / L891 → 用 FactorCache.load
- [ ] `backend/scripts/compute_factor_ic.py` L239 → 用 FactorCache.load
- [ ] `backend/engines/mining/pipeline_utils.py` L119 → 用 factor_repository
- [ ] `backend/engines/multi_freq_backtest.py` L360 → 用 BacktestDataCache

### 6.2 新代码接入指南

**写新因子研究脚本**:
```python
# 旧方式 ❌
conn = get_sync_conn()
cur.execute("SELECT ... FROM factor_values WHERE factor_name=%s", ...)
# 自己查industry/mv...

# 新方式 ✅
from app.services.data_orchestrator import DataOrchestrator
orch = DataOrchestrator(start, end)
raw_df = orch.get_raw_values("my_factor")  # 走FactorCache
industry_map = orch.shared_pool.industry_map
mv_lookup = orch.shared_pool.market_cap
```

**写新因子入库**:
```python
# 旧方式 ❌
cur.execute("INSERT INTO factor_values ...", records)

# 新方式 ✅
from app.data_fetcher.pipeline import DataPipeline
from app.data_fetcher.contracts import FACTOR_VALUES
pipeline = DataPipeline(conn)
result = pipeline.ingest(df, FACTOR_VALUES)  # 铁律17
# 然后自动触发FactorCache追加（P1实现）
```

---

## 7. 运维手册

### 7.1 日常操作

**每日自动流程**（无需干预）:
```
16:15 数据拉取 (fetch_daily.py) → klines_daily, daily_basic
16:30 因子计算 (factor_compute_service) → factor_values.raw_value + Parquet
16:35 moneyflow 拉取
16:40 data_quality_check (L1 + L3)
17:00 DataOrchestrator.neutralize (增量) → factor_values.neutral_value + Parquet
17:30 factor health check
17:40 daily_quality_report → StreamBus 告警（如有）
```

### 7.2 失败处理与恢复（P0新增）

#### 7.2.1 重试策略

**分类重试规则**:
| 失败类型 | 重试策略 | 最大次数 | 间隔 |
|---------|---------|---------|------|
| DB连接超时 | 指数退避 | 3 | 1s, 2s, 4s |
| SQL 死锁 | 立即重试 | 5 | 100ms |
| Parquet 写失败（临时） | 立即重试 | 2 | 500ms |
| Parquet 读失败（损坏） | 不重试，fallback DB | - | - |
| 外部 API（Tushare等） | 指数退避 | 5 | 1s~30s |
| 计算异常（NaN等） | 不重试，记录后跳过 | - | - |

**实现位置**:
```python
# backend/app/services/db.py 新增 retry decorator
@retry_on_transient(max_attempts=3, backoff="exponential")
def execute_query(...): ...
```

**证据**:
- 当前代码无重试: `fast_neutralize._update_db_neutral_values` 失败直接抛异常
- PT 运行时 DB 瞬时故障会导致整个 pipeline 失败
- Tushare API 已有 retry（`tushare_client.py`），需扩展到 DB 层

#### 7.2.2 数据损坏检测

**Parquet 完整性**:
```python
# FactorCache.load 内部
def _verify_parquet(self, path: Path) -> bool:
    """读取 metadata + row count 对比 _meta.json"""
    try:
        meta = pq.read_metadata(path)
        expected_rows = self._meta.get(path.name, {}).get("row_count")
        if expected_rows and meta.num_rows != expected_rows:
            logger.warning(f"Parquet row count mismatch: {path}")
            return False
        return True
    except Exception as e:
        logger.error(f"Parquet corrupted: {path} - {e}")
        return False
```

**损坏处理流程**:
1. 检测到损坏 → `invalidate()` 删除该文件
2. 下次读取自动 `build_from_db()` 重建
3. 记录事件到 StreamBus `qm:datacache:corruption`

**DB 数据污染检测**（定期巡检）:
```python
# QualityValidator.L3 新增
def detect_anomaly(self, factor_name, trade_date) -> dict:
    """检测单日异常: NaN率突增 / 覆盖率暴跌 / 值域突变"""
    # 对比最近7日基线，> 3σ 告警
```

**证据**:
- RSQR_20 事件（CLAUDE.md 铁律29）: 11.5M行NaN未被发现 → 需要主动检测而非被动发现
- 当前 QualityValidator 只检查单日快照，缺少"相对于历史基线的漂移"检测

#### 7.2.3 恢复流程

**部分失败恢复**:
```
场景: neutralize 10因子，f5 失败
当前行为: f1-f4 commit保留, f5 记录failed, f6-f10 继续尝试
恢复: 单独重跑 f5 → orch.neutralize_factors(['f5'], incremental=True)
  → CheckpointTracker 自动识别 f5 有 raw 无 neutral → 只跑 f5 的增量
```

**完整性检查**（每日17:45）:
```bash
# scripts/data_integrity_check.py （P1 新建）
python scripts/data_integrity_check.py --date today
# 输出:
#   factor_values: 10因子 neutral覆盖率 ≥ 95% ✓
#   Parquet cache: 10/10 文件 CRC pass ✓
#   行数一致性: klines vs daily_basic 差异 0.3% ✓
#   可疑: f7 NaN率 6.2% (基线 3.1%) → WARN
```

### 7.3 磁盘监控与清理（P0新增）

#### 7.3.1 磁盘使用阈值

**警戒线**:
| 磁盘 | 总量 | 当前使用 | 警戒 | 熔断 |
|------|------|---------|------|------|
| C: (OS) | 268GB | 212GB (79%) | 85% | 90% |
| D: (DB+cache) | 1073GB | 277GB (26%) | 70% | 85% |

**现状评估**（截至 2026-04-17）:
- DB (PG): 217GB（主要 factor_values 165GB）
- Parquet cache/backtest: ~2GB
- Parquet cache/minute_bars: ~2.8GB
- Parquet cache/factor_values (新建后预计): +5GB

**证据**:
- `shutil.disk_usage('D:/')` 实测: 796GB空闲（2026-04-17）
- `hypertable_size('factor_values')`: 165GB
- `timescaledb_information.chunks`: 151 chunks × ~1GB/chunk

#### 7.3.2 Parquet 清理策略

**FactorCache 清理规则**:
```python
class FactorCache:
    MAX_AGE_DAYS = 1095                    # 3年以上的 Parquet 定期清理
    MAX_TOTAL_SIZE_GB = 20                 # 总大小上限
    PROTECTED_FACTORS = [                  # 永不清理的核心因子
        "turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm",  # CORE3+dv
    ]

    def cleanup(self, dry_run=True) -> dict:
        """按策略清理:
        1. 废弃因子的 Parquet（factor_compute_version.compute_end 设置了）
        2. 早于 MAX_AGE_DAYS 的历史年份（除非 PROTECTED）
        3. 超出 MAX_TOTAL_SIZE_GB 时按 last_access 淘汰
        """
```

**DB 层清理**（不频繁）:
- TimescaleDB 压缩策略（P2 评估）: 3年前的 chunk 自动压缩 → 预计省 70%空间
- factor_values.raw_value 废弃后不删，移到 archive schema

#### 7.3.3 监控告警

**每日 18:00 定时任务**（P1 实施）:
```python
# scripts/disk_monitor.py
def check_disk():
    for drive in ['C:', 'D:']:
        free_pct = shutil.disk_usage(drive + '/').free / shutil.disk_usage(drive + '/').total
        if free_pct < 0.15:  # 熔断
            send_alert("CRITICAL", f"{drive} 剩余 {free_pct:.0%}")
        elif free_pct < 0.30:  # 警戒
            send_alert("WARNING", f"{drive} 剩余 {free_pct:.0%}")
```

告警通过 StreamBus `qm:ops:disk_warning` 广播。

### 7.4 常见故障排查

**症状: 中性化突然变慢**
1. 检查索引: `EXPLAIN` 确认使用 covering index
2. 检查Parquet: `FactorCache.stats()` 看缓存是否被invalidate
3. 检查DB: `pg_stat_activity` 有无锁

**症状: IC 结果漂移**
1. 检查 `factor_ic_history` 最近入库记录
2. 对比 FactorCache vs DB 是否一致 (`reconcile_factor_coverage`)
3. 检查 neutralize 的 validate 报告

**症状: 数据不新**
1. `DataOrchestrator.check_freshness` 查所有asset
2. 检查 Celery Beat 运行状态
3. 检查 Redis `checkpoint:*` 键

### 7.5 数据修正流程（backfill）

**场景: 发现某因子历史有bug，需要重算**
```bash
# 1. 在 factor_values 表上 UPDATE 或 DELETE 错误数据
# 2. 失效Parquet缓存
python -c "from backend.data.factor_cache import FactorCache; FactorCache().invalidate('bad_factor')"

# 3. 重新计算（走标准流程）
python scripts/recompute_factor.py --factor bad_factor --start 2021-01-01

# 4. 重新中性化
python -c "
from app.services.data_orchestrator import DataOrchestrator
orch = DataOrchestrator('2021-01-01', '2025-12-31')
orch.neutralize_factors(['bad_factor'], incremental=True, validate=True)
"

# 5. 重新计算IC
# 6. 验证质量报告
```

---

## 8. 附录

### 8.1 DATA_CATALOG.yaml 最小模板（P1落地）

```yaml
version: "1.0"
last_updated: "2026-04-17"

assets:
  - name: klines_daily
    layer: L1
    source: tushare
    pk: [code, trade_date]
    freshness_sla_hours: 18
    size_gb: 4
    ingest: scripts/fetch_daily.py
    downstream: [factor_values, backtest_data_cache]

  - name: daily_basic
    layer: L1
    source: tushare
    pk: [code, trade_date]
    freshness_sla_hours: 18
    downstream: [factor_values, fast_neutralize]

  - name: factor_values_raw
    layer: L2
    parent_table: factor_values
    column: raw_value
    pk: [code, trade_date, factor_name]
    freshness_sla_hours: 18.5
    compute: backend/app/services/factor_compute_service.py
    depends_on: [klines_daily, daily_basic]
    downstream: [factor_values_neutral]
    quality_thresholds:
      max_nan_rate: 0.05

  - name: factor_values_neutral
    layer: L3
    parent_table: factor_values
    column: neutral_value
    pk: [code, trade_date, factor_name]
    freshness_sla_hours: 19
    compute: backend/engines/fast_neutralize.py
    depends_on: [factor_values_raw, symbols.industry_sw1, daily_basic.total_mv]
    downstream: [factor_ic_history, signals, backtest]
    quality_thresholds:
      max_nan_rate: 0.05
      max_mean_drift: 0.1
      std_range: [0.5, 2.0]
      max_extreme_rate: 0.02

  # ... 其他20+资产
```

### 8.2 验收 Checklist（P0 结束时）

- [ ] covering index 已建且被query planner选中
- [ ] `FactorCache` 已实现，测试覆盖 load/refresh/invalidate
- [ ] `QualityValidator` L2 + L3 已实现
- [ ] `DataOrchestrator.get_raw_values/get_neutral_values` 已实现
- [ ] 所有新代码有单元测试，16/16+ 通过
- [ ] 10个minute因子都完成中性化（neutral_value覆盖率 > 95%）
- [ ] neutral IC 评估完成，记录到 factor_ic_history
- [ ] G_robust 噪声测试完成
- [ ] `daily_quality_report` 输出格式正确
- [ ] 原有243个测试全部通过，无回归

### 8.3 回滚方案

**如果 covering index 出问题**:
```sql
DROP INDEX CONCURRENTLY idx_fv_factor_date_covering;
```
零副作用，PG 自动回退到原索引。

**如果 FactorCache 出问题**:
- 删除 `cache/factor_values/` 目录
- 代码 fallback 到 factor_repository 直查 DB（已设计）

**如果 DataOrchestrator 出问题**:
- 老代码路径未动，直接用 `fast_neutralize_batch` 或直接 SQL 即可

---

## 9. 本文档维护

**归属**: `docs/DATA_SYSTEM_V1.md`
**更新触发**:
- 新增数据资产 → 更新附录 8.1
- 新增查询模式 → 更新 3.1
- 新增质量规则 → 更新 4.4
- 版本升级 → 文件名改为 `DATA_SYSTEM_V2.md`，旧版本归档

**审阅周期**: 季度审阅一次，Sprint结束时更新
