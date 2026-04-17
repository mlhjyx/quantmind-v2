"""Framework #8 Config Management — ConfigAuditor concrete 实现.

两大职责:
  1. `check_alignment()` — Schema 驱动的三源 (`.env` / `pt_live.yaml` / `PAPER_TRADING_CONFIG`)
     一致性校验, 接管老 `config_guard.check_config_alignment`. 新字段加到 `_TRIPLE_SOURCE_FIELDS`
     映射表即生效, 不再每次改代码.
  2. `dump_on_startup()` — 启动时 dump full config + sha256 hash + git_commit 到
     `logs/config_audit_YYYY-MM-DD.json` (同日多次启动 append 成 list).

关联铁律:
  - 34: 配置 single source of truth — 漂移 fail-loud, 不允许 warning
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from .interface import ConfigAuditor
from .schema import RootConfigSchema

_DEFAULT_YAML_PATH = "configs/pt_live.yaml"
_DEFAULT_LOG_DIR = "logs"


# ---------- 三源对比映射表 ----------


@dataclass(frozen=True)
class _TripleField:
    """单参数三源映射.

    Attributes:
      name: 报告里用的参数名
      env_key: .env 环境变量名 (None 表示无对应 env 源)
      yaml_path: pt_live.yaml 的 dotted path (从 strategy/execution 等子段内开始)
      py_attr: PAPER_TRADING_CONFIG 实例的属性名
      cast: env 字符串 cast 函数
    """

    name: str
    env_key: str | None
    yaml_path: str
    py_attr: str
    cast: type | None


_TRIPLE_SOURCE_FIELDS: tuple[_TripleField, ...] = (
    _TripleField("top_n", "PT_TOP_N", "strategy.top_n", "top_n", int),
    _TripleField("industry_cap", "PT_INDUSTRY_CAP", "strategy.industry_cap", "industry_cap", float),
    _TripleField(
        "size_neutral_beta",
        "PT_SIZE_NEUTRAL_BETA",
        "strategy.size_neutral_beta",
        "size_neutral_beta",
        float,
    ),
    _TripleField("turnover_cap", None, "strategy.turnover_cap", "turnover_cap", None),
    _TripleField("rebalance_freq", None, "strategy.rebalance_freq", "rebalance_freq", None),
)


_FLOAT_TOL = 1e-9


# ---------- Error + Report ----------


class ConfigDriftError(RuntimeError):
    """铁律 34: 配置 single source of truth 违反.

    `.env` / `pt_live.yaml` / `PAPER_TRADING_CONFIG` 三源之间任何一项
    关键参数不一致都会抛此异常. PT 启动 fail-loud, 不允许静默降级.

    Attributes:
        drifts: 漂移列表, 每项 `{"param": str, "sources": {src_name: value, ...}}`.
    """

    def __init__(self, drifts: list[dict[str, Any]]):
        self.drifts = drifts
        lines = [
            f"配置 single source of truth 违反 (铁律 34): {len(drifts)} 项漂移",
        ]
        for d in drifts:
            param = d["param"]
            srcs = "; ".join(f"{k}={v!r}" for k, v in d["sources"].items())
            lines.append(f"  - {param}: {srcs}")
        lines.append(
            "修复: 把三处 (.env / pt_live.yaml / signal_engine.py::PAPER_TRADING_CONFIG) "
            "对齐到同一值. YAML 是 factor_list / rebalance_freq / turnover_cap 权威, "
            ".env 是 top_n / industry_cap / size_neutral_beta 权威."
        )
        super().__init__("\n".join(lines))


@dataclass(frozen=True)
class ConfigDriftReport:
    """check_alignment 输出.

    Attributes:
      passed: 三源是否全部对齐
      mismatches: 漂移列表 (同 ConfigDriftError.drifts 结构)
    """

    passed: bool
    mismatches: list[dict[str, Any]]


# ---------- Helper ----------


def _values_equal(a: Any, b: Any) -> bool:
    """通用相等, 数值走浮点容差."""
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < _FLOAT_TOL
    return a == b


def _get_dotted(d: dict[str, Any], path: str) -> Any:
    """按 dotted path 从 nested dict 取值, 缺失返回 None."""
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _cast_env(raw: str, cast: type | None) -> Any:
    if cast is None:
        return raw
    if cast is bool:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return cast(raw)


def _resolve_yaml_path(yaml_path: Path | str | None) -> Path:
    if yaml_path is None:
        yaml_path = _DEFAULT_YAML_PATH
    path = Path(yaml_path)
    if not path.is_absolute():
        project_root = Path(__file__).resolve().parents[3]
        path = project_root / path
    return path


def _git_commit() -> str:
    """读当前 git HEAD commit sha, 失败返回 'unknown'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return "unknown"


# ---------- PlatformConfigAuditor ----------


class PlatformConfigAuditor(ConfigAuditor):
    """`backend.platform.config.interface.ConfigAuditor` 的 concrete 实现.

    Usage (PT 启动):
        auditor = PlatformConfigAuditor()
        auditor.check_alignment(schema)  # 三源对齐硬校验
        auditor.dump_on_startup(schema, caller='pt_start')
    """

    def check_alignment(
        self,
        schema: RootConfigSchema | Any | None = None,
        *,
        yaml_path: Path | str | None = None,
        env: dict[str, str] | None = None,
        python_config: Any | None = None,
        strict: bool = True,
    ) -> ConfigDriftReport:
        """Schema 驱动三源对齐校验.

        Args:
          schema: 已加载的 RootConfigSchema (预留给未来 Schema 自定义场景; 本 MVP
            内部仍独立读三源对比, 不信任 schema 已合并的值). 保留参数位置以兼容
            ConfigAuditor abstract 签名.
          yaml_path: pt_live.yaml 路径 (None 走默认).
          env: 注入 env (测试用, None 读 os.environ).
          python_config: PAPER_TRADING_CONFIG 实例 (None 动态 import).
          strict: True 则漂移即 raise ConfigDriftError (默认).

        Returns:
          ConfigDriftReport.

        Raises:
          ConfigDriftError: strict=True 且有漂移.
          FileNotFoundError: pt_live.yaml 不存在.
        """
        # 1. 加载三源
        yaml_path_resolved = _resolve_yaml_path(yaml_path)
        if not yaml_path_resolved.exists():
            raise FileNotFoundError(f"pt_live.yaml 未找到: {yaml_path_resolved}")
        with yaml_path_resolved.open(encoding="utf-8") as f:
            yaml_raw = yaml.safe_load(f) or {}
        if not isinstance(yaml_raw, dict):
            raise ValueError(f"pt_live.yaml 顶层不是 dict: {yaml_path_resolved}")
        if not isinstance(yaml_raw.get("strategy"), dict):
            raise ValueError(f"pt_live.yaml 缺少 'strategy' 段: {yaml_path_resolved}")

        env_dict = env if env is not None else dict(os.environ)

        if python_config is None:
            # 动态 import 兼容两种 sys.path 场景:
            #   (a) pytest / PT 主进程: backend/ 已在 sys.path → `import engines` OK
            #   (b) 项目根直跑 python: backend/ 不在 sys.path → append 到末尾
            # 注意: 禁止 insert(0), 否则 backend/platform/ 会覆盖 stdlib platform,
            # 导致 pandas 崩溃 (pandas 内部 `import platform; platform.python_implementation()`).
            try:
                from engines.signal_engine import PAPER_TRADING_CONFIG
            except ImportError:
                import sys
                backend_dir = Path(__file__).resolve().parents[2]
                if str(backend_dir) not in sys.path:
                    sys.path.append(str(backend_dir))  # append 保 stdlib 优先
                from engines.signal_engine import PAPER_TRADING_CONFIG

            python_config = PAPER_TRADING_CONFIG

        drifts: list[dict[str, Any]] = []

        # 2. 按 _TRIPLE_SOURCE_FIELDS 逐字段对比
        for field in _TRIPLE_SOURCE_FIELDS:
            yaml_val = _get_dotted(yaml_raw, field.yaml_path)
            py_val = getattr(python_config, field.py_attr, None)
            sources: dict[str, Any] = {"pt_live.yaml": yaml_val, "python": py_val}

            # env (如有)
            if field.env_key is not None and field.env_key in env_dict and env_dict[field.env_key] != "":
                env_raw = env_dict[field.env_key]
                env_val: Any = _cast_env(env_raw, field.cast)
                sources[".env"] = env_val
                if not (
                    _values_equal(env_val, yaml_val) and _values_equal(yaml_val, py_val)
                ):
                    drifts.append({"param": field.name, "sources": sources})
            else:
                # 只比 yaml vs python
                if not _values_equal(yaml_val, py_val):
                    drifts.append({"param": field.name, "sources": sources})

        # 3. factor_list 特殊: yaml 是 list[{name, direction}], python 是 tuple[str,...]
        yaml_factors = yaml_raw.get("strategy", {}).get("factors") or []
        yaml_factor_names = tuple(
            sorted(f["name"] for f in yaml_factors if isinstance(f, dict) and "name" in f)
        )
        py_factor_names = tuple(sorted(getattr(python_config, "factor_names", []) or []))
        if yaml_factor_names != py_factor_names:
            drifts.append(
                {
                    "param": "factor_list",
                    "sources": {
                        "pt_live.yaml": list(yaml_factor_names),
                        "python": list(py_factor_names),
                    },
                }
            )

        # 4. 汇总
        report = ConfigDriftReport(passed=not drifts, mismatches=drifts)
        if drifts and strict:
            raise ConfigDriftError(drifts)
        return report

    def dump_on_startup(
        self,
        schema: RootConfigSchema,
        *,
        caller: str,
        log_dir: Path | str | None = None,
    ) -> Path:
        """Dump full config + hash + git_commit 到 logs/config_audit_YYYY-MM-DD.json.

        同日多次调用 append, 文件格式为 list[entry].

        Args:
          schema: RootConfigSchema 实例 (合并后).
          caller: 调用方标识 (e.g. "pt_start", "celery_beat_start", "health_check").
          log_dir: 日志目录 (None 走 `logs/`).

        Returns:
          日志文件路径.
        """
        # 1. 序列化 config (model_dump + sort_keys 保 hash 稳定)
        config_dict = schema.model_dump(mode="json")
        canonical = json.dumps(config_dict, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        config_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

        # 2. 构造 entry
        now = datetime.now(UTC)
        entry = {
            "timestamp_utc": now.isoformat(),
            "caller": caller,
            "git_commit": _git_commit(),
            "config_hash": config_hash,
            "config": config_dict,
        }

        # 3. 解析路径
        if log_dir is None:
            project_root = Path(__file__).resolve().parents[3]
            log_dir_path = project_root / _DEFAULT_LOG_DIR
        else:
            log_dir_path = Path(log_dir)
        log_dir_path.mkdir(parents=True, exist_ok=True)

        today = now.astimezone().date() if now.astimezone().tzinfo else date.today()
        audit_path = log_dir_path / f"config_audit_{today.isoformat()}.json"

        # 4. append 到文件 (若存在)
        existing: list[dict[str, Any]] = []
        if audit_path.exists():
            try:
                with audit_path.open(encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    existing = loaded
            except (json.JSONDecodeError, OSError):
                existing = []
        existing.append(entry)

        with audit_path.open("w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)

        return audit_path


__all__ = [
    "ConfigDriftError",
    "ConfigDriftReport",
    "PlatformConfigAuditor",
]
