# F-D3A-1 Migration Apply Log — 2026-04-30

**PR**: feat/batch-2-p0-fixes (commit 1/6)
**Date**: 2026-04-30 ~19:10
**Operator**: Claude (chat-driven, via psql -f raw SQL)
**Scope**: 3 missing migrations (D3-A Step 1 spike F-D3A-1 P0, ~6h gap)
**真金风险**: 0 (schema mutation only, 0 业务 data INSERT/UPDATE/DELETE)

---

## §1 触发

D3-A Step 1 spike (PR #156) 实测发现 backend/migrations/*.sql 3 表 missing in DB:
- alert_dedup (MVP 4.1 batch 1 PostgresAlertRouter cross-process dedup)
- platform_metrics (MVP 4.1 batch 2.1 PostgresMetricExporter TimescaleDB hypertable)
- strategy_evaluations (MVP 3.5.1 update_status(LIVE) 守门历史 audit)

3 表生产代码引用:
- backend/qm_platform/observability/alert.py → alert_dedup
- backend/qm_platform/observability/metric.py → platform_metrics
- backend/qm_platform/strategy/registry.py → strategy_evaluations

任何 SDK 调 raise `psycopg2.errors.UndefinedTable`. PT 重启 gate 阻塞 prerequisite.

## §2 Apply 顺序 (硬性, FK 依赖驱动)

```
1. alert_dedup           (无 FK, 独立)
2. platform_metrics      (无 FK, hypertable 独立)
3. strategy_evaluations  (FK → strategy_registry, 必先 verify strategy_registry 存在)
```

## §3 实测命令 + 输出

### Pre-apply

```sql
-- 验证 connect 正确 DB
\conninfo
-- 用户 "xin" 已经连接 ... 端口"5432" ... 数据库 "quantmind_v2".

-- 验证 3 表 missing
SELECT table_name FROM information_schema.tables
 WHERE table_name IN ('alert_dedup','platform_metrics','strategy_evaluations');
-- (empty)  ← 3 表全 missing 证实

-- 验证 FK 目标 strategy_registry 存在
SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='strategy_registry');
-- t  ← FK 安全
```

### Apply (3 表顺序)

```bash
psql $DB -f backend/migrations/alert_dedup.sql
# CREATE TABLE / 8 COMMENT / 2 CREATE INDEX

psql $DB -f backend/migrations/platform_metrics.sql
# BEGIN / CREATE TABLE / 4 COMMENT / COMMIT
# SET statement_timeout
# create_hypertable (1 row)
# add_retention_policy (1006 — job id)
# SET / 2 CREATE INDEX
# DO $$ guard PASS

psql $DB -f backend/migrations/strategy_evaluations.sql
# CREATE TABLE / 8 COMMENT / 1 CREATE INDEX
# DO $$ defensive ALTER (idempotent CHECK)
```

### Post-apply verify

```bash
.venv/Scripts/python.exe scripts/audit/check_alembic_sync.py
# Table                          Status
# alert_dedup                    ✅ EXISTS
# platform_metrics               ✅ EXISTS
# strategy_evaluations           ✅ EXISTS
# ✅ PASS — 全部 3 expected tables 已 applied.
#    F-D3A-1 P0 阻塞已修.
# exit 0
```

## §4 Rollback path (备用, 本 commit 不跑)

```bash
psql $DB -f backend/migrations/strategy_evaluations_rollback.sql  # DROP RESTRICT order 反向
psql $DB -f backend/migrations/platform_metrics_rollback.sql       # DROP CASCADE chunks + retention
psql $DB -f backend/migrations/alert_dedup_rollback.sql            # DROP TABLE
```

## §5 Tier 0 + LL impact

- F-D3A-1 P0 阻塞: ✅ **关闭** (3 missing migrations 全 apply)
- PT 重启 gate prerequisite: 6/7 fail → 5/7 fail (F-D3A-1 ✓ + T0-19 ✓)
- LL 累计不变 (本 commit 无新 LL)
- 沿用 LL #24 (CHECK constraint 必实测) — 3 表 CHECK enum 沿用 SQL 文件 inline 定义

## §6 关联

- D3-A Step 1 spike PR #156 (F-D3A-1 实测发现)
- PR #167 scripts/audit/check_alembic_sync.py (本 commit verifier 来源)
- 批 2 P0 修 PR (本 PR feat/batch-2-p0-fixes commit 1/6)

## §7 后续 commits 解锁

T0-15 (commit 4) + T0-16 (commit 5) 钉钉去重依赖 alert_dedup 表 — 本 commit 解锁后可继续.
