# Sunday PG 维护窗口 — Phase 2: VACUUM FULL + REINDEX (~2-4h, 表锁)
#
# 用途: 回收 factor_values bloat (~20-40 GB) + 索引重建 (~30-60 GB)
# 时机: Sunday 02:00 起, 走完前需 PT 全停 (Phase 1 已停 Servy)
# 依赖: Phase 1 sunday_pg_maintenance.ps1 已跑 (shared_buffers 升 8GB + Servy 停)
#
# 风险: factor_values VACUUM FULL 需独占锁 (~2-4h, 期间表不可读写)
# 时间预算: 211GB factor_values × ~50MB/s 重写 ≈ 1.2h, 加索引重建总 2-4h
# 可中断: VACUUM FULL 不可断 (会持锁), 中断需 pg_terminate_backend
#
# 使用:
#   powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_vacuum.ps1 -Phase analyze
#   powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_vacuum.ps1 -Phase vacuum
#   powershell -ExecutionPolicy Bypass -File scripts\maintenance\sunday_pg_vacuum.ps1 -Phase reindex

param(
    [ValidateSet("analyze", "drop_covering", "vacuum", "reindex", "all")]
    [string]$Phase = "analyze",
    [switch]$DryRun = $false
)

$ErrorActionPreference = "Stop"
$env:PGPASSWORD = 'quantmind'
$psql = "D:\pgsql\bin\psql.exe"
$startTime = Get-Date

Write-Host "===== Sunday PG Maintenance Phase 2: $Phase =====" -ForegroundColor Cyan

# ─── 预检 ───────────────────────────────────────────────────
$dow = (Get-Date).DayOfWeek
$hr = (Get-Date).Hour
if ($dow -ne 'Saturday' -and $dow -ne 'Sunday' -and ($hr -ge 9 -and $hr -le 16)) {
    Write-Host "[FATAL] 交易时段拒绝" -ForegroundColor Red; exit 3
}

# ─── Phase: analyze (read-only, 列 bloat + 候选 drop 索引) ──
if ($Phase -eq "analyze" -or $Phase -eq "all") {
    Write-Host "`n[ANALYZE] factor_values bloat + 索引候选 ..." -ForegroundColor Yellow

    # bloat estimate (per chunk)
    & $psql -U xin -d quantmind_v2 -h localhost -c @"
SELECT
  schemaname || '.' || relname AS chunk,
  pg_size_pretty(pg_total_relation_size(relid)) AS total,
  pg_size_pretty(pg_relation_size(relid)) AS heap,
  n_live_tup, n_dead_tup,
  ROUND(100.0 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 1) AS dead_pct
FROM pg_stat_user_tables
WHERE schemaname = '_timescaledb_internal'
  AND relname LIKE '%factor_values%'
  AND n_live_tup > 1000000
ORDER BY n_dead_tup DESC
LIMIT 10
"@

    Write-Host "`n--- 索引重叠候选 (factor_values 5 个索引) ---"
    & $psql -U xin -d quantmind_v2 -h localhost -c @"
-- 列 hypertable parent 上的索引定义
SELECT indexname, indexdef FROM pg_indexes
WHERE schemaname='public' AND tablename='factor_values'
ORDER BY indexname
"@

    Write-Host "`n--- 索引使用率 (重叠则可 drop) ---"
    & $psql -U xin -d quantmind_v2 -h localhost -c @"
SELECT relname AS tbl, indexrelname AS idx,
       idx_scan AS scans, idx_tup_read AS tuples,
       pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes
WHERE schemaname='public' AND relname='factor_values'
ORDER BY idx_scan DESC
"@

    Write-Host "`n[ANALYZE 完成] 评估上述输出后:" -ForegroundColor Green
    Write-Host "  - dead_pct > 20%: VACUUM FULL 价值高"
    Write-Host "  - idx_scan = 0: 该索引未用 (可 DROP, 节省空间)"
    Write-Host "  - 多个索引功能重叠: 留 covering, drop 子集"
    Write-Host "`n下一步: vacuum 或 reindex (单独运行)"
}

# ─── Phase: drop_covering (轻, 释放 45GB) ───────────────────
if ($Phase -eq "drop_covering" -or $Phase -eq "all") {
    Write-Host "`n[DROP idx_fv_factor_date_covering] 45GB 收回 (实测 10K scans / 5年, 极度浪费) ..." -ForegroundColor Yellow
    Write-Host "  实测: 5 MB/scan vs idx_fv_date_factor 0.02 MB/scan (225x 更不划算)"
    Write-Host "  风险: 极低 (PG planner 几乎不选), DROP 后 query plan 自动 fallback"

    if ($DryRun) {
        Write-Host "  [DRY-RUN] would: DROP INDEX idx_fv_factor_date_covering" -ForegroundColor Gray
    } else {
        $dropStart = Get-Date
        & $psql -U xin -d quantmind_v2 -h localhost -c "DROP INDEX IF EXISTS public.idx_fv_factor_date_covering" 2>&1
        if ($LASTEXITCODE -ne 0) { Write-Host "[FATAL] DROP failed" -ForegroundColor Red; exit 4 }
        $dropElapsed = (Get-Date) - $dropStart
        Write-Host "  ✓ DROP done in $($dropElapsed.TotalSeconds.ToString('F1')) s"

        # 验证 chunk 索引也被 cascade drop
        $remaining = & $psql -U xin -d quantmind_v2 -h localhost -t -c "SELECT COUNT(*) FROM pg_stat_user_indexes WHERE schemaname='_timescaledb_internal' AND indexrelname LIKE '%idx_fv_factor_date_covering%'"
        Write-Host "  remaining chunk indexes: $($remaining.Trim()) (应为 0)"

        # DB size 收缩验证
        $newSize = & $psql -U xin -d quantmind_v2 -h localhost -t -c "SELECT pg_size_pretty(pg_database_size('quantmind_v2'))"
        Write-Host "  DB size now: $($newSize.Trim()) (期望减 ~45 GB)"
    }
}

# ─── Phase: vacuum (heavy, 表锁) ────────────────────────────
if ($Phase -eq "vacuum" -or $Phase -eq "all") {
    Write-Host "`n[VACUUM FULL] factor_values (~1-2h, 表锁) ..." -ForegroundColor Yellow
    if ($DryRun) {
        Write-Host "  [DRY-RUN] skip" -ForegroundColor Gray
    } else {
        # VACUUM FULL ANALYZE: 重写表 + 重建索引 + 更新统计
        $vacStart = Get-Date
        & $psql -U xin -d quantmind_v2 -h localhost -c "VACUUM (FULL, ANALYZE, VERBOSE) factor_values" 2>&1 | Tee-Object -FilePath "D:\quantmind-v2\logs\sunday_vacuum_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
        $vacElapsed = (Get-Date) - $vacStart
        Write-Host "  ✓ VACUUM FULL done in $($vacElapsed.TotalMinutes.ToString('F1')) min"

        # 验证 size 收缩
        & $psql -U xin -d quantmind_v2 -h localhost -c "SELECT pg_size_pretty(pg_total_relation_size('factor_values'::regclass))"
    }
}

# ─── Phase: reindex (轻, 单独) ──────────────────────────────
if ($Phase -eq "reindex" -or $Phase -eq "all") {
    Write-Host "`n[REINDEX] factor_values 索引重建 ..." -ForegroundColor Yellow
    Write-Host "  注意: VACUUM FULL 已包含索引重建, REINDEX 只对 VACUUM 后仍 bloat 的索引有用"
    if ($DryRun) {
        Write-Host "  [DRY-RUN] skip" -ForegroundColor Gray
    } else {
        & $psql -U xin -d quantmind_v2 -h localhost -c "REINDEX TABLE CONCURRENTLY factor_values" 2>&1 | Tee-Object -FilePath "D:\quantmind-v2\logs\sunday_reindex_$(Get-Date -Format 'yyyyMMdd_HHmm').log"
    }
}

$elapsed = (Get-Date) - $startTime
Write-Host "`n===== Phase 2 ($Phase) 完成 =====" -ForegroundColor Green
Write-Host "Total: $($elapsed.TotalMinutes.ToString('F1')) min"
