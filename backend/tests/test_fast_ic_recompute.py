"""fast_ic_recompute.py 迁移回归测试 (Session 23 Part 1 铁律合规重构).

历史版本 (重构前) 走 `execute_values("INSERT INTO factor_ic_history (factor_name,
trade_date, ic_1d, ic_5d, ic_10d, ic_20d) ... ON CONFLICT ... DO UPDATE SET
ic_1d=..., ic_5d=..., ...")` + Service 层 `conn.commit()`, 违反铁律 17 + 32.

本 Session 23 重构: `upsert_ic_history` → `upsert_ic_history_partial` **铁律 17 例外**
(对齐 compute_ic_rolling.py PR #43 模式):
- 手工 partial-column UPSERT 仅 SET 4 列 (ic_5d/ic_10d/ic_20d/ic_abs_5d)
- 保护 ic_1d/ic_abs_1d/ic_ma20/ic_ma60/decay_level 不被 NULL 覆盖 (compute_ic_rolling
  + factor_decay 写入的数据)
- 不走 DataPipeline.ingest (reviewer CRITICAL P1 PR #45: 会 NULL 化其他列)
- main() 统一 commit/rollback (铁律 32)

覆盖:
- 铁律 17 例外 scope: SQL 只 SET 4 列 (ic_5d/10d/20d/ic_abs_5d), 不 SET 保护列
- 铁律 32 合规: upsert_ic_history_partial 不 commit
- 铁律 19 一致: HORIZONS = (5, 10, 20), CORE_FACTORS 对齐 compute_daily_ic
- ic_abs_5d 由 records 派生 (对齐 compute_daily_ic scope)

不覆盖:
- 真实 DB end-to-end (走 ad-hoc 运行或 smoke)
- 12 年 price/benchmark 加载 (依赖 cache/backtest/*.parquet, 走 ad-hoc)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# 模块 import 执行 structlog/logging 配置, 对测试无副作用 (不走 DB)
import fast_ic_recompute as fir  # noqa: E402

# ────────── Constants 契约 ──────────


class TestConstants:
    def test_core_factors_aligns_with_compute_daily_ic(self):
        """CORE_FACTORS 对齐 PT live 配置 (CORE3+dv_ttm WF PASS, 2026-04-12)."""
        assert fir.CORE_FACTORS == [
            "turnover_mean_20",
            "volatility_20",
            "bp_ratio",
            "dv_ttm",
        ]

    def test_horizons_no_one(self):
        """HORIZONS 对齐 compute_daily_ic (PR #37 reviewer P2): 去掉 1.

        ic_calculator horizon=1 时 entry==exit → stock_ret 全 0 → spearmanr 退化
        NaN, 写入 ic_1d 无意义. factor_ic_history.ic_1d 列保留但不再由本脚本写入.
        """
        assert fir.HORIZONS == [5, 10, 20]
        assert 1 not in fir.HORIZONS


# ────────── upsert_ic_history_partial 铁律 17 例外 ──────────


class TestUpsertIcHistoryPartial:
    def _make_ic_df(self, n_rows: int = 5) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [date(2024, 1, i + 1) for i in range(n_rows)],
                "ic_5d": [0.01 * (i + 1) for i in range(n_rows)],
                "ic_10d": [0.02 * (i + 1) for i in range(n_rows)],
                "ic_20d": [0.03 * (i + 1) for i in range(n_rows)],
            }
        )

    def test_dry_run_short_circuits_without_cursor(self):
        """dry_run=True → 返回 len(ic_df) 不开 cursor (铁律 32)."""
        mock_conn = MagicMock()
        ic_df = self._make_ic_df(5)

        rows = fir.upsert_ic_history_partial(mock_conn, "foo", ic_df, dry_run=True)

        assert rows == 5
        mock_conn.cursor.assert_not_called()

    def test_empty_df_returns_zero(self):
        mock_conn = MagicMock()
        empty = pd.DataFrame(columns=["trade_date", "ic_5d", "ic_10d", "ic_20d"])
        assert fir.upsert_ic_history_partial(mock_conn, "foo", empty, dry_run=False) == 0
        mock_conn.cursor.assert_not_called()

    def test_sql_protects_ic_1d_ic_ma_and_decay_columns(self):
        """**铁律 17 例外核心契约**: SQL 只 SET ic_5d/10d/20d/ic_abs_5d,

        不可触 ic_1d / ic_abs_1d / ic_ma20 / ic_ma60 / decay_level (保护
        compute_ic_rolling + factor_decay 写入的数据).

        reviewer CRITICAL P1 PR #45: 初版走 DataPipeline 会 NULL 化这 5 列,
        修正为手工 partial UPSERT.
        """
        from unittest.mock import patch

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        ic_df = self._make_ic_df(5)

        with patch("fast_ic_recompute.execute_values") as mock_ev:
            fir.upsert_ic_history_partial(mock_conn, "bp_ratio", ic_df, dry_run=False)

        mock_ev.assert_called_once()
        sql = mock_ev.call_args[0][1]

        # SET 必须只含这 4 列
        assert "ic_5d = EXCLUDED.ic_5d" in sql
        assert "ic_10d = EXCLUDED.ic_10d" in sql
        assert "ic_20d = EXCLUDED.ic_20d" in sql
        assert "ic_abs_5d = EXCLUDED.ic_abs_5d" in sql

        # 关键保护: 这 5 列**不得**出现在 DO UPDATE SET 子句
        # (ic_1d 列存在于 INSERT 但不在 SET; 检查 SET 段内)
        set_clause_start = sql.find("DO UPDATE SET")
        assert set_clause_start > 0, "必须有 ON CONFLICT DO UPDATE SET 子句"
        set_clause = sql[set_clause_start:]

        assert "ic_1d = EXCLUDED" not in set_clause, (
            "铁律 17 例外违规: ic_1d 不得出现在 SET 子句 (保护 compute_daily_ic 历史数据)"
        )
        assert "ic_abs_1d" not in set_clause, "ic_abs_1d 不得出现在 SET 子句"
        assert "ic_ma20 = EXCLUDED" not in set_clause, (
            "铁律 17 例外违规: ic_ma20 不得出现在 SET 子句 (保护 compute_ic_rolling PR #43 的回填)"
        )
        assert "ic_ma60 = EXCLUDED" not in set_clause, (
            "铁律 17 例外违规: ic_ma60 不得出现在 SET 子句 (保护 compute_ic_rolling PR #43 的回填)"
        )
        assert "decay_level = EXCLUDED" not in set_clause, (
            "铁律 17 例外违规: decay_level 不得出现在 SET 子句 (保护 factor_decay 写入)"
        )

    def test_records_include_ic_abs_5d_derived_from_ic_5d(self):
        """ic_abs_5d 从 ic_5d 派生 abs() (对齐 compute_daily_ic scope)."""
        from unittest.mock import patch

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        # 负 ic_5d 测试 abs 派生
        ic_df = pd.DataFrame(
            {
                "trade_date": [date(2024, 1, 1)],
                "ic_5d": [-0.03],
                "ic_10d": [0.04],
                "ic_20d": [0.05],
            }
        )

        with patch("fast_ic_recompute.execute_values") as mock_ev:
            fir.upsert_ic_history_partial(mock_conn, "foo", ic_df, dry_run=False)

        records = mock_ev.call_args[0][2]
        assert len(records) == 1
        # record tuple: (factor_name, trade_date, ic_5d, ic_10d, ic_20d, ic_abs_5d)
        assert records[0][0] == "foo"
        assert records[0][2] == -0.03  # ic_5d 保持负值
        assert records[0][5] == 0.03  # ic_abs_5d 是 |ic_5d|

    def test_nan_values_convert_to_none(self):
        """铁律 29: NaN → None, ic_abs_5d 基于 ic_5d 也正确处理."""
        from unittest.mock import patch

        import numpy as np

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        ic_df = pd.DataFrame(
            {
                "trade_date": [date(2024, 1, 1)],
                "ic_5d": [np.nan],
                "ic_10d": [0.01],
                "ic_20d": [np.nan],
            }
        )

        with patch("fast_ic_recompute.execute_values") as mock_ev:
            fir.upsert_ic_history_partial(mock_conn, "foo", ic_df, dry_run=False)

        records = mock_ev.call_args[0][2]
        # (factor_name, trade_date, ic_5d, ic_10d, ic_20d, ic_abs_5d)
        assert records[0][2] is None  # ic_5d NaN → None
        assert records[0][3] == 0.01  # ic_10d 保持
        assert records[0][4] is None  # ic_20d NaN → None
        assert records[0][5] is None  # ic_abs_5d 基于 None ic_5d → None

    def test_does_not_commit(self):
        """铁律 32: upsert_ic_history_partial 不调 conn.commit (调用方 main() 管理)."""
        from unittest.mock import patch

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        ic_df = self._make_ic_df(5)
        with patch("fast_ic_recompute.execute_values"):
            fir.upsert_ic_history_partial(mock_conn, "foo", ic_df, dry_run=False)

        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_not_called()


# ────────── 源码 level 铁律 17 例外守护 ──────────


class TestIronLawCompliance:
    """source-code level 守护: 防止未来 reviewer 回退到 DataPipeline (会 NULL 化其他列)."""

    def test_no_datapipeline_ingest_for_factor_ic_history(self):
        """铁律 17 例外: 本脚本**不得**调 DataPipeline.ingest 写 factor_ic_history.

        reviewer CRITICAL P1 PR #45 根因: DataPipeline.ingest 会补缺失 nullable
        列为 None + DO UPDATE SET non_pk = EXCLUDED, NULL 化 ic_ma20/60/decay_level
        等保护列. 对齐 compute_ic_rolling.py 同样绕过.
        """
        src = (SCRIPTS_DIR / "fast_ic_recompute.py").read_text(encoding="utf-8")
        # 允许 docstring 引用 "DataPipeline" 解释为什么不用, 但不得有实际调用
        assert "DataPipeline(conn=" not in src, (
            "铁律 17 例外违规: 不得实例化 DataPipeline (会 NULL 化保护列)"
        )
        assert "pipeline.ingest(" not in src, (
            "铁律 17 例外违规: 不得调 pipeline.ingest (会 NULL 化保护列)"
        )

    def test_no_service_commit_in_upsert_function(self):
        """铁律 32: upsert_ic_history_partial 函数体不得含 conn.commit."""
        import inspect

        src = inspect.getsource(fir.upsert_ic_history_partial)
        assert "conn.commit" not in src

    def test_sql_set_clause_scope_documented(self):
        """docstring 必须含'铁律 17 例外'字样 (防后续误撤消保护)."""
        src = (SCRIPTS_DIR / "fast_ic_recompute.py").read_text(encoding="utf-8")
        assert "铁律 17 例外" in src, (
            "fast_ic_recompute 必须显式声明铁律 17 例外, 说明为什么不走 DataPipeline"
        )
