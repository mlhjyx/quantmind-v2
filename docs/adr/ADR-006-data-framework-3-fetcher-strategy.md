---
adr_id: ADR-006
title: Data Framework 3 fetcher 收编策略 — Template method + BaseDataSource
status: accepted
related_ironlaws: [17, 30, 31]
recorded_at: 2026-04-17
---

## Context

Wave 2 MVP 2.1 需把现有 3 fetcher 代码收编到 Platform `DataSource` abstract:

| Fetcher | 现有文件 | 行数 | 数据类型 |
|---|---|---|---|
| Tushare | `backend/app/data_fetcher/fetch_base_data.py` | 598 | 日 K / daily_basic / 资金流 |
| Baostock | `scripts/fetch_minute_bars.py` | 280 | 5 分钟 K 线 (minute_bars) |
| QMT | `scripts/qmt_data_service.py` | 274 | 实时持仓 / NAV / 价格 → Redis |

3 fetcher 的 **validation 逻辑 70% 重复** (schema + 主键唯一 + NaN 比例 + 单位归一). 若每个 fetcher 独立实现 `DataSource.validate`, 意味着 **3x 重复代码 + 3x 测试覆盖**.

## Decision

采用 **Template Method 模式** + `BaseDataSource` 抽公共 validation 骨架:

```python
class BaseDataSource(DataSource):
    def fetch(self, contract, since):
        df = self._fetch_raw(contract, since)      # 子类实现
        result = self.validate(df, contract)        # 公共
        if not result.passed:
            raise ContractViolation(result.issues)
        return df

    def validate(self, df, contract):
        issues = []
        issues.extend(self._check_schema(df, contract))
        issues.extend(self._check_primary_key(df, contract))
        issues.extend(self._check_nan_ratio(df, contract))
        issues.extend(self._check_value_ranges(df, contract))
        return ValidationResult(passed=not issues, ...)
```

MVP 2.1b 3 concrete fetcher **只写 `_fetch_raw` + 单位归一 + 可选 `_check_value_ranges` override**.

**职责边界**:
- `BaseDataSource.validate` = **拉取后入库前** (schema + PK + NaN + value range)
- `DataPipeline.ingest` = **入库时** (rename + L1 sanity + FK 过滤 + upsert)
- 两者不重叠. DataPipeline 不抄进 BaseDataSource.

## Alternatives Considered

| 选项 | 代码量 | 测试复用 | 为何不选 |
|---|---|---|---|
| **Template method + BaseDataSource** ⭐ | 3 × 约 200 行 | 公共 helpers 复用 | — (选此) |
| 独立 DataSource 无继承 | 3 × 400 行 (重复 validation) | 0 复用 | 1200 行重复, 改一处改 3 份 |
| 函数式 wrapper (`validate_df(df, contract, ...)`) | 3 × 350 行 | helpers 可复用 | 破坏 OOP 语义, MVP 1.1 interface 已是 ABC |
| Decorator 模式 `@validated_fetch` | 3 × 300 行 | 中等 | decorator 无 state, 需全局参数传递, 复杂度高 |

## Consequences

**正面**:
- 3 concrete fetcher 代码量降 1400 → ~600 行 (-57%)
- validation helpers 测试 1 次覆盖 3 fetcher (测试复用)
- MVP 2.1b 实施时 `_fetch_raw` 专注拉取, validation bug 在 Base 层集中修
- 与 MVP 1.1 `DataSource` ABC 契约一致, 不改 interface

**负面**:
- 子类继承深度 +1 (DataSource → BaseDataSource → TushareDataSource)
- value_ranges 业务检查因 fetcher 而异 (e.g. close > 0 vs position ≥ 0), 必须 `_check_value_ranges` override 而非固化在 Base
- 未来若出现第 4 种 fetcher (e.g. JoinQuant) 需重新评估 Base 能否涵盖

## References

- `docs/mvp/MVP_2_1a_cache_coherency_foundation.md` §D2/D4
- `backend/platform/data/base_source.py` (MVP 2.1a 实现)
- `backend/platform/data/interface.py::DataSource` (MVP 1.1 ABC)
- `backend/tests/test_data_base_source.py` (10 tests 验证 Template method)
- 铁律 17 (DataPipeline 入库) / 30 (Cache Coherency) / 31 (Engine 纯计算)
- ADR-003 (Event Sourcing StreamBus + PG) — 相同 "共基类 + 具体实现" 架构精神
