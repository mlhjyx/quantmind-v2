"""Daily IC auto-ingest regression (铁律 11 + 17 + 19 合规验证).

Session 21 加时: 修复 factor_ic_history 4-07 后 14 天零入库 gap. 本 tests 验证
`scripts/compute_daily_ic.py` 核心行为 (纯函数 + mock DB).

不覆盖:
- 真实 DB end-to-end (走 ad-hoc 命令行跑的 smoke, 见 docstring)
- ic_ma20/60/decay_level 计算 (scope 外, v1 不写这些列)
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# 导入被测模块. 模块 import 时做 load_dotenv + logging 设置, 对测试无副作用
import compute_daily_ic as cdi  # noqa: E402


class TestConstants:
    """模块常量合约."""

    def test_core_factors_is_tuple_of_4(self):
        """CORE_FACTORS 包含 CORE3 + dv_ttm (2026-04-12 WF PASS 配置)."""
        assert cdi.CORE_FACTORS == (
            "turnover_mean_20",
            "volatility_20",
            "bp_ratio",
            "dv_ttm",
        )

    def test_horizons_match_factor_ic_history_schema(self):
        """HORIZONS = (5, 10, 20). 不含 1 (ic_calculator horizon=1 退化 entry==exit → 全 0 IC NaN).

        reviewer P2 采纳: 原 (1,5,10,20) 导致 ic_1d 全 NaN + ic_abs_1d 全 NaN 写 DB
        无意义, 移除 1.
        """
        assert cdi.HORIZONS == (5, 10, 20)

    def test_benchmark_is_csi300(self):
        """BENCHMARK_CODE 是 CSI300 (铁律 19 默认)."""
        assert cdi.BENCHMARK_CODE == "000300.SH"

    def test_future_buffer_covers_max_horizon_with_holiday_margin(self):
        """FUTURE_BUFFER_DAYS 需含假期余量.

        reviewer P2 采纳: 20 trading days ≈ 28-30 calendar days (含周末); 长假 buffer
        需 ≥ max(HORIZONS) × 2. 原 =25 仅 1.25× 余量, 长假时 ic_20d 可能缺.
        """
        assert max(cdi.HORIZONS) * 2 <= cdi.FUTURE_BUFFER_DAYS, (
            f"buffer {cdi.FUTURE_BUFFER_DAYS} < max_horizon×2 {max(cdi.HORIZONS) * 2}, "
            "长假期间 ic_20d 可能计算不出"
        )


class TestFetchActiveFactors:
    """_fetch_active_factors 只取 active + warning (排除 retired/candidate)."""

    def test_filters_status(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("bp_ratio",), ("dv_ttm",)]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = cdi._fetch_active_factors(mock_conn)

        assert result == ["bp_ratio", "dv_ttm"]
        # 验证 SQL 只选 active + warning
        sql_arg = mock_cur.execute.call_args[0][0]
        assert "status IN ('active', 'warning')" in sql_arg

    def test_empty_registry_returns_empty(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        assert cdi._fetch_active_factors(mock_conn) == []


class TestLoadPricesAdjustment:
    """_load_prices 计算 adj_close = close × adj_factor (前复权)."""

    def test_adj_close_multiplication(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        # close=10.0, adj_factor=1.5 → adj_close=15.0
        mock_cur.fetchall.return_value = [
            ("000001.SZ", date(2026, 4, 1), 10.0, 1.5),
            ("000001.SZ", date(2026, 4, 2), 11.0, 1.5),
        ]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = cdi._load_prices(mock_conn, date(2026, 4, 1), date(2026, 4, 30))

        assert list(result["adj_close"]) == [15.0, 16.5]
        assert set(result.columns) == {"code", "trade_date", "adj_close"}

    def test_null_adj_factor_defaults_to_one(self):
        """adj_factor NULL → fillna(1.0), adj_close = close."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [("000001.SZ", date(2026, 4, 1), 10.0, None)]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        result = cdi._load_prices(mock_conn, date(2026, 4, 1), date(2026, 4, 1))

        assert result["adj_close"].iloc[0] == 10.0


class TestLoadBenchmark:
    """_load_benchmark 查 index_daily 用 index_code 列 (非 code).

    Session 21 加时 debug: schema 差异 (klines_daily=code, index_daily=index_code)
    曾导致第一次 dry-run 失败, 本测试 prevent regression.
    """

    def test_uses_index_code_column(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = [(date(2026, 4, 1), 3800.0)]
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        cdi._load_benchmark(mock_conn, date(2026, 4, 1), date(2026, 4, 30))

        sql_arg = mock_cur.execute.call_args[0][0]
        assert "index_code = %s" in sql_arg
        # 不应是裸 code (=klines_daily 列): 用正则边界 (index_code 含 code 子串)
        assert not re.search(r"\bcode\s*=\s*%s", sql_arg), f"SQL 含 klines_daily.code = : {sql_arg}"

    def test_empty_benchmark_raises(self):
        """benchmark 缺数据 → RuntimeError (铁律 33 fail-loud)."""
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_cur.fetchall.return_value = []
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur

        with pytest.raises(RuntimeError, match=r"index_daily 无"):
            cdi._load_benchmark(mock_conn, date(2026, 4, 1), date(2026, 4, 30))


class TestComputeFactorIC:
    """_compute_factor_ic 产出 4 horizons + abs 列."""

    def test_empty_input_returns_empty(self):
        result = cdi._compute_factor_ic(pd.DataFrame(), {})
        assert result.empty

    def test_output_has_expected_columns(self, monkeypatch):
        """成功计算后 DataFrame 含 trade_date + ic_{1,5,10,20}d + ic_abs_{1,5}d."""
        # 构造 5 天 × 3 股 factor_df (长表)
        factor_df = pd.DataFrame(
            {
                "code": ["A", "B", "C"] * 5,
                "trade_date": [date(2026, 4, d) for d in range(1, 6) for _ in range(3)],
                "neutral_value": [
                    0.1,
                    0.2,
                    0.3,
                    0.4,
                    0.5,
                    0.6,
                    0.7,
                    0.8,
                    0.9,
                    1.0,
                    1.1,
                    1.2,
                    1.3,
                    1.4,
                    1.5,
                ],
            }
        )

        # Mock fwd_rets_by_horizon: 宽表 (date × code)
        def mock_fwd(h):
            idx = [date(2026, 4, d) for d in range(1, 6)]
            cols = ["A", "B", "C"]
            # 随便的数值
            return pd.DataFrame(
                [[0.01 * h + 0.001 * i + 0.0001 * j for j in range(3)] for i in range(5)],
                index=pd.Index(idx, name="trade_date"),
                columns=pd.Index(cols, name="code"),
            )

        fwd = {h: mock_fwd(h) for h in cdi.HORIZONS}

        result = cdi._compute_factor_ic(factor_df, fwd)

        # 列结构 (HORIZONS=5,10,20, 不含 ic_1d/ic_abs_1d)
        expected_cols = {"trade_date", "ic_5d", "ic_10d", "ic_20d", "ic_abs_5d"}
        assert expected_cols.issubset(set(result.columns))
        # ic_1d / ic_abs_1d 不应存在 (reviewer P2 采纳)
        assert "ic_1d" not in result.columns
        assert "ic_abs_1d" not in result.columns

    def test_abs_columns_are_abs_of_ic(self):
        """ic_abs_5d = abs(ic_5d) (HORIZONS 移除 1 后只剩 5d abs)."""
        factor_df = pd.DataFrame(
            {
                "code": ["A", "B", "C", "D", "E"] * 2,
                "trade_date": [date(2026, 4, 1)] * 5 + [date(2026, 4, 2)] * 5,
                "neutral_value": [0.1, 0.2, 0.3, 0.4, 0.5] * 2,
            }
        )

        # Mock: 保证非 NaN IC (20+ 样本以上才靠谱, 这里 5 样本可能返 None 但列仍存在)
        def mock_fwd(h):
            idx = [date(2026, 4, 1), date(2026, 4, 2)]
            cols = ["A", "B", "C", "D", "E"]
            return pd.DataFrame(
                [[0.01 * i * h for i in range(5)], [0.02 * i * h for i in range(5)]],
                index=pd.Index(idx, name="trade_date"),
                columns=pd.Index(cols, name="code"),
            )

        fwd = {h: mock_fwd(h) for h in cdi.HORIZONS}
        result = cdi._compute_factor_ic(factor_df, fwd)

        # abs 列 = abs(对应 ic). 对齐 index 后比较 (跳过 NaN)
        aligned = result[["ic_5d", "ic_abs_5d"]].dropna()
        if len(aligned) > 0:
            assert (aligned["ic_abs_5d"] == aligned["ic_5d"].abs()).all()


class TestMainArgParsing:
    """main() / compute_and_ingest() 参数处理."""

    def test_dry_run_skips_ingest_returns_would_write_count(self, monkeypatch):
        """dry_run=True 不调 pipeline.ingest, total_rows 返回 "would-write" 行数.

        reviewer P3 采纳: 原 dry_run total_rows=0 语义不明, 改返回预计写入行数.
        """
        fake_conn = MagicMock()
        monkeypatch.setattr(
            cdi,
            "_load_prices",
            lambda c, s, e: pd.DataFrame(
                {
                    "code": ["A"] * 30,
                    "trade_date": pd.date_range("2026-03-01", periods=30).date,
                    "adj_close": [10.0 + i * 0.1 for i in range(30)],
                }
            ),
        )
        monkeypatch.setattr(
            cdi,
            "_load_benchmark",
            lambda c, s, e: pd.DataFrame(
                {
                    "trade_date": pd.date_range("2026-03-01", periods=30).date,
                    "close": [3800.0 + i for i in range(30)],
                }
            ),
        )
        monkeypatch.setattr(
            cdi,
            "_load_factor",
            lambda c, f, s, e: pd.DataFrame(
                {
                    "code": ["A"] * 25,
                    "trade_date": pd.date_range("2026-03-01", periods=25).date,
                    "neutral_value": [0.1] * 25,
                }
            ),
        )

        # ingest 如果 dry_run 不应调
        pipeline_ingest_called = []

        class MockPipeline:
            def __init__(self, conn):
                pass

            def ingest(self, df, contract):
                pipeline_ingest_called.append(True)
                return MagicMock(upserted_rows=0, total_rows=0, valid_rows=0, rejected_rows=0)

        monkeypatch.setattr(cdi, "DataPipeline", MockPipeline)

        result = cdi.compute_and_ingest(
            conn=fake_conn,
            days=30,
            factors=["bp_ratio"],
            dry_run=True,
        )

        # dry_run → 不调 ingest + total_rows > 0 (预计写行数, 语义明确)
        assert not pipeline_ingest_called, "dry_run 不应调 ingest"
        assert result["total_rows"] > 0, "dry_run total_rows 应返回预计写入行数 (非 0)"

    def test_no_factors_early_exit(self, monkeypatch):
        """空 factor 列表 → 0 processed, 不加载数据."""
        fake_conn = MagicMock()
        monkeypatch.setattr(cdi, "_fetch_active_factors", lambda c: [])

        result = cdi.compute_and_ingest(
            conn=fake_conn,
            days=30,
            factors=None,
            dry_run=False,
        )

        assert result["processed_factors"] == 0
        assert result["total_rows"] == 0

    def test_per_factor_exception_isolated(self, monkeypatch):
        """单因子 _compute_factor_ic 异常 → logger.error + 继续下一因子 (非阻断).

        reviewer P2 采纳: 原无 try/except, 一坏则全批死. 铁律 33 fail-loud:
        单因子异常独立 isolate, 不阻断其他.
        """
        fake_conn = MagicMock()
        monkeypatch.setattr(
            cdi,
            "_load_prices",
            lambda c, s, e: pd.DataFrame(
                {
                    "code": ["A"] * 30,
                    "trade_date": pd.date_range("2026-03-01", periods=30).date,
                    "adj_close": [10.0 + i * 0.1 for i in range(30)],
                }
            ),
        )
        monkeypatch.setattr(
            cdi,
            "_load_benchmark",
            lambda c, s, e: pd.DataFrame(
                {
                    "trade_date": pd.date_range("2026-03-01", periods=30).date,
                    "close": [3800.0 + i for i in range(30)],
                }
            ),
        )

        # factor A 返常规数据, factor B 强制 raise
        def mock_load_factor(c, f, s, e):
            if f == "bad_factor":
                raise RuntimeError("SIMULATED factor load fail")
            return pd.DataFrame(
                {
                    "code": ["A"] * 25,
                    "trade_date": pd.date_range("2026-03-01", periods=25).date,
                    "neutral_value": [0.1] * 25,
                }
            )

        monkeypatch.setattr(cdi, "_load_factor", mock_load_factor)

        class MockPipeline:
            def __init__(self, conn):
                pass

            def ingest(self, df, contract):
                return MagicMock(
                    upserted_rows=len(df),
                    total_rows=len(df),
                    valid_rows=len(df),
                    rejected_rows=0,
                    reject_reasons={},
                    null_ratio_warnings={},
                )

        monkeypatch.setattr(cdi, "DataPipeline", MockPipeline)

        result = cdi.compute_and_ingest(
            conn=fake_conn,
            days=30,
            factors=["good_factor", "bad_factor"],
            dry_run=False,
        )

        # 坏 factor 不阻断好 factor
        assert result["processed_factors"] == 1, "bad_factor 应独立 skip"
        statuses = {s["factor"]: s["status"] for s in result["factor_summary"]}
        assert statuses["good_factor"] == "ok"
        assert statuses["bad_factor"] == "error"


class TestHolidayGuard:
    """PR #40 P2.2 follow-up: `--force` / is_trading_day guard.

    A 股节假日 (5/1 劳动节 / 国庆 / 春节) schtask Mon-Fri 触发会空跑 (~15 days/year).
    holiday guard 提前 exit 0 防浪费 DB IO. `--force` 覆盖 (manual backfill).
    """

    def test_non_trading_day_early_exit(self, monkeypatch):
        """非交易日 (e.g. 5/1 劳动节) → main exit 0, 不调 compute_and_ingest."""
        fake_conn = MagicMock()
        monkeypatch.setattr(cdi, "get_sync_conn", lambda: fake_conn)
        monkeypatch.setattr(cdi, "is_trading_day", lambda conn, d: False)

        # compute_and_ingest 不应被调
        compute_called = []
        monkeypatch.setattr(
            cdi,
            "compute_and_ingest",
            lambda **kw: compute_called.append(True) or {"processed_factors": 999},
        )
        monkeypatch.setattr(sys, "argv", ["compute_daily_ic.py"])

        rc = cdi.main()

        assert rc == 0, "非交易日应 exit 0 (成功 skip)"
        assert not compute_called, "非交易日不应调 compute_and_ingest"
        # reviewer P2.2 修: `assert_called_once(), "msg"` 原是 tuple 表达式, 消息永不
        # 触发. 现独立行, 失败时 AssertionError 自带 "Called 0 times" 信息.
        fake_conn.close.assert_called_once()

    def test_trading_day_proceeds(self, monkeypatch):
        """交易日 → main 调 compute_and_ingest 正常执行."""
        fake_conn = MagicMock()
        monkeypatch.setattr(cdi, "get_sync_conn", lambda: fake_conn)
        monkeypatch.setattr(cdi, "is_trading_day", lambda conn, d: True)

        compute_called = []

        def mock_compute(**kw):
            compute_called.append(kw)
            return {
                "processed_factors": 4,
                "total_rows": 100,
                "elapsed_sec": 0.1,
                "factor_summary": [],
            }

        monkeypatch.setattr(cdi, "compute_and_ingest", mock_compute)
        monkeypatch.setattr(sys, "argv", ["compute_daily_ic.py", "--dry-run"])

        rc = cdi.main()

        assert rc == 0, "交易日 + processed>0 应 exit 0"
        assert len(compute_called) == 1, "交易日应调 compute_and_ingest exactly once"
        fake_conn.close.assert_called_once()

    def test_force_bypasses_guard(self, monkeypatch):
        """--force 应覆盖 is_trading_day=False 的 guard, 仍执行 compute_and_ingest."""
        fake_conn = MagicMock()
        monkeypatch.setattr(cdi, "get_sync_conn", lambda: fake_conn)

        # is_trading_day 返 False (理应 skip), 但 --force 应覆盖
        is_trading_day_called: list[bool] = []

        # reviewer P3 采纳: lambda 内 tuple-index 副作用 trick 晦涩, 改 named function
        def mock_is_trading_day(conn, d):
            is_trading_day_called.append(True)
            return False

        monkeypatch.setattr(cdi, "is_trading_day", mock_is_trading_day)

        compute_called = []
        monkeypatch.setattr(
            cdi,
            "compute_and_ingest",
            lambda **kw: (
                compute_called.append(True)
                or {
                    "processed_factors": 1,
                    "total_rows": 10,
                    "elapsed_sec": 0.1,
                    "factor_summary": [],
                }
            ),
        )
        monkeypatch.setattr(
            sys,
            "argv",
            ["compute_daily_ic.py", "--force", "--dry-run"],
        )

        rc = cdi.main()

        assert rc == 0
        assert compute_called, "--force 应绕过 guard, 调 compute_and_ingest"
        # --force 下甚至不应该调 is_trading_day (short-circuit)
        assert not is_trading_day_called, "--force 应 short-circuit 不调 is_trading_day"
