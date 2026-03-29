"""config_guard 单元测试 — 验证配置一致性守卫功能。

测试项:
1. assert_baseline_config: 因子集一致时返回True，无WARNING
2. assert_baseline_config: 因子集不一致时返回False，打印差异
3. print_config_header: 输出包含全部5个基线因子名
"""

import pytest
from engines.config_guard import assert_baseline_config, print_config_header
from engines.signal_engine import PAPER_TRADING_CONFIG


class TestAssertBaselineConfig:
    """assert_baseline_config 测试。"""

    def test_consistent_factors_returns_true(self, capsys: pytest.CaptureFixture) -> None:
        """因子集与PAPER_TRADING_CONFIG完全一致时，返回True且无WARNING输出。"""
        result = assert_baseline_config(
            factor_names=list(PAPER_TRADING_CONFIG.factor_names),
            config_source="test_consistent",
        )
        assert result is True
        captured = capsys.readouterr()
        assert "WARNING" not in captured.out

    def test_consistent_factors_different_order(self) -> None:
        """顺序不同但集合一致，仍返回True。"""
        reversed_factors = list(reversed(PAPER_TRADING_CONFIG.factor_names))
        result = assert_baseline_config(
            factor_names=reversed_factors,
            config_source="test_order",
        )
        assert result is True

    def test_extra_factors_returns_false(self, capsys: pytest.CaptureFixture) -> None:
        """多出因子时返回False，输出包含多出因子名。"""
        factors = list(PAPER_TRADING_CONFIG.factor_names) + ["ln_market_cap"]
        result = assert_baseline_config(
            factor_names=factors,
            config_source="test_extra",
        )
        assert result is False
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        assert "ln_market_cap" in captured.out
        assert "test_extra" in captured.out

    def test_missing_factors_returns_false(self, capsys: pytest.CaptureFixture) -> None:
        """缺少因子时返回False，输出包含缺少因子名。"""
        factors = PAPER_TRADING_CONFIG.factor_names[:3]  # 只用前3个
        result = assert_baseline_config(
            factor_names=factors,
            config_source="test_missing",
        )
        assert result is False
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        # 应列出缺少的因子
        missing = set(PAPER_TRADING_CONFIG.factor_names) - set(factors)
        for f in missing:
            assert f in captured.out

    def test_completely_wrong_factors(self, capsys: pytest.CaptureFixture) -> None:
        """完全不同的因子集，返回False，输出包含多出和缺少。"""
        wrong_factors = ["momentum_20", "ln_market_cap", "ep_ratio"]
        result = assert_baseline_config(
            factor_names=wrong_factors,
            config_source="test_wrong",
        )
        assert result is False
        captured = capsys.readouterr()
        assert "WARNING" in captured.out
        # 多出的
        assert "momentum_20" in captured.out
        assert "ln_market_cap" in captured.out
        assert "ep_ratio" in captured.out

    def test_config_source_in_output(self, capsys: pytest.CaptureFixture) -> None:
        """config_source参数出现在不一致的输出中。"""
        result = assert_baseline_config(
            factor_names=["fake_factor"],
            config_source="my_custom_script.py",
        )
        assert result is False
        captured = capsys.readouterr()
        assert "my_custom_script.py" in captured.out


class TestPrintConfigHeader:
    """print_config_header 测试。"""

    def test_header_contains_all_factor_names(self, capsys: pytest.CaptureFixture) -> None:
        """输出包含PAPER_TRADING_CONFIG中全部5个因子名。"""
        print_config_header()
        captured = capsys.readouterr()
        for factor in PAPER_TRADING_CONFIG.factor_names:
            assert factor in captured.out, f"因子 {factor} 未出现在header输出中"

    def test_header_contains_top_n(self, capsys: pytest.CaptureFixture) -> None:
        """输出包含top_n配置值。"""
        print_config_header()
        captured = capsys.readouterr()
        assert str(PAPER_TRADING_CONFIG.top_n) in captured.out

    def test_header_contains_freq(self, capsys: pytest.CaptureFixture) -> None:
        """输出包含rebalance_freq配置值。"""
        print_config_header()
        captured = capsys.readouterr()
        assert PAPER_TRADING_CONFIG.rebalance_freq in captured.out

    def test_header_contains_factor_count(self, capsys: pytest.CaptureFixture) -> None:
        """输出包含因子数量。"""
        print_config_header()
        captured = capsys.readouterr()
        assert str(len(PAPER_TRADING_CONFIG.factor_names)) in captured.out
