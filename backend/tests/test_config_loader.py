"""YAML配置加载器测试。"""

import pytest

from app.services.config_loader import (
    config_hash,
    get_data_range,
    get_directions,
    load_config,
    to_backtest_config,
    to_signal_config,
)


class TestLoadConfig:
    def test_load_valid_yaml(self):
        cfg = load_config("configs/backtest_5yr.yaml")
        assert isinstance(cfg, dict)
        assert "strategy" in cfg
        assert "execution" in cfg

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_config("configs/nonexistent.yaml")


class TestToBacktestConfig:
    def test_all_fields_mapped(self):
        cfg = load_config("configs/backtest_5yr.yaml")
        bt = to_backtest_config(cfg)
        assert bt.top_n == 20
        assert bt.rebalance_freq == "monthly"
        assert bt.initial_capital == 1_000_000
        assert bt.slippage_mode == "volume_impact"
        assert bt.historical_stamp_tax is True
        assert bt.pms.enabled is True
        assert bt.pms.exec_mode == "same_close"
        assert len(bt.pms.tiers) == 3

    def test_pms_tiers_correct(self):
        cfg = load_config("configs/pt_live.yaml")
        bt = to_backtest_config(cfg)
        assert bt.pms.tiers[0] == (0.30, 0.15)
        assert bt.pms.tiers[1] == (0.20, 0.12)
        assert bt.pms.tiers[2] == (0.10, 0.10)


class TestToSignalConfig:
    def test_factors_mapped(self):
        cfg = load_config("configs/backtest_5yr.yaml")
        sc = to_signal_config(cfg)
        assert len(sc.factor_names) == 5
        assert "turnover_mean_20" in sc.factor_names
        assert sc.top_n == 20
        assert sc.rebalance_freq == "monthly"


class TestGetDirections:
    def test_directions_correct(self):
        cfg = load_config("configs/backtest_5yr.yaml")
        dirs = get_directions(cfg)
        assert dirs["turnover_mean_20"] == -1
        assert dirs["volatility_20"] == -1
        assert dirs["reversal_20"] == 1
        assert dirs["amihud_20"] == 1
        assert dirs["bp_ratio"] == 1


class TestConfigHash:
    def test_hash_deterministic(self):
        cfg = load_config("configs/backtest_5yr.yaml")
        h1 = config_hash(cfg)
        h2 = config_hash(cfg)
        assert h1 == h2
        assert len(h1) == 16  # SHA256[:16]

    def test_different_config_different_hash(self):
        cfg1 = load_config("configs/backtest_5yr.yaml")
        cfg2 = load_config("configs/backtest_12yr.yaml")
        assert config_hash(cfg1) != config_hash(cfg2)


class TestGetDataRange:
    def test_5yr_range(self):
        cfg = load_config("configs/backtest_5yr.yaml")
        start, end = get_data_range(cfg)
        assert start == "2021-01-01"
        assert end == "2025-12-31"

    def test_12yr_range(self):
        cfg = load_config("configs/backtest_12yr.yaml")
        start, end = get_data_range(cfg)
        assert start == "2014-01-01"
