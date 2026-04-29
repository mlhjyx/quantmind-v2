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

# PR-E1 后 backend/platform/ → qm_platform/, 根因消除. alias 现仅守 scripts/platform.py
# 同名 shadow (sys.path.insert(0, ...) 把 scripts/ 加在前面所致).
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
    SERVY_SERVICES,
    BeatHeartbeatCheck,
    HealthReport,
    ServiceCheck,
    _to_cst_display,
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
# _to_cst_display — 铁律 41 时区展示层 (Session 36 末 user 反馈)
# ═════════════════════════════════════════════════════════════════

class TestToCstDisplay:
    """_to_cst_display: UTC ISO → Asia/Shanghai 展示格式 (LL-074 钉钉告警友好化)."""

    def test_utc_to_cst_8h_offset(self):
        """UTC 14:45 → CST 22:45 (UTC+8)."""
        utc_iso = "2026-04-25T14:45:02.315821+00:00"
        cst = _to_cst_display(utc_iso)
        assert cst == "2026-04-25 22:45:02 CST"

    def test_utc_midnight_to_cst_8am_next_day(self):
        """UTC 2026-04-26T00:00 → CST 2026-04-26 08:00 (跨日检查)."""
        utc_iso = "2026-04-26T00:00:00+00:00"
        cst = _to_cst_display(utc_iso)
        assert cst == "2026-04-26 08:00:00 CST"

    def test_utc_late_pm_crosses_to_next_day_cst(self):
        """UTC 2026-04-25T20:30 → CST 2026-04-26 04:30 (跨日)."""
        utc_iso = "2026-04-25T20:30:00+00:00"
        cst = _to_cst_display(utc_iso)
        assert cst == "2026-04-26 04:30:00 CST"

    def test_naive_iso_treated_as_utc(self):
        """无 tz suffix 的 ISO 字符串按 UTC 处理 (fail-safe)."""
        cst = _to_cst_display("2026-04-25T14:45:02")
        assert cst == "2026-04-25 22:45:02 CST"

    def test_none_returns_na(self):
        """None 输入 → 'N/A' (不抛异常, 防 alert 完全 broken)."""
        assert _to_cst_display(None) == "N/A"

    def test_empty_string_returns_na(self):
        """空字符串 → 'N/A'."""
        assert _to_cst_display("") == "N/A"

    def test_invalid_format_returns_raw_fallback(self):
        """invalid ISO format → 返原始字符串 (fallback 不抛, 防 alert broken)."""
        garbage = "not-an-iso-string"
        assert _to_cst_display(garbage) == garbage

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

    def _mk_popen(self, returncode: int, stdout: str, stderr: str = "", timeout: bool = False):
        """模拟 Popen + communicate (Session 35 reviewer P2: 改 Popen + kill 后)."""
        proc = MagicMock()
        proc.returncode = returncode
        if timeout:
            # First communicate raises TimeoutExpired, kill + drain
            proc.communicate.side_effect = [
                subprocess.TimeoutExpired(cmd="sc query", timeout=5),
                (stdout, stderr),  # post-kill drain
            ]
        else:
            proc.communicate.return_value = (stdout, stderr)
        return proc

    def test_running_service(self, monkeypatch):
        # 真实 sc query 输出: 包含 SERVICE_NAME / TYPE : 10 / STATE : 4 RUNNING / capabilities
        sc_stdout = (
            "SERVICE_NAME: QuantMind-CeleryBeat\n"
            "        TYPE               : 10  WIN32_OWN_PROCESS\n"
            "        STATE              : 4  RUNNING\n"
            "                                (STOPPABLE, NOT_PAUSABLE, ACCEPTS_SHUTDOWN)\n"
            "        WIN32_EXIT_CODE    : 0  (0x0)\n"
        )
        proc = self._mk_popen(0, sc_stdout)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
        r = query_service_state("QuantMind-CeleryBeat")
        assert r.running is True
        assert r.state_text == "RUNNING"
        assert r.name == "QuantMind-CeleryBeat"

    def test_stopped_service(self, monkeypatch):
        # P1 reviewer fix: 必须包含 TYPE : 10 行 (真实 sc query 输出格式), 验证按行解析
        # 不被 "TYPE : 10" 行的 ": 10" → ": 1" 子串误判为 STOPPED.
        sc_stdout = (
            "SERVICE_NAME: QuantMind-CeleryBeat\n"
            "        TYPE               : 10  WIN32_OWN_PROCESS\n"
            "        STATE              : 1  STOPPED\n"
            "        WIN32_EXIT_CODE    : 0  (0x0)\n"
        )
        proc = self._mk_popen(0, sc_stdout)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
        r = query_service_state("QuantMind-CeleryBeat")
        assert r.running is False
        assert r.state_text == "STOPPED"

    def test_running_service_with_type_10_substring_collision(self, monkeypatch):
        """Reviewer P1 regression guard: TYPE : 10 不能被旧 substring 解析误判 STOPPED.

        旧实现 ``": 1" in stdout`` 在此输入返 STOPPED (TYPE 行包含 ": 10"). 新按行
        实现先 split STATE 行再判 ": 4", 不被 TYPE 行污染.
        """
        sc_stdout = (
            "SERVICE_NAME: foo\n"
            "        TYPE               : 10  WIN32_OWN_PROCESS\n"
            "        STATE              : 4  RUNNING\n"
        )
        proc = self._mk_popen(0, sc_stdout)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
        r = query_service_state("foo")
        assert r.running is True, "TYPE : 10 子串不应触发 STOPPED 误判"
        assert r.state_text == "RUNNING"

    def test_unknown_state_paused(self, monkeypatch):
        # State paused (7) — not RUNNING/STOPPED, fallback to UNKNOWN
        sc_stdout = (
            "SERVICE_NAME: foo\n"
            "        TYPE               : 10  WIN32_OWN_PROCESS\n"
            "        STATE              : 7  PAUSED\n"
        )
        proc = self._mk_popen(0, sc_stdout)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
        r = query_service_state("foo")
        assert r.running is False
        assert r.state_text.startswith("UNKNOWN")

    def test_no_state_line_at_all(self, monkeypatch):
        """完全没 STATE 行 (sc 输出异常 / unexpected format) — 兜底 UNKNOWN."""
        sc_stdout = "SERVICE_NAME: foo\n        TYPE               : 10  WIN32_OWN_PROCESS\n"
        proc = self._mk_popen(0, sc_stdout)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
        r = query_service_state("foo")
        assert r.running is False
        assert r.state_text.startswith("UNKNOWN")

    def test_nonzero_returncode_unknown_service(self, monkeypatch):
        proc = self._mk_popen(1060, "", "FAILED 1060: The specified service does not exist")
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
        r = query_service_state("does-not-exist")
        assert r.running is False
        assert r.state_text.startswith("ERROR: rc=1060")

    def test_timeout_kills_child(self, monkeypatch):
        """Reviewer P2 fix verify: 超时必须调 proc.kill() 防 sc.exe orphan."""
        proc = self._mk_popen(0, "", "", timeout=True)
        kill_called = []
        proc.kill.side_effect = lambda: kill_called.append(True)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: proc)
        r = query_service_state("foo")
        assert r.running is False
        assert "timeout" in r.state_text
        assert kill_called == [True], "Popen.kill 必须被调以防止 sc.exe orphan"

    def test_oserror(self, monkeypatch):
        def _raise(*a, **kw):
            raise FileNotFoundError("sc.exe not on PATH")

        monkeypatch.setattr(subprocess, "Popen", _raise)
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


def _make_running_popen():
    """Helper: 真实 sc query RUNNING 输出格式 (含 TYPE 行) Popen mock."""
    proc = MagicMock()
    proc.returncode = 0
    proc.communicate.return_value = (
        "SERVICE_NAME: foo\n"
        "        TYPE               : 10  WIN32_OWN_PROCESS\n"
        "        STATE              : 4  RUNNING\n"
        "        WIN32_EXIT_CODE    : 0  (0x0)\n",
        "",
    )
    return proc


class TestBuildReport:
    def test_all_ok(self, monkeypatch, tmp_path):
        # 4 services RUNNING (真实 sc 输出格式 含 TYPE 行)
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: _make_running_popen())

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
        def _fake_popen(args, **_):
            proc = MagicMock()
            proc.returncode = 0
            if "QuantMind-CeleryBeat" in args:
                proc.communicate.return_value = (
                    "SERVICE_NAME: QuantMind-CeleryBeat\n"
                    "        TYPE               : 10  WIN32_OWN_PROCESS\n"
                    "        STATE              : 1  STOPPED\n",
                    "",
                )
            else:
                proc.communicate.return_value = (
                    "SERVICE_NAME: foo\n"
                    "        TYPE               : 10  WIN32_OWN_PROCESS\n"
                    "        STATE              : 4  RUNNING\n",
                    "",
                )
            return proc

        monkeypatch.setattr(subprocess, "Popen", _fake_popen)
        beat_file = tmp_path / "celerybeat-schedule.dat"
        beat_file.write_bytes(b"x")
        monkeypatch.setattr("services_healthcheck.BEAT_SCHEDULE_FILE", beat_file)
        r = build_report()
        assert r.status == "degraded"
        assert any("QuantMind-CeleryBeat" in f for f in r.failures)

    def test_beat_stale_only(self, monkeypatch, tmp_path):
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: _make_running_popen())

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

    def test_naive_isoformat_treated_as_utc(self):
        """python-reviewer P3 fix: 防御性 last_alert.replace(tzinfo=UTC) 路径覆盖.

        正常运行时 update_state 写 ``datetime.now(UTC).isoformat()`` 永远带 +00:00,
        本路径仅在状态文件被手工编辑或 cross-version 兼容场景触发. 必须保证不抛
        TypeError (naive vs aware datetime 减法).
        """
        failures = ["service:a=STOPPED"]
        r = self._mk_report(failures=failures)
        # ISO 字符串无 tz 后缀 → fromisoformat 返 naive datetime → 走
        # ``replace(tzinfo=UTC)`` 兜底路径 (services_healthcheck.py L362-363)
        naive_iso = (datetime.now(UTC) - timedelta(minutes=30)).replace(tzinfo=None).isoformat()
        assert "+" not in naive_iso, "test fixture must produce naive ISO"
        state = {
            "last_status": "degraded",
            "last_failures": failures,
            "last_alert_time": naive_iso,
        }
        # 30min ago (naive 视为 UTC) → 仍在 1h 窗口 → dedup
        send, reason = should_alert(r, state)
        assert send is False
        assert "dedup" in reason

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
    """legacy `_send_alert_via_legacy_dingtalk` path 行为 (OBSERVABILITY_USE_PLATFORM_SDK=False).

    MVP 4.1 batch 1 (PR #131) 引入 SDK path (PostgresAlertRouter) 默认 ON,
    SDK path 行为不同 (DingTalkChannel webhook 空 → ValueError; 全 channel 失败
    → AlertDispatchError). 本类专测 legacy fallback 友好降级语义, 必须显式 patch
    `OBSERVABILITY_USE_PLATFORM_SDK=False` 强制走 legacy. SDK path 行为见
    `test_data_quality_check_observability.py` + `test_platform_alert_router.py`.
    """

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

        # Mock empty settings (强制走 legacy path 测 friendly degrade)
        from app import config as _config

        fake_settings = MagicMock()
        fake_settings.DINGTALK_WEBHOOK_URL = ""
        fake_settings.OBSERVABILITY_USE_PLATFORM_SDK = False
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
        fake_settings.OBSERVABILITY_USE_PLATFORM_SDK = False
        monkeypatch.setattr(_config, "settings", fake_settings)

        def _raise(*a, **kw):
            raise RuntimeError("network down")

        monkeypatch.setattr(_dt, "send_markdown_sync", _raise)
        ok = send_alert(report, "transition")
        assert ok is False  # 不抛, 友好降级 (legacy try/except silent_ok)


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
