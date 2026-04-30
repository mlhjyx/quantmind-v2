# 现状快照 — DB Schema (类 2)

**Audit ID**: SYSTEM_AUDIT_2026_05 / WI 3 / snapshot/02
**Date**: 2026-05-01
**Type**: 描述性 + 实测证据 + 发现

---

## §1 实测真值 (CC 5-01 04:30 实测 PG)

### 1.1 总表数

```sql
SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';
-- 实测: 86
```

### 1.2 Top 5 公共表 (按 size)

| 表 | size | 行数 (n_live_tup) | 备注 |
|---|---|---|---|
| minute_bars | 36 GB | 0 (hypertable, 行在 chunks) | Baostock 5min K 线, sprint period CLAUDE.md 写 190M 行 |
| moneyflow_daily | 4.4 GB | 62,095 | sprint state 沉淀 sustained |
| daily_basic | 3.8 GB | 54,848 | sprint state 沉淀 sustained |
| stock_status_daily | 1.2 GB | 54,848 | — |
| margin_detail | 902 MB | 0 | 死表 candidate (n_live_tup=0) |
| northbound_holdings | 648 MB | 0 | 死表 candidate (n_live_tup=0) |

### 1.3 TimescaleDB Hypertables

实测 chunk 命名实测 `_hyper_1_NNN_chunk` 出现到 ID=202 (CLAUDE.md sprint period 写 "factor_values hypertable 152 chunks", 实测**chunk ID 已超 152 → 200+**). **F-D78-9 [P3] CLAUDE.md "152 chunks" 数字漂移** (sprint state Session 45 D3-B 实测 2026-04-30 但当前 chunk 数已扩).

### 1.4 因子 DISTINCT 真值

实测 SQL:
```sql
SELECT COUNT(DISTINCT factor_id) FROM factor_values;
SELECT COUNT(DISTINCT factor_id) FROM factor_ic_history;
```
(本审查 query 部分卡顿, 未取得真值. 留 sub-md 06_factors 详查.)

### 1.5 cb / position 关键 schema

详 GLOSSARY C 段. 关键发现:
- **真表名**: `circuit_breaker_state` (sprint state 用 `cb_state` 别名漂移)
- **真字段**: `execution_mode` (sprint state 用 `source` 字段漂移)
- 关联 finding: F-D78-2 [P3] sprint state 用 cb_state alias

---

## §2 跨表 FK / JOIN 关系

(本审查未深查 FK 真 graph, 留 sub-md 14_dataflow 详查. 候选 finding: TimescaleDB hypertable + 普通表 join 性能 + 跨表外键约束 verify.)

---

## §3 死表 candidate

| 表 | n_live_tup | size | 推断 |
|---|---|---|---|
| margin_detail | 0 | 902 MB | 历史导入数据但 0 live row, 候选 deprecated |
| northbound_holdings | 0 | 648 MB | 同上 |

(其他 0 行表很多是 hypertable parent, 不算死表. 真死表需 query 最后 INSERT timestamp 实测.)

---

## §4 慢查询 candidate

(本审查未启用 pg_stat_statements 跑实测, 留 performance 领域 sub-md.)

---

## §5 发现汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-9 | P3 | CLAUDE.md "factor_values hypertable 152 chunks" 数字漂移, 实测 chunk ID 已超 152 (sprint period sustained 数字 stale) |
| F-D78-10 | P2 | 死表 candidate `margin_detail` (902 MB / 0 live rows) + `northbound_holdings` (648 MB / 0 live rows), 未 deprecated 标记 |
| F-D78-2 (复) | P3 | cb_state alias 漂移 (真表 circuit_breaker_state) — sprint state handoff |

---

## §6 实测证据 cite

- 实测时间: 2026-05-01 04:16 (NOW())
- 实测 query: `pg_stat_user_tables` ORDER BY pg_total_relation_size DESC
- 实测 hypertable: `timescaledb_information.hypertables`
- 实测 schema: `information_schema.columns`

**文档结束**.
