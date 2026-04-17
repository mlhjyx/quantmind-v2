"""FactorOnboardingService 单元测试 (S2b Rewrite 2026-04-15).

重构后全 sync psycopg2, 不依赖真实 DB.
所有入库走 DataPipeline, IC 走 ic_calculator (铁律 17/19).

覆盖用例:
1. test_onboard_happy_path           — 正常入库完整流程
2. test_onboard_non_approved_raises  — 非 approved 状态抛 ValueError
3. test_onboard_empty_market_data    — 行情数据为空时优雅退出
4. test_onboard_idempotent           — ON CONFLICT 幂等性
5. test_neutralize_with_industry     — 截面 zscore 中性化
6. test_upsert_delegates_to_pipeline — DataPipeline 入库路径验证 (S2b 新增)
"""

from __future__ import annotations

import sys

# FactorDSL 位于 engines.mining.factor_dsl, 测试环境中可能不存在.
# 在 sys.modules 中预注册一个假模块, 避免 _compute_factor_values 内部的
# `from engines.mining.factor_dsl import FactorDSL` 抛 ImportError.
import types as _types
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def _install_fake_factor_dsl() -> None:
    """向 sys.modules 注入轻量级假 FactorDSL, 仅在尚未安装时执行."""
    if "engines" not in sys.modules:
        engines_mod = _types.ModuleType("engines")
        sys.modules["engines"] = engines_mod
    if "engines.mining" not in sys.modules:
        mining_mod = _types.ModuleType("engines.mining")
        sys.modules["engines.mining"] = mining_mod
        sys.modules["engines"].mining = mining_mod  # type: ignore[attr-defined]
    if "engines.mining.factor_dsl" not in sys.modules:
        dsl_mod = _types.ModuleType("engines.mining.factor_dsl")

        class _FakeExprNode:
            def evaluate(self, day_data: pd.DataFrame) -> pd.Series:
                return day_data["close"]  # 默认返回 close

        class _FakeFactorDSL:
            def parse(self, expr: str) -> _FakeExprNode:
                return _FakeExprNode()

        dsl_mod.FactorDSL = _FakeFactorDSL  # type: ignore[attr-defined]
        sys.modules["engines.mining.factor_dsl"] = dsl_mod
        sys.modules["engines.mining"].factor_dsl = dsl_mod  # type: ignore[attr-defined]


_install_fake_factor_dsl()

# 确保 backend/ 和项目根在 sys.path
_BACKEND = Path(__file__).resolve().parent.parent
_PROJECT_ROOT = _BACKEND.parent
_MAIN_REPO_BACKEND = Path("D:/quantmind-v2/backend")
_MAIN_REPO_ROOT = Path("D:/quantmind-v2")
for _p in [str(_MAIN_REPO_BACKEND), str(_MAIN_REPO_ROOT), str(_BACKEND), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_svc():
    """构造 FactorOnboardingService, 跳过 __init__ 中的 DB URL 读取."""
    from app.services.factor_onboarding import FactorOnboardingService

    svc = FactorOnboardingService.__new__(FactorOnboardingService)
    svc._db_url = "postgresql://mock:mock@localhost/mock"
    return svc


# SELECT 列顺序与 factor_onboarding._onboard_inner 中的 approval_queue 查询一致
_AQ_COLUMNS = (
    "id",
    "run_id",
    "factor_name",
    "factor_expr",
    "ast_hash",
    "gate_result",
    "sharpe_1y",
    "sharpe_5y",
    "backtest_report",
    "status",
)


def _make_sync_conn(
    aq_row: dict | None = None,
    registry_id: str = "aaaaaaaa-0000-0000-0000-000000000001",
) -> MagicMock:
    """构造模拟 psycopg2 sync 连接.

    psycopg2 的 cursor 是 context manager:
        with conn.cursor() as cur:
            cur.execute(...)
            row = cur.fetchone()

    fetchone 返回值顺序 (按 _onboard_inner 中调用顺序):
        1. approval_queue SELECT — 返回 aq_row 的 tuple
        2. _upsert_factor_registry INSERT ... RETURNING id — 返回 (registry_id,)

    cursor.description 设置为 _AQ_COLUMNS 以便 _onboard_inner 中
    `colnames = [desc[0] for desc in cur.description]` 正确工作.

    Args:
        aq_row: approval_queue 记录字典 (None → fetchone 返回 None).
        registry_id: registry upsert fetchone 返回的 id.

    Returns:
        MagicMock 模拟的 psycopg2 连接.
    """
    conn = MagicMock()
    conn.closed = False
    conn.autocommit = True

    cursor_mock = MagicMock()

    if aq_row is not None:
        aq_tuple = tuple(aq_row.get(c) for c in _AQ_COLUMNS)
        # fetchone 按调用顺序返回: 第1次 = approval_queue, 第2次 = registry_id
        cursor_mock.fetchone.side_effect = [aq_tuple, (registry_id,)]
    else:
        cursor_mock.fetchone.return_value = None

    # cursor.description 必须与 _AQ_COLUMNS 对齐 (psycopg2 返回 tuple of Column)
    cursor_mock.description = [(c,) for c in _AQ_COLUMNS]

    # cursor 是 context manager: with conn.cursor() as cur:
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor_mock)
    ctx.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = ctx

    # 暴露给测试用例做断言
    conn._test_cursor = cursor_mock
    return conn


def _approved_aq_row(factor_name: str = "test_factor_v1", factor_expr: str = "close") -> dict:
    """构造一条 status='approved' 的 approval_queue 记录."""
    return {
        "id": 1,
        "run_id": "run-001",
        "factor_name": factor_name,
        "factor_expr": factor_expr,
        "ast_hash": "abc123",
        "gate_result": '{"hypothesis": "测试因子假设"}',
        "sharpe_1y": 1.05,
        "sharpe_5y": 0.95,
        "backtest_report": None,
        "status": "approved",
    }


def _make_market_df(n_stocks: int = 50, n_days: int = 10) -> pd.DataFrame:
    """构造最小行情 DataFrame."""
    rng = np.random.default_rng(42)
    records = []
    for d in range(n_days):
        trade_date = date(2024, 1, d + 2) if d + 2 <= 31 else date(2024, 2, d - 28)
        for i in range(n_stocks):
            price = float(rng.uniform(5.0, 50.0))
            records.append(
                {
                    "code": f"{600000 + i:06d}.SH",
                    "trade_date": trade_date,
                    "open": price,
                    "high": price * 1.02,
                    "low": price * 0.98,
                    "close": price,
                    "volume": float(rng.uniform(1e5, 1e7)),
                    "amount": float(rng.uniform(1e6, 1e8)),
                    "adj_factor": 1.0,
                    "is_suspended": False,
                }
            )
    return pd.DataFrame(records)


def _make_fv_df(n_stocks: int = 50, n_days: int = 20) -> pd.DataFrame:
    """预构造因子值 DataFrame, 绕开 FactorDSL 依赖."""
    market_df = _make_market_df(n_stocks=n_stocks, n_days=n_days)
    records = []
    for dt, group in market_df.groupby("trade_date"):
        if len(group) < 30:
            continue
        vals = group["close"].values.astype(float)
        mean_v = vals.mean()
        std_v = vals.std(ddof=1)
        if std_v < 1e-9:
            continue
        for _, row in group.iterrows():
            records.append(
                {
                    "code": row["code"],
                    "trade_date": dt,
                    "raw_value": float(row["close"]),
                    "neutral_value": float((row["close"] - mean_v) / std_v),
                }
            )
    return pd.DataFrame(records)


def _make_mock_ic_df(n_days: int = 30) -> pd.DataFrame:
    """构造一个最小合规的 IC DataFrame (模拟 _compute_ic_multi_horizon 输出)."""
    rng = np.random.default_rng(7)
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]
    ic_20d = rng.normal(0.03, 0.05, n_days)
    return pd.DataFrame(
        {
            "trade_date": dates,
            "ic_1d": rng.normal(0.02, 0.05, n_days),
            "ic_5d": rng.normal(0.025, 0.05, n_days),
            "ic_10d": rng.normal(0.028, 0.05, n_days),
            "ic_20d": ic_20d,
            "ic_abs_1d": np.abs(rng.normal(0.02, 0.05, n_days)),
            "ic_abs_5d": np.abs(rng.normal(0.025, 0.05, n_days)),
            "ic_ma20": ic_20d,  # 简化: ma 等于原值
            "ic_ma60": ic_20d,
            "decay_level": ["slow"] * n_days,
        }
    )


def _patch_all_onboard_deps(svc, market_df=None, fv_df=None, ic_df=None, fv_written=100, ic_written=30):
    """返回一组 patch context managers 覆盖 _onboard_inner 所有外部依赖.

    被 patch 的方法: _upsert_factor_registry (MVP 1.3c: 走 Platform register) /
    _load_market_data / _load_industry_map / _load_csi300 /
    _compute_factor_values / _compute_ic_multi_horizon / _upsert_factor_values /
    _upsert_ic_history

    MVP 1.3c (2026-04-18): 加 _upsert_factor_registry mock — 改造后该方法开新 conn
    走 Platform DBFactorRegistry.register (G9+G10 硬门), 老 test 不测 Platform
    内部逻辑 (内部由 test_factor_registry.py + test_factor_onboarding_gates.py 覆盖).
    这里统一 mock 返回固定 UUID, 专注测 _onboard_inner 编排行为.

    只保留 cursor + fetchone 相关的 DB 调用走真 mock conn (SELECT aq_row /
    UPDATE gate). 注意: INSERT factor_registry 已移到 Platform 路径 (MVP 1.3c),
    不再在 service 层 conn 上执行.
    """
    market_df = market_df if market_df is not None else _make_market_df(n_stocks=50, n_days=30)
    fv_df = fv_df if fv_df is not None else _make_fv_df(n_stocks=50, n_days=30)
    ic_df = ic_df if ic_df is not None else _make_mock_ic_df(n_days=30)

    return [
        patch.object(svc, "_load_market_data", return_value=market_df),
        patch.object(svc, "_load_industry_map", return_value={}),
        patch.object(
            svc,
            "_load_csi300",
            return_value=pd.DataFrame({"trade_date": [date(2024, 1, 1)], "close": [3500.0]}),
        ),
        patch.object(svc, "_compute_factor_values", return_value=fv_df),
        patch.object(svc, "_compute_ic_multi_horizon", return_value=ic_df),
        patch.object(svc, "_upsert_factor_values", return_value=fv_written),
        patch.object(svc, "_upsert_ic_history", return_value=ic_written),
        patch.object(svc, "_upsert_factor_registry", return_value="aaaaaaaa-0000-0000-0000-000000000001"),  # MVP 1.3c
    ]


# ---------------------------------------------------------------------------
# 1. test_onboard_happy_path
# ---------------------------------------------------------------------------


class TestOnboardHappyPath:
    """正常入库流程: approved 记录 + 有效行情数据."""

    def test_happy_path_returns_success(self):
        """factor_registry / factor_values / IC 全链路走通, 返回 success=True."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        with (
            _patch_all_onboard_deps(svc)[0],
            _patch_all_onboard_deps(svc)[1],
            _patch_all_onboard_deps(svc)[2],
            _patch_all_onboard_deps(svc)[3],
            _patch_all_onboard_deps(svc)[4],
            _patch_all_onboard_deps(svc)[5],
            _patch_all_onboard_deps(svc)[6],
            _patch_all_onboard_deps(svc)[7],  # MVP 1.3c _upsert_factor_registry mock
        ):
            result = svc._onboard_inner(conn, approval_queue_id=1)

        assert result["success"] is True
        assert result["factor_name"] == "test_factor_v1"
        assert result["error"] is None
        assert result["factor_values_written"] == 100
        assert result["ic_rows_written"] == 30

    def test_happy_path_factor_registry_fetchone_called_once(self):
        """cursor.fetchone 调用 1 次: SELECT approval_queue. MVP 1.3c: INSERT factor_registry 移到 Platform 新 conn."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        with (
            _patch_all_onboard_deps(svc)[0],
            _patch_all_onboard_deps(svc)[1],
            _patch_all_onboard_deps(svc)[2],
            _patch_all_onboard_deps(svc)[3],
            _patch_all_onboard_deps(svc)[4],
            _patch_all_onboard_deps(svc)[5],
            _patch_all_onboard_deps(svc)[6],
            _patch_all_onboard_deps(svc)[7],  # MVP 1.3c _upsert_factor_registry mock
        ):
            svc._onboard_inner(conn, approval_queue_id=1)

        # MVP 1.3c: INSERT factor_registry 移到 Platform 新 conn, svc 层 fetchone 只 1 次 (SELECT aq_row)
        assert conn._test_cursor.fetchone.call_count == 1

    def test_happy_path_factor_values_written_count(self):
        """_upsert_factor_values 返回值写进 result['factor_values_written']."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        with (
            _patch_all_onboard_deps(svc)[0],
            _patch_all_onboard_deps(svc)[1],
            _patch_all_onboard_deps(svc)[2],
            _patch_all_onboard_deps(svc)[3],
            _patch_all_onboard_deps(svc)[4],
            patch.object(svc, "_upsert_factor_values", return_value=42) as mock_fv,
            _patch_all_onboard_deps(svc)[6],
            _patch_all_onboard_deps(svc)[7],  # MVP 1.3c _upsert_factor_registry mock
        ):
            result = svc._onboard_inner(conn, approval_queue_id=1)

        assert result["factor_values_written"] == 42
        assert mock_fv.call_count == 1

    def test_happy_path_gate_update_execute_called(self):
        """IC 计算后 cursor.execute 至少被调用 3 次 (SELECT + INSERT + UPDATE)."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        with (
            _patch_all_onboard_deps(svc)[0],
            _patch_all_onboard_deps(svc)[1],
            _patch_all_onboard_deps(svc)[2],
            _patch_all_onboard_deps(svc)[3],
            _patch_all_onboard_deps(svc)[4],
            _patch_all_onboard_deps(svc)[5],
            _patch_all_onboard_deps(svc)[6],
            _patch_all_onboard_deps(svc)[7],  # MVP 1.3c _upsert_factor_registry mock
        ):
            svc._onboard_inner(conn, approval_queue_id=1)

        # MVP 1.3c: INSERT factor_registry 已移到 Platform 新 conn, svc 层只 SELECT + UPDATE = 2
        assert conn._test_cursor.execute.call_count >= 2


# ---------------------------------------------------------------------------
# 2. test_onboard_non_approved_raises
# ---------------------------------------------------------------------------


class TestOnboardNonApprovedRaises:
    """非 approved 状态应抛出 ValueError."""

    def test_pending_status_raises_value_error(self):
        """status='pending' 应抛 ValueError."""
        svc = _make_svc()
        pending_row = _approved_aq_row()
        pending_row["status"] = "pending"

        conn = _make_sync_conn(aq_row=pending_row)

        with pytest.raises(ValueError) as exc_info:
            svc._onboard_inner(conn, approval_queue_id=1)

        assert "approved" in str(exc_info.value).lower() or "pending" in str(exc_info.value)

    def test_rejected_status_raises_value_error(self):
        """status='rejected' 应抛 ValueError."""
        svc = _make_svc()
        rejected_row = _approved_aq_row()
        rejected_row["status"] = "rejected"

        conn = _make_sync_conn(aq_row=rejected_row)

        with pytest.raises(ValueError):
            svc._onboard_inner(conn, approval_queue_id=1)

    def test_nonexistent_id_raises_value_error(self):
        """approval_queue_id 不存在 (fetchone 返回 None) 应抛 ValueError."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=None)  # fetchone → None

        with pytest.raises(ValueError) as exc_info:
            svc._onboard_inner(conn, approval_queue_id=9999)

        assert "9999" in str(exc_info.value)

    def test_non_approved_does_not_insert_registry(self):
        """非 approved 状态下 factor_registry 相关的 cursor 调用不触发."""
        svc = _make_svc()
        pending_row = _approved_aq_row()
        pending_row["status"] = "pending"

        conn = _make_sync_conn(aq_row=pending_row)

        with pytest.raises(ValueError):
            svc._onboard_inner(conn, approval_queue_id=1)

        # 只有 1 次 SELECT approval_queue, 没有 INSERT factor_registry
        assert conn._test_cursor.fetchone.call_count == 1


# ---------------------------------------------------------------------------
# 3. test_onboard_empty_market_data
# ---------------------------------------------------------------------------


class TestOnboardEmptyMarketData:
    """行情数据为空时优雅退出, 不 crash."""

    def test_empty_market_data_returns_success_false(self):
        """空行情时返回 success=False, error 非空."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        # MVP 1.3c: 需 mock _upsert_factor_registry (Platform register 走新 conn)
        with (
            patch.object(svc, "_upsert_factor_registry", return_value="aaaaaaaa-0000-0000-0000-000000000001"),
            patch.object(svc, "_load_market_data", return_value=pd.DataFrame()),
        ):
            result = svc._onboard_inner(conn, approval_queue_id=1)

        assert result["success"] is False
        assert result["factor_values_written"] == 0
        assert result["ic_rows_written"] == 0
        assert result["error"] is not None
        assert len(result["error"]) > 0

    def test_empty_market_data_no_pipeline_call(self):
        """空行情时 _upsert_factor_values / _upsert_ic_history 不应被调用."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        with (
            patch.object(svc, "_upsert_factor_registry", return_value="aaaaaaaa-0000-0000-0000-000000000001"),
            patch.object(svc, "_load_market_data", return_value=pd.DataFrame()),
            patch.object(svc, "_upsert_factor_values") as mock_fv,
            patch.object(svc, "_upsert_ic_history") as mock_ic,
        ):
            svc._onboard_inner(conn, approval_queue_id=1)

        mock_fv.assert_not_called()
        mock_ic.assert_not_called()

    def test_empty_market_data_logs_warning(self):
        """空行情时应记录 warning 日志 (铁律 33: 不 silent)."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        with (
            patch.object(svc, "_upsert_factor_registry", return_value="aaaaaaaa-0000-0000-0000-000000000001"),
            patch.object(svc, "_load_market_data", return_value=pd.DataFrame()),
            patch("app.services.factor_onboarding.logger") as mock_logger,
        ):
            svc._onboard_inner(conn, approval_queue_id=1)

        mock_logger.warning.assert_called()

    def test_empty_market_data_registry_id_still_returned(self):
        """空行情时 registry_id 仍然写入 (Step 2 在 Step 3 之前).

        MVP 1.3c: registry_id 现在由 Platform DBFactorRegistry.register 返回
        (走新 conn). 这里 mock _upsert_factor_registry 模拟 Platform 返 UUID.
        """
        svc = _make_svc()
        expected_registry_id = "bbbbbbbb-1111-1111-1111-000000000002"
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        with (
            patch.object(svc, "_upsert_factor_registry", return_value=expected_registry_id),
            patch.object(svc, "_load_market_data", return_value=pd.DataFrame()),
        ):
            result = svc._onboard_inner(conn, approval_queue_id=1)

        assert result["registry_id"] == expected_registry_id


# ---------------------------------------------------------------------------
# 4. test_onboard_idempotent
# ---------------------------------------------------------------------------


class TestOnboardIdempotent:
    """同名因子重复入库时 ON CONFLICT 不报错, 返回成功."""

    def test_duplicate_factor_name_no_error(self):
        """同名因子第二次入库 upsert 不抛异常, 正常返回."""
        svc = _make_svc()

        conn1 = _make_sync_conn(aq_row=_approved_aq_row(factor_name="existing_factor"))
        with (
            _patch_all_onboard_deps(svc)[0],
            _patch_all_onboard_deps(svc)[1],
            _patch_all_onboard_deps(svc)[2],
            _patch_all_onboard_deps(svc)[3],
            _patch_all_onboard_deps(svc)[4],
            _patch_all_onboard_deps(svc)[5],
            _patch_all_onboard_deps(svc)[6],
            _patch_all_onboard_deps(svc)[7],  # MVP 1.3c _upsert_factor_registry mock
        ):
            result1 = svc._onboard_inner(conn1, approval_queue_id=1)

        conn2 = _make_sync_conn(aq_row=_approved_aq_row(factor_name="existing_factor"))
        with (
            _patch_all_onboard_deps(svc)[0],
            _patch_all_onboard_deps(svc)[1],
            _patch_all_onboard_deps(svc)[2],
            _patch_all_onboard_deps(svc)[3],
            _patch_all_onboard_deps(svc)[4],
            _patch_all_onboard_deps(svc)[5],
            _patch_all_onboard_deps(svc)[6],
            _patch_all_onboard_deps(svc)[7],  # MVP 1.3c _upsert_factor_registry mock
        ):
            result2 = svc._onboard_inner(conn2, approval_queue_id=2)

        assert result1["success"] is True
        assert result2["success"] is True
        assert result1["factor_name"] == result2["factor_name"]

    def test_upsert_registry_returns_expected_id(self):
        """factor_registry upsert 返回的 id 写入 result['registry_id']."""
        svc = _make_svc()
        conn = _make_sync_conn(aq_row=_approved_aq_row())

        with (
            _patch_all_onboard_deps(svc)[0],
            _patch_all_onboard_deps(svc)[1],
            _patch_all_onboard_deps(svc)[2],
            _patch_all_onboard_deps(svc)[3],
            _patch_all_onboard_deps(svc)[4],
            _patch_all_onboard_deps(svc)[5],
            _patch_all_onboard_deps(svc)[6],
            _patch_all_onboard_deps(svc)[7],  # MVP 1.3c _upsert_factor_registry mock
        ):
            result = svc._onboard_inner(conn, approval_queue_id=1)

        assert result["registry_id"] == "aaaaaaaa-0000-0000-0000-000000000001"


# ---------------------------------------------------------------------------
# 5. test_upsert_delegates_to_pipeline — S2b 新增 (铁律 17 验证)
# ---------------------------------------------------------------------------


class TestUpsertDelegatesToPipeline:
    """S2b 新增: 验证 _upsert_factor_values / _upsert_ic_history 走 DataPipeline."""

    def test_factor_values_empty_df_returns_zero_no_pipeline(self):
        """空 df 时 _upsert_factor_values 返回 0, 不构造 DataPipeline."""
        svc = _make_svc()
        conn = MagicMock()
        empty_df = pd.DataFrame(columns=["code", "trade_date", "raw_value", "neutral_value"])

        with patch("app.services.factor_onboarding.DataPipeline") as mock_pipeline_cls:
            written = svc._upsert_factor_values(
                conn=conn,
                factor_name="test_factor",
                factor_values_df=empty_df,
            )

        assert written == 0
        mock_pipeline_cls.assert_not_called()

    def test_factor_values_non_empty_calls_pipeline_ingest(self):
        """非空 df 时 _upsert_factor_values 调用 DataPipeline(conn).ingest(df, FACTOR_VALUES)."""
        from app.data_fetcher.contracts import FACTOR_VALUES

        svc = _make_svc()
        conn = MagicMock()
        fv_df = pd.DataFrame(
            {
                "code": ["600000.SH", "000001.SZ"],
                "trade_date": [date(2024, 1, 2), date(2024, 1, 2)],
                "raw_value": [1.0, 2.0],
                "neutral_value": [0.5, -0.5],
            }
        )

        mock_result = MagicMock()
        mock_result.upserted_rows = 2
        mock_result.rejected_rows = 0

        with patch("app.services.factor_onboarding.DataPipeline") as mock_pipeline_cls:
            mock_pipeline_cls.return_value.ingest.return_value = mock_result
            written = svc._upsert_factor_values(
                conn=conn,
                factor_name="test_factor",
                factor_values_df=fv_df,
            )

        assert written == 2
        mock_pipeline_cls.assert_called_once_with(conn)
        # ingest 被调用 1 次, 第 2 个位置参数是 FACTOR_VALUES Contract
        assert mock_pipeline_cls.return_value.ingest.call_count == 1
        args, _ = mock_pipeline_cls.return_value.ingest.call_args
        assert args[1] is FACTOR_VALUES
        # 验证 factor_name 列已注入
        ingest_df = args[0]
        assert "factor_name" in ingest_df.columns
        assert (ingest_df["factor_name"] == "test_factor").all()

    def test_ic_history_empty_df_returns_zero_no_pipeline(self):
        """空 ic_df 时 _upsert_ic_history 返回 0, 不构造 DataPipeline."""
        svc = _make_svc()
        conn = MagicMock()

        with patch("app.services.factor_onboarding.DataPipeline") as mock_pipeline_cls:
            written = svc._upsert_ic_history(conn, "test_factor", pd.DataFrame())

        assert written == 0
        mock_pipeline_cls.assert_not_called()

    def test_ic_history_non_empty_calls_pipeline_ingest(self):
        """非空 ic_df 时 _upsert_ic_history 调用 DataPipeline.ingest(df, FACTOR_IC_HISTORY)."""
        from app.data_fetcher.contracts import FACTOR_IC_HISTORY

        svc = _make_svc()
        conn = MagicMock()
        ic_df = _make_mock_ic_df(n_days=10)

        mock_result = MagicMock()
        mock_result.upserted_rows = 10
        mock_result.rejected_rows = 0

        with patch("app.services.factor_onboarding.DataPipeline") as mock_pipeline_cls:
            mock_pipeline_cls.return_value.ingest.return_value = mock_result
            written = svc._upsert_ic_history(conn, "test_factor", ic_df)

        assert written == 10
        mock_pipeline_cls.assert_called_once_with(conn)
        args, _ = mock_pipeline_cls.return_value.ingest.call_args
        assert args[1] is FACTOR_IC_HISTORY
        ingest_df = args[0]
        assert "factor_name" in ingest_df.columns
        assert (ingest_df["factor_name"] == "test_factor").all()
        assert "decay_level" in ingest_df.columns


# ---------------------------------------------------------------------------
# 6. test_neutralize_with_industry
# ---------------------------------------------------------------------------


class TestNeutralizeWithIndustry:
    """截面 zscore 中性化验证: 3个行业各10只股票, 中性化后行业均值接近0."""

    def _make_industry_market_data(self) -> pd.DataFrame:
        """构造有明显行业差异的行情数据."""
        rng = np.random.default_rng(42)
        records = []
        trade_date = date(2024, 6, 3)

        # 行业A: 10只股票, close ~ 50
        for i in range(10):
            records.append(
                {
                    "code": f"60{i:04d}.SH",
                    "trade_date": trade_date,
                    "open": float(rng.normal(50.0, 1.0)),
                    "high": float(rng.normal(51.0, 1.0)),
                    "low": float(rng.normal(49.0, 1.0)),
                    "close": float(rng.normal(50.0, 1.0)),
                    "volume": 1e6,
                    "amount": 5e7,
                    "adj_factor": 1.0,
                    "is_suspended": False,
                    "industry": "A",
                }
            )
        # 行业B: 10只股票, close ~ 20
        for i in range(10):
            records.append(
                {
                    "code": f"00{i:04d}.SZ",
                    "trade_date": trade_date,
                    "open": float(rng.normal(20.0, 1.0)),
                    "high": float(rng.normal(21.0, 1.0)),
                    "low": float(rng.normal(19.0, 1.0)),
                    "close": float(rng.normal(20.0, 1.0)),
                    "volume": 1e6,
                    "amount": 2e7,
                    "adj_factor": 1.0,
                    "is_suspended": False,
                    "industry": "B",
                }
            )
        # 行业C: 10只股票, close ~ 5
        for i in range(10):
            records.append(
                {
                    "code": f"30{i:04d}.SZ",
                    "trade_date": trade_date,
                    "open": float(rng.normal(5.0, 0.5)),
                    "high": float(rng.normal(5.2, 0.5)),
                    "low": float(rng.normal(4.8, 0.5)),
                    "close": float(rng.normal(5.0, 0.5)),
                    "volume": 1e6,
                    "amount": 5e6,
                    "adj_factor": 1.0,
                    "is_suspended": False,
                    "industry": "C",
                }
            )
        return pd.DataFrame(records)

    def test_zscore_neutralization_industry_mean_near_zero(self):
        """截面 zscore 后, 原始行业差异应被压缩: 各行业 neutral_value 均值接近 0."""
        svc = _make_svc()
        df = self._make_industry_market_data()

        result_df = svc._compute_factor_values(
            factor_expr="close",
            market_data=df,
        )

        assert not result_df.empty, "因子值不应为空"
        assert "neutral_value" in result_df.columns

        industry_map = {row["code"]: row["industry"] for _, row in df.iterrows()}
        result_df["industry"] = result_df["code"].map(industry_map)

        raw_industry_means = result_df.groupby("industry")["raw_value"].mean()
        raw_spread = raw_industry_means.max() - raw_industry_means.min()
        assert raw_spread > 10.0, (
            f"原始值行业间差距 {raw_spread:.2f} 应 > 10 (行业A~50 vs 行业C~5)"
        )

        neutral_industry_means = result_df.groupby("industry")["neutral_value"].mean()
        for industry, mean_val in neutral_industry_means.items():
            assert abs(mean_val) < 1.5, (
                f"行业 {industry} 中性化后均值 {mean_val:.4f} 仍过大"
            )

    def test_zscore_neutralization_cross_section_std_near_one(self):
        """截面 zscore 后, neutral_value 标准差应接近 1.0."""
        svc = _make_svc()
        df = self._make_industry_market_data()

        result_df = svc._compute_factor_values(
            factor_expr="close",
            market_data=df,
        )

        assert not result_df.empty

        for dt, group in result_df.groupby("trade_date"):
            std_val = group["neutral_value"].std(ddof=1)
            assert 0.5 < std_val < 1.5, (
                f"date={dt} 截面 neutral_value std={std_val:.4f}, 偏离 1.0 过多"
            )

    def test_zscore_neutralization_mean_near_zero(self):
        """截面 zscore 后, 各日的全截面均值应接近 0."""
        svc = _make_svc()
        df = self._make_industry_market_data()

        result_df = svc._compute_factor_values(
            factor_expr="close",
            market_data=df,
        )

        assert not result_df.empty

        for dt, group in result_df.groupby("trade_date"):
            mean_val = group["neutral_value"].mean()
            assert abs(mean_val) < 1e-6, (
                f"date={dt} 截面 neutral_value mean={mean_val:.2e}, 应为 0"
            )


# ---------------------------------------------------------------------------
# 7. 边界条件补充测试
# ---------------------------------------------------------------------------


class TestBoundaryConditions:
    """边界条件: 低于 MIN_STOCKS 阈值、IC 数据不足、_compute_decay_level 等."""

    def test_compute_factor_values_below_min_stocks_skips_date(self):
        """股票数量低于 MIN_STOCKS=30 的交易日应被跳过."""
        svc = _make_svc()

        df = _make_market_df(n_stocks=10, n_days=5)

        result_df = svc._compute_factor_values(
            factor_expr="close",
            market_data=df,
        )

        assert result_df.empty

    def test_compute_gate_stats_empty_ic_df_returns_none(self):
        """空 IC DataFrame 时 _compute_gate_stats 应返回 (None, None, None)."""
        svc = _make_svc()
        gate_ic, gate_ir, gate_t = svc._compute_gate_stats(pd.DataFrame())
        assert gate_ic is None
        assert gate_ir is None
        assert gate_t is None

    def test_compute_gate_stats_single_row_returns_none(self):
        """IC 数据只有 1 行时应返回 (None, None, None)."""
        svc = _make_svc()
        ic_df = pd.DataFrame({"ic_20d": [0.05]})
        gate_ic, gate_ir, gate_t = svc._compute_gate_stats(ic_df)
        assert gate_ic is None
        assert gate_ir is None
        assert gate_t is None

    def test_compute_gate_stats_normal_data(self):
        """正常 IC 数据时 gate_ic/gate_ir/gate_t 应为有效浮点数."""
        svc = _make_svc()
        rng = np.random.default_rng(7)
        ic_vals = rng.normal(0.03, 0.05, 100)
        ic_df = pd.DataFrame({"ic_20d": ic_vals})

        gate_ic, gate_ir, gate_t = svc._compute_gate_stats(ic_df)

        assert gate_ic is not None
        assert gate_ir is not None
        assert gate_t is not None
        assert isinstance(gate_ic, float)
        assert isinstance(gate_ir, float)
        assert isinstance(gate_t, float)
        assert gate_t > 2.0, f"期望 t>2.0, 实际 t={gate_t:.4f}"

    def test_compute_decay_level_fast_decay(self):
        """IC 1d >> IC 20d 时衰减标签应为 'fast'."""
        from app.services.factor_onboarding import _compute_decay_level

        ic_df = pd.DataFrame(
            {
                "ic_1d": [0.10] * 50,
                "ic_5d": [0.03] * 50,
                "ic_10d": [0.02] * 50,
                "ic_20d": [0.01] * 50,
            }
        )
        assert _compute_decay_level(ic_df) == "fast"

    def test_compute_decay_level_stable(self):
        """IC 各期差异小时衰减标签应为 'stable'."""
        from app.services.factor_onboarding import _compute_decay_level

        ic_df = pd.DataFrame(
            {
                "ic_1d": [0.05] * 50,
                "ic_5d": [0.05] * 50,
                "ic_10d": [0.05] * 50,
                "ic_20d": [0.048] * 50,
            }
        )
        assert _compute_decay_level(ic_df) == "stable"

    def test_factor_values_dsl_exception_skips_date(self):
        """FactorDSL evaluate() 抛异常时该日应被跳过, 不 crash (铁律 33)."""
        svc = _make_svc()
        df = _make_market_df(n_stocks=50, n_days=5)

        import types as _t

        failing_mod = _t.ModuleType("engines.mining.factor_dsl")

        class _FailingExprNode:
            def evaluate(self, day_data: pd.DataFrame) -> None:
                raise RuntimeError("DSL 计算失败")

        class _FailingFactorDSL:
            def parse(self, expr: str) -> _FailingExprNode:
                return _FailingExprNode()

        failing_mod.FactorDSL = _FailingFactorDSL  # type: ignore[attr-defined]

        original_mod = sys.modules.get("engines.mining.factor_dsl")
        sys.modules["engines.mining.factor_dsl"] = failing_mod
        try:
            result_df = svc._compute_factor_values(
                factor_expr="broken_expr",
                market_data=df,
            )
        finally:
            if original_mod is not None:
                sys.modules["engines.mining.factor_dsl"] = original_mod

        assert result_df.empty
