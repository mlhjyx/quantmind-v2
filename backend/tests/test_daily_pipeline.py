"""daily_pipeline health_check → signal_task 依赖链测试。

验证:
1. health_check通过 → signal_task正常运行
2. health_check失败 → signal_task跳过 + P0告警
3. 无health_check结果 → signal_task放行 + warning日志
"""

import json
from datetime import date
from unittest.mock import MagicMock, patch


class TestHealthGate:
    """测试 _check_health_gate 三种场景。"""

    def test_health_check_passed(self) -> None:
        """health_check通过 → 返回 'passed'。"""
        from app.tasks.daily_pipeline import _check_health_gate, _health_check_key

        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps({
            "postgresql": True,
            "data_freshness": True,
            "redis": True,
            "disk_space": True,
            "all_pass": True,
        })

        with patch("app.tasks.daily_pipeline._get_redis_client", return_value=mock_redis):
            result = _check_health_gate(date(2024, 10, 8))

        assert result == "passed"
        mock_redis.get.assert_called_once_with(_health_check_key(date(2024, 10, 8)))

    def test_health_check_failed(self) -> None:
        """health_check失败 → 返回 'failed'。"""
        from app.tasks.daily_pipeline import _check_health_gate

        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps({
            "postgresql": True,
            "data_freshness": False,
            "redis": True,
            "disk_space": True,
            "all_pass": False,
        })

        with patch("app.tasks.daily_pipeline._get_redis_client", return_value=mock_redis):
            result = _check_health_gate(date(2024, 10, 8))

        assert result == "failed"

    def test_health_check_missing(self) -> None:
        """无health_check结果 → 返回 'missing'。"""
        from app.tasks.daily_pipeline import _check_health_gate

        mock_redis = MagicMock()
        mock_redis.get.return_value = None

        with patch("app.tasks.daily_pipeline._get_redis_client", return_value=mock_redis):
            result = _check_health_gate(date(2024, 10, 8))

        assert result == "missing"

    def test_redis_connection_error_returns_missing(self) -> None:
        """Redis连接失败 → 降级为 'missing'（放行）。"""
        from app.tasks.daily_pipeline import _check_health_gate

        with patch("app.tasks.daily_pipeline._get_redis_client", side_effect=Exception("conn refused")):
            result = _check_health_gate(date(2024, 10, 8))

        assert result == "missing"


class TestSignalTaskGate:
    """测试signal_task的health gate集成。"""

    def test_signal_skipped_on_health_failure(self) -> None:
        """health_check失败 → signal_task返回skipped。"""
        from app.tasks.daily_pipeline import daily_signal_task

        with (
            patch("app.tasks.daily_pipeline._check_health_gate", return_value="failed"),
            patch("app.tasks.daily_pipeline._send_health_gate_alert") as mock_alert,
        ):
            # __wrapped__跳过Celery bind=True的self注入
            result = daily_signal_task.__wrapped__("2024-10-08")

        assert result["status"] == "skipped"
        assert result["reason"] == "health_check_failed"
        mock_alert.assert_called_once_with(date(2024, 10, 8))

    def test_signal_runs_on_health_pass(self) -> None:
        """health_check通过 → signal_task正常运行。"""
        from app.tasks.daily_pipeline import daily_signal_task

        mock_result = {"phase": "signal", "trade_date": "2024-10-08"}
        with (
            patch("app.tasks.daily_pipeline._check_health_gate", return_value="passed"),
            patch("app.tasks.daily_pipeline.asyncio.run", return_value=mock_result),
        ):
            result = daily_signal_task.__wrapped__("2024-10-08")

        assert result["status"] == "success"

    def test_signal_runs_on_missing_with_warning(self) -> None:
        """无health_check结果 → signal_task放行。"""
        from app.tasks.daily_pipeline import daily_signal_task

        mock_result = {"phase": "signal", "trade_date": "2024-10-08"}
        with (
            patch("app.tasks.daily_pipeline._check_health_gate", return_value="missing"),
            patch("app.tasks.daily_pipeline.asyncio.run", return_value=mock_result),
        ):
            result = daily_signal_task.__wrapped__("2024-10-08")

        assert result["status"] == "success"


class TestHealthCheckWritesRedis:
    """测试health_check task写入Redis。"""

    def test_health_check_writes_result_to_redis(self) -> None:
        """health_check完成后结果写入Redis。"""
        from app.tasks.daily_pipeline import daily_health_check_task

        mock_redis = MagicMock()
        health_result = {
            "postgresql": True,
            "data_freshness": True,
            "redis": True,
            "disk_space": True,
            "all_pass": True,
        }

        with (
            patch("app.tasks.daily_pipeline.asyncio.run", return_value=health_result),
            patch("app.tasks.daily_pipeline._get_redis_client", return_value=mock_redis),
        ):
            result = daily_health_check_task.__wrapped__()

        assert result["all_pass"] is True
        # 验证写入Redis
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert "health_check" in call_args[0][0]
        assert call_args[0][1] == 86400  # TTL = 24h


class TestHealthCheckKeyFormat:
    """测试Redis key格式。"""

    def test_key_format(self) -> None:
        from app.tasks.daily_pipeline import _health_check_key

        key = _health_check_key(date(2024, 10, 8))
        assert key == "task_status:2024-10-08:health_check"
