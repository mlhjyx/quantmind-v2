# MVP 1.3a · Registry Schema + 回填

> **Wave**: 1 — 架构基础层 (第 4 步, MVP 1.3 拆分的 1/3)
> **耗时**: 1 天实施 (plan 预估 3-4 天)
> **范围**: factor_registry schema 扩展 (+pool/+ic_decay_ratio) + 回填 282 因子 + MVP 1.1 FactorMeta 对齐 + MVP 1.2a DAL drift 修复
> **铁律**: 15 (regression), 22 (doc 跟随), 23 (独立可执行), 25 (验代码), 28 (drift 报告), 34 (config SSOT), 40 (测试债)

---

## 目标 (已兑现)

1. **修复 6 个 drift** (MVP 1.2a plan 深度探索发现)
2. factor_registry 达 287 行 (前 5 + 新 282), pool 分布合理
3. MVP 1.1 FactorMeta 对齐 live PG 18 字段
4. MVP 1.2a DAL read_registry 对 live PG 真可用 (原本 pool 列不存在会爆)

## 非目标 (留 1.3b/1.3c)

- ❌ signal_engine.py direction DB 化 (MVP 1.3b)
- ❌ onboarding 强制化 DataPipeline 拒写 (MVP 1.3c)
- ❌ factor_lifecycle.py 迁 Platform (MVP 1.3c)
- ❌ _constants.py hardcoded direction 删除 (MVP 1.3b 后)

---

## 6 个 Drift 修复 (本次)

| # | Drift | 修复 |
|---|---|---|
| 1 | DB `factor_registry` 无 `pool` 列 | ALTER TABLE ADD COLUMN pool VARCHAR(30) DEFAULT 'CANDIDATE' + index |
| 2 | DB 无 `ic_decay_ratio` (MVP A factor_lifecycle 需要) | ALTER TABLE ADD COLUMN ic_decay_ratio NUMERIC(6,4) |
| 3 | MVP 1.1 FactorMeta 字段与 DB drift (ic_mean/registered_at/pool 等) | interface.py FactorMeta 扩展 18 字段 + property alias 向后兼容 |
| 4 | MVP 1.2a DAL read_registry SQL 查 pool 会爆 live PG | 改 SQL 对齐 18 列 |
| 5 | sqlite test schema 虚假通过 (自建 pool 列) | test fixture schema 对齐 live PG |
| 6 | DB 5 行 vs factor_values 276 distinct 巨大 gap | 写回填脚本 (3 层合并 + dry-run 默认) |

---

## 实施结构

```
backend/migrations/
├── factor_registry_v2.sql             ⭐ 新增: ALTER TABLE + 索引 (已应用)
└── factor_registry_v2_rollback.sql    ⭐ 新增: emergency rollback

scripts/registry/
└── backfill_factor_registry.py        ⭐ 新增 ~500 行: 3 层合并 + dry-run/apply

backend/platform/factor/interface.py   ⚠️ FactorMeta 扩展 18 字段 + registered_at/ic_mean property alias
backend/platform/data/access_layer.py  ⚠️ read_registry SQL 对齐 DB 18 列
backend/tests/test_platform_dal.py     ⚠️ sqlite schema + seed 数据对齐 DB 18 列

backend/tests/
└── test_registry_backfill.py          ⭐ 新增 50 tests (category/pool/status/merge)

docs/mvp/
└── MVP_1_3a_registry_backfill.md      ⭐ 本文
```

**规模**: ~500 行脚本 + ~50 行 SQL + ~300 行测试 + interface/DAL 小改 = ~900 行.

---

## 关键设计

### 3 层数据源合并策略

| Layer | 来源 | 优先级 | 结果 |
|---|---|---|---|
| 1 | live PG factor_registry (5 行) | 最高 | 保 DB 值, 只补 pool/status |
| 2 | `_constants.py` + signal_engine hardcoded (59 因子) | 中 | 补 direction + source='builtin' |
| 3 | factor_values distinct (276 个) | 低 | 孤儿填 LEGACY + direction=1 |

冲突策略: Layer 1 vs Layer 2 direction 不一致 → 保 Layer 1 + 记 WARN (e.g. `reversal_20: DB=-1 vs hardcoded=1`).

### Pool 分类规则 (CLAUDE.md §因子池状态)

| Pool | 规则 | 本次回填数 |
|---|---|---|
| CORE | CORE3+dv_ttm (PT 生产): turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm | **4** |
| CORE5_baseline | reversal_20 / amihud_20 (regression_test 基线保留) | **2** |
| INVALIDATED | mf_momentum_divergence (IC=-2.27% 证伪) | **1** |
| DEPRECATED | momentum_5/10/60 / volatility_60 / turnover_std_20 | **4** |
| PASS | 有 hardcoded direction 的因子 (已画像) | **48** |
| LEGACY | factor_values 出现但无元数据 (AUTO_BACKFILL) | **228** |
| **总计** | | **287** |

### Category 推断规则 (15+ pattern)

顺序优先: **特定前缀先, 通用关键词后** (如 `high_freq_volatility` 应命中 microstructure, 不是 risk). 10+ category: liquidity / risk / fundamental / momentum / microstructure / moneyflow / northbound / event / alpha158 / phase21 / price_volume / legacy.

---

## 验收标准 (实测)

| # | 项 | 实测 |
|---|---|---|
| 1 | ALTER TABLE migration 幂等 | ✅ IF NOT EXISTS, 跑 2 次无错 |
| 2 | live PG factor_registry 18 字段 | ✅ 已验证 |
| 3 | MVP 1.2a DAL read_registry 对 live PG PASS | ✅ 5→287 行查询成功 |
| 4 | 回填后 factor_registry 287 行 (CORE 4, PASS 48, LEGACY 228, ...) | ✅ pool 分布正确 |
| 5 | CORE 4 因子 pool/direction/category 全对 | ✅ 抽查 PASS |
| 6 | `test_registry_backfill.py` | ✅ **50/50 PASS** (0.04s) |
| 7 | `test_platform_dal.py` (21 → 21 PASS) + skeleton 65 | ✅ 86/86 |
| 8 | ruff check 新代码 | ✅ All checks passed |
| 9 | regression_test --years 5 | ✅ **max_diff=0.0** |
| 10 | 全量 pytest fail | (后台, commit 前最终确认) |
| 11 | DDL 文档同步 | Day 3 更新 docs/QUANTMIND_V2_DDL_FINAL.sql |
| 12 | 老代码 diff | 空 (除 interface 扩展 / DAL SQL 对齐 / 测试 schema 对齐) |

---

## 关键踩坑

1. **MVP 1.2a 伪通过**: sqlite test 自建 schema 含 pool 列, 但 live PG 无. MVP 1.2a commit 时未对接 live PG 验证. 启示: 后续 MVP (如 1.3b) 测试必须包含**至少一个 live DB smoke 断言**.
2. **category 规则顺序敏感**: `high_freq_volatility_20` 若 volatility 规则先匹配 → 错分 risk. 修: 特定 prefix 先, 通用关键词后.
3. **zip strict=True**: pyproject scripts/ 不免 B905, 用 `strict=True` 保 name-value 对齐严格.

---

## 下一步 (MVP 1.3b)

**MVP 1.3b Direction DB 化 + 老代码迁移** (3-5 天, 中-高风险):
1. 实现 `FactorRegistry.get_direction(name) -> int` concrete (调 DAL.read_registry + cache)
2. signal_engine.py L163 `FACTOR_DIRECTION.get(fname, 1)` → 走 FactorRegistry.get_direction, 带 FeatureFlag `use_db_direction` 灰度
3. 验证一周后切 True, 删 `_constants.py` 10 direction dict
4. regression max_diff=0 + 全量 pytest 不倒退

MVP 1.3b 前置 precondition 全部就绪: pool 分布 + 287 行元数据 + DAL read_registry 对 live PG 工作.

---

## 变更记录

- 2026-04-17 晚 v1.0 — 当天实施完成, 287 行 registry 落地, 50 tests PASS + regression max_diff=0
