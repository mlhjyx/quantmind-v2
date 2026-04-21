"""F22 regression: DataPipeline NULL-ratio guard.

F22 背景 (Session 20 发现, Session 21 落地):
- 2026-04-15 起 Tushare daily_basic.dv_ttm / pe_ttm NULL 率异常漂移
  dv_ttm: 0% → 31.7% (4-15) → 100% (4-20)
  pe_ttm: 0% → 26.9% (4-15, 持平)
- DataPipeline 无 NULL 率校验, 脏数据静默入库 5 天 (4-15 → 4-20)
- 仅被 17:40 data_quality_report 事后识别

Fix (铁律 33 fail-loud):
- ColumnSpec 新增 null_ratio_max 字段 (None = 不校验)
- DataPipeline.ingest 新增 step 5.5: _check_null_ratio
- 超阈值 → logger.error + IngestResult.null_ratio_warnings 写 {col: ratio}
- 不 raise 不 drop rows (单列 100% NULL 时其他列可能正常, raise 阻断全批)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.data_fetcher import pipeline as pipeline_mod
from app.data_fetcher.contracts import (
    DAILY_BASIC,
    ColumnSpec,
    TableContract,
)
from app.data_fetcher.pipeline import DataPipeline, IngestResult

# ════════════════════════════════════════════════════════════
# Unit: ColumnSpec + IngestResult schema
# ════════════════════════════════════════════════════════════


class TestColumnSpecSchema:
    """ColumnSpec 向后兼容: null_ratio_max default None."""

    def test_default_null_ratio_max_is_none(self):
        """未显式传 null_ratio_max → None (不校验)."""
        spec = ColumnSpec("float")
        assert spec.null_ratio_max is None

    def test_explicit_null_ratio_max(self):
        """显式传 null_ratio_max=0.05 保留."""
        spec = ColumnSpec("float", null_ratio_max=0.05)
        assert spec.null_ratio_max == 0.05

    def test_combined_with_other_validations(self):
        """null_ratio_max 与 min_val/max_val 正交可同时配."""
        spec = ColumnSpec("float", min_val=0, max_val=100, null_ratio_max=0.10)
        assert spec.min_val == 0
        assert spec.max_val == 100
        assert spec.null_ratio_max == 0.10

    def test_null_ratio_max_domain_lower_boundary(self):
        """null_ratio_max=0.0 合法 (reviewer P3 域校验)."""
        spec = ColumnSpec("float", null_ratio_max=0.0)
        assert spec.null_ratio_max == 0.0

    def test_null_ratio_max_domain_upper_boundary(self):
        """null_ratio_max=1.0 合法 (100% NULL 总是 OK)."""
        spec = ColumnSpec("float", null_ratio_max=1.0)
        assert spec.null_ratio_max == 1.0

    def test_null_ratio_max_exceeds_upper_raises(self):
        """null_ratio_max=1.5 → ValueError (reviewer P3 域校验, import 时即 fail-fast)."""
        with pytest.raises(ValueError, match=r"null_ratio_max must be in"):
            ColumnSpec("float", null_ratio_max=1.5)

    def test_null_ratio_max_negative_raises(self):
        """null_ratio_max=-0.1 → ValueError (负值无意义)."""
        with pytest.raises(ValueError, match=r"null_ratio_max must be in"):
            ColumnSpec("float", null_ratio_max=-0.1)


class TestIngestResultSchema:
    """IngestResult null_ratio_warnings default empty dict."""

    def test_default_null_ratio_warnings_empty(self):
        """不传 null_ratio_warnings → 空 dict (向后兼容)."""
        result = IngestResult(
            table="test", total_rows=0, valid_rows=0, rejected_rows=0, upserted_rows=0
        )
        assert result.null_ratio_warnings == {}

    def test_explicit_null_ratio_warnings(self):
        """传入具体 warnings dict 保留."""
        warnings = {"dv_ttm": 0.317, "pe_ttm": 0.269}
        result = IngestResult(
            table="daily_basic",
            total_rows=5490,
            valid_rows=5490,
            rejected_rows=0,
            upserted_rows=5490,
            null_ratio_warnings=warnings,
        )
        assert result.null_ratio_warnings == warnings


# ════════════════════════════════════════════════════════════
# DAILY_BASIC contract config (F22 具体落地)
# ════════════════════════════════════════════════════════════


class TestDailyBasicContractConfig:
    """daily_basic 在 F22 后 dv_ttm / pe_ttm 必须有 null_ratio_max=0.05."""

    def test_dv_ttm_has_threshold(self):
        """DAILY_BASIC.dv_ttm null_ratio_max=0.05 (历史 0% NULL, 5% 留容差)."""
        dv_spec = DAILY_BASIC.columns["dv_ttm"]
        assert dv_spec.null_ratio_max == 0.05

    def test_pe_ttm_has_threshold(self):
        """DAILY_BASIC.pe_ttm null_ratio_max=0.05."""
        pe_spec = DAILY_BASIC.columns["pe_ttm"]
        assert pe_spec.null_ratio_max == 0.05

    def test_other_cols_no_threshold(self):
        """非 F22 影响列 null_ratio_max=None (pb/ps/total_mv 等保持零改动)."""
        # pb 4-20 NULL=0.5%, 非 F22 范围
        assert DAILY_BASIC.columns["pb"].null_ratio_max is None
        # total_mv 4-20 NULL=0.0%, 非 F22 范围
        assert DAILY_BASIC.columns["total_mv"].null_ratio_max is None
        assert DAILY_BASIC.columns["turnover_rate"].null_ratio_max is None


# ════════════════════════════════════════════════════════════
# DataPipeline._check_null_ratio 纯函数验证
# ════════════════════════════════════════════════════════════


def _fake_contract(null_ratio_max: float | None) -> TableContract:
    """构造 1 float 列 + null_ratio_max 可配的 Contract."""
    return TableContract(
        table_name="_fake",
        pk_columns=("code",),
        columns={
            "code": ColumnSpec("str", nullable=False),
            "value": ColumnSpec("float", null_ratio_max=null_ratio_max),
        },
        fk_filter_col=None,
        skip_unit_conversion=True,
    )


class TestCheckNullRatio:
    """DataPipeline._check_null_ratio 行为契约."""

    def test_empty_df_returns_empty_warnings(self):
        """空 DataFrame → 空 dict (无除 0 风险)."""
        pipeline = DataPipeline(conn=MagicMock())
        contract = _fake_contract(0.05)
        warnings = pipeline._check_null_ratio(pd.DataFrame(), contract)
        assert warnings == {}

    def test_within_threshold_no_warning(self):
        """NULL 率 = 4% < 阈值 5% → 无 warning."""
        pipeline = DataPipeline(conn=MagicMock())
        contract = _fake_contract(0.05)
        # 100 行, 4 NULL (4%)
        df = pd.DataFrame({
            "code": [f"c{i}" for i in range(100)],
            "value": [1.0] * 96 + [None] * 4,
        })
        warnings = pipeline._check_null_ratio(df, contract)
        assert warnings == {}

    def test_exceeds_threshold_logs_severe_and_warns(self, monkeypatch):
        """NULL 率 = 30% (>2× threshold 5%) → logger.error severity=severe + warning 填充.

        reviewer P2/P3 采纳: structlog 不走 stdlib caplog, 改 monkeypatch 直接拦截
        cg_module.logger.error 捕获调用 (test_config_guard_execution_mode.py 同模式).
        """
        calls: list[tuple[str, dict]] = []
        real_error = pipeline_mod.logger.error

        def capture(msg, *args, **kwargs):
            calls.append((msg, kwargs))
            return real_error(msg, *args, **kwargs)

        monkeypatch.setattr(pipeline_mod.logger, "error", capture)

        pipeline = DataPipeline(conn=MagicMock())
        contract = _fake_contract(0.05)
        # 10 行, 3 NULL (30% > 2×5% → severe)
        df = pd.DataFrame({
            "code": [f"c{i}" for i in range(10)],
            "value": [1.0] * 7 + [None] * 3,
        })
        warnings = pipeline._check_null_ratio(df, contract)
        assert "value" in warnings
        assert warnings["value"] == pytest.approx(0.30, abs=1e-4)
        # 铁律 33 fail-loud 实证: logger.error 实际被调用 (非 no-op)
        assert len(calls) == 1, f"预期 1 次 error 调用, 实际 {len(calls)}"
        msg, kwargs = calls[0]
        assert "null_ratio_exceeded" in msg
        assert kwargs["column"] == "value"
        assert kwargs["severity"] == "severe"

    def test_mild_drift_logs_warning_not_error(self, monkeypatch):
        """NULL 率 = 7% (轻度超 5%, 未到 2×) → logger.warning + severity='drift'.

        reviewer P1 采纳: 避免 5% 略超即同 100% NULL 同等严重 → 分级告警.
        """
        warn_calls: list[tuple[str, dict]] = []
        error_calls: list[tuple[str, dict]] = []
        real_warning = pipeline_mod.logger.warning
        real_error = pipeline_mod.logger.error

        def cap_warn(msg, *args, **kwargs):
            warn_calls.append((msg, kwargs))
            return real_warning(msg, *args, **kwargs)

        def cap_err(msg, *args, **kwargs):
            error_calls.append((msg, kwargs))
            return real_error(msg, *args, **kwargs)

        monkeypatch.setattr(pipeline_mod.logger, "warning", cap_warn)
        monkeypatch.setattr(pipeline_mod.logger, "error", cap_err)

        pipeline = DataPipeline(conn=MagicMock())
        contract = _fake_contract(0.05)
        # 100 行, 7 NULL = 7% (> 5%, < 10% = 2×threshold)
        df = pd.DataFrame({
            "code": [f"c{i}" for i in range(100)],
            "value": [1.0] * 93 + [None] * 7,
        })
        warnings = pipeline._check_null_ratio(df, contract)
        assert warnings["value"] == pytest.approx(0.07, abs=1e-4)
        # drift 级: warning 1 次, error 0 次
        assert len(warn_calls) == 1
        assert len(error_calls) == 0
        assert warn_calls[0][1]["severity"] == "drift"

    def test_no_threshold_never_warns(self):
        """null_ratio_max=None 时, 即使 100% NULL 也不触发 warning."""
        pipeline = DataPipeline(conn=MagicMock())
        contract = _fake_contract(None)
        # 10 行, 全 NULL
        df = pd.DataFrame({
            "code": [f"c{i}" for i in range(10)],
            "value": [None] * 10,
        })
        warnings = pipeline._check_null_ratio(df, contract)
        assert warnings == {}

    def test_missing_col_skipped_gracefully(self):
        """contract 声明的列 df 里不存在 → 跳过, 不 KeyError."""
        pipeline = DataPipeline(conn=MagicMock())
        contract = _fake_contract(0.05)
        # df 仅含 code, 无 value 列
        df = pd.DataFrame({"code": ["c0", "c1", "c2"]})
        warnings = pipeline._check_null_ratio(df, contract)
        assert warnings == {}

    def test_boundary_exact_threshold_not_flagged(self):
        """NULL 率 = 阈值 → 不 flagged (严格 > 才 alarm, 避免 equal 边界噪声)."""
        pipeline = DataPipeline(conn=MagicMock())
        contract = _fake_contract(0.05)
        # 100 行, 5 NULL = 5% 正好等于阈值
        df = pd.DataFrame({
            "code": [f"c{i}" for i in range(100)],
            "value": [1.0] * 95 + [None] * 5,
        })
        warnings = pipeline._check_null_ratio(df, contract)
        assert warnings == {}

    def test_multi_col_contract_multi_warnings(self):
        """多列均超阈值 → 每列独立入 warnings."""
        contract = TableContract(
            table_name="_fake2",
            pk_columns=("code",),
            columns={
                "code": ColumnSpec("str", nullable=False),
                "a": ColumnSpec("float", null_ratio_max=0.05),
                "b": ColumnSpec("float", null_ratio_max=0.10),
            },
            fk_filter_col=None,
            skip_unit_conversion=True,
        )
        pipeline = DataPipeline(conn=MagicMock())
        # a: 30% NULL (>5% flag), b: 15% NULL (>10% flag)
        df = pd.DataFrame({
            "code": [f"c{i}" for i in range(20)],
            "a": [1.0] * 14 + [None] * 6,  # 6/20 = 30%
            "b": [1.0] * 17 + [None] * 3,  # 3/20 = 15%
        })
        warnings = pipeline._check_null_ratio(df, contract)
        assert set(warnings.keys()) == {"a", "b"}
        assert warnings["a"] == pytest.approx(0.30, abs=1e-4)
        assert warnings["b"] == pytest.approx(0.15, abs=1e-4)


# ════════════════════════════════════════════════════════════
# Integration: ingest 端到端补 warnings 字段 (mock _upsert)
# ════════════════════════════════════════════════════════════


class TestIngestIntegration:
    """DataPipeline.ingest 端到端: warnings 正确填 IngestResult."""

    def test_ingest_returns_warnings(self, monkeypatch):
        """daily_basic 30% dv_ttm NULL → IngestResult.null_ratio_warnings 含 dv_ttm."""
        pipeline = DataPipeline(conn=MagicMock())
        # skip fk / upsert (仅验证 warning 链路)
        monkeypatch.setattr(pipeline, "_fk_filter", lambda df, col: df)
        monkeypatch.setattr(pipeline, "_upsert", lambda df, c: len(df))

        # 20 行, 6 NULL dv_ttm = 30%
        df = pd.DataFrame({
            "code": [f"{i:06d}.SZ" for i in range(20)],
            "trade_date": ["2026-04-20"] * 20,
            "dv_ttm": [2.5] * 14 + [None] * 6,
            "pe_ttm": [15.0] * 20,  # 0% NULL
            "pb": [2.0] * 20,
        })
        result = pipeline.ingest(df, DAILY_BASIC)
        assert "dv_ttm" in result.null_ratio_warnings
        assert result.null_ratio_warnings["dv_ttm"] == pytest.approx(0.30, abs=1e-4)
        assert "pe_ttm" not in result.null_ratio_warnings  # pe_ttm 0% NULL 不触发

    def test_ingest_empty_warnings_when_healthy(self, monkeypatch):
        """正常数据 (全列 0% NULL) → null_ratio_warnings 空 dict."""
        pipeline = DataPipeline(conn=MagicMock())
        monkeypatch.setattr(pipeline, "_fk_filter", lambda df, col: df)
        monkeypatch.setattr(pipeline, "_upsert", lambda df, c: len(df))

        df = pd.DataFrame({
            "code": [f"{i:06d}.SZ" for i in range(10)],
            "trade_date": ["2026-04-14"] * 10,
            "dv_ttm": [2.5] * 10,
            "pe_ttm": [15.0] * 10,
            "pb": [2.0] * 10,
        })
        result = pipeline.ingest(df, DAILY_BASIC)
        assert result.null_ratio_warnings == {}
