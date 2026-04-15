"""config_guard 单元测试 — 验证配置一致性守卫功能。

测试项:
1. assert_baseline_config: 因子集一致时返回True，无WARNING
2. assert_baseline_config: 因子集不一致时返回False，打印差异
3. print_config_header: 输出包含全部5个基线因子名
4. check_config_alignment / ConfigDriftError (铁律 34, Phase B M3):
   - happy path: 三源对齐 → 无异常
   - 每个参数单独漂移 → RAISE ConfigDriftError
   - factor_list 集合漂移 → RAISE
   - 多项漂移 → 错误消息列出全部
   - yaml 文件缺失 → FileNotFoundError
"""

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import yaml
from engines.config_guard import (
    ConfigDriftError,
    assert_baseline_config,
    check_config_alignment,
    print_config_header,
)
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


# ---------------------------------------------------------------------------
# check_config_alignment 三源对齐硬校验 (铁律 34, Phase B M3)
# ---------------------------------------------------------------------------


@dataclass
class _FakeSettings:
    """模拟 app.config.Settings, 避免 pydantic 环境依赖."""

    PT_TOP_N: int = 20
    PT_INDUSTRY_CAP: float = 1.0
    PT_SIZE_NEUTRAL_BETA: float = 0.50


@dataclass
class _FakePythonConfig:
    """模拟 PAPER_TRADING_CONFIG (SignalConfig-like)."""

    top_n: int = 20
    industry_cap: float = 1.0
    size_neutral_beta: float = 0.50
    turnover_cap: float = 0.50
    rebalance_freq: str = "monthly"
    factor_names: list[str] = field(
        default_factory=lambda: [
            "turnover_mean_20",
            "volatility_20",
            "bp_ratio",
            "dv_ttm",
        ]
    )


def _baseline_yaml_dict() -> dict:
    """返回与 _FakePythonConfig / _FakeSettings 对齐的 strategy YAML."""
    return {
        "strategy": {
            "name": "equal_weight_top20",
            "factors": [
                {"name": "turnover_mean_20", "direction": -1},
                {"name": "volatility_20", "direction": -1},
                {"name": "bp_ratio", "direction": 1},
                {"name": "dv_ttm", "direction": 1},
            ],
            "compose": "equal_weight",
            "top_n": 20,
            "rebalance_freq": "monthly",
            "industry_cap": 1.0,
            "turnover_cap": 0.50,
            "size_neutral_beta": 0.50,
        }
    }


def _write_yaml(tmp_path: Path, config: dict) -> Path:
    p = tmp_path / "pt_live.yaml"
    p.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return p


class TestCheckConfigAlignment:
    """check_config_alignment / ConfigDriftError 测试 (铁律 34)."""

    def test_happy_path_all_aligned(self, tmp_path: Path) -> None:
        """三源完全对齐, 不抛异常."""
        yaml_path = _write_yaml(tmp_path, _baseline_yaml_dict())
        check_config_alignment(
            yaml_path=yaml_path,
            env_settings=_FakeSettings(),
            python_config=_FakePythonConfig(),
        )

    def test_top_n_env_drift_raises(self, tmp_path: Path) -> None:
        """`.env` top_n ≠ yaml/python → RAISE + 错误消息含 top_n."""
        yaml_path = _write_yaml(tmp_path, _baseline_yaml_dict())
        env = _FakeSettings(PT_TOP_N=15)
        with pytest.raises(ConfigDriftError) as exc:
            check_config_alignment(
                yaml_path=yaml_path,
                env_settings=env,
                python_config=_FakePythonConfig(),
            )
        assert "top_n" in str(exc.value)
        assert "15" in str(exc.value)
        assert any(d["param"] == "top_n" for d in exc.value.drifts)

    def test_industry_cap_python_drift_raises(self, tmp_path: Path) -> None:
        """python industry_cap ≠ yaml/env → RAISE."""
        yaml_path = _write_yaml(tmp_path, _baseline_yaml_dict())
        py = _FakePythonConfig(industry_cap=0.25)
        with pytest.raises(ConfigDriftError) as exc:
            check_config_alignment(
                yaml_path=yaml_path,
                env_settings=_FakeSettings(),
                python_config=py,
            )
        assert "industry_cap" in str(exc.value)
        assert any(d["param"] == "industry_cap" for d in exc.value.drifts)

    def test_size_neutral_beta_yaml_drift_raises(self, tmp_path: Path) -> None:
        """yaml size_neutral_beta ≠ env/python → RAISE.

        防复发 F62 (default 0.0 静默降级).
        """
        cfg = _baseline_yaml_dict()
        cfg["strategy"]["size_neutral_beta"] = 0.0
        yaml_path = _write_yaml(tmp_path, cfg)
        with pytest.raises(ConfigDriftError) as exc:
            check_config_alignment(
                yaml_path=yaml_path,
                env_settings=_FakeSettings(),
                python_config=_FakePythonConfig(),
            )
        assert "size_neutral_beta" in str(exc.value)

    def test_turnover_cap_yaml_vs_python_drift_raises(self, tmp_path: Path) -> None:
        """turnover_cap 仅 yaml↔python 对齐 (env 不参与)."""
        cfg = _baseline_yaml_dict()
        cfg["strategy"]["turnover_cap"] = 0.80
        yaml_path = _write_yaml(tmp_path, cfg)
        with pytest.raises(ConfigDriftError) as exc:
            check_config_alignment(
                yaml_path=yaml_path,
                env_settings=_FakeSettings(),
                python_config=_FakePythonConfig(),
            )
        assert "turnover_cap" in str(exc.value)

    def test_rebalance_freq_drift_raises(self, tmp_path: Path) -> None:
        """rebalance_freq yaml ≠ python → RAISE.

        防复发 Step 0.5 原 assert_baseline_config 不检查 freq (F40).
        """
        yaml_path = _write_yaml(tmp_path, _baseline_yaml_dict())
        py = _FakePythonConfig(rebalance_freq="biweekly")
        with pytest.raises(ConfigDriftError) as exc:
            check_config_alignment(
                yaml_path=yaml_path,
                env_settings=_FakeSettings(),
                python_config=py,
            )
        assert "rebalance_freq" in str(exc.value)
        assert "biweekly" in str(exc.value)

    def test_factor_list_extra_in_yaml_raises(self, tmp_path: Path) -> None:
        """yaml 多一个因子 → RAISE."""
        cfg = _baseline_yaml_dict()
        cfg["strategy"]["factors"].append({"name": "amihud_20", "direction": 1})
        yaml_path = _write_yaml(tmp_path, cfg)
        with pytest.raises(ConfigDriftError) as exc:
            check_config_alignment(
                yaml_path=yaml_path,
                env_settings=_FakeSettings(),
                python_config=_FakePythonConfig(),
            )
        assert "factor_list" in str(exc.value)
        assert "amihud_20" in str(exc.value)

    def test_factor_list_missing_in_python_raises(self, tmp_path: Path) -> None:
        """python 少一个因子 → RAISE."""
        yaml_path = _write_yaml(tmp_path, _baseline_yaml_dict())
        py = _FakePythonConfig(factor_names=["turnover_mean_20", "volatility_20", "bp_ratio"])
        with pytest.raises(ConfigDriftError) as exc:
            check_config_alignment(
                yaml_path=yaml_path,
                env_settings=_FakeSettings(),
                python_config=py,
            )
        assert "factor_list" in str(exc.value)
        assert "dv_ttm" in str(exc.value)

    def test_factor_list_order_insensitive(self, tmp_path: Path) -> None:
        """factor_list 比较走 sorted, 顺序不同但集合一致不应触发漂移."""
        yaml_path = _write_yaml(tmp_path, _baseline_yaml_dict())
        py = _FakePythonConfig(
            factor_names=["dv_ttm", "bp_ratio", "volatility_20", "turnover_mean_20"]
        )
        check_config_alignment(
            yaml_path=yaml_path,
            env_settings=_FakeSettings(),
            python_config=py,
        )

    def test_multiple_drifts_all_reported(self, tmp_path: Path) -> None:
        """多个参数同时漂移 → drifts 列出全部, 不 fail-fast."""
        cfg = _baseline_yaml_dict()
        cfg["strategy"]["top_n"] = 25  # yaml 改
        yaml_path = _write_yaml(tmp_path, cfg)
        env = _FakeSettings(PT_INDUSTRY_CAP=0.25)  # env 改
        py = _FakePythonConfig(size_neutral_beta=0.0)  # python 改
        with pytest.raises(ConfigDriftError) as exc:
            check_config_alignment(
                yaml_path=yaml_path,
                env_settings=env,
                python_config=py,
            )
        drift_params = {d["param"] for d in exc.value.drifts}
        assert "top_n" in drift_params
        assert "industry_cap" in drift_params
        assert "size_neutral_beta" in drift_params
        assert len(exc.value.drifts) >= 3

    def test_yaml_file_missing_raises_filenotfound(self, tmp_path: Path) -> None:
        """yaml 路径不存在 → FileNotFoundError (非 ConfigDriftError)."""
        missing = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            check_config_alignment(
                yaml_path=missing,
                env_settings=_FakeSettings(),
                python_config=_FakePythonConfig(),
            )

    def test_yaml_missing_strategy_section_raises_valueerror(self, tmp_path: Path) -> None:
        """yaml 存在但缺 strategy 段 → ValueError."""
        p = tmp_path / "broken.yaml"
        p.write_text("execution:\n  mode: paper\n", encoding="utf-8")
        with pytest.raises(ValueError, match="strategy"):
            check_config_alignment(
                yaml_path=p,
                env_settings=_FakeSettings(),
                python_config=_FakePythonConfig(),
            )

    def test_float_tolerance_handles_representation_noise(self, tmp_path: Path) -> None:
        """0.50 vs 0.5 vs float 表示误差不应触发假漂移."""
        cfg = _baseline_yaml_dict()
        cfg["strategy"]["size_neutral_beta"] = 0.5  # yaml 用 0.5
        yaml_path = _write_yaml(tmp_path, cfg)
        env = _FakeSettings(PT_SIZE_NEUTRAL_BETA=0.5)
        py = _FakePythonConfig(size_neutral_beta=0.5000000001)
        check_config_alignment(
            yaml_path=yaml_path,
            env_settings=env,
            python_config=py,
        )

    def test_real_sources_baseline_aligned(self) -> None:
        """真实 .env + configs/pt_live.yaml + PAPER_TRADING_CONFIG 必须对齐.

        这是 M3 验收的关键测试: 当前 git HEAD 的生产配置不允许漂移.
        如果本测试失败, 表示 PT 生产配置本身已漂移, 需要立刻修复.
        """
        # 使用默认 (内部会读 app.config.settings + configs/pt_live.yaml +
        # engines.signal_engine.PAPER_TRADING_CONFIG)
        check_config_alignment()
