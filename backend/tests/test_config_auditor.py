"""MVP 1.2 test — PlatformConfigAuditor (check_alignment + dump_on_startup)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from backend.platform.config.auditor import (
    ConfigDriftError,
    ConfigDriftReport,
    PlatformConfigAuditor,
    _values_equal,
)
from backend.platform.config.loader import PlatformConfigLoader
from backend.platform.config.schema import RootConfigSchema

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PT_LIVE_YAML = PROJECT_ROOT / "configs" / "pt_live.yaml"


# ---------- Fake python_config ----------


@dataclass
class _FakePythonConfig:
    """模拟 PAPER_TRADING_CONFIG 属性结构."""

    top_n: int = 20
    industry_cap: float = 1.0
    size_neutral_beta: float = 0.50
    turnover_cap: float = 0.50
    rebalance_freq: str = "monthly"
    factor_names: tuple[str, ...] = (
        "turnover_mean_20",
        "volatility_20",
        "bp_ratio",
        "dv_ttm",
    )


# ---------- _values_equal helper ----------


def test_values_equal_numeric_tolerance() -> None:
    assert _values_equal(0.5, 0.5)
    assert _values_equal(0.50, 0.5 + 1e-12)
    assert not _values_equal(0.50, 0.51)


def test_values_equal_none_handling() -> None:
    assert _values_equal(None, None)
    assert not _values_equal(None, 0)
    assert not _values_equal(1, None)


# ---------- check_alignment ----------


def test_check_alignment_pt_live_aligned() -> None:
    """现生产 PT 配置三源对齐 (已通过 regression 验证)."""
    report = PlatformConfigAuditor().check_alignment(
        yaml_path=PT_LIVE_YAML,
        env={
            "PT_TOP_N": "20",
            "PT_INDUSTRY_CAP": "1.0",
            "PT_SIZE_NEUTRAL_BETA": "0.50",
        },
        python_config=_FakePythonConfig(),
        strict=False,
    )
    assert report.passed is True
    assert report.mismatches == []


def test_check_alignment_env_drift_raises(tmp_path: Path) -> None:
    """env PT_TOP_N 与 yaml/python 不一致 → raise ConfigDriftError."""
    with pytest.raises(ConfigDriftError, match="top_n"):
        PlatformConfigAuditor().check_alignment(
            yaml_path=PT_LIVE_YAML,
            env={
                "PT_TOP_N": "30",  # yaml/python 都是 20
                "PT_SIZE_NEUTRAL_BETA": "0.50",
            },
            python_config=_FakePythonConfig(),
            strict=True,
        )


def test_check_alignment_yaml_vs_python_drift(tmp_path: Path) -> None:
    """yaml 有 turnover_cap=0.5, python 写 0.7 → drift."""
    report = PlatformConfigAuditor().check_alignment(
        yaml_path=PT_LIVE_YAML,
        env={},
        python_config=_FakePythonConfig(turnover_cap=0.7),
        strict=False,
    )
    assert report.passed is False
    drift_names = {m["param"] for m in report.mismatches}
    assert "turnover_cap" in drift_names


def test_check_alignment_factor_list_drift() -> None:
    """python.factor_names 多一个因子 → drift."""
    report = PlatformConfigAuditor().check_alignment(
        yaml_path=PT_LIVE_YAML,
        env={},
        python_config=_FakePythonConfig(
            factor_names=(
                "turnover_mean_20",
                "volatility_20",
                "bp_ratio",
                "dv_ttm",
                "extra_factor",  # 多一个
            )
        ),
        strict=False,
    )
    assert report.passed is False
    drift_names = {m["param"] for m in report.mismatches}
    assert "factor_list" in drift_names


def test_check_alignment_strict_raises_drift_error() -> None:
    """strict=True 时漂移必 raise."""
    with pytest.raises(ConfigDriftError):
        PlatformConfigAuditor().check_alignment(
            yaml_path=PT_LIVE_YAML,
            env={},
            python_config=_FakePythonConfig(size_neutral_beta=0.20),  # yaml 0.50
            strict=True,
        )


def test_check_alignment_missing_env_falls_back_to_yaml_python() -> None:
    """.env 不提供对应 key 时, 只比 yaml vs python (不 raise)."""
    report = PlatformConfigAuditor().check_alignment(
        yaml_path=PT_LIVE_YAML,
        env={},  # 空 env
        python_config=_FakePythonConfig(),
        strict=False,
    )
    assert report.passed is True


def test_check_alignment_missing_yaml_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        PlatformConfigAuditor().check_alignment(
            yaml_path=tmp_path / "does_not_exist.yaml",
            env={},
            python_config=_FakePythonConfig(),
        )


def test_config_drift_error_message_includes_all_drifts() -> None:
    """异常消息里列出所有漂移 param, 便于人肉排查."""
    with pytest.raises(ConfigDriftError) as exc_info:
        PlatformConfigAuditor().check_alignment(
            yaml_path=PT_LIVE_YAML,
            env={"PT_TOP_N": "99"},
            python_config=_FakePythonConfig(
                top_n=20, size_neutral_beta=0.99, turnover_cap=0.99
            ),
            strict=True,
        )
    msg = str(exc_info.value)
    assert "top_n" in msg
    assert "size_neutral_beta" in msg
    assert "turnover_cap" in msg
    # drift 清单也暴露为属性
    assert len(exc_info.value.drifts) >= 3


def test_check_alignment_returns_report_dataclass() -> None:
    """strict=False 时返回 ConfigDriftReport, 可查 mismatches."""
    report = PlatformConfigAuditor().check_alignment(
        yaml_path=PT_LIVE_YAML,
        env={},
        python_config=_FakePythonConfig(top_n=99),  # drift
        strict=False,
    )
    assert isinstance(report, ConfigDriftReport)
    assert report.passed is False
    assert any(m["param"] == "top_n" for m in report.mismatches)


# ---------- dump_on_startup ----------


def test_dump_on_startup_creates_file(tmp_path: Path) -> None:
    cfg = PlatformConfigLoader().load(
        RootConfigSchema,
        yaml_path=PT_LIVE_YAML,
        env={"DATABASE_URL": "postgresql://test"},
    )
    audit_path = PlatformConfigAuditor().dump_on_startup(
        cfg, caller="unit_test", log_dir=tmp_path
    )
    assert audit_path.exists()
    data = json.loads(audit_path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert len(data) == 1
    entry = data[0]
    assert entry["caller"] == "unit_test"
    assert len(entry["config_hash"]) == 16
    assert "git_commit" in entry
    assert entry["config"]["strategy"]["top_n"] == 20


def test_dump_on_startup_appends_same_day(tmp_path: Path) -> None:
    """同一天多次调用 append 到 list."""
    cfg = PlatformConfigLoader().load(
        RootConfigSchema,
        yaml_path=PT_LIVE_YAML,
        env={"DATABASE_URL": "postgresql://test"},
    )
    auditor = PlatformConfigAuditor()
    p1 = auditor.dump_on_startup(cfg, caller="first", log_dir=tmp_path)
    p2 = auditor.dump_on_startup(cfg, caller="second", log_dir=tmp_path)
    assert p1 == p2
    data = json.loads(p2.read_text(encoding="utf-8"))
    assert len(data) == 2
    assert data[0]["caller"] == "first"
    assert data[1]["caller"] == "second"


def test_dump_config_hash_stable(tmp_path: Path) -> None:
    """相同 config 产生相同 hash (铁律 15 复现锚点)."""
    cfg = PlatformConfigLoader().load(
        RootConfigSchema,
        yaml_path=PT_LIVE_YAML,
        env={"DATABASE_URL": "postgresql://test"},
    )
    auditor = PlatformConfigAuditor()
    p1 = auditor.dump_on_startup(cfg, caller="hash_test_a", log_dir=tmp_path)
    auditor.dump_on_startup(cfg, caller="hash_test_b", log_dir=tmp_path)
    data = json.loads(p1.read_text(encoding="utf-8"))
    # 两条 entry 的 config_hash 应相同
    assert data[0]["config_hash"] == data[1]["config_hash"]


def test_dump_creates_log_dir(tmp_path: Path) -> None:
    """log_dir 不存在时自动创建."""
    nested = tmp_path / "nested" / "logs"
    cfg = PlatformConfigLoader().load(
        RootConfigSchema,
        yaml_path=PT_LIVE_YAML,
        env={"DATABASE_URL": "postgresql://test"},
    )
    audit_path = PlatformConfigAuditor().dump_on_startup(
        cfg, caller="mkdir_test", log_dir=nested
    )
    assert audit_path.exists()
    assert nested.is_dir()
