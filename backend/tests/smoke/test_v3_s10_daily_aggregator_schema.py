"""Smoke: V3 §13.2 daily_aggregator SQL specs vs real PG schema (S10 ops).

Closes a real-bug gap discovered during 5d operational kickoff 1:1 test
(2026-05-13): the `llm_cost_total` spec referenced `total_cost_usd` (wrong) on
`llm_cost_daily.date` (wrong column name) — actual schema has `cost_usd_total`
on `day`. The existing `test_daily_aggregator.py` uses a `MagicMock` conn so
the SQL string is never parsed by PG, and the column-name drift was masked
until production fire surfaced an `ERROR/MainProcess` line.

This smoke test prevents that pattern: each entry in `_DEFAULT_SPECS` is run
against a real PG connection with a no-data sentinel date — PG parses + binds
+ executes, so column-name / table-name drift surfaces as a smoke failure
rather than a silent production WARN.

铁律 10b 意图: 单测 mock conn 永远绿不等于生产 PG schema 兼容. 本 smoke
连真 PG run 每条 SQL spec → catch schema drift.
"""

from __future__ import annotations

from datetime import date

import psycopg2
import pytest

from app.services.db import get_sync_conn
from backend.qm_platform.risk.metrics.daily_aggregator import (
    _DEFAULT_SPECS,
    aggregate_daily_metrics,
)


@pytest.mark.smoke
def test_each_spec_sql_parses_against_real_schema() -> None:
    """Each _DEFAULT_SPECS SQL runs against real PG without schema error.

    Uses a sentinel date with no expected data (1900-01-01) — query result
    irrelevant; only that PG accepts the column / table names.
    """
    sentinel_date = date(1900, 1, 1)
    failures: list[str] = []

    conn = get_sync_conn()
    try:
        for key, spec in _DEFAULT_SPECS.items():
            cur = conn.cursor()
            try:
                cur.execute(spec.sql, (sentinel_date,))
                cur.fetchone()
            except psycopg2.Error as e:
                failures.append(f"{key}: {e}")
                conn.rollback()  # reset aborted txn for next spec
            finally:
                cur.close()
    finally:
        conn.close()

    assert not failures, "SQL spec(s) failed against real schema:\n" + "\n".join(failures)


@pytest.mark.smoke
def test_aggregate_daily_metrics_no_warn_against_real_schema(caplog) -> None:
    """aggregate_daily_metrics for an empty date logs 0 query-failed WARNs.

    The bug manifested as a single ERROR log line per fire (silent default=0
    fallback). This test fails if any spec triggers _run_query_safe's exception
    branch — which means any column-name / table-name drift surfaces immediately.
    """
    sentinel_date = date(1900, 1, 1)

    conn = get_sync_conn()
    try:
        with caplog.at_level("ERROR", logger="backend.qm_platform.risk.metrics.daily_aggregator"):
            aggregate_daily_metrics(conn, sentinel_date)
    finally:
        conn.close()

    query_failed_lines = [r.message for r in caplog.records if "query failed" in r.message]
    assert not query_failed_lines, (
        "[daily-aggregator] query failed messages surfaced — schema drift?\n"
        + "\n".join(query_failed_lines)
    )
