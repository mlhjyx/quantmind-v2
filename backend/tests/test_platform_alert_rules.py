"""MVP 4.1 batch 2.2 unit tests — AlertRulesEngine yaml-driven routing."""
from __future__ import annotations

from pathlib import Path

import pytest
from qm_platform._types import Severity
from qm_platform.observability import (
    Alert,
    AlertRule,
    AlertRuleError,
    AlertRulesEngine,
)


def _alert(
    *,
    severity: Severity = Severity.P1,
    source: str = "factor_lifecycle_monitor",
    details: dict | None = None,
    title: str = "test alert",
) -> Alert:
    return Alert(
        title=title,
        severity=severity,
        source=source,
        details=details or {},
        trade_date="2026-04-29",
        timestamp_utc="2026-04-29T12:00:00+00:00",
    )


# ─────────────────────────── AlertRule.matches ───────────────────────────


def test_rule_matches_severity_and_source():
    rule = AlertRule(
        name="p1_factor",
        match_severity="p1",
        match_source="factor_lifecycle_monitor",
        channels=("dingtalk",),
        suppress_minutes=30,
        dedup_key_template="factor:{factor}",
    )
    assert rule.matches(_alert(severity=Severity.P1, source="factor_lifecycle_monitor"))
    assert not rule.matches(_alert(severity=Severity.P0))
    assert not rule.matches(_alert(source="other"))


def test_rule_matches_wildcard_when_field_none():
    """match_severity=None or match_source=None 视为通配."""
    rule = AlertRule(
        name="catchall_p0",
        match_severity="p0",
        match_source=None,  # 通配 source
        channels=("dingtalk",),
        suppress_minutes=5,
        dedup_key_template="any:{source}",
    )
    assert rule.matches(_alert(severity=Severity.P0, source="anything"))
    assert rule.matches(_alert(severity=Severity.P0, source="other_source"))
    assert not rule.matches(_alert(severity=Severity.P1))


# ─────────────────────────── format_dedup_key ───────────────────────────


def test_format_dedup_key_uses_alert_details():
    rule = AlertRule(
        name="x",
        match_severity=None,
        match_source=None,
        channels=("dingtalk",),
        suppress_minutes=30,
        dedup_key_template="factor_lifecycle:{factor}:{transition}",
    )
    a = _alert(details={"factor": "dv_ttm", "transition": "warning"})
    assert rule.format_dedup_key(a) == "factor_lifecycle:dv_ttm:warning"


def test_format_dedup_key_supports_source_severity_top_level():
    rule = AlertRule(
        name="x",
        match_severity=None,
        match_source=None,
        channels=("dingtalk",),
        suppress_minutes=30,
        dedup_key_template="catchall:{source}:{severity}",
    )
    a = _alert(severity=Severity.P0, source="x_module")
    assert rule.format_dedup_key(a) == "catchall:x_module:p0"


def test_format_dedup_key_top_level_wins_over_details_shadow():
    """reviewer P1 采纳: details 含 source/severity 时, top-level 永远赢, 防 silent shadow.

    历史: 原代码 ``{**details, "source": ...}`` 顺序让 details 后写覆盖 top-level,
    若 caller 误塞 ``details={"source": "shadowed"}`` 会 silently 用错 key 破 dedup.
    """
    rule = AlertRule(
        name="x",
        match_severity=None,
        match_source=None,
        channels=("dingtalk",),
        suppress_minutes=30,
        dedup_key_template="{source}:{severity}:{factor}",
    )
    a = _alert(
        severity=Severity.P1,
        source="real_source",
        details={
            "source": "MALICIOUS_SHADOW",  # 必须不能覆盖 top-level
            "severity": "p99",  # 必须不能覆盖 top-level
            "factor": "dv_ttm",
        },
    )
    key = rule.format_dedup_key(a)
    assert key == "real_source:p1:dv_ttm", f"top-level shadowed by details, got: {key}"


def test_format_dedup_key_missing_placeholder_raises():
    rule = AlertRule(
        name="x",
        match_severity=None,
        match_source=None,
        channels=("dingtalk",),
        suppress_minutes=30,
        dedup_key_template="needs:{nonexistent_key}",
    )
    with pytest.raises(AlertRuleError, match="缺占位符变量"):
        rule.format_dedup_key(_alert(details={"factor": "dv"}))


# ─────────────────────────── AlertRulesEngine.match ───────────────────────────


def test_engine_match_first_rule_wins():
    """rules 顺序敏感, 第一个 match 即返."""
    rules = (
        AlertRule(
            name="specific_p0_intraday",
            match_severity="p0",
            match_source="intraday_monitor",
            channels=("dingtalk",),
            suppress_minutes=5,
            dedup_key_template="intraday:p0",
        ),
        AlertRule(
            name="catchall_p0",
            match_severity="p0",
            match_source=None,
            channels=("dingtalk",),
            suppress_minutes=5,
            dedup_key_template="catchall:p0",
        ),
    )
    engine = AlertRulesEngine(rules=rules)
    a_specific = _alert(severity=Severity.P0, source="intraday_monitor")
    a_other = _alert(severity=Severity.P0, source="other")

    matched = engine.match(a_specific)
    assert matched is not None and matched.name == "specific_p0_intraday"

    matched2 = engine.match(a_other)
    assert matched2 is not None and matched2.name == "catchall_p0"


def test_engine_match_no_rule_returns_none():
    engine = AlertRulesEngine(rules=())
    assert engine.match(_alert()) is None


def test_from_dict_zero_rules_logs_warning(caplog):
    """reviewer P2 采纳: 加载 0 rules 必 log warn (退化 SSOT 应早提示运维)."""
    import logging as _logging
    with caplog.at_level(_logging.WARNING, logger="qm_platform.observability.rules"):
        engine = AlertRulesEngine.from_dict({"rules": []})
    assert len(engine.rules) == 0
    assert any(
        "0 rules" in rec.message for rec in caplog.records
    ), f"必 log 0-rules warning, got: {[r.message for r in caplog.records]}"


# ─────────────────────────── from_dict schema validation ───────────────────────────


def test_from_dict_minimal_valid():
    data = {
        "rules": [
            {
                "name": "p1_default",
                "match": {"severity": "p1"},
                "action": {
                    "channels": ["dingtalk"],
                    "suppress_minutes": 30,
                    "dedup_key_template": "x:{source}",
                },
            }
        ]
    }
    engine = AlertRulesEngine.from_dict(data)
    assert len(engine.rules) == 1
    assert engine.rules[0].name == "p1_default"


def test_from_dict_rejects_non_dict_root():
    with pytest.raises(AlertRuleError, match="root must be dict"):
        AlertRulesEngine.from_dict("not a dict")  # type: ignore[arg-type]


def test_from_dict_rejects_missing_rules_key():
    with pytest.raises(AlertRuleError, match="must be list"):
        AlertRulesEngine.from_dict({})


def test_from_dict_rejects_duplicate_names():
    data = {
        "rules": [
            {
                "name": "x",
                "match": {},
                "action": {
                    "channels": ["d"],
                    "suppress_minutes": 5,
                    "dedup_key_template": "k",
                },
            },
            {
                "name": "x",
                "match": {},
                "action": {
                    "channels": ["d"],
                    "suppress_minutes": 5,
                    "dedup_key_template": "k",
                },
            },
        ]
    }
    with pytest.raises(AlertRuleError, match="duplicate rule name"):
        AlertRulesEngine.from_dict(data)


def test_from_dict_rejects_invalid_severity():
    data = {
        "rules": [
            {
                "name": "x",
                "match": {"severity": "P0"},  # 大写不对
                "action": {
                    "channels": ["d"],
                    "suppress_minutes": 5,
                    "dedup_key_template": "k",
                },
            }
        ]
    }
    with pytest.raises(AlertRuleError, match="invalid severity"):
        AlertRulesEngine.from_dict(data)


def test_from_dict_rejects_zero_suppress_minutes():
    data = {
        "rules": [
            {
                "name": "x",
                "match": {},
                "action": {
                    "channels": ["d"],
                    "suppress_minutes": 0,
                    "dedup_key_template": "k",
                },
            }
        ]
    }
    with pytest.raises(AlertRuleError, match="positive int"):
        AlertRulesEngine.from_dict(data)


def test_from_dict_rejects_bool_suppress_minutes():
    """bool 是 int 子类, 显式 reject."""
    data = {
        "rules": [
            {
                "name": "x",
                "match": {},
                "action": {
                    "channels": ["d"],
                    "suppress_minutes": True,  # bool!
                    "dedup_key_template": "k",
                },
            }
        ]
    }
    with pytest.raises(AlertRuleError, match="positive int"):
        AlertRulesEngine.from_dict(data)


def test_from_dict_rejects_empty_channels():
    data = {
        "rules": [
            {
                "name": "x",
                "match": {},
                "action": {
                    "channels": [],
                    "suppress_minutes": 5,
                    "dedup_key_template": "k",
                },
            }
        ]
    }
    with pytest.raises(AlertRuleError, match="non-empty str list"):
        AlertRulesEngine.from_dict(data)


def test_from_dict_rejects_empty_template():
    data = {
        "rules": [
            {
                "name": "x",
                "match": {},
                "action": {
                    "channels": ["d"],
                    "suppress_minutes": 5,
                    "dedup_key_template": "  ",
                },
            }
        ]
    }
    with pytest.raises(AlertRuleError, match="non-empty str"):
        AlertRulesEngine.from_dict(data)


# ─────────────────────────── from_yaml integration ───────────────────────────


def test_from_yaml_loads_real_default_config():
    """实测加载 configs/alert_rules.yaml 默认规则集."""
    project_root = Path(__file__).resolve().parents[2]
    yaml_path = project_root / "configs" / "alert_rules.yaml"
    if not yaml_path.exists():
        pytest.skip("configs/alert_rules.yaml 未发现 (CI 环境)")

    engine = AlertRulesEngine.from_yaml(yaml_path)
    # 至少含 P0/P1/P2 catchall
    rule_names = {r.name for r in engine.rules}
    assert "catchall_p0" in rule_names
    assert "catchall_p1" in rule_names

    # 实测 Alert 匹配
    a_p1 = _alert(
        severity=Severity.P1,
        source="factor_lifecycle_monitor",
        details={"factor": "dv_ttm", "transition": "warning"},
    )
    matched = engine.match(a_p1)
    assert matched is not None
    assert matched.name == "p1_factor_lifecycle_warning"
    assert (
        matched.format_dedup_key(a_p1) == "factor_lifecycle:dv_ttm:warning"
    )


def test_from_yaml_file_not_found_raises():
    with pytest.raises(AlertRuleError, match="not found"):
        AlertRulesEngine.from_yaml("/nonexistent/path/to/rules.yaml")
