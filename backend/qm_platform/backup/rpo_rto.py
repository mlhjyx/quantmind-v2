"""MVP 4.4 sub-iter 6 (iter 75 batch) — RPO/RTO monitoring.

Recovery Point Objective (max acceptable data loss) + Recovery Time Objective
(max acceptable restore time) measurement + AlertRouter dispatch.

Pure-Python compute on artifact mtime + last-restore duration. Sustains
MVP 4.1 PlatformAlertRouter SDK pattern + 铁律 33 fail-soft 2-tier.

Default thresholds (per QPB v1.16 Framework #12 ROF):
  - RPO: 24h (artifacts must be at most 24h stale)
  - RTO: 4h (last sample restore should complete within 4h)

Platform 严格隔离 sustained.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_RPO_HOURS = 24.0
DEFAULT_RTO_HOURS = 4.0
DEFAULT_SUPPRESS_MINUTES = 60  # 1h dedup for RPO/RTO alerts


@dataclass(frozen=True)
class RpoRtoSnapshot:
    """Single RPO/RTO measurement snapshot (frozen)."""

    rpo_hours_actual: float  # hours since most-recent artifact mtime
    rto_hours_actual: float  # last sample-restore duration (None → 0 if untested)
    rpo_breached: bool
    rto_breached: bool


def measure_rpo_hours(artifact_dir: Path, now_ts: float | None = None) -> float:
    """Compute hours since newest artifact mtime in directory.

    Args:
        artifact_dir: directory containing backup artifacts.
        now_ts: optional current timestamp override (for tests).

    Returns:
        Hours since newest artifact mtime. INF if directory missing or empty
        (denoting "no backups exist" — worst-case RPO breach).
    """
    if not artifact_dir.exists():
        return float("inf")
    candidates = [p for p in artifact_dir.iterdir() if p.is_file()]
    if not candidates:
        return float("inf")
    newest_mtime = max(p.stat().st_mtime for p in candidates)
    now = now_ts if now_ts is not None else time.time()
    return max(0.0, (now - newest_mtime) / 3600.0)


def compute_rpo_rto_snapshot(
    artifact_dir: Path,
    last_restore_duration_seconds: float,
    rpo_threshold_hours: float = DEFAULT_RPO_HOURS,
    rto_threshold_hours: float = DEFAULT_RTO_HOURS,
    now_ts: float | None = None,
) -> RpoRtoSnapshot:
    """Compute current RPO/RTO snapshot (铁律 31 pure compute)."""
    rpo_actual = measure_rpo_hours(artifact_dir, now_ts=now_ts)
    rto_actual = last_restore_duration_seconds / 3600.0
    return RpoRtoSnapshot(
        rpo_hours_actual=rpo_actual,
        rto_hours_actual=rto_actual,
        rpo_breached=rpo_actual > rpo_threshold_hours,
        rto_breached=rto_actual > rto_threshold_hours,
    )


def _fire_via_platform_sdk(
    snapshot: RpoRtoSnapshot,
    rpo_threshold_hours: float,
    rto_threshold_hours: float,
) -> None:
    """Dispatch RPO/RTO breach alert via PlatformAlertRouter.

    Sustains MVP 4.1 batch 3.x SDK pattern. AlertDispatchError propagates;
    caller wraps in fail-soft try/except.
    """
    from datetime import UTC, datetime

    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    today_str = str(datetime.now(UTC).date())
    breach_kind = "rpo" if snapshot.rpo_breached else "rto"
    details: dict[str, str] = {
        "rpo_hours_actual": f"{snapshot.rpo_hours_actual:.2f}",
        "rto_hours_actual": f"{snapshot.rto_hours_actual:.2f}",
        "rpo_threshold_hours": f"{rpo_threshold_hours:.2f}",
        "rto_threshold_hours": f"{rto_threshold_hours:.2f}",
        "rpo_breached": str(snapshot.rpo_breached),
        "rto_breached": str(snapshot.rto_breached),
        "kind": f"backup_{breach_kind}_breach",
    }

    alert = Alert(
        title=f"[P1] Backup {breach_kind.upper()} threshold breached",
        severity=Severity.P1,
        source="qm_platform.backup.rpo_rto",
        details=details,
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    router = get_alert_router()
    dedup_key = f"backup:rpo_rto:{breach_kind}:{today_str}"
    router.fire(alert, dedup_key=dedup_key, suppress_minutes=DEFAULT_SUPPRESS_MINUTES)


def fire_rpo_rto_alert(
    snapshot: RpoRtoSnapshot,
    rpo_threshold_hours: float = DEFAULT_RPO_HOURS,
    rto_threshold_hours: float = DEFAULT_RTO_HOURS,
) -> bool:
    """Fire alert if snapshot breaches RPO or RTO threshold.

    沿用 MVP 4.2 fire_residual_alert 体例 — 铁律 33 fail-soft 2-tier (catch
    AlertDispatchError + generic Exception, return False).

    Returns:
        True if alert fired successfully, False otherwise (below threshold /
        dispatch fail / suppress).
    """
    if not snapshot.rpo_breached and not snapshot.rto_breached:
        return False  # silent_ok: expected normal path (no breach)

    logger = logging.getLogger(__name__)
    try:
        _fire_via_platform_sdk(snapshot, rpo_threshold_hours, rto_threshold_hours)
        return True
    except Exception as e:  # noqa: BLE001 — 铁律 33 fail-soft tier-2
        try:
            from qm_platform.observability import AlertDispatchError

            if isinstance(e, AlertDispatchError):
                logger.error("[RpoRto] AlertDispatchError: %s (fail-soft)", e)
                return False
        except ImportError:
            pass
        logger.error("[RpoRto] alert dispatch failed (fail-soft): %s", e, exc_info=True)
        return False


__all__ = [
    "DEFAULT_RPO_HOURS",
    "DEFAULT_RTO_HOURS",
    "DEFAULT_SUPPRESS_MINUTES",
    "RpoRtoSnapshot",
    "compute_rpo_rto_snapshot",
    "fire_rpo_rto_alert",
    "measure_rpo_hours",
]
