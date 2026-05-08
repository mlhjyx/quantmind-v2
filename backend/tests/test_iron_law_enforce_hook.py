"""V3 step 4 sub-PR 6 — iron_law_enforce.py v2 扩展 hook smoke tests.

scope (V3 step 4 sub-PR 6 atomic sediment+wire 沿用 LL-117 候选 promote trigger sustained
满足 6 PR 实证累积 PR #276/#280/#281/#282/#283 + 本):
- v2 marker present (V3 实施期扩展 cite)
- v1 sustained: 铁律 2/4/5/6/8/11 + check_pt_protection (反 silent overwrite ADR-022)
- v2 扩展 3/3 类静态可达 (sustained Q3 (β)):
  - V3 §11 12 模块 fail-open detect (production engines path + fail_open=True/裸 except: pass)
  - 铁律 44 X9 Beat schedule 注释 ≠ 停服 detect (celery_beat / beat_schedule path)
  - memory #19/#20 prompt 设计 hardcoded command detect (prompts/risk/*.yaml)
- action mode sustained user Q1 (α) — WARN-only sys.exit(0) + hookSpecificOutput.additionalContext
- fail-soft on parse error / 0 file_path

Phase 1 narrowed scope (沿用 PR #280/#281/#282/#283 LL-130 体例累积 + Constitution §L6.2 line
280-282 决议 + skeleton §3.2 line 304):
- v2 hook 静态 detect 3/3 类 trigger pattern; full SOP 走 quantmind-v3-anti-pattern-guard /
  quantmind-v3-prompt-design-laws skill SOP active CC invoke
- 真账户红线 deferred to redline_pretool_block.py (PR #276) 0 重叠扩展 (sustained Q3 (β) 1/4 类)

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only):
- Constitution §L6.2 line 280 (anti-prompt-design-violation-pretool 合并到 iron_law_enforce 决议)
- Constitution §L6.2 line 282 (4 全新 + 4 现有扩展, ADR-022 反 silent overwrite)
- skeleton §3.2 line 304 (现有 hook 扩展真值)
- 铁律 44 X9 (Beat schedule 注释 ≠ 停服)
- memory #19/#20 (prompt 设计 broader 47/53+ enforcement layer)
- skill quantmind-v3-anti-pattern-guard (PR #275)
- skill quantmind-v3-prompt-design-laws (PR #275)
- LL-130 候选 + LL-133 候选 cumulative
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "iron_law_enforce.py"


def _run_hook(payload: dict | None = None) -> tuple[int, str, str]:
    """Run hook subprocess with JSON stdin, return (rc, stdout, stderr).

    sustained user Q1 (α) — WARN-only sys.exit(0) + hookSpecificOutput.additionalContext
    (反 BLOCK exit 2 体例).
    """
    payload_json = json.dumps(payload or {})
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload_json,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _edit(file_path: str, old: str, new: str) -> dict:
    return {
        "tool_name": "Edit",
        "tool_input": {"file_path": file_path, "old_string": old, "new_string": new},
    }


def _write(file_path: str, content: str) -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


# ── v2 marker + action mode sustained ──


def test_v2_marker_in_docstring() -> None:
    """v2 hook output structure verify + v2 marker present in source."""
    source = HOOK.read_text(encoding="utf-8")
    assert "v2 2026-05-09 V3 实施期扩展" in source, "missing v2 marker"
    assert "Q1 (α)" in source, "missing user Q1 (α) decision cite"
    assert "Q3 (β)" in source, "missing user Q3 (β) decision cite"
    assert "ADR-022" in source, "missing ADR-022 cite"


def test_action_mode_warn_only_sustained() -> None:
    """sustained user Q1 (α) — iron_law_enforce v2 sustained WARN-only sys.exit(0).

    sustained 现 v1 真值 + ADR-022 反 silent overwrite + PR #280-#283 四 PR WARN ALLOW 体例累积一致.
    任 input → exit 0 (反 BLOCK exit 2 体例).
    """
    # Empty input
    rc, _, _ = _run_hook()
    assert rc == 0, "empty input should sys.exit(0) sustained Q1 (α)"
    # File path triggering issue
    rc, _, _ = _run_hook(
        _write(
            "backend/engines/risk_engine.py",
            "fail_open = True\n# missing silent_ok",
        )
    )
    assert rc == 0, "issue trigger should still sys.exit(0) sustained Q1 (α) WARN-only"


# ── v1 sustained ──


def test_v1_law_2_verify_code_sustained() -> None:
    """v1 sustained: 铁律 2 conclusion 文档 sans evidence."""
    rc, out, _ = _run_hook(
        _write(
            "docs/some_decision.md",
            "## 结论\n\n这个方案 PASS\n",
        )
    )
    assert rc == 0
    assert "铁律 2" in out


def test_v1_law_4_neutralize_sustained() -> None:
    """v1 sustained: 铁律 4 因子测试 sans neutralize."""
    rc, out, _ = _run_hook(
        _write(
            "tests/test_my_factor_ic.py",
            "def test_compute_ic():\n    pass  # 验证 ic\n",
        )
    )
    assert rc == 0
    assert "铁律 4" in out


def test_v1_pt_protection_sustained() -> None:
    """v1 sustained: PT 核心链路文件保护."""
    rc, out, _ = _run_hook(
        _edit("backend/app/services/signal_service.py", "old", "new")
    )
    assert rc == 0
    assert "PT 核心链路" in out


# ── v2 V3 §11 fail-open detect ──


def test_v2_v3_module_fail_open_true_detected() -> None:
    """V3 §11 fail-open detect: backend/engines/risk_*.py 含 fail_open=True 触发 WARN."""
    rc, out, _ = _run_hook(
        _write(
            "backend/engines/risk_decision/decider.py",
            "def decide():\n    fail_open = True\n    return 0\n",
        )
    )
    assert rc == 0
    assert "V3 §11" in out
    assert "fail-open" in out


def test_v2_v3_module_fail_open_silent_ok_whitelist() -> None:
    """V3 §11 fail-open detect: # silent_ok 注释 whitelist 触发 0 issue (沿用铁律 33)."""
    rc, out, _ = _run_hook(
        _write(
            "backend/engines/risk_engine/core.py",
            "def safe_call():\n    fail_open = True  # silent_ok: explicit safe fallback\n",
        )
    )
    assert rc == 0
    assert "V3 §11" not in out, f"silent_ok whitelist should suppress, got: {out!r}"


def test_v2_v3_module_bare_except_pass_detected() -> None:
    """V3 §11 fail-open detect: 裸 except: pass pattern 触发 WARN."""
    rc, out, _ = _run_hook(
        _write(
            "backend/engines/alert/router.py",
            "def send():\n    try:\n        x()\n    except:\n        pass\n",
        )
    )
    assert rc == 0
    assert "V3 §11" in out


def test_v2_v3_module_outside_scope_no_trigger() -> None:
    """V3 §11 fail-open detect: 非 V3 module path (backend/app/) 反 trigger."""
    rc, out, _ = _run_hook(
        _write(
            "backend/app/main.py",
            "fail_open = True\nexcept:\n    pass\n",
        )
    )
    assert rc == 0
    assert "V3 §11" not in out, f"non-V3 path should not trigger, got: {out!r}"


# ── v2 Beat schedule 注释 detect ──


def test_v2_beat_schedule_comment_detected() -> None:
    """铁律 44 X9: celery_beat.py 含注释 schedule entry 触发 WARN."""
    rc, out, _ = _run_hook(
        _write(
            "backend/app/celery_beat.py",
            "beat_schedule = {\n    # 'old_task': {'schedule': 60},\n    'new_task': {'schedule': 30},\n}\n",
        )
    )
    assert rc == 0
    assert "铁律 44 X9" in out
    assert "Beat schedule 注释" in out


def test_v2_beat_schedule_no_comment_no_trigger() -> None:
    """铁律 44 X9: beat 文件 sans 注释 entry → 0 trigger."""
    rc, out, _ = _run_hook(
        _write(
            "backend/app/celery_beat.py",
            "beat_schedule = {\n    'task_a': {'schedule': 60},\n    'task_b': {'schedule': 30},\n}\n",
        )
    )
    assert rc == 0
    assert "铁律 44 X9" not in out


def test_v2_beat_schedule_outside_scope_no_trigger() -> None:
    """铁律 44 X9: 非 beat 文件 (随便 .py) 含注释 dict-like 反 trigger."""
    rc, out, _ = _run_hook(
        _write(
            "backend/app/services/normal.py",
            "config = {\n    # 'commented': {'foo': 'bar'},\n}\n",
        )
    )
    assert rc == 0
    assert "铁律 44 X9" not in out


# ── v2 prompt 设计 0 hardcoded command detect ──


def test_v2_prompt_design_hardcoded_command_detected() -> None:
    """memory #19/#20: prompts/risk/*.yaml 含 hardcoded shell command 触发 WARN."""
    rc, out, _ = _run_hook(
        _write(
            "prompts/risk/test_classifier.yaml",
            "instructions: |\n  Run `python scripts/classify.py --input news.json`\n",
        )
    )
    assert rc == 0
    assert "memory #19/#20" in out
    assert "hardcoded shell command" in out


def test_v2_prompt_design_no_hardcode_no_trigger() -> None:
    """memory #19/#20: prompts/risk/*.yaml sans hardcoded command → 0 trigger."""
    rc, out, _ = _run_hook(
        _write(
            "prompts/risk/test_clean.yaml",
            "version: v1\ndescription: Clean prompt template\nschema:\n  - sentiment_score\n",
        )
    )
    assert rc == 0
    assert "memory #19/#20" not in out


def test_v2_prompt_design_outside_scope_no_trigger() -> None:
    """memory #19/#20: 非 prompts/risk/*.yaml 含合法 command example 反 trigger
    (反 false positive on .claude/CLAUDE.md / docs)."""
    rc, out, _ = _run_hook(
        _edit(
            ".claude/CLAUDE.md",
            "old",
            "Run `python scripts/health_check.py` to verify",
        )
    )
    assert rc == 0
    assert "memory #19/#20" not in out, "non-prompt path should not trigger"


# ── 边界 graceful ──


def test_no_file_path_pass() -> None:
    """0 file_path → fail-soft sys.exit(0) sustained."""
    rc, _, _ = _run_hook({"tool_input": {}})
    assert rc == 0


def test_malformed_json_fail_soft() -> None:
    """malformed JSON stdin → fail-soft sys.exit(0)."""
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
