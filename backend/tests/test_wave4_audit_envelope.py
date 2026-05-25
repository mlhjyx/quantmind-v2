"""iter 132 — Wave 4 NEW Beat tasks scheduler_task_log audit envelope tests.

Closes W2-A F1+F2 P0 per `docs/audit/W2_A_OBSERVABILITY_MVP41_RUNTIME_VERIFY_2026_05_26.md`:
- 5/5 Wave 4 NEW Beat entries silent execution (0 scheduler_task_log row past 7d
  despite Beat schedule firing at correct cadence per beat-stderr 2728+ occurrences)
- 4/4 Wave 4 task modules 0 `_write_scheduler_log_safe` adoption (LL-204 regression)

Scope iter 132: meta_monitor_tasks + attribution_tasks (2 of 4 modules).
iter 133 will cover backup_tasks (2 tasks) + report_tasks.

Sibling pattern to test_factor_lifecycle_audit_envelope.py (iter 103 PR #479 LL-204 canonical).

铁律 alignment:
- 33 silent_ok: audit helper failure logs warning, does not propagate (verified in test_*_audit_helper_failure_silent).
- 41 UTC: _audit_start uses datetime.now(UTC) internally.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ─────────────────────────────────────────────────────────────
# §1: meta_monitor_tasks audit envelope coverage
# ─────────────────────────────────────────────────────────────


class TestMetaMonitorAuditEnvelope:
    """Verify meta_monitor_tick writes scheduler_task_log on every path (success + error)."""

    def test_writes_success_row_on_clean_tick(self) -> None:
        """Success path → status='success' + result_json containing evaluated/triggered counts."""
        from app.tasks import meta_monitor_tasks as task_mod  # noqa: PLC0415

        # Stub service.collect_and_evaluate → 0 triggered alerts (clean tick)
        fake_alerts: list = []
        fake_service = MagicMock(name="meta_monitor_service")
        fake_service.collect_and_evaluate.return_value = fake_alerts
        fake_service.push_triggered.return_value = []

        # Stub get_sync_conn → mock conn with commit/rollback/close stubs
        fake_conn = MagicMock(name="fake_conn")
        fake_get_conn = MagicMock(return_value=fake_conn)

        with (
            patch.object(task_mod, "_get_service", return_value=fake_service),
            patch("app.services.db.get_sync_conn", fake_get_conn),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            result = task_mod.meta_monitor_tick.apply(args=[]).get()

        assert result["ok"] is True
        assert result["evaluated"] == 0
        assert result["triggered"] == 0
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "meta_monitor"  # task_name canonical
        assert call_args[0][2] == "success"  # status
        # result_json should be the actual result dict
        assert call_args[0][3]["ok"] is True
        assert call_args[0][3]["evaluated"] == 0

    def test_writes_error_row_and_reraises_on_exception(self) -> None:
        """Exception path → status='error' + result_json containing error msg + re-raise."""
        from app.tasks import meta_monitor_tasks as task_mod  # noqa: PLC0415

        # Service.collect_and_evaluate raises → outer envelope catches + re-raises
        fake_service = MagicMock(name="meta_monitor_service")
        fake_service.collect_and_evaluate.side_effect = ValueError("synthetic meta-monitor failure")

        fake_conn = MagicMock(name="fake_conn")
        fake_get_conn = MagicMock(return_value=fake_conn)

        with (
            patch.object(task_mod, "_get_service", return_value=fake_service),
            patch("app.services.db.get_sync_conn", fake_get_conn),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            r = task_mod.meta_monitor_tick.apply(args=[])
            assert r.failed()

        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "meta_monitor"
        assert call_args[0][2] == "error"
        assert call_args[0][3]["status"] == "error"
        assert "ValueError" in call_args[0][3]["error"]
        assert "synthetic meta-monitor failure" in call_args[0][3]["error"]

    def test_envelope_uses_canonical_helper_name(self) -> None:
        """Mutation guard — audit MUST go through _write_scheduler_log_safe.

        Renaming/inlining the helper would silently break sibling daily_pipeline +
        sibling iter 133 attribution/backup/report task pattern. Regression test catches that.
        """
        from app.tasks import meta_monitor_tasks as task_mod  # noqa: PLC0415

        assert hasattr(task_mod, "_write_scheduler_log_safe")
        assert callable(task_mod._write_scheduler_log_safe)

    def test_envelope_helper_silent_on_db_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """Helper signature: silent_ok 铁律 33(c) — DB write failure logs warning, no raise.

        This verifies _write_scheduler_log_safe itself does not crash the task body
        when scheduler_task_log INSERT fails (e.g. PG down). Sibling daily_pipeline.py L97-105 pattern.
        """
        from datetime import UTC, datetime

        from app.tasks import meta_monitor_tasks as task_mod  # noqa: PLC0415

        with (
            patch("app.services.db.get_sync_conn", side_effect=RuntimeError("PG down")),
            caplog.at_level("WARNING", logger="celery.meta_monitor_tasks"),
        ):
            # Helper must NOT raise (silent_ok contract)
            task_mod._write_scheduler_log_safe(
                "meta_monitor", datetime.now(UTC), "success", {"ok": True}
            )

        # Warning logged
        assert any("scheduler_task_log" in rec.message for rec in caplog.records)


# ─────────────────────────────────────────────────────────────
# §2: attribution_tasks audit envelope coverage (fail-soft preserved)
# ─────────────────────────────────────────────────────────────


class TestAttributionAuditEnvelope:
    """Verify daily_attribution_compute_task writes scheduler_task_log on every path.

    Fail-soft contract preserved — exception path RETURNS error dict (no re-raise per
    original `except Exception ... return {error: ...}` semantics at iter 65 build).
    """

    def test_writes_success_row_on_clean_compute(self) -> None:
        """Success path → status='success' + result_json containing trade_date/residual_bps."""
        from app.tasks import attribution_tasks as task_mod  # noqa: PLC0415

        # Stub all upstream attribution chain
        fake_attribution_module = MagicMock(name="attribution_module")
        fake_attribution_initial = MagicMock(name="attribution_initial")
        fake_attribution_initial.trade_date = "2026-05-26"
        fake_attribution_initial.strategy_id = "paper-strategy-default"
        fake_attribution_initial.execution_mode = "paper"
        fake_attribution_initial.nav_change_pct = 0.0
        fake_attribution_initial.by_factor = {}
        fake_attribution_initial.by_sector = {}
        fake_attribution_initial.by_regime = None
        fake_attribution_initial.by_cost = {}
        fake_attribution_initial.alpha_vs_benchmark = 0.0

        fake_attribution_module.DailyAttribution.return_value = fake_attribution_initial
        fake_attribution_module.compute_unexplained_residual.return_value = 0.001
        fake_attribution_module.persist_attribution.return_value = 999
        fake_attribution_module.fire_residual_alert.return_value = False

        fake_conn = MagicMock(name="fake_conn")
        fake_get_pg = MagicMock(return_value=fake_conn)

        with (
            patch.dict(
                "sys.modules",
                {"backend.qm_platform.eval.attribution": fake_attribution_module},
            ),
            # iter 132: patch canonical conn factory (`app.services.db.get_sync_conn`)
            # post W2-A F7 fix at attribution_tasks.py:193 (phantom `app.core.db` removed).
            patch("app.services.db.get_sync_conn", fake_get_pg),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            result = task_mod.daily_attribution_compute_task.apply(args=[]).get()

        assert "trade_date" in result
        assert result["strategy_id"] == "paper-strategy-default"
        assert result["row_id"] == 999

        # iter 132 PR #484 reviewer P2: single-conn lifecycle regression guard.
        # Production bug (W2-A F8 P0): factory `get_pg_connection` passed to
        # persist_attribution → Engine invokes factory (conn #1) + caller invokes
        # factory separately (conn #2). Only conn #2 committed; conn #1 GC'd with
        # uncommitted INSERT → 24+ days silent rollback since iter 65.
        #
        # Two complementary assertions:
        #   (1) `fake_get_pg.call_count == 1` — task body opens conn ONCE in source.
        #       (Narrow: under mocked persist_attribution this only catches accidental
        #       dual-explicit calls; does NOT catch the original factory-bug because
        #       the mock doesn't invoke its first arg. Still useful as forward guard.)
        #   (2) Factory-arg inspection — `persist_attribution(factory, ...)`'s first arg
        #       must be a callable that returns the SAME conn opened by the task body,
        #       not a fresh-conn factory. This catches the actual bug pattern (factory
        #       passed in lieu of `lambda: conn`).
        assert fake_get_pg.call_count == 1, (
            f"Expected single get_sync_conn() call (single-conn lifecycle, "
            f"PR #484 fix), got {fake_get_pg.call_count} — double-open regression?"
        )

        # Inspect what was passed to persist_attribution as the conn_factory arg
        persist_call_args = fake_attribution_module.persist_attribution.call_args
        passed_factory = persist_call_args[0][0]
        # The factory must be a same-conn-returning lambda, NOT the fresh-conn factory
        # itself. Calling it must NOT call get_sync_conn (the lambda captures the
        # already-opened conn) AND must return the SAME conn object.
        get_conn_call_count_before = fake_get_pg.call_count
        factory_returned_conn = passed_factory()
        assert fake_get_pg.call_count == get_conn_call_count_before, (
            "passed factory must NOT call get_sync_conn (must be `lambda: conn`, "
            "not the raw factory) — invoking it bumped call_count, indicating "
            "factory-bug regression (W2-A F8 P0)"
        )
        assert factory_returned_conn is fake_conn, (
            "passed factory must return the SAME conn opened by the task body "
            "(single-conn lifecycle), not a fresh conn"
        )

        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "daily_attribution_compute"
        assert call_args[0][2] == "success"
        assert call_args[0][3]["row_id"] == 999

    def test_writes_error_row_fail_soft_no_reraise(self) -> None:
        """Exception path → status='error' + RETURN error dict (NOT raise — fail-soft preserved)."""
        from app.tasks import attribution_tasks as task_mod  # noqa: PLC0415

        # Force inner exception via failed import
        fake_attribution_module = MagicMock(name="attribution_module")
        fake_attribution_module.DailyAttribution.side_effect = RuntimeError(
            "synthetic attribution failure"
        )

        with (
            patch.dict(
                "sys.modules",
                {"backend.qm_platform.eval.attribution": fake_attribution_module},
            ),
            patch.object(task_mod, "_write_scheduler_log_safe") as mock_audit,
        ):
            # apply().get() returns result instead of raising (fail-soft contract)
            result = task_mod.daily_attribution_compute_task.apply(args=[]).get()

        # Fail-soft: returns error dict, does not raise
        assert "error" in result
        assert "synthetic attribution failure" in result["error"]
        assert result["trade_date"] == "today"

        # Envelope still wrote audit row
        mock_audit.assert_called_once()
        call_args = mock_audit.call_args
        assert call_args[0][0] == "daily_attribution_compute"
        assert call_args[0][2] == "error"
        assert call_args[0][3]["status"] == "error"
        assert "RuntimeError" in call_args[0][3]["error"]

    def test_envelope_uses_canonical_helper_name(self) -> None:
        """Mutation guard — audit MUST go through _write_scheduler_log_safe."""
        from app.tasks import attribution_tasks as task_mod  # noqa: PLC0415

        assert hasattr(task_mod, "_write_scheduler_log_safe")
        assert callable(task_mod._write_scheduler_log_safe)

    def test_envelope_helper_silent_on_db_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        """Helper signature: silent_ok 铁律 33(c) — DB write failure logs warning, no raise."""
        from datetime import UTC, datetime

        from app.tasks import attribution_tasks as task_mod  # noqa: PLC0415

        with (
            patch("app.services.db.get_sync_conn", side_effect=RuntimeError("PG down")),
            caplog.at_level("WARNING"),
        ):
            task_mod._write_scheduler_log_safe(
                "daily_attribution_compute",
                datetime.now(UTC),
                "success",
                {"row_id": 1},
            )

        assert any("scheduler_task_log" in rec.message for rec in caplog.records)


# ─────────────────────────────────────────────────────────────
# §3: cross-module canonical pattern parity (sibling consistency)
# ─────────────────────────────────────────────────────────────


class TestCanonicalPatternParity:
    """Verify iter 132 module-local helpers retain identical signature to iter 103 canonical.

    iter 134+ promotion to shared service candidate when 5+ callers established
    (LL-206 sibling consolidation pattern). Until then, this test ensures signature
    drift doesn't silently break the planned consolidation refactor.
    """

    def test_meta_monitor_helper_signature_matches_daily_pipeline(self) -> None:
        """meta_monitor_tasks._write_scheduler_log_safe MUST match daily_pipeline helper signature."""
        import inspect

        from app.tasks import daily_pipeline, meta_monitor_tasks  # noqa: PLC0415

        sig_meta = inspect.signature(meta_monitor_tasks._write_scheduler_log_safe)
        sig_canon = inspect.signature(daily_pipeline._write_scheduler_log_safe)

        # Same param names + same param count
        assert list(sig_meta.parameters.keys()) == list(sig_canon.parameters.keys())

    def test_attribution_helper_signature_matches_daily_pipeline(self) -> None:
        """attribution_tasks._write_scheduler_log_safe MUST match daily_pipeline helper signature."""
        import inspect

        from app.tasks import attribution_tasks, daily_pipeline  # noqa: PLC0415

        sig_attr = inspect.signature(attribution_tasks._write_scheduler_log_safe)
        sig_canon = inspect.signature(daily_pipeline._write_scheduler_log_safe)

        assert list(sig_attr.parameters.keys()) == list(sig_canon.parameters.keys())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
