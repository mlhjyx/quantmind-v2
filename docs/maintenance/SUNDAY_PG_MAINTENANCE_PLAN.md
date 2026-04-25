# Sunday PG 维护窗口完整计划

> **时机**: Sunday 02:00-06:00 (PT 不交易, schtask 间隙)
> **目的**: Monday 4-27 09:00 MVP 3.1 真生产首触发前 PG 性能调优 + 磁盘回收
> **总收益**: ~70-90 GB 磁盘释放 + 真实查询 2-5x 加速

## ✅ 状态更新 (2026-04-26 00:00, Saturday 提前执行)

Phase 1+2 已 **Saturday 23:38-23:56 提前完成**, 不需 Sunday 02:00 再跑:

| Phase | 状态 | 实际结果 |
|---|---|---|
| Phase 1 shared_buffers 2→8GB | ✅ DONE | DB restart 23:38 via Windows Service |
| Phase 2.1 analyze | ✅ DONE | factor_values 6.83% bloat (~14 GB potential) |
| Phase 2.2 drop_covering | ✅ DONE | DB 263→218 GB (-45 GB), 0.18s |
| Phase 3 VACUUM FULL | ⏸️ **取消** | 仅 14 GB bloat, 2-4h 表锁性价比低, defer |
| **Bonus**: idx_fv_factor_date 重建 | ⏳ 跑中 | 修复 Q2 regression, ~10GB, 净 -35GB |

实测加速: Q1 (4 CORE GROUP BY) 9.75s → **5.68s** (1.7x). Q2 待 idx 完成 verify.

**实战教训** (新 LL 候选):
- TimescaleDB hypertable **不支持** CREATE INDEX CONCURRENTLY, 必须 plain CREATE INDEX
- pg_ctl restart **不刷新** Windows Service 状态, Servy 依赖 PG Windows Service 时启动失败 — 必走 `Start-Service PostgreSQL16` 而非 `pg_ctl start`
- drop covering 索引前必看 EXPLAIN production 查询模式, 不能仅看 idx_scan 数字

## 实测背景 (Session 36 末调研)

- PG 总: **263 GB** (vs 文档 159 GB drift +65%)
- factor_values: **211 GB** (134 GB 索引 = 64% heap)
- shared_buffers: 2 GB (32GB 机器仅 6.25%, 推荐 25% = 8GB)
- 索引使用率审计实测 (5 年累计 scan):

| 索引 | 大小 | 总 scans | MB/scan | 评级 |
|---|---|---|---|---|
| `idx_fv_factor_date_covering` | **45 GB** | 10,331 | **4.5 MB/scan** | 🔴 极度浪费 |
| `idx_fv_date_factor` | 9.8 GB | 506M | 0.02 MB/scan | 🔥 真热点 |
| `factor_values_pkey` | 59 GB | 575M | 0.1 KB/scan | ✅ 必保 |
| `idx_fv_code_date` | 10 GB | 2.3M | 4.5 KB/scan | ✅ 保留 |
| `factor_values_trade_date_idx` | 9.8 GB | 5.6M | 1.8 KB/scan | ✅ 保留 |

## 执行计划 (3 phase)

### Phase 1: shared_buffers 升级 (5-30s 中断)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_maintenance.ps1
```

操作: ALTER SYSTEM shared_buffers 8GB → Servy 4 服务 stop → pg_ctl restart → Servy start.
预期: PG cache hit 率 ↑, 真实查询 **2-3x 加速**.
风险: Servy 5-30s 中断 (auto reconnect).

### Phase 2: 索引清理 (~1 分钟, 释放 45 GB)

```powershell
# Step 1: 重新审计 (read-only, 验证 covering 仍闲置)
powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_vacuum.ps1 -Phase analyze

# Step 2: DROP idx_fv_factor_date_covering (-45 GB, 即时)
powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_vacuum.ps1 -Phase drop_covering -DryRun  # 预演
powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_vacuum.ps1 -Phase drop_covering         # 真跑
```

操作: `DROP INDEX idx_fv_factor_date_covering` (parent + 152 chunks 自动 cascade).
预期: 立即释放 ~45 GB, query plan 自动 fallback.
风险: 极低 — 实测 5 年仅 10K scans (噪音级使用), 但保险起见先 analyze 再 drop.

### Phase 3: VACUUM FULL (-20~40 GB bloat, 表锁 2-4h)

**前置**: Phase 1+2 完成, PT 全停 (Servy 服务停).

```powershell
powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_vacuum.ps1 -Phase vacuum
```

操作: VACUUM (FULL, ANALYZE, VERBOSE) factor_values.
预期: 重写表 + 重建索引 + 更新统计, 释放 bloat.
风险: 表锁 2-4h, 不可中断, 中断需 pg_terminate_backend.
时间预算: 211GB / ~50MB/s 重写 ≈ 1.2h, 加索引重建总 2-4h.

## 时序建议

```
02:00 — 跑 sunday_pg_maintenance.ps1 (Phase 1, 1-2 min)
02:05 — 跑 sunday_pg_vacuum.ps1 -Phase analyze (read-only, 1 min)
       审视输出 (idx_fv_factor_date_covering 仍 0-10K scans?)
02:15 — 跑 sunday_pg_vacuum.ps1 -Phase drop_covering (-45 GB, 1 min)
02:20 — 跑 sunday_pg_vacuum.ps1 -Phase vacuum (heavy, 2-4h)
05:00 — 期望完成, Servy 服务自动 reconnect 应该已恢复
05:30 — Verify: pg_size + smoke test + Servy /health
06:00 — 完工
```

## 回滚预案

| Phase | 回滚命令 |
|---|---|
| Phase 1 | `ALTER SYSTEM RESET shared_buffers; pg_ctl restart` |
| Phase 2 | 重建索引: `CREATE INDEX idx_fv_factor_date_covering ON factor_values (factor_name, trade_date) INCLUDE (...)` (需 ~1-2h, 但可后台跑 CONCURRENTLY) |
| Phase 3 | VACUUM FULL 不可回滚, 但操作只重写不改 schema, 数据不变 |

## 后续 verify

Phase 3 完成后跑:
```sql
SELECT pg_size_pretty(pg_database_size('quantmind_v2'));  -- 期望从 263 GB → ~150-180 GB
SELECT pg_size_pretty(pg_total_relation_size('factor_values'));  -- 期望从 211 GB → ~120-140 GB
```

跑 Saturday baseline benchmark 对比:
- Q1 (4 CORE 1yr GROUP BY): 9.75s → 期望 < 4s
- Q2 (1 因子 1yr bulk): 2.35s → 期望 < 1s

## 不要在本窗口做

- ❌ DROP `factor_values_pkey` (主键, 唯一热点 575M scans)
- ❌ DROP `idx_fv_date_factor` (506M scans, 真热点)
- ❌ TRUNCATE / DELETE 任何数据
- ❌ ALTER hypertable schema (TimescaleDB 限制)

## 后置 checklist (周一 09:00 真生产前)

- [ ] PG /health 200
- [ ] Servy 4 服务 Running
- [ ] Celery Beat lastrun < 5 min
- [ ] cb_state live row updated_at fresh
- [ ] strategy_registry 2 rows (s1 live + s2 dry_run)
- [ ] schtasks: 21 tasks Ready
- [ ] DingTalk 0 false alarm
