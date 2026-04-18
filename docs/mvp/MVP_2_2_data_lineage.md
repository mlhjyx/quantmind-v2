# MVP 2.2 · Data Lineage (U3) — `data_lineage` 表 + DataPipeline 埋点 + FactorCompute 集成

> **Wave**: 2 第 4 步 (2.1c 进行中时并行, 配合 dual-write 窗口)
> **耗时**: 2 天 (Day 1 ColumnSpec UUID/JSONB 前置 + ADR-0009 + 设计稿 / Day 2 Lineage 表 + 埋点 + FactorCompute 集成 + 查询 API)
> **风险**: 低 (纯新增, 不改老路径 signal/backtest, regression max_diff=0 锁)
> **Scope 原则** (v1.0): 通用 lineage 跨表可用, **复用 `factor_compute_version` (P0-1.5 已存)** 不重建. TEXT[] 不在本 MVP.
> **铁律**: 15 / 17 / 22 / 23 / 24 / 29 / 30 / 36 / 37 / 38 / 40

---

## 目标 (2 项核心 + 1 项前置)

1. **`data_lineage` 通用表 + `Lineage` dataclass** — 跨 factor_values/signals/orders/backtest 统一血缘存储, JSON 可追溯源数据 + git commit + 参数
2. **DataPipeline.ingest 自动埋点** — 每次 ingest 产 lineage_id, 写 data_lineage 行, 返回 id 供调用方写入目标表
3. **前置: ColumnSpec 扩 UUID + JSONB** — MVP 2.1c Sub2 遗留 #3a, data_lineage 表必需, 本 MVP 吸收 (TEXT[] 不做, 留 MVP 3.4)

## 非目标 (明确推后续)

- ❌ **ColumnSpec TEXT[] 扩展** — factor_profile 56 字段 regime_tags 需求, 推 **MVP 3.4 Evaluation Gate 前置**
- ❌ **DataContract/TableContract 架构收敛** — ADR-0009 决议"延迟实施", 触发点: MVP 2.1c Sub3 完结后 (调用点 8→3)
- ❌ **修改老 fetcher 埋点** — 2.1c Sub3 退役, 本 MVP 不碰
- ❌ **lineage 反查 UI / OpenLineage 对接** — B1 Backlog (JIT 触发)
- ❌ **Materialized View / snapshot 血缘** — Wave 3 MVP 3.3 Event Sourcing
- ❌ **signals / orders / backtest_run 表埋点** — 本 MVP 只埋 DataPipeline 通道, signals/orders 走 MVP 3.2, backtest_run 走 MVP 2.3
- ❌ **改 `factor_compute_version`** — P0-1.5 已存, 本 MVP 读用不改写

## 实施结构

```
backend/migrations/
└── data_lineage.sql                         ⭐ NEW 幂等 DDL + rollback 配对

backend/platform/data/
├── interface.py                             ⚠️ MVP 1.1 锁定 (无改动, L13 注释已预埋)
└── lineage.py                               ⭐ NEW ~150 行 Lineage + LineageRef + CodeRef + get_lineage API

backend/app/data_fetcher/
├── contracts.py                             ⚠️ ColumnSpec.dtype docstring 扩 "uuid"/"jsonb"
└── pipeline.py                              ⚠️ 扩 ~80 行 (_validate UUID+JSONB 分支 + _is_null helper + Json wrapper + lineage 埋点 ~30 行)

backend/app/services/
└── factor_compute_service.py                ⚠️ save_daily_factors 调用 write_lineage 接入 (~15 行)

backend/tests/
├── test_pipeline_ext_types.py               ⭐ NEW ~10 tests (UUID + JSONB 逻辑, 不含 TEXT[])
├── test_data_lineage.py                     ⭐ NEW ~12 tests (Lineage dataclass + 查询 API + DataPipeline 埋点)
└── smoke/test_mvp_2_2_lineage_live.py       ⭐ NEW 1 live smoke (随机 factor_value → get_lineage → 含 git commit)

docs/adr/
└── ADR-0009-datacontract-tablecontract-convergence.md  ⭐ NEW (决议-only, 延迟实施)

docs/mvp/
└── MVP_2_2_data_lineage.md                  ⭐ 本文
```

**规模**: ~300 行 Platform + ~80 行 pipeline ext + ~15 行 service + ~280 行 tests + 1 migration + 1 ADR ≈ 780 行

---

## 关键设计

### D1. `data_lineage` 通用表 (Blueprint L996 起源)

```sql
-- backend/migrations/data_lineage.sql (幂等)
CREATE TABLE IF NOT EXISTS data_lineage (
    lineage_id  UUID         PRIMARY KEY,
    lineage_data JSONB        NOT NULL,            -- Lineage dataclass 序列化
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lineage_created_at ON data_lineage (created_at DESC);
-- 跨表查询索引 (按 source table / commit 过滤)
CREATE INDEX IF NOT EXISTS idx_lineage_jsonb_gin ON data_lineage USING GIN (lineage_data);
```

**不在 factor_values 表加列**: 165 GB 主表不动 (P0-1.5 决策一致), 只通过 JSONB `lineage_data.outputs[].table_row_pk` 反向索引.

### D2. `Lineage` dataclass (全 Application 共用)

```python
# backend/platform/data/lineage.py

from dataclasses import dataclass, field, asdict
from datetime import datetime
from uuid import UUID, uuid4

@dataclass(frozen=True)
class LineageRef:
    """单一源数据引用."""
    table: str                         # e.g. "klines_daily"
    pk_values: dict[str, Any]          # {"code": "000001.SZ", "trade_date": "2026-04-18"}
    version_hash: str | None = None    # 源数据 md5 (可选, Wave 3 再落)

@dataclass(frozen=True)
class CodeRef:
    """代码版本引用."""
    git_commit: str                    # 40-char SHA-1 (复用 P0-1.5 pattern)
    module: str                        # e.g. "backend.engines.factor_engine.calculators"
    function: str | None = None        # 具体算子 (e.g. "calc_turnover_mean_20")

@dataclass(frozen=True)
class Lineage:
    """统一血缘记录 (存 data_lineage.lineage_data JSONB)."""
    lineage_id: UUID = field(default_factory=uuid4)
    inputs: list[LineageRef] = field(default_factory=list)
    code: CodeRef | None = None
    params: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    parent_lineage_ids: list[UUID] = field(default_factory=list)  # 链式追溯
    outputs: list[LineageRef] = field(default_factory=list)       # 写入目标

def write_lineage(lineage: Lineage, conn=None) -> UUID:
    """落 data_lineage 表, 返回 lineage_id."""
    ...

def get_lineage(lineage_id: UUID, conn=None) -> Lineage | None:
    """反序列化 JSONB → Lineage."""
    ...

def get_lineage_for_row(table: str, pk: dict, conn=None) -> list[Lineage]:
    """通过 outputs 反查写入此行的所有 lineage."""
    ...
```

### D3. ColumnSpec UUID + JSONB 前置 (吸收 Sub2 遗留 #3a)

pipeline.py 顶部:
```python
import uuid as _uuid
from psycopg2.extras import execute_values, Json, register_uuid
register_uuid()  # 幂等模块级
```

`_validate` 扩 2 分支 (`"uuid"` / `"jsonb"`), **不含 `"text_array"`** (留 MVP 3.4).

`_upsert` tuple 构造加 type-aware prepare: `Json(v)` wrap for jsonb, uuid 直通.

`_validate` 末 `valid_df.where(pd.notna, None)` **收紧**到仅 numeric 列 (object 列含 dict/list 会崩 vectorize).

### D4. DataPipeline.ingest 埋点 (核心集成)

`DataPipeline.ingest(df, contract, lineage: Lineage | None = None)` 签名加可选参数:
- 若 lineage is None → 不埋 (backward compat)
- 若 lineage 传入 → 补全 `outputs` (从 df PK + contract.table_name) → 调 `write_lineage(lineage)` → 返 `IngestResult(..., lineage_id=...)`

### D5. FactorCompute 集成 (复用 factor_compute_version)

`save_daily_factors` 内部:
1. 查 `factor_compute_version` 拿 `(factor_name, version, compute_commit)` (P0-1.5 已实现)
2. 构 `Lineage(code=CodeRef(git_commit=compute_commit, module="...", function=f"calc_{factor_name}"), params={"version": N}, inputs=[...源数据 LineageRef])`
3. 调 `pipeline.ingest(df, FACTOR_VALUES, lineage=lineage)`

**不改 factor_compute_version**: 它记录 "哪个版本算的", data_lineage 记录 "哪个具体 run 写的这批行". 两者互补.

### D6. Query API 使用示例

```python
# 用户想问: 这个 factor_value 怎么算出来的?
lineages = get_lineage_for_row("factor_values",
    {"code": "000001.SZ", "trade_date": "2026-04-18", "factor_name": "turnover_mean_20"})
# → Lineage(inputs=[LineageRef(table="klines_daily", pk_values=...)], code=CodeRef(git_commit="abc123...", ...))
```

---

## 验收标准

| # | 项 | 目标 |
|---|---|---|
| 1 | `backend/migrations/data_lineage.sql` + rollback 配对 | ✅ 幂等 |
| 2 | `backend/platform/data/lineage.py` (~150 行) | ✅ 存在 |
| 3 | `backend/app/data_fetcher/pipeline.py` 扩 UUID/JSONB 支持 + 埋点 | ✅ 存在 |
| 4 | `backend/app/services/factor_compute_service.py` 集成 | ✅ 调用 write_lineage |
| 5 | `test_pipeline_ext_types.py` ~10 tests (UUID+JSONB) | ✅ PASS |
| 6 | `test_data_lineage.py` ~12 tests | ✅ PASS |
| 7 | `smoke/test_mvp_2_2_lineage_live.py` 1 live smoke | ✅ PASS, `get_lineage_for_row` 返 Lineage w/ git_commit |
| 8 | `docs/adr/ADR-0009-...md` + register_adrs.py --apply | ✅ adr_records 7 行 (6+1) |
| 9 | MVP 1.1-2.1c 锚点 all tests | ✅ 不回归 |
| 10 | regression_test --years 5 | ✅ max_diff=0.0 Sharpe 0.6095 |
| 11 | ruff check 新代码 | ✅ clean |
| 12 | 全量 pytest fail | ≤ 24 (铁律 40) |
| 13 | smoke 总数 | 25 → 26 (+1 live smoke) |
| 14 | 老代码 `signal_engine.py` / `run_backtest.py` / 老 3 fetcher | ✅ git diff = 0 |

---

## 开工协议 (铁律 36 precondition)

- ✅ `factor_compute_version` 表存在 (P0-1.5 已建, 47 个因子有 v1 records)
- ✅ MVP 1.1 `DataContract` ABC 锁定 (interface.py L13 预埋注释确认 MVP 2.2 触发)
- ✅ MVP 2.1a Cache Coherency 已绿 (lineage 未来可与 cache 协同)
- ✅ `backend/app/data_fetcher/pipeline.py` 369 行稳定, 无 async 改造 (本 MVP 仅扩 sync)
- ✅ `register_adrs.py --apply` 脚本幂等 (ADR-0009 入 adr_records)
- ✅ psycopg2 `register_uuid` / `Json` 模块存在 (stdlib-adjacent, 无新依赖)

---

## 禁做 (铁律)

- ❌ 不改 `factor_values` 表 schema (不加 lineage_id 列, 165 GB 主表不动, 铁律 30 避雷)
- ❌ 不扩 ColumnSpec TEXT[] (留 MVP 3.4 需 factor_profile 时)
- ❌ 不做 DataContract / TableContract 收敛 (ADR-0009 延迟)
- ❌ 不埋点 signals / orders / backtest_run (分别走 MVP 3.2 / 2.3)
- ❌ 不改老 3 fetcher (dual-write 窗口期保护, 2.1c Sub3 处理)
- ❌ 不建 MVP 1.1 `DataContract` 新字段 (ABC 锁定, Wave 3 再评估)

---

## 风险 + 缓解

| R | 描述 | 概率 | 缓解 |
|---|---|---|---|
| R1 | `Json(dict)` wrap 时机错漏 (_validate 保留原 dict, _upsert wrap) | 中 | 明确边界 + unit test cover |
| R2 | `pd.isna(dict)` 在某 pandas 版本 TypeError | 中 | `_is_null` 白名单 isinstance 短路 |
| R3 | `valid_df.where(pd.notna, None)` 全 df vectorize 遇 object 列崩 | 高 | 收紧仅 numeric 列 (D3) |
| R4 | data_lineage 表快速膨胀 (每 ingest 1 行 → 165M factor_values × N run = 超大) | 中 | GIN index + 本 MVP 不启用 backfill, 只对新数据埋点 |
| R5 | factor_compute_version commit hash 与当前 HEAD 不一致 | 低 | 查表取 compute_commit (P0-1.5 已逻辑), 不重新 git describe |
| R6 | Lineage JSONB 结构变更破坏反序列化 | 中 | `lineage_data.schema_version = 1`, dataclass from_dict 提供 upgrader hook |
| R7 | 铁律 40 新增 fail | 低 | 纯新增, 老锚点 pytest 全跑 |

---

## 下一步 (MVP 2.2 后)

- **MVP 2.1c Sub3** (dual-write 2026-04-25 窗口后): 老 3 fetcher 退役 + klines orchestrator + **触发 ADR-0009 收敛实施评估**
- **MVP 2.3 Backtest Parity**: BacktestMode + BacktestRunner + backtest_run DB 表 (此表要用 UUID+JSONB+TEXT[]+DECIMAL[], **届时扩余下 ColumnSpec 类型**)
- **MVP 3.4 Eval Gate**: factor_profile 56 字段 Contract (届时扩 TEXT[])
- **Wave 3 Event Sourcing (MVP 3.3)**: lineage 与 event_log outbox 集成, snapshot 触发 lineage chain 追溯

---

## 变更记录

- 2026-04-18 v1.0 设计稿落盘, 等 plan approval + 实施.
- 2026-04-19 v1.1 **Sub1 + Sub2 已交付** (commits `42fbd1d` + `5ace7df`):
  - Sub1: ColumnSpec 扩 UUID/JSONB + ADR-0009 + 设计稿 (235 行) + 12 unit PASS
  - Sub2: data_lineage 表 (UUID PK + JSONB GIN) + backend/platform/data/lineage.py (236 行
    含 3 dataclass + 3 DB API) + DataPipeline.ingest `lineage` 参数 (向后兼容 13 调用方零改动)
    + factor_compute_service 集成 factor_compute_version 多数票 commit
    + 13 unit + 1 live smoke 全 PASS
  - 硬门: regression max_diff=0 Sharpe=0.6095 / 全量 pytest 2685 pass 24 fail baseline /
    smoke 25 PASS + 2 SKIP / ruff clean
  - Sub3 (本次 commit): CLAUDE.md / handoff / 本变更记录 bump
