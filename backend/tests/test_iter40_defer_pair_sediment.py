"""Regression-guard tests for iter 40 DEFER pair sediment.

Iter 40 IMPLEMENT (LL-194 codification) + DEFER (paper_trading_service.py:361
signal→exec timing hardcode) ship in the same PR per L4R_LOOP_SPEC §5
same-commit-ship to keep §4.5 ratio at 21:3:7=68.75% mid-band (pre-merge
21:2:7=70.0% AT §4.5 boundary; pure-IMPLEMENT iter 40 would push to 22:2:7=
71.0% breaching threshold).

These tests are anti-silent-removal regression guards:
  - DEFER rationale must survive future refactor passes (no behavior change,
    pure code-comment + 2 inline reminders)
  - LL-194 sediment must survive LESSONS_LEARNED.md edits (anti retroactive
    deletion / LL-115 active-discovery family)
  - Hardcoded 17:20 / 09:30 approximation must remain in place until Phase B-2
    cutover-driven refactor lands (per the DEFER verdict)

If any of these tests fail, the DEFER pair was silently removed — re-add per
the original §5 rationale OR explicitly close the DEFER via new ADR + remove
this test file with provenance in commit message.

Mirrors iter 34 test_backtest_sensitivity_defer.py pattern (regression guard
around DEFER sediment) but for code-comment-only sediment (no endpoint
contract change).
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _read(rel_path: str) -> str:
    """Read project-rooted file as text."""
    full = PROJECT_ROOT / rel_path
    assert full.is_file(), f"expected file {full} not found (iter 40 sediment broken)"
    return full.read_text(encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# DEFER side: paper_trading_service.py:361 signal→exec timing
# ──────────────────────────────────────────────────────────────────────────────


def test_defer_block_present_in_paper_trading_service():
    """The iter 40 DEFER sediment block must be present in source.

    Anti silent-removal guard. If a future refactor pass deletes the DEFER
    comment block, this test fails — re-add per iter 40 §5 pairing OR close
    the DEFER explicitly.
    """
    src = _read("backend/app/services/paper_trading_service.py")
    assert "DEFER sediment (iter 40" in src, "iter 40 DEFER block missing"
    assert "PT-coupled premature precision" in src, "DEFER rationale stripped"
    assert "same-commit-ship" in src, "§5 pairing rationale stripped"


def test_defer_block_cites_phase_b_post_pt_restart():
    """DEFER verdict must explicitly cite Phase B-2 cutover unblock condition."""
    src = _read("backend/app/services/paper_trading_service.py")
    assert "Phase B-2" in src, "DEFER unblock condition stripped"
    assert "executed_at" in src, "true exec_ts source citation stripped"
    assert "signal_log" in src or "scheduler_task_log" in src, (
        "true signal_ts source citation stripped"
    )


def test_signal_exec_hardcode_sustained_until_phase_b_2():
    """The 17:20 / 09:30 hardcoded approximation must remain in place.

    Per the DEFER verdict, behavior change is gated on Phase B-2 cutover.
    Mid-DEFER refactor of the approximation = silent scope creep (would
    violate the DEFER same-commit-ship promise).
    """
    src = _read("backend/app/services/paper_trading_service.py")
    assert "hour=17, minute=20" in src, "signal time hardcode removed mid-DEFER"
    assert "hour=9, minute=30" in src, "exec time hardcode removed mid-DEFER"


def test_inline_reminders_present_on_hardcoded_times():
    """Inline DEFER iter 40 reminders next to hardcoded times (find-on-grep aid)."""
    src = _read("backend/app/services/paper_trading_service.py")
    # Both hardcoded time lines should have "DEFER iter 40" inline reminder
    # in the preceding comment (defense-in-depth visibility)
    assert src.count("DEFER iter 40") >= 2, (
        "inline DEFER iter 40 reminders missing from hardcoded time call sites"
    )


# ──────────────────────────────────────────────────────────────────────────────
# IMPLEMENT side: LL-194 codification to LESSONS_LEARNED.md
# ──────────────────────────────────────────────────────────────────────────────


def test_ll194_entry_present_in_lessons_learned():
    """LL-194 codification must exist in LESSONS_LEARNED.md.

    Anti retroactive-deletion regression guard (LL-115 active-discovery family).
    """
    src = _read("LESSONS_LEARNED.md")
    assert "## LL-194" in src, "LL-194 entry missing (iter 40 sediment regression)"
    assert "Verify retrospective bug claim pre-fix" in src, "LL-194 title stripped"


def test_ll194_cites_iter_36_pr_464():
    """LL-194 must trace back to iter 36 PR #464 root cause (provenance chain)."""
    src = _read("LESSONS_LEARNED.md")
    # LL-194 sediment trigger should cite the originating PR + commit
    ll194_section_start = src.index("## LL-194")
    # Bound LL-194 section to next ## header or EOF (defensive)
    next_header_offset = src.find("\n## ", ll194_section_start + 10)
    if next_header_offset == -1:
        next_header_offset = len(src)
    ll194_section = src[ll194_section_start:next_header_offset]

    assert "PR #464" in ll194_section, "LL-194 missing iter 36 PR provenance"
    assert "e106f0f" in ll194_section, "LL-194 missing iter 36 commit SHA"


def test_ll194_cites_mutation_test_sop():
    """LL-194 Fix SOP must mention mutation testing (the core actionable)."""
    src = _read("LESSONS_LEARNED.md")
    ll194_section_start = src.index("## LL-194")
    next_header_offset = src.find("\n## ", ll194_section_start + 10)
    if next_header_offset == -1:
        next_header_offset = len(src)
    ll194_section = src[ll194_section_start:next_header_offset]

    assert "mutation test" in ll194_section.lower(), "LL-194 Fix SOP missing mutation test"
    assert "Defense-in-depth" in ll194_section or "defense-in-depth" in ll194_section, (
        "LL-194 reframings (defense-in-depth alternative) missing"
    )


def test_ll194_cross_refs_anti_pattern_family():
    """LL-194 must cross-ref the LL-098/LL-101/LL-103 family (drift cousin)."""
    src = _read("LESSONS_LEARNED.md")
    ll194_section_start = src.index("## LL-194")
    next_header_offset = src.find("\n## ", ll194_section_start + 10)
    if next_header_offset == -1:
        next_header_offset = len(src)
    ll194_section = src[ll194_section_start:next_header_offset]

    # Must cite at least LL-098 (X10 forward-progress) which is the parent
    # anti-pattern family for fabricated-progress claims
    assert "LL-098" in ll194_section, "LL-194 missing parent anti-pattern family (LL-098)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
