"""Tests for V3 Plan v0.4 CT-2b — .env paper→live flip apply runner.

Scope (PURE / fixture-driven; 0 production .env hit):
  - _EnvFieldState / _FlipResult dataclass invariants
  - .env field parsing (line-by-line + key=value extraction)
  - Preflight verify semantics (passing + 3 drift scenarios)
  - Atomic flip apply logic (using tempfile fixture .env)
  - Post-flip verify
  - Rollback re-apply from snapshot

Out of scope (integration-only, exercised by `python
scripts/v3_ct_2b_env_flip_apply.py --apply` at user 同意 moment):
  - Real backend/.env mutation

关联铁律: 25 (改什么读什么) / 33 (fail-loud) / 35 (.env secrets) /
  40 (test debt) / 41
关联 Plan: V3_PT_CUTOVER_PLAN_v0.1.md §A CT-2b
关联 LL: LL-098 X10 / LL-174 lesson 2 (3-step user gate体例)
"""

# ruff: noqa: E402

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


from v3_ct_2b_env_flip_apply import (
    _ENV_FLIPS,
    _ENV_SUSTAINED,
    _apply_flip,
    _capture_snapshot,
    _EnvFieldState,
    _FlipResult,
    _read_env_field_states,
    _rollback_from_snapshot,
    _verify_post_flip,
    _verify_preflight,
    _write_snapshot_atomic,
)

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────


class TestConstants:
    def test_env_flips_count_exactly_2(self) -> None:
        """Plan §A row 95: 双 .env field 改 — exactly 2 flips per scope."""
        assert len(_ENV_FLIPS) == 2

    def test_env_flips_are_paper_to_live_transition(self) -> None:
        flip_dict = {f: (pre, post) for f, pre, post in _ENV_FLIPS}
        assert flip_dict["LIVE_TRADING_DISABLED"] == ("true", "false")
        assert flip_dict["EXECUTION_MODE"] == ("paper", "live")

    def test_qmt_account_id_sustained_not_flipped(self) -> None:
        """QMT_ACCOUNT_ID stays at 81001102 (sustained 红线)."""
        sustained_dict = dict(_ENV_SUSTAINED)
        assert sustained_dict["QMT_ACCOUNT_ID"] == "81001102"


# ─────────────────────────────────────────────────────────────
# _EnvFieldState + _FlipResult
# ─────────────────────────────────────────────────────────────


class TestDataclasses:
    def test_env_field_state_defaults(self) -> None:
        s = _EnvFieldState(field="X")
        assert s.field == "X"
        assert s.current_value is None
        assert s.expected_value == ""
        assert s.line_number is None

    def test_flip_result_defaults(self) -> None:
        r = _FlipResult()
        assert r.preflight_passed is False
        assert r.apply_executed is False
        assert r.post_verify_passed is False
        assert r.failures == []
        assert r.snapshot_path is None


# ─────────────────────────────────────────────────────────────
# _read_env_field_states
# ─────────────────────────────────────────────────────────────


class TestReadEnvFieldStates:
    def _make_env(self, tmp_path: Path, content: str) -> Path:
        env = tmp_path / ".env"
        env.write_text(content, encoding="utf-8")
        return env

    def test_reads_target_fields(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            "# comment\nKEY_A=val_a\nKEY_B=val_b\n# more\nKEY_C=val_c\n",
        )
        states = _read_env_field_states(env, ("KEY_A", "KEY_B"))
        assert states["KEY_A"].current_value == "val_a"
        assert states["KEY_A"].line_number == 2
        assert states["KEY_B"].current_value == "val_b"
        assert states["KEY_B"].line_number == 3

    def test_missing_field_has_none_value(self, tmp_path: Path) -> None:
        env = self._make_env(tmp_path, "KEY_A=val_a\n")
        states = _read_env_field_states(env, ("KEY_A", "MISSING"))
        assert states["MISSING"].current_value is None

    def test_skips_comments_and_blank_lines(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            "# header comment\n\nKEY_A=val_a\n\n# more comment\n",
        )
        states = _read_env_field_states(env, ("KEY_A",))
        assert states["KEY_A"].current_value == "val_a"
        assert states["KEY_A"].line_number == 3

    def test_raises_filenotfound_if_missing(self, tmp_path: Path) -> None:
        import pytest

        with pytest.raises(FileNotFoundError, match=".env file not found"):
            _read_env_field_states(tmp_path / "nonexistent.env", ("X",))


# ─────────────────────────────────────────────────────────────
# _verify_preflight
# ─────────────────────────────────────────────────────────────


class TestVerifyPreflight:
    def _make_env(self, tmp_path: Path, lines: list[str]) -> Path:
        env = tmp_path / ".env"
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return env

    def test_passes_when_all_pre_flip_state_correct(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            [
                "QMT_ACCOUNT_ID=81001102",
                "EXECUTION_MODE=paper",
                "LIVE_TRADING_DISABLED=true",
            ],
        )
        ok, states, failures = _verify_preflight(env)
        assert ok is True
        assert failures == []
        # 3 fields: 2 flips + 1 sustained.
        assert len(states) == 3

    def test_fails_when_already_flipped(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            [
                "QMT_ACCOUNT_ID=81001102",
                "EXECUTION_MODE=live",  # already flipped
                "LIVE_TRADING_DISABLED=false",  # already flipped
            ],
        )
        ok, _, failures = _verify_preflight(env)
        assert ok is False
        # Both flips fail preflight (already at post-flip values).
        assert any("LIVE_TRADING_DISABLED" in f for f in failures)
        assert any("EXECUTION_MODE" in f for f in failures)

    def test_fails_when_qmt_account_id_drift(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            [
                "QMT_ACCOUNT_ID=99999999",  # wrong account!
                "EXECUTION_MODE=paper",
                "LIVE_TRADING_DISABLED=true",
            ],
        )
        ok, _, failures = _verify_preflight(env)
        assert ok is False
        assert any("QMT_ACCOUNT_ID" in f for f in failures)

    def test_fails_when_field_missing(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            ["QMT_ACCOUNT_ID=81001102", "EXECUTION_MODE=paper"],
        )
        ok, _, failures = _verify_preflight(env)
        assert ok is False
        assert any("LIVE_TRADING_DISABLED" in f for f in failures)


# ─────────────────────────────────────────────────────────────
# _apply_flip + _verify_post_flip
# ─────────────────────────────────────────────────────────────


class TestApplyFlip:
    def _make_env(self, tmp_path: Path, lines: list[str]) -> Path:
        env = tmp_path / ".env"
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return env

    def test_flips_2_fields_atomically(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            [
                "# comment line",
                "QMT_ACCOUNT_ID=81001102",
                "EXECUTION_MODE=paper",
                "# another comment",
                "LIVE_TRADING_DISABLED=true",
                "OTHER_KEY=other_val",
            ],
        )
        _apply_flip(env)
        new_text = env.read_text(encoding="utf-8")
        assert "EXECUTION_MODE=live" in new_text
        assert "EXECUTION_MODE=paper" not in new_text
        assert "LIVE_TRADING_DISABLED=false" in new_text
        assert "LIVE_TRADING_DISABLED=true" not in new_text
        # Unrelated fields preserved.
        assert "QMT_ACCOUNT_ID=81001102" in new_text
        assert "OTHER_KEY=other_val" in new_text
        assert "# comment line" in new_text

    def test_post_verify_passes_after_flip(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            [
                "QMT_ACCOUNT_ID=81001102",
                "EXECUTION_MODE=paper",
                "LIVE_TRADING_DISABLED=true",
            ],
        )
        _apply_flip(env)
        ok, states, failures = _verify_post_flip(env)
        assert ok is True
        assert failures == []
        post_dict = {s.field: s.current_value for s in states}
        assert post_dict["LIVE_TRADING_DISABLED"] == "false"
        assert post_dict["EXECUTION_MODE"] == "live"

    def test_raises_if_field_value_drift_mid_apply(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            [
                "EXECUTION_MODE=unknown",  # neither paper nor live
                "LIVE_TRADING_DISABLED=true",
            ],
        )
        import pytest

        with pytest.raises(ValueError, match="value drift mid-apply|not found"):
            _apply_flip(env)


# ─────────────────────────────────────────────────────────────
# _capture_snapshot + _write_snapshot_atomic + _rollback
# ─────────────────────────────────────────────────────────────


class TestSnapshotAndRollback:
    def _make_env(self, tmp_path: Path, content: str) -> Path:
        env = tmp_path / ".env"
        env.write_text(content, encoding="utf-8")
        return env

    def test_snapshot_captures_full_env_content(self, tmp_path: Path) -> None:
        env = self._make_env(tmp_path, "QMT_ACCOUNT_ID=81001102\nEXECUTION_MODE=paper\n")
        states = [_EnvFieldState(field="EXECUTION_MODE", current_value="paper")]
        snap = _capture_snapshot(env, states)
        assert "env_full_content" in snap
        assert snap["env_full_content"] == env.read_text(encoding="utf-8")
        assert "field_states" in snap
        assert "captured_at_utc" in snap

    def test_atomic_write_roundtrips(self, tmp_path: Path) -> None:
        out = tmp_path / "snap.json"
        snap = {"a": 1, "b": [1, 2, 3]}
        _write_snapshot_atomic(snap, out)
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert loaded == snap

    def test_rollback_restores_original_env(self, tmp_path: Path) -> None:
        env = self._make_env(
            tmp_path,
            "QMT_ACCOUNT_ID=81001102\nEXECUTION_MODE=paper\nLIVE_TRADING_DISABLED=true\n",
        )
        original = env.read_text(encoding="utf-8")

        # Capture snapshot.
        snap = {
            "captured_at_utc": "x",
            "env_full_content": original,
            "field_states": [],
        }
        snap_path = tmp_path / "snap.json"
        snap_path.write_text(json.dumps(snap), encoding="utf-8")

        # Apply flip + verify modified.
        _apply_flip(env)
        modified = env.read_text(encoding="utf-8")
        assert modified != original
        assert "EXECUTION_MODE=live" in modified

        # Rollback.
        _rollback_from_snapshot(env, snap_path)
        restored = env.read_text(encoding="utf-8")
        assert restored == original

    def test_rollback_raises_if_snapshot_malformed(self, tmp_path: Path) -> None:
        env = self._make_env(tmp_path, "X=y\n")
        snap_path = tmp_path / "snap.json"
        snap_path.write_text(json.dumps({"missing_env_full_content": True}), encoding="utf-8")

        import pytest

        with pytest.raises(ValueError, match="missing env_full_content"):
            _rollback_from_snapshot(env, snap_path)
