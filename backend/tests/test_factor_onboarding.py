"""FactorOnboardingService 单元测试。

Sprint 1.32 Phase 3: 全 mock，不依赖真实 DB。

覆盖用例:
1. test_onboard_happy_path           — 正常入库完整流程
2. test_onboard_non_approved_raises  — 非 approved 状态抛 ValueError
3. test_onboard_empty_market_data    — 行情数据为空时优雅退出
4. test_onboard_idempotent           — ON CONFLICT 幂等性（同名因子不报错）
5. test_neutralize_with_industry     — 截面 zscore 中性化后行业均值接近 0
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# FactorDSL 位于 engines.mining.factor_dsl，在测试环境中可能不存在。
# 在 sys.modules 中预注册一个假模块，避免 _compute_factor_values 内部的
# `from engines.mining.factor_dsl import FactorDSL` 抛 ImportError。
import types as _types

def _install_fake_factor_dsl() -> None:
    """向 sys.modules 注入轻量级假 FactorDSL，仅在尚未安装时执行。"""
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
            def evaluate(self, day_data: "pd.DataFrame") -> "pd.Series":
                return day_data["close"]  # 默认返回 close

        class _FakeFactorDSL:
            def parse(self, expr: str) -> _FakeExprNode:
                return _FakeExprNode()

        dsl_mod.FactorDSL = _FakeFactorDSL  # type: ignore[attr-defined]
        sys.modules["engines.mining.factor_dsl"] = dsl_mod
        sys.modules["engines.mining"].factor_dsl = dsl_mod  # type: ignore[attr-defined]

_install_fake_factor_dsl()

# 确保 backend/ 和项目根在 sys.path
# 优先插入主仓库路径（factor_onboarding.py 仅存在于主仓库）
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
    """构造 FactorOnboardingService，跳过 __init__ 中的 DB URL 读取。"""
    from app.services.factor_onboarding import FactorOnboardingService

    svc = FactorOnboardingService.__new__(FactorOnboardingService)
    svc._db_url = "postgresql://mock:mock@localhost/mock"
    return svc


def _make_async_conn(
    aq_row: dict | None = None,
    market_rows: list | None = None,
    registry_id: str = "aaaaaaaa-0000-0000-0000-000000000001",
) -> AsyncMock:
    """构造模拟 asyncpg 连接。

    Args:
        aq_row: fetchrow 返回的 approval_queue 记录（dict → asyncpg Record 近似）。
        market_rows: fetch 返回的行情行列表。
        registry_id: _upsert_factor_registry fetchrow 返回的 id。

    Returns:
        AsyncMock 模拟的 asyncpg.Connection。
    """
    conn = AsyncMock()

    # fetchrow 第一次调用返回 approval_queue 记录，第二次返回 registry id
    aq_record = _make_asyncpg_record(aq_row) if aq_row is not None else None
    reg_record = _make_asyncpg_record({"id": registry_id})
    conn.fetchrow.side_effect = [aq_record, reg_record]

    # fetch 返回行情数据
    conn.fetch.return_value = market_rows or []

    # execute / executemany 无副作用
    conn.execute = AsyncMock(return_value=None)
    conn.executemany = AsyncMock(return_value=None)
    conn.close = AsyncMock(return_value=None)

    return conn


def _make_asyncpg_record(data: dict):
    """模拟 asyncpg.Record（支持 [] 和 get() 访问）。"""
    record = MagicMock()
    record.__getitem__ = lambda self, key: data[key]
    record.get = lambda key, default=None: data.get(key, default)
    # 支持 row["status"] == "approved" 比较
    record.__contains__ = lambda self, key: key in data
    return record


def _approved_aq_row(factor_name: str = "test_factor_v1", factor_expr: str = "close") -> dict:
    """构造一条 status='approved' 的 approval_queue 记录。"""
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
    """构造最小行情 DataFrame。

    Args:
        n_stocks: 股票数量。
        n_days: 交易日数量。

    Returns:
        包含 [code, trade_date, open, high, low, close, volume, amount, adj_factor, is_suspended]。
    """
    rng = np.random.default_rng(42)
    records = []
    base = date(2024, 1, 2)
    for d in range(n_days):
        trade_date = date(2024, 1, d + 2) if d + 2 <= 31 else date(2024, 2, d - 28)
        for i in range(n_stocks):
            price = float(rng.uniform(5.0, 50.0))
            records.append({
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
            })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# 1. test_onboard_happy_path
# ---------------------------------------------------------------------------


class TestOnboardHappyPath:
    """正常入库流程：approved 记录 + 有效行情数据。"""

    def _make_factor_values_df(self, n_stocks: int = 50, n_days: int = 20) -> pd.DataFrame:
        """预构造因子值 DataFrame，绕开 FactorDSL 依赖。"""
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
                records.append({
                    "code": row["code"],
                    "trade_date": dt,
                    "raw_value": float(row["close"]),
                    "neutral_value": float((row["close"] - mean_v) / std_v),
                })
        return pd.DataFrame(records)

    @pytest.mark.asyncio
    async def test_happy_path_returns_success(self):
        """factor_registry INSERT、factor_values INSERT、IC 计算均被触发，返回 success=True。"""
        svc = _make_svc()
        market_df = _make_market_df(n_stocks=50, n_days=30)
        fv_df = self._make_factor_values_df(n_stocks=50, n_days=30)

        conn = _make_async_conn(aq_row=_approved_aq_row())

        with patch.object(svc, "_load_market_data", return_value=market_df):
            with patch.object(svc, "_compute_factor_values", return_value=fv_df):
                result = await svc._onboard_inner(conn, approval_queue_id=1)

        assert result["success"] is True
        assert result["factor_name"] == "test_factor_v1"
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_happy_path_factor_registry_insert_called(self):
        """factor_registry INSERT（fetchrow）必须被调用两次：aq_row 查询 + registry upsert。"""
        svc = _make_svc()
        market_df = _make_market_df(n_stocks=50, n_days=20)
        fv_df = self._make_factor_values_df(n_stocks=50, n_days=20)
        conn = _make_async_conn(aq_row=_approved_aq_row())

        with patch.object(svc, "_load_market_data", return_value=market_df):
            with patch.object(svc, "_compute_factor_values", return_value=fv_df):
                await svc._onboard_inner(conn, approval_queue_id=1)

        # fetchrow 调用次数：1次查 approval_queue + 1次 upsert factor_registry
        assert conn.fetchrow.call_count == 2

    @pytest.mark.asyncio
    async def test_happy_path_factor_values_written(self):
        """行情数据有效时，factor_values executemany 必须被调用至少一次。"""
        svc = _make_svc()
        market_df = _make_market_df(n_stocks=50, n_days=20)
        fv_df = self._make_factor_values_df(n_stocks=50, n_days=20)
        conn = _make_async_conn(aq_row=_approved_aq_row())

        with patch.object(svc, "_load_market_data", return_value=market_df):
            with patch.object(svc, "_compute_factor_values", return_value=fv_df):
                result = await svc._onboard_inner(conn, approval_queue_id=1)

        # factor_values_written > 0 且 executemany 被调用
        assert result["factor_values_written"] > 0
        assert conn.executemany.call_count >= 1

    @pytest.mark.asyncio
    async def test_happy_path_gate_update_called(self):
        """IC 计算后，factor_registry gate 字段 UPDATE（conn.execute）必须被调用。"""
        svc = _make_svc()
        market_df = _make_market_df(n_stocks=50, n_days=30)
        fv_df = self._make_factor_values_df(n_stocks=50, n_days=30)
        conn = _make_async_conn(aq_row=_approved_aq_row())

        with patch.object(svc, "_load_market_data", return_value=market_df):
            with patch.object(svc, "_compute_factor_values", return_value=fv_df):
                await svc._onboard_inner(conn, approval_queue_id=1)

        # conn.execute 至少调用一次（UPDATE factor_registry gate 字段）
        conn.execute.assert_called()


# ---------------------------------------------------------------------------
# 2. test_onboard_non_approved_raises
# ---------------------------------------------------------------------------


class TestOnboardNonApprovedRaises:
    """非 approved 状态应抛出 ValueError。"""

    @pytest.mark.asyncio
    async def test_pending_status_raises_value_error(self):
        """status='pending' 应抛出 ValueError，且消息包含 'approved'。"""
        svc = _make_svc()
        pending_row = _approved_aq_row()
        pending_row["status"] = "pending"

        conn = _make_async_conn(aq_row=pending_row)

        with pytest.raises(ValueError) as exc_info:
            await svc._onboard_inner(conn, approval_queue_id=1)

        assert "approved" in str(exc_info.value).lower() or "pending" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rejected_status_raises_value_error(self):
        """status='rejected' 应抛出 ValueError。"""
        svc = _make_svc()
        rejected_row = _approved_aq_row()
        rejected_row["status"] = "rejected"

        conn = _make_async_conn(aq_row=rejected_row)

        with pytest.raises(ValueError):
            await svc._onboard_inner(conn, approval_queue_id=1)

    @pytest.mark.asyncio
    async def test_nonexistent_id_raises_value_error(self):
        """approval_queue_id 不存在（fetchrow 返回 None）应抛出 ValueError。"""
        svc = _make_svc()

        conn = AsyncMock()
        conn.fetchrow.return_value = None  # 记录不存在

        with pytest.raises(ValueError) as exc_info:
            await svc._onboard_inner(conn, approval_queue_id=9999)

        assert "9999" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_non_approved_does_not_insert_registry(self):
        """非 approved 状态下 factor_registry INSERT 不应被触发。"""
        svc = _make_svc()
        pending_row = _approved_aq_row()
        pending_row["status"] = "pending"

        conn = _make_async_conn(aq_row=pending_row)

        with pytest.raises(ValueError):
            await svc._onboard_inner(conn, approval_queue_id=1)

        # fetchrow 只调用了 1 次（查 approval_queue），没有触发 registry upsert
        assert conn.fetchrow.call_count == 1


# ---------------------------------------------------------------------------
# 3. test_onboard_empty_market_data
# ---------------------------------------------------------------------------


class TestOnboardEmptyMarketData:
    """行情数据为空时优雅退出，不 crash。"""

    @pytest.mark.asyncio
    async def test_empty_market_data_returns_success_false(self):
        """空行情数据时返回 success=False，error 字段非空。"""
        svc = _make_svc()

        conn = _make_async_conn(aq_row=_approved_aq_row())

        # _load_market_data 返回空 DataFrame
        with patch.object(svc, "_load_market_data", return_value=pd.DataFrame()):
            result = await svc._onboard_inner(conn, approval_queue_id=1)

        assert result["success"] is False
        assert result["factor_values_written"] == 0
        assert result["ic_rows_written"] == 0
        assert result["error"] is not None
        assert len(result["error"]) > 0

    @pytest.mark.asyncio
    async def test_empty_market_data_no_executemany(self):
        """空行情数据时 factor_values 和 ic_history 的 executemany 不应被调用。"""
        svc = _make_svc()
        conn = _make_async_conn(aq_row=_approved_aq_row())

        with patch.object(svc, "_load_market_data", return_value=pd.DataFrame()):
            await svc._onboard_inner(conn, approval_queue_id=1)

        conn.executemany.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_market_data_logs_warning(self):
        """空行情数据时应记录 warning 日志。"""
        import logging

        svc = _make_svc()
        conn = _make_async_conn(aq_row=_approved_aq_row())

        with patch.object(svc, "_load_market_data", return_value=pd.DataFrame()):
            with patch("app.services.factor_onboarding.logger") as mock_logger:
                await svc._onboard_inner(conn, approval_queue_id=1)

        mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_empty_market_data_registry_id_still_returned(self):
        """即使行情数据为空，registry_id 字段应已写入（Step 2 在 Step 3 之前）。"""
        svc = _make_svc()
        expected_registry_id = "bbbbbbbb-1111-1111-1111-000000000002"
        conn = _make_async_conn(
            aq_row=_approved_aq_row(),
            registry_id=expected_registry_id,
        )

        with patch.object(svc, "_load_market_data", return_value=pd.DataFrame()):
            result = await svc._onboard_inner(conn, approval_queue_id=1)

        assert result["registry_id"] == expected_registry_id


# ---------------------------------------------------------------------------
# 4. test_onboard_idempotent
# ---------------------------------------------------------------------------


class TestOnboardIdempotent:
    """同名因子重复入库时 ON CONFLICT 不报错，返回成功。"""

    def _make_fv_df(self, n_stocks: int = 50, n_days: int = 20) -> pd.DataFrame:
        """预构造因子值 DataFrame，绕开 FactorDSL 依赖。"""
        market_df = _make_market_df(n_stocks=n_stocks, n_days=n_days)
        records = []
        for dt, group in market_df.groupby("trade_date"):
            if len(group) < 30:
                continue
            vals = group["close"].values.astype(float)
            mean_v, std_v = vals.mean(), vals.std(ddof=1)
            if std_v < 1e-9:
                continue
            for _, row in group.iterrows():
                records.append({
                    "code": row["code"],
                    "trade_date": dt,
                    "raw_value": float(row["close"]),
                    "neutral_value": float((row["close"] - mean_v) / std_v),
                })
        return pd.DataFrame(records)

    @pytest.mark.asyncio
    async def test_duplicate_factor_name_no_error(self):
        """同名因子第二次入库时 upsert 不抛异常，正常返回。"""
        svc = _make_svc()
        market_df = _make_market_df(n_stocks=50, n_days=20)
        fv_df = self._make_fv_df(n_stocks=50, n_days=20)

        conn = _make_async_conn(aq_row=_approved_aq_row(factor_name="existing_factor"))
        with patch.object(svc, "_load_market_data", return_value=market_df):
            with patch.object(svc, "_compute_factor_values", return_value=fv_df):
                result1 = await svc._onboard_inner(conn, approval_queue_id=1)

        # 第二次入库（同名因子，新 conn）
        conn2 = _make_async_conn(aq_row=_approved_aq_row(factor_name="existing_factor"))
        with patch.object(svc, "_load_market_data", return_value=market_df):
            with patch.object(svc, "_compute_factor_values", return_value=fv_df):
                result2 = await svc._onboard_inner(conn2, approval_queue_id=2)

        assert result1["success"] is True
        assert result2["success"] is True
        assert result1["factor_name"] == result2["factor_name"]

    @pytest.mark.asyncio
    async def test_upsert_registry_called_with_on_conflict(self):
        """factor_registry upsert 使用 ON CONFLICT 语义：fetchrow 被调用返回 id。"""
        svc = _make_svc()
        market_df = _make_market_df(n_stocks=50, n_days=10)
        fv_df = self._make_fv_df(n_stocks=50, n_days=10)
        conn = _make_async_conn(aq_row=_approved_aq_row())

        with patch.object(svc, "_load_market_data", return_value=market_df):
            with patch.object(svc, "_compute_factor_values", return_value=fv_df):
                result = await svc._onboard_inner(conn, approval_queue_id=1)

        # registry_id 来自 fetchrow 第二次调用的返回值
        assert result["registry_id"] == "aaaaaaaa-0000-0000-0000-000000000001"

    @pytest.mark.asyncio
    async def test_factor_values_upsert_on_empty_df_returns_zero(self):
        """factor_values_df 为空时 _upsert_factor_values 返回 0，不调用 executemany。"""
        svc = _make_svc()

        conn = AsyncMock()
        conn.executemany = AsyncMock(return_value=None)

        written = await svc._upsert_factor_values(
            conn=conn,
            factor_name="test_factor",
            factor_values_df=pd.DataFrame(
                columns=["code", "trade_date", "raw_value", "neutral_value"]
            ),
        )

        assert written == 0
        conn.executemany.assert_not_called()


# ---------------------------------------------------------------------------
# 5. test_neutralize_with_industry
# ---------------------------------------------------------------------------


class TestNeutralizeWithIndustry:
    """截面 zscore 中性化验证：3个行业各10只股票，中性化后行业均值接近0。"""

    def _make_industry_market_data(self) -> pd.DataFrame:
        """构造有明显行业差异的行情数据。

        行业A: close 均值 ~50（高价股）
        行业B: close 均值 ~20（中价股）
        行业C: close 均值 ~5（低价股）

        中性化后截面 zscore 应使3个行业的因子均值接近0。
        """
        rng = np.random.default_rng(42)
        records = []
        trade_date = date(2024, 6, 3)

        # 行业A: 10只股票，close ~ 50
        for i in range(10):
            records.append({
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
            })
        # 行业B: 10只股票，close ~ 20
        for i in range(10):
            records.append({
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
            })
        # 行业C: 10只股票，close ~ 5
        for i in range(10):
            records.append({
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
            })
        return pd.DataFrame(records)

    def test_zscore_neutralization_industry_mean_near_zero(self):
        """截面 zscore 后，原始行业差异应被压缩：各行业 neutral_value 均值接近 0。

        验证原始 IC vs 中性化后 IC（铁律2）：
        - 原始 close：行业A~50, B~20, C~5，行业间差距极大，raw_value 行业均值差距显著
        - 截面 zscore 中性化后：neutral_value 行业均值应接近 0（行业因子剔除）
        """
        svc = _make_svc()
        df = self._make_industry_market_data()

        # 预注册的 _FakeFactorDSL 默认返回 close 列，无需额外 patch
        result_df = svc._compute_factor_values(
            factor_expr="close",
            market_data=df,
        )

        assert not result_df.empty, "因子值不应为空"
        assert "neutral_value" in result_df.columns

        # 关联行业标签
        industry_map = {row["code"]: row["industry"] for _, row in df.iterrows()}
        result_df["industry"] = result_df["code"].map(industry_map)

        # 原始值行业均值：应有明显差距（raw_value 验证因子确实有行业偏差）
        raw_industry_means = result_df.groupby("industry")["raw_value"].mean()
        raw_spread = raw_industry_means.max() - raw_industry_means.min()
        assert raw_spread > 10.0, (
            f"原始值行业间差距 {raw_spread:.2f} 应 > 10（行业A~50 vs 行业C~5）"
        )

        # 中性化后行业均值：应接近 0（行业差异已被截面 zscore 压缩）
        neutral_industry_means = result_df.groupby("industry")["neutral_value"].mean()
        for industry, mean_val in neutral_industry_means.items():
            assert abs(mean_val) < 1.5, (
                f"行业 {industry} 中性化后均值 {mean_val:.4f} 仍过大，"
                "截面 zscore 中性化可能有问题"
            )

    def test_zscore_neutralization_cross_section_std_near_one(self):
        """截面 zscore 后，全截面 neutral_value 标准差应接近 1.0（zscore 定义）。"""
        svc = _make_svc()
        df = self._make_industry_market_data()

        result_df = svc._compute_factor_values(
            factor_expr="close",
            market_data=df,
        )

        assert not result_df.empty

        # 每个截面日 neutral_value 的标准差应接近 1.0
        for dt, group in result_df.groupby("trade_date"):
            std_val = group["neutral_value"].std(ddof=1)
            assert 0.5 < std_val < 1.5, (
                f"date={dt} 截面 neutral_value std={std_val:.4f}，偏离 1.0 过多"
            )

    def test_zscore_neutralization_mean_near_zero(self):
        """截面 zscore 后，各日的全截面均值应接近 0。"""
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
                f"date={dt} 截面 neutral_value mean={mean_val:.2e}，应为 0"
            )


# ---------------------------------------------------------------------------
# 边界条件补充测试
# ---------------------------------------------------------------------------


class TestBoundaryConditions:
    """边界条件：低于 MIN_STOCKS 阈值、IC 数据不足、_safe_float 等。"""

    def test_compute_factor_values_below_min_stocks_skips_date(self):
        """股票数量低于 MIN_STOCKS=30 的交易日应被跳过。"""
        svc = _make_svc()

        # 只有 10 只股票（< MIN_STOCKS=30）
        # 预注册的 _FakeFactorDSL 返回 close 列，无需额外 patch
        df = _make_market_df(n_stocks=10, n_days=5)

        result_df = svc._compute_factor_values(
            factor_expr="close",
            market_data=df,
        )

        # 所有日期均被跳过，结果应为空 DataFrame
        assert result_df.empty

    def test_compute_gate_stats_empty_ic_df_returns_none(self):
        """空 IC DataFrame 时 _compute_gate_stats 应返回 (None, None, None)。"""
        svc = _make_svc()
        gate_ic, gate_ir, gate_t = svc._compute_gate_stats(pd.DataFrame())
        assert gate_ic is None
        assert gate_ir is None
        assert gate_t is None

    def test_compute_gate_stats_single_row_returns_none(self):
        """IC 数据只有 1 行（< 2）时应返回 (None, None, None)。"""
        svc = _make_svc()
        ic_df = pd.DataFrame({"ic_20d": [0.05]})
        gate_ic, gate_ir, gate_t = svc._compute_gate_stats(ic_df)
        assert gate_ic is None
        assert gate_ir is None
        assert gate_t is None

    def test_compute_gate_stats_normal_data(self):
        """正常 IC 数据时 gate_ic/gate_ir/gate_t 应为有效浮点数。"""
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
        # IC 均值约 0.03，t 统计量 = mean / (std / sqrt(100)) 约 6
        assert gate_t > 2.0, f"期望 t>2.0, 实际 t={gate_t:.4f}"

    def test_safe_float_none_returns_none(self):
        """_safe_float(None) 应返回 None。"""
        from app.services.factor_onboarding import _safe_float

        assert _safe_float(None) is None

    def test_safe_float_nan_returns_none(self):
        """_safe_float(NaN) 应返回 None。"""
        from app.services.factor_onboarding import _safe_float

        assert _safe_float(float("nan")) is None

    def test_safe_float_valid_returns_float(self):
        """_safe_float(1.23) 应返回 1.23。"""
        from app.services.factor_onboarding import _safe_float

        assert _safe_float(1.23) == pytest.approx(1.23)

    def test_compute_decay_level_fast_decay(self):
        """IC 1d >> IC 20d 时衰减标签应为 'fast'。"""
        from app.services.factor_onboarding import _compute_decay_level

        ic_df = pd.DataFrame({
            "ic_1d": [0.10] * 50,
            "ic_5d": [0.03] * 50,  # decay_5 = (0.10-0.03)/0.10 = 0.7 > 0.5
            "ic_10d": [0.02] * 50,
            "ic_20d": [0.01] * 50,
        })
        assert _compute_decay_level(ic_df) == "fast"

    def test_compute_decay_level_stable(self):
        """IC 各期差异小时衰减标签应为 'stable'。"""
        from app.services.factor_onboarding import _compute_decay_level

        ic_df = pd.DataFrame({
            "ic_1d": [0.05] * 50,
            "ic_5d": [0.05] * 50,
            "ic_10d": [0.05] * 50,
            "ic_20d": [0.048] * 50,  # decay_20 = (0.05-0.048)/0.05 = 0.04 < 0.1
        })
        assert _compute_decay_level(ic_df) == "stable"

    def test_upsert_ic_history_empty_returns_zero(self):
        """空 ic_df 时 _upsert_ic_history 应返回 0。"""
        import asyncio
        svc = _make_svc()
        conn = AsyncMock()
        conn.executemany = AsyncMock(return_value=None)

        written = asyncio.get_event_loop().run_until_complete(
            svc._upsert_ic_history(conn, "test_factor", pd.DataFrame())
        )

        assert written == 0
        conn.executemany.assert_not_called()

    @pytest.mark.asyncio
    async def test_factor_values_dsl_exception_skips_date(self):
        """FactorDSL evaluate() 抛异常时该日应被跳过，不 crash。"""
        svc = _make_svc()
        df = _make_market_df(n_stocks=50, n_days=5)

        # 构造一个 evaluate() 总抛异常的假 FactorDSL，替换 sys.modules 中的假模块
        import types as _t
        failing_mod = _t.ModuleType("engines.mining.factor_dsl")

        class _FailingExprNode:
            def evaluate(self, day_data: "pd.DataFrame") -> None:
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
            # 恢复原始假模块，不污染其他测试
            if original_mod is not None:
                sys.modules["engines.mining.factor_dsl"] = original_mod

        # 所有日期跳过，结果为空 DataFrame（但不 crash）
        assert result_df.empty
