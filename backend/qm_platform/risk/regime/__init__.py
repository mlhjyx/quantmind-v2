"""V3 §5.3 Bull/Bear market regime detection (Tier B, TB-2 sprint chain).

Modules (TB-2 chunked sub-PR roadmap per Plan v0.2 §A):
  - interface (TB-2a, 本 PR): 纯 dataclass + Enum 契约 (0 IO / 0 DB / 0 LiteLLM)
  - repository (TB-2a, 本 PR): persist MarketRegime → market_regime_log via single-row INSERT
    (LL-066 exception to 铁律 17 DataPipeline — 3 daily cadence × 1 row each, not batch)
  - service (TB-2b 留): MarketRegimeService.classify orchestration (Bull/Bear/Judge V4-Pro)
  - agents (TB-2b 留): BullAgent / BearAgent / RegimeJudge wiring LiteLLMRouter
  - prompts (TB-2b 留): prompts/risk/bull_agent_v1.yaml / bear_agent_v1.yaml / regime_judge_v1.yaml
  - scheduler (TB-2c 留): Celery Beat 3 schedule (9:00 / 14:30 / 16:00 Asia/Shanghai)
  - threshold_integration (TB-2d 留): DynamicThresholdEngine extension to consume MarketRegime

Architecture (per V3 §11.2 line 1227 SSOT + ADR-036 V4-Pro mapping sustained):
  - MarketRegimeService location: backend/app/services/risk/ (concrete) — TB-2b 加
  - Engine PURE (本 package): 0 IO, 0 LiteLLM, 0 DB — 仅 dataclass + repository contract
  - Caller (Tier B TB-2b service.py) orchestrates LLM + persist (3-layer pattern sustained)

关联 V3: §5.3 (Bull/Bear regime) / §11.2 (service location) / §16.2 ($50/月 cap)
关联 ADR: ADR-029 / ADR-036 (V4-Pro mapping) / ADR-064 (Plan v0.2 5 决议) / ADR-066 (Tier B context)
关联 铁律: 17 (DataPipeline 入库) / 31 (Engine PURE) / 41 (timezone-aware) / 24 (单一职责)
"""

from __future__ import annotations

from .default_indicators_provider import DefaultIndicatorsProvider
from .interface import (
    MarketIndicators,
    MarketRegime,
    MarketRegimeError,
    RegimeArgument,
    RegimeLabel,
)
from .repository import persist_market_regime

__all__ = [
    "DefaultIndicatorsProvider",
    "MarketIndicators",
    "MarketRegime",
    "MarketRegimeError",
    "RegimeArgument",
    "RegimeLabel",
    "persist_market_regime",
]
