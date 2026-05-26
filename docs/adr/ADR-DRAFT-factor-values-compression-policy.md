# ADR-DRAFT — factor_values TimescaleDB compression policy

**Status**: DRAFT (iter 158 W3-C sediment 2026-05-26)
**Trigger**: W2-D iter 149 R2 paired DEFER — factor_values 173 GB hypertable with compression disabled, 153 chunks growing ~1/day.
**Author**: L4+R loop iter 158
**Decision**: PENDING (DRAFT — awaiting R3 offline rehearsal + R4 disk audit + maintenance window)

---

## §1 Context

Per W2-D iter 149 audit `docs/audit/W2_D_FACTOR_VALUES_HYPERTABLE_AUDIT_2026_05_26.md`:

- **Current state**: 173 GB / 153 chunks / `compression_enabled=FALSE` / 0 compressed chunks
- **Growth rate**: +1 chunk + 1 GB / day (sustained iter 52 → iter 149 baseline drift)
- **Naive projection**: ~365 GB end-2026 if no compression intervention
- **Schema**: 6 columns (code / trade_date / factor_name / raw_value / neutral_value / zscore)

TimescaleDB native compression typically achieves 10x-20x compression on factor data due to numeric-heavy + repeated factor_name patterns.

---

## §2 Proposed compression policy

```sql
-- §2.1 Enable compression with optimal segmentation
ALTER TABLE factor_values SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'factor_name',
    timescaledb.compress_orderby = 'trade_date DESC, code'
);

-- §2.2 Scheduled compression policy (chunks older than 30 days)
SELECT add_compression_policy('factor_values', INTERVAL '30 days');

-- §2.3 Verify
SELECT hypertable_name, num_chunks, compression_enabled
FROM timescaledb_information.hypertables
WHERE hypertable_name = 'factor_values';
```

**Segmentation rationale**:
- `compress_segmentby = 'factor_name'` — 276 distinct factor_names, each becomes a compression group. Time-series queries filtered by factor_name avoid decompressing irrelevant segments.
- `compress_orderby = 'trade_date DESC, code'` — most queries filter by date range, descending order keeps newest data in fastest-access compressed segments.

**Threshold rationale**:
- 30-day threshold — keeps recent 30 days uncompressed for daily IC write (compute_daily_ic.py writes T+1 trade_dates each evening), avoids decompression overhead on hot data.

---

## §3 Decision matrix

### §3.1 Pros

| Metric | Uncompressed (current) | Compressed (projected 10x) |
|---|---|---|
| Disk footprint | 173 GB (growing 1 GB/day) | ~17-37 GB (steady-state) |
| Backup time | full + slow | full + faster (compressed) |
| Cold query latency | fast (raw rows) | +5-50ms decompression overhead per chunk |
| Hot query latency (recent 30d) | fast | unchanged (uncompressed window) |

### §3.2 Cons

- One-time CPU burst during initial compression (~150 chunks × N seconds each, run during off-hours)
- Decompression overhead on backtest scenarios querying old dates (12.4 years of factor data)
- IC computation read pattern hits decompression if `--days 365+` flag used
- Compression policy is reversible (`remove_compression_policy + decompress_chunk`) but consumes CPU

### §3.3 Risks

- Once enabled, schema migrations (ALTER TABLE) require decompression first (operational complexity)
- D:\pgdata16 free-space buffer must accommodate decompression temp + compressed copy during transitions
- 铁律 9 资源仲裁 — compression jobs are CPU-intensive, must coordinate with Beat schedule (avoid 14:30 PMSRule eval window + 18:00 daily IC compute window)

---

## §4 Implementation prerequisites (R3+R4 rehearsal)

Per W2-D §4 R2+R3+R4 paired DEFER:

| # | Prerequisite | Owner | Status |
|---|---|---|---|
| P1 | Host disk D:\ partition free-space audit — ensure ≥40 GB buffer for decompression temp | ops | DEFERRED |
| P2 | Staging table rehearsal — create empty staging table with same schema, copy 1 chunk worth of data, ALTER compress, measure compression ratio + query latency delta | dev | DEFERRED |
| P3 | Beat schedule conflict scan — confirm no Beat triggers during compression policy hour (default `policy_compression`) | dev | DEFERRED |
| P4 | PT restart prerequisite — compression migration MUST run during PT-paused window (sustained since 4-29), Phase B-1 paper-mode dry-run period is ideal | ops | available now (PT 27d paused) |

---

## §5 Rollback plan

```sql
-- Step 1: remove scheduled policy
SELECT remove_compression_policy('factor_values');

-- Step 2: decompress all compressed chunks
SELECT decompress_chunk(c)
FROM show_chunks('factor_values') c
WHERE c::regclass::oid IN (
    SELECT chunk_oid FROM _timescaledb_catalog.chunk WHERE compressed_chunk_id IS NOT NULL
);

-- Step 3: disable compression
ALTER TABLE factor_values SET (timescaledb.compress = false);
```

Rollback time: ~150 chunks × decompression time per chunk (estimated 2-5 minutes per chunk for 1 GB data, total 5-12 hours sequential).

---

## §6 Acceptance criteria

1. P1+P2+P3 prerequisites completed (rehearsal report + free-space confirmation)
2. Initial compression migration applied during maintenance window
3. Verify post-migration: `hypertable_size('factor_values')` decreased by ≥80% (10x compression target)
4. Smoke test: 1-week backtest still runs cleanly post-compression (`pytest -m smoke`)
5. IC query latency benchmark: cold-read on compressed chunk <500ms (acceptable degradation)
6. ADR promote from DRAFT → ADR-NNN (per REGISTRY assign next sparse ID, likely ADR-096 since ADR-095 already exists per Pattern B pivot)

---

## §7 References

- W2-D audit: `docs/audit/W2_D_FACTOR_VALUES_HYPERTABLE_AUDIT_2026_05_26.md` (compression OFF finding, ADR-DRAFT trigger)
- LL-208: `LESSONS_LEARNED.md` LL-208 (T+1 IC lookahead — factor_values write pattern context)
- TimescaleDB docs: <https://docs.timescale.com/api/latest/compression/>
- CLAUDE.md §因子存储 (current state baseline)
- 铁律 9 (重数据并发限制), 铁律 15 (回测可复现)

---

## §8 §6 8-trigger STOP check at promote-time

When promoting DRAFT → ADR-NNN, run 8-trigger STOP check:
- broker: NEGATIVE (DDL only)
- .env: NEGATIVE
- yaml: NEGATIVE
- DB mutation: **POSITIVE** (ALTER TABLE + compression policy invocation = DDL change)
- production code: NEGATIVE
- Beat schedule: NEGATIVE (no new Beat, uses TimescaleDB internal scheduler)
- broker comm: NEGATIVE
- 铁律 9 资源: **POSITIVE** (CPU-intensive compression jobs need ops coordination)

→ Promote-time requires explicit user authorization + maintenance window scheduling.

---

**ADR-DRAFT lifecycle**: created iter 158 → P1-P4 rehearsal → user authorization → promote to ADR-NNN → migration → smoke verify → §6 acceptance.

**iter 158 §4.5 ratio impact**: +1 implement (ADR-DRAFT row sediment); R3+R4 paired DEFER carry over.
