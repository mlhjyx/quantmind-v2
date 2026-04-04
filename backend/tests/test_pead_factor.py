"""PEAD Q1季报因子单元测试。"""

from datetime import date
from unittest.mock import MagicMock


class TestPeadQ1:
    """calc_pead_q1 测试。"""

    def _mock_conn(self, rows):
        """构造mock DB连接。"""
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        cur.fetchall.return_value = rows
        return conn

    def test_basic_signal(self):
        """有Q1季报的股票返回非NaN。"""
        from engines.factor_engine import calc_pead_q1

        rows = [
            ("000001.SZ", 0.25, date(2025, 4, 20)),
            ("600519.SH", -0.10, date(2025, 4, 22)),
        ]
        conn = self._mock_conn(rows)
        result = calc_pead_q1(date(2025, 4, 25), conn=conn)
        assert len(result) == 2
        assert result["000001"] == 0.25
        assert result["600519"] == -0.10

    def test_window_constraint(self):
        """SQL查询包含7天窗口约束。"""
        from engines.factor_engine import calc_pead_q1

        conn = self._mock_conn([])
        calc_pead_q1(date(2025, 5, 10), conn=conn)
        # 验证SQL参数包含trade_date
        call_args = conn.cursor().execute.call_args
        params = call_args[0][1]
        assert params[0] == date(2025, 5, 10)  # trade_date
        assert params[1] == date(2025, 5, 10)  # 7天窗口基准

    def test_latest_only(self):
        """同一股票多条Q1季报只取最近一条。"""
        from engines.factor_engine import calc_pead_q1

        rows = [
            ("000001.SZ", 0.30, date(2025, 4, 22)),  # 较近（ORDER BY DESC先出）
            ("000001.SZ", 0.10, date(2024, 4, 20)),  # 较远
        ]
        conn = self._mock_conn(rows)
        result = calc_pead_q1(date(2025, 4, 25), conn=conn)
        assert len(result) == 1
        assert result["000001"] == 0.30  # 取最近

    def test_no_data(self):
        """无Q1季报记录返回空Series。"""
        from engines.factor_engine import calc_pead_q1

        conn = self._mock_conn([])
        result = calc_pead_q1(date(2025, 4, 25), conn=conn)
        assert len(result) == 0

    def test_direction_positive(self):
        """PEAD因子方向为正（正surprise→正drift）。"""
        from engines.factor_engine import PEAD_FACTOR_DIRECTION

        assert PEAD_FACTOR_DIRECTION["pead_q1"] == 1

    def test_extreme_filter(self):
        """SQL过滤|surprise|>10的极端值。"""
        from engines.factor_engine import calc_pead_q1

        conn = self._mock_conn([])
        calc_pead_q1(date(2025, 4, 25), conn=conn)
        sql = conn.cursor().execute.call_args[0][0]
        assert "ABS(ea.eps_surprise_pct) < 10" in sql
