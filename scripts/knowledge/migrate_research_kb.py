"""MVP 1.4 — 一次性迁移 `docs/research-kb/` + `CLAUDE.md` L474 已知失败方向 → DB.

源:
  1. `CLAUDE.md` §已知失败方向 table (| 方向 | 结论 | 来源 |) → failed_directions
  2. `docs/research-kb/failed/*.md` → failed_directions (与 CLAUDE.md 去重合并)
  3. `docs/research-kb/findings/*.md` → platform_experiments (status=success)
  4. `docs/research-kb/experiments/*.md` → platform_experiments (status=success)

CLI:
    python scripts/knowledge/migrate_research_kb.py              # dry-run
    python scripts/knowledge/migrate_research_kb.py --apply      # 真写 DB
    python scripts/knowledge/migrate_research_kb.py --verbose    # 详细日志

幂等 (ON CONFLICT DO UPDATE), 可重复运行.

铁律: 22 (文档跟随代码) / 32 (Service 不 commit — orchestration 脚本负责) / 33 (禁 silent failure).
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# 用 append 避免 backend/platform/ 覆盖 stdlib `platform` (MVP 1.2 踩坑)
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("migrate_research_kb")


CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
RESEARCH_KB = PROJECT_ROOT / "docs" / "research-kb"


# ---------- Data containers ----------


@dataclass
class FailedDirEntry:
    direction: str
    reason: str
    evidence: list[str]
    severity: str
    source: str
    tags: list[str]


@dataclass
class ExperimentEntry:
    hypothesis: str
    status: str
    author: str
    verdict: str
    artifacts: dict[str, str]
    tags: list[str]


# ---------- Parser: CLAUDE.md L474 table ----------


def parse_claude_md_table() -> list[FailedDirEntry]:
    """Parse `| 方向 | 结论 | 来源 |` Markdown table under §已知失败方向."""
    if not CLAUDE_MD.exists():
        logger.warning("CLAUDE.md 不存在: %s", CLAUDE_MD)
        return []

    text = CLAUDE_MD.read_text(encoding="utf-8")
    # Locate section
    header_match = re.search(r"^##\s+已知失败方向", text, re.MULTILINE)
    if not header_match:
        logger.warning("CLAUDE.md 未找到 ## 已知失败方向 section")
        return []

    section_start = header_match.end()
    # Find next ## header (end of section)
    next_header = re.search(r"^##\s+", text[section_start:], re.MULTILINE)
    section_end = section_start + next_header.start() if next_header else len(text)
    section_text = text[section_start:section_end]

    entries: list[FailedDirEntry] = []
    for line in section_text.splitlines():
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 3:
            continue
        direction, reason, source = cells
        # Skip header / separator
        if direction in ("方向", "") or set(direction) <= {"-", ":"}:
            continue
        entries.append(
            FailedDirEntry(
                direction=direction,
                reason=reason,
                evidence=[f"CLAUDE.md: {source}"],
                severity="terminal",
                source="CLAUDE.md",
                tags=_infer_tags(direction + " " + reason),
            )
        )
    logger.info("CLAUDE.md 表格解析: %d 条失败方向", len(entries))
    return entries


# ---------- Parser: research-kb/failed/*.md ----------


_FAILED_TITLE_RE = re.compile(r"^#\s+失败方向\s*[:：]\s*(.+?)\s*$", re.MULTILINE)


def parse_failed_kb_dir() -> list[FailedDirEntry]:
    folder = RESEARCH_KB / "failed"
    if not folder.exists():
        return []
    entries: list[FailedDirEntry] = []
    for md in sorted(folder.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        m = _FAILED_TITLE_RE.search(text)
        if not m:
            logger.warning("%s 无 `# 失败方向: XXX` 标题, 跳过", md.name)
            continue
        direction = m.group(1).strip()
        reason = _extract_bullet(text, "失败原因") or _extract_bullet(text, "结果") or "(未提取)"
        evidence = [f"docs/research-kb/failed/{md.name}"]
        adapt_cond = _extract_bullet(text, "适用条件")
        if adapt_cond:
            evidence.append(f"适用条件: {adapt_cond}")
        entries.append(
            FailedDirEntry(
                direction=direction,
                reason=reason,
                evidence=evidence,
                severity="terminal",
                source=f"docs/research-kb/failed/{md.name}",
                tags=_infer_tags(direction + " " + reason),
            )
        )
    logger.info("research-kb/failed/ 解析: %d 条", len(entries))
    return entries


def _extract_bullet(text: str, key: str) -> str | None:
    """匹配 `- KEY: VALUE` 或 `- KEY：VALUE` 的第一行 value."""
    pattern = re.compile(rf"^-\s+{re.escape(key)}\s*[:：]\s*(.+?)\s*$", re.MULTILINE)
    m = pattern.search(text)
    return m.group(1).strip() if m else None


# ---------- Parser: research-kb/findings/ + experiments/ → platform_experiments ----------


def parse_experiments_kb() -> list[ExperimentEntry]:
    """findings/ + experiments/ 每份 md → 一条 platform_experiments (status=success)."""
    entries: list[ExperimentEntry] = []
    for sub in ("findings", "experiments"):
        folder = RESEARCH_KB / sub
        if not folder.exists():
            continue
        for md in sorted(folder.glob("*.md")):
            text = md.read_text(encoding="utf-8")
            # title: first "# XXX"
            title_m = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
            title = title_m.group(1).strip() if title_m else md.stem
            # hypothesis / verdict: best effort 从文首 200 字提取
            preview = text[:500].strip().replace("\n", " ")
            entries.append(
                ExperimentEntry(
                    hypothesis=title,
                    status="success",  # findings 都是"已完成的结论"
                    author="historical",
                    verdict=preview[:400],
                    artifacts={"source": f"docs/research-kb/{sub}/{md.name}"},
                    tags=[sub, *_infer_tags(title)],
                )
            )
    logger.info("research-kb/findings + experiments 解析: %d 条", len(entries))
    return entries


# ---------- Tag 推断 ----------


_TAG_KEYWORDS = {
    "ml": ["ml", "LightGBM", "ML", "模型", "LambdaRank", "regression"],
    "portfolio": ["portfolio", "MVO", "riskfolio", "等权", "权重", "优化"],
    "factor": ["因子", "factor", "alpha", "IC"],
    "regime": ["regime", "动态", "HMM"],
    "ml_e2e": ["E2E", "端到端", "可微"],
    "universe": ["universe", "微盘", "小盘"],
    "minute": ["分钟", "minute", "微结构", "日内"],
    "pms": ["PMS", "保护", "止损"],
    "rebalance": ["调仓", "rebalance", "双周"],
    "sim_to_real": ["sim-to-real", "gap", "实盘"],
}


def _infer_tags(text: str) -> list[str]:
    text_l = text.lower()
    tags: list[str] = []
    for tag, kws in _TAG_KEYWORDS.items():
        if any(k.lower() in text_l for k in kws):
            tags.append(tag)
    return tags or ["misc"]


# ---------- Dedupe ----------


def merge_failed_entries(*lists: list[FailedDirEntry]) -> list[FailedDirEntry]:
    """By direction, md-sourced 优先 (evidence 更丰富)."""
    by_dir: dict[str, FailedDirEntry] = {}
    for entries in lists:
        for e in entries:
            key = e.direction.strip().lower()
            if key in by_dir:
                # merge evidence + tags
                merged_ev = by_dir[key].evidence + [ev for ev in e.evidence if ev not in by_dir[key].evidence]
                merged_tags = list(dict.fromkeys(by_dir[key].tags + e.tags))
                # 优先保 md-sourced (非 CLAUDE.md)
                base = by_dir[key] if by_dir[key].source != "CLAUDE.md" else e
                by_dir[key] = FailedDirEntry(
                    direction=base.direction,
                    reason=base.reason,
                    evidence=merged_ev,
                    severity=base.severity,
                    source=base.source,
                    tags=merged_tags,
                )
            else:
                by_dir[key] = e
    return list(by_dir.values())


# ---------- DB writer ----------


def apply_failed_directions(entries: list[FailedDirEntry], dry_run: bool) -> int:
    if dry_run:
        logger.info("[DRY-RUN] 跳过写 failed_directions (%d 条)", len(entries))
        return 0
    from app.services.db import get_sync_conn
    from backend.qm_platform.knowledge.interface import FailedDirectionRecord
    from backend.qm_platform.knowledge.registry import DBFailedDirectionDB

    db = DBFailedDirectionDB(conn_factory=get_sync_conn)
    count = 0
    for e in entries:
        rec = FailedDirectionRecord(
            direction=e.direction,
            reason=e.reason,
            evidence=e.evidence,
            recorded_at="",  # DB DEFAULT NOW()
            severity=e.severity,
        )
        db.add_with_source(rec, source=e.source, tags=e.tags)
        count += 1
    logger.info("failed_directions upserted: %d", count)
    return count


def apply_experiments(entries: list[ExperimentEntry], dry_run: bool) -> int:
    if dry_run:
        logger.info("[DRY-RUN] 跳过写 platform_experiments (%d 条)", len(entries))
        return 0
    from uuid import uuid4

    from app.services.db import get_sync_conn
    from backend.qm_platform.knowledge.interface import ExperimentRecord
    from backend.qm_platform.knowledge.registry import DBExperimentRegistry

    db = DBExperimentRegistry(conn_factory=get_sync_conn)
    count = 0
    for e in entries:
        eid = uuid4()
        rec = ExperimentRecord(
            experiment_id=eid,
            hypothesis=e.hypothesis,
            status=e.status,
            author=e.author,
            started_at="",  # DB DEFAULT NOW()
            completed_at=None,
            verdict=e.verdict,
            artifacts=e.artifacts,
            tags=e.tags,
        )
        db.register(rec)
        # 标记完成
        db.complete(eid, verdict=e.verdict, status=e.status, artifacts=e.artifacts)
        count += 1
    logger.info("platform_experiments registered+completed: %d", count)
    return count


# ---------- Main ----------


def main() -> None:
    parser = argparse.ArgumentParser(description="MVP 1.4 migrate research-kb + CLAUDE.md → DB")
    parser.add_argument("--apply", action="store_true", help="真写 DB (默认 dry-run)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # Parse sources
    claude_entries = parse_claude_md_table()
    failed_md_entries = parse_failed_kb_dir()
    merged = merge_failed_entries(claude_entries, failed_md_entries)
    logger.info("merge 后 failed_directions: %d 条 (去重后)", len(merged))

    experiments = parse_experiments_kb()

    # Preview
    if args.verbose or not args.apply:
        logger.info("=== Preview failed_directions (top 5) ===")
        for e in merged[:5]:
            logger.info("  - %s | %s | tags=%s", e.direction[:40], e.source, e.tags)
        logger.info("=== Preview platform_experiments (top 5) ===")
        for e in experiments[:5]:
            logger.info("  - %s | status=%s | tags=%s", e.hypothesis[:40], e.status, e.tags)

    # Apply
    dry = not args.apply
    apply_failed_directions(merged, dry)
    apply_experiments(experiments, dry)

    if dry:
        logger.info("[DRY-RUN] 结束. 加 --apply 真写 DB.")
    else:
        logger.info("✅ Migration 完成: failed_directions=%d, platform_experiments=%d",
                    len(merged), len(experiments))


if __name__ == "__main__":
    main()
