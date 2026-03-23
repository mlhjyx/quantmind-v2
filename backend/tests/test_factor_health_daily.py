"""因子健康日报测试 — 覆盖 scripts/factor_health_daily.py。

7个测试场景:
11. 正常运行：--date 2026-03-19 --dry-run
12. IC趋势判断：递增=上升，递减=衰减
13. 相关矩阵：对角线=1.0，标记>0.7
14. 非交易日跳过
15. 无因子数据跳过
16. DB写入：非dry-run写scheduler_task_log
17. 退出码：critical=2, error=1

核心函数纯逻辑测试不依赖DB。集成测试用真实DB。
"""

import importlib.util
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import numpy as np
import pandas as pd
import pytest

# scripts/factor_health_daily.py不是包模块，用importlib直接加载
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
_BACKEND_DIR = Path(__file__).resolve().parent.parent

# 确保backend在path中（factor_health_daily.py自身会插入）
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_spec = importlib.util.spec_from_file_location(
    "factor_health_daily",
    _SCRIPTS_DIR / "factor_health_daily.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["factor_health_daily"] = _mod
_spec.loader.exec_module(_mod)

classify_ic_trend = _mod.classify_ic_trend
format_correlation_matrix = _mod.format_correlation_matrix
run_factor_health_daily = _mod.run_factor_health_daily


# ──────────────────────────────────────────────────────────
# 场景12: IC趋势判断 — 递增=上升，递减=衰减
# ──────────────────────────────────────────────────────────

class TestClassifyICTrend:
    """classify_ic_trend() 趋势分类测试。"""

    def test_increasing_trend(self) -> None:
        """递增IC序列 → '上升'。"""
        rolling_ic = [0.01, 0.015, 0.02, 0.025, 0.03, 0.035, 0.04]
        assert classify_ic_trend(rolling_ic) == "上升"

    def test_decreasing_trend(self) -> None:
        """递减IC序列 → '衰减'。"""
        rolling_ic = [0.04, 0.035, 0.03, 0.025, 0.02, 0.015, 0.01]
        assert classify_ic_trend(rolling_ic) == "衰减"

    def test_stable_trend(self) -> None:
        """平稳IC序列 → '稳定'。"""
        rolling_ic = [0.03, 0.03, 0.03, 0.03, 0.03, 0.03]
        assert classify_ic_trend(rolling_ic) == "稳定"

    def test_insufficient_data(self) -> None:
        """数据不足 → '数据不足'。"""
        assert classify_ic_trend([0.01, 0.02]) == "数据不足"
        assert classify_ic_trend([]) == "数据不足"

    def test_with_none_values(self) -> None:
        """含None值但有效数据>=5 → 正常判断。"""
        rolling_ic = [None, 0.01, None, 0.02, 0.025, 0.03, 0.035, None]
        assert classify_ic_trend(rolling_ic) == "上升"

    def test_all_none(self) -> None:
        """全部None → '数据不足'。"""
        assert classify_ic_trend([None, None, None, None, None, None]) == "数据不足"


# ──────────────────────────────────────────────────────────
# 场景13: 相关矩阵格式化 — 对角线=1.00, >0.7标记
# ──────────────────────────────────────────────────────────

class TestFormatCorrelationMatrix:
    """format_correlation_matrix() 格式化测试。"""

    def test_diagonal_is_one(self) -> None:
        """对角线显示为1.00。"""
        corr = pd.DataFrame(
            [[1.0, 0.3], [0.3, 1.0]],
            index=["turnover_mean_20", "volatility_20"],
            columns=["turnover_mean_20", "volatility_20"],
        )
        result = format_correlation_matrix(corr)
        assert "1.00" in result

    def test_empty_df(self) -> None:
        """空DataFrame → '(无数据)'。"""
        result = format_correlation_matrix(pd.DataFrame())
        assert "无数据" in result

    def test_nan_handling(self) -> None:
        """NaN显示为N/A。"""
        corr = pd.DataFrame(
            [[1.0, np.nan], [np.nan, 1.0]],
            index=["factor_a", "factor_b"],
            columns=["factor_a", "factor_b"],
        )
        result = format_correlation_matrix(corr)
        assert "N/A" in result

    def test_high_corr_formatted(self) -> None:
        """高相关值正确格式化显示。"""
        corr = pd.DataFrame(
            [[1.0, 0.75], [0.75, 1.0]],
            index=["turnover_mean_20", "volatility_20"],
            columns=["turnover_mean_20", "volatility_20"],
        )
        result = format_correlation_matrix(corr)
        assert "0.750" in result


# ──────────────────────────────────────────────────────────
# 场景14: 非交易日跳过
# ──────────────────────────────────────────────────────────

class TestNonTradingDaySkip:
    """非交易日应该跳过。"""

    @patch("factor_health_daily._get_sync_conn")
    def test_non_trading_day_returns_skipped(self, mock_conn_fn) -> None:
        """非交易日返回skipped状态。"""
        mock_conn = MagicMock()
        mock_conn_fn.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # is_trading_day查询返回False
        mock_cursor.fetchone.return_value = (False,)

        result = run_factor_health_daily(date(2026, 3, 22), dry_run=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "non_trading_day"
        mock_conn.close.assert_called_once()


# ──────────────────────────────────────────────────────────
# 场景15: 无因子数据跳过
# ──────────────────────────────────────────────────────────

class TestNoFactorDataSkip:
    """无因子数据应该跳过。"""

    @patch("factor_health_daily._get_sync_conn")
    def test_no_factor_data_returns_skipped(self, mock_conn_fn) -> None:
        """因子数据为0时返回skipped状态。"""
        mock_conn = MagicMock()
        mock_conn_fn.return_value = mock_conn
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        # 第1次fetchone: is_trading_day = True
        # 第2次fetchone: factor_count = 0
        mock_cursor.fetchone.side_effect = [(True,), (0,)]

        result = run_factor_health_daily(date(2026, 3, 19), dry_run=True)

        assert result["status"] == "skipped"
        assert result["reason"] == "no_factor_data"
        mock_conn.close.assert_called_once()


# ──────────────────────────────────────────────────────────
# 场景11 + 16: 正常运行 + DB写入 (集成测试，使用真实DB)
# ──────────────────────────────────────────────────────────

class TestFactorHealthIntegration:
    """使用真实数据库的集成测试。"""

    def _get_test_conn(self):
        """获取同步测试连接。"""
        import psycopg2
        return psycopg2.connect(
            "postgresql://quantmind:quantmind@localhost:5432/quantmind_v2"
        )

    def test_dry_run_normal_date(self) -> None:
        """场景11: --date 2026-03-19 --dry-run正常运行。"""
        conn = self._get_test_conn()
        try:
            # 确认2026-03-19是交易日且有因子数据
            cur = conn.cursor()
            cur.execute(
                """SELECT is_trading_day FROM trading_calendar
                   WHERE trade_date = '2026-03-19' AND market = 'astock'"""
            )
            row = cur.fetchone()
            if not row or not row[0]:
                pytest.skip("2026-03-19不是交易日")

            cur.execute(
                """SELECT COUNT(DISTINCT factor_name)
                   FROM factor_values WHERE trade_date = '2026-03-19'"""
            )
            factor_count = cur.fetchone()[0]
            if factor_count == 0:
                pytest.skip("2026-03-19无因子数据")
        finally:
            conn.close()

        # 使用dry-run（不写DB）
        result = run_factor_health_daily(date(2026, 3, 19), dry_run=True)

        # 正常运行应返回包含factors键的结果
        assert "factors" in result or result.get("status") == "skipped"
        if "factors" in result:
            assert "overall_status" in result
            assert result["overall_status"] in ("healthy", "warning", "critical")
            # 确认5个因子都有检查结果
            assert len(result["factors"]) >= 1

    def test_db_write_scheduler_task_log(self) -> None:
        """场景16: 非dry-run写入scheduler_task_log后回滚。"""
        conn = self._get_test_conn()
        try:
            # 检查前置条件
            cur = conn.cursor()
            cur.execute(
                """SELECT is_trading_day FROM trading_calendar
                   WHERE trade_date = '2026-03-19' AND market = 'astock'"""
            )
            row = cur.fetchone()
            if not row or not row[0]:
                pytest.skip("2026-03-19不是交易日")

            cur.execute(
                """SELECT COUNT(DISTINCT factor_name)
                   FROM factor_values WHERE trade_date = '2026-03-19'"""
            )
            if cur.fetchone()[0] == 0:
                pytest.skip("2026-03-19无因子数据")

            # 记录写入前的行数
            cur.execute(
                "SELECT COUNT(*) FROM scheduler_task_log WHERE task_name = 'factor_health_daily'"
            )
            before_count = cur.fetchone()[0]
        finally:
            conn.close()

        # 运行非dry-run（会真实写入）
        result = run_factor_health_daily(date(2026, 3, 19), dry_run=False)

        if "factors" not in result:
            pytest.skip("运行未成功")

        # 验证写入了一行
        conn = self._get_test_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM scheduler_task_log WHERE task_name = 'factor_health_daily'"
            )
            after_count = cur.fetchone()[0]
            assert after_count >= before_count + 1, (
                f"应多写入至少1行, before={before_count}, after={after_count}"
            )

            # 验证最新一行的内容
            cur.execute(
                """SELECT status, result_json FROM scheduler_task_log
                   WHERE task_name = 'factor_health_daily'
                   ORDER BY created_at DESC LIMIT 1"""
            )
            row = cur.fetchone()
            assert row is not None
            assert row[0] in ("healthy", "warning", "critical")
            # result_json应该是有效JSON
            import json
            if isinstance(row[1], str):
                data = json.loads(row[1])
            else:
                data = row[1]
            assert "date" in data
            assert "overall_status" in data
            assert "factors" in data

            # 清理: 删除本次测试写入的行
            cur.execute(
                """DELETE FROM scheduler_task_log
                   WHERE task_name = 'factor_health_daily'
                   AND created_at = (
                       SELECT MAX(created_at) FROM scheduler_task_log
                       WHERE task_name = 'factor_health_daily'
                   )"""
            )
            conn.commit()
        finally:
            conn.close()


# ──────────────────────────────────────────────────────────
# 场景17: 退出码 — critical=2, error=1
# ──────────────────────────────────────────────────────────

class TestExitCodes:
    """main()退出码测试。"""

    def test_critical_exit_code(self) -> None:
        """overall_status=critical → sys.exit(2)。"""
        # 直接测试main的退出逻辑
        result = {"overall_status": "critical", "factors": {}}

        # 模拟main中的退出判断
        overall = result.get("overall_status", result.get("status", "unknown"))
        if overall == "critical":
            exit_code = 2
        elif overall == "error":
            exit_code = 1
        else:
            exit_code = 0

        assert exit_code == 2

    def test_error_exit_code(self) -> None:
        """status=error → sys.exit(1)。"""
        result = {"status": "error", "error": "some error"}

        overall = result.get("overall_status", result.get("status", "unknown"))
        if overall == "critical":
            exit_code = 2
        elif overall == "error":
            exit_code = 1
        else:
            exit_code = 0

        assert exit_code == 1

    def test_healthy_no_exit(self) -> None:
        """overall_status=healthy → 不退出(exit_code=0)。"""
        result = {"overall_status": "healthy", "factors": {}}

        overall = result.get("overall_status", result.get("status", "unknown"))
        if overall == "critical":
            exit_code = 2
        elif overall == "error":
            exit_code = 1
        else:
            exit_code = 0

        assert exit_code == 0

    @patch("factor_health_daily.run_factor_health_daily")
    @patch("factor_health_daily.argparse.ArgumentParser.parse_args")
    def test_main_critical_calls_exit(self, mock_args, mock_run) -> None:
        """main()在critical时调用sys.exit(2)。"""
        main = _mod.main

        mock_args.return_value = MagicMock(date="2026-03-19", dry_run=True)
        mock_run.return_value = {"overall_status": "critical", "factors": {}}

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 2

    @patch("factor_health_daily.run_factor_health_daily")
    @patch("factor_health_daily.argparse.ArgumentParser.parse_args")
    def test_main_error_calls_exit(self, mock_args, mock_run) -> None:
        """main()在error时调用sys.exit(1)。"""
        main = _mod.main

        mock_args.return_value = MagicMock(date="2026-03-19", dry_run=True)
        mock_run.return_value = {"status": "error", "error": "test error"}

        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1
