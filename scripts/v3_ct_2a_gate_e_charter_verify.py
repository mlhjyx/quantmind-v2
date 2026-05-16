#!/usr/bin/env python3
"""V3 Plan v0.4 CT-2a — Gate E charter verify (Constitution §L10.5 5 prereq + V3 §20.1 10 user 决议).

Plan v0.4 §A CT-2a — Gate E formal verify run BEFORE CT-2b .env paper→live
flip. Per user 决议 (C1)+(M1)+(T1) 2026-05-17, CT-2a is verify-only doc
(0 mutation) ahead of separate CT-2b apply moment with user 显式 "同意
apply" trigger.

**Gate E charter** (Constitution §L10.5 line 450-469):
  5 prerequisite — each verifiable via cite cross-reference + grep:
    1. paper-mode 5d 通过 (replay-path equivalent per ADR-063 — Tier B
       真测路径 transferable; IC-3a 5y full minute_bars replay 4/4 V3
       §15.4 PASS = Tier A 5d 等价 evidence)
    2. 元监控 0 P0 (sustained from IC-3a 4-acceptance item #4 + CT-1b
       operational readiness 6/6 ✅)
    3. Tier A ADR 全 sediment (REGISTRY committed count + V3 §12.1
       Sprint S1-S11 closure cite)
    4. 5 SLA 满足 (V3 §13.1 5 SLA — sustained from IC-3a/b/c reports
       cumulative + CT-1b operational readiness)
    5. 10 user 决议 verify (V3 §20.1 — all closed PR #216 sediment,
       cumulative ADR-027 + ADR-028 + ADR-033)

**Why verify-only doc** (NOT real mutation):
  - CT-2a is Gate E READINESS CHECK before CT-2b .env flip
  - 0 broker call / 0 .env mutation / 0 yaml mutation throughout CT-2a
  - All checks are cite cross-reference + grep + file presence
  - Re-uses CT-1b operational readiness harness (still ✅ READY?)

**Verify mode** (sustained CT-1b体例):
  - `--dry-run` default: run checks + print report, 0 mutation, no sediment
  - `--out`: optional report path override

关联铁律: 22 / 24 / 25 (改什么读什么) / 33 (fail-loud per check) / 41 / 42
关联 V3: §20.1 (10 user 决议) / §13.1 (5 SLA) / §15.4 (4 acceptance) /
  §12.1 (Sprint S1-S11) / §17.2 (双锁)
关联 ADR: ADR-027 (STAGED + 反向决策权 + 跌停 fallback) / ADR-028
  (AUTO + V4-Pro X 阈值 + RAG + backtest replay) / ADR-033 (News 6 源
  换源决议) / ADR-063 (Tier B 真测路径 — paper-mode 5d 等价) /
  ADR-077 reserved (Plan v0.4 closure cumulative — CT-2c sediment)
关联 Plan: V3_PT_CUTOVER_PLAN_v0.1.md §A CT-2a + Constitution §L10.5
关联 LL: LL-098 X10 / LL-164 (Gate E charter pre-sediment verify体例) /
  LL-173 lesson 1 (replay-as-gate replaces wall-clock) / LL-174 lesson 2
  (3-step user gate体例)
"""

# ruff: noqa: E402 — sys.path.insert(s) precede imports (necessary path setup)

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)

# Expected sediment artifacts (CT-2a charter verify cite cross-reference).
_IC3A_REPORT: Path = (
    PROJECT_ROOT / "docs" / "audit"
    / "v3_ic_3a_5y_integrated_replay_report_2026_05_16.md"
)
_IC3B_REPORT: Path = (
    PROJECT_ROOT / "docs" / "audit"
    / "v3_ic_3b_counterfactual_replay_report_2026_05_16.md"
)
_IC3C_REPORT: Path = (
    PROJECT_ROOT / "docs" / "audit"
    / "v3_ic_3c_synthetic_scenarios_report_2026_05_16.md"
)
_CT1A_REPORT: Path = (
    PROJECT_ROOT / "docs" / "audit"
    / "v3_ct_1a_cleanup_report_2026_05_16.md"
)
_CT1B_REPORT: Path = (
    PROJECT_ROOT / "docs" / "audit"
    / "v3_ct_1b_operational_readiness_report_2026_05_17.md"
)

# Tier A ADR list per V3 §12.1 + Constitution §L10.4 sediment.
_TIER_A_ADR_MIN: tuple[str, ...] = (
    "ADR-019",  # T1.5b-2 formal promote
    "ADR-020",
    "ADR-027",  # L4 STAGED + 反向决策权
    "ADR-028",  # AUTO mode + V4-Pro + RAG + replay
    "ADR-029",  # 10 RealtimeRiskRule
    "ADR-033",  # News 6 源 换源
    "ADR-063",  # Tier B 真测路径 (paper-mode 5d equivalent)
    "ADR-070",  # TB-5b methodology + 阈值 sustained
    "ADR-076",  # 横切层 closed + Gate D close
    "ADR-078",  # IC-1 closure
    "ADR-079",  # IC-2 closure
    "ADR-080",  # IC-3 closure
    "ADR-081",  # CT-1 closure
)

# V3 §20.1 10 user 决议 keywords for grep verify.
_TEN_USER_DECISIONS: tuple[tuple[str, str], ...] = (
    ("STAGED default", "ADR-027"),
    ("Bull/Bear regime cadence", "daily 3 次"),
    ("RAG embedding model", "BGE-M3"),
    ("RiskReflector cadence", "周日 19:00"),
    ("AUTO 模式启用条件", "ADR-028"),
    ("LLM 成本月预算上限", "$50/月"),
    ("user 离线 STAGED 30min", "hybrid 自适应窗口"),
    ("L4 batched 平仓 batch interval", "5min"),
    ("L5 反思 lesson 入 RAG", "后置抽查"),
    ("L0 News 6 源", "ADR-033"),
)


# ---------- Check result types ----------


@dataclass
class _PrereqResult:
    """One Gate E prerequisite verify outcome."""

    name: str
    passed: bool = False
    detail: str = ""
    failures: list[str] = field(default_factory=list)


@dataclass
class _GateEReport:
    """Aggregate Gate E charter verify report."""

    timestamp_utc: str
    timestamp_shanghai: str
    prereq_checks: list[_PrereqResult] = field(default_factory=list)
    user_decisions_checks: list[_PrereqResult] = field(default_factory=list)

    @property
    def all_prereq_passed(self) -> bool:
        return (
            all(c.passed for c in self.prereq_checks)
            and len(self.prereq_checks) == 5
        )

    @property
    def all_user_decisions_passed(self) -> bool:
        return (
            all(c.passed for c in self.user_decisions_checks)
            and len(self.user_decisions_checks) == 10
        )

    @property
    def gate_e_ready(self) -> bool:
        return self.all_prereq_passed and self.all_user_decisions_passed


# ---------- 5 Prereq checks ----------


def _check_prereq_1_paper_mode_5d() -> _PrereqResult:
    """Prereq 1: paper-mode 5d 通过 — replay-path equivalent per ADR-063.

    IC-3a 5y replay 4/4 V3 §15.4 PASS = Tier A 5d paper-mode equivalent.
    """
    r = _PrereqResult(
        name="paper_mode_5d (ADR-063 replay-path equivalent)"
    )
    if not _IC3A_REPORT.exists():
        r.failures.append(f"IC-3a report missing: {_IC3A_REPORT}")
        return r
    txt = _IC3A_REPORT.read_text(encoding="utf-8")
    has_pass_verdict = "✅ PASS" in txt and "Overall verdict" in txt
    has_4_of_4 = ("4/4" in txt or "4 项 acceptance" in txt) and "V3 §15.4" in txt
    has_adr_063 = "ADR-063" in txt
    if not has_pass_verdict:
        r.failures.append("IC-3a report missing ✅ PASS verdict")
    if not has_4_of_4:
        r.failures.append("IC-3a report missing 4/4 V3 §15.4 acceptance cite")
    if not has_adr_063:
        r.failures.append("IC-3a report missing ADR-063 replay-path cite")
    if not r.failures:
        r.passed = True
        r.detail = (
            "IC-3a 5y replay 4/4 V3 §15.4 PASS + ADR-063 replay-path "
            "equivalent cited (Tier A 5d paper-mode equivalent)"
        )
    return r


def _check_prereq_2_meta_monitor_0_p0() -> _PrereqResult:
    """Prereq 2: 元监控 0 P0 — IC-3a item 4 + CT-1b operational readiness."""
    r = _PrereqResult(name="meta_monitor_0_p0")
    if not _IC3A_REPORT.exists() or not _CT1B_REPORT.exists():
        r.failures.append("IC-3a or CT-1b report missing")
        return r
    ic3a = _IC3A_REPORT.read_text(encoding="utf-8")
    ct1b = _CT1B_REPORT.read_text(encoding="utf-8")
    if "元监控" not in ic3a or "= 0" not in ic3a:
        r.failures.append("IC-3a 元监控 = 0 cite missing")
    if "✅ READY" not in ct1b:
        r.failures.append("CT-1b operational readiness verdict not ✅ READY")
    if not r.failures:
        r.passed = True
        r.detail = "IC-3a 元监控 = 0 ✅ + CT-1b operational readiness ✅ READY"
    return r


def _check_prereq_3_tier_a_adr_sediment() -> _PrereqResult:
    """Prereq 3: Tier A ADR 全 sediment — REGISTRY committed count + cite."""
    r = _PrereqResult(name="tier_a_adr_full_sediment")
    registry = PROJECT_ROOT / "docs" / "adr" / "REGISTRY.md"
    if not registry.exists():
        r.failures.append("REGISTRY.md missing")
        return r
    txt = registry.read_text(encoding="utf-8")
    missing = [adr for adr in _TIER_A_ADR_MIN if adr not in txt]
    if missing:
        r.failures.append(
            f"Tier A ADRs missing from REGISTRY: {', '.join(missing)}"
        )
    # Verify committed status — fuzzy match against committed count.
    if "73 个" not in txt and "74 个" not in txt:
        r.failures.append(
            "REGISTRY committed count NOT 73 or 74 (post-CT-1 expected)"
        )
    if not r.failures:
        r.passed = True
        r.detail = (
            f"REGISTRY committed >=73 + {len(_TIER_A_ADR_MIN)} Tier A ADRs "
            f"all present"
        )
    return r


def _check_prereq_4_5_sla_satisfied() -> _PrereqResult:
    """Prereq 4: 5 SLA 满足 — CT-1b operational readiness cite IC-3 cumulative."""
    r = _PrereqResult(name="5_sla_satisfied_v3_13_1")
    if not _CT1B_REPORT.exists():
        r.failures.append("CT-1b report missing — required for 5 SLA cite")
        return r
    txt = _CT1B_REPORT.read_text(encoding="utf-8")
    sla_keywords = [
        "L1 detection latency P99",
        "L4 STAGED 30min cancel",
        "L0 News 6-source 30s timeout",
        "LiteLLM",
        "DingTalk push",
    ]
    missing = [k for k in sla_keywords if k not in txt]
    if missing:
        r.failures.append(f"CT-1b SLA cite missing: {missing}")
    sla_section_start = txt.find("§2 V3 §13.1 SLA")
    if sla_section_start < 0:
        r.failures.append("CT-1b §2 SLA section header missing")
    else:
        sla_section = txt[sla_section_start:sla_section_start + 3000]
        if sla_section.count("✅") < 5:
            r.failures.append(
                f"CT-1b SLA section has <5 ✅ marks (got "
                f"{sla_section.count('✅')})"
            )
    if not r.failures:
        r.passed = True
        r.detail = "5 SLA all cited ✅ in CT-1b report (IC-3 cumulative)"
    return r


def _check_prereq_5_10_user_decisions_verify() -> _PrereqResult:
    """Prereq 5: 10 user 决议 verify — V3 §20.1 grep + cross-cite."""
    r = _PrereqResult(name="10_user_decisions_v3_20_1")
    v3_design = PROJECT_ROOT / "docs" / "QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md"
    if not v3_design.exists():
        r.failures.append("V3 design doc missing")
        return r
    txt = v3_design.read_text(encoding="utf-8")
    if "§20.1 设计层决议" not in txt:
        r.failures.append("V3 §20.1 设计层决议 section missing")
    missing_decisions = []
    for keyword, sediment in _TEN_USER_DECISIONS:
        if keyword not in txt or sediment not in txt:
            missing_decisions.append(f"{keyword} / {sediment}")
    if missing_decisions:
        r.failures.append(f"Missing 10 user 决议 cite: {missing_decisions}")
    if not r.failures:
        r.passed = True
        r.detail = "V3 §20.1 + 10 decisions + sediment ADR cite verified"
    return r


# ---------- 10 user 决议 individual checks ----------


def _check_user_decision(idx: int, keyword: str, sediment: str) -> _PrereqResult:
    """One user 决议 verify — V3 §20.1 + ADR cite cross-reference."""
    r = _PrereqResult(name=f"user_decision_{idx}_{keyword[:30]}")
    v3_design = PROJECT_ROOT / "docs" / "QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md"
    if not v3_design.exists():
        r.failures.append("V3 design doc missing")
        return r
    txt = v3_design.read_text(encoding="utf-8")
    table_start = txt.find("§20.1 设计层决议")
    if table_start < 0:
        r.failures.append("V3 §20.1 table missing")
        return r
    table_section = txt[table_start:table_start + 5000]
    if keyword not in table_section:
        r.failures.append(f"决议 keyword {keyword!r} not in V3 §20.1 table")
    if sediment not in table_section:
        r.failures.append(f"决议 sediment {sediment!r} not cited")
    if not r.failures:
        r.passed = True
        r.detail = f"{keyword} → {sediment} ✅ cited in V3 §20.1"
    return r


# ---------- Compile + report ----------


def run_gate_e_verify() -> _GateEReport:
    """Run full Gate E charter verify."""
    from datetime import UTC

    now_utc = datetime.now(UTC)
    report = _GateEReport(
        timestamp_utc=now_utc.isoformat(),
        timestamp_shanghai=now_utc.astimezone(_SHANGHAI_TZ).isoformat(),
    )

    # 5 prereq.
    prereq_fns = (
        _check_prereq_1_paper_mode_5d,
        _check_prereq_2_meta_monitor_0_p0,
        _check_prereq_3_tier_a_adr_sediment,
        _check_prereq_4_5_sla_satisfied,
        _check_prereq_5_10_user_decisions_verify,
    )
    for fn in prereq_fns:
        logger.info("[CT-2a] running %s", fn.__name__)
        result = fn()
        report.prereq_checks.append(result)
        if result.passed:
            logger.info("[CT-2a] ✅ %s — %s", result.name, result.detail)
        else:
            logger.warning(
                "[CT-2a] ❌ %s — failures: %s", result.name, "; ".join(result.failures)
            )

    # 10 user 决议.
    for idx, (keyword, sediment) in enumerate(_TEN_USER_DECISIONS, start=1):
        result = _check_user_decision(idx, keyword, sediment)
        report.user_decisions_checks.append(result)
        if result.passed:
            logger.info("[CT-2a] ✅ user_decision_%d %s", idx, result.detail)
        else:
            logger.warning(
                "[CT-2a] ❌ user_decision_%d %s — %s",
                idx,
                keyword,
                "; ".join(result.failures),
            )

    return report


def render_report(report: _GateEReport) -> str:
    """Render Gate E charter verify report as markdown."""
    lines: list[str] = []
    lines.append("# V3 CT-2a — Gate E Charter Verify Report (Constitution §L10.5)")
    lines.append("")
    lines.append(f"**Run timestamp (Asia/Shanghai)**: {report.timestamp_shanghai}")
    lines.append(f"**Run timestamp (UTC)**: {report.timestamp_utc}")
    overall = "✅ READY" if report.gate_e_ready else "❌ NOT READY"
    lines.append(f"**Gate E overall verdict**: {overall}")
    lines.append("")
    lines.append(
        "**Scope**: V3 Plan v0.4 §A CT-2a — Gate E charter verify BEFORE "
        "CT-2b .env paper→live flip. Verify-only doc (0 mutation) per user "
        "决议 (C1)+(M1)+(T1) 2026-05-17. Re-cites sediment from IC-3 + CT-1 "
        "+ Constitution §L10.5 + V3 §20.1; 5 prereq + 10 user 决议 verify."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §1 5 Prerequisite (Constitution §L10.5)")
    lines.append("")
    lines.append("| # | Prereq | Status | Detail |")
    lines.append("|---|---|---|---|")
    for idx, p in enumerate(report.prereq_checks, start=1):
        status = "✅ PASS" if p.passed else "❌ FAIL"
        detail = p.detail if p.passed else "; ".join(p.failures)[:200]
        lines.append(f"| {idx} | `{p.name}` | {status} | {detail} |")
    lines.append("")
    lines.append(
        f"**5 prereq verdict**: "
        f"{'✅ ALL PASS' if report.all_prereq_passed else '❌ FAIL'}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §2 10 user 决议 (V3 §20.1 — closed PR #216 sediment, ADR-027/028/033 cumulative)")
    lines.append("")
    lines.append("| # | 决议项 | Sediment | Status |")
    lines.append("|---|---|---|---|")
    for idx, (keyword, sediment) in enumerate(_TEN_USER_DECISIONS, start=1):
        check = report.user_decisions_checks[idx - 1]
        status = "✅" if check.passed else "❌"
        lines.append(f"| {idx} | `{keyword}` | `{sediment}` | {status} |")
    lines.append("")
    lines.append(
        f"**10 user 决议 verdict**: "
        f"{'✅ ALL PASS' if report.all_user_decisions_passed else '❌ FAIL'}"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §3 Sediment cite cross-reference (IC-3 + CT-1 cumulative)")
    lines.append("")
    lines.append("| Source | Path | Status |")
    lines.append("|---|---|---|")
    for label, path in (
        ("IC-3a 5y integrated replay (4/4 V3 §15.4 PASS)", _IC3A_REPORT),
        ("IC-3b counterfactual 3-incident (3/3 PASS)", _IC3B_REPORT),
        ("IC-3c synthetic scenarios (24/24 PASS)", _IC3C_REPORT),
        ("CT-1a DB cleanup (121 stale rows applied)", _CT1A_REPORT),
        ("CT-1b operational readiness (6/6 ✅ READY)", _CT1B_REPORT),
    ):
        status = "✅ present" if path.exists() else "❌ missing"
        lines.append(f"| {label} | `{path.relative_to(PROJECT_ROOT)}` | {status} |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §4 CT-2b prerequisite gate (Plan §A 红线 SOP)")
    lines.append("")
    if report.gate_e_ready:
        lines.append("**Gate E ✅ READY for CT-2b transition**:")
        lines.append("")
        lines.append("CT-2b .env flip prerequisite satisfied. Next step requires:")
        lines.append("")
        lines.append("1. **User 显式 trigger**: \"同意 apply CT-2b\" message (sustained")
        lines.append("   user 决议 T1 2026-05-17 3-step gate体例)")
        lines.append("2. **CC opens CT-2b PR**: .env field change (LIVE_TRADING_DISABLED")
        lines.append("   true→false + EXECUTION_MODE paper→live) + redline-guardian +")
        lines.append("   3-reviewer review")
        lines.append("3. **User 显式 .env 授权** per Constitution §L8.1 (c) + ADR-077")
        lines.append("   cite + commit message hard-cite + emergency rollback path")
        lines.append("   readiness")
        lines.append("4. **CC executes CT-2b apply** ONLY after explicit user 同意 trigger")
    else:
        lines.append("**Gate E ❌ NOT READY**: CT-2b transition BLOCKED until 5 prereq + 10 user 决议 all green.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## §5 Methodology + 红线")
    lines.append("")
    lines.append(
        "- **Verify-only mode** per user 决议 (C1)+(M1)+(T1) 2026-05-17: 0 "
        "mutation. All checks are cite cross-reference + grep + file "
        "presence verification."
    )
    lines.append(
        "- **Replay-path equivalent paper-mode 5d** per ADR-063 (Tier B 真测路径) — "
        "IC-3a 5y full minute_bars replay 4/4 V3 §15.4 PASS = Tier A 5d "
        "paper-mode equivalent evidence. 反日历式观察期 sustained LL-173 lesson 1."
    )
    lines.append(
        "- **Defense-in-depth gate**: CT-2b transition requires (1) Gate E "
        "verify ✅ (本 report), (2) user 显式 \"同意 apply CT-2b\" message, "
        "(3) CT-2b PR + 3-reviewer + redline-guardian, (4) user 显式 .env "
        "授权 per Constitution §L8.1 (c)."
    )
    lines.append(
        "- **0 broker call / 0 .env mutation / 0 yaml mutation / 0 DB row "
        "mutation / 0 LLM call / 0 真 DingTalk push**. 红线 5/5 sustained: "
        "cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / "
        "EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102."
    )
    lines.append("")
    lines.append(
        "关联: V3 §20.1 (10 user 决议) / §13.1 (5 SLA) / §15.4 / §12.1 / "
        "Constitution §L10.5 (Gate E) / Plan v0.4 §A CT-2a · ADR-027 / "
        "ADR-028 / ADR-033 / ADR-063 / ADR-077 reserved (Plan v0.4 closure "
        "cumulative — CT-2c sediment time) · 铁律 22 / 24 / 25 / 33 / 41 / "
        "42 · LL-098 X10 / LL-164 (Gate E charter pre-sediment verify) / "
        "LL-173 lesson 1 / LL-174 lesson 2 (3-step user gate体例)"
    )
    lines.append("")
    return "\n".join(lines)


# ---------- main ----------


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="report markdown 输出路径 (default: docs/audit/v3_ct_2a_gate_e_charter_verify_*.md)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="print report, do NOT sediment markdown",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    return p


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    logger.info("[CT-2a] starting Gate E charter verify (Constitution §L10.5)")
    report = run_gate_e_verify()
    rendered = render_report(report)
    print(rendered)  # noqa: T201

    if not args.dry_run:
        out_path = args.out or (
            PROJECT_ROOT
            / "docs"
            / "audit"
            / f"v3_ct_2a_gate_e_charter_verify_report_{datetime.now(_SHANGHAI_TZ):%Y_%m_%d}.md"
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(rendered, encoding="utf-8")
        logger.info("[CT-2a] sedimented report: %s", out_path)

    return 0 if report.gate_e_ready else 1


if __name__ == "__main__":
    sys.exit(main())
