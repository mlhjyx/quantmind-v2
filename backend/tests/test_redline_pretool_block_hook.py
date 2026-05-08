"""V3 step 4 sub-PR 1 — redline_pretool_block.py hook smoke tests.

scope (V3 step 4 atomic sediment+wire 沿用 LL-117 reverse case lesson 反向):
- BLOCK 沿用: broker call (xtquant order_stock / place_order / cancel / sell / buy)
- BLOCK 沿用: 真账户 .env field mutation (LIVE_TRADING_DISABLED / EXECUTION_MODE /
  QMT_ACCOUNT_ID via setx / $env: / export)
- BLOCK 沿用: 真生产 yaml direct mutation (configs/pt_live.yaml /
  config/litellm_router.yaml via >>, >, Add-Content, Set-Content)
- BLOCK 沿用: live-mode 真发单 script (run_paper_trading --live / --mode live)
- WARN 沿用: DB row mutation (psql INSERT/UPDATE/DELETE on trade_log /
  risk_event_log / llm_cost_daily / llm_call_log) — ALLOW-with-WARN
- ALLOW 沿用: 普通命令 + paper-mode 命令 + bypass marker

bypass 体例 (沿用 quantmind-v3-redline-verify skill §3 SSOT):
- env var QM_REDLINE_BYPASS=1
- per-command marker `# qm-redline-allow:<reason>`

关联铁律: 33 (fail-loud / fail-safe / silent_ok 三选一) / 42 (PR 分级审查制)
关联 SSOT: Constitution §L6.2 redline-pretool-block 决议 + §L8.1 (b) 真生产红线 user
介入 + LL-117 候选 + skill quantmind-v3-redline-verify (PR #273)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOK_PATH = (
    Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "redline_pretool_block.py"
)


def _run_hook(command: str, env_override: dict | None = None) -> tuple[int, str, str]:
    """Run hook with mock Bash tool input.

    Returns (returncode, stdout, stderr). 0=allow (含 WARN-with-PASS via stdout JSON),
    2=block.
    """
    payload = json.dumps({"tool_input": {"command": command}})
    env = os.environ.copy()
    # Strip any existing bypass to ensure deterministic test behavior
    env.pop("QM_REDLINE_BYPASS", None)
    if env_override:
        env.update(env_override)
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return result.returncode, result.stdout, result.stderr


# ── BLOCK: broker call ──


@pytest.mark.parametrize(
    "command",
    [
        "python -c 'import xtquant; xtquant.order_stock(...)'",
        "python -c 'from xtquant.xttrader import place_order'",
        "python scripts/some_script.py && xtquant.cancel_order_stock_async()",
        "python -c 'xt.sell(123)'",
        "python -c 'xt.buy(456)'",
        "python -c 'order_stock(account, code, 1.0)'",
        "python -c 'place_order(args)'",
    ],
)
def test_broker_call_blocked(command: str) -> None:
    """broker call patterns 沿用 BLOCK red-line sustained."""
    rc, _, stderr = _run_hook(command)
    assert rc == 2, f"expected BLOCK for {command!r}, stderr={stderr}"
    assert "broker_call" in stderr


# ── BLOCK: 真账户 .env field mutation ──


@pytest.mark.parametrize(
    "command",
    [
        # Lowercase canonical
        "setx LIVE_TRADING_DISABLED false",
        "setx EXECUTION_MODE live",
        "setx QMT_ACCOUNT_ID 12345678",
        "setx DINGTALK_ALERTS_ENABLED true",
        "setx L4_AUTO_MODE_ENABLED true",
        "$env:LIVE_TRADING_DISABLED = 'false'",
        "$env:EXECUTION_MODE = 'live'",
        "$env:QMT_ACCOUNT_ID = '99'",
        "export LIVE_TRADING_DISABLED=false",
        "export EXECUTION_MODE=live",
        "export QMT_ACCOUNT_ID=99",
        # Case variants (Windows shell case-insensitive — 反 silent bypass)
        "SETX LIVE_TRADING_DISABLED false",
        "Setx EXECUTION_MODE live",
        "SeTx QMT_ACCOUNT_ID 99",
    ],
)
def test_env_redline_blocked(command: str) -> None:
    """真账户 .env field mutation 沿用 BLOCK Constitution §L8.1 (b)."""
    rc, _, stderr = _run_hook(command)
    assert rc == 2, f"expected BLOCK for {command!r}, stderr={stderr}"
    assert "env_redline" in stderr


# ── BLOCK: 真生产 yaml direct mutation ──


@pytest.mark.parametrize(
    "command",
    [
        # Canonical
        "echo 'foo' >> configs/pt_live.yaml",
        "echo 'bar' > configs/pt_live.yaml",
        "echo 'baz' >> config/litellm_router.yaml",
        "Add-Content -Path configs/pt_live.yaml -Value 'x'",
        "Set-Content -Path config/litellm_router.yaml -Value 'y'",
        # Case variants (PowerShell case-insensitive — 反 silent bypass)
        "add-content -Path configs/pt_live.yaml -Value 'x'",
        "set-content -Path config/litellm_router.yaml -Value 'y'",
        "ADD-CONTENT -Path configs/pt_live.yaml -Value 'x'",
        # Trailing space + EOL boundary 沿用 (?:\s|$) anchor
        "echo 'foo' >> configs/pt_live.yaml ",
    ],
)
def test_prod_yaml_blocked(command: str) -> None:
    """真生产 yaml direct mutation via Bash 沿用 BLOCK ADR-022 反 silent overwrite."""
    rc, _, stderr = _run_hook(command)
    assert rc == 2, f"expected BLOCK for {command!r}, stderr={stderr}"
    assert "prod_yaml" in stderr


@pytest.mark.parametrize(
    "command",
    [
        # `.yaml.bak` / `.yaml.staging` etc — sidecar files NOT canonical, 反 over-match
        "echo 'foo' >> configs/pt_live.yaml.bak",
        "echo 'bar' > configs/pt_live.yaml.staging",
        "Add-Content -Path config/litellm_router.yaml.backup-2026-05-08 -Value 'x'",
    ],
)
def test_prod_yaml_sidecar_files_allowed(command: str) -> None:
    """sidecar file (.yaml.bak / .yaml.staging) 沿用 ALLOW (反 \b over-match P1-1 fix verify)."""
    rc, _, _ = _run_hook(command)
    assert rc == 0, f"expected ALLOW for sidecar {command!r}"


# ── BLOCK: live-mode broker exec script ──


@pytest.mark.parametrize(
    "command",
    [
        "python scripts/run_paper_trading.py --live",
        "python scripts/run_paper_trading.py --mode live",
    ],
)
def test_live_exec_blocked(command: str) -> None:
    """live-mode 真发单 script 沿用 BLOCK Constitution §L10.5 Gate E."""
    rc, _, stderr = _run_hook(command)
    assert rc == 2, f"expected BLOCK for {command!r}, stderr={stderr}"
    assert "live_exec" in stderr


# ── WARN: DB row mutation (ALLOW-with-WARN, sys.exit(0) + hookSpecificOutput) ──


@pytest.mark.parametrize(
    "command",
    [
        "psql -c 'INSERT INTO trade_log (col) VALUES (1)'",
        "psql -c 'UPDATE risk_event_log SET status=1'",
        "psql -c 'DELETE FROM llm_cost_daily WHERE date=\"2026-01-01\"'",
        "psql -c 'INSERT INTO llm_call_log (col) VALUES (1)'",
    ],
)
def test_db_row_mutation_warn_passes(command: str) -> None:
    """DB row mutation 沿用 ALLOW-with-WARN (hook 0 拿到 sub-PR scope, surface SOP)."""
    rc, stdout, _ = _run_hook(command)
    assert rc == 0, f"expected WARN-PASS for {command!r}"
    # hookSpecificOutput JSON contains category cite
    assert "db_row_mutation" in stdout
    assert "additionalContext" in stdout


# ── ALLOW: 普通命令 + paper-mode + bypass ──


@pytest.mark.parametrize(
    "command",
    [
        "ls -la",
        "git status",
        "pytest backend/tests/",
        "python scripts/run_paper_trading.py --mode paper",
        "python scripts/run_paper_trading.py signal --date 2026-03-25",
        "python -c 'print(1)'",
        "ruff check",
        "psql -c 'SELECT * FROM trade_log LIMIT 10'",  # SELECT 反 mutation
    ],
)
def test_safe_commands_allowed(command: str) -> None:
    """普通命令 + paper-mode + read-only SQL 沿用 ALLOW (反 false positive)."""
    rc, _, stderr = _run_hook(command)
    assert rc == 0, f"expected ALLOW for {command!r}, stderr={stderr}"


def test_empty_command_allowed() -> None:
    """空 command (e.g. malformed input) → fail-soft sys.exit(0)."""
    rc, _, _ = _run_hook("")
    assert rc == 0


def test_malformed_json_fail_soft() -> None:
    """malformed JSON stdin → fail-soft sys.exit(0) (沿用 protect_critical_files 体例)."""
    result = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input="not valid json {{{",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0


# ── BYPASS: env var ──


def test_bypass_env_var_allows_block_pattern() -> None:
    """QM_REDLINE_BYPASS=1 → ALLOW even broker call (user 显式触发 SOP)."""
    rc, _, _ = _run_hook(
        "python -c 'xtquant.order_stock(...)'",
        env_override={"QM_REDLINE_BYPASS": "1"},
    )
    assert rc == 0


def test_bypass_env_var_zero_does_not_bypass() -> None:
    """QM_REDLINE_BYPASS=0 → 反 bypass (反 silent override 沿用 Constitution §L8.1 (b))."""
    rc, _, _ = _run_hook(
        "python -c 'xtquant.order_stock(...)'",
        env_override={"QM_REDLINE_BYPASS": "0"},
    )
    assert rc == 2


# ── BYPASS: per-command marker ──


@pytest.mark.parametrize(
    "command",
    [
        "python -c 'xtquant.order_stock(...)'  # qm-redline-allow:paper-mode-mock-broker-test",
        "setx LIVE_TRADING_DISABLED true # qm-redline-allow:user-cutover-gate-E-explicit",
    ],
)
def test_bypass_per_command_marker(command: str) -> None:
    """per-command marker `# qm-redline-allow:<reason>` 沿用 ALLOW (user 显式触发)."""
    rc, _, _ = _run_hook(command)
    assert rc == 0
