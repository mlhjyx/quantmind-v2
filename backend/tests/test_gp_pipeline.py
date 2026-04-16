"""单元测试 — GP Pipeline Celery任务 (Sprint 1.17)

覆盖 app/tasks/mining_tasks.py:
  - run_gp_mining: 任务结构正确，mock GP Engine可执行
  - run_bruteforce_mining: 返回 not_implemented
  - _mark_run_failed: 异常时不崩溃（mock asyncpg）
  - _run_gp_mining_async: 数据为空时提前返回 failed
  - 异常处理: 任何步骤失败不导致未捕获崩溃
  - Celery任务注册名称正确

测试策略:
  - mock DB / asyncpg / GPEngine（不依赖PG/Celery/网络）
  - 直接调用异步函数（不走Celery worker）
  - 边界: 空市场数据 / GP Engine异常
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# F74/F18: Windows asyncio event loop hang — GP pipeline async tests freeze on IOCP.
# Root cause: pytest-asyncio + Windows ProactorEventLoop. F18 async→sync 迁移后移除此 skip.
_SKIP_WIN_ASYNC = pytest.mark.skipif(
    sys.platform == "win32",
    reason="F74: Windows asyncio IOCP hang, 待 F18 async→sync 迁移后移除",
)

# ---------------------------------------------------------------------------
# 导入守卫（Celery / asyncpg 可能未安装）
# ---------------------------------------------------------------------------

try:
    from app.tasks.mining_tasks import (
        _mark_run_failed,
        _run_gp_mining_async,
        _write_results_to_db,
        run_bruteforce_mining,
        run_gp_mining,
    )

    _TASKS_AVAILABLE = True
except ImportError:
    _TASKS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _TASKS_AVAILABLE,
    reason="mining_tasks 导入失败（Celery未安装或导入错误）",
)


# ---------------------------------------------------------------------------
# 1. 任务注册名称正确性
# ---------------------------------------------------------------------------


class TestTaskRegistration:
    """Celery任务名称应与代码一致。"""

    def test_gp_mining_task_name(self) -> None:
        """run_gp_mining 任务名称应为 'app.tasks.mining_tasks.run_gp_mining'。"""
        assert run_gp_mining.name == "app.tasks.mining_tasks.run_gp_mining"

    def test_bruteforce_mining_task_name(self) -> None:
        """run_bruteforce_mining 任务名称应正确注册。"""
        assert run_bruteforce_mining.name == "app.tasks.mining_tasks.run_bruteforce_mining"

    def test_gp_mining_is_callable(self) -> None:
        """run_gp_mining 应是可调用对象。"""
        assert callable(run_gp_mining)

    def test_bruteforce_mining_is_callable(self) -> None:
        """run_bruteforce_mining 应是可调用对象。"""
        assert callable(run_bruteforce_mining)


# ---------------------------------------------------------------------------
# 2. run_bruteforce_mining — not_implemented占位符
# ---------------------------------------------------------------------------


class TestBruteforceMiningTask:
    """run_bruteforce_mining 是Sprint 1.18占位符，应返回not_implemented。"""

    def test_bruteforce_returns_not_implemented(self) -> None:
        """run_bruteforce_mining 应返回 status=not_implemented。"""
        with patch("app.tasks.mining_tasks._mark_run_failed") as mock_mark:
            mock_mark.return_value = None

            # mock asyncio.run以避免真实DB调用
            with patch("asyncio.run"):
                # 直接调用底层函数（绕过Celery装饰器）
                result = run_bruteforce_mining.__wrapped__(
                    run_id="bf_test_001",
                    config={"generations": 10},
                )

        assert result["status"] == "not_implemented"
        assert result["run_id"] == "bf_test_001"

    def test_bruteforce_calls_mark_failed(self) -> None:
        """run_bruteforce_mining 应调用 _mark_run_failed 标记任务失败。"""
        with patch("asyncio.run") as mock_run:
            run_bruteforce_mining.__wrapped__(
                run_id="bf_fail_001",
                config={},
            )
            # asyncio.run 应被调用（用于 _mark_run_failed）
            mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# 3. _mark_run_failed 容错性
# ---------------------------------------------------------------------------


class TestMarkRunFailed:
    """_mark_run_failed 的异常处理。"""

    @pytest.mark.asyncio
    async def test_mark_run_failed_db_unavailable_no_crash(self) -> None:
        """DB不可用时 _mark_run_failed 应只记录日志，不抛出异常。"""
        with patch("asyncpg.connect", side_effect=ConnectionError("DB不可用")):
            # 不应抛出异常
            await _mark_run_failed("gp_fail_test", "测试错误信息")

    @pytest.mark.asyncio
    async def test_mark_run_failed_with_valid_mock_db(self) -> None:
        """有效mock DB时 _mark_run_failed 应执行UPDATE并关闭连接。"""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=mock_conn):
            await _mark_run_failed("gp_run_999", "某种错误")

        mock_conn.execute.assert_called_once()
        mock_conn.close.assert_called_once()

        # 验证调用的SQL包含UPDATE和run_id
        call_args = mock_conn.execute.call_args
        sql = call_args[0][0]
        assert "UPDATE" in sql.upper()
        assert "pipeline_runs" in sql
        assert "failed" in sql

    @pytest.mark.asyncio
    async def test_mark_run_failed_execute_error_no_crash(self) -> None:
        """execute失败时也不应崩溃。"""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=RuntimeError("execute失败"))
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=mock_conn):
            # 不应抛出异常
            try:
                await _mark_run_failed("gp_exec_fail", "错误")
            except Exception as e:
                pytest.fail(f"_mark_run_failed 不应抛出异常: {e}")


# ---------------------------------------------------------------------------
# 4. _write_results_to_db 结构验证
# ---------------------------------------------------------------------------


class TestWriteResultsToDB:
    """_write_results_to_db 写入结构正确性。"""

    @pytest.mark.asyncio
    async def test_write_empty_passed_factors(self) -> None:
        """空passed_factors列表时只更新pipeline_runs，不写approval_queue。"""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.close = AsyncMock()

        with patch("asyncpg.connect", return_value=mock_conn):
            await _write_results_to_db(
                db_url="postgresql://fake/db",
                run_id="gp_empty_write",
                stats={"total_evaluated": 100, "passed_gate_full": 0},
                passed_factors=[],
            )

        # 只有一次execute（UPDATE pipeline_runs）
        assert mock_conn.execute.call_count == 1
        sql = mock_conn.execute.call_args[0][0]
        assert "UPDATE" in sql.upper()

    @pytest.mark.asyncio
    async def test_write_with_passed_factors(self) -> None:
        """有passed_factors时应写入approval_queue（INSERT）。"""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.close = AsyncMock()

        passed_factors = [
            {
                "factor_expr": "ts_mean(turnover_rate, 20)",
                "ast_hash": "abc123def456",
                "gate_result": {"G1": "PASS", "G2": "PASS"},
            },
            {
                "factor_expr": "inv(pb)",
                "ast_hash": "fedcba987654",
                "gate_result": {"G1": "PASS"},
            },
        ]

        with patch("asyncpg.connect", return_value=mock_conn):
            await _write_results_to_db(
                db_url="postgresql://fake/db",
                run_id="gp_with_factors",
                stats={"total_evaluated": 500, "passed_gate_full": 2},
                passed_factors=passed_factors,
            )

        # 1次UPDATE + 2次INSERT
        assert mock_conn.execute.call_count == 3
        mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_db_unavailable_no_crash(self) -> None:
        """DB不可用时 _write_results_to_db 应记录错误，不崩溃。"""
        with patch("asyncpg.connect", side_effect=ConnectionError("DB down")):
            try:
                await _write_results_to_db(
                    db_url="postgresql://fake/db",
                    run_id="gp_db_down",
                    stats={},
                    passed_factors=[],
                )
            except Exception as e:
                pytest.fail(f"_write_results_to_db 不应抛出异常: {e}")


# ---------------------------------------------------------------------------
# 5. _run_gp_mining_async — 空数据提前返回
# ---------------------------------------------------------------------------


@_SKIP_WIN_ASYNC
class TestRunGPMiningAsync:
    """_run_gp_mining_async 的核心逻辑路径。"""

    @pytest.mark.asyncio
    async def test_empty_market_data_returns_failed(self) -> None:
        """_load_market_data 返回空DataFrame时，任务应返回 status='failed'。"""
        import pandas as pd

        empty_df = pd.DataFrame()

        with (
            patch(
                "scripts.run_gp_pipeline._load_market_data",
                new_callable=AsyncMock,
                return_value=empty_df,
            ),
            patch(
                "scripts.run_gp_pipeline._load_existing_factor_data",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch("app.tasks.mining_tasks._mark_run_failed", new_callable=AsyncMock),
        ):
            result = await _run_gp_mining_async(
                run_id="gp_empty_market",
                config={"generations": 5, "population": 20, "islands": 2},
            )

        assert result["status"] == "failed"
        assert result["run_id"] == "gp_empty_market"
        assert result["passed_factors"] == 0

    @pytest.mark.asyncio
    async def test_gp_engine_exception_propagates(self) -> None:
        """GPEngine.evolve() 抛出异常时，应由 run_gp_mining 捕获并调用 _mark_run_failed。"""
        import numpy as np
        import pandas as pd

        # 非空市场数据
        n = 50
        rng = np.random.default_rng(0)
        market_data = pd.DataFrame(
            {
                "close": rng.uniform(5, 100, n),
                "volume": rng.uniform(1e6, 5e7, n),
                "pb": rng.uniform(0.5, 8.0, n),
                "turnover_rate": rng.uniform(0.001, 0.05, n),
            }
        )
        forward_returns = pd.Series(rng.normal(0, 0.02, n))

        with (
            patch(
                "scripts.run_gp_pipeline._load_market_data",
                new_callable=AsyncMock,
                return_value=market_data,
            ),
            patch(
                "scripts.run_gp_pipeline._load_existing_factor_data",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "scripts.run_gp_pipeline._compute_forward_returns",
                return_value=forward_returns,
            ),
            patch(
                "engines.mining.gp_engine.GPEngine.evolve",
                side_effect=RuntimeError("GP进化崩溃了"),
            ),
            patch("app.tasks.mining_tasks._mark_run_failed", new_callable=AsyncMock),
            pytest.raises(RuntimeError, match="GP进化崩溃了"),
        ):
            await _run_gp_mining_async(
                run_id="gp_crash_test",
                config={"generations": 3, "population": 10, "islands": 1},
            )


# ---------------------------------------------------------------------------
# 6. 钉钉通知格式验证
# ---------------------------------------------------------------------------


@_SKIP_WIN_ASYNC
class TestDingTalkNotification:
    """钉钉通知格式和调用验证。"""

    def test_dingtalk_notification_called_with_correct_args(self) -> None:
        """_send_dingtalk_notification 应以正确参数被调用。"""
        import numpy as np
        import pandas as pd

        n = 50
        rng = np.random.default_rng(1)
        market_data = pd.DataFrame(
            {
                "close": rng.uniform(5, 100, n),
                "volume": rng.uniform(1e6, 5e7, n),
                "pb": rng.uniform(0.5, 8.0, n),
                "turnover_rate": rng.uniform(0.001, 0.05, n),
            }
        )
        forward_returns = pd.Series(rng.normal(0, 0.02, n))

        mock_gp_results = []
        mock_stats = MagicMock()
        mock_stats.total_evaluated = 100
        mock_stats.passed_quick_gate = 5
        mock_stats.best_fitness = 0.75
        mock_stats.n_generations_completed = 10
        mock_stats.elapsed_seconds = 60.0
        mock_stats.timeout = False

        with (
            patch(
                "scripts.run_gp_pipeline._load_market_data",
                new_callable=AsyncMock,
                return_value=market_data,
            ),
            patch(
                "scripts.run_gp_pipeline._load_existing_factor_data",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "scripts.run_gp_pipeline._compute_forward_returns",
                return_value=forward_returns,
            ),
            patch(
                "engines.mining.gp_engine.GPEngine.evolve",
                return_value=(mock_gp_results, mock_stats),
            ),
            patch(
                "scripts.run_gp_pipeline._run_full_gate",
                return_value=[],
            ),
            patch(
                "app.tasks.mining_tasks._write_results_to_db",
                new_callable=AsyncMock,
            ),
            patch(
                "scripts.run_gp_pipeline._send_dingtalk_notification",
            ) as mock_notify,
        ):
            result = asyncio.run(
                _run_gp_mining_async(
                    run_id="gp_notify_test",
                    config={"generations": 5, "population": 10, "islands": 1},
                )
            )

        # 钉钉通知应被调用
        mock_notify.assert_called_once()
        assert result["status"] == "completed"
        assert result["run_id"] == "gp_notify_test"

    def test_dingtalk_notification_empty_webhook_no_crash(self) -> None:
        """空webhook URL时，通知函数不应崩溃。"""
        try:
            from scripts.run_gp_pipeline import _send_dingtalk_notification  # type: ignore[import]
        except ImportError:
            pytest.skip("run_gp_pipeline不可导入")

        # 空webhook不应崩溃
        _send_dingtalk_notification(
            webhook_url="",
            secret="",
            run_id="gp_no_webhook",
            stats={"total_evaluated": 100, "passed_gate_full": 0},
            passed_factors=[],
        )

    def test_dingtalk_notification_network_error_no_crash(self) -> None:
        """网络错误时，通知函数不应崩溃。"""
        try:
            from scripts.run_gp_pipeline import _send_dingtalk_notification  # type: ignore[import]
        except ImportError:
            pytest.skip("run_gp_pipeline不可导入")

        with patch("requests.post", side_effect=ConnectionError("网络不可用")):
            try:
                _send_dingtalk_notification(
                    webhook_url="https://fake.dingtalk.com/robot/send",
                    secret="fake_secret",
                    run_id="gp_net_fail",
                    stats={"total_evaluated": 200},
                    passed_factors=[],
                )
            except Exception as e:
                pytest.fail(f"_send_dingtalk_notification 不应传播网络异常: {e}")


# ---------------------------------------------------------------------------
# 7. run_gp_mining Celery任务封装结构
# ---------------------------------------------------------------------------


class TestRunGPMiningTask:
    """run_gp_mining Celery任务的封装结构（不跑真实GP）。"""

    def test_gp_mining_task_config(self) -> None:
        """run_gp_mining 应配置 acks_late=True, max_retries=0。"""
        # 检查 Celery task 属性
        assert getattr(run_gp_mining, "acks_late", None) is True
        assert getattr(run_gp_mining, "max_retries", None) == 0

    def test_gp_mining_task_time_limits(self) -> None:
        """soft_time_limit < time_limit（硬超时应大于软超时）。"""
        soft = getattr(run_gp_mining, "soft_time_limit", None)
        hard = getattr(run_gp_mining, "time_limit", None)
        if soft is not None and hard is not None:
            assert soft < hard, f"soft_time_limit({soft}) 应 < time_limit({hard})"

    def test_bruteforce_task_config(self) -> None:
        """run_bruteforce_mining 应配置 max_retries=0。"""
        assert getattr(run_bruteforce_mining, "max_retries", None) == 0

    def test_gp_task_exception_calls_mark_failed(self) -> None:
        """run_gp_mining 内部异常时应调用 _mark_run_failed 并重新抛出。"""
        with (
            patch(
                "asyncio.run",
                side_effect=[RuntimeError("GP内部错误"), None],
            ),
            pytest.raises(RuntimeError, match="GP内部错误"),
        ):
            run_gp_mining.__wrapped__(
                run_id="gp_exc_test",
                config={"generations": 5},
            )
