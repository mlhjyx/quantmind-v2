"""MVP 4.1 batch 2.2 — AlertRulesEngine yaml-driven routing.

Blueprint #7 字面 "AlertRulesEngine (yaml 驱动): configs/alert_rules.yaml":
  规则集中化 + caller 只需 fire(Alert) 不传 suppress_minutes, Engine 查 rules 决定.

设计原则:
  - yaml schema 走 Pydantic (复用 MVP 1.2 ConfigSchema 模式)
  - rules 顺序匹配, 第一个 match 即应用 (caller 用更具体规则放前面)
  - match 字段 ALL 满足才算匹配 (AND 语义), 缺字段视为通配
  - 默认规则 fallback (e.g. 无规则匹配时用 severity 默认 suppress)
  - dedup_key_template 支持 {field} 占位符从 Alert.details 取值
  - **不破坏现有 fire(dedup_key=...) API**: Engine 是新增能力, caller 显式 key 优先

关联铁律:
  - 34 (config SSOT): yaml 唯一规则源, 不允许散落
  - 33 (fail-loud): yaml schema 错误必 raise, dedup_key_template 占位符缺 raise
  - 39 (双模式): 平台工程师视角写, Application caller 透明使用

Usage:
    >>> from qm_platform.observability import AlertRulesEngine, get_alert_router
    >>> engine = AlertRulesEngine.from_yaml("configs/alert_rules.yaml")
    >>> router = get_alert_router()
    >>> # caller 不传 dedup_key, Engine 自动查 rules
    >>> alert = Alert(title="...", severity=Severity.P0, source="intraday_monitor",
    ...               details={"code": "600519.SH"}, ...)
    >>> rule = engine.match(alert)
    >>> if rule:
    ...     router.fire(alert, dedup_key=rule.format_dedup_key(alert),
    ...                 suppress_minutes=rule.suppress_minutes)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .interface import Alert

logger = logging.getLogger(__name__)


class AlertRuleError(ValueError):
    """yaml schema 或 rule 应用错误 (铁律 33 fail-loud)."""


@dataclass(frozen=True)
class AlertRule:
    """单条告警规则 (yaml 一行 entry).

    Args:
      name: 规则唯一标识 (e.g. "p0_intraday_drop")
      match_severity: 严重度匹配 (None = 通配)
      match_source: 发源模块匹配 (None = 通配, 支持精确字符串)
      channels: 触发的 channel 列表 (e.g. ["dingtalk"], ["dingtalk","sms"])
      suppress_minutes: dedup 抑制窗口 (分钟)
      dedup_key_template: dedup key 模板, 支持 {field} 占位符从 Alert.details 取值,
                          {source}/{severity} 从 Alert 顶层
    """

    name: str
    match_severity: str | None
    match_source: str | None
    channels: tuple[str, ...]
    suppress_minutes: int
    dedup_key_template: str

    def matches(self, alert: Alert) -> bool:
        """ALL match_* 满足 (AND, None 视通配)."""
        if self.match_severity is not None and alert.severity.value != self.match_severity:
            return False
        return not (
            self.match_source is not None and alert.source != self.match_source
        )

    def format_dedup_key(self, alert: Alert) -> str:
        """从 template 生成实际 dedup_key, 占位符缺失 raise.

        Template 解析:
          - {source} → alert.source
          - {severity} → alert.severity.value
          - {<key>} → alert.details[<key>]
          - 字面 {} 用 {{}} 转义 (Python str.format 标准)
        """
        # 收集可用变量
        ctx: dict[str, Any] = {
            "source": alert.source,
            "severity": alert.severity.value,
            **alert.details,
        }
        try:
            return self.dedup_key_template.format(**ctx)
        except KeyError as e:
            raise AlertRuleError(
                f"rule {self.name!r} dedup_key_template {self.dedup_key_template!r} "
                f"缺占位符变量 {e}, 可用变量={sorted(ctx)}"
            ) from e


@dataclass(frozen=True)
class AlertRulesEngine:
    """AlertRulesEngine: 加载 yaml 规则集, 按顺序匹配 Alert.

    Args:
      rules: AlertRule 列表 (顺序敏感, 第一个 match 即返)
      default_suppress_minutes: 无规则匹配时的兜底 (severity-driven 由 PostgresAlertRouter
                                _DEFAULT_SUPPRESS_MINUTES 决定, 此处不重叠)
    """

    rules: tuple[AlertRule, ...]

    def match(self, alert: Alert) -> AlertRule | None:
        """按顺序查第一个匹配规则. None = 无匹配 (caller 用 PostgresAlertRouter 默认)."""
        for rule in self.rules:
            if rule.matches(alert):
                return rule
        return None

    @classmethod
    def from_yaml(cls, path: str | Path) -> AlertRulesEngine:
        """从 yaml 文件加载.

        yaml schema 示例:
            rules:
              - name: p0_intraday_portfolio
                match:
                  severity: p0
                  source: intraday_monitor
                action:
                  channels: [dingtalk]
                  suppress_minutes: 5
                  dedup_key_template: "intraday:{source}:{code}"

        Raises:
          AlertRuleError: yaml 解析失败 / schema 错误.
        """
        # 延迟 import yaml — 减少 module load 时依赖暴露
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as e:
            raise AlertRuleError(
                "AlertRulesEngine.from_yaml requires PyYAML. pip install pyyaml."
            ) from e

        path = Path(path)
        if not path.is_file():
            raise AlertRuleError(f"yaml file not found: {path}")
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as e:
            raise AlertRuleError(f"yaml parse error: {e}") from e

        return cls.from_dict(data, source_path=str(path))

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, source_path: str = "<dict>"
    ) -> AlertRulesEngine:
        """从已解析 dict 构造 (单测便利方法 + from_yaml 内部用)."""
        if not isinstance(data, dict):
            raise AlertRuleError(
                f"yaml root must be dict, got {type(data).__name__} at {source_path}"
            )
        raw_rules = data.get("rules")
        if not isinstance(raw_rules, list):
            raise AlertRuleError(
                f"yaml 'rules' must be list, got {type(raw_rules).__name__} at {source_path}"
            )
        rules: list[AlertRule] = []
        seen_names: set[str] = set()
        for idx, raw in enumerate(raw_rules):
            if not isinstance(raw, dict):
                raise AlertRuleError(
                    f"rules[{idx}] must be dict, got {type(raw).__name__}"
                )
            name = raw.get("name")
            if not name or not isinstance(name, str):
                raise AlertRuleError(f"rules[{idx}] missing or non-str 'name'")
            if name in seen_names:
                raise AlertRuleError(f"duplicate rule name: {name}")
            seen_names.add(name)

            match = raw.get("match", {})
            action = raw.get("action", {})
            if not isinstance(match, dict) or not isinstance(action, dict):
                raise AlertRuleError(
                    f"rules[{idx}={name}] match/action must be dict"
                )

            ms = match.get("severity")
            if ms is not None and ms not in ("p0", "p1", "p2", "info"):
                raise AlertRuleError(
                    f"rules[{idx}={name}] invalid severity {ms!r}, "
                    f"must be p0/p1/p2/info"
                )
            mo_src = match.get("source")
            if mo_src is not None and not isinstance(mo_src, str):
                raise AlertRuleError(
                    f"rules[{idx}={name}] match.source must be str"
                )

            channels = action.get("channels")
            if (
                not isinstance(channels, list)
                or not channels  # empty list (vacuous all()) reject
                or not all(isinstance(c, str) and c for c in channels)
            ):
                raise AlertRuleError(
                    f"rules[{idx}={name}] action.channels must be non-empty str list"
                )
            sm = action.get("suppress_minutes")
            if not isinstance(sm, int) or isinstance(sm, bool) or sm <= 0:
                raise AlertRuleError(
                    f"rules[{idx}={name}] action.suppress_minutes must be positive int, "
                    f"got {sm!r}"
                )
            tpl = action.get("dedup_key_template")
            if not isinstance(tpl, str) or not tpl.strip():
                raise AlertRuleError(
                    f"rules[{idx}={name}] action.dedup_key_template must be non-empty str"
                )
            rules.append(
                AlertRule(
                    name=name,
                    match_severity=ms,
                    match_source=mo_src,
                    channels=tuple(channels),
                    suppress_minutes=sm,
                    dedup_key_template=tpl,
                )
            )
        return cls(rules=tuple(rules))


__all__ = [
    "AlertRule",
    "AlertRuleError",
    "AlertRulesEngine",
]
