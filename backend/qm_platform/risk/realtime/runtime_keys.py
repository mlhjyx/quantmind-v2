"""Runtime infrastructure keys for the L1 RealtimeRiskEngine production runner.

V3 PT Cutover Plan v0.4 §A IC-1c WU-3 SSOT module (extracted per
python-reviewer P2 finding, 2026-05-15) — single declaration of the Redis
key + TTL + Redis stream name shared between:

  - `scripts/realtime_risk_engine_service.py` (writer — IC-1c WU-2)
  - `backend/app/services/risk/meta_monitor_service.py` (reader — IC-1c WU-3)

Previously these were declared in 3 places (runner + meta_monitor + the
_MockRedis test fixture) with no import-enforced SSOT — silent drift risk.
This module is the SINGLE SOURCE OF TRUTH.

关联铁律: 34 (config single source of truth — extends to runtime infra keys)
关联 LL: LL-081 (Redis SETEX zombie protection — TTL > threshold invariant
  documented at CACHE_L1_HEARTBEAT_TTL_SEC)
关联 V3: §13.3 (元告警 alert-on-alert — L1 heartbeat read path consumes
  CACHE_L1_HEARTBEAT)
关联 ADR: ADR-073 D3 (dormant L1 heartbeat alert re-activated via
  CACHE_L1_HEARTBEAT readback)
"""

from __future__ import annotations

from typing import Final

# ── L1 RealtimeRiskEngine heartbeat (cross-process Redis cache) ──

CACHE_L1_HEARTBEAT: Final[str] = "risk:l1_heartbeat"
"""Redis key for L1 RealtimeRiskEngine per-tick heartbeat (SETEX value =
tz-aware ISO 8601 timestamp). Writer: scripts/realtime_risk_engine_service.py
WU-2. Reader: backend/app/services/risk/meta_monitor_service.py
_collect_l1_heartbeat (WU-3). LL-081 SETEX zombie-protection 体例."""

CACHE_L1_HEARTBEAT_TTL_SEC: Final[int] = 3600
"""1h TTL — MUST exceed L1_HEARTBEAT_STALE_THRESHOLD_S (300s in
meta_alert_interface.py) to keep the key alive long enough for the staleness
check to fire (WU-3 Finding #10, 2026-05-15). If TTL == threshold, the Redis
key expires at exactly the moment staleness crosses the alert boundary,
giving the meta_monitor rule a ~zero alert window after a service crash.
With TTL=3600s, the post-crash alert window is 300s..3600s (rule fires) →
3600s+ (key expires → silent again)."""

# ── L1 triggered RuleResult stream (Redis stream consumer hookup) ──

STREAM_RISK_L1_TRIGGERED: Final[str] = "qm:risk:l1_triggered"
"""Redis stream — L1 RealtimeRiskEngine triggered RuleResult publish target.
Consumer (IC-2 scope: signal_service V3 chain / L4ExecutionPlanner) wires
after IC-1c closure. Currently publish-only — no live consumer until IC-2."""


__all__ = [
    "CACHE_L1_HEARTBEAT",
    "CACHE_L1_HEARTBEAT_TTL_SEC",
    "STREAM_RISK_L1_TRIGGERED",
]
