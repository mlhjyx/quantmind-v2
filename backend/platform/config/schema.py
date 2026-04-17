"""Framework #8 Config Management — Pydantic Schema concrete 定义.

对齐 `configs/pt_live.yaml` 的 2 层 nested 结构:
  root.strategy / root.execution / root.universe / root.backtest /
  root.database / root.paper_trading

覆盖 60-80 项参数 (7 类), 剩余 (LLM / GP / Celery / notification 等) 留给对应
Framework 各自 MVP 纳入 — 铁律 23 独立可执行 + 铁律 24 抽象层级聚焦.

关联铁律:
  - 34: 配置 single source of truth (本模块是 Schema 真相源)

实施时机: MVP 1.2 Config Management (Wave 1, 2026-04-18).
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .interface import ConfigSchema

# ---------- Strategy ----------


class StrategyConfigSchema(BaseModel):
    """策略级参数 — 对齐 pt_live.yaml `strategy:` 段."""

    model_config = ConfigDict(extra="forbid")

    name: str = "equal_weight_top20"
    factor_names: tuple[str, ...] = Field(..., min_length=1)
    factor_directions: dict[str, int]
    compose: str = "equal_weight"
    top_n: int = Field(20, ge=1, le=100)
    rebalance_freq: str = "monthly"
    industry_cap: float = Field(1.0, ge=0.0, le=1.0)
    turnover_cap: float = Field(0.50, ge=0.0, le=1.0)
    cash_buffer: float = Field(0.03, ge=0.0, le=0.5)
    size_neutral_beta: float = Field(0.50, ge=0.0, le=1.0)

    @field_validator("rebalance_freq")
    @classmethod
    def _check_freq(cls, v: str) -> str:
        allowed = {"daily", "weekly", "monthly", "event"}
        if v not in allowed:
            raise ValueError(f"rebalance_freq must be one of {allowed}, got {v!r}")
        return v

    @field_validator("compose")
    @classmethod
    def _check_compose(cls, v: str) -> str:
        allowed = {"equal_weight", "equal", "ic_weighted", "ir_weighted", "lambda_rank"}
        if v not in allowed:
            raise ValueError(f"compose must be one of {allowed}, got {v!r}")
        return v


# ---------- Execution (nested: slippage / costs / pms) ----------


class SlippageConfigSchema(BaseModel):
    """三因素滑点模型参数 — 对齐 slippage_model.SlippageConfig."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "volume_impact"
    Y_large: float = 0.8
    Y_mid: float = 1.0
    Y_small: float = 1.5
    base_bps_large: float = 3.0
    base_bps_mid: float = 5.0
    base_bps_small: float = 8.0
    sell_penalty: float = 1.2
    gap_penalty_factor: float = 0.5


class CostConfigSchema(BaseModel):
    """交易成本参数 — 对齐 pt_live.yaml `execution.costs:` 段."""

    model_config = ConfigDict(extra="forbid")

    commission_rate: float = Field(0.0000854, ge=0.0, le=0.01)
    min_commission: float = Field(5.0, ge=0.0)
    stamp_tax: str = "historical"
    stamp_tax_rate: float = Field(0.0005, ge=0.0, le=0.01)
    transfer_fee_rate: float = Field(0.00001, ge=0.0, le=0.001)

    @field_validator("stamp_tax")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in {"historical", "fixed"}:
            raise ValueError(f"stamp_tax must be 'historical' or 'fixed', got {v!r}")
        return v


class PMSTier(BaseModel):
    """PMS 单层阈值 (浮盈阈值 + 回撤阈值)."""

    model_config = ConfigDict(extra="forbid")

    gain: float = Field(ge=0.0, le=1.0)
    drawdown: float = Field(ge=0.0, le=1.0)


class PMSConfigSchema(BaseModel):
    """PMS 阶梯利润保护参数."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    exec_mode: str = "same_close"
    tiers: list[PMSTier] = Field(
        default_factory=lambda: [
            PMSTier(gain=0.30, drawdown=0.15),
            PMSTier(gain=0.20, drawdown=0.12),
            PMSTier(gain=0.10, drawdown=0.10),
        ]
    )

    @field_validator("exec_mode")
    @classmethod
    def _check_exec_mode(cls, v: str) -> str:
        if v not in {"same_close", "next_open"}:
            raise ValueError(f"exec_mode must be 'same_close' or 'next_open', got {v!r}")
        return v


class ExecutionConfigSchema(BaseModel):
    """执行层参数 — 对齐 pt_live.yaml `execution:` 段."""

    model_config = ConfigDict(extra="forbid")

    mode: str = "paper"
    slippage: SlippageConfigSchema = Field(default_factory=SlippageConfigSchema)
    costs: CostConfigSchema = Field(default_factory=CostConfigSchema)
    pms: PMSConfigSchema = Field(default_factory=PMSConfigSchema)

    @field_validator("mode")
    @classmethod
    def _check_mode(cls, v: str) -> str:
        if v not in {"paper", "live", "backtest"}:
            raise ValueError(f"execution.mode must be paper/live/backtest, got {v!r}")
        return v


# ---------- Universe ----------


class UniverseConfigSchema(BaseModel):
    """可交易股票池过滤规则."""

    model_config = ConfigDict(extra="forbid")

    exclude_st: bool = True
    exclude_bj: bool = True
    exclude_suspended: bool = True
    exclude_new_stock: bool = True
    min_listing_days: int = Field(60, ge=0, le=365)


# ---------- Backtest ----------


class BacktestConfigSchema(BaseModel):
    """回测基础参数 — 对齐 pt_live.yaml `backtest:` 段."""

    model_config = ConfigDict(extra="forbid")

    initial_capital: float = Field(1_000_000.0, gt=0.0)
    benchmark: str = "000300.SH"
    lot_size: int = Field(100, ge=1)
    volume_cap_pct: float = Field(0.10, ge=0.0, le=1.0)


# ---------- Infrastructure (DB / PT runtime) ----------


class DatabaseConfigSchema(BaseModel):
    """数据库连接 — .env DATABASE_URL 等."""

    model_config = ConfigDict(extra="forbid")

    url: str
    pool_size: int = Field(20, ge=1, le=200)
    echo: bool = False


class PaperTradingConfigSchema(BaseModel):
    """PT runtime 运行时参数 — .env PAPER_* / QMT_*."""

    model_config = ConfigDict(extra="forbid")

    strategy_id: str = ""
    initial_capital: float = Field(1_000_000.0, gt=0.0)
    qmt_path: str = ""
    qmt_account_id: str = ""


# ---------- Root ----------


class RootConfigSchema(BaseModel):
    """Platform 配置 root — env>yaml>code 合并后产出.

    消费方: PT / Celery Beat / health_check / regression_test
    所有一等公民参数都在这里, 无 extra 字段 (extra=forbid 全链路启用).
    """

    model_config = ConfigDict(extra="forbid")

    strategy: StrategyConfigSchema
    execution: ExecutionConfigSchema = Field(default_factory=ExecutionConfigSchema)
    universe: UniverseConfigSchema = Field(default_factory=UniverseConfigSchema)
    backtest: BacktestConfigSchema = Field(default_factory=BacktestConfigSchema)
    database: DatabaseConfigSchema
    paper_trading: PaperTradingConfigSchema = Field(default_factory=PaperTradingConfigSchema)


# ---------- ConfigSchema wrapper (对接 MVP 1.1 abstract) ----------


class PlatformConfigSchema(ConfigSchema):
    """`backend.platform.config.interface.ConfigSchema` 的 concrete 实现.

    持有 Pydantic RootConfigSchema 类型引用, 提供 `get_schema()` / `validate()`
    对接 MVP 1.1 abstract.
    """

    def __init__(self, root_model: type[BaseModel] = RootConfigSchema) -> None:
        self._root_model = root_model

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """返回 Pydantic 生成的 JSON Schema."""
        return self._root_model.model_json_schema()

    def validate(self, config: dict[str, Any]) -> None:
        """校验给定 config dict 符合 Schema.

        Raises:
          pydantic.ValidationError: 类型 / 值域 / unknown field 违规
        """
        self._root_model.model_validate(config)


__all__ = [
    "StrategyConfigSchema",
    "SlippageConfigSchema",
    "CostConfigSchema",
    "PMSTier",
    "PMSConfigSchema",
    "ExecutionConfigSchema",
    "UniverseConfigSchema",
    "BacktestConfigSchema",
    "DatabaseConfigSchema",
    "PaperTradingConfigSchema",
    "RootConfigSchema",
    "PlatformConfigSchema",
]
