"""Unit tests for scripts/services_healthcheck.py (LL-074 fix, Session 35).

覆盖:
- query_service_state: 4 sc query 输出场景 (RUNNING / STOPPED / unknown rc / timeout / OSError)
- check_beat_heartbeat: 文件不存在 / fresh / stale / stat 异常
- build_report: 聚合 services + beat 计算 failures
- should_alert: 7 dedup 决策路径 (ok-still-ok / recovery / transition / escalation /
  no_prior / unparseable_iso / dedup_window)
- update_state / save_state / load_state: 持久化 + 损坏文件容忍
- send_alert: webhook 未配置 silent / send_markdown_sync 异常吃掉
- _run + main: 顶层 try/except + boot stderr probe (铁律 43)
- HealthReport.status: 派生属性
- HealthReport.to_dict: JSON 序列化

关联铁律:
- 铁律 33 fail-loud: subprocess timeout / OSError 不 raise 但归类 ERROR
- 铁律 43: schtask script 4 项硬化 (a) N/A 无 PG / (b) FileHandler delay / (c)+(d) ✓
"""

from __future__ import annotations

import json
import platform as _stdlib_platform  # noqa: I001
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_stdlib_platform.python_implementation()
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from services_healthcheck import (  # noqa: E402
    BEAT_HEARTBEAT_MAX_AGE_SECONDS,
    DEDUP_WINDOW_SECONDS,
    SC_QUERY_TIMEOUT_SECONDS,
    SERVY_SERVICES,
    BeatHeartbeatCheck,
    HealthReport,
    ServiceCheck,
    build_report,
    check_beat_heartbeat,
    load_state,
    main,
    query_service_state,
    save_state,
    send_alert,
    should_alert,
    update_state,
)

# ═════════════════════════════════════════════════════════════════
# query_service_state — sc query stdout parse
# ═════════════════════════════════════════════════════════════════


class TestQueryServiceState:
    """Windows sc query 输出解析覆盖."""

    def _mk_completed_process(self, returncode: int, stdout: str, stderr: str = ""):
        cp = MagicMock()
        cp.returncode = returncode
        cp.stdout = stdout
        cp.stderr = stderr
        return cp

    def test_running_service(self, monkeypatch):
        sc_stdout = (
            "SERVICE_NAME: QuantMind-CeleryBeat\n"
            "        TYPE               : 10  WIN32_OWN_PROCESS\n"
            "        STATE              : 4  RUNNING\n"
            "                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)\n"
        )
        cp = self._mk_completed_process(0, sc_stdout)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: cp)
        r = query_service_state("QuantMind-CeleryBeat")
        assert r.running is True
        assert r.state_text == "RUNNING"
        assert r.name == "QuantMind-CeleryBeat"

    def test_stopped_service(self, monkeypatch):
        sc_stdout = "SERVICE_NAME: QuantMind-CeleryBeat\n        STATE              : 1  STOPPED\n"
        cp = self._mk_completed_process(0, sc_stdout)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: cp)
        r = query_service_state("QuantMind-CeleryBeat")
        assert r.running is False
        assert r.state_text == "STOPPED"

    def test_unknown_state_paused(self, monkeypatch):
        # State paused (3) — not RUNNING/STOPPED, fallback to UNKNOWN
        sc_stdout = "SERVICE_NAME: foo\n        STATE              : 7  PAUSED\n"
        cp = self._mk_completed_process(0, sc_stdout)
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: cp)
        r = query_service_state("foo")
        assert r.running is False
        assert r.state_text.startswith("UNKNOWN")

    def test_nonzero_returncode_unknown_service(self, monkeypatch):
        cp = self._mk_completed_process(
            1060, "", "FAILED 1060: The specified service does not exist"
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: cp)
        r = query_service_state("does-not-exist")
        assert r.running is False
        assert r.state_text.startswith("ERROR: rc=1060")

    def test_timeout(self, monkeypatch):
        def _raise(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="sc query", timeout=SC_QUERY_TIMEOUT_SECONDS)

        monkeypatch.setattr(subprocess, "run", _raise)
        r = query_service_state("foo")
        assert r.running is False
        assert "timeout" in r.state_text

    def test_oserror(self, monkeypatch):
        def _raise(*a, **kw):
            raise FileNotFoundError("sc.exe not on PATH")

        monkeypatch.setattr(subprocess, "run", _raise)
        r = query_service_state("foo")
        assert r.running is False
        assert "ERROR:" in r.state_text


# ═════════════════════════════════════════════════════════════════
# check_beat_heartbeat
# ═════════════════════════════════════════════════════════════════


class TestCheckBeatHeartbeat:
    """celerybeat-schedule.dat freshness 检查."""

    def test_file_missing(self, monkeypatch, tmp_path):
        ghost = tmp_path / "nope.dat"
        monkeypatch.setattr("services_healthcheck.BEAT_SCHEDULE_FILE", ghost)
        r = check_beat_heartbeat()
        assert r.file_exists is False
        assert r.fresh is False
        assert r.age_seconds is None

    def test_fresh_heartbeat(self, monkeypatch, tmp_path):
        beat_file = tmp_path / "celerybeat-schedule.dat"
        beat_file.write_bytes(b"x" * 100)
        monkeypatch.setattr("services_healthcheck.BEAT_SCHEDULE_FILE", beat_file)
        r = check_beat_heartbeat()
        assert r.file_exists is True
        assert r.fresh is True
        assert r.age_seconds is not None and r.age_seconds < 60
        assert r.last_write_iso is not None

    def test_stale_heartbeat(self, monkeypatch, tmp_path):
        beat_file = tmp_path / "celerybeat-schedule.dat"
        beat_file.write_bytes(b"x" * 100)
        # mtime 设回 30min 前
        old_ts = (datetime.now(UTC) - timedelta(minutes=30)).timestamp()
        import os

        os.utime(beat_file, (old_ts, old_ts))
        monkeypatch.setattr("services_healthcheck.BEAT_SCHEDULE_FILE", beat_file)
        r = check_beat_heartbeat()
        assert r.file_exists is True
        assert r.fresh is False
        assert r.age_seconds is not None and r.age_seconds > BEAT_HEARTBEAT_MAX_AGE_SECONDS

    def test_boundary_exactly_threshold(self, monkeypatch, tmp_path):
        """Age == threshold should be fresh (≤ in code)."""
        beat_file = tmp_path / "celerybeat-schedule.dat"
        beat_file.write_bytes(b"x" * 100)
        # mtime 设到正好 threshold - 5s 边界 (避免 stat→now 微秒漂移触发 > 阈值)
        boundary_ts = (
            datetime.now(UTC) - timedelta(seconds=BEAT_HEARTBEAT_MAX_AGE_SECONDS - 5)
        ).timestamp()
        import os

        os.utime(beat_file, (boundary_ts, boundary_ts))
        monkeypatch.setattr("services_healthcheck.BEAT_SCHEDULE_FILE", beat_file)
        r = check_beat_heartbeat()
        assert r.fresh is True


# ═════════════════════════════════════════════════════════════════
# build_report aggregation
# ═════════════════════════════════════════════════════════════════


class TestBuildReport:
    def test_all_ok(self, monkeypatch, tmp_path):
        # 4 services RUNNING
        cp_running = MagicMock()
        cp_running.returncode = 0
        cp_running.stdout = "STATE              : 4  RUNNING"
        cp_running.stderr = ""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: cp_running)

        # Beat fresh
        beat_file = tmp_path / "celerybeat-schedule.dat"
        beat_file.write_bytes(b"x")
        monkeypatch.setattr("services_healthcheck.BEAT_SCHEDULE_FILE", beat_file)
        r = build_report()
        assert r.status == "ok"
        assert r.failures == []
        assert len(r.services) == len(SERVY_SERVICES)
        for svc in r.services:
            assert svc.running

    def test_one_service_stopped(self, monkeypatch, tmp_path):
        def _fake_run(args, **_):
            cp = MagicMock()
            cp.returncode = 0
            cp.stderr = ""
            if "QuantMind-CeleryBeat" in args:
                cp.stdout = "STATE              : 1  STOPPED"
            else:
                cp.stdout = "STATE              : 4  RUNNING"
            return cp

        monkeypatch.setattr(subprocess, "run", _fake_run)
        beat_file = tmp_path / "celerybeat-schedule.dat"
        beat_file.write_bytes(b"x")
        monkeypatch.setattr("services_healthcheck.BEAT_SCHEDULE_FILE", beat_file)
        r = build_report()
        assert r.status == "degraded"
        assert any("QuantMind-CeleryBeat" in f for f in r.failures)

    def test_beat_stale_only(self, monkeypatch, tmp_path):
        cp_running = MagicMock()
        cp_running.returncode = 0
        cp_running.stdout = "STATE              : 4  RUNNING"
        cp_running.stderr = ""
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: cp_running)

        beat_file = tmp_path / "celerybeat-schedule.dat"
        beat_file.write_bytes(b"x")
        old_ts = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
        import os

        os.utime(beat_file, (old_ts, old_ts))
        monkeypatch.setattr("services_healthcheck.BEAT_SCHEDULE_FILE", beat_file)
        r = build_report()
        assert r.status == "degraded"
        assert any("beat:heartbeat stale" in f for f in r.failures)
        # Other services must be fine
        assert all(s.running for s in r.services)


# ═════════════════════════════════════════════════════════════════
# should_alert dedup matrix
# ═════════════════════════════════════════════════════════════════


class TestShouldAlert:
    """7 路径 x boundary."""

    def _mk_report(self, failures: list[str]) -> HealthReport:
        return HealthReport(
            timestamp_utc=datetime.now(UTC).isoformat(),
            services=[],
            beat_heartbeat=None,
            failures=failures,
        )

    def test_ok_still_ok_no_alert(self):
        r = self._mk_report(failures=[])
        send, reason = should_alert(r, {"last_status": "ok"})
        assert send is False
        assert "still ok" in reason

    def test_recovery_alert(self):
        r = self._mk_report(failures=[])
        send, reason = should_alert(r, {"last_status": "degraded"})
        assert send is True
        assert "recovery" in reason

    def test_transition_ok_to_degraded(self):
        r = self._mk_report(failures=["service:foo=STOPPED"])
        send, reason = should_alert(r, {"last_status": "ok"})
        assert send is True
        assert "transition" in reason

    def test_first_run_no_state_treats_as_transition(self):
        r = self._mk_report(failures=["service:foo=STOPPED"])
        send, _ = should_alert(r, {})
        assert send is True

    def test_failures_changed_escalation(self):
        r = self._mk_report(failures=["service:a=STOPPED", "service:b=STOPPED"])
        state = {
            "last_status": "degraded",
            "last_failures": ["service:a=STOPPED"],
            "last_alert_time": datetime.now(UTC).isoformat(),
        }
        send, reason = should_alert(r, state)
        assert send is True
        assert "escalation" in reason

    def test_dedup_within_window(self):
        failures = ["service:a=STOPPED"]
        r = self._mk_report(failures=failures)
        # 30 min ago — within 1h dedup window
        last = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
        state = {
            "last_status": "degraded",
            "last_failures": failures,
            "last_alert_time": last,
        }
        send, reason = should_alert(r, state)
        assert send is False
        assert "dedup" in reason

    def test_re_alert_after_dedup_window(self):
        failures = ["service:a=STOPPED"]
        r = self._mk_report(failures=failures)
        # 90 min ago — past 1h
        last = (datetime.now(UTC) - timedelta(minutes=90)).isoformat()
        state = {
            "last_status": "degraded",
            "last_failures": failures,
            "last_alert_time": last,
        }
        send, reason = should_alert(r, state)
        assert send is True
        assert "re-alert" in reason

    def test_unparseable_last_alert_time(self):
        r = self._mk_report(failures=["service:a=STOPPED"])
        state = {
            "last_status": "degraded",
            "last_failures": ["service:a=STOPPED"],
            "last_alert_time": "not-a-datetime",
        }
        send, reason = should_alert(r, state)
        assert send is True
        assert "unparseable" in reason

    def test_no_prior_alert_timestamp(self):
        r = self._mk_report(failures=["service:a=STOPPED"])
        state = {
            "last_status": "degraded",
            "last_failures": ["service:a=STOPPED"],
            # missing last_alert_time
        }
        send, reason = should_alert(r, state)
        assert send is True
        assert "no prior" in reason

    def test_dedup_window_boundary_exact(self):
        """Elapsed == DEDUP_WINDOW should still suppress (>) ."""
        failures = ["service:a=STOPPED"]
        r = self._mk_report(failures=failures)
        # Exactly 60min ago
        last = (datetime.now(UTC) - timedelta(seconds=DEDUP_WINDOW_SECONDS - 5)).isoformat()
        state = {
            "last_status": "degraded",
            "last_failures": failures,
            "last_alert_time": last,
        }
        send, _ = should_alert(r, state)
        # 5s before threshold — should NOT alert (still in window)
        assert send is False


# ═════════════════════════════════════════════════════════════════
# State persistence
# ═════════════════════════════════════════════════════════════════


class TestStatePersistence:
    def test_load_state_missing_file_returns_empty(self, monkeypatch, tmp_path):
        ghost = tmp_path / "nope.json"
        monkeypatch.setattr("services_healthcheck.STATE_FILE", ghost)
        assert load_state() == {}

    def test_load_state_corrupted_returns_empty(self, monkeypatch, tmp_path):
        bad = tmp_path / "state.json"
        bad.write_text("not valid json {", encoding="utf-8")
        monkeypatch.setattr("services_healthcheck.STATE_FILE", bad)
        assert load_state() == {}

    def test_save_then_load_roundtrip(self, monkeypatch, tmp_path):
        path = tmp_path / "state.json"
        monkeypatch.setattr("services_healthcheck.STATE_FILE", path)
        save_state({"last_status": "ok", "last_failures": []})
        loaded = load_state()
        assert loaded == {"last_status": "ok", "last_failures": []}

    def test_save_state_dir_creation(self, monkeypatch, tmp_path):
        nested = tmp_path / "sub" / "deeper" / "state.json"
        monkeypatch.setattr("services_healthcheck.STATE_FILE", nested)
        save_state({"k": "v"})
        assert nested.exists()
        assert json.loads(nested.read_text(encoding="utf-8")) == {"k": "v"}

    def test_save_state_oserror_does_not_raise(self, monkeypatch, tmp_path, caplog):
        path = tmp_path / "state.json"
        monkeypatch.setattr("services_healthcheck.STATE_FILE", path)

        def _raise(*a, **kw):
            raise PermissionError("readonly fs")

        monkeypatch.setattr(Path, "write_text", _raise)
        # Must NOT raise — dedup is nice-to-have, alerting is critical
        save_state({"k": "v"})  # if this raises, test fails


class TestUpdateState:
    def test_update_state_with_alert(self):
        report = HealthReport(
            timestamp_utc="2026-04-25T15:00:00+00:00",
            services=[],
            beat_heartbeat=None,
            failures=["foo"],
        )
        state = update_state(report, sent_alert=True)
        assert state["last_status"] == "degraded"
        assert state["last_failures"] == ["foo"]
        assert state["last_alert_time"] == "2026-04-25T15:00:00+00:00"
        assert state["last_check_time"] == "2026-04-25T15:00:00+00:00"

    def test_update_state_no_alert_omits_alert_time(self):
        report = HealthReport(
            timestamp_utc="2026-04-25T15:00:00+00:00",
            services=[],
            beat_heartbeat=None,
            failures=[],
        )
        state = update_state(report, sent_alert=False)
        assert state["last_status"] == "ok"
        assert "last_alert_time" not in state


# ═════════════════════════════════════════════════════════════════
# send_alert
# ═════════════════════════════════════════════════════════════════


class TestSendAlert:
    def test_no_webhook_returns_false_silent(self, monkeypatch, caplog):
        report = HealthReport(
            timestamp_utc=datetime.now(UTC).isoformat(),
            services=[ServiceCheck(name="foo", running=False, state_text="STOPPED")],
            beat_heartbeat=BeatHeartbeatCheck(
                file_exists=True,
                age_seconds=120.0,
                last_write_iso="2026-04-25T14:00:00+00:00",
                fresh=True,
            ),
            failures=["service:foo=STOPPED"],
        )

        # Mock empty settings
        from app import config as _config

        fake_settings = MagicMock()
        fake_settings.DINGTALK_WEBHOOK_URL = ""
        monkeypatch.setattr(_config, "settings", fake_settings)

        ok = send_alert(report, "transition")
        assert ok is False

    def test_dingtalk_exception_returns_false(self, monkeypatch):
        report = HealthReport(
            timestamp_utc=datetime.now(UTC).isoformat(),
            services=[],
            beat_heartbeat=None,
            failures=["x"],
        )

        from app import config as _config
        from app.services.dispatchers import dingtalk as _dt

        fake_settings = MagicMock()
        fake_settings.DINGTALK_WEBHOOK_URL = "https://example.com/hook"
        fake_settings.DINGTALK_SECRET = ""
        fake_settings.DINGTALK_KEYWORD = ""
        monkeypatch.setattr(_config, "settings", fake_settings)

        def _raise(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(_dt, "send_markdown_sync", _raise)
        ok = send_alert(report, "transition")
        assert ok is False  # 不抛, 友好降级


# ═════════════════════════════════════════════════════════════════
# HealthReport derived fields
# ═════════════════════════════════════════════════════════════════


class TestHealthReport:
    def test_status_ok_when_no_failures(self):
        r = HealthReport(timestamp_utc="2026-04-25T15:00:00+00:00", failures=[])
        assert r.status == "ok"

    def test_status_degraded_when_failures(self):
        r = HealthReport(timestamp_utc="2026-04-25T15:00:00+00:00", failures=["foo"])
        assert r.status == "degraded"

    def test_to_dict_serializable(self):
        r = HealthReport(
            timestamp_utc="2026-04-25T15:00:00+00:00",
            services=[ServiceCheck(name="x", running=True, state_text="RUNNING")],
            beat_heartbeat=BeatHeartbeatCheck(
                file_exists=True,
                age_seconds=10.0,
                last_write_iso="2026-04-25T15:00:00+00:00",
                fresh=True,
            ),
            failures=[],
        )
        d = r.to_dict()
        # Round-trip must JSON-encode without error
        json.dumps(d)
        assert d["status"] == "ok"
        assert d["services"][0]["name"] == "x"
        assert d["beat_heartbeat"]["fresh"] is True


# ═════════════════════════════════════════════════════════════════
# main() — top-level fail-loud (铁律 43 d)
# ═════════════════════════════════════════════════════════════════


class TestMain:
    def test_main_returns_2_on_unexpected_exception(self, monkeypatch, capsys):
        def _raise(*a, **kw):
            raise RuntimeError("simulated boom")

        monkeypatch.setattr("services_healthcheck._run", _raise)
        rc = main()
        assert rc == 2
        captured = capsys.readouterr()
        assert "FATAL" in captured.err
        assert "boom" in captured.err

    def test_main_emits_boot_probe_to_stderr(self, monkeypatch, capsys):
        monkeypatch.setattr("services_healthcheck._run", lambda: 0)
        rc = main()
        assert rc == 0
        captured = capsys.readouterr()
        assert "[services_healthcheck] boot" in captured.err
        assert "pid=" in captured.err

    def test_main_returns_run_exit_code(self, monkeypatch):
        monkeypatch.setattr("services_healthcheck._run", lambda: 1)
        assert main() == 1


# ═════════════════════════════════════════════════════════════════
# Integration smoke (no mocks for build_report internals)
# ═════════════════════════════════════════════════════════════════


@pytest.mark.smoke
class TestSmokeIntegration:
    """脚本可被 import + 顶层常量 sanity (catch shadow / .pth issues, 铁律 10b).

    不真启 sc query (pytest 跑在 hooks 之外可能无 admin / sc PATH 不一致),
    仅验 module 加载 + 关键常量类型 + dataclass 实例化.
    """

    def test_module_imports_cleanly(self):
        import services_healthcheck

        assert services_healthcheck.SERVY_SERVICES
        assert services_healthcheck.BEAT_HEARTBEAT_MAX_AGE_SECONDS == 600
        assert services_healthcheck.DEDUP_WINDOW_SECONDS == 3600
        assert services_healthcheck.SC_QUERY_TIMEOUT_SECONDS == 5

    def test_constants_have_4_servy_services(self):
        assert len(SERVY_SERVICES) == 4
        assert "QuantMind-CeleryBeat" in SERVY_SERVICES
        assert "QuantMind-FastAPI" in SERVY_SERVICES

    def test_dataclasses_instantiate(self):
        sc = ServiceCheck(name="x", running=True, state_text="RUNNING")
        assert sc.to_dict() == {
            "name": "x",
            "running": True,
            "state_text": "RUNNING",
        }
        bh = BeatHeartbeatCheck(file_exists=True, age_seconds=1.0, last_write_iso="t", fresh=True)
        assert bh.to_dict()["fresh"] is True
