"""MVP 1.2 test — ConfigSchema (Pydantic) + ConfigLoader (env > yaml > default)."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from backend.qm_platform.config.loader import (
    PlatformConfigLoader,
    _apply_env_overrides,
    _cast_env_value,
    _transform_yaml_for_schema,
)
from backend.qm_platform.config.schema import (
    BacktestConfigSchema,
    CostConfigSchema,
    DatabaseConfigSchema,
    ExecutionConfigSchema,
    PlatformConfigSchema,
    PMSConfigSchema,
    PMSTier,
    RootConfigSchema,
    StrategyConfigSchema,
    UniverseConfigSchema,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PT_LIVE_YAML = PROJECT_ROOT / "configs" / "pt_live.yaml"


# ---------- Schema 默认值 / 值域 ----------


_MIN_STRATEGY = {
    "factor_names": ("x",),
    "factor_directions": {"x": 1},
}


def test_strategy_schema_defaults() -> None:
    s = StrategyConfigSchema(**_MIN_STRATEGY)
    assert s.top_n == 20
    assert s.size_neutral_beta == 0.50
    assert s.industry_cap == 1.0
    assert s.turnover_cap == 0.50
    assert s.rebalance_freq == "monthly"
    assert s.compose == "equal_weight"


def test_strategy_schema_top_n_range() -> None:
    with pytest.raises(ValidationError, match="top_n"):
        StrategyConfigSchema(**_MIN_STRATEGY, top_n=0)
    with pytest.raises(ValidationError, match="top_n"):
        StrategyConfigSchema(**_MIN_STRATEGY, top_n=200)


def test_strategy_schema_invalid_freq() -> None:
    with pytest.raises(ValidationError, match="rebalance_freq"):
        StrategyConfigSchema(**_MIN_STRATEGY, rebalance_freq="quarterly")


def test_strategy_schema_invalid_compose() -> None:
    with pytest.raises(ValidationError, match="compose"):
        StrategyConfigSchema(**_MIN_STRATEGY, compose="random")


def test_strategy_schema_unknown_field_rejected() -> None:
    """extra=forbid 防漂移."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        StrategyConfigSchema(**_MIN_STRATEGY, top_n=20, unknown_field="xyz")


def test_strategy_schema_empty_factors_rejected() -> None:
    """factor_names 必填且至少 1 个 — 防空 PT."""
    with pytest.raises(ValidationError):
        StrategyConfigSchema(factor_names=(), factor_directions={})


def test_cost_schema_stamp_tax_validator() -> None:
    with pytest.raises(ValidationError, match="stamp_tax"):
        CostConfigSchema(stamp_tax="invalid")


def test_execution_mode_validator() -> None:
    with pytest.raises(ValidationError, match="execution.mode"):
        ExecutionConfigSchema(mode="invalid")


def test_pms_tier_range() -> None:
    with pytest.raises(ValidationError):
        PMSTier(gain=1.5, drawdown=0.5)
    with pytest.raises(ValidationError):
        PMSTier(gain=0.3, drawdown=-0.1)


def test_pms_defaults_has_3_tiers() -> None:
    p = PMSConfigSchema()
    assert len(p.tiers) == 3
    assert p.tiers[0].gain == 0.30
    assert p.tiers[0].drawdown == 0.15


def test_universe_defaults() -> None:
    u = UniverseConfigSchema()
    assert u.exclude_bj is True
    assert u.exclude_st is True
    assert u.min_listing_days == 60


def test_backtest_defaults() -> None:
    b = BacktestConfigSchema()
    assert b.initial_capital == 1_000_000.0
    assert b.benchmark == "000300.SH"
    assert b.lot_size == 100


def test_root_schema_required_fields() -> None:
    """strategy / database 是 required, 其他有默认."""
    with pytest.raises(ValidationError):
        RootConfigSchema()  # missing strategy + database


def test_root_schema_minimal_valid() -> None:
    root = RootConfigSchema(
        strategy=StrategyConfigSchema(
            factor_names=("turnover_mean_20",),
            factor_directions={"turnover_mean_20": -1},
        ),
        database=DatabaseConfigSchema(url="postgresql://test"),
    )
    assert root.execution.mode == "paper"
    assert root.universe.exclude_bj is True
    assert root.backtest.lot_size == 100


def test_platform_config_schema_json_schema() -> None:
    """PlatformConfigSchema (MVP 1.1 ConfigSchema wrapper) 可产出 JSON Schema."""
    pcs = PlatformConfigSchema()
    schema = pcs.get_schema()
    assert "properties" in schema
    assert set(schema["properties"]).issuperset(
        {"strategy", "execution", "universe", "backtest", "database"}
    )


def test_platform_config_schema_validate() -> None:
    """PlatformConfigSchema.validate 调 Pydantic model_validate."""
    pcs = PlatformConfigSchema()
    pcs.validate(
        {
            "strategy": {"factor_names": ["x"], "factor_directions": {"x": 1}},
            "database": {"url": "postgresql://test"},
        }
    )
    with pytest.raises(ValidationError):
        pcs.validate({"strategy": {}})  # missing database


# ---------- Loader: yaml 解析 + env override ----------


def test_load_pt_live_yaml(tmp_path: Path) -> None:
    """读真实 pt_live.yaml, 验证字段对齐."""
    cfg = PlatformConfigLoader().load(
        RootConfigSchema,
        yaml_path=PT_LIVE_YAML,
        env={"DATABASE_URL": "postgresql://test"},
    )
    assert cfg.strategy.factor_names == (
        "turnover_mean_20",
        "volatility_20",
        "bp_ratio",
        "dv_ttm",
    )
    assert cfg.strategy.factor_directions == {
        "turnover_mean_20": -1,
        "volatility_20": -1,
        "bp_ratio": 1,
        "dv_ttm": 1,
    }
    assert cfg.strategy.top_n == 20
    assert cfg.strategy.size_neutral_beta == 0.50
    assert cfg.execution.slippage.Y_large == 0.8
    assert cfg.execution.costs.stamp_tax == "historical"
    assert cfg.execution.pms.enabled is True
    assert len(cfg.execution.pms.tiers) == 3
    assert cfg.universe.exclude_bj is True


def test_load_env_overrides_yaml(tmp_path: Path) -> None:
    """env 优先于 yaml (PT_SIZE_NEUTRAL_BETA=0.20 覆盖 yaml 的 0.50)."""
    cfg = PlatformConfigLoader().load(
        RootConfigSchema,
        yaml_path=PT_LIVE_YAML,
        env={
            "DATABASE_URL": "postgresql://test",
            "PT_TOP_N": "25",
            "PT_SIZE_NEUTRAL_BETA": "0.20",
            "PT_INDUSTRY_CAP": "0.25",
        },
    )
    assert cfg.strategy.top_n == 25
    assert cfg.strategy.size_neutral_beta == 0.20
    assert cfg.strategy.industry_cap == 0.25


def test_load_env_cast_bool() -> None:
    """bool 类型 env 正确 cast."""
    cfg = PlatformConfigLoader().load(
        RootConfigSchema,
        yaml_path=PT_LIVE_YAML,
        env={
            "DATABASE_URL": "postgresql://test",
            "PMS_ENABLED": "false",
        },
    )
    assert cfg.execution.pms.enabled is False


def test_load_missing_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        PlatformConfigLoader().load(
            RootConfigSchema,
            yaml_path=tmp_path / "does_not_exist.yaml",
            env={"DATABASE_URL": "postgresql://test"},
        )


def test_load_malformed_yaml_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a\n- list\n")
    with pytest.raises(ValueError, match="顶层不是 dict"):
        PlatformConfigLoader().load(
            RootConfigSchema,
            yaml_path=bad,
            env={"DATABASE_URL": "postgresql://test"},
        )


def test_load_yaml_without_strategy_raises(tmp_path: Path) -> None:
    """yaml 缺 strategy 段 → Pydantic 校验 required fail."""
    bad = tmp_path / "no_strategy.yaml"
    bad.write_text("execution:\n  mode: paper\n")
    with pytest.raises(ValidationError):
        PlatformConfigLoader().load(
            RootConfigSchema,
            yaml_path=bad,
            env={"DATABASE_URL": "postgresql://test"},
        )


# ---------- Helper 函数单测 ----------


def test_transform_yaml_factors_to_schema() -> None:
    raw = {
        "strategy": {
            "factors": [
                {"name": "a", "direction": 1},
                {"name": "b", "direction": -1},
            ],
            "top_n": 10,
        },
    }
    out = _transform_yaml_for_schema(raw)
    assert out["strategy"]["factor_names"] == ("a", "b")
    assert out["strategy"]["factor_directions"] == {"a": 1, "b": -1}
    assert out["strategy"]["top_n"] == 10
    assert "factors" not in out["strategy"]


def test_transform_yaml_slippage_flatten() -> None:
    raw = {
        "execution": {
            "slippage": {
                "mode": "volume_impact",
                "config": {"Y_large": 0.9, "base_bps_large": 4.0},
            }
        }
    }
    out = _transform_yaml_for_schema(raw)
    assert out["execution"]["slippage"]["mode"] == "volume_impact"
    assert out["execution"]["slippage"]["Y_large"] == 0.9
    assert out["execution"]["slippage"]["base_bps_large"] == 4.0
    assert "config" not in out["execution"]["slippage"]


def test_cast_env_value_bool_variants() -> None:
    assert _cast_env_value("true", bool) is True
    assert _cast_env_value("1", bool) is True
    assert _cast_env_value("YES", bool) is True
    assert _cast_env_value("false", bool) is False
    assert _cast_env_value("", bool) is False
    assert _cast_env_value("anything_else", bool) is False


def test_apply_env_overrides_nested_creation() -> None:
    base: dict = {}
    _apply_env_overrides(
        base,
        {
            "PT_TOP_N": "30",
            "PT_SIZE_NEUTRAL_BETA": "0.75",
            "DATABASE_URL": "postgresql://x",
            "PMS_ENABLED": "1",
        },
    )
    assert base["strategy"]["top_n"] == 30
    assert base["strategy"]["size_neutral_beta"] == 0.75
    assert base["database"]["url"] == "postgresql://x"
    assert base["execution"]["pms"]["enabled"] is True


def test_apply_env_overrides_empty_value_ignored() -> None:
    """env 值为空字符串不覆盖 (保护老 .env 空值导致静默降级)."""
    base: dict = {"strategy": {"top_n": 20}}
    _apply_env_overrides(base, {"PT_TOP_N": ""})
    assert base["strategy"]["top_n"] == 20


# ---------- Frozen / immutable 属性 ----------


def test_config_extra_forbid_catches_typos() -> None:
    """Pydantic extra=forbid: 拼错字段名会被拒绝 (防 F62 类事故)."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RootConfigSchema.model_validate(
            {
                "strategy": {
                    "factor_names": ["x"],
                    "factor_directions": {"x": 1},
                    "size_neutral_btea": 0.5,  # typo: btea
                },
                "database": {"url": "postgresql://test"},
            }
        )


def test_loaded_config_values_aligned_with_pt_live() -> None:
    """端到端: load pt_live.yaml 后关键参数与当前 PT 生产一致 (F62 监控)."""
    cfg = PlatformConfigLoader().load(
        RootConfigSchema,
        yaml_path=PT_LIVE_YAML,
        env={"DATABASE_URL": "postgresql://test"},
    )
    with PT_LIVE_YAML.open(encoding="utf-8") as f:
        yaml_raw = yaml.safe_load(f)
    assert cfg.strategy.size_neutral_beta == yaml_raw["strategy"]["size_neutral_beta"]
    assert cfg.strategy.top_n == yaml_raw["strategy"]["top_n"]
    assert cfg.strategy.turnover_cap == yaml_raw["strategy"]["turnover_cap"]
    assert cfg.backtest.initial_capital == yaml_raw["backtest"]["initial_capital"]
