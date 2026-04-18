# MVP 2.3 · Backtest Framework + U1 Research-Production Parity

> **Wave**: 2 第 5 步 (Wave 2 收尾, 大块工程)
> **耗时**: 3-4 周 (Blueprint v1.4 L1215 警告"MLOps 圣杯"难度, Uber Michelangelo 季度工程级)
> **依赖**: MVP 2.1 Data Framework ✅ / MVP 2.2 Data Lineage ✅ (新 backtest_run 用 Lineage 追溯) / MVP 1.2 Config ✅
> **风险**: 高 (blast radius 20+ scripts + PT 生产路径). 做不彻底 → Wave 3 Strategy Framework 策略验证全白做
> **Scope 原则**: 同构 + 可复现 + 批量淘汰 (不做 WF 优化算法 / 不做多策略隔离 — 留 MVP 3.1)
> **铁律**: 14 / 15 / 16 / 17 / 18 / 22 / 23 / 24 / 34 / 36 / 37 / 38 / 40

---

## 目标 (3 项)

1. **BacktestRunner 统一入口** — 函数式 `run_hybrid_backtest` / `run_composite_backtest` 收编为 `PlatformBacktestRunner.run(mode, config)` concrete, 20+ scripts/research/*.py 全部迁 SDK
2. **U1 Parity (核心)** — research 脚本 & PT 生产走**同一 SignalPipeline**, 同 config 产出 bit-identical 结果. 消除 Phase 2.1 sim-to-real gap 282% 根因
3. **backtest_run DB 自动记录** — 每次 run 落盘 (config_hash + git_commit + metrics + artifact 路径), 替代散落 JSON. 可按 hash 查重复, 作为 regression_test 新一代锚点

## 非目标 (明确推后续)

- ❌ **多策略隔离** → MVP 3.1 Strategy Framework
- ❌ **Walk-Forward 引擎重写** → 本 MVP 保留 `walk_forward.py` 走 SDK, 不改 WF 算法
- ❌ **GPU 加速回测** → MVP 3.0 Resource Orchestration 后评估
- ❌ **AI 闭环内循环调度** → Wave 3 MVP 3.4 Eval Gate 集成
- ❌ **vectorbt 替代引擎** → vendor eval 已做, 仍自建
- ❌ **实盘执行接入** (真 QMT 下单) → MVP 3.2 Signal & Execution

## 实施结构 (3 Sub-commit, 分批落地)

```
Sub1 (~2 周): Platform concrete + DB 表 + 批 1 script 迁移
├── backend/migrations/
│   ├── backtest_run.sql            ⭐ NEW (UUID PK + JSONB config + TEXT[] + DECIMAL[] metrics)
│   └── backtest_run_rollback.sql   ⭐ NEW 配对
├── backend/app/data_fetcher/contracts.py     ⚠️ ColumnSpec 扩 "text_array" + "decimal_array" (吸收 Sub1 3b/4 遗留)
├── backend/platform/backtest/
│   ├── interface.py                ⚠️ (MVP 1.1 已锁定, 无改动)
│   ├── runner.py                   ⭐ NEW ~200 行 PlatformBacktestRunner(BacktestRunner) + BacktestMode dispatch
│   ├── registry.py                 ⭐ NEW ~150 行 DBBacktestRegistry(BacktestRegistry) + BACKTEST_RUN TableContract
│   └── executor.py                 ⭐ NEW ~80 行 SerialBacktestExecutor(BatchBacktestExecutor)
├── backend/app/services/
│   └── backtest_service.py         ⚠️ ~30 行 重构走 SDK (保留 async 入口)
├── scripts/
│   ├── regression_test.py          ⚠️ 走 BacktestRunner.run(FULL_5Y) (保留 max_diff=0 锚点)
│   └── run_backtest.py             ⚠️ 走 BacktestRunner (命令行入口)
└── backend/tests/
    ├── test_backtest_runner.py          ⭐ NEW ~15 unit
    ├── test_backtest_registry.py        ⭐ NEW ~10 unit
    └── smoke/test_mvp_2_3_backtest_live.py ⭐ NEW 1 live smoke

Sub2 (~1 周): 批 2 script 迁移 + scripts/research/ 20+ 全量迁
├── scripts/research/*.py (20+ 文件)    ⚠️ 全部改调 BacktestRunner.run
└── deprecated 标注 run_hybrid_backtest 直接导入 (保留函数, 仅加 DeprecationWarning)

Sub3 (~1 周): U1 Parity 实盘对齐
├── backend/engines/signal_engine.py     ⚠️ PAPER_TRADING_CONFIG 收编入 StrategyConfig
├── scripts/run_paper_trading.py         ⚠️ 生产入口走 BacktestRunner.run(BacktestMode.LIVE_PT)
├── scripts/parity_check.py              ⭐ NEW 随机抽 1 日, research backtest vs PT signal diff == 0
└── backend/tests/smoke/test_mvp_2_3_parity_live.py ⭐ NEW bit-identical 验证
```

**规模预估**: ~800 行 Platform + ~300 行 contracts/service 扩展 + ~200 行 scripts migration + ~500 行 tests + 1 migration ≈ 1800 行, 3-4 周工程

---

## 关键设计 (D1-D6)

### D1. `BacktestMode` enum (复用 MVP 1.1 `backend.platform._types.BacktestMode`)

```python
class BacktestMode(Enum):
    QUICK_1Y = "quick_1y"     # 1y 简化成本 ~5s (AI 闭环内循环淘汰)
    FULL_5Y  = "full_5y"      # 5y 完整成本 ~30s (regression anchor)
    FULL_12Y = "full_12y"     # 12y 完整 ~4min (WF baseline)
    WF_5FOLD = "wf_5fold"     # 5-fold walk-forward OOS (~10min)
    LIVE_PT  = "live_pt"      # PT 实盘路径 (Sub3 新增, 同一代码, 接 QMT signal stream)
```

### D2. `PlatformBacktestRunner` concrete

```python
class PlatformBacktestRunner(BacktestRunner):
    def __init__(self, registry: BacktestRegistry, dal: DataAccessLayer): ...

    def run(self, mode: BacktestMode, config: BacktestConfig) -> BacktestResult:
        config_hash = _compute_config_hash(config)
        # 查重: 同 config_hash 已有结果 → 返回缓存 (铁律 15 复现)
        cached = self.registry.get_by_hash(config_hash)
        if cached and not mode == BacktestMode.LIVE_PT:
            return cached

        # 载数据 (通过 DAL, 禁裸 SQL)
        price_df = self.dal.read_ohlc(...)
        factor_df = self.dal.read_factor(...)

        # 走既有 engine (不重写计算)
        result = run_hybrid_backtest(
            factor_df=factor_df, price_data=price_df,
            config=_config_to_engine(config, mode),
            ...
        )
        # log 到 backtest_run + data_lineage (MVP 2.2 集成)
        self.registry.log_run(config, result, artifact_paths={...})
        return result
```

**包而不改**: `run_hybrid_backtest` 内部逻辑不动, 仅 wrap 成 OO 接口, 降低 blast radius.

### D3. `backtest_run` DB 表 + TableContract (ColumnSpec 扩 TEXT[] / DECIMAL[])

```sql
-- backend/migrations/backtest_run.sql
CREATE TABLE IF NOT EXISTS backtest_run (
    run_id          UUID         PRIMARY KEY,
    config_hash     VARCHAR(64)  NOT NULL,
    git_commit      VARCHAR(40),
    mode            VARCHAR(16)  NOT NULL,
    config          JSONB        NOT NULL,
    factor_pool     TEXT[]       NOT NULL,         -- 因子列表 (ColumnSpec 扩 text_array)
    metrics         JSONB        NOT NULL,
    extra_decimals  NUMERIC[] ,                    -- 可选扩展指标 (ColumnSpec 扩 decimal_array)
    lineage_id      UUID         REFERENCES data_lineage(lineage_id),  -- MVP 2.2 集成
    started_at      TIMESTAMPTZ  NOT NULL,
    finished_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    artifact_json   JSONB                          -- {nav: "path", holdings: "path", ...}
);

CREATE INDEX idx_backtest_config_hash ON backtest_run (config_hash);
CREATE INDEX idx_backtest_started_at ON backtest_run (started_at DESC);
```

**ColumnSpec 扩 2 类型 (吸收 MVP 2.1c Sub1 3b/4 遗留)**:
- `text_array` → `ColumnSpec("text_array")` 映射 PG `TEXT[]`, 用 `psycopg2.extensions.AsIs` wrap list
- `decimal_array` → 同上映射 `NUMERIC[]`

### D4. U1 Parity 核心 (Sub3)

**问题**: Phase 2.1 val_sharpe=1.26 → 实盘 Sharpe=-0.99, gap 282%.

**根因**: research 脚本用 `factor_df` 直接 groupby 产 signal, PT 用 `signal_engine.SignalComposer` — **两条代码路径, 两个 bug surface**.

**方案**: Sub3 把 `signal_engine.SignalComposer` 提升为 **唯一 SignalPipeline**, research & PT 都调:
```python
# 研究 (BacktestRunner 内部)
pipeline = SignalPipeline.from_config(config)
signals = pipeline.generate(trade_date, data_context)

# PT (run_paper_trading.py)
pipeline = SignalPipeline.from_config(strategy_config)
signals = pipeline.generate(trade_date, data_context)  # 同一 generate 方法
```

**parity_check.py** 随机抽 1 日 (上周三), 两路径产 signal 逐 code 对比, **max |diff| == 0** 硬门.

### D5. `config_hash` 复现锚点 (铁律 15)

```python
def _compute_config_hash(config: BacktestConfig) -> str:
    # 序列化为 sorted JSON (dict 无序 → 保稳定)
    s = json.dumps(asdict(config), sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()
```

`regression_test --years 5` 新流程: 查 `backtest_run WHERE config_hash = <baseline_hash>`, 比对 metrics. Ephemeral NAV parquet 对比退位为 Sub1 双向兼容回退.

### D6. scripts/research/ 批量迁移策略

20+ scripts 按 blast radius 分批:
- **批 1 (Sub1 含)**: regression_test / run_backtest / profile_backtest — 4 最重要
- **批 2 (Sub2)**: wf_*, size_neutral_* 一批 8-10
- **批 3 (Sub2)**: 剩余 strategy_overlay / phase3e_* 等 8-10
- **批 4 (Sub2 末)**: 用 deprecation warning 收尾, 半年过渡期后删除 `run_hybrid_backtest`

每批迁后全量 `pytest -m regression` + `regression_test --years 5 max_diff=0` 硬门.

---

## 验收标准 (Sub1 硬门)

| # | 项 | 目标 |
|---|---|---|
| 1 | `backend/migrations/backtest_run.sql` + rollback | ✅ 幂等 + 10+ 索引 |
| 2 | ColumnSpec 扩 `text_array` + `decimal_array` 类型 | ✅ `_validate` + `_prepare_cell` 各 2 分支 |
| 3 | `PlatformBacktestRunner` 4 Mode (QUICK_1Y/FULL_5Y/FULL_12Y/WF_5FOLD) | ✅ 跑通 |
| 4 | `DBBacktestRegistry` log_run / get_by_hash / list_recent | ✅ 同 hash 走缓存 |
| 5 | `scripts/regression_test.py` 走 SDK + max_diff=0 | ✅ 新老对照一致 |
| 6 | `scripts/run_backtest.py` 走 SDK | ✅ 命令行不破坏 |
| 7 | 15 new unit (runner) + 10 (registry) | ✅ PASS |
| 8 | 1 live smoke (PG backtest_run 真写入 + hash 查回) | ✅ |
| 9 | 全量 pytest fail | ≤ 24 (铁律 40) |
| 10 | regression --years 5 | ✅ max_diff=0 Sharpe=0.6095 |
| 11 | ruff + format | clean |
| 12 | MVP 2.2 Lineage 集成 (backtest_run.lineage_id 非空) | ✅ 随机抽查 |

### Sub2 验收
- 20+ scripts 走 SDK, `grep "run_hybrid_backtest\|run_composite_backtest"` 零直调 (import 除外)
- 每次迁移 regression_test max_diff=0

### Sub3 验收
- `scripts/parity_check.py` 上周 3 个随机交易日, research vs PT signal `max |diff| == 0`
- PT 生产 `run_paper_trading.py` 走 BacktestRunner, 账面 signal 同以前一致
- `test_mvp_2_3_parity_live.py` 1 live smoke PASS

---

## 开工协议 (铁律 36 precondition)

- ✅ MVP 2.1 Data Framework 已交付 (DAL 11 方法)
- ✅ MVP 2.2 Data Lineage 已交付 (data_lineage 表 + write_lineage API)
- ✅ MVP 1.2 Config Management 已交付 (PlatformConfigLoader 可注入 BacktestConfig)
- ✅ MVP 1.1 `backend/platform/backtest/interface.py` abstract 已锁定 (不改签名)
- ✅ 现有 `engines/backtest/runner.py` 稳定, `run_hybrid_backtest` 可 wrap 而非重写
- ⚠️ **新 precondition**: MVP 2.1c Sub3 老 fetcher 退役完成 (避免 dual-write 期间 backtest_run 数据源不确定)

**推荐启动时序**:
1. MVP 2.1c Sub3-prep (扩 3 字段, 已在本 session 做) ✅
2. dual-write 窗口 2026-04-20 ~ 04-25, 每日验证
3. MVP 2.1c Sub3-main (04-25 后删老 fetcher)
4. **MVP 2.3 Sub1 开工** (~2 周)
5. MVP 2.3 Sub2 + Sub3 (~2 周)

---

## 风险 + 缓解

| R | 描述 | 概率 | 缓解 |
|---|---|---|---|
| R1 | U1 Parity 做不彻底 → Wave 3 策略验证白做 | 高 | Sub3 `parity_check.py` bit-identical 硬门 + 每日 PT 收盘自动跑 |
| R2 | 20+ scripts 迁移破坏既有研究结论可复现性 | 高 | Sub2 每批迁后 regression_test max_diff=0, 保留 `run_hybrid_backtest` 半年 Deprecation |
| R3 | `backtest_run` 膨胀 (每次 run 1 行, sweep 可能 1000+) | 中 | config_hash 查重避免重复 run + artifact 压缩 + 季度归档 |
| R4 | ColumnSpec TEXT[]/DECIMAL[] `psycopg2` adapter 边界 | 中 | 先单测 `_validate` + `_prepare_cell`, live smoke 真写 10 行 TEXT[] 覆盖 |
| R5 | Sub3 PT 切换风险 (生产路径变) | 高 | dry-run 1 周 (PT 双路径: 老 signal_engine 下单 + 新 SignalPipeline 仅 log, diff > 0 告警) |
| R6 | WF_5FOLD 耗时爆炸 (~10min × 每次) | 低 | 缓存 config_hash 查重 + 允许 `force=True` 绕过 |
| R7 | 铁律 40 新增 fail | 中 | 每 Sub 提交前全量 pytest, fail > 24 阻断 |

---

## 禁做 (铁律)

- ❌ 不重写 `run_hybrid_backtest` 内部逻辑 (Sub1 只 wrap)
- ❌ 不改 `signal_engine.SignalComposer` 计算语义 (Sub3 只抽接口)
- ❌ 不删除 `run_hybrid_backtest` 本 MVP 内 (Deprecation 半年过渡)
- ❌ 不动 cache/baseline/*.parquet (5yr/12yr 冻结锚点, regression 新路径只是**再加**一层 DB 锚)
- ❌ 不提前做 MVP 3.0 Resource Orchestration (串行执行足够, 过早优化 YAGNI)

---

## 下一步 (MVP 2.3 后)

- **MVP 3.0 Resource Orchestration** (Wave 3): ROF + `@requires_resources`, BacktestExecutor 加 admission control
- **MVP 3.0a PEAD 前置 (并行)**: PIT 修 / PMS v2 / cost H0-v2
- **MVP 3.1 Strategy Framework**: 当前 PT 重构为 S1 MonthlyRanking + 加 S2 PEAD, BacktestRunner 支持 `strategies=[S1, S2]`
- **MVP 3.4 Eval Gate**: EvaluationPipeline 消费 BacktestResult, Verdict 自动判 PASS/FAIL

---

## 变更记录

- 2026-04-18 v1.0 设计稿落盘 (Session 5 末), 等 plan approval + 实施.
  后续 Session 开工先跑 `docs/mvp/MVP_2_3_backtest_parity.md` precondition checklist.
