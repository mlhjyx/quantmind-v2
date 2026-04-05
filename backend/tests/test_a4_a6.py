"""A4 数据单位审计 + A6 API 500修复 测试。

A4: 验证单位注释准确性（通过因子计算结果间接验证）
A6: 验证6个端点不返回500
"""

import math
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest


# =====================================================================
# A4: 单位一致性验证
# =====================================================================


class TestA4UnitConsistency:
    """验证各因子函数中金额单位使用的正确性。"""

    def test_amihud_ranking_invariant_to_amount_scale(self):
        """Amihud排名不受amount缩放影响（千元 vs 元 vs 万元）。"""
        from engines.factor_engine import calc_amihud

        close = pd.Series([10.0, 10.1, 10.3, 9.8, 10.5, 10.2, 10.7, 10.4, 10.6, 10.8,
                           11.0, 10.9, 11.2, 11.1, 11.3, 11.5, 11.4, 11.6, 11.8, 11.7])
        volume = pd.Series([1000] * 20)
        amount_qian = pd.Series([100.0] * 20)  # 千元
        amount_yuan = amount_qian * 1000        # 元
        amount_wan = amount_qian / 10           # 万元

        amihud_qian = calc_amihud(close, volume, amount_qian, 10)
        amihud_yuan = calc_amihud(close, volume, amount_yuan, 10)
        amihud_wan = calc_amihud(close, volume, amount_wan, 10)

        # 排名应完全相同（单调缩放不改变排名）
        valid = amihud_qian.dropna().index
        rank_qian = amihud_qian[valid].rank()
        rank_yuan = amihud_yuan[valid].rank()
        rank_wan = amihud_wan[valid].rank()
        pd.testing.assert_series_equal(rank_qian, rank_yuan, check_names=False)
        pd.testing.assert_series_equal(rank_qian, rank_wan, check_names=False)

    def test_vwap_bias_unit_conversion(self):
        """VWAP = amount*10/volume 验证千元→元/股单位正确。"""
        from engines.factor_engine import calc_vwap_bias

        # amount=100千元=100,000元, volume=1000手=100,000股
        # VWAP = 100*10/1000 = 1.0 元/股
        close = pd.Series([1.05])
        amount = pd.Series([100.0])   # 千元
        volume = pd.Series([1000.0])  # 手

        bias = calc_vwap_bias(close, amount, volume, 1)
        # VWAP=1.0, bias=(1.05-1.0)/1.0 ≈ 0.05
        assert abs(float(bias.iloc[0]) - 0.05) < 0.01

    def test_money_flow_strength_same_unit(self):
        """net_mf_amount和total_mv同为万元, 比值无量纲。"""
        from engines.factor_engine import calc_money_flow_strength

        net_mf = pd.Series([100.0, 200.0, -50.0])   # 万元
        total_mv = pd.Series([10000.0, 20000.0, 5000.0])  # 万元

        mfs = calc_money_flow_strength(net_mf, total_mv)
        # 100/10000=0.01, 200/20000=0.01, -50/5000=-0.01
        assert abs(float(mfs.iloc[0]) - 0.01) < 1e-6
        assert abs(float(mfs.iloc[2]) - (-0.01)) < 1e-6

    def test_slippage_daily_amount_conversion(self):
        """SimBroker._daily_amount_yuan 千元→元转换。"""
        from engines.backtest_engine import BacktestConfig, SimBroker

        broker = SimBroker(BacktestConfig())
        # 1e5 千元 = 1e8 元 (< 1e9阈值, 应转换)
        row = pd.Series({"amount": 1e5})
        assert broker._daily_amount_yuan(row) == 1e8

        # 已是元的大值 (>= 1e9, 不转换)
        row2 = pd.Series({"amount": 2e9})
        assert broker._daily_amount_yuan(row2) == 2e9

    def test_slippage_market_cap_conversion(self):
        """calc_slippage中total_mv万元→元转换。"""
        from engines.backtest_engine import BacktestConfig, SimBroker

        config = BacktestConfig(slippage_mode="volume_impact")
        broker = SimBroker(config)
        # total_mv=50000万元=5e8元 (< 1e10, 应转换)
        row = pd.Series({
            "open": 10.0, "close": 10.0, "pre_close": 10.0,
            "amount": 1e6,  # 千元→1e9元
            "volume": 1e7,
            "total_mv": 50000,  # 万元→5e8元
            "turnover_rate": 5.0,
        })
        slippage = broker.calc_slippage(10.0, 100000.0, row, "buy")
        # 应该返回正数滑点
        assert slippage > 0
        assert slippage < 10.0  # 不应超过价格本身


# =====================================================================
# A6: API 500错误修复测试
# =====================================================================


class TestA6RiskStateEndpoint:
    """GET /api/risk/state — 返回200而非500。"""

    @pytest.mark.asyncio
    async def test_risk_state_returns_default_when_table_missing(self):
        """表不存在时返回默认NORMAL状态（200）。"""
        from app.api.risk import get_risk_state

        mock_svc = AsyncMock()
        mock_svc.get_current_state.side_effect = Exception(
            'relation "circuit_breaker_state" does not exist'
        )

        result = await get_risk_state(
            strategy_id="00000000-0000-0000-0000-000000000001",
            execution_mode="paper",
            svc=mock_svc,
        )
        assert result["level"] == 0
        assert result["level_name"] == "NORMAL"
        assert result["can_rebalance"] is True

    @pytest.mark.asyncio
    async def test_risk_state_reraises_non_table_errors(self):
        """非表缺失的异常应继续抛出。"""
        from app.api.risk import get_risk_state

        mock_svc = AsyncMock()
        mock_svc.get_current_state.side_effect = RuntimeError("connection refused")

        with pytest.raises(RuntimeError, match="connection refused"):
            await get_risk_state(
                strategy_id="00000000-0000-0000-0000-000000000001",
                execution_mode="paper",
                svc=mock_svc,
            )


class TestA6RiskHistoryEndpoint:
    """GET /api/risk/history — 返回200而非500。"""

    @pytest.mark.asyncio
    async def test_risk_history_returns_empty_when_table_missing(self):
        """表不存在时返回空列表（200）。"""
        from app.api.risk import get_risk_history

        mock_svc = AsyncMock()
        mock_svc.get_transition_history.side_effect = Exception(
            'relation "circuit_breaker_log" does not exist'
        )

        result = await get_risk_history(
            strategy_id="00000000-0000-0000-0000-000000000001",
            execution_mode="paper",
            limit=50,
            svc=mock_svc,
        )
        assert result == []


class TestA6FactorsCorrelationEndpoint:
    """GET /api/factors/correlation — 返回200而非500。"""

    @pytest.mark.asyncio
    async def test_correlation_returns_empty_when_table_missing(self):
        """factor_registry表不存在时返回空矩阵（200）。"""
        from app.api.factors import get_factor_correlation

        mock_svc = AsyncMock()
        mock_svc.get_factor_list.side_effect = Exception(
            'relation "factor_registry" does not exist'
        )

        result = await get_factor_correlation(
            start_date=None,
            end_date=None,
            status="active",
            svc=mock_svc,
        )
        assert result["factor_names"] == []
        assert result["matrix"] == []

    @pytest.mark.asyncio
    async def test_correlation_normal_path_returns_matrix(self):
        """正常路径返回相关性矩阵。"""
        from app.api.factors import get_factor_correlation

        mock_svc = AsyncMock()
        mock_svc.get_factor_list.return_value = [
            {"factor_name": "f1", "status": "active"},
            {"factor_name": "f2", "status": "active"},
        ]

        ic_data_f1 = pd.DataFrame({
            "trade_date": pd.date_range("2024-01-01", periods=30),
            "ic_value": np.random.randn(30) * 0.05,
        })
        ic_data_f2 = pd.DataFrame({
            "trade_date": pd.date_range("2024-01-01", periods=30),
            "ic_value": np.random.randn(30) * 0.05,
        })

        async def mock_get_ic(name, start, end, forward_days=20):
            return ic_data_f1 if name == "f1" else ic_data_f2

        mock_svc.get_factor_ic = mock_get_ic

        result = await get_factor_correlation(
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 1),
            status="active",
            svc=mock_svc,
        )
        assert len(result["factor_names"]) == 2
        assert len(result["matrix"]) == 2
        assert len(result["matrix"][0]) == 2
        # 对角线应为1.0
        assert result["matrix"][0][0] == 1.0
        assert result["matrix"][1][1] == 1.0


class TestA6BacktestNavEndpoint:
    """GET /api/backtest/{id}/nav — 返回200而非500。"""

    @pytest.mark.asyncio
    async def test_nav_returns_empty_when_table_missing(self):
        """backtest_daily_nav表不存在时返回空列表。"""
        from uuid import UUID

        from app.api.backtest import _safe_query

        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception(
            'relation "backtest_daily_nav" does not exist'
        )

        result = await _safe_query(
            mock_session,
            "SELECT * FROM backtest_daily_nav WHERE run_id = :rid",
            {"rid": "test-uuid"},
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_safe_query_reraises_non_table_errors(self):
        """非表缺失错误应继续抛出。"""
        from app.api.backtest import _safe_query

        mock_session = AsyncMock()
        mock_session.execute.side_effect = RuntimeError("timeout")

        with pytest.raises(RuntimeError, match="timeout"):
            await _safe_query(
                mock_session,
                "SELECT 1",
                {},
            )


class TestA6StrategyVersionsEndpoint:
    """GET /api/strategies/{id}/versions — 端点存在且返回200。"""

    @pytest.mark.asyncio
    async def test_versions_returns_empty_when_table_missing(self):
        """strategy_configs表不存在时返回空列表。"""
        from app.api.strategies import get_strategy_versions

        mock_svc = MagicMock()
        mock_repo = AsyncMock()
        mock_repo.get_config_history.side_effect = Exception(
            'relation "strategy_configs" does not exist'
        )
        mock_svc.strategy_repo = mock_repo

        result = await get_strategy_versions(
            strategy_id="test-id",
            svc=mock_svc,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_versions_returns_list_when_exists(self):
        """正常返回版本列表。"""
        from app.api.strategies import get_strategy_versions

        mock_svc = MagicMock()
        mock_repo = AsyncMock()
        mock_repo.get_config_history.return_value = [
            {"version": 2, "config": {}, "changelog": "v2", "created_at": "2024-01-02"},
            {"version": 1, "config": {}, "changelog": "v1", "created_at": "2024-01-01"},
        ]
        mock_svc.strategy_repo = mock_repo

        result = await get_strategy_versions(
            strategy_id="test-id",
            svc=mock_svc,
        )
        assert len(result) == 2
        assert result[0]["version"] == 2

    @pytest.mark.asyncio
    async def test_versions_404_when_strategy_not_found(self):
        """策略不存在且无版本时返回404。"""
        from fastapi import HTTPException

        from app.api.strategies import get_strategy_versions

        mock_svc = MagicMock()
        mock_repo = AsyncMock()
        mock_repo.get_config_history.return_value = []
        mock_repo.get_strategy.return_value = None
        mock_svc.strategy_repo = mock_repo

        with pytest.raises(HTTPException) as exc_info:
            await get_strategy_versions(
                strategy_id="nonexistent",
                svc=mock_svc,
            )
        assert exc_info.value.status_code == 404
