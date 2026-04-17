"""Framework #8 Config Management — ConfigLoader concrete 实现.

实现优先级: env (.env 显式映射) > yaml (configs/pt_live.yaml) > code default (Pydantic Field default).

env 映射表硬编码 (显式, 避免隐式推断漂移):
  PT_TOP_N              → strategy.top_n
  PT_INDUSTRY_CAP       → strategy.industry_cap
  PT_SIZE_NEUTRAL_BETA  → strategy.size_neutral_beta
  EXECUTION_MODE        → execution.mode
  PMS_ENABLED           → execution.pms.enabled
  DATABASE_URL          → database.url
  PAPER_STRATEGY_ID     → paper_trading.strategy_id
  PAPER_INITIAL_CAPITAL → paper_trading.initial_capital
  QMT_PATH              → paper_trading.qmt_path
  QMT_ACCOUNT_ID        → paper_trading.qmt_account_id

其他 .env 参数 (如 LOG_LEVEL / TUSHARE_TOKEN / ADMIN_TOKEN) 由 `backend/app/config.py::Settings`
继续管理, 不进入 Platform Schema — 因为它们非策略参数, 纳入 Schema 会增 surface 无价值.

关联铁律 34: 配置 single source of truth — 本模块是 load 真相源.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from backend.platform.config.interface import ConfigLoader, ConfigSchema
from backend.platform.config.schema import RootConfigSchema

_DEFAULT_YAML_PATH = "configs/pt_live.yaml"


# ---------- 类型化环境变量映射 ----------

_ENV_MAPPING: dict[str, tuple[str, type]] = {
    # env var name → (schema dotted path, cast type)
    "PT_TOP_N": ("strategy.top_n", int),
    "PT_INDUSTRY_CAP": ("strategy.industry_cap", float),
    "PT_SIZE_NEUTRAL_BETA": ("strategy.size_neutral_beta", float),
    "EXECUTION_MODE": ("execution.mode", str),
    "PMS_ENABLED": ("execution.pms.enabled", bool),
    "DATABASE_URL": ("database.url", str),
    "PAPER_STRATEGY_ID": ("paper_trading.strategy_id", str),
    "PAPER_INITIAL_CAPITAL": ("paper_trading.initial_capital", float),
    "QMT_PATH": ("paper_trading.qmt_path", str),
    "QMT_ACCOUNT_ID": ("paper_trading.qmt_account_id", str),
}


def _resolve_yaml_path(yaml_path: Path | str | None) -> Path:
    """把相对路径解析为项目根绝对路径."""
    if yaml_path is None:
        yaml_path = _DEFAULT_YAML_PATH
    path = Path(yaml_path)
    if not path.is_absolute():
        # backend/platform/config/loader.py → 4 parents up = project root
        project_root = Path(__file__).resolve().parents[3]
        path = project_root / path
    return path


def _load_yaml(path: Path) -> dict[str, Any]:
    """安全加载 YAML, 返回 dict."""
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} 顶层不是 dict")
    return data


def _transform_yaml_for_schema(raw: dict[str, Any]) -> dict[str, Any]:
    """把 pt_live.yaml 原始结构映射到 RootConfigSchema 期望结构.

    转换点:
      1. strategy.factors (list of {name, direction}) → factor_names + factor_directions
      2. execution.slippage.config (nested) → flat SlippageConfigSchema fields
      3. 其他字段直通

    注意: 不直接改 pt_live.yaml, 由本 loader 在内存做结构适配.
    """
    out: dict[str, Any] = {}

    # ---- strategy ----
    strategy_raw = dict(raw.get("strategy") or {})
    factors = strategy_raw.pop("factors", None)
    if factors is not None:
        names = tuple(f["name"] for f in factors if isinstance(f, dict) and "name" in f)
        directions = {
            f["name"]: int(f["direction"])
            for f in factors
            if isinstance(f, dict) and "name" in f and "direction" in f
        }
        strategy_raw["factor_names"] = names
        strategy_raw["factor_directions"] = directions
    out["strategy"] = strategy_raw

    # ---- execution ----
    execution_raw = dict(raw.get("execution") or {})
    slippage_raw = dict(execution_raw.get("slippage") or {})
    if "config" in slippage_raw:
        # flatten: {mode, config: {...}} → {mode, ...}
        nested = slippage_raw.pop("config") or {}
        slippage_raw.update(nested)
    if slippage_raw:
        execution_raw["slippage"] = slippage_raw
    # pms.tiers: 保持 list[dict], Pydantic PMSTier 会校验
    if execution_raw:
        out["execution"] = execution_raw

    # ---- universe / backtest 直通 ----
    if raw.get("universe"):
        out["universe"] = raw["universe"]
    if raw.get("backtest"):
        out["backtest"] = raw["backtest"]

    return out


def _cast_env_value(raw: str, cast_type: type) -> Any:
    """把 env 字符串 cast 到目标类型."""
    if cast_type is bool:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    if cast_type is int:
        return int(raw)
    if cast_type is float:
        return float(raw)
    return raw  # str


def _set_nested(target: dict[str, Any], dotted: str, value: Any) -> None:
    """按点分路径把值写入 nested dict (创建中间层)."""
    parts = dotted.split(".")
    cur = target
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = value


def _apply_env_overrides(base: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    """把 env 显式映射叠加到 base dict (最高优先级)."""
    for env_key, (dotted, cast_type) in _ENV_MAPPING.items():
        if env_key in env and env[env_key] != "":
            _set_nested(base, dotted, _cast_env_value(env[env_key], cast_type))
    return base


# ---------- Public API: PlatformConfigLoader ----------


class PlatformConfigLoader(ConfigLoader):
    """`backend.platform.config.interface.ConfigLoader` 的 concrete 实现.

    用法:
        loader = PlatformConfigLoader()
        root = loader.load(RootConfigSchema, yaml_path='configs/pt_live.yaml')
        assert root.strategy.top_n == 20
    """

    def load(
        self,
        schema: ConfigSchema | type[RootConfigSchema] = RootConfigSchema,
        yaml_path: Path | str | None = None,
        *,
        env: dict[str, str] | None = None,
    ) -> RootConfigSchema:
        """加载并合并配置.

        Args:
          schema: RootConfigSchema 类 (接受 ConfigSchema 以兼容 abstract 签名, 但
            实际使用 Pydantic 类). 传入其他 ConfigSchema 实例会 raise.
          yaml_path: YAML 路径. None 则使用 `configs/pt_live.yaml`.
          env: 注入 env dict (测试用). None 则读 os.environ.

        Returns:
          RootConfigSchema 合并后的不可变实例.

        Raises:
          FileNotFoundError: YAML 文件不存在
          ValueError: YAML 格式损坏
          pydantic.ValidationError: Schema 校验失败
        """
        # 1. 解析 schema 类型
        if isinstance(schema, type) and issubclass(schema, RootConfigSchema):
            root_cls = schema
        elif schema is RootConfigSchema or isinstance(schema, ConfigSchema):
            root_cls = RootConfigSchema
        else:
            raise TypeError(
                f"PlatformConfigLoader expects RootConfigSchema class, got {schema!r}"
            )

        # 2. YAML 加载 + 结构适配
        path = _resolve_yaml_path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(
                f"配置文件不存在: {path}. "
                "PlatformConfigLoader 需要 YAML 作为权威源 (或显式传 yaml_path=None 并 env 补齐)."
            )
        yaml_raw = _load_yaml(path)
        merged = _transform_yaml_for_schema(yaml_raw)

        # 3. env override (最高优先级)
        env_dict = env if env is not None else dict(os.environ)
        merged = _apply_env_overrides(merged, env_dict)

        # 4. 填补 required 字段 (若 yaml 缺 database, 从 env 补)
        if "database" not in merged and "DATABASE_URL" in env_dict:
            merged.setdefault("database", {})["url"] = env_dict["DATABASE_URL"]
        merged.setdefault("database", {"url": env_dict.get("DATABASE_URL", "")})
        # strategy 必填: yaml 里有, 否则 env 无法补 factor_names — 交由 Pydantic raise

        # 5. Pydantic 校验 + 构造 immutable instance
        try:
            return root_cls.model_validate(merged)
        except ValidationError as e:
            raise ValidationError.from_exception_data(
                title=f"RootConfigSchema validation failed (yaml={path})",
                line_errors=e.errors(),  # type: ignore[arg-type]
            ) from e


__all__ = ["PlatformConfigLoader"]
