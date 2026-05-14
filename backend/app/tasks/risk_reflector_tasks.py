"""V3 §8 RiskReflector Celery Beat tasks — TB-4b sub-PR (3 cadence wire).

V3 §8.1 line 918-921 cadence:
  - 每周日 19:00 (周复盘) → weekly_reflection — Beat `risk-reflector-weekly`
  - 每月 1 日 09:00 (月复盘) → monthly_reflection — Beat `risk-reflector-monthly`
  - 重大事件后 24h → event_reflection — L1 event dispatch (NO Beat schedule)

Task body (V3 §8.1-8.2):
  1. Gather ReflectionInput — TB-4b: stub gatherer (placeholder summaries);
     TB-4c will wire real risk_event_log + execution_plans + trade_log + RAG.
  2. RiskReflectorAgent.reflect(input) → V4-Pro 5 维反思 → ReflectionOutput
  3. Render markdown report → write docs/risk_reflections/{YYYY_WW.md |
     YYYY_MM.md | event/YYYY-MM-DD_<slug>.md} (V3 §8.2 line 939-942)
  4. Render DingTalk 摘要 → push via send_with_dedup (V3 §8.2 line 945-957)

3-layer pattern sustained (反 hidden coupling, sustained TB-2c market_regime_tasks):
  - qm_platform/risk/reflector/ = Engine PURE side (interface + agent)
  - app/services/risk/risk_reflector_agent.py = Application orchestration
  - 本 module = Beat schedule dispatch + markdown sediment + DingTalk push

Beat schedule per V3 §8.1 (beat_schedule.py amend):
  - "risk-reflector-weekly"  — crontab(hour=19, minute=0, day_of_week='0')  # Sunday
  - "risk-reflector-monthly" — crontab(hour=9, minute=0, day_of_month='1')
  - event_reflection has NO Beat entry — dispatched by L1 event detection
    (TB-4c+ wire) since trigger is data-driven not time-driven.

Schedule collision risk (反 hard collision, sustained TB-2c 体例):
  - Sunday 19:00 — collides with `news-ingest-5-source-cadence` +
    `news-ingest-rsshub-cadence` (both crontab `hour="3,7,11,15,19,23"` fire
    every day at 19:00 incl Sunday). Beat sequential dispatch + `--pool=solo`
    tolerates (independent tasks, ~5-10s combined queue). `factor-lifecycle-weekly`
    is Friday 19:00 (NO overlap), `gp-weekly-mining` is Sunday 22:00 (NO overlap).
  - 月 1 日 09:00 — may collide with `risk-market-regime-0900` if 月 1 日 is a
    weekday. Beat sequential dispatch + `--pool=solo` Windows tolerates
    sub-second queue (independent V4-Pro tasks, ~3-5s combined). Acceptable.

TB-4c scope (本 PR — lesson loop wired):
  - lesson→risk_memory 闭环 ✅ (V3 §8.3) — RiskReflectorAgent.sediment_lesson:
    BGE-M3 embed lesson text → RiskMemory → persist_risk_memory INSERT.
    embedding 选型 = BGE-M3 local per ADR-064 D2 + ADR-068 D2 (NOT V4-Flash —
    V3 §8.3/§16.2 "V4-Flash embedding" cite is pre-ADR-064 spec drift, 留 TB-5c
    batch doc amend per ADR-022).
TB-4c scope boundary (留 TB-4d):
  - Input gathering still stub placeholder (TB-4d wires real risk_event_log /
    execution_plans / trade_log / RiskMemoryRAG queries)
  - user reply approve → CC auto PR generate = 留 TB-4d (DingTalk webhook patch)

铁律 22 sustained: doc 跟随代码 — beat_schedule.py amend + runbook + README same PR.
铁律 31 sustained: qm_platform/risk/reflector + memory engine PURE; 本 task = Application dispatch.
铁律 32 sustained: TB-4c risk_memory INSERT — 本 task is caller / transaction owner
  (explicit conn.commit + rollback). sediment_lesson takes caller-injected conn,
  does NOT commit. `send_with_dedup` DingTalk helper writes alert_dedup metadata
  (helper-internal).
铁律 17 sustained: risk_memory INSERT 走 persist_risk_memory single-row (LL-066
  subset 例外 — small per-reflection sediment, not batch).
铁律 33 sustained: fail-loud — ReflectorAgentError / file IO error propagate per Celery retry.
铁律 41 sustained: Asia/Shanghai timezone via celery_app.py + tz-aware datetime throughout.
铁律 44 X9 sustained: post-merge ops `Servy restart QuantMind-CeleryBeat AND QuantMind-Celery`
  per docs/runbook/cc_automation/v3_tb_4b_reflector_beat_wire.md (LL-141 4-step sediment).

关联文档:
- docs/adr/ADR-064 (Plan v0.2 D2 Tier B cadence sustained)
- docs/adr/ADR-069 候选 (TB-4 closure cumulative)
- backend/qm_platform/risk/reflector/agent.py (ReflectorAgent V4-Pro wrapper)
- backend/app/services/risk/risk_reflector_agent.py (RiskReflectorAgent orchestration)
- backend/app/services/dingtalk_alert.py (send_with_dedup outbound push)
- backend/app/tasks/beat_schedule.py (2 Beat entries — weekly + monthly)
- docs/risk_reflections/README.md (沉淀 dir 体例)
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from qm_platform.risk.reflector import ReflectionInput, ReflectionOutput

from app.services.risk.risk_reflector_agent import RiskReflectorAgent
from app.tasks.celery_app import celery_app

if TYPE_CHECKING:
    from qm_platform.risk.memory.embedding_service import EmbeddingService
    from qm_platform.risk.reflector.agent import _RouterProtocol

logger = logging.getLogger("celery.risk_reflector_tasks")

# risk_memory.event_type for periodic reflections (open vocab per V3 §5.4).
# event_reflection uses caller-supplied event_type (the triggering event).
_EVENT_TYPE_WEEKLY: str = "WeeklyReflection"
_EVENT_TYPE_MONTHLY: str = "MonthlyReflection"

# ─────────────────────────────────────────────────────────────
# 常量 (V3 §8.2 沉淀 dir + repo root resolution)
# ─────────────────────────────────────────────────────────────

# Repo root resolution — backend/app/tasks/risk_reflector_tasks.py.
# parents[0]=tasks, [1]=app, [2]=backend, [3]=repo_root.
_REPO_ROOT: Path = Path(__file__).resolve().parents[3]
REFLECTIONS_DIR: Path = _REPO_ROOT / "docs" / "risk_reflections"
"""V3 §8.2 line 939-942 沉淀 dir — markdown report write target."""

# DingTalk push 摘要 hard cap (反 DingTalk ~5KB markdown body limit per
# V3 §8.2 — full report 走 repo 沉淀, 摘要 short).
_DINGTALK_SUMMARY_MAX_CHARS: int = 3000


# ─────────────────────────────────────────────────────────────
# Module-level lazy singleton (sustained TB-2c market_regime_tasks 体例)
# ─────────────────────────────────────────────────────────────

_service: RiskReflectorAgent | None = None


def _get_service() -> RiskReflectorAgent:
    """Lazy singleton — RiskReflectorAgent with shared LiteLLMRouter + BGE-M3 factory.

    Sustained TB-2c market_regime_tasks._get_service 体例 — router + embedding
    service init is non-trivial (BGE-M3 ~2.5GB model load), reuse across Beat
    invocations. TB-4c: embedding_factory wired for lesson→risk_memory 闭环.
    """
    global _service
    if _service is None:

        def _router_factory() -> _RouterProtocol:
            from backend.qm_platform.llm import get_llm_router  # noqa: PLC0415

            return get_llm_router()

        def _embedding_factory() -> EmbeddingService:
            # BGE-M3 local embedding (ADR-064 D2 + ADR-068 D2 sustained, NOT
            # V4-Flash — pre-ADR-064 V3 §8.3/§16.2 spec drift). Default
            # cache_folder resolves to repo-rooted ./models/bge-m3 (TB-3b 体例).
            from backend.qm_platform.risk.memory.embedding_service import (  # noqa: PLC0415
                BGEM3EmbeddingService,
            )

            return BGEM3EmbeddingService()

        _service = RiskReflectorAgent(
            router_factory=_router_factory,
            embedding_factory=_embedding_factory,
        )
    return _service


# ─────────────────────────────────────────────────────────────
# Period bounds + stub input gathering (TB-4c replaces stub with real DB)
# ─────────────────────────────────────────────────────────────


def _build_stub_input(
    period_label: str,
    period_start: datetime,
    period_end: datetime,
) -> ReflectionInput:
    """TB-4b placeholder ReflectionInput — TB-4c wires real DB gathering.

    Sustained TB-2c StubIndicatorsProvider 体例 — stub returns clearly-marked
    placeholder summaries so the cadence + push + sediment wire can be tested
    end-to-end before TB-4c real input gathering.

    The reflector_v1.yaml prompt explicitly handles the empty-data path
    ("数据不足, 待下周期") so V4-Pro reflection over stub input produces a
    valid (if data-light) ReflectionOutput.
    """
    placeholder = (
        "[TB-4b stub — TB-4c will gather from risk_event_log / execution_plans / "
        "trade_log / RiskMemoryRAG]"
    )
    return ReflectionInput(
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        events_summary=placeholder,
        plans_summary=placeholder,
        pnl_outcome=placeholder,
        rag_top5=placeholder,
    )


def _weekly_bounds(now: datetime) -> tuple[str, datetime, datetime]:
    """Compute weekly reflection period bounds — last 7 days ending at `now`.

    Returns (period_label, period_start, period_end). period_label uses ISO
    week format YYYY_WW (V3 §8.2 line 940).
    """
    period_end = now
    period_start = now - timedelta(days=7)
    iso_year, iso_week, _ = now.isocalendar()
    period_label = f"{iso_year}_W{iso_week:02d}"
    return period_label, period_start, period_end


def _monthly_bounds(now: datetime) -> tuple[str, datetime, datetime]:
    """Compute monthly reflection period bounds — previous calendar month.

    Fired on month 1st 09:00 → reflects the *previous* full month.
    Returns (period_label, period_start, period_end). period_label YYYY_MM.
    """
    # period_end = first day of current month at 00:00 (exclusive upper bound).
    period_end = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # period_start = first day of previous month.
    if period_end.month == 1:
        period_start = period_end.replace(year=period_end.year - 1, month=12)
    else:
        period_start = period_end.replace(month=period_end.month - 1)
    period_label = f"{period_start.year}_{period_start.month:02d}"
    return period_label, period_start, period_end


# ─────────────────────────────────────────────────────────────
# Markdown rendering + DingTalk 摘要 + file write
# ─────────────────────────────────────────────────────────────


def _render_reflection_markdown(output: ReflectionOutput) -> str:
    """Render ReflectionOutput → full markdown report (V3 §8.2 沉淀 format)."""
    lines: list[str] = [
        f"# RiskReflector 反思报告 — {output.period_label}",
        "",
        f"**生成时间**: {output.generated_at.isoformat()}",
        "",
        "## 综合摘要",
        "",
        output.overall_summary,
        "",
    ]
    # 5 维 sections in enum declaration order.
    for r in output.reflections:
        lines.append(f"## {r.dimension.value.capitalize()}")
        lines.append("")
        lines.append(r.summary)
        lines.append("")
        if r.findings:
            lines.append("**发现**:")
            lines.extend(f"- {f}" for f in r.findings)
            lines.append("")
        if r.candidates:
            lines.append("**改进候选**:")
            lines.extend(f"- {c}" for c in r.candidates)
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(
        "_本报告由 RiskReflector V4-Pro 自动生成 (V3 §8 L5 反思闭环层). "
        "参数候选需 user 显式 approve, 反 silent .env mutation (ADR-022 sustained)._"
    )
    lines.append("")
    return "\n".join(lines)


def _render_dingtalk_summary(output: ReflectionOutput, target_path: Path) -> str:
    """Render ReflectionOutput → DingTalk markdown 摘要 (short, ≤ 3000 chars).

    V3 §8.2 line 945-957 体例 — overall_summary + per-dim candidates count +
    完整 report 走 repo 沉淀 (本摘要不含全文).

    Reviewer-fix (PR #344 LOW 1): report link uses actual target_path (relative
    to repo root) instead of computed `period_label`.md — event reflections
    write to event/ subdir so period_label != filename path.
    """
    total_findings = sum(len(r.findings) for r in output.reflections)
    total_candidates = sum(len(r.candidates) for r in output.reflections)
    lines: list[str] = [
        f"### 📊 RiskReflector 反思 {output.period_label}",
        "",
        output.overall_summary,
        "",
        f"**发现**: {total_findings} 项 / **改进候选**: {total_candidates} 项",
        "",
    ]
    # Per-dim candidates count brief.
    for r in output.reflections:
        if r.candidates:
            lines.append(
                f"- {r.dimension.value.capitalize()}: {len(r.candidates)} 候选"
            )
    lines.append("")
    # Accurate report link — relative to repo root (handles event/ subdir).
    try:
        rel_path = target_path.relative_to(_REPO_ROOT)
    except ValueError:
        # target_path outside repo (e.g. test tmp_path) — fall back to name.
        rel_path = target_path.name
    lines.append(f"完整报告: {rel_path}")
    summary = "\n".join(lines)
    # Hard cap — truncate (反 DingTalk ~5KB body limit per V3 §8.2).
    if len(summary) > _DINGTALK_SUMMARY_MAX_CHARS:
        summary = summary[: _DINGTALK_SUMMARY_MAX_CHARS - 20] + "\n... (截断, 见完整报告)"
    return summary


def _slugify_event(event_summary: str) -> str:
    """Slugify event_summary for event/ filename (lowercase + non-alnum → _).

    V3 §8.2 line 942: event/YYYY-MM-DD_<event_summary>.md
    """
    slug = re.sub(r"[^\w一-鿿]+", "_", event_summary.strip().lower())
    slug = slug.strip("_")
    # Cap length — filename safety.
    return slug[:60] if slug else "event"


def _write_reflection_markdown(output: ReflectionOutput, target_path: Path) -> None:
    """Write rendered markdown to target_path (creates parent dir if needed).

    铁律 33 fail-loud — file IO error propagates (Celery retry per task policy).
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    content = _render_reflection_markdown(output)
    target_path.write_text(content, encoding="utf-8")
    logger.info(
        "[risk-reflector-beat] markdown report written: %s (%d chars)",
        target_path,
        len(content),
    )


def _push_dingtalk_summary(
    output: ReflectionOutput, *, dedup_key: str, target_path: Path
) -> dict[str, Any]:
    """Push DingTalk 摘要 via send_with_dedup (双锁 + alert_dedup 去重).

    DINGTALK_ALERTS_ENABLED default-off — paper-mode 0 真 push unless explicitly
    enabled. Returns send_with_dedup result dict.

    Note: send_with_dedup writes alert_dedup dedup metadata (helper-internal,
    not domain DB write per 铁律 32 — TB-4b task itself is 0 domain DB write).

    铁律 33 fail-loud — httpx error propagates if alerts enabled + push fails.
    """
    from app.services.dingtalk_alert import send_with_dedup  # noqa: PLC0415

    body = _render_dingtalk_summary(output, target_path)
    return send_with_dedup(
        dedup_key=dedup_key,
        severity="info",
        source="risk_reflector",
        title=f"RiskReflector 反思 {output.period_label}",
        body=body,
    )


# ─────────────────────────────────────────────────────────────
# Shared task body (gather → reflect → sediment → push)
# ─────────────────────────────────────────────────────────────


def _run_reflection(
    *,
    period_label: str,
    period_start: datetime,
    period_end: datetime,
    target_path: Path,
    decision_id: str,
    dedup_key: str,
    event_type: str,
    symbol_id: str | None = None,
) -> dict[str, Any]:
    """Shared reflection task body — gather stub input → reflect → sediment → push.

    TB-4b flow: gather → reflect → markdown write → DingTalk push.
    TB-4c (本 PR) adds: → lesson→risk_memory 闭环 (V3 §8.3) as the final step.

    Args:
        event_type: risk_memory.event_type for the lesson sediment (TB-4c).
            Weekly/monthly use period-category constants; event_reflection
            uses caller-supplied triggering event type.
        symbol_id: optional stock code for the lesson sediment (None for
            market-wide weekly/monthly reflections).

    Returns task result dict. Raises ReflectorAgentError / file IO error /
    httpx error / RiskMemoryError / psycopg2.Error per 铁律 33 fail-loud
    (Celery retry).

    TB-4c retry-double-insert minor risk (documented, 留 TB-5 dedup if needed):
        If sediment commits but Celery retries the whole task (e.g. worker
        loss mid-result-ack), a duplicate risk_memory row could be inserted.
        Low-impact — RAG retrieval tolerates near-duplicates (returns 2 similar
        hits). risk_memory has no natural key for reflections; dedup guard
        deferred to TB-5 if production retry frequency warrants it.
    """
    logger.info(
        "[risk-reflector-beat] reflection start: period=%s event_type=%s decision_id=%s",
        period_label,
        event_type,
        decision_id,
    )

    service = _get_service()
    # TB-4b: stub input (TB-4d wires real DB gathering — risk_event_log /
    # execution_plans / trade_log / RiskMemoryRAG).
    input_data = _build_stub_input(period_label, period_start, period_end)
    output = service.reflect(input_data, decision_id=decision_id)

    # Write markdown report (V3 §8.2 沉淀).
    _write_reflection_markdown(output, target_path)

    # Push DingTalk 摘要 (V3 §8.2 line 945-957).
    push_result = _push_dingtalk_summary(
        output, dedup_key=dedup_key, target_path=target_path
    )

    # TB-4c: lesson→risk_memory 闭环 (V3 §8.3) — BGE-M3 embed + persist.
    # 铁律 32: 本 task is caller / transaction owner — explicit commit/rollback.
    from app.services.db import get_sync_conn  # noqa: PLC0415

    conn = get_sync_conn()
    try:
        memory_id = service.sediment_lesson(
            output,
            conn,
            event_type=event_type,
            symbol_id=symbol_id,
            event_timestamp=period_end,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    total_candidates = sum(len(r.candidates) for r in output.reflections)
    result: dict[str, Any] = {
        "ok": True,
        "period_label": period_label,
        "decision_id": decision_id,
        "report_path": str(target_path),
        "total_candidates": total_candidates,
        "memory_id": memory_id,
        "dingtalk_sent": push_result.get("sent", False),
        "dingtalk_reason": push_result.get("reason", "unknown"),
    }
    logger.info(
        "[risk-reflector-beat] reflection complete: period=%s candidates=%d "
        "memory_id=%d dingtalk_sent=%s decision_id=%s",
        period_label,
        total_candidates,
        memory_id,
        push_result.get("sent", False),
        decision_id,
    )
    return result


# ─────────────────────────────────────────────────────────────
# Celery tasks — 3 cadence (weekly / monthly / event)
# ─────────────────────────────────────────────────────────────


@celery_app.task(
    name="app.tasks.risk_reflector_tasks.weekly_reflection",
    soft_time_limit=90,  # V4-Pro 5 维反思 typically 10-30s, 90s soft margin
    time_limit=180,  # 3min hard kill (反 hung V4-Pro)
)
def weekly_reflection(decision_id: str | None = None) -> dict[str, Any]:
    """V3 §8.1 周复盘 — Sunday 19:00 Beat `risk-reflector-weekly`.

    Reflects the trailing 7-day period. Writes docs/risk_reflections/YYYY_WW.md.

    Args:
        decision_id: optional caller-traceable ID. Auto-generated if None.

    Returns:
        Task result dict (ok / period_label / report_path / total_candidates /
        dingtalk_sent / dingtalk_reason).
    """
    now = datetime.now(UTC)
    period_label, period_start, period_end = _weekly_bounds(now)
    if decision_id is None:
        decision_id = f"reflector-weekly-{now.isoformat(timespec='seconds')}"
    target_path = REFLECTIONS_DIR / f"{period_label}.md"
    return _run_reflection(
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        target_path=target_path,
        decision_id=decision_id,
        dedup_key=f"risk_reflector:weekly:{period_label}",
        event_type=_EVENT_TYPE_WEEKLY,
    )


@celery_app.task(
    name="app.tasks.risk_reflector_tasks.monthly_reflection",
    soft_time_limit=90,
    time_limit=180,
)
def monthly_reflection(decision_id: str | None = None) -> dict[str, Any]:
    """V3 §8.1 月复盘 — 月 1 日 09:00 Beat `risk-reflector-monthly`.

    Reflects the *previous* full calendar month. Writes
    docs/risk_reflections/YYYY_MM.md.

    Args:
        decision_id: optional caller-traceable ID. Auto-generated if None.

    Returns:
        Task result dict.
    """
    now = datetime.now(UTC)
    period_label, period_start, period_end = _monthly_bounds(now)
    if decision_id is None:
        decision_id = f"reflector-monthly-{now.isoformat(timespec='seconds')}"
    target_path = REFLECTIONS_DIR / f"{period_label}.md"
    return _run_reflection(
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        target_path=target_path,
        decision_id=decision_id,
        dedup_key=f"risk_reflector:monthly:{period_label}",
        event_type=_EVENT_TYPE_MONTHLY,
    )


@celery_app.task(
    name="app.tasks.risk_reflector_tasks.event_reflection",
    soft_time_limit=90,
    time_limit=180,
)
def event_reflection(
    event_summary: str,
    event_type: str = "EventReflection",
    symbol_id: str | None = None,
    event_window_hours: int = 24,
    decision_id: str | None = None,
) -> dict[str, Any]:
    """V3 §8.1 重大事件后反思 — event-triggered (NO Beat schedule).

    Dispatched by L1 event detection (TB-4d+ wire) when V3 §8.1 line 921
    triggers fire: 单日 portfolio < -5% / N 股同时跌停 / STAGED cancel 率异常.

    Args:
        event_summary: short event description (slugified into filename +
            used as period_label suffix). Required, non-empty.
        event_type: risk_memory.event_type for the lesson sediment (TB-4c).
            Caller (L1 dispatch) supplies the triggering event category
            (e.g. "LimitDown" / "RapidDrop"). Default "EventReflection" for
            manual/generic invocation. Open vocab per V3 §5.4.
        symbol_id: optional stock code if the event is symbol-specific
            (None for market-wide events — CorrelatedDrop / regime shift).
        event_window_hours: lookback window in hours (default 24h per V3 §8.1).
        decision_id: optional caller-traceable ID. Auto-generated if None.

    Returns:
        Task result dict. report_path = docs/risk_reflections/event/YYYY-MM-DD_<slug>.md.

    Raises:
        ValueError: event_summary empty.
    """
    if not event_summary or not event_summary.strip():
        raise ValueError("event_reflection: event_summary must be non-empty")

    now = datetime.now(UTC)
    period_end = now
    period_start = now - timedelta(hours=event_window_hours)
    date_str = now.strftime("%Y-%m-%d")
    slug = _slugify_event(event_summary)
    period_label = f"event-{date_str}-{slug}"
    if decision_id is None:
        decision_id = f"reflector-event-{now.isoformat(timespec='seconds')}"
    target_path = REFLECTIONS_DIR / "event" / f"{date_str}_{slug}.md"
    return _run_reflection(
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        target_path=target_path,
        decision_id=decision_id,
        dedup_key=f"risk_reflector:event:{date_str}:{slug}",
        event_type=event_type,
        symbol_id=symbol_id,
    )
