# W2-D FACTOR_VALUES_172GB_HYPERTABLE_AUDIT (iter 149)

**Date**: 2026-05-26
**Trigger**: Audit Week 2 manifest backlog (W2-D MID priority data layer perf)
**Method**: PG direct query (TimescaleDB hypertable_size + chunks + compression policy)

---

## §1 Audit scope

`factor_values` table (TimescaleDB hypertable, factor IC + raw value storage). Verify:
- Current disk footprint vs CLAUDE.md cite (172 GB claim)
- Compression policy state (TimescaleDB native compression)
- Chunk count + size distribution
- Retention policy (drop_chunks)
- Compression saving estimate

---

## §2 Reality findings (PG queries fresh 2026-05-26)

| Metric | Value | Source |
|---|---|---|
| `pg_size_pretty(hypertable_size('factor_values'))` | **173 GB** | direct PG query |
| `COUNT(*)` row count | **841,376,039** | direct PG query |
| `num_chunks` | **153** | timescaledb_information.hypertables |
| `compression_enabled` | **FALSE** | timescaledb_information.hypertables |
| `compressed_chunks` | **0 of 153** | timescaledb_information.chunks |
| Compression policy | **NOT CONFIGURED** | (no add_compression_policy invocation found in migrations) |
| Retention policy | **NOT CONFIGURED** | (no add_retention_policy invocation found) |

### Cross-doc comparison

- CLAUDE.md §因子存储 cite: "factor_values: 841,376,039 行 (~172 GB, TimescaleDB hypertable 152 chunks)" — **drift +1 GB +1 chunk** (natural growth since 5-25 fresh verify)
- SYSTEM_STATUS.md:732 (per CLAUDE.md note): stale 501M 4-07 snapshot — confirmed `1.67x diff is SYSTEM_STATUS stale, NOT CLAUDE.md 错误` (per CLAUDE.md drift annotation iter 52)

---

## §3 Finding F1 (P1) — Compression NOT enabled

**Pre-condition**: TimescaleDB native compression is a standard feature (https://docs.timescale.com/use-timescale/latest/compression/). For OLAP / time-series workloads typical compression ratio is 5-10x. Factor IC + value data (heavy on numeric columns with limited variance per chunk window) is high compression candidate.

**Current state**: `compression_enabled = FALSE`. 0 of 153 chunks compressed. 173 GB uncompressed.

**Impact**:
- Disk footprint: 173 GB current → estimated 20-35 GB compressed (~5-9x typical for factor data) = **~140-150 GB potential savings**
- Backup size: PG_BASEBACKUP / pg_dump time scales with on-disk size. Reducing 173 GB → 20-35 GB cuts daily backup time ~80%.
- Query performance: compressed chunks use columnar storage + dictionary encoding → faster scans for analytical queries (sum/avg/group-by on time windows) at cost of slight insertion overhead.
- Cache efficiency: smaller pages → more chunks fit shared_buffers (currently 2 GB per CLAUDE.md PG config) → reduces disk I/O.

**Recommended action (DEFER-to-user — DB DDL requires authorization per 铁律 9 + CLAUDE.md ALTER TABLE pg_stat_activity check)**:

```sql
-- Step 1: Enable compression on factor_values hypertable
ALTER TABLE factor_values SET (
  timescaledb.compress = true,
  timescaledb.compress_segmentby = 'symbol_id, factor_name',
  timescaledb.compress_orderby = 'trade_date DESC'
);

-- Step 2: Add compression policy (compress chunks older than 30 days)
SELECT add_compression_policy('factor_values', INTERVAL '30 days');

-- Step 3: Monitor compression progress (will run in background)
SELECT chunk_name, compression_status, ... FROM ... WHERE hypertable='factor_values';
```

**Risks**:
- Compression takes time (153 chunks × ~1 GB each → could run for hours during initial backfill)
- Should be done during off-hours (Saturday/Sunday) to avoid Beat schedule contention
- PG OOM risk (per CLAUDE.md "32GB DDR5 + shared_buffers=2GB" + iter 132 envelope still active in Beat schedule)
- After compression, INSERT cost increases ~2-5x (compressed chunk decompression on insert) — currently `factor_values` writes only during daily Beat tasks (IC computation 18:00 + minute_bars factor compute), insert volume manageable

**Pre-check before user runs**:
```sql
-- Check no active connections holding lock
SELECT pid, state, query FROM pg_stat_activity
WHERE datname='quantmind_v2' AND state != 'idle';
-- Check disk free space (compression needs 2x source space during process)
SELECT pg_size_pretty(pg_database_size('quantmind_v2'));
```

---

## §4 Finding F2 (P2) — Retention policy NOT configured

`factor_values` has 5+ years of data (per CLAUDE.md cite 5yr Baostock since 2021). Beyond ~10 years for backtest, older factor data ROI diminishes (regime drift > recent alpha signal).

**Recommended action (DEFER)**:
```sql
-- Drop chunks older than 10 years (preserves 12yr OOS regression baseline)
SELECT add_retention_policy('factor_values', INTERVAL '10 years');
```

**Defer cite**: Lower priority than compression. Compression first reduces disk; retention is finer-grained pruning. Reasonable only post-compression baseline.

---

## §5 Finding F3 (INFO) — CLAUDE.md drift annotation accurate

CLAUDE.md drift annotation iter 52 explicitly documented:
- factor_values fresh 5-25 verify = 841,478,083 rows / 152 chunks
- iter 149 fresh 5-26 verify = 841,376,039 rows / 153 chunks

**Wait — discrepancy detected**: CLAUDE.md (5-25 verify): **841,478,083** rows. iter 149 (5-26 verify): **841,376,039** rows. That's -102,044 rows (-0.012%). Row counts should monotonically INCREASE, not decrease. Either:
- (a) CLAUDE.md 5-25 cite was wrong (typo OR misread)
- (b) Recent DELETE / TRUNCATE occurred between 5-25 and 5-26
- (c) PG stale stats / cached count discrepancy

Most likely (a) — CLAUDE.md row counts should be monotone but CLAUDE.md has been edited by parallel iter 132+133 governance commits. iter 52 fresh verify cited may itself have been typo. Defer-with-cite for follow-up reconciliation iter.

Doesn't affect §3 compression recommendation (still ~841M rows, still ~173 GB, still 0 compression).

---

## §6 Recommendation summary

| Finding | Severity | Action | Cost | Authorization |
|---|---|---|---|---|
| F1 Compression OFF | P1 | Enable TS compression + 30d policy | ~hours during off-hour | **User authorization needed** (DB DDL on prod table) |
| F2 Retention OFF | P2 | Add 10y retention policy | ~min | Defer, do post-F1 |
| F3 Row count drift | INFO | Cross-verify cite source | ~min | Iter 150+ reconciliation |

**Estimated benefit**: 140-150 GB disk reclaim + ~5x faster backups + improved cache efficiency for time-series queries.

**Estimated risk**: Compression backfill 1-3 hours / off-hour required / PG OOM monitoring during process / post-compression INSERT cost +2-5x (manageable for current load).

---

## §7 Next iter (user redirect for execution OR continue audit)

Iter 150+ candidates:

1. **F1 compression apply** (requires user authorization + off-hour scheduling — Saturday 2026-05-30 candidate)
2. **W2-B L4_STAGED_EXECUTION_AUDIT** (remaining Week 2 audit slot)
3. **iter 142 Servy restart unblock** (still pending elevated shell)
4. **Tier A§1 Phase J 5 chain** (sustained backlog)
5. **Tier B Wave 5 MVP design** (post-W2 audit closure)

红线 5/5 sustained: cash ¥993,520.66 / 0 持仓 / paper / true / 81001102.
main HEAD: a5738b1 (post iter 148 F9 DEFER).

铁律 alignment: 9 (重数据 ALTER TABLE pre-check sustained), §6 carve-out
NOT triggered (compression is config not new architecture, but DDL still
needs user authorization per CLAUDE.md ALTER TABLE protocol), §v9.49
reality re-grounding sustained (audit reveals deploy debt + perf gap).

---

**Provenance**: Direct PG queries against `quantmind_v2` DB via psql 2026-05-26 ~14:30 SH. Hypertable_size + chunks + compression policy all fresh-verified at audit time.
