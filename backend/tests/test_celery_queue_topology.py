"""Celery queue topology regression tests.

Runtime audit 2026-05-29 found that a Windows solo worker can be ready yet
starve high-frequency risk/outbox/meta-monitor tasks while it waits on slow
LLM/network ingestion. These tests pin the intended split:

- QuantMind-Celery: core/default queue only.
- QuantMind-CelerySlow: slow data/factor queues.
- Beat slow tasks must not dispatch to the core default queue.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE

REPO_ROOT = Path(__file__).resolve().parents[2]

CORE_QUEUE_ENTRIES = {
    "outbox-publisher-tick",
    "trade-event-risk-consumer-tick",
    "risk-l4-sweep-1min",
    "realtime-risk-tick",
    "risk-l4-broker-stuck-sweep",
    "meta-monitor-tick",
}

SLOW_QUEUE_ENTRIES = {
    "gp-weekly-mining": "factor_calc",
    "embedding-backfill-every-6h": "data_fetch",
    "daily-quality-report": "factor_calc",
    "factor-lifecycle-weekly": "factor_calc",
    "news-ingest-5-source-cadence": "data_fetch",
    "news-ingest-rsshub-cadence": "data_fetch",
    "announcement-ingest-trading-hours": "data_fetch",
    "fundamental-context-daily-1600": "data_fetch",
    "risk-market-regime-0900": "data_fetch",
    "risk-market-regime-1430": "data_fetch",
    "risk-market-regime-1600": "data_fetch",
    "risk-reflector-weekly": "data_fetch",
    "risk-reflector-monthly": "data_fetch",
    "llm-cost-monthly-audit": "data_fetch",
    "slippage-calibration-quarterly": "factor_calc",
    "reports-cleanup-weekly": "data_fetch",
    "daily-attribution-compute": "factor_calc",
    "daily-backup-run": "data_fetch",
    "weekly-backup-verify": "data_fetch",
}


def _queue_for(entry_name: str) -> str:
    return CELERY_BEAT_SCHEDULE[entry_name]["options"]["queue"]


def test_high_frequency_entries_stay_on_core_default_queue() -> None:
    for entry_name in CORE_QUEUE_ENTRIES:
        assert _queue_for(entry_name) == "default", entry_name


def test_slow_entries_do_not_share_core_default_queue() -> None:
    for entry_name, expected_queue in SLOW_QUEUE_ENTRIES.items():
        assert _queue_for(entry_name) == expected_queue, entry_name


def test_core_worker_consumes_default_queue_only() -> None:
    config = json.loads((REPO_ROOT / "config/servy/QuantMind-Celery.json").read_text())

    assert "-Q default" in config["Parameters"]
    assert "-Q default,factor_calc,data_fetch" not in config["Parameters"]
    assert "--without-gossip --without-mingle --without-heartbeat" in config["Parameters"]


def test_slow_worker_consumes_data_and_factor_queues() -> None:
    config = json.loads((REPO_ROOT / "config/servy/QuantMind-CelerySlow.json").read_text())

    assert config["Name"] == "QuantMind-CelerySlow"
    assert "-Q data_fetch,factor_calc" in config["Parameters"]
    assert "--without-gossip --without-mingle --without-heartbeat" in config["Parameters"]
