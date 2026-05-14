"""V3 §8.3 RiskReflector candidate approve/reject service — TB-4d sprint.

Per V3 §8.3 line 965-968: reflection 参数候选 → user reply approve/reject →
sediment to docs/research-kb/risk_findings/. The sedimented "approved" records
are later turned into a PR by scripts/generate_risk_candidate_pr.py (explicit
human/CC trigger — NOT this service, NOT a Beat, NOT the webhook hot path).

Safety design (PR #345 plan — option B "Webhook sediment + scripts/ PR 生成器"):
  - 本 service = pure sediment: 0 git / 0 .env / 0 broker / 0 DB. Only file IO
    (read source report markdown + write risk_findings/ candidate record).
  - scripts/generate_risk_candidate_pr.py = the ONLY git-touching component,
    explicitly triggered, branch+commit+push (NEVER merge — user 显式 merge).
  - candidate proposals → PR diff for user review (sustained ADR-022 反 silent
    .env mutation). Webhook NEVER mutates production config.

Flow:
  1. DingTalkWebhookReceiver inbound → webhook_parser.parse_candidate_command
     → ParsedCandidateWebhook(command, candidate_id).
  2. 本 service.process_candidate_command(parsed):
     a. Parse candidate_id `<period_label>#<index>` → period_label + index.
     b. Locate source report (weekly/monthly = <dir>/<label>.md; event =
        <dir>/event/<date>_<slug>.md).
     c. Extract candidate text by global index from the report's 改进候选 blocks.
     d. Write docs/research-kb/risk_findings/<date>_<slug>_<status>.md with
        frontmatter {candidate_id, status, source_report, candidate_text, decided_at}.
  3. CandidateOutcome returned to API layer → HTTP 200 idempotent response.

铁律 31: Application layer (file IO orchestration) — composes pure parser
  (webhook_parser) + file sediment. NOT Engine PURE (does file IO).
铁律 33: fail-loud — report-not-found / candidate-index-out-of-range raise
  ReflectionCandidateError (caller maps to HTTP 4xx idempotent body).

关联 V3: §8.3 line 965-972 (参数候选 + 候选规则新增 闭环)
关联 ADR: ADR-022 (反 silent .env mutation) / ADR-057 (S8 webhook receiver 体例) /
  ADR-069 候选 (TB-4 closure)
关联 铁律: 22 / 24 / 31 (Application) / 33 (fail-loud) / 41 (tz-aware)
关联 LL: LL-098 X10 / LL-151 (S8 webhook 体例) / LL-163 候选 (TB-4 closure)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.qm_platform.risk.execution.webhook_parser import (
        ParsedCandidateWebhook,
    )

logger = logging.getLogger(__name__)

# Repo root resolution — backend/app/services/risk/reflection_candidate_service.py.
# parents[0]=risk, [1]=services, [2]=app, [3]=backend, [4]=repo_root.
_REPO_ROOT: Path = Path(__file__).resolve().parents[4]
_DEFAULT_REFLECTIONS_DIR: Path = _REPO_ROOT / "docs" / "risk_reflections"
_DEFAULT_RISK_FINDINGS_DIR: Path = _REPO_ROOT / "docs" / "research-kb" / "risk_findings"

# Markdown report 改进候选 block — _render_reflection_markdown writes
# "**改进候选**:" header then "- {candidate}" lines (TB-4b 体例).
_CANDIDATE_BLOCK_HEADER: str = "**改进候选**:"
_CANDIDATE_LINE_RE = re.compile(r"^- (?P<text>.+)$")

# event period_label format: `event-<YYYY-MM-DD>-<slug>` (risk_reflector_tasks
# event_reflection 体例: period_label = f"event-{date_str}-{slug}").
_EVENT_LABEL_RE = re.compile(r"^event-(?P<date>\d{4}-\d{2}-\d{2})-(?P<slug>.+)$")


class CandidateOutcome(StrEnum):
    """Service-layer result of candidate command processing."""

    APPROVED_SEDIMENTED = "approved_sedimented"
    REJECTED_SEDIMENTED = "rejected_sedimented"
    ALREADY_DECIDED = "already_decided"  # idempotent re-reply


class ReflectionCandidateError(RuntimeError):
    """candidate_id resolution / report read / candidate extraction failure.

    Caller (API layer) maps to HTTP 4xx with idempotent body (反 DingTalk
    webhook auto-retry storm on non-2xx — sustained S8 8b 体例).
    """


@dataclass(frozen=True)
class CandidateDecisionResult:
    """Service result returned to API layer."""

    outcome: CandidateOutcome
    candidate_id: str
    sediment_path: str | None  # risk_findings/ markdown path (None if ALREADY_DECIDED)


def _parse_candidate_id(candidate_id: str) -> tuple[str, int]:
    """Split `<period_label>#<index>` → (period_label, index).

    Raises:
        ReflectionCandidateError: malformed candidate_id (defensive — parser
            already validated, but service re-checks per fail-loud 铁律 33).
    """
    if "#" not in candidate_id:
        raise ReflectionCandidateError(
            f"candidate_id {candidate_id!r} missing '#' separator"
        )
    period_label, _, index_raw = candidate_id.rpartition("#")
    if not period_label:
        raise ReflectionCandidateError(
            f"candidate_id {candidate_id!r} has empty period_label"
        )
    try:
        index = int(index_raw)
    except ValueError as exc:
        raise ReflectionCandidateError(
            f"candidate_id {candidate_id!r} index {index_raw!r} not an integer"
        ) from exc
    if index < 1:
        raise ReflectionCandidateError(
            f"candidate_id {candidate_id!r} index {index} must be ≥ 1 (1-based)"
        )
    return period_label, index


def _resolve_report_path(period_label: str, reflections_dir: Path) -> Path:
    """Map period_label → source report markdown path.

    weekly/monthly: <reflections_dir>/<period_label>.md
    event: <reflections_dir>/event/<date>_<slug>.md (period_label =
      `event-<YYYY-MM-DD>-<slug>` per risk_reflector_tasks.event_reflection).

    Raises:
        ReflectionCandidateError: report file not found at resolved path.
    """
    event_match = _EVENT_LABEL_RE.match(period_label)
    if event_match:
        date_str = event_match.group("date")
        slug = event_match.group("slug")
        report_path = reflections_dir / "event" / f"{date_str}_{slug}.md"
    else:
        report_path = reflections_dir / f"{period_label}.md"

    if not report_path.is_file():
        raise ReflectionCandidateError(
            f"source report not found for period_label {period_label!r} "
            f"at {report_path} — reflection report must exist before candidate "
            f"approve/reject (TB-4b sediment prerequisite)"
        )
    return report_path


def _extract_candidate_text(report_path: Path, index: int) -> str:
    """Extract the index-th candidate (1-based, global across 5 维) from report.

    _render_reflection_markdown writes per-dimension '**改进候选**:' blocks with
    '- {candidate}' lines, in ReflectionDimension enum order. The global index
    counts candidates across all dimension blocks in document order — which
    matches _render_dingtalk_summary's candidate_id assignment exactly.

    Raises:
        ReflectionCandidateError: index out of range (report has < index
            candidates) OR report markdown malformed.
    """
    try:
        content = report_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReflectionCandidateError(
            f"failed to read source report {report_path}"
        ) from exc

    candidates: list[str] = []
    in_candidate_block = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == _CANDIDATE_BLOCK_HEADER:
            in_candidate_block = True
            continue
        if in_candidate_block:
            m = _CANDIDATE_LINE_RE.match(stripped)
            if m:
                candidates.append(m.group("text"))
            else:
                # Blank line or next section header ends the candidate block.
                in_candidate_block = False

    # Reviewer-fix (PR #346 MEDIUM 2): defense-in-depth `index < 1` guard —
    # _parse_candidate_id already validates index ≥ 1, but if a caller bypasses
    # it, `candidates[0 - 1]` = candidates[-1] would silently return the LAST
    # candidate. Explicit lower-bound check 反 silent wrong-candidate.
    if index < 1 or index > len(candidates):
        raise ReflectionCandidateError(
            f"candidate index {index} out of range [1, {len(candidates)}] — "
            f"report {report_path.name} has {len(candidates)} candidate(s)"
        )
    return candidates[index - 1]


def _candidate_id_slug(candidate_id: str) -> str:
    """Filesystem-safe slug of candidate_id for risk_findings/ filename.

    candidate_id is already parser-validated [\\w\\-]+#\\d+ — only '#' needs
    replacing for filename safety (反 path-traversal already guaranteed by parser).
    """
    return candidate_id.replace("#", "_idx")


class ReflectionCandidateService:
    """V3 §8.3 candidate approve/reject → risk_findings/ sediment (TB-4d).

    Pure sediment service — 0 git / 0 .env / 0 broker / 0 DB. File IO only:
    read source report (docs/risk_reflections/) + write candidate record
    (docs/research-kb/risk_findings/).

    Args:
        reflections_dir: source report dir. Default docs/risk_reflections/.
        risk_findings_dir: candidate sediment dir. Default
            docs/research-kb/risk_findings/. Created on first write if missing.
    """

    def __init__(
        self,
        *,
        reflections_dir: Path = _DEFAULT_REFLECTIONS_DIR,
        risk_findings_dir: Path = _DEFAULT_RISK_FINDINGS_DIR,
    ) -> None:
        self.reflections_dir = reflections_dir
        self.risk_findings_dir = risk_findings_dir

    def process_candidate_command(
        self,
        parsed: ParsedCandidateWebhook,
        *,
        now: datetime | None = None,
    ) -> CandidateDecisionResult:
        """V3 §8.3 — sediment an approved/rejected candidate to risk_findings/.

        Idempotent: if a record for this candidate_id already exists (same
        candidate_id, any status), returns ALREADY_DECIDED without overwriting
        (反 DingTalk webhook auto-retry double-write + 反 silent decision flip).

        Args:
            parsed: ParsedCandidateWebhook from webhook_parser.parse_candidate_command.
            now: tz-aware decision timestamp. None = current UTC.

        Returns:
            CandidateDecisionResult with outcome + candidate_id + sediment_path.

        Raises:
            ValueError: now is naive (铁律 41).
            ReflectionCandidateError: candidate_id malformed / report not found /
                candidate index out of range (fail-loud per 铁律 33).
        """
        from backend.qm_platform.risk.execution.webhook_parser import (  # noqa: PLC0415
            CandidateCommand,
        )

        now_effective = now if now is not None else datetime.now(UTC)
        if now_effective.tzinfo is None:
            raise ValueError(
                "process_candidate_command: now must be tz-aware (铁律 41 sustained)"
            )

        candidate_id = parsed.candidate_id
        period_label, index = _parse_candidate_id(candidate_id)

        status = (
            "approved"
            if parsed.command is CandidateCommand.APPROVE
            else "rejected"
        )
        outcome = (
            CandidateOutcome.APPROVED_SEDIMENTED
            if parsed.command is CandidateCommand.APPROVE
            else CandidateOutcome.REJECTED_SEDIMENTED
        )

        # Idempotency check — same candidate_id already sedimented?
        slug = _candidate_id_slug(candidate_id)
        existing = list(self.risk_findings_dir.glob(f"*_{slug}_*.md"))
        if existing:
            logger.info(
                "[reflection-candidate] candidate_id=%s already decided "
                "(%d existing record(s)) — idempotent return",
                candidate_id,
                len(existing),
            )
            return CandidateDecisionResult(
                outcome=CandidateOutcome.ALREADY_DECIDED,
                candidate_id=candidate_id,
                sediment_path=None,
            )

        # Resolve source report + extract candidate text (fail-loud).
        report_path = _resolve_report_path(period_label, self.reflections_dir)
        candidate_text = _extract_candidate_text(report_path, index)

        # Write risk_findings/ candidate record.
        self.risk_findings_dir.mkdir(parents=True, exist_ok=True)
        date_str = now_effective.strftime("%Y-%m-%d")
        sediment_path = self.risk_findings_dir / f"{date_str}_{slug}_{status}.md"

        try:
            report_rel = report_path.relative_to(_REPO_ROOT)
        except ValueError:
            report_rel = report_path

        record = self._render_candidate_record(
            candidate_id=candidate_id,
            status=status,
            period_label=period_label,
            index=index,
            candidate_text=candidate_text,
            source_report=str(report_rel),
            decided_at=now_effective,
        )
        sediment_path.write_text(record, encoding="utf-8")

        logger.info(
            "[reflection-candidate] sedimented candidate_id=%s status=%s → %s",
            candidate_id,
            status,
            sediment_path.name,
        )
        return CandidateDecisionResult(
            outcome=outcome,
            candidate_id=candidate_id,
            sediment_path=str(sediment_path),
        )

    @staticmethod
    def _render_candidate_record(
        *,
        candidate_id: str,
        status: str,
        period_label: str,
        index: int,
        candidate_text: str,
        source_report: str,
        decided_at: datetime,
    ) -> str:
        """Render the risk_findings/ candidate record markdown.

        Approved records are read by scripts/generate_risk_candidate_pr.py to
        build a PR (the `pr_generated: false` flag tracks PR-generation state).
        Rejected records are 长尾留存 only (V3 §8.3 line 968).
        """
        return (
            f"---\n"
            f"candidate_id: {candidate_id}\n"
            f"status: {status}\n"
            f"period_label: {period_label}\n"
            f"candidate_index: {index}\n"
            f"source_report: {source_report}\n"
            f"decided_at: {decided_at.isoformat()}\n"
            f"pr_generated: false\n"
            f"---\n\n"
            f"# RiskReflector 候选 {candidate_id} — {status}\n\n"
            f"**改进候选内容**:\n\n"
            f"> {candidate_text}\n\n"
            f"**来源报告**: {source_report}\n\n"
            f"**决策**: user 经 DingTalk webhook 回复 `{status}` "
            f"(decided_at={decided_at.isoformat()})\n\n"
            f"---\n\n"
            f"_本记录由 ReflectionCandidateService 自动沉淀 (V3 §8.3 闭环). "
            f"{'approved → scripts/generate_risk_candidate_pr.py 生成 PR 供 user 显式 merge' if status == 'approved' else 'rejected → 长尾留存 (V3 §8.3 line 968)'}, "
            f"反 silent .env mutation (ADR-022 sustained)._\n"
        )


__all__ = [
    "CandidateDecisionResult",
    "CandidateOutcome",
    "ReflectionCandidateError",
    "ReflectionCandidateService",
]
