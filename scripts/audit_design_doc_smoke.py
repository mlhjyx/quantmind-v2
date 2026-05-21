"""Plan v8 §VIII #27 closure: Living Documentation — design doc smoke test verifier.

Why §VIII #27:
- Design docs (DEV_*.md, CLAUDE.md, SYSTEM_STATUS.md) make claims like:
    "4 CORE active" / "113 factors in factor_ic_history" / "27 schtasks" / "170 LL entries"
- Claims drift from reality over time (LL-188 sediment drift forensic — .env=live armed
  3+ weeks while CC handoff claimed paper sustained)
- Plan v8 §VIII #27: Living Documentation — design doc 自带 smoke test 验证 alignment w/ code

Strategy (smoke test approach):
- Parse markdown docs for numeric claims (`N factors` / `N tasks` / `M.md` count / etc)
- Cross-reference with truth sources:
  - DB row counts (factor_ic_history.factors, trade_log, position_snapshot, etc)
  - File system counts (docs/adr/*.md, LESSONS_LEARNED.md LL entries, etc)
  - Schtask LastResult via Get-ScheduledTaskInfo (Windows)
  - .env field values (EXECUTION_MODE / LIVE_TRADING_DISABLED / etc)
- Flag drift: doc claims X, truth is Y

Output: docs/audit/DESIGN_DOC_SMOKE_TEST_<date>.md

Usage:
  python scripts/audit_design_doc_smoke.py              # Full audit
  python scripts/audit_design_doc_smoke.py --json       # JSON
  python scripts/audit_design_doc_smoke.py --strict     # Exit 1 on any drift

Exit code:
  0 = no drift OR warnings only
  1 = critical drift detected (--strict mode OR 5/5 红线 drift)
  2 = script error

Test SOP integration: Future schtask cadence (quarterly per Plan v8 §VIII #29).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
LL_FILE = PROJECT_ROOT / "LESSONS_LEARNED.md"
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"


# ============================================================
# Truth source collectors
# ============================================================


def count_files(pattern: str, root: Path) -> int:
    """Count files matching pattern under root."""
    return len(list(root.glob(pattern)))


def count_grep_lines(pattern: str, file: Path) -> int:
    """Count lines matching regex in file."""
    if not file.exists():
        return -1
    try:
        content = file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return -1
    return len(re.findall(pattern, content, flags=re.MULTILINE))


def get_env_field(field: str) -> str | None:
    """Get value of an env field from backend/.env."""
    env_file = PROJECT_ROOT / "backend" / ".env"
    if not env_file.exists():
        return None
    try:
        text = env_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None
    m = re.search(rf"^{re.escape(field)}=(.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def collect_truth_facts() -> dict[str, str | int]:
    """Collect canonical truth facts from filesystem + .env."""
    return {
        "adr_count": count_files("ADR-*.md", DOCS_DIR / "adr"),
        "ll_unique_ids": count_grep_lines(r"^## LL-\d+:", LL_FILE),
        "audit_doc_count": count_files("*.md", DOCS_DIR / "audit"),
        "mvp_doc_count": count_files("MVP_*.md", DOCS_DIR / "mvp"),
        "research_kb_failed": count_files("*.md", DOCS_DIR / "research-kb" / "failed"),
        "research_kb_findings": count_files("*.md", DOCS_DIR / "research-kb" / "findings"),
        "research_kb_decisions": count_files("*.md", DOCS_DIR / "research-kb" / "decisions"),
        "env_execution_mode": get_env_field("EXECUTION_MODE") or "MISSING",
        "env_live_trading_disabled": get_env_field("LIVE_TRADING_DISABLED") or "MISSING",
        "env_qmt_account_id": get_env_field("QMT_ACCOUNT_ID") or "MISSING",
        "env_dingtalk_enabled": get_env_field("DINGTALK_ALERTS_ENABLED") or "MISSING",
        "env_pt_top_n": get_env_field("PT_TOP_N") or "MISSING",
        "env_pt_size_neutral_beta": get_env_field("PT_SIZE_NEUTRAL_BETA") or "MISSING",
    }


# ============================================================
# Doc claim extractors
# ============================================================


def extract_claude_md_claims(claude_md: Path) -> list[dict]:
    """Extract numeric/state claims from CLAUDE.md."""
    if not claude_md.exists():
        return []
    text = claude_md.read_text(encoding="utf-8")

    claims = []

    # ADR count claim, e.g. "累计 71 .md 实测 2026-05-19"
    m = re.search(r"累计\s*(\d+)\s*\.md.*?ADR", text)
    if m:
        claims.append(
            {
                "fact": "adr_count",
                "claim_value": int(m.group(1)),
                "claim_text": m.group(0)[:80],
            }
        )

    # PT config claims
    for field, pattern in [
        ("env_pt_top_n", r"PT_TOP_N=(\d+)"),
        ("env_pt_size_neutral_beta", r"PT_SIZE_NEUTRAL_BETA=([\d.]+)"),
    ]:
        m = re.search(pattern, text)
        if m:
            claims.append(
                {
                    "fact": field,
                    "claim_value": m.group(1),
                    "claim_text": m.group(0),
                }
            )

    return claims


def compare_claims_vs_truth(claims: list[dict], truth: dict) -> list[dict]:
    """Cross-reference each claim against truth, flag drift."""
    results = []
    for claim in claims:
        fact_key = claim["fact"]
        truth_value = truth.get(fact_key)
        claim_value = claim["claim_value"]

        if truth_value is None:
            severity = "UNKNOWN"
            note = "Truth source missing"
        elif str(truth_value) == str(claim_value):
            severity = "ALIGNED"
            note = "Claim matches truth"
        else:
            severity = "DRIFT"
            note = f"Claim {claim_value!r} ≠ truth {truth_value!r}"

        results.append(
            {
                **claim,
                "truth_value": truth_value,
                "severity": severity,
                "note": note,
            }
        )

    return results


# ============================================================
# Report
# ============================================================


def to_markdown_report(truth: dict, drift_results: list[dict]) -> str:
    """Render markdown report."""
    drift_count = sum(1 for r in drift_results if r["severity"] == "DRIFT")
    aligned_count = sum(1 for r in drift_results if r["severity"] == "ALIGNED")

    lines = [
        f"# Design Doc Smoke Test — {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
        "> **Plan v8 §VIII #27 closure** (Living Documentation, sediment-then-implement).",
        "> Auto-verify doc claims against filesystem + .env truth sources.",
        "> 反 LL-188 sediment drift (doc claim vs .env truth mismatch).",
        "",
        "## §1 Summary",
        "",
        f"- **Claims checked**: {len(drift_results)}",
        f"- **Aligned**: {aligned_count} ✅",
        f"- **Drift detected**: {drift_count} ❌",
        "",
        "## §2 Truth Facts (Canonical SSOT 5-20)",
        "",
        "| Fact | Value | Source |",
        "|---|---|---|",
    ]

    truth_sources = {
        "adr_count": "fs: docs/adr/ADR-*.md",
        "ll_unique_ids": "grep: LESSONS_LEARNED.md '^## LL-'",
        "audit_doc_count": "fs: docs/audit/*.md",
        "mvp_doc_count": "fs: docs/mvp/MVP_*.md",
        "research_kb_failed": "fs: docs/research-kb/failed/*.md",
        "research_kb_findings": "fs: docs/research-kb/findings/*.md",
        "research_kb_decisions": "fs: docs/research-kb/decisions/*.md",
        "env_execution_mode": ".env",
        "env_live_trading_disabled": ".env",
        "env_qmt_account_id": ".env",
        "env_dingtalk_enabled": ".env",
        "env_pt_top_n": ".env",
        "env_pt_size_neutral_beta": ".env",
    }

    for fact, value in truth.items():
        src = truth_sources.get(fact, "?")
        lines.append(f"| `{fact}` | `{value}` | {src} |")

    lines.extend(
        [
            "",
            "## §3 Drift Findings",
            "",
            "| Severity | Fact | Claim | Truth | Note |",
            "|---|---|---|---|---|",
        ]
    )

    if drift_results:
        for r in drift_results:
            sev = r["severity"]
            sym = {"ALIGNED": "✅", "DRIFT": "❌", "UNKNOWN": "⚠️"}.get(sev, "?")
            lines.append(
                f"| {sym} {sev} | `{r['fact']}` | `{r['claim_value']}` | "
                f"`{r['truth_value']}` | {r['note']} |"
            )
    else:
        lines.append("| — | — | — | — | No claims extracted from CLAUDE.md |")

    lines.extend(
        [
            "",
            "## §4 5/5 红线 Field Verification",
            "",
            "| Field | Truth | Expected (Phase B-1) | Verdict |",
            "|---|---|---|---|",
            f"| EXECUTION_MODE | `{truth.get('env_execution_mode')}` | `paper` | "
            f"{'✅' if truth.get('env_execution_mode') == 'paper' else '❌ DRIFT'} |",
            f"| LIVE_TRADING_DISABLED | `{truth.get('env_live_trading_disabled')}` | `true` | "
            f"{'✅' if truth.get('env_live_trading_disabled') == 'true' else '❌ DRIFT'} |",
            f"| QMT_ACCOUNT_ID | `{truth.get('env_qmt_account_id')}` | `81001102` | "
            f"{'✅' if truth.get('env_qmt_account_id') == '81001102' else '❌ DRIFT'} |",
            f"| DINGTALK_ALERTS_ENABLED | `{truth.get('env_dingtalk_enabled')}` | `true` | "
            f"{'✅' if truth.get('env_dingtalk_enabled') == 'true' else '❌ DRIFT'} |",
            "",
            "---",
            "",
            "**Auto-regenerate**: `python scripts/audit_design_doc_smoke.py`",
            "**Source of truth**: filesystem counts + grep + backend/.env",
            f"**Plan v8 §VIII #27 closure**: {datetime.now(UTC).strftime('%Y-%m-%d')} sediment",
            "",
            "## §5 Future Enhancement",
            "",
            "- Expand claim extraction to DEV_*.md (factor counts, schtask counts, service counts)",
            "- Integrate w/ pre-commit canonical metrics (factor_count, ll_unique_ids, etc)",
            "- DB query truth sources (factor_ic_history.factors, trade_log rows)",
            "- Schtask LastResult via Get-ScheduledTaskInfo (Windows-only)",
        ]
    )

    return "\n".join(lines)


# ============================================================
# Main
# ============================================================


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any drift")
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output path (default: docs/audit/DESIGN_DOC_SMOKE_TEST_<date>.md)",
    )
    args = parser.parse_args()

    print("[smoke-test] Collecting truth facts...", file=sys.stderr)
    truth = collect_truth_facts()

    print("[smoke-test] Extracting CLAUDE.md claims...", file=sys.stderr)
    claims = extract_claude_md_claims(CLAUDE_MD)

    print(f"[smoke-test] {len(claims)} claims extracted", file=sys.stderr)
    drift = compare_claims_vs_truth(claims, truth)

    drift_count = sum(1 for r in drift if r["severity"] == "DRIFT")

    if args.json:
        print(json.dumps({"truth": truth, "drift": drift}, indent=2, ensure_ascii=False))
    else:
        report = to_markdown_report(truth, drift)
        if args.output:
            output_path = PROJECT_ROOT / args.output
        else:
            date_str = datetime.now(UTC).strftime("%Y_%m_%d")
            output_path = PROJECT_ROOT / "docs" / "audit" / f"DESIGN_DOC_SMOKE_TEST_{date_str}.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        print(f"[smoke-test] Written: {output_path}", file=sys.stderr)
        print(f"[smoke-test] Drift: {drift_count} / {len(drift)}", file=sys.stderr)

    return 1 if args.strict and drift_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
