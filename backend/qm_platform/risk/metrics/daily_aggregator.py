"""DailyMetricsAggregator — V3 §13.2 risk_metrics_daily 日聚合 (S10).

V3 §13.2: 风控系统自身 KPI 日聚合. 由 daily Beat 任务调用 (e.g. 16:30 收市后),
聚合昨日 risk_event_log + execution_plans + llm_cost_daily + news_raw 等
source tables → upsert risk_metrics_daily 1 row per date.

Layered architecture:
  - Engine (this file) — PURE: SELECT 聚合查询 + 数据 dict 组装, 0 conn.commit
  - Caller (scripts/v3_paper_mode_5d_extract_metrics.py) — DB conn 获取 +
    commit + Celery Beat 周期触发

铁律 31 not strictly invoked (SQL is IO-adjacent but caller owns conn).
铁律 32 sustained: 0 conn.commit in this module. conn.rollback() IS called inside
  `_run_query_safe` ONLY to reset PG transaction state after per-query errors
  (required by psycopg2 — without this, subsequent queries fail with
  "InFailedSqlTransaction" cascading). This is NOT a transaction boundary
  operation — it's per-query error recovery. Caller still owns the outer
  commit() and any savepoint semantics.
铁律 33 sustained: missing source tables → log warn + return 0 for that metric
  (反 silent skip the entire aggregation; partial metric is better than no
  metric at all on first-week before all tables populated).

V3 §15.4 验收指标 (4 项, 由 verify_report 检查 5d 累计):
  - P0 alert 误报率 < 30% (本表写 raw count; 误报率 verify 报告侧 join trade_log)
  - L1 detection latency P99 < 5s (本表 detection_latency_p99_ms)
  - L4 STAGED 流程闭环 0 失败 (本表 staged_executed + staged_cancelled +
    staged_timeout_executed; verify 报告侧 sum + check 0 FAILED state)
  - 元监控 0 P0 元告警 (本表不写 元告警; verify 报告侧 check 元告警 table)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyMetricsSpec:
    """Source table + query name → tuple for one column in risk_metrics_daily.

    Used internally by aggregate_daily_metrics to drive query dispatch.
    Frozen so each metric's spec is immutable across runs.
    """

    column: str  # target column in risk_metrics_daily
    sql: str  # SELECT returning a single scalar (with %s placeholder for date)
    default_on_missing: Any = 0  # value if source table missing / query fails


@dataclass
class DailyMetricsResult:
    """One day's aggregated KPIs (mirrors risk_metrics_daily columns)."""

    date: date
    # L0
    news_ingested_count: int = 0
    news_source_failures: dict[str, int] = field(default_factory=dict)
    fundamental_ingest_success_rate: float | None = None
    # L1
    alerts_p0_count: int = 0
    alerts_p1_count: int = 0
    alerts_p2_count: int = 0
    detection_latency_p50_ms: int | None = None
    detection_latency_p99_ms: int | None = None
    # L2
    sentiment_calls_count: int = 0
    sentiment_avg_cost: float | None = None
    rag_retrievals_count: int = 0
    # L4
    staged_plans_count: int = 0
    staged_executed_count: int = 0
    staged_cancelled_count: int = 0
    staged_timeout_executed_count: int = 0
    auto_triggered_count: int = 0
    # L5
    reflector_weekly_completed: bool = False
    reflector_lessons_added: int = 0
    # Cost
    llm_cost_total: float = 0.0


# SQL specs per metric. Caller may swap individual queries via spec override
# (e.g. for testing or future schema changes).
#
# Reviewer P2 (code-reviewer + db-reviewer cross-finding): 9 columns are
# populated via spec queries below (alerts P0/P1/P2 + staged 5 states + llm_cost).
# The remaining 11 DailyMetricsResult fields are INTENTIONALLY left at dataclass
# defaults until their source tables are wired:
#   - news_ingested_count / news_source_failures — L0 NewsIngestionService (S11+)
#   - fundamental_ingest_success_rate — L0.3 FundamentalContext (S4 minimal exists)
#   - detection_latency_p50_ms / detection_latency_p99_ms — L1 latency
#     instrumentation (needs risk_event_log latency_ms column or histogram cache)
#   - sentiment_calls_count / sentiment_avg_cost / rag_retrievals_count — L2
#     pipeline metrics (Tier B scope)
#   - reflector_weekly_completed / reflector_lessons_added — L5 RiskReflector
#     (Tier B scope)
# These can be added via spec override once source tables/columns exist.
_DEFAULT_SPECS: dict[str, DailyMetricsSpec] = {
    "alerts_p0_count": DailyMetricsSpec(
        column="alerts_p0_count",
        sql=(
            "SELECT COUNT(*) FROM risk_event_log "
            "WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai') = %s "
            "AND severity = 'P0'"
        ),
    ),
    "alerts_p1_count": DailyMetricsSpec(
        column="alerts_p1_count",
        sql=(
            "SELECT COUNT(*) FROM risk_event_log "
            "WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai') = %s "
            "AND severity = 'P1'"
        ),
    ),
    "alerts_p2_count": DailyMetricsSpec(
        column="alerts_p2_count",
        sql=(
            "SELECT COUNT(*) FROM risk_event_log "
            "WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai') = %s "
            "AND severity = 'P2'"
        ),
    ),
    "staged_plans_count": DailyMetricsSpec(
        column="staged_plans_count",
        sql=(
            "SELECT COUNT(*) FROM execution_plans "
            "WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai') = %s "
            "AND mode = 'STAGED'"
        ),
    ),
    "staged_executed_count": DailyMetricsSpec(
        column="staged_executed_count",
        sql=(
            "SELECT COUNT(*) FROM execution_plans "
            "WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai') = %s "
            "AND status = 'EXECUTED'"
        ),
    ),
    "staged_cancelled_count": DailyMetricsSpec(
        column="staged_cancelled_count",
        sql=(
            "SELECT COUNT(*) FROM execution_plans "
            "WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai') = %s "
            "AND status = 'CANCELLED'"
        ),
    ),
    "staged_timeout_executed_count": DailyMetricsSpec(
        column="staged_timeout_executed_count",
        sql=(
            "SELECT COUNT(*) FROM execution_plans "
            "WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai') = %s "
            "AND status = 'TIMEOUT_EXECUTED'"
        ),
    ),
    "auto_triggered_count": DailyMetricsSpec(
        column="auto_triggered_count",
        sql=(
            "SELECT COUNT(*) FROM execution_plans "
            "WHERE date_trunc('day', created_at AT TIME ZONE 'Asia/Shanghai') = %s "
            "AND mode = 'AUTO'"
        ),
    ),
    "llm_cost_total": DailyMetricsSpec(
        column="llm_cost_total",
        sql="SELECT COALESCE(SUM(total_cost_usd), 0) FROM llm_cost_daily WHERE date = %s",
        default_on_missing=0.0,
    ),
}


def aggregate_daily_metrics(
    conn: Any,
    target_date: date,
    *,
    specs: dict[str, DailyMetricsSpec] | None = None,
) -> DailyMetricsResult:
    """Run all metric queries for one date; return DailyMetricsResult.

    Args:
        conn: psycopg2 connection (caller manages commit).
        target_date: the day being aggregated.
        specs: optional override for individual metric specs (testing /
            future schema changes). None → use _DEFAULT_SPECS.

    Returns:
        DailyMetricsResult with all metrics populated. Missing source tables
        / query errors → log + use spec.default_on_missing for that column.

    Raises:
        Nothing — per铁律 33, this aggregator never blocks the entire day's
        rollup just because one source table is missing (e.g. llm_cost_daily
        not yet created on first day of paper-mode). Individual query failures
        are logged + counted as 0. If you want fail-loud, run queries directly.
    """
    active_specs = specs or _DEFAULT_SPECS
    result = DailyMetricsResult(date=target_date)

    for key, spec in active_specs.items():
        value = _run_query_safe(conn, spec.sql, target_date, spec.default_on_missing)
        # Map back to the dataclass field. We use dynamic setattr since
        # the dataclass is non-frozen.
        try:
            setattr(result, spec.column, value)
        except AttributeError:
            logger.warning(
                "[daily-aggregator] unknown column %s in spec %s — skipped",
                spec.column,
                key,
            )

    return result


def upsert_daily_metrics(conn: Any, result: DailyMetricsResult) -> int:
    """UPSERT one risk_metrics_daily row from DailyMetricsResult.

    Args:
        conn: psycopg2 connection (caller manages commit).
        result: assembled DailyMetricsResult.

    Returns:
        rowcount (1 on insert, 1 on update). 0 only on driver-level no-op.

    Raises:
        psycopg2.Error: any DB error propagates (caller decides rollback).
    """
    import json

    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO risk_metrics_daily (
                date,
                news_ingested_count, news_source_failures, fundamental_ingest_success_rate,
                alerts_p0_count, alerts_p1_count, alerts_p2_count,
                detection_latency_p50_ms, detection_latency_p99_ms,
                sentiment_calls_count, sentiment_avg_cost, rag_retrievals_count,
                staged_plans_count, staged_executed_count, staged_cancelled_count,
                staged_timeout_executed_count, auto_triggered_count,
                reflector_weekly_completed, reflector_lessons_added,
                llm_cost_total,
                created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
            )
            ON CONFLICT (date) DO UPDATE SET
                news_ingested_count = EXCLUDED.news_ingested_count,
                news_source_failures = EXCLUDED.news_source_failures,
                fundamental_ingest_success_rate = EXCLUDED.fundamental_ingest_success_rate,
                alerts_p0_count = EXCLUDED.alerts_p0_count,
                alerts_p1_count = EXCLUDED.alerts_p1_count,
                alerts_p2_count = EXCLUDED.alerts_p2_count,
                detection_latency_p50_ms = EXCLUDED.detection_latency_p50_ms,
                detection_latency_p99_ms = EXCLUDED.detection_latency_p99_ms,
                sentiment_calls_count = EXCLUDED.sentiment_calls_count,
                sentiment_avg_cost = EXCLUDED.sentiment_avg_cost,
                rag_retrievals_count = EXCLUDED.rag_retrievals_count,
                staged_plans_count = EXCLUDED.staged_plans_count,
                staged_executed_count = EXCLUDED.staged_executed_count,
                staged_cancelled_count = EXCLUDED.staged_cancelled_count,
                staged_timeout_executed_count = EXCLUDED.staged_timeout_executed_count,
                auto_triggered_count = EXCLUDED.auto_triggered_count,
                reflector_weekly_completed = EXCLUDED.reflector_weekly_completed,
                reflector_lessons_added = EXCLUDED.reflector_lessons_added,
                llm_cost_total = EXCLUDED.llm_cost_total,
                updated_at = NOW()
            """,
            (
                result.date,
                result.news_ingested_count,
                json.dumps(result.news_source_failures),
                result.fundamental_ingest_success_rate,
                result.alerts_p0_count,
                result.alerts_p1_count,
                result.alerts_p2_count,
                result.detection_latency_p50_ms,
                result.detection_latency_p99_ms,
                result.sentiment_calls_count,
                result.sentiment_avg_cost,
                result.rag_retrievals_count,
                result.staged_plans_count,
                result.staged_executed_count,
                result.staged_cancelled_count,
                result.staged_timeout_executed_count,
                result.auto_triggered_count,
                result.reflector_weekly_completed,
                result.reflector_lessons_added,
                result.llm_cost_total,
            ),
        )
        return cur.rowcount
    finally:
        cur.close()


# ── Helpers ──


def _run_query_safe(
    conn: Any,
    sql: str,
    target_date: date,
    default_on_missing: Any,
) -> Any:
    """Execute a single-scalar SELECT; on any error log + return default.

    Used to avoid the entire day's rollup failing when one source table is
    missing (e.g. llm_cost_daily not yet present on day 1 of paper-mode).
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, (target_date,))
        row = cur.fetchone()
        if row is None or row[0] is None:
            return default_on_missing
        return row[0]
    except Exception:
        logger.exception(
            "[daily-aggregator] query failed (returning default=%s): sql=%s",
            default_on_missing,
            sql[:80],
        )
        # Reset the failed transaction so subsequent queries on this conn
        # don't all fail with "current transaction is aborted".
        try:
            conn.rollback()
        except Exception:
            logger.exception("[daily-aggregator] rollback after query error failed")
        return default_on_missing
    finally:
        cur.close()


__all__ = [
    "DailyMetricsResult",
    "DailyMetricsSpec",
    "aggregate_daily_metrics",
    "upsert_daily_metrics",
]
