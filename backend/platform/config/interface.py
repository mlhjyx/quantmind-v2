"""Framework #8 Config Management — single source of truth 的守护者.

目标: 消除 .env / pt_live.yaml / Python 常量三处配置漂移.

关联铁律:
  - 34: 配置 single source of truth (ConfigSchema 是唯一真相源)

实施时机:
  - MVP 1.2 Config Management (Wave 1, 紧跟 1.1 之后)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ConfigDriftReport:
    """config_guard 校验输出.

    Args:
      passed: 是否三处对齐
      mismatches: 不一致列表, 每条 {"key": "...", "env": "...", "yaml": "...", "py": "..."}
    """

    passed: bool
    mismatches: list[dict[str, str]]


class ConfigSchema(ABC):
    """配置 schema 基类 — 所有可配置参数必须在此声明.

    原则:
      - 每个参数只有一个 ConfigSchema 定义点 (铁律 34)
      - 默认值由此定, .env / yaml 可 override, 但 key 必须先在此注册
      - 类型 + 值域 校验发生在 load 时 (fail-loud)
    """

    @abstractmethod
    def get_schema(self) -> dict[str, dict[str, Any]]:
        """返回完整 schema.

        Returns:
          dict, key=参数名, value={"type": "...", "default": ..., "range": [...], "doc": "..."}
        """

    @abstractmethod
    def validate(self, config: dict[str, Any]) -> None:
        """校验给定 config 满足 schema.

        Raises:
          ConfigValidationError: 类型错 / 值域超限 / 未知 key
        """


class ConfigLoader(ABC):
    """配置加载器 — 按优先级合并 .env → yaml → Python default.

    优先级 (高覆盖低):
      1. 环境变量 (.env / process env)
      2. YAML 配置文件 (pt_live.yaml)
      3. ConfigSchema default
    """

    @abstractmethod
    def load(self, schema: ConfigSchema, yaml_path: str | None = None) -> dict[str, Any]:
        """加载合并后的配置.

        Args:
          schema: 配置 schema 实例
          yaml_path: YAML 文件路径 (可空, 仅用 env + default)

        Returns:
          合并后的 config dict

        Raises:
          ConfigValidationError: schema 校验失败
          YAMLParseError: YAML 解析失败
        """


class ConfigAuditor(ABC):
    """配置漂移审计 — PT 启动前 + health_check 调用, 确保三处对齐.

    关联铁律 34: 不一致必须 RAISE, 不允许 warning.
    """

    @abstractmethod
    def check_alignment(self, schema: ConfigSchema) -> ConfigDriftReport:
        """检查 .env / yaml / Python 常量三处一致.

        Returns:
          ConfigDriftReport, passed=False 时 mismatches 列具体差异.

        Raises:
          ConfigDriftError: 若 passed=False 且调用方设 strict=True
        """


class FeatureFlag(ABC):
    """Feature flag — 用于 MVP 灰度上线 + A/B 实验.

    原则: 每个 flag 必须有 removal_date (避免 flag 永久化).
    """

    @abstractmethod
    def is_enabled(self, flag_name: str, context: dict[str, Any] | None = None) -> bool:
        """查询 flag 是否开启.

        Args:
          flag_name: 唯一 flag 名
          context: 上下文 (用于 percentage rollout / user bucketing)

        Returns:
          True 若开启

        Raises:
          FlagNotFound: flag_name 未注册
          FlagExpired: flag 超过 removal_date 仍未移除
        """

    @abstractmethod
    def register(
        self, name: str, default: bool, removal_date: str, description: str
    ) -> None:
        """注册新 flag.

        Args:
          name: flag 名
          default: 默认值
          removal_date: YYYY-MM-DD, 超期必须清理
          description: 作用说明
        """
