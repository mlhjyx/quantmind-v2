"""MVP 1.4 — 扫 `docs/adr/ADR-*.md` frontmatter + body → `adr_records` DB.

源: `docs/adr/ADR-NNN-slug.md` yaml frontmatter + 6 section body.

CLI:
    python scripts/knowledge/register_adrs.py              # dry-run
    python scripts/knowledge/register_adrs.py --apply      # 真写 DB
    python scripts/knowledge/register_adrs.py --verbose

幂等 (ON CONFLICT DO UPDATE 保 register 可重跑).

铁律: 22 / 32 / 33 / 38.
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
sys.path.append(str(PROJECT_ROOT))
sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("register_adrs")


ADR_DIR = PROJECT_ROOT / "docs" / "adr"


@dataclass
class ParsedADR:
    adr_id: str
    title: str
    status: str
    context: str
    decision: str
    consequences: str
    related_ironlaws: list[int]
    file_path: str


# ---------- Parser ----------


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """简单 yaml frontmatter parser (不引 yaml 依赖避免新增).

    支持: key: value / key: [a, b, c] / key: text.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm_text, body = m.group(1), m.group(2)
    meta: dict = {}
    for line in fm_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        key = key.strip()
        if value.startswith("[") and value.endswith("]"):
            # list
            inner = value[1:-1].strip()
            items = [x.strip() for x in inner.split(",") if x.strip()]
            # try int conversion
            try:
                meta[key] = [int(x) for x in items]
            except ValueError:
                meta[key] = items
        else:
            meta[key] = value
    return meta, body


def _extract_section(body: str, heading: str) -> str:
    """Extract body text under `## HEADING` until next `## ` or EOF."""
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s+|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    m = pattern.search(body)
    return m.group(1).strip() if m else ""


def parse_adr_file(path: Path) -> ParsedADR | None:
    """Parse a single ADR markdown file."""
    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)

    adr_id = str(meta.get("adr_id", "")).strip()
    if not adr_id.startswith("ADR-"):
        logger.warning("%s frontmatter 缺 adr_id 或格式错, 跳过", path.name)
        return None

    title = str(meta.get("title", "")).strip() or path.stem
    status = str(meta.get("status", "accepted")).strip()
    related = meta.get("related_ironlaws", []) or []
    if not isinstance(related, list):
        related = []
    # 确保都是 int
    related_ints: list[int] = []
    for x in related:
        try:
            related_ints.append(int(x))
        except (ValueError, TypeError):
            continue

    context = _extract_section(body, "Context")
    decision = _extract_section(body, "Decision")
    consequences = _extract_section(body, "Consequences")

    if not context or not decision:
        logger.warning("%s 缺 Context 或 Decision section, 跳过", path.name)
        return None

    return ParsedADR(
        adr_id=adr_id,
        title=title,
        status=status,
        context=context,
        decision=decision,
        consequences=consequences or "(未填)",
        related_ironlaws=related_ints,
        file_path=f"docs/adr/{path.name}",
    )


def scan_adrs() -> list[ParsedADR]:
    if not ADR_DIR.exists():
        logger.warning("docs/adr 不存在")
        return []
    results: list[ParsedADR] = []
    for path in sorted(ADR_DIR.glob("ADR-*.md")):
        parsed = parse_adr_file(path)
        if parsed:
            results.append(parsed)
    logger.info("扫描 docs/adr/ → %d 条 ADR", len(results))
    return results


# ---------- DB writer ----------


def apply_adrs(adrs: list[ParsedADR], dry_run: bool) -> int:
    if dry_run:
        logger.info("[DRY-RUN] 跳过写 adr_records (%d 条)", len(adrs))
        return 0
    from app.services.db import get_sync_conn
    from backend.platform.knowledge.interface import ADRRecord
    from backend.platform.knowledge.registry import DBADRRegistry

    registry = DBADRRegistry(conn_factory=get_sync_conn)
    count = 0
    for adr in adrs:
        rec = ADRRecord(
            adr_id=adr.adr_id,
            title=adr.title,
            status=adr.status,
            context=adr.context,
            decision=adr.decision,
            consequences=adr.consequences,
            related_ironlaws=adr.related_ironlaws,
            recorded_at="",  # DB DEFAULT NOW()
        )
        registry._register_with_file(rec, file_path=adr.file_path)
        count += 1
    logger.info("adr_records upserted: %d", count)
    return count


# ---------- Main ----------


def main() -> None:
    parser = argparse.ArgumentParser(description="MVP 1.4 register ADR markdown → adr_records DB")
    parser.add_argument("--apply", action="store_true", help="真写 DB (默认 dry-run)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    adrs = scan_adrs()

    if args.verbose or not args.apply:
        for adr in adrs:
            logger.info(
                "  %s | %s | ironlaws=%s | %s",
                adr.adr_id, adr.title[:40], adr.related_ironlaws, adr.file_path,
            )

    dry = not args.apply
    apply_adrs(adrs, dry)

    if dry:
        logger.info("[DRY-RUN] 结束. 加 --apply 真写 DB.")
    else:
        logger.info("✅ register_adrs 完成: %d 条", len(adrs))


if __name__ == "__main__":
    main()
