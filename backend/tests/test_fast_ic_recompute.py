"""fast_ic_recompute.py 迁移回归测试 (Session 23 Part 1 铁律合规重构).

历史版本 (PR #43 之前) 走 `execute_values("INSERT INTO factor_ic_history ... ON
CONFLICT")` 直接裸 INSERT + Service 层 `conn.commit()`, 违反铁律 17 + 32.

本 Session 23 重构: `upsert_ic_history` → `ingest_ic_history` 走 DataPipeline.ingest,
main() 统一 commit/rollback.

覆盖:
- 铁律 17 合规验证: 无 INSERT INTO factor_ic_history 裸 SQL, 走 DataPipeline
- 铁律 32 合规: ingest_ic_history 不 commit, dry_run=True 不入库
- 铁律 19 一致: HORIZONS = (5, 10, 20), CORE_FACTORS 对齐 compute_daily_ic
- ic_abs_5d 派生列 (对齐 compute_daily_ic scope, 不写 ic_ma20/60)

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


# ────────── ingest_ic_history 铁律 17 合规 ──────────


class TestIngestIcHistory:
    def _make_ic_df(self, n_rows: int = 5) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [date(2024, 1, i + 1) for i in range(n_rows)],
                "ic_5d": [0.01 * (i + 1) for i in range(n_rows)],
                "ic_10d": [0.02 * (i + 1) for i in range(n_rows)],
                "ic_20d": [0.03 * (i + 1) for i in range(n_rows)],
            }
        )

    def test_dry_run_short_circuits_without_pipeline_call(self):
        """dry_run=True → 返回 len(ic_df) 不调 pipeline.ingest (铁律 32)."""
        mock_pipeline = MagicMock()
        ic_df = self._make_ic_df(5)

        rows = fir.ingest_ic_history(mock_pipeline, "foo", ic_df, dry_run=True)

        assert rows == 5
        mock_pipeline.ingest.assert_not_called()

    def test_empty_df_returns_zero(self):
        mock_pipeline = MagicMock()
        empty = pd.DataFrame(columns=["trade_date", "ic_5d", "ic_10d", "ic_20d"])
        assert fir.ingest_ic_history(mock_pipeline, "foo", empty, dry_run=False) == 0
        mock_pipeline.ingest.assert_not_called()

    def test_ingest_path_uses_factor_ic_history_contract(self):
        """铁律 17: 走 DataPipeline.ingest(df, FACTOR_IC_HISTORY), 不裸 INSERT."""
        from app.data_fetcher.contracts import FACTOR_IC_HISTORY

        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_result.upserted_rows = 5
        mock_result.rejected_rows = 0
        mock_result.reject_reasons = {}
        mock_result.null_ratio_warnings = {}
        mock_pipeline.ingest.return_value = mock_result

        ic_df = self._make_ic_df(5)
        rows = fir.ingest_ic_history(mock_pipeline, "bp_ratio", ic_df, dry_run=False)

        assert rows == 5
        mock_pipeline.ingest.assert_called_once()
        call_args = mock_pipeline.ingest.call_args
        df_passed, contract_passed = call_args[0]
        # contract 必须是 FACTOR_IC_HISTORY (不是其他 contract)
        assert contract_passed is FACTOR_IC_HISTORY
        # factor_name 被注入 df
        assert "factor_name" in df_passed.columns
        assert (df_passed["factor_name"] == "bp_ratio").all()

    def test_derives_ic_abs_5d_not_ic_abs_1d(self):
        """派生列对齐 compute_daily_ic scope: 只派生 ic_abs_5d (HORIZONS 无 1)."""
        mock_pipeline = MagicMock()
        mock_result = MagicMock()
        mock_result.upserted_rows = 5
        mock_result.rejected_rows = 0
        mock_result.reject_reasons = {}
        mock_result.null_ratio_warnings = {}
        mock_pipeline.ingest.return_value = mock_result

        ic_df = self._make_ic_df(5)
        fir.ingest_ic_history(mock_pipeline, "foo", ic_df, dry_run=False)

        df_passed = mock_pipeline.ingest.call_args[0][0]
        # ic_abs_5d 必须存在且为 ic_5d 的 abs
        assert "ic_abs_5d" in df_passed.columns
        assert (df_passed["ic_abs_5d"] == df_passed["ic_5d"].abs()).all()
        # ic_abs_1d 不应手工派生 (HORIZONS 无 1), 由 DataPipeline auto-fill None
        assert "ic_abs_1d" not in df_passed.columns

    def test_ingest_does_not_commit(self):
        """铁律 32: ingest_ic_history 不调 conn.commit (调用方 main() 管理)."""
        mock_pipeline = MagicMock()
        mock_conn = MagicMock()
        mock_pipeline.conn = mock_conn
        mock_result = MagicMock()
        mock_result.upserted_rows = 5
        mock_result.rejected_rows = 0
        mock_result.reject_reasons = {}
        mock_result.null_ratio_warnings = {}
        mock_pipeline.ingest.return_value = mock_result

        ic_df = self._make_ic_df(5)
        fir.ingest_ic_history(mock_pipeline, "foo", ic_df, dry_run=False)

        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_not_called()


# ────────── 源码 AST-level 铁律 17 守护 ──────────


class TestIronLawCompliance:
    """source-code level 守护: 防止未来 reviewer 误引入裸 INSERT."""

    def test_no_raw_insert_into_factor_ic_history(self):
        """铁律 17: 源码不得含 `INSERT INTO factor_ic_history`."""
        src = (SCRIPTS_DIR / "fast_ic_recompute.py").read_text(encoding="utf-8")
        # 允许 docstring / comment 解释, 但不允许实际 SQL literal
        # 粗略检查: 不含 "INSERT INTO factor_ic_history"
        assert "INSERT INTO factor_ic_history" not in src, (
            "铁律 17 违规: fast_ic_recompute.py 不得裸 INSERT INTO factor_ic_history, "
            "必须走 DataPipeline.ingest(df, FACTOR_IC_HISTORY)"
        )

    def test_no_execute_values_import(self):
        """历史 `from psycopg2.extras import execute_values` 已移除 (铁律 17 副产物)."""
        src = (SCRIPTS_DIR / "fast_ic_recompute.py").read_text(encoding="utf-8")
        assert "from psycopg2.extras import execute_values" not in src

    def test_no_service_commit_in_ingest_function(self):
        """铁律 32: ingest_ic_history 函数体不得含 conn.commit."""
        import inspect

        src = inspect.getsource(fir.ingest_ic_history)
        assert "conn.commit" not in src
        assert "pipeline.conn.commit" not in src
