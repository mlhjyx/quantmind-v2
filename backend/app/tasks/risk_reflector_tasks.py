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

TB-4c scope (lesson loop wired):
  - lesson→risk_memory 闭环 ✅ (V3 §8.3) — RiskReflectorAgent.sediment_lesson:
    BGE-M3 embed lesson text → RiskMemory → persist_risk_memory INSERT.
    embedding 选型 = BGE-M3 local per ADR-064 D2 + ADR-068 D2 (NOT V4-Flash —
    V3 §8.3/§16.2 "V4-Flash embedding" cite is pre-ADR-064 spec drift, 留 TB-5c
    batch doc amend per ADR-022).

V3 PT Cutover Plan v0.4 §A IC-2c scope (2026-05-15 — input de-stub closure):
  - `_build_stub_input` placeholder REMOVED; replaced with `_build_reflection_input`
    that gathers 4 REAL sources (per user 决议 R1 full 4-source wire):
    - events_summary  → risk_event_log GROUP BY (rule_id, severity)
    - plans_summary   → execution_plans GROUP BY (status, user_decision)
                        + cancel-rate calc (user trust calibration signal)
    - pnl_outcome     → trade_log GROUP BY direction (paper-mode only,
                        sustains 红线 — live-mode 0 持仓 anyway)
    - rag_top5        → RiskMemoryRAG.retrieve(query, k=5)
  - Per-source fail-soft sustains reflector_v1.yaml "数据不足, 待下周期"
    empty-data path (transient infra blip → data-light reflection, NOT crash).
  - RAG event_type filter: weekly/monthly = None (broad recall);
    event_reflection = real triggering event_type (e.g. "LimitDown" narrow).

IC-2c remaining (留 IC-2d closure sediment):
  - user reply approve → CC auto PR generate (DingTalk webhook patch) — was
    historically TB-4d candidate; now留 future IC-3 or post-cutover scope.

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

from app.services.risk.risk_reflector_agent import RiskReflectorAgent
from app.tasks.celery_app import celery_app

# Reviewer-fix (PR #345 MEDIUM 1): align imports to `backend.qm_platform.*` —
# risk_reflector_agent.py (the service this task composes) uses
# `backend.qm_platform.*`, and `qm_platform.*` vs `backend.qm_platform.*` are
# distinct module objects (.pth dual root). Consistent root 反 latent
# isinstance-mismatch risk.
from backend.qm_platform.risk.reflector import ReflectionInput, ReflectionOutput

if TYPE_CHECKING:
    from backend.qm_platform.risk.memory.embedding_service import EmbeddingService
    from backend.qm_platform.risk.reflector.agent import _RouterProtocol

logger = logging.getLogger("celery.risk_reflector_tasks")

# risk_memory.event_type for periodic reflections (open vocab per V3 §5.4).
# Reviewer-fix (PR #345 MEDIUM 2): `Reflection:` namespace prefix 反 semantic
# pollution — risk_memory.event_type is shared with real risk events
# (LimitDown/RapidDrop/etc); prefixed reflection types let RAG retrieval callers
# distinguish (TB-3c RiskMemoryRAG default-filters reflections out of L1 push
# augmentation where only real-event memories are relevant). event_reflection
# uses caller-supplied event_type (L1 dispatch passes the REAL triggering event
# type — a reflection ABOUT a LimitDown IS relevant when querying LimitDown).
_EVENT_TYPE_WEEKLY: str = "Reflection:Weekly"
_EVENT_TYPE_MONTHLY: str = "Reflection:Monthly"

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
# IC-2c (2026-05-15) NEW singleton — shares embedding_service with the agent
# (avoids 2x BGE-M3 ~2.5GB model load). Lazy + initialized on first
# reflection task invocation (weekly/monthly cadence).
_rag: Any = None  # RiskMemoryRAG; Any to defer heavy import to first use


def _get_rag() -> Any:
    """Lazy singleton — RiskMemoryRAG sharing embedding_service with RiskReflectorAgent.

    IC-2c (2026-05-15): replaces _build_stub_input's rag placeholder. RAG
    queries risk_memory rows for top-5 similar lessons during reflection input
    composition (V3 §8.1 line 923 rag_top5 field).

    embedding_service is shared via `_get_service()._ensure_embedding_service()`
    so the BGE-M3 ~2.5GB model is loaded ONCE per worker process (sustained
    `_get_service` lazy pattern). conn_factory uses `app.services.db.get_sync_conn`
    — caller owns connection lifecycle (RAG.retrieve opens + caller closes).
    """
    global _rag
    if _rag is None:
        from app.services.db import get_sync_conn  # noqa: PLC0415
        from backend.app.services.risk.risk_memory_rag import RiskMemoryRAG  # noqa: PLC0415

        service = _get_service()
        _rag = RiskMemoryRAG(
            embedding_service=service._ensure_embedding_service(),
            conn_factory=get_sync_conn,
        )
    return _rag


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


def _build_reflection_input(
    period_label: str,
    period_start: datetime,
    period_end: datetime,
    *,
    conn: Any,
    rag: Any,  # RiskMemoryRAG — typed Any to avoid heavy import at module load
    rag_event_type_filter: str | None = None,
) -> ReflectionInput:
    """V3 §8.1 line 923 — gather 4 real input sources for V4-Pro reflection.

    V3 PT Cutover Plan v0.4 §A IC-2c de-stub (2026-05-15, replaces
    `_build_stub_input` placeholder). Per user 决议 (R1) full 4-source wire:
    - events_summary  → risk_event_log GROUP BY (rule_id, severity) period-bounded
    - plans_summary   → execution_plans GROUP BY (status, user_decision) period-bounded
    - pnl_outcome     → trade_log GROUP BY direction period-bounded, paper-mode
    - rag_top5        → RiskMemoryRAG.retrieve(query, k=5)

    Per-source fail-soft sustains _fetch_market_crisis_indicators / _collect_news
    体例 — each gatherer returns "数据不足: {error}" placeholder on exception, so
    a transient infra blip degrades to data-light reflection (V3 §8.1
    reflector_v1.yaml explicitly handles "数据不足, 待下周期" path) rather than
    crashing the weekly/monthly Beat.

    Args:
        period_label: e.g. "2026_W18" (weekly) / "2026_05" (monthly) /
            "event-2026-05-14-LimitDownCluster" (event-triggered).
        period_start: tz-aware inclusive lower bound.
        period_end: tz-aware exclusive upper bound.
        conn: psycopg2 connection (read-only here; caller owns close).
            Used for 3 SQL queries (events / plans / pnl).
        rag: RiskMemoryRAG instance for similar-lesson retrieval.
        rag_event_type_filter: optional event_type filter for RAG (e.g.
            "LimitDown" for event_reflection). None for weekly/monthly (recall
            across all event types).

    Returns:
        ReflectionInput with 4 real string fields (each MAY contain
        "数据不足: ..." prefix on per-source failure — engine + prompt handle
        gracefully).
    """
    events_summary = _gather_events_summary(conn, period_start, period_end)
    plans_summary = _gather_plans_summary(conn, period_start, period_end)
    pnl_outcome = _gather_pnl_outcome(conn, period_start, period_end)

    # RAG query text: period_label + events brief (events_summary already
    # gathered → use first ~200 chars for embedding query context).
    # Reviewer-fix (code-reviewer P2-2, 2026-05-15): guard against
    # "数据不足: ..." placeholder contamination — when events_summary is a
    # fail-soft placeholder (DB query raised), the error message itself would
    # poison the embedding query and return noise hits. Fall back to minimal
    # context (period_label only) so RAG retrieves period-generic memories.
    if events_summary.startswith("数据不足"):
        rag_query = f"{period_label} 风控复盘"
    else:
        rag_query = f"{period_label} 风控复盘: {events_summary[:200]}"
    rag_top5 = _gather_rag_top5(rag, rag_query, event_type=rag_event_type_filter)

    return ReflectionInput(
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        events_summary=events_summary,
        plans_summary=plans_summary,
        pnl_outcome=pnl_outcome,
        rag_top5=rag_top5,
    )


def _gather_events_summary(conn: Any, start: datetime, end: datetime) -> str:
    """Aggregate risk_event_log rows in [start, end) by (rule_id, severity).

    Returns markdown table sorted by count DESC + total row, OR "数据不足"
    placeholder on 0 rows / query failure (fail-soft per-source).

    Period-bounded via `triggered_at` column (TimescaleDB hypertable, 90d
    retention sustained).
    """
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT rule_id, severity, COUNT(*) AS cnt
                FROM risk_event_log
                WHERE triggered_at >= %s AND triggered_at < %s
                GROUP BY rule_id, severity
                ORDER BY cnt DESC, rule_id ASC
                LIMIT 20
                """,
                (start, end),
            )
            rows = cur.fetchall()
        finally:
            cur.close()
    except Exception as e:  # noqa: BLE001 — fail-soft per-source
        logger.warning("[risk-reflector] events_summary gather failed (fail-soft): %s", e)
        return f"数据不足: events_summary 查询失败 ({type(e).__name__}: {e})"

    if not rows:
        return f"数据不足: 0 risk_event_log rows in [{start.date()}, {end.date()})"

    lines = ["| rule_id | severity | count |", "|---|---|---|"]
    total = 0
    for rule_id, severity, count in rows:
        lines.append(f"| {rule_id} | {severity} | {count} |")
        total += int(count)
    lines.append("")
    lines.append(f"Total: {total} events across {len(rows)} (rule, severity) groups")
    return "\n".join(lines)


def _gather_plans_summary(conn: Any, start: datetime, end: datetime) -> str:
    """Aggregate execution_plans rows in [start, end) by (status, user_decision).

    Includes STAGED cancel-rate calculation:
        cancel_rate = CANCELLED / (CANCELLED + CONFIRMED)
    surfaces user trust calibration signal per V3 §8.1.

    Period-bounded via `created_at`.
    """
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT status, COALESCE(user_decision, 'null') AS decision, COUNT(*) AS cnt
                FROM execution_plans
                WHERE created_at >= %s AND created_at < %s
                GROUP BY status, user_decision
                ORDER BY status ASC, decision ASC
                """,
                (start, end),
            )
            rows = cur.fetchall()
        finally:
            cur.close()
    except Exception as e:  # noqa: BLE001 — fail-soft per-source
        logger.warning("[risk-reflector] plans_summary gather failed (fail-soft): %s", e)
        return f"数据不足: plans_summary 查询失败 ({type(e).__name__}: {e})"

    if not rows:
        return f"数据不足: 0 execution_plans rows in [{start.date()}, {end.date()})"

    lines = ["| status | user_decision | count |", "|---|---|---|"]
    for status, decision, count in rows:
        lines.append(f"| {status} | {decision} | {count} |")

    cancelled = sum(int(c) for s, _, c in rows if s == "CANCELLED")
    confirmed = sum(int(c) for s, _, c in rows if s == "CONFIRMED")
    denom = cancelled + confirmed
    if denom > 0:
        lines.append("")
        lines.append(
            f"Cancel rate: {cancelled}/{denom} = {cancelled / denom:.1%} "
            "(user-cancelled vs confirmed)"
        )
    return "\n".join(lines)


def _gather_pnl_outcome(conn: Any, start: datetime, end: datetime) -> str:
    """Aggregate trade_log rows in [start, end) by direction (paper-mode only).

    Period-bounded via `created_at`. Filter `execution_mode='paper'` sustains
    红线 (live-mode 0 持仓 anyway — if live trades appear, reflection over
    paper-only avoids leaking live exposure into the prompt context).
    """
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT direction,
                       COUNT(*) AS cnt,
                       COALESCE(SUM(quantity * fill_price), 0) AS gross,
                       COALESCE(SUM(total_cost), 0) AS total_cost_sum,
                       COALESCE(AVG(slippage_bps), 0) AS avg_slip
                FROM trade_log
                WHERE created_at >= %s AND created_at < %s
                  AND execution_mode = 'paper'
                  AND fill_price IS NOT NULL
                GROUP BY direction
                """,
                (start, end),
            )
            rows = cur.fetchall()
        finally:
            cur.close()
    except Exception as e:  # noqa: BLE001 — fail-soft per-source
        logger.warning("[risk-reflector] pnl_outcome gather failed (fail-soft): %s", e)
        return f"数据不足: pnl_outcome 查询失败 ({type(e).__name__}: {e})"

    if not rows:
        return f"数据不足: 0 paper-mode filled trade_log rows in [{start.date()}, {end.date()})"

    lines = [
        "| direction | count | gross ¥ | total_cost ¥ | avg slippage bps |",
        "|---|---|---|---|---|",
    ]
    for direction, count, gross, total_cost, avg_slip in rows:
        lines.append(
            f"| {direction} | {count} | {float(gross):,.2f} | "
            f"{float(total_cost):,.2f} | {float(avg_slip):.2f} |"
        )
    return "\n".join(lines)


def _gather_rag_top5(rag: Any, query: str, *, event_type: str | None = None) -> str:
    """RiskMemoryRAG.retrieve(query, k=5) → markdown table of top-5 similar lessons.

    Fail-soft per-source: empty hits OR retrieval exception → "数据不足: ..."
    placeholder, sustained 3 SQL gatherer 体例.

    Each row: `(cosine, event_type, symbol_id, lesson_preview)` with lesson
    truncated to 80 chars + pipe-escape for table-safety.
    """
    try:
        hits = rag.retrieve(query, k=5, event_type=event_type)
    except Exception as e:  # noqa: BLE001 — fail-soft per-source
        logger.warning("[risk-reflector] rag_top5 retrieve failed (fail-soft): %s", e)
        return f"数据不足: RAG retrieve 失败 ({type(e).__name__}: {e})"

    if not hits:
        filt = f"event_type={event_type!r}" if event_type else "(no filter)"
        return f"数据不足: RAG returned 0 hits for query {filt}"

    lines = [
        "| cosine | event_type | symbol | lesson |",
        "|---|---|---|---|",
    ]
    for hit in hits:
        m = hit.memory
        lesson_raw = m.lesson or "(no lesson)"
        # Truncate + escape pipes/newlines so the markdown table doesn't break
        lesson_preview = lesson_raw[:80] + ("..." if len(lesson_raw) > 80 else "")
        lesson_preview = lesson_preview.replace("|", "\\|").replace("\n", " ")
        symbol = m.symbol_id or "—"
        lines.append(
            f"| {hit.cosine_similarity:.3f} | {m.event_type} | {symbol} | {lesson_preview} |"
        )
    return "\n".join(lines)


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
    # TB-4d: list each candidate with its candidate_id so user can reply
    # `approve <candidate_id>` / `reject <candidate_id>` via DingTalk webhook.
    # candidate_id = `<period_label>#<global_index>` (1-based, across 5 维 in
    # ReflectionDimension enum order) — sustained _candidate_id_for() in
    # reflection_candidate_service.py.
    if total_candidates > 0:
        lines.append("**改进候选** (回复 `approve <id>` / `reject <id>`):")
        global_idx = 0
        for r in output.reflections:
            for c in r.candidates:
                global_idx += 1
                candidate_id = f"{output.period_label}#{global_idx}"
                lines.append(f"- `{candidate_id}` [{r.dimension.value}] {c}")
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
    # IC-2c (2026-05-15) de-stub: real 4-source gather from risk_event_log /
    # execution_plans / trade_log / RiskMemoryRAG. Per-source fail-soft sustains
    # reflector_v1.yaml "数据不足, 待下周期" empty-data path.
    # 铁律 32: separate conn from sediment conn — input gather conn closes BEFORE
    # the ~30-60s V4-Pro LLM call (反 hold PG conn open during LLM latency
    # anti-pattern). sediment conn opens later for the lesson INSERT.
    from app.services.db import get_sync_conn  # noqa: PLC0415

    rag = _get_rag()
    input_conn = get_sync_conn()
    try:
        input_data = _build_reflection_input(
            period_label,
            period_start,
            period_end,
            conn=input_conn,
            rag=rag,
            # Weekly/monthly use "Reflection:Weekly"/"Reflection:Monthly" meta-type
            # → broad RAG recall (None filter) across all real risk events.
            # event_reflection passes the REAL triggering event type (e.g.
            # "LimitDown") → narrow RAG to same-category memories per V3 §11.4.
            rag_event_type_filter=(None if event_type.startswith("Reflection:") else event_type),
        )
    finally:
        input_conn.close()

    output = service.reflect(input_data, decision_id=decision_id)

    # Write markdown report (V3 §8.2 沉淀).
    _write_reflection_markdown(output, target_path)

    # Push DingTalk 摘要 (V3 §8.2 line 945-957).
    push_result = _push_dingtalk_summary(output, dedup_key=dedup_key, target_path=target_path)

    # TB-4c: lesson→risk_memory 闭环 (V3 §8.3) — BGE-M3 embed + persist.
    # 铁律 32: 本 task is caller / transaction owner — explicit commit/rollback.
    # IC-2c reviewer-fix (python-reviewer P2-2): redundant `from app.services.db
    # import get_sync_conn` removed here — already bound in function scope by
    # the IC-2c input-gather import at line ~666 (CPython caches via sys.modules
    # so the re-import was a no-op, but the duplication was misleading).
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
# V3 §14 mode 14 — retry-once-skip + RISK_REFLECTOR_FAILED 元告警 (HC-2b G5)
# ─────────────────────────────────────────────────────────────

# retry countdown — V4-Pro transient failure (LiteLLM blip / timeout) recovery
# margin. 5min: long enough for a transient LiteLLM provider hiccup to clear,
# short enough that the retry still lands well within the same period.
_REFLECTOR_RETRY_COUNTDOWN_S: int = 300


def _emit_reflector_failure_meta_alert(
    *, cadence_label: str, period_label: str, exc: BaseException
) -> None:
    """Emit RISK_REFLECTOR_FAILED 元告警 via HC-1b channel fallback chain (V3 §14 mode 14).

    Event-emitted rule (NOT polled — 见 meta_alert_interface.MetaAlertRuleId docstring):
    RiskReflector 自身失败时直接构造 MetaAlert + 走 push_triggered (主 DingTalk → 备
    email → 极端 log-P0).

    Fail-soft: 元告警 push 自身失败 **不掩盖** 原 reflection 失败 (caller 仍 raise 原 exc;
    push 失败仅 log). 反 — 一个 notification 失败连带吞掉根因.
    """
    try:
        from app.services.db import get_sync_conn  # noqa: PLC0415
        from app.services.risk.meta_monitor_service import MetaMonitorService  # noqa: PLC0415
        from backend.qm_platform.risk.metrics.meta_alert_interface import (  # noqa: PLC0415
            RULE_SEVERITY,
            MetaAlert,
            MetaAlertRuleId,
        )

        rule_id = MetaAlertRuleId.RISK_REFLECTOR_FAILED
        alert = MetaAlert(
            rule_id=rule_id,
            severity=RULE_SEVERITY[rule_id],
            triggered=True,
            detail=(
                f"L5 RiskReflector {cadence_label} reflection failed after retry "
                f"(period={period_label}) — 跳过本周期, 下一 cadence crontab 自然重跑. "
                f"cause: {type(exc).__name__}: {exc}"
            ),
            observed_at=datetime.now(UTC),
        )
        # push_triggered = HC-1b public API (filters .triggered, runs channel
        # fallback chain per alert). conn owned here — failure path 自管事务.
        conn = get_sync_conn()
        try:
            MetaMonitorService().push_triggered([alert], conn=conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as push_exc:  # noqa: BLE001 — fail-soft: 元告警 push 失败不掩盖原 reflection 失败
        logger.error(
            "[risk-reflector-beat] RISK_REFLECTOR_FAILED 元告警 push itself failed "
            "(原 reflection 失败 caller 仍 raise propagate): %s",
            push_exc,
        )


def _dispatch_with_retry_skip(
    task: Any,
    *,
    cadence_label: str,
    period_label: str,
    period_start: datetime,
    period_end: datetime,
    target_path: Path,
    decision_id: str,
    dedup_key: str,
    event_type: str,
) -> dict[str, Any]:
    """Run _run_reflection with V3 §14 mode 14 retry-once-then-skip semantics.

    失败 → Celery retry 一次 (countdown _REFLECTOR_RETRY_COUNTDOWN_S); 重试仍失败 →
    emit RISK_REFLECTOR_FAILED 元告警 + raise propagate (Celery marks task FAILED →
    "跳过本周期"; 下一 cadence crontab 自然重跑 — NO manual re-dispatch needed).

    Only scheduled cadences (weekly/monthly) use this — event_reflection is L1-event
    dispatched (caller-driven), retry/skip 语义 N/A.

    Args:
        task: the bound Celery task (`self` — needs `request.retries` + `max_retries`
            + `.retry()`).
    """
    try:
        return _run_reflection(
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
            target_path=target_path,
            decision_id=decision_id,
            dedup_key=dedup_key,
            event_type=event_type,
        )
    except Exception as exc:
        if task.request.retries < task.max_retries:
            logger.warning(
                "[risk-reflector-beat] %s reflection failed (attempt %d/%d) — retry in %ds: %s",
                cadence_label,
                task.request.retries + 1,
                task.max_retries + 1,
                _REFLECTOR_RETRY_COUNTDOWN_S,
                exc,
            )
            # self.retry() raises celery.exceptions.Retry — propagates past this
            # `except Exception` handler (raised within it, not re-caught).
            # `from exc` satisfies B904 (semantically correct — retry caused by exc).
            raise task.retry(exc=exc, countdown=_REFLECTOR_RETRY_COUNTDOWN_S) from exc
        # Retries exhausted — emit 元告警 + 跳过本周期 (re-raise → Celery FAILED).
        logger.error(
            "[risk-reflector-beat] %s reflection failed after retry — "
            "emit RISK_REFLECTOR_FAILED 元告警 + skip period %s: %s",
            cadence_label,
            period_label,
            exc,
        )
        _emit_reflector_failure_meta_alert(
            cadence_label=cadence_label, period_label=period_label, exc=exc
        )
        raise


# ─────────────────────────────────────────────────────────────
# Celery tasks — 3 cadence (weekly / monthly / event)
# ─────────────────────────────────────────────────────────────


@celery_app.task(
    bind=True,  # HC-2b G5: needs self.request.retries / max_retries / .retry()
    name="app.tasks.risk_reflector_tasks.weekly_reflection",
    soft_time_limit=90,  # V4-Pro 5 维反思 typically 10-30s, 90s soft margin
    time_limit=180,  # 3min hard kill (反 hung V4-Pro)
    max_retries=1,  # V3 §14 mode 14: 重试一次 (then skip + 元告警)
)
def weekly_reflection(self: Any, decision_id: str | None = None) -> dict[str, Any]:
    """V3 §8.1 周复盘 — Sunday 19:00 Beat `risk-reflector-weekly`.

    Reflects the trailing 7-day period. Writes docs/risk_reflections/YYYY_WW.md.

    V3 §14 mode 14 (HC-2b G5): 失败 → retry 一次 → 仍失败 → emit
    RISK_REFLECTOR_FAILED 元告警 + 跳过本周 (下周 crontab 自然重跑).

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
    return _dispatch_with_retry_skip(
        self,
        cadence_label="weekly",
        period_label=period_label,
        period_start=period_start,
        period_end=period_end,
        target_path=target_path,
        decision_id=decision_id,
        dedup_key=f"risk_reflector:weekly:{period_label}",
        event_type=_EVENT_TYPE_WEEKLY,
    )


@celery_app.task(
    bind=True,  # HC-2b G5: needs self.request.retries / max_retries / .retry()
    name="app.tasks.risk_reflector_tasks.monthly_reflection",
    soft_time_limit=90,
    time_limit=180,
    max_retries=1,  # V3 §14 mode 14: 重试一次 (then skip + 元告警)
)
def monthly_reflection(self: Any, decision_id: str | None = None) -> dict[str, Any]:
    """V3 §8.1 月复盘 — 月 1 日 09:00 Beat `risk-reflector-monthly`.

    Reflects the *previous* full calendar month. Writes
    docs/risk_reflections/YYYY_MM.md.

    V3 §14 mode 14 (HC-2b G5): 失败 → retry 一次 → 仍失败 → emit
    RISK_REFLECTOR_FAILED 元告警 + 跳过本月 (下月 crontab 自然重跑).

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
    return _dispatch_with_retry_skip(
        self,
        cadence_label="monthly",
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
    event_type: str = "Reflection:Event",
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
            Caller (L1 dispatch) supplies the REAL triggering event category
            (e.g. "LimitDown" / "RapidDrop") — a reflection ABOUT a LimitDown
            IS relevant when RAG-querying LimitDown memories, so no prefix.
            Default "Reflection:Event" for manual/generic invocation (prefixed
            namespace per PR #345 MEDIUM 2). Open vocab per V3 §5.4.
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
