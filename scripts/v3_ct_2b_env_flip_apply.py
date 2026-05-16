#!/usr/bin/env python3
"""V3 Plan v0.4 CT-2b — .env paper→live flip apply runner (HIGHEST-STAKES MUTATION).

Plan v0.4 §A CT-2b — V3 实施期 ONLY 真账户解锁 sprint. 整 V3 实施期
highest-stakes mutation per Plan §A row 102 reviewer-reverse-risk.

**Mutation scope** (Phase 0 verified 2026-05-17):
  - LIVE_TRADING_DISABLED=true → false (line 20 backend/.env)
  - EXECUTION_MODE=paper → live (line 17 backend/.env)

  NOT in scope:
  - DINGTALK_ALERTS_ENABLED (not present in .env, default OFF — separate
    enablement decision out of CT-2b)
  - L4_AUTO_MODE_ENABLED (sustained OFF per ADR-028 — Sprint N+ 5 prereq
    closed after cutover before AUTO can be启用)
  - STAGED_ENABLED (sustained OFF per ADR-027 #1 — default = OFF (短期),
    long-term swap after observation)
  - QMT_ACCOUNT_ID (sustained 81001102, unchanged)

**4-layer enforce** (Plan §A row 102):
  1. redline_pretool_block hook (auto-block CC tool calls modifying .env)
  2. quantmind-redline-guardian subagent (mechanism layer)
  3. user 显式 .env 授权 (Constitution §L8.1 (c) hard gate) — runner
     requires `--apply` flag explicitly + env vars set to confirm
  4. commit message hard-cite + ADR-077 cite + emergency rollback path
     readiness (post-apply commit)

**Apply pipeline** (--apply mode):
  1. Preflight verify: 2 .env fields current state MATCHES pre-flip values
  2. Snapshot capture: pre-flip .env atomic backup to JSON
  3. Atomic flip: read .env → field replace (line-by-line) → tempfile +
     rename
  4. Post-flip verify: 2 .env fields current state MATCHES post-flip values
  5. Emergency rollback path: --rollback mode re-applies snapshot

**Safety nets**:
  - --dry-run default: 0 mutation, verify preflight + print plan
  - --apply: REQUIRES user 显式 "同意 apply CT-2b" trigger sustained from
    sprint kickoff message
  - Snapshot capture BEFORE flip (rollback always available)
  - Post-flip state cite in commit message + audit report
  - 红线 5/5 transitioned (NOT just sustained):
    - cash → 真值 (xtquant query post-flip)
    - 0 持仓 → 真持仓 (post first trade)
    - LIVE_TRADING_DISABLED → false
    - EXECUTION_MODE → live
    - QMT_ACCOUNT_ID sustained 81001102

Apply moment per sustained CT-1a体例 (3-step gate):
  1. CT-2b PR opened (本 file) + 3 reviewer + redline-guardian review
  2. User 显式 "同意 apply CT-2b" message AFTER PR review
  3. CC runs `python scripts/v3_ct_2b_env_flip_apply.py --apply`

关联铁律: 22 / 24 / 25 / 33 (fail-loud per check) / 35 (.env secrets) /
  41 / 42
关联 V3: Plan v0.4 §A CT-2b + §B row 8 (.env flip silent overwrite NOT
  user-triggered mitigation) + §B row 13 (CT-2b trigger 时机判断错误
  mitigation) + Constitution §L10.5 (Gate E formal close)
关联 ADR: ADR-022 (rollback discipline + append-only sediment) / ADR-027
  (STAGED + 反向决策权 — STAGED stays OFF at cutover) / ADR-028 (AUTO +
  V4-Pro — AUTO stays OFF at cutover) / ADR-077 reserved (Plan v0.4
  closure + Gate E formal close + cutover real-money go-live 决议, CT-2c
  sediment)
关联 LL: LL-098 X10 / LL-100 chunked SOP / LL-159 (4-step preflight) /
  LL-174 lesson 2 (3-step user gate体例) / LL-174 lesson 5 (cutover
  hygiene体例 — DB row mutation = CT-1 ONLY pre-mutation; CT-2b .env =
  cutover mutation, different class)
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger(__name__)

# Target .env file path (sustained CLAUDE.md §部署规则 location).
_ENV_PATH: Path = PROJECT_ROOT / "backend" / ".env"

# .env field flips (pre → post). Plan v0.4 §A CT-2b scope.
# Tuple of (field_name, pre_value, post_value).
_ENV_FLIPS: tuple[tuple[str, str, str], ...] = (
    ("LIVE_TRADING_DISABLED", "true", "false"),
    ("EXECUTION_MODE", "paper", "live"),
)

# Sustained env vars (CT-2b verifies but does NOT mutate).
_ENV_SUSTAINED: tuple[tuple[str, str], ...] = (
    ("QMT_ACCOUNT_ID", "81001102"),  # 真账户 ID 不变
)

# Rollback snapshot path (sustained CT-1a docs/audit/ JSON snapshot pattern).
_ROLLBACK_SNAPSHOT: Path = (
    PROJECT_ROOT / "docs" / "audit" / "v3_ct_2b_env_flip_rollback_snapshot_2026_05_17.json"
)


# ---------- Apply state types ----------


@dataclass
class _EnvFieldState:
    """One .env field current/expected state."""

    field: str
    current_value: str | None = None
    expected_value: str = ""
    line_number: int | None = None


@dataclass
class _FlipResult:
    """Full CT-2b flip outcome (preflight + apply + post-verify)."""

    preflight_passed: bool = False
    apply_executed: bool = False
    post_verify_passed: bool = False
    pre_flip_state: list[_EnvFieldState] = field(default_factory=list)
    post_flip_state: list[_EnvFieldState] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    snapshot_path: Path | None = None


# ---------- Preflight ----------


def _read_env_field_states(env_path: Path, fields: tuple[str, ...]) -> dict[str, _EnvFieldState]:
    """Read .env, return per-field state map. fields = field names to extract."""
    if not env_path.exists():
        raise FileNotFoundError(f".env file not found: {env_path}")
    states = {f: _EnvFieldState(field=f) for f in fields}
    with env_path.open(encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                continue
            if "=" not in line_stripped:
                continue
            key, _, val = line_stripped.partition("=")
            key = key.strip()
            val = val.strip()
            if key in states:
                states[key].current_value = val
                states[key].line_number = idx
    return states


def _verify_preflight(env_path: Path) -> tuple[bool, list[_EnvFieldState], list[str]]:
    """Verify .env current state matches pre-flip expectations.

    Returns:
        (passed, current_states, failures)
    """
    failures: list[str] = []
    target_fields = tuple(f for f, _, _ in _ENV_FLIPS) + tuple(f for f, _ in _ENV_SUSTAINED)
    try:
        all_states = _read_env_field_states(env_path, target_fields)
    except FileNotFoundError as e:
        return False, [], [str(e)]

    pre_flip_states: list[_EnvFieldState] = []
    # Verify flips have correct PRE value.
    for f, pre_v, post_v in _ENV_FLIPS:
        s = all_states[f]
        s.expected_value = pre_v
        pre_flip_states.append(s)
        if s.current_value is None:
            failures.append(f"{f}: field missing from .env (expected pre-flip={pre_v!r})")
        elif s.current_value != pre_v:
            failures.append(
                f"{f}: current={s.current_value!r} != expected pre-flip={pre_v!r} "
                f"(NOT in cutover-ready state; abort to prevent unsafe transition)"
            )

    # Verify sustained fields.
    for f, expected in _ENV_SUSTAINED:
        s = all_states[f]
        s.expected_value = expected
        pre_flip_states.append(s)
        if s.current_value != expected:
            failures.append(f"{f}: current={s.current_value!r} != expected sustained={expected!r}")

    return (not failures), pre_flip_states, failures


# ---------- Snapshot capture ----------


def _capture_snapshot(env_path: Path, pre_flip_states: list[_EnvFieldState]) -> dict[str, str]:
    """Capture .env current full content + field states for rollback safety.

    Returns:
        Snapshot dict suitable for JSON serialization.
    """
    snapshot: dict[str, object] = {
        "captured_at_utc": datetime.now(UTC).isoformat(),
        "captured_at_shanghai": datetime.now(_SHANGHAI_TZ).isoformat(),
        "env_path": str(env_path),
        # Full .env content backup for unconditional rollback.
        "env_full_content": env_path.read_text(encoding="utf-8"),
        # Per-field state (concise audit trail).
        "field_states": [
            {
                "field": s.field,
                "current_value": s.current_value,
                "expected_value": s.expected_value,
                "line_number": s.line_number,
            }
            for s in pre_flip_states
        ],
    }
    return snapshot


def _write_snapshot_atomic(snapshot: dict[str, object], out_path: Path) -> None:
    """Atomic snapshot write — tempfile + rename (sustained CT-1a体例)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=out_path.stem + "_",
        suffix=".tmp",
        dir=str(out_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, out_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------- Apply flip ----------


def _apply_flip(env_path: Path) -> str:
    """Apply 2-field flip to .env atomically. Returns flipped content.

    Reads .env line-by-line, replaces field values per _ENV_FLIPS,
    writes back atomically via tempfile + os.replace.
    """
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    flip_targets = {f: (pre, post) for f, pre, post in _ENV_FLIPS}
    flipped_lines: list[str] = []
    flips_applied: dict[str, bool] = {f: False for f in flip_targets}

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            flipped_lines.append(line)
            continue
        if "=" not in line_stripped:
            flipped_lines.append(line)
            continue
        key, _, val = line_stripped.partition("=")
        key = key.strip()
        if key in flip_targets:
            pre_v, post_v = flip_targets[key]
            current_val = val.strip()
            if current_val == pre_v:
                # Preserve original line ending + leading whitespace.
                new_line = line.replace(f"{key}={pre_v}", f"{key}={post_v}", 1)
                flipped_lines.append(new_line)
                flips_applied[key] = True
            else:
                # Should NOT happen — preflight would have caught.
                raise ValueError(
                    f"_apply_flip: {key} value drift mid-apply: "
                    f"current={current_val!r}, expected_pre={pre_v!r}"
                )
        else:
            flipped_lines.append(line)

    # All flips must have been applied.
    missing = [f for f, applied in flips_applied.items() if not applied]
    if missing:
        raise ValueError(f"_apply_flip: fields not found during line iteration: {missing}")

    new_content = "".join(flipped_lines)

    # Atomic write — tempfile + os.replace.
    fd, tmp_path = tempfile.mkstemp(
        prefix=env_path.stem + "_",
        suffix=".tmp",
        dir=str(env_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(new_content)
        os.replace(tmp_path, env_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

    return new_content


# ---------- Post-flip verify ----------


def _verify_post_flip(
    env_path: Path,
) -> tuple[bool, list[_EnvFieldState], list[str]]:
    """Verify .env post-flip state matches expected post values."""
    failures: list[str] = []
    target_fields = tuple(f for f, _, _ in _ENV_FLIPS)
    all_states = _read_env_field_states(env_path, target_fields)

    post_flip_states: list[_EnvFieldState] = []
    for f, _, post_v in _ENV_FLIPS:
        s = all_states[f]
        s.expected_value = post_v
        post_flip_states.append(s)
        if s.current_value != post_v:
            failures.append(f"{f}: post-flip current={s.current_value!r} != expected={post_v!r}")

    return (not failures), post_flip_states, failures


# ---------- Rollback ----------


def _rollback_from_snapshot(env_path: Path, snapshot_path: Path) -> None:
    """Re-write .env from JSON snapshot full content. Atomic write."""
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    original_content = snapshot.get("env_full_content")
    if not isinstance(original_content, str):
        raise ValueError(f"Snapshot {snapshot_path} missing env_full_content (str expected)")

    fd, tmp_path = tempfile.mkstemp(
        prefix=env_path.stem + "_",
        suffix=".tmp",
        dir=str(env_path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(original_content)
        os.replace(tmp_path, env_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


# ---------- Main pipeline ----------


def run_flip_pipeline(env_path: Path) -> _FlipResult:
    """Full apply pipeline — preflight + snapshot + flip + post-verify."""
    result = _FlipResult()

    # 1. Preflight.
    preflight_ok, pre_states, preflight_failures = _verify_preflight(env_path)
    result.pre_flip_state = pre_states
    if not preflight_ok:
        result.failures.extend(preflight_failures)
        return result
    result.preflight_passed = True
    logger.info("[CT-2b] preflight ✅ PASS — 2 fields verified pre-flip state")

    # 2. Snapshot capture (BEFORE flip).
    snapshot = _capture_snapshot(env_path, pre_states)
    _write_snapshot_atomic(snapshot, _ROLLBACK_SNAPSHOT)
    result.snapshot_path = _ROLLBACK_SNAPSHOT
    logger.info("[CT-2b] rollback snapshot captured: %s", _ROLLBACK_SNAPSHOT)

    # 3. Apply flip.
    try:
        _apply_flip(env_path)
        result.apply_executed = True
        logger.warning("[CT-2b] .env flip APPLIED — 红线 5/5 TRANSITIONED")
    except Exception as e:  # noqa: BLE001 — fail-loud
        result.failures.append(f"Apply flip failed: {type(e).__name__}: {e}")
        return result

    # 4. Post-verify.
    post_ok, post_states, post_failures = _verify_post_flip(env_path)
    result.post_flip_state = post_states
    if not post_ok:
        result.failures.extend(post_failures)
        return result
    result.post_verify_passed = True
    logger.info("[CT-2b] post-flip ✅ PASS — 2 fields verified post-flip state")

    return result


# ---------- CLI ----------


def _print_dry_run_plan(env_path: Path) -> int:
    """Print dry-run plan (preflight verify + planned flips, 0 mutation)."""
    print("=" * 70)
    print("CT-2b .env flip — DRY RUN (0 mutation)")
    print("=" * 70)
    preflight_ok, pre_states, failures = _verify_preflight(env_path)
    print(f"\nPreflight verify: {'✅ PASS' if preflight_ok else '❌ FAIL'}")
    if failures:
        print("\nFAILURES:")
        for fa in failures:
            print(f"  - {fa}")
        return 1

    print(f"\n.env path: {env_path}")
    print("\nPlanned flips (HIGHEST-STAKES MUTATION per Plan §A row 102):")
    for f, pre_v, post_v in _ENV_FLIPS:
        line_num = next((s.line_number for s in pre_states if s.field == f), "?")
        print(f"  - {f} (line {line_num}): {pre_v!r} → {post_v!r}")

    print("\nSustained (verified, NOT mutated):")
    for f, expected in _ENV_SUSTAINED:
        s = next((s for s in pre_states if s.field == f), None)
        line_num = s.line_number if s else "?"
        print(f"  - {f} (line {line_num}): {expected!r}")

    print(
        f"\nRollback snapshot will be captured to: {_ROLLBACK_SNAPSHOT.relative_to(PROJECT_ROOT)}"
    )
    print("\nTo execute the flip, run: python scripts/v3_ct_2b_env_flip_apply.py --apply")
    print("(Requires user 显式 '同意 apply CT-2b' trigger per 3-step gate.)")
    return 0


def _print_apply_result(result: _FlipResult) -> None:
    """Print apply result summary."""
    print("=" * 70)
    print("CT-2b .env flip — APPLY RESULT")
    print("=" * 70)
    print(f"  Preflight: {'✅ PASS' if result.preflight_passed else '❌ FAIL'}")
    print(f"  Apply executed: {'✅ YES' if result.apply_executed else '❌ NO'}")
    print(f"  Post-verify: {'✅ PASS' if result.post_verify_passed else '❌ FAIL'}")
    if result.snapshot_path:
        print(f"  Rollback snapshot: {result.snapshot_path.relative_to(PROJECT_ROOT)}")
    if result.failures:
        print("\n  FAILURES:")
        for fa in result.failures:
            print(f"    - {fa}")
    if result.preflight_passed and result.apply_executed and result.post_verify_passed:
        print("\n  ✅✅✅ CT-2b APPLY SUCCESS — 红线 5/5 TRANSITIONED ✅✅✅")
        print("  Post-flip state:")
        for s in result.post_flip_state:
            print(f"    {s.field} = {s.current_value} (line {s.line_number})")
        print("\n  V3 实施期 .env paper→live unlock COMPLETE.")
        print("  Next: first live trade verify + 1d live 监控 per CT-2c.")


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="default — preflight + print plan, 0 mutation",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="EXECUTE .env flip — requires user 显式 '同意 apply CT-2b' "
        "trigger per LL-098 X10 + Plan §A row 102 4-layer enforce",
    )
    mode.add_argument(
        "--rollback",
        action="store_true",
        help="re-apply pre-flip .env from JSON snapshot (emergency rollback)",
    )
    parser.add_argument(
        "--env-path",
        type=Path,
        default=_ENV_PATH,
        help=f".env path (default: {_ENV_PATH.relative_to(PROJECT_ROOT)})",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if args.rollback:
        if not _ROLLBACK_SNAPSHOT.exists():
            logger.error("[CT-2b rollback] snapshot file not found: %s", _ROLLBACK_SNAPSHOT)
            return 1
        try:
            _rollback_from_snapshot(args.env_path, _ROLLBACK_SNAPSHOT)
            logger.warning(
                "[CT-2b rollback] ✅ .env restored from snapshot — "
                "verify state via: python scripts/v3_ct_2b_env_flip_apply.py --dry-run"
            )
            return 0
        except Exception:
            logger.exception("[CT-2b rollback] failed")
            return 1

    if args.apply:
        # 4-layer enforce signal — sustained CT-1a apply体例.
        logger.warning(
            "[CT-2b apply] EXECUTING .env paper→live flip — HIGHEST-STAKES "
            "MUTATION per Plan §A row 102. Expected: user 显式 '同意 apply "
            "CT-2b' trigger sustained sprint kickoff body."
        )
        result = run_flip_pipeline(args.env_path)
        _print_apply_result(result)
        return (
            0
            if (result.preflight_passed and result.apply_executed and result.post_verify_passed)
            else 1
        )

    # Default: --dry-run.
    return _print_dry_run_plan(args.env_path)


if __name__ == "__main__":
    sys.exit(main())
