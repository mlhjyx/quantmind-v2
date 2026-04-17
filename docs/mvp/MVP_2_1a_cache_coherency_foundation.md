# MVP 2.1a · Data Framework 基础 — Cache Coherency 协议 + DataSource base class + ADR-006

> **Wave**: 2 第 1 步 (MVP 2.1 拆分 1/3, 最小切片)
> **耗时**: 2-3 天 (Day 1 Cache Coherency 协议文档 + validation harness / Day 2 DataSource base class + MVP 1.1 interface 增强 + ADR-006 / Day 3 tests + commit)
> **风险**: 低 (纯文档 + abstract 代码 + ADR, 不改老 fetcher / DAL / 13 处直连 SQL)
> **Scope 修正** (用户批准 D2=(b)): 不补第 10 张 Contract (announcements 留 MVP 3.0a PEAD 前置时补)
> **铁律**: 17 / 22 / 23 / 24 / 30 / 33 / 36 / 37 / 38 / 40

---

## 目标 (最小切片 3 项)

1. **Cache Coherency 协议正式文档化** — 显式契约 (现有 `backend/data/factor_cache.py::_get_cache_max_date` 是隐式协议) + Python dataclass `CacheCoherencyPolicy` + 验收测试
2. **DataSource base class + validation helpers** — `backend/platform/data/base_source.py` 抽 3 fetcher 共同 validation 骨架 (不做 concrete fetcher, 留 MVP 2.1b)
3. **ADR-006 DataSource 重构策略** — 记录 Wave 2 3 fetcher 包装路径 (Tushare 重构 / Baostock / QMT) 决策 + MVP 1.4 Knowledge 立即 use

## 非目标 (明确留后续 sub-MVP)

- ❌ 不建 `announcements` / `financial_ind` 表 (MVP 3.0a PEAD 前置时补)
- ❌ 不补第 10 张 Contract (9 表已覆盖生产 PT)
- ❌ 不实现 3 fetcher concrete (Tushare/Baostock/QMT) — 留 MVP 2.1b (5-7 天)
- ❌ 不扩 DAL 完整版 (读路径扩展) — 留 MVP 2.1c
- ❌ 不迁 16 处直连 SQL — 留 MVP 2.1c (主工程量)
- ❌ 不改 `backend/data/factor_cache.py` 核心逻辑 (仅加协议 wrapper, 内核不动)
- ❌ 不做 pgvector / Redis pub-sub cache invalidation (留 Wave 3 Event Sourcing)

## 实施结构

```
backend/platform/data/
├── interface.py               ⚠️ MVP 1.1 锁定, 本 MVP 不动 ABC 签名
├── base_source.py             ⭐ NEW ~120 行 BaseDataSource + validation helpers
├── cache_coherency.py         ⭐ NEW ~180 行 CacheCoherencyPolicy + MaxDateChecker + TTLGuard
└── access_layer.py            ⚠️ MVP 1.2a, 本 MVP 不动

backend/tests/
├── test_data_base_source.py   ⭐ NEW ~8 tests (validation helpers + ContractViolation 边界)
└── test_cache_coherency.py    ⭐ NEW ~10 tests (max_date 对比 + TTL + policy 组合)

docs/adr/
└── ADR-006-data-framework-3-fetcher-strategy.md  ⭐ NEW

docs/mvp/
└── MVP_2_1a_cache_coherency_foundation.md  ⭐ 本文 (设计稿)
```

**规模**: ~300 Platform 代码 + ~200 测试代码 + 1 ADR (~180 行) ≈ 680 行. 远小于 MVP 1.3c (2085 行) / 1.4 (~4000 行).

---

## 关键设计

### D1. Cache Coherency 协议 (显式契约)

现状: `backend/data/factor_cache.py::_get_cache_max_date` 是**隐式协议** (代码读才知道行为). MVP 2.1a **显式文档化**成 dataclass + 契约接口:

```python
# backend/platform/data/cache_coherency.py

@dataclass(frozen=True)
class CacheCoherencyPolicy:
    """Cache coherency 显式契约. 铁律 30 的工程实现.

    属性:
      db_max_date_check: 每次 read 前对比 DB max_date vs cache max_date
      ttl_seconds: TTL 兜底 (默认 24h, DB 挂 or DataPipeline 未落时保守返 stale)
      content_hash_check: 优化 — 同 max_date 下用内容 hash 检测 (Wave 2+ 可选)
      invalidate_on_write: 是否订阅 DataPipeline write 事件自动失效 (Wave 3 Event Sourcing)
    """
    db_max_date_check: bool = True
    ttl_seconds: int = 86400
    content_hash_check: bool = False
    invalidate_on_write: bool = False


class MaxDateChecker:
    """对比 DB max_date vs cache max_date, 决定 cache 是否 stale."""

    def is_stale(
        self, db_max: date, cache_max: date | None, policy: CacheCoherencyPolicy
    ) -> bool: ...


class TTLGuard:
    """TTL 兜底 — cache 超 ttl_seconds 视为 stale (DB 查询失败时的保守策略)."""

    def is_expired(self, cache_written_at: datetime, policy: CacheCoherencyPolicy) -> bool: ...
```

**锚定铁律 30**: 源数据变更 → 缓存在下一交易日内失效. 本协议确保"下次 read 前必 check"。

### D2. DataSource base class (抽 validation 骨架)

MVP 1.1 `DataSource` ABC 只规定 `fetch` / `validate` 签名. 3 fetcher (Tushare/Baostock/QMT) 的 validation 逻辑 70% 重复 (NaN 比例 / 单位 / 主键唯一 / 值域). 抽 `BaseDataSource`:

```python
# backend/platform/data/base_source.py

class BaseDataSource(DataSource):
    """DataSource 抽象基类 — 提供公共 validation 骨架.

    concrete fetcher (Tushare/Baostock/QMT) 继承本类, 只实现 `_fetch_raw`,
    validate 逻辑由本类的 helpers 处理.
    """

    @abstractmethod
    def _fetch_raw(self, contract: DataContract, since: date) -> pd.DataFrame:
        """子类只实现原始拉取 (未校验)."""

    def fetch(self, contract, since) -> pd.DataFrame:
        """Template method: _fetch_raw → validate → raise if invalid."""
        df = self._fetch_raw(contract, since)
        result = self.validate(df, contract)
        if not result.passed:
            raise ContractViolation(result.issues)
        return df

    def validate(self, df, contract) -> ValidationResult:
        """公共 validation: schema + 单位 + 主键 + NaN 比例 + 值域."""
        issues = []
        issues.extend(self._check_schema(df, contract))
        issues.extend(self._check_primary_key(df, contract))
        issues.extend(self._check_nan_ratio(df, contract))
        issues.extend(self._check_value_ranges(df, contract))
        return ValidationResult(
            passed=len(issues) == 0,
            row_count=len(df),
            issues=issues,
            metadata={"validator": self.__class__.__name__},
        )

    # ---------- Helpers (供 subclass override 扩展) ----------
    def _check_schema(self, df, contract) -> list[str]: ...
    def _check_primary_key(self, df, contract) -> list[str]: ...
    def _check_nan_ratio(self, df, contract, threshold=0.1) -> list[str]: ...
    def _check_value_ranges(self, df, contract) -> list[str]: ...
```

MVP 2.1b 3 concrete fetcher 继承 `BaseDataSource`, 代码量从 `1 × 598 行 + 2 × ~400 行` ≈ 1400 行 → 合约化 ~600 行.

### D3. ADR-006 DataSource 3 fetcher 策略

新 `docs/adr/ADR-006-data-framework-3-fetcher-strategy.md`:

- **Context**: Wave 2 需把现有 3 fetcher (Tushare fetch_base_data.py 598 行 / Baostock fetch_minute_bars.py 280 行 / QMT qmt_data_service.py 274 行) 收编到 DataSource abstract
- **Decision**: 通过 `BaseDataSource` 抽公共 validation, 3 concrete 只写 `_fetch_raw` + 单位归一. Tushare MVP 2.1b 优先 (生产路径), Baostock + QMT MVP 2.1b 尾声
- **Alternatives**: (a) 每 fetcher 独立 DataSource 无继承 (代码重复) / (b) 统一 wrapper 函数式 (破坏 OOP 语义)
- **Consequences**: +600 代码行, -800 重复行, 3 fetcher 测试复用 (ADR + ADR-003 Event Sourcing 同款理由)
- **related_ironlaws**: [17, 30, 31]

### D4. DataSource 公共 validation 与现有 DataPipeline 边界

**关键不混淆**: DataPipeline (`backend/app/data_fetcher/pipeline.py` 369 行) 是 **入库时** 的 validation (rename / 列对齐 / L1 sanity / FK 过滤 / upsert). `BaseDataSource.validate` 是 **拉取后入库前** 的 schema/primary_key/单位 validation. 两者职责:

```
外部源 → fetch (_fetch_raw) → BaseDataSource.validate (schema + 单位 + PK + NaN)
       → DataPipeline.ingest (rename + FK 过滤 + upsert)
       → DB
```

MVP 2.1a 明确文档化此边界, 防止 MVP 2.1b 误把 DataPipeline 逻辑抄进 BaseDataSource.

---

## 验收标准

| # | 项 | 目标 |
|---|---|---|
| 1 | `backend/platform/data/base_source.py` (~120 行) | ✅ 存在 |
| 2 | `backend/platform/data/cache_coherency.py` (~180 行) | ✅ 存在 |
| 3 | `backend/tests/test_data_base_source.py` (~8 tests) | ✅ PASS |
| 4 | `backend/tests/test_cache_coherency.py` (~10 tests) | ✅ PASS |
| 5 | MVP 1.1-1.4 锚点 336 tests | ✅ 不回归 |
| 6 | `docs/adr/ADR-006-data-framework-3-fetcher-strategy.md` + `register_adrs.py --apply` 入库 | ✅ adr_records 6 行 |
| 7 | ruff check 新代码 | ✅ All checks passed |
| 8 | regression_test --years 5 | ✅ max_diff=0.0 (Data Framework 基础不触 signal/backtest 路径) |
| 9 | 全量 pytest fail | ≤ 24 (MVP 1.4 baseline 不增) |
| 10 | 老代码 git diff | 0 改动 (只新增 Platform 层 + docs/adr/ + tests) |

---

## 开工协议 (铁律 36 precondition 全部就绪)

- ✅ MVP 1.1 `DataSource` / `DataContract` / `ValidationResult` ABC 锁定
- ✅ MVP 1.2a `PlatformDataAccessLayer` read-only 可用 (本 MVP 不扩)
- ✅ MVP 1.4 `DBADRRegistry` 可用 — ADR-006 立即登记入库
- ✅ 老 `backend/data/factor_cache.py::_get_cache_max_date` 现有隐式协议 (本 MVP 显式化, 不改 logic)
- ✅ `register_adrs.py --apply` 脚本可重跑 (幂等 ON CONFLICT DO UPDATE)

---

## 禁做 (铁律)

- ❌ 不改 `backend/data/factor_cache.py` 核心逻辑 (MVP 2.1c 再集成)
- ❌ 不改 `backend/app/data_fetcher/pipeline.py` DataPipeline (铁律 17 专责, MVP 2.1a 不动)
- ❌ 不建新 DB 表 (announcements/financial_ind 留 MVP 3.0a)
- ❌ 不改 `backend/platform/data/interface.py` ABC 签名 (MVP 1.1 锁定)
- ❌ 不扩 `DataAccessLayer` 方法 (留 MVP 2.1c, 保 MVP 1.2a 接口稳定)
- ❌ 不做 concrete DataSource (Tushare/Baostock/QMT) — 留 MVP 2.1b

---

## 风险 + 缓解

| R | 描述 | 概率 | 缓解 |
|---|---|---|---|
| R1 | `BaseDataSource` validation 逻辑与 DataPipeline 重复 | 中 | §D4 明确边界 + tests 分别验证 |
| R2 | Cache Coherency 协议过度设计 (现有 factor_cache 已 work) | 低 | 本 MVP 只 wrap 现有, 不重写 |
| R3 | ADR-006 写的决策 MVP 2.1b 实施时被推翻 | 低 | ADR 可 `supersede()` (MVP 1.4 已实现), 允许演进 |
| R4 | 铁律 40 新增 fail | 低 | 纯新增代码 0 老路径改动, 每步跑 anchor |

---

## 下一步 (MVP 2.1b 预告)

- Wave 2 MVP 2.1b: 3 concrete fetcher (Tushare 重构 + Baostock + QMT) 继承 `BaseDataSource` (5-7 天, 中风险)
- MVP 2.1c: DAL 完整版扩展 + FactorCacheProtocol 集成 + 16 处直连 SQL 迁移 (5-7 天, 中-高风险)
- MVP 2.2: Data Lineage (data_lineage 表 + DataPipeline 自动记录, 1 周)
- MVP 2.3: Backtest Framework + U1 Parity (sim-to-real 对齐, 3-4 周)

---

## 变更记录

- 2026-04-17 v1.0 设计稿落盘, 等 plan approval.
- 2026-04-17 v1.1 **已交付** — plan file approval + 3 天内完成:
  - Day 1: `cache_coherency.py` (~220 行) + test_cache_coherency.py 19 tests PASS (超预期 10)
  - Day 2: `base_source.py` (~180 行, Template method) + test_data_base_source.py 10 tests PASS + ADR-006 markdown
  - Day 3: register_adrs.py --apply `adr_records` 5→6 / ruff clean / MVP 1.1-2.1a 锚点 365 PASS / regression max_diff=0 Sharpe 0.6095
  - 老代码 git diff = 0 行 (纯 Platform 新增)
  - Wave 2 正式开幕
