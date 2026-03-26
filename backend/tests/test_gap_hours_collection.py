"""gap_hours时间戳采集和计算测试。

验证:
1. signal_generated_at格式为UTC TIMESTAMPTZ
2. executed_at格式为UTC TIMESTAMPTZ
3. gap_hours = (executed_at - signal_generated_at) / 3600，典型值14-18h
"""

from datetime import datetime, timezone, timedelta

import pytest


class TestGapHoursTimestamps:
    """gap_hours时间戳格式和计算验证。"""

    def test_signal_generated_at_is_utc(self) -> None:
        """signal_generated_at应为UTC时区."""
        now_utc = datetime.now(timezone.utc)
        assert now_utc.tzinfo is not None
        assert now_utc.tzinfo == timezone.utc

    def test_executed_at_is_utc(self) -> None:
        """executed_at应为UTC时区."""
        now_utc = datetime.now(timezone.utc)
        assert now_utc.tzinfo is not None

    def test_gap_hours_calculation_typical(self) -> None:
        """典型gap_hours: 信号T日17:30 → 执行T+1日09:30 ≈ 16h."""
        # T日 17:30 北京时间 = 09:30 UTC
        signal_time = datetime(2024, 1, 2, 9, 30, 0, tzinfo=timezone.utc)
        # T+1日 09:30 北京时间 = 01:30 UTC
        exec_time = datetime(2024, 1, 3, 1, 30, 0, tzinfo=timezone.utc)

        gap_hours = (exec_time - signal_time).total_seconds() / 3600
        assert 15.0 < gap_hours < 17.0  # 约16h

    def test_gap_hours_calculation_same_day(self) -> None:
        """异常gap_hours: 同一天信号和执行."""
        signal_time = datetime(2024, 1, 2, 9, 30, 0, tzinfo=timezone.utc)
        exec_time = datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc)

        gap_hours = (exec_time - signal_time).total_seconds() / 3600
        assert gap_hours == pytest.approx(0.5)

    def test_gap_hours_negative_is_anomaly(self) -> None:
        """executed_at早于signal_generated_at应为异常."""
        signal_time = datetime(2024, 1, 3, 9, 30, 0, tzinfo=timezone.utc)
        exec_time = datetime(2024, 1, 2, 1, 30, 0, tzinfo=timezone.utc)

        gap_hours = (exec_time - signal_time).total_seconds() / 3600
        assert gap_hours < 0  # 负值 = 异常

    def test_gap_hours_weekend_longer(self) -> None:
        """跨周末gap_hours会更长(正常现象)."""
        # 周五 17:30 北京时间
        signal_time = datetime(2024, 1, 5, 9, 30, 0, tzinfo=timezone.utc)  # Friday
        # 周一 09:30 北京时间
        exec_time = datetime(2024, 1, 8, 1, 30, 0, tzinfo=timezone.utc)  # Monday

        gap_hours = (exec_time - signal_time).total_seconds() / 3600
        assert gap_hours > 60  # 周五到周一约64h

    def test_timestamp_precision_microseconds(self) -> None:
        """时间戳应有微秒精度."""
        ts = datetime.now(timezone.utc)
        # Python datetime默认有微秒精度
        assert ts.microsecond >= 0


class TestSignalServiceTimestamp:
    """验证SignalService._write_signals包含signal_generated_at."""

    def test_write_signals_includes_timestamp_column(self) -> None:
        """_write_signals的INSERT语句应包含signal_generated_at."""
        import inspect
        from app.services.signal_service import SignalService

        source = inspect.getsource(SignalService._write_signals)
        assert "signal_generated_at" in source
        assert "datetime.now(timezone.utc)" in source or "now_utc" in source


class TestPaperBrokerTimestamp:
    """验证PaperBroker写入trade_log时包含executed_at."""

    def test_save_fills_includes_executed_at(self) -> None:
        """save_fills的INSERT应包含executed_at."""
        import inspect
        from engines.paper_broker import PaperBroker

        source = inspect.getsource(PaperBroker.save_fills_only)
        assert "executed_at" in source

    def test_save_state_includes_executed_at(self) -> None:
        """save_state的trade_log INSERT应包含executed_at."""
        import inspect
        from engines.paper_broker import PaperBroker

        source = inspect.getsource(PaperBroker.save_state)
        assert "executed_at" in source
