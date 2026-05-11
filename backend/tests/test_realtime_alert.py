"""Unit tests for AlertDispatcher + EmailBackupStub (S6 L0 告警实时化).

覆盖:
  - AlertDispatcher: P0 立即 send / P1+P2 缓冲 / flush / flush_and_send
  - AlertDispatcher: stats 计数 / buffer_sizes / thread safety
  - AlertDispatcher: custom send_fn / send failure tracking
  - EmailBackupStub: backup 写入 JSONL / backup_count / 并发安全
  - _rule_severity_str: P0/P1/P2 映射
"""

from __future__ import annotations

import json
import tempfile
import threading
from pathlib import Path

import pytest

from backend.qm_platform.risk import RuleResult
from backend.qm_platform.risk.realtime.alert import (
    AlertDispatcher,
    _rule_severity_str,
)
from backend.qm_platform.risk.realtime.email_backup import EmailBackupStub

# ── helpers ──


def _make_result(
    rule_id: str = "limit_down_detection",
    code: str = "600519.SH",
    reason: str = "test reason",
) -> RuleResult:
    return RuleResult(
        rule_id=rule_id,
        code=code,
        shares=0,
        reason=reason,
        metrics={"val": 1.0},
    )


def _always_ok(result: RuleResult) -> bool:
    """send_fn stub: 始终成功."""
    return True


def _always_fail(result: RuleResult) -> bool:
    """send_fn stub: 始终失败."""
    return False


# ── _rule_severity_str ──


class TestRuleSeverityStr:
    def test_p0_rules(self):
        assert _rule_severity_str(_make_result("limit_down_detection")) == "p0"
        assert _rule_severity_str(_make_result("near_limit_down")) == "p0"
        assert _rule_severity_str(_make_result("gap_down_open")) == "p0"
        assert _rule_severity_str(_make_result("correlated_drop")) == "p0"

    def test_p1_rules(self):
        assert _rule_severity_str(_make_result("rapid_drop_5min")) == "p1"
        assert _rule_severity_str(_make_result("rapid_drop_15min")) == "p1"
        assert _rule_severity_str(_make_result("volume_spike")) == "p1"
        assert _rule_severity_str(_make_result("liquidity_collapse")) == "p1"

    def test_p2_rules(self):
        assert _rule_severity_str(_make_result("industry_concentration")) == "p2"

    def test_unknown_defaults_to_p1(self):
        assert _rule_severity_str(_make_result("some_new_rule")) == "p1"


# ── AlertDispatcher ──


class TestAlertDispatcher:
    def test_p0_immediate_dispatch(self):
        """P0 规则立即 send, 不缓冲."""
        sent_calls: list[RuleResult] = []

        def capture(result: RuleResult) -> bool:
            sent_calls.append(result)
            return True

        dispatcher = AlertDispatcher(send_fn=capture)
        results = [
            _make_result("limit_down_detection", "600519.SH"),
            _make_result("correlated_drop", "000001.SZ"),
        ]
        n = dispatcher.dispatch(results)
        assert n == 2
        assert len(sent_calls) == 2
        assert dispatcher.buffer_sizes == {"p1": 0, "p2": 0}

    def test_p1_buffered_not_immediate(self):
        """P1 规则缓冲, 不立即 send."""
        sent_calls: list[RuleResult] = []

        def capture(result: RuleResult) -> bool:
            sent_calls.append(result)
            return True

        dispatcher = AlertDispatcher(send_fn=capture)
        results = [
            _make_result("rapid_drop_5min", "600519.SH"),
            _make_result("volume_spike", "000001.SZ"),
        ]
        n = dispatcher.dispatch(results)
        assert n == 0  # 无 P0
        assert len(sent_calls) == 0  # 未 send
        assert dispatcher.buffer_sizes["p1"] == 2

    def test_p2_buffered_not_immediate(self):
        """P2 规则缓冲."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        dispatcher.dispatch([_make_result("industry_concentration", "")])
        assert dispatcher.buffer_sizes["p2"] == 1

    def test_mixed_priority_dispatch(self):
        """混合 P0/P1/P2 同批."""
        sent: list[str] = []

        def capture(result: RuleResult) -> bool:
            sent.append(result.rule_id)
            return True

        dispatcher = AlertDispatcher(send_fn=capture)
        results = [
            _make_result("limit_down_detection", "600519.SH"),  # P0
            _make_result("rapid_drop_5min", "000001.SZ"),  # P1
            _make_result("volume_spike", "300750.SZ"),  # P1
            _make_result("industry_concentration", ""),  # P2
            _make_result("correlated_drop", "688121.SH"),  # P0
        ]
        n = dispatcher.dispatch(results)
        assert n == 2  # 2 P0
        assert sent == ["limit_down_detection", "correlated_drop"]
        assert dispatcher.buffer_sizes == {"p1": 2, "p2": 1}

    def test_empty_dispatch(self):
        """空列表 dispatch, 无副作用."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        assert dispatcher.dispatch([]) == 0
        assert dispatcher.buffer_sizes == {"p1": 0, "p2": 0}

    # ── flush ──

    def test_flush_p1_returns_buffered(self):
        """flush P1 返缓冲结果并清空 buffer."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        r1 = _make_result("rapid_drop_5min", "600519.SH")
        r2 = _make_result("volume_spike", "000001.SZ")
        dispatcher.dispatch([r1, r2])

        batch = dispatcher.flush("5min")
        assert len(batch) == 2
        assert batch == [r1, r2]
        assert dispatcher.buffer_sizes["p1"] == 0  # 已清空

    def test_flush_p2_returns_buffered(self):
        """flush P2 返缓冲结果."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        r = _make_result("industry_concentration", "")
        dispatcher.dispatch([r])

        batch = dispatcher.flush("15min")
        assert len(batch) == 1
        assert dispatcher.buffer_sizes["p2"] == 0

    def test_flush_empty_buffer(self):
        """flush 空 buffer 返 []."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        assert dispatcher.flush("5min") == []
        assert dispatcher.flush("15min") == []

    def test_flush_invalid_cadence_raises(self):
        """无效 cadence → ValueError."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        with pytest.raises(ValueError, match="Invalid flush cadence"):
            dispatcher.flush("hourly")  # type: ignore[arg-type]

    # ── flush_and_send ──

    def test_flush_and_send_calls_send_fn(self):
        """flush_and_send 逐条调用 send_fn."""
        sent: list[str] = []

        def capture(result: RuleResult) -> bool:
            sent.append(result.code)
            return True

        dispatcher = AlertDispatcher(send_fn=capture)
        dispatcher.dispatch(
            [
                _make_result("rapid_drop_5min", "600519.SH"),
                _make_result("volume_spike", "000001.SZ"),
            ]
        )
        n = dispatcher.flush_and_send("5min")
        assert n == 2
        assert sent == ["600519.SH", "000001.SZ"]
        assert dispatcher.buffer_sizes["p1"] == 0

    def test_flush_and_send_counts_failures(self):
        """flush_and_send 中 send_fn 失败被计入 stats."""
        dispatcher = AlertDispatcher(send_fn=_always_fail)
        dispatcher.dispatch(
            [
                _make_result("rapid_drop_5min", "600519.SH"),
            ]
        )
        n = dispatcher.flush_and_send("5min")
        assert n == 0
        assert dispatcher.stats["send_failed"] == 1

    def test_flush_and_send_empty(self):
        """空 buffer flush_and_send 返 0."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        assert dispatcher.flush_and_send("5min") == 0

    # ── stats ──

    def test_stats_tracking(self):
        """stats 正确跟踪 dispatch/flush/send_failed."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        dispatcher.dispatch(
            [
                _make_result("limit_down_detection", "600519.SH"),  # P0
                _make_result("rapid_drop_5min", "000001.SZ"),  # P1
                _make_result("rapid_drop_15min", "300750.SZ"),  # P1
                _make_result("industry_concentration", ""),  # P2
            ]
        )
        dispatcher.flush_and_send("5min")
        dispatcher.flush_and_send("15min")

        stats = dispatcher.stats
        assert stats["p0_sent"] == 1
        assert stats["p1_buffered"] == 2
        assert stats["p2_buffered"] == 1
        assert stats["p1_flushed"] == 2
        assert stats["p2_flushed"] == 1
        assert stats["send_failed"] == 0

    def test_stats_send_failed(self):
        """send_fn 失败计数."""
        dispatcher = AlertDispatcher(send_fn=_always_fail)
        dispatcher.dispatch(
            [
                _make_result("limit_down_detection", "600519.SH"),  # P0 → fail
            ]
        )
        dispatcher.dispatch(
            [
                _make_result("rapid_drop_5min", "000001.SZ"),  # P1 → buffer
            ]
        )
        dispatcher.flush_and_send("5min")  # flush → fail

        stats = dispatcher.stats
        assert stats["send_failed"] >= 1  # at least P0 failure
        assert stats["p0_sent"] == 0  # 失败不计入 p0_sent

    def test_multiple_dispatch_accumulates(self):
        """多次 dispatch 累积 buffer."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        for _ in range(3):
            dispatcher.dispatch([_make_result("rapid_drop_5min", "600519.SH")])
        assert dispatcher.buffer_sizes["p1"] == 3
        dispatcher.flush("5min")
        dispatcher.dispatch([_make_result("rapid_drop_5min", "000001.SZ")])
        assert dispatcher.buffer_sizes["p1"] == 1

    # ── concurrency ──

    def test_concurrent_dispatch(self):
        """并发 dispatch 不丢记录."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        errors: list[str] = []

        def worker(n: int):
            for i in range(n):
                try:
                    dispatcher.dispatch(
                        [
                            _make_result("rapid_drop_5min", f"code_{i}"),
                        ]
                    )
                except Exception as e:
                    errors.append(str(e))

        threads = [
            threading.Thread(target=worker, args=(50,)),
            threading.Thread(target=worker, args=(50,)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert dispatcher.buffer_sizes["p1"] == 100

    def test_concurrent_flush(self):
        """并发 dispatch + flush 不丢记录 / 不崩溃."""
        dispatcher = AlertDispatcher(send_fn=_always_ok)
        errors: list[str] = []

        def dispatcher_worker():
            for _ in range(30):
                try:
                    dispatcher.dispatch(
                        [
                            _make_result("rapid_drop_5min", "test"),
                        ]
                    )
                except Exception as e:
                    errors.append(str(e))

        def flush_worker():
            for _ in range(10):
                try:
                    dispatcher.flush("5min")
                except Exception as e:
                    errors.append(str(e))

        threads = [
            threading.Thread(target=dispatcher_worker),
            threading.Thread(target=dispatcher_worker),
            threading.Thread(target=flush_worker),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # 最终 buffer 应 ≥ 0 (flush 可能清了部分)
        remaining = dispatcher.buffer_sizes["p1"]
        stats = dispatcher.stats
        # p1_buffered = dispatched, p1_flushed = flushed
        assert stats["p1_buffered"] == 60  # 2 workers × 30
        assert stats["p1_flushed"] + remaining == 60


# ── EmailBackupStub ──


class TestEmailBackupStub:
    def test_backup_writes_jsonl(self):
        """backup 写入 JSONL 文件."""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "email_backup.jsonl"
            stub = EmailBackupStub(log_path=log_path)

            result = _make_result("limit_down_detection", "600519.SH", reason="跌停检测触发")
            stub.backup(result, retry_count=3)

            assert log_path.exists()
            lines = log_path.read_text().strip().split("\n")
            assert len(lines) == 1
            record = json.loads(lines[0])
            assert record["rule_id"] == "limit_down_detection"
            assert record["code"] == "600519.SH"
            assert record["retry_exhausted_after"] == 3
            assert "timestamp" in record

    def test_backup_appends_not_overwrites(self):
        """多次 backup 追加而非覆盖."""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "email_backup.jsonl"
            stub = EmailBackupStub(log_path=log_path)

            stub.backup(_make_result("limit_down_detection", "A"))
            stub.backup(_make_result("rapid_drop_5min", "B"))
            stub.backup(_make_result("correlated_drop", "C"))

            lines = log_path.read_text().strip().split("\n")
            assert len(lines) == 3
            codes = [json.loads(l)["code"] for l in lines]
            assert codes == ["A", "B", "C"]

    def test_backup_count_increments(self):
        """backup_count 正确累加."""
        with tempfile.TemporaryDirectory() as tmp:
            stub = EmailBackupStub(log_path=Path(tmp) / "test.jsonl")
            assert stub.backup_count == 0
            stub.backup(_make_result("limit_down_detection", "A"))
            assert stub.backup_count == 1
            stub.backup(_make_result("rapid_drop_5min", "B"))
            assert stub.backup_count == 2

    def test_backup_default_path(self):
        """默认路径 logs/email_backup.jsonl."""
        stub = EmailBackupStub()
        assert stub.log_path == Path("logs/email_backup.jsonl")

    def test_backup_custom_path(self):
        """自定义路径."""
        stub = EmailBackupStub(log_path=Path("/tmp/custom.jsonl"))
        assert stub.log_path == Path("/tmp/custom.jsonl")

    def test_concurrent_backup(self):
        """并发 backup 不丢记录."""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "concurrent.jsonl"
            stub = EmailBackupStub(log_path=log_path)
            errors: list[str] = []

            def worker(start: int, n: int):
                for i in range(start, start + n):
                    try:
                        stub.backup(
                            _make_result("rapid_drop_5min", f"code_{i}"),
                            retry_count=3,
                        )
                    except Exception as e:
                        errors.append(str(e))

            threads = [
                threading.Thread(target=worker, args=(0, 20)),
                threading.Thread(target=worker, args=(20, 20)),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0
            lines = log_path.read_text().strip().split("\n")
            assert len(lines) == 40
            assert stub.backup_count == 40

    def test_backup_log_path_created(self):
        """backup 自动创建父目录."""
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "subdir" / "nested" / "email_backup.jsonl"
            stub = EmailBackupStub(log_path=log_path)
            stub.backup(_make_result("limit_down_detection", "test"))
            assert log_path.exists()
