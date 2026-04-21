"""compute_ic_rolling.py 回归测试 (Phase 2 of 铁律 11).

Session 22 Part 7: factor_ic_history.ic_ma20/ic_ma60 回填脚本测试.
纯函数 + mock DB, 不接触真实数据库.

覆盖:
- compute_rolling 算法与 factor_onboarding.py:739-740 canonical 对齐
- 分组隔离 (不跨因子 bleed)
- min_periods=5 / 10 语义 (短尾 NaN)
- diff_updates 幂等 (equal → skip)
- diff_updates 变化侦测 + all-NaN skip
- apply_updates SQL pattern (仅 UPDATE 2 列)
- _to_nullable NaN→None
- _fetch_target_factors 三种路径: explicit / all-factors / default active
- compute_and_update dry-run 路径
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import compute_ic_rolling as cir  # noqa: E402

# ────────── Constants ──────────


class TestConstants:
    def test_core_factors_matches_pt_config(self):
        """CORE_FACTORS 镜像 compute_daily_ic (单一真相源). CORE3+dv_ttm WF PASS."""
        assert cir.CORE_FACTORS == (
            "turnover_mean_20",
            "volatility_20",
            "bp_ratio",
            "dv_ttm",
        )

    def test_rolling_params_match_canonical(self):
        """canonical: factor_onboarding.py:739-740 rolling(20, min_periods=5) / (60, 10)."""
        assert cir.MA20_WINDOW == 20
        assert cir.MA20_MIN_PERIODS == 5
        assert cir.MA60_WINDOW == 60
        assert cir.MA60_MIN_PERIODS == 10

    def test_db_precision_matches_numeric_8_6(self):
        """factor_ic_history.ic_ma20/60 是 numeric(8,6) → round 6 位."""
        assert cir.DB_PRECISION == 6


# ────────── _to_nullable ──────────


class TestToNullable:
    def test_none_stays_none(self):
        assert cir._to_nullable(None) is None

    def test_nan_becomes_none(self):
        """铁律 29: NaN → None (DB NULL)."""
        assert cir._to_nullable(float("nan")) is None
        assert cir._to_nullable(np.nan) is None

    def test_float_passes_through(self):
        assert cir._to_nullable(0.123456) == 0.123456

    def test_zero_is_preserved(self):
        """0.0 ≠ NaN, 是合法 IC 值 (factor 完全无预测力)."""
        assert cir._to_nullable(0.0) == 0.0


# ────────── compute_rolling ──────────


class TestComputeRolling:
    def test_empty_df_returns_empty_with_cols(self):
        df = pd.DataFrame(columns=["factor_name", "trade_date", "ic_20d"])
        out = cir.compute_rolling(df)
        assert out.empty
        assert "ic_ma20_new" in out.columns
        assert "ic_ma60_new" in out.columns

    def test_formula_matches_factor_onboarding_canonical(self):
        """compute_rolling 与 factor_onboarding.py:739-740 精确对齐 (单因子)."""
        dates = pd.bdate_range("2024-01-01", periods=30).date
        ic_20d = np.linspace(0.01, 0.1, 30)
        df = pd.DataFrame(
            {
                "factor_name": "foo",
                "trade_date": dates,
                "ic_20d": ic_20d,
            }
        )
        out = cir.compute_rolling(df)

        # Canonical 算法直接复制
        expected_ma20 = pd.Series(ic_20d).rolling(window=20, min_periods=5).mean().round(6).tolist()
        expected_ma60 = (
            pd.Series(ic_20d).rolling(window=60, min_periods=10).mean().round(6).tolist()
        )
        # NaN 不能直接相等, 逐行比
        got_ma20 = out["ic_ma20_new"].tolist()
        got_ma60 = out["ic_ma60_new"].tolist()
        for e, g in zip(expected_ma20, got_ma20, strict=True):
            if pd.isna(e):
                assert pd.isna(g)
            else:
                assert abs(e - g) < 1e-9
        for e, g in zip(expected_ma60, got_ma60, strict=True):
            if pd.isna(e):
                assert pd.isna(g)
            else:
                assert abs(e - g) < 1e-9

    def test_groupby_isolates_factors_no_bleed(self):
        """两因子混合, 因子 A 的 rolling 不能引入因子 B 的 ic_20d."""
        rows = []
        # factor_A: 20 个 0.1 值
        for i in range(20):
            rows.append(("factor_A", date(2024, 1, 1 + i), 0.1))
        # factor_B: 20 个 0.5 值 (按 trade_date 和 A 重叠)
        for i in range(20):
            rows.append(("factor_B", date(2024, 1, 1 + i), 0.5))
        df = pd.DataFrame(rows, columns=["factor_name", "trade_date", "ic_20d"])

        out = cir.compute_rolling(df)
        # 每因子第 20 行 (达到 window=20) ic_ma20_new 应等于本因子值
        last_A = out[out["factor_name"] == "factor_A"].iloc[-1]
        last_B = out[out["factor_name"] == "factor_B"].iloc[-1]
        assert abs(last_A["ic_ma20_new"] - 0.1) < 1e-6
        assert abs(last_B["ic_ma20_new"] - 0.5) < 1e-6

    def test_min_periods_short_tail_returns_nan(self):
        """MA20 min_periods=5 — 前 4 行应为 NaN."""
        dates = pd.bdate_range("2024-01-01", periods=6).date
        df = pd.DataFrame(
            {
                "factor_name": "foo",
                "trade_date": dates,
                "ic_20d": [0.01, 0.02, 0.03, 0.04, 0.05, 0.06],
            }
        )
        out = cir.compute_rolling(df)
        # 前 4 行 NaN, 第 5 行开始有值
        assert pd.isna(out["ic_ma20_new"].iloc[0])
        assert pd.isna(out["ic_ma20_new"].iloc[3])
        assert not pd.isna(out["ic_ma20_new"].iloc[4])
        # ma60 min_periods=10, 6 行全 NaN
        assert out["ic_ma60_new"].isna().all()

    def test_rounding_to_db_precision(self):
        """输出 round 到 6 位以匹配 numeric(8,6)."""
        dates = pd.bdate_range("2024-01-01", periods=20).date
        df = pd.DataFrame(
            {
                "factor_name": "foo",
                "trade_date": dates,
                "ic_20d": [0.1234567890123] * 20,
            }
        )
        out = cir.compute_rolling(df)
        last = out["ic_ma20_new"].iloc[-1]
        # rolling mean 理论值 = 0.1234567890123, round 6 → 0.123457
        assert last == round(0.1234567890123, 6)

    def test_sorts_within_factor(self):
        """输入乱序时内部按 (factor_name, trade_date) 排序 → rolling 按时间顺序."""
        dates = [date(2024, 1, 3), date(2024, 1, 1), date(2024, 1, 2)]  # 乱序
        df = pd.DataFrame(
            {
                "factor_name": ["foo", "foo", "foo"],
                "trade_date": dates,
                "ic_20d": [0.3, 0.1, 0.2],  # 对应原日期
            }
        )
        out = cir.compute_rolling(df)
        # 排序后应为 1/1:0.1 / 1/2:0.2 / 1/3:0.3, min_periods=5 未满 → 全 NaN
        # 但排序结果应按 trade_date 升序
        assert list(out["trade_date"]) == sorted(dates)
        assert list(out["ic_20d"]) == [0.1, 0.2, 0.3]


# ────────── diff_updates ──────────


class TestDiffUpdates:
    def _make_computed(self, rows):
        """rows: list[(factor, date, ic_20d, cur_ma20, cur_ma60, new_ma20, new_ma60)]."""
        return pd.DataFrame(
            rows,
            columns=[
                "factor_name",
                "trade_date",
                "ic_20d",
                "ic_ma20",
                "ic_ma60",
                "ic_ma20_new",
                "ic_ma60_new",
            ],
        )

    def test_idempotent_equal_values_skipped(self):
        """current = new → skip."""
        df = self._make_computed(
            [("foo", date(2024, 1, 1), 0.05, 0.047234, 0.048123, 0.047234, 0.048123)]
        )
        updates = cir.diff_updates(df)
        assert updates == []

    def test_current_null_triggers_update(self):
        """首次回填: current NULL, new 有值 → UPDATE."""
        df = self._make_computed(
            [("foo", date(2024, 1, 1), 0.05, np.nan, np.nan, 0.047234, 0.048123)]
        )
        updates = cir.diff_updates(df)
        assert len(updates) == 1
        assert updates[0] == ("foo", date(2024, 1, 1), 0.047234, 0.048123)

    def test_value_change_triggers_update(self):
        """new 与 current 不同 → UPDATE."""
        df = self._make_computed(
            [("foo", date(2024, 1, 1), 0.05, 0.040000, 0.042000, 0.050000, 0.052000)]
        )
        updates = cir.diff_updates(df)
        assert len(updates) == 1
        assert updates[0][2] == 0.05
        assert updates[0][3] == 0.052

    def test_all_null_row_skipped(self):
        """new 和 current 都 NaN (min_periods 未满) → skip 无意义 UPDATE."""
        df = self._make_computed([("foo", date(2024, 1, 1), 0.05, np.nan, np.nan, np.nan, np.nan)])
        updates = cir.diff_updates(df)
        assert updates == []

    def test_partial_null_one_column_changes(self):
        """只 ic_ma20 值变, ic_ma60 仍 NaN → UPDATE (new_ma60 也 None)."""
        df = self._make_computed([("foo", date(2024, 1, 1), 0.05, np.nan, np.nan, 0.04, np.nan)])
        updates = cir.diff_updates(df)
        assert len(updates) == 1
        assert updates[0] == ("foo", date(2024, 1, 1), 0.04, None)

    def test_empty_df(self):
        df = pd.DataFrame(
            columns=[
                "factor_name",
                "trade_date",
                "ic_20d",
                "ic_ma20",
                "ic_ma60",
                "ic_ma20_new",
                "ic_ma60_new",
            ]
        )
        assert cir.diff_updates(df) == []


# ────────── apply_updates ──────────


class TestApplyUpdates:
    def test_empty_updates_returns_zero(self):
        mock_conn = MagicMock()
        assert cir.apply_updates(mock_conn, []) == 0
        # 不应开 cursor
        mock_conn.cursor.assert_not_called()

    def test_sql_updates_only_ma_columns(self):
        """SQL SET 只涉 ic_ma20 / ic_ma60, 不触 ic_5d/10d/20d/ic_abs_5d/decay_level.

        铁律 17 例外: 本脚本 UPDATE 2 列, 不能走 DataPipeline (会 NULL 化其他列).
        """
        from unittest.mock import patch

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.rowcount = 3
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        updates = [
            ("foo", date(2024, 1, 1), 0.04, 0.05),
            ("foo", date(2024, 1, 2), 0.041, 0.051),
            ("bar", date(2024, 1, 1), 0.02, None),
        ]

        with patch("compute_ic_rolling.psycopg2.extras.execute_values") as mock_ev:
            n = cir.apply_updates(mock_conn, updates)

        assert n == 3
        mock_ev.assert_called_once()
        call_args = mock_ev.call_args
        sql = call_args[0][1]
        rows = call_args[0][2]
        # SET 必须只含 ic_ma20 / ic_ma60
        assert "ic_ma20" in sql
        assert "ic_ma60" in sql
        # 不应触 ic_5d / 10d / 20d / decay_level / ic_abs
        assert "ic_5d" not in sql
        assert "ic_10d" not in sql
        assert "ic_20d" not in sql
        assert "ic_abs" not in sql
        assert "decay_level" not in sql
        # WHERE 必须按 pk 匹配
        assert "factor_name" in sql
        assert "trade_date" in sql
        # 行数正确传入
        assert len(rows) == 3


# ────────── _fetch_target_factors ──────────


class TestFetchTargetFactors:
    def test_explicit_list_short_circuits(self):
        """explicit 提供时不查 DB."""
        mock_conn = MagicMock()
        result = cir._fetch_target_factors(mock_conn, ["foo", "bar"], all_factors=False)
        assert result == ["foo", "bar"]
        mock_conn.cursor.assert_not_called()

    def test_default_reads_active_and_warning(self):
        """default 读 factor_registry active + warning (排除 retired/critical/candidate)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("bp_ratio",), ("dv_ttm",)]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = cir._fetch_target_factors(mock_conn, None, all_factors=False)

        assert result == ["bp_ratio", "dv_ttm"]
        sql_arg = mock_cur.execute.call_args[0][0]
        assert "factor_registry" in sql_arg
        assert "active" in sql_arg
        assert "warning" in sql_arg

    def test_all_factors_reads_from_ic_history(self):
        """--all-factors 读 factor_ic_history (含 retired)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("foo",), ("bar",), ("baz",)]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = cir._fetch_target_factors(mock_conn, None, all_factors=True)

        assert result == ["foo", "bar", "baz"]
        sql_arg = mock_cur.execute.call_args[0][0]
        assert "factor_ic_history" in sql_arg
        assert "ic_20d IS NOT NULL" in sql_arg


# ────────── _load_ic_20d ──────────


class TestLoadIc20d:
    def test_empty_factors_returns_empty(self):
        mock_conn = MagicMock()
        df = cir._load_ic_20d(mock_conn, [])
        assert df.empty
        assert list(df.columns) == [
            "factor_name",
            "trade_date",
            "ic_20d",
            "ic_ma20",
            "ic_ma60",
        ]
        mock_conn.cursor.assert_not_called()

    def test_sql_filters_non_null_ic_20d(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [
            ("foo", date(2024, 1, 1), 0.05, 0.04, None),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        df = cir._load_ic_20d(mock_conn, ["foo"])

        assert len(df) == 1
        assert df.iloc[0]["factor_name"] == "foo"
        sql_arg = mock_cur.execute.call_args[0][0]
        assert "ic_20d IS NOT NULL" in sql_arg
        # 按 (factor_name, trade_date) 排序
        assert "ORDER BY factor_name, trade_date" in sql_arg


# ────────── compute_and_update integration ──────────


class TestComputeAndUpdate:
    def _setup_mock_conn(self, factors_rows, ic_rows):
        """helper: mock conn.cursor 返回两轮 fetchall (factors → ic_20d)."""
        mock_conn = MagicMock()
        mock_cur1 = MagicMock()
        mock_cur1.fetchall.return_value = factors_rows
        mock_cur2 = MagicMock()
        mock_cur2.fetchall.return_value = ic_rows

        # cursor() 返回 ctx manager. 第一次 (fetch_target_factors), 第二次 (load_ic_20d).
        # 注意: 如果 factors 是 explicit, 只会 call 1 次.
        ctx1 = MagicMock()
        ctx1.__enter__ = MagicMock(return_value=mock_cur1)
        ctx1.__exit__ = MagicMock(return_value=False)
        ctx2 = MagicMock()
        ctx2.__enter__ = MagicMock(return_value=mock_cur2)
        ctx2.__exit__ = MagicMock(return_value=False)
        mock_conn.cursor.side_effect = [ctx1, ctx2]
        return mock_conn

    def test_dry_run_no_updates_applied(self):
        """dry_run=True 计算 planned_updates 但不调 apply_updates."""
        # Explicit factors → 跳过 _fetch_target_factors 的 cursor
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # 20 个数据点 (达到 min_periods=5 for ma20)
        rows = [("foo", date(2024, 1, i + 1), 0.05, None, None) for i in range(20)]
        mock_cur.fetchall.return_value = rows
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = cir.compute_and_update(mock_conn, factors=["foo"], all_factors=False, dry_run=True)

        assert result["processed_factors"] == 1
        assert result["total_ic20d_rows"] == 20
        # 首次回填 (current NULL), planned updates > 0
        assert result["planned_updates"] > 0
        assert result["applied_updates"] == 0  # dry_run

    def test_no_factors_returns_empty_summary(self):
        """无 target factor 直接退出."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = cir.compute_and_update(mock_conn, factors=None, all_factors=False, dry_run=True)

        assert result["processed_factors"] == 0
        assert result["total_ic20d_rows"] == 0
        assert result["planned_updates"] == 0
