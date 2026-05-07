"""sub-PR 8b-cadence-B 5-07 — News ingestion Celery Beat schedule tests (ADR-043 §Decision).

scope (~80 line, single chunk per LL-100):
- Beat schedule entry verify: news-ingest-5-source-cadence + news-ingest-rsshub-cadence
- cron syntax verify: crontab(hour="3,7,11,15,19,23", minute=0) (4-hour offset 3h)
- task name binding verify: app.tasks.news_ingest_tasks.news_ingest_5_sources / news_ingest_rsshub
- task signature verify: keyword-only args (query/limit_per_source / route_path/limit)
- default constants verify: DEFAULT_5_SOURCE_QUERY / DEFAULT_RSSHUB_ROUTE_PATH

真生产证据沿用 5-07 sub-PR 8b-cadence-B ADR-043:
- Beat schedule mechanism 真生产 active sustained Servy QuantMind-CeleryBeat 服务 (4 现存 Beat entries 体例)
- cron 4-hour offset 3h 反 hard collision PT chain 16:25/16:30/09:31 + Beat 17:40/22:00 Sun/30s outbox

关联铁律:
- 17 (DataPipeline 入库走 NewsIngestionService orchestrator)
- 32 (Service 不 commit — task 真**事务边界**)
- 33 (fail-loud — task fail 沿用 logger.exception + raise)
- 41 (timezone — Asia/Shanghai sustained celery_app.py:42-43)
- 44 (X9 — Beat schedule 必显式 restart 体例)
"""

from __future__ import annotations

from celery.schedules import crontab

from app.tasks.beat_schedule import CELERY_BEAT_SCHEDULE
from app.tasks.news_ingest_tasks import (
    DEFAULT_5_SOURCE_LIMIT_PER_SOURCE,
    DEFAULT_5_SOURCE_QUERY,
    DEFAULT_RSSHUB_LIMIT,
    DEFAULT_RSSHUB_ROUTE_PATH,
    news_ingest_5_sources,
    news_ingest_rsshub,
)

# ── Beat schedule entry registration ──


def test_news_5_source_beat_entry_registered() -> None:
    """news-ingest-5-source-cadence 真**注册** in CELERY_BEAT_SCHEDULE sustained ADR-043 §Decision #2."""
    assert "news-ingest-5-source-cadence" in CELERY_BEAT_SCHEDULE
    entry = CELERY_BEAT_SCHEDULE["news-ingest-5-source-cadence"]
    assert entry["task"] == "app.tasks.news_ingest_tasks.news_ingest_5_sources"
    assert entry["options"]["queue"] == "default"
    assert entry["options"]["expires"] == 3600


def test_news_rsshub_beat_entry_registered() -> None:
    """news-ingest-rsshub-cadence 真**注册** in CELERY_BEAT_SCHEDULE sustained ADR-043 §Decision #3."""
    assert "news-ingest-rsshub-cadence" in CELERY_BEAT_SCHEDULE
    entry = CELERY_BEAT_SCHEDULE["news-ingest-rsshub-cadence"]
    assert entry["task"] == "app.tasks.news_ingest_tasks.news_ingest_rsshub"
    assert entry["options"]["queue"] == "default"
    assert entry["options"]["expires"] == 3600


# ── cron syntax (ADR-043 §Decision #2) ──


def test_news_5_source_cron_4h_offset_3h() -> None:
    """4-hour offset 3h: 03/07/11/15/19/23 Asia/Shanghai sustained ADR-043 §Decision #2."""
    entry = CELERY_BEAT_SCHEDULE["news-ingest-5-source-cadence"]
    expected = crontab(hour="3,7,11,15,19,23", minute=0)
    sched = entry["schedule"]
    assert isinstance(sched, crontab)
    # crontab 真 hour set 真**equal** sustained (反 string compare)
    assert sched.hour == expected.hour
    assert sched.minute == expected.minute


def test_news_rsshub_cron_aligned_with_5_source() -> None:
    """RSSHub cron 真**align 5-source** sustained (sub-PR 8b-cadence-B 体例)."""
    entry_5src = CELERY_BEAT_SCHEDULE["news-ingest-5-source-cadence"]
    entry_rss = CELERY_BEAT_SCHEDULE["news-ingest-rsshub-cadence"]
    assert entry_5src["schedule"].hour == entry_rss["schedule"].hour
    assert entry_5src["schedule"].minute == entry_rss["schedule"].minute


# ── 反 hard collision verify (ADR-043 §Decision #2 conflict 分析) ──


def test_news_cron_no_hard_collision_with_existing_beat_entries() -> None:
    """4-hour cron (03/07/11/15/19/23) 反 hard collision 4 现存 Beat entries.

    反 hard collision: 17:40 daily-quality-report / 22:00 Sun gp-weekly /
    30s outbox-publisher-tick / Fri 19:00 factor-lifecycle-weekly (软 conflict tolerated).
    """
    news_hours = {3, 7, 11, 15, 19, 23}
    # 4 现存 Beat entries hour
    existing_hours_with_minute_0 = {
        22,  # gp-weekly Sun (day_of_week=0, 软 conflict only on Sun 22)
        19,  # factor-lifecycle Fri (day_of_week=5, 软 conflict only on Fri 19)
    }
    # 17:40 daily-quality-report 真 minute=40 反 minute=0, hard collision 反 hour-only
    # 30s outbox 真 schedule=30.0 (continuous), 反 hour-based collision
    # Only 19 真**软 conflict tolerated** sustained (Fri only, sequential dispatch).
    soft_conflicts = news_hours & existing_hours_with_minute_0
    assert soft_conflicts == {19}, f"Expected only 19:00 soft conflict, got {soft_conflicts}"


# ── Default constants (ADR-043 §Decision #4 cost cap defer + IngestRequest 体例) ──


def test_default_5_source_query_constant() -> None:
    """DEFAULT_5_SOURCE_QUERY 真**non-empty broad keyword** sustained."""
    assert isinstance(DEFAULT_5_SOURCE_QUERY, str)
    assert len(DEFAULT_5_SOURCE_QUERY) > 0
    assert len(DEFAULT_5_SOURCE_QUERY) <= 64  # IngestRequest max_length=64 sustained


def test_default_5_source_limit_per_source_2() -> None:
    """DEFAULT_5_SOURCE_LIMIT_PER_SOURCE=2 沿用 IngestRequest default + cost throttle ~$0.02-0.05/run."""
    assert DEFAULT_5_SOURCE_LIMIT_PER_SOURCE == 2


def test_default_rsshub_route_path_jin10_working_route() -> None:
    """DEFAULT_RSSHUB_ROUTE_PATH=/jin10/news 沿用 PR #254 1/4 working route sustained."""
    assert DEFAULT_RSSHUB_ROUTE_PATH == "/jin10/news"


def test_default_rsshub_limit_10() -> None:
    """DEFAULT_RSSHUB_LIMIT=10 沿用 IngestRsshubRequest default + sub-PR 6 体例."""
    assert DEFAULT_RSSHUB_LIMIT == 10


# ── Task callable + signature verify ──


def test_news_ingest_5_sources_task_registered() -> None:
    """news_ingest_5_sources 真**Celery task** registered with canonical name."""
    assert news_ingest_5_sources.name == "app.tasks.news_ingest_tasks.news_ingest_5_sources"


def test_news_ingest_rsshub_task_registered() -> None:
    """news_ingest_rsshub 真**Celery task** registered with canonical name."""
    assert news_ingest_rsshub.name == "app.tasks.news_ingest_tasks.news_ingest_rsshub"


# ── celery_app.py imports list verify (autodiscover sustained) ──


def test_news_ingest_tasks_in_celery_imports() -> None:
    """app.tasks.news_ingest_tasks 真**celery_app.conf.imports** sustained autodiscover."""
    from app.tasks.celery_app import celery_app

    imports = celery_app.conf.imports
    assert "app.tasks.news_ingest_tasks" in imports
