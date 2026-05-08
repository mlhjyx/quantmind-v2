"""Harness Hook: redline pretool block — V3 5/5 红线 query layer (PreToolUse Bash).

触发: PreToolUse[Bash]
功能: Bash command 调用前 detect 真账户 / 真生产红线 mutation 模式, 反 silent
breach 沿用 5/5 红线 sustained. 互补 protect_critical_files.py (file pattern only).
退出码: 0=通过 (含 ALLOW-with-WARN), 2=阻止

scope (Phase 1, V3 step 4 sub-PR 1 sediment):
- BLOCK: broker call (xtquant order_stock / place_order / cancel / sell / buy)
- BLOCK: 真账户 .env field mutation via Bash (LIVE_TRADING_DISABLED /
  EXECUTION_MODE / QMT_ACCOUNT_ID setx / $env:)
- BLOCK: 真生产 yaml direct mutation via Bash (configs/pt_live.yaml /
  config/litellm_router.yaml Add-Content / Set-Content / >> append)
- BLOCK: live-mode 真发单 script (scripts/run_paper_trading*.py --live)
- WARN: DB row mutation via psql / python -c (sustained context-aware,
  hook 0 拿到 sub-PR scope, hookSpecificOutput surface SOP cite)

bypass 体例 (沿用 quantmind-v3-redline-verify skill §3 user 显式触发 + Constitution
§L8.1 (b) 真生产红线 user 介入 SSOT):
- env var QM_REDLINE_BYPASS=1 (session-level override, e.g. user 显式跑 paper-mode
  test 含 mock broker call)
- per-command marker `# qm-redline-allow:<reason>` (沿用 block_dangerous_git.py
  +  scripts/check_llm_imports.sh allowlist 体例 sustained)

互补 hook (沿用 Constitution §L6.2 redline-pretool-block 决议 — 跟 protect_critical_files
互补不替代):
- protect_critical_files.py (PreToolUse[Edit|Write]) — file path pattern only
- 本 hook (PreToolUse[Bash]) — Bash command 调用前 mutation 模式 detect
- quantmind-v3-redline-verify skill (CC 主动 invoke 知识层) — 5/5 红线 + 5 condition
  严核 (沿用 Constitution §L6.2 redline-verify 决议)

关联铁律: 33 (fail-loud, parse error 沿用 protect_critical_files 体例 fail-soft
              sys.exit(0) 反 break tool 调用) /
          35 (Secrets env var 唯一, 反 hardcode credentials 沿用) /
          42 (PR 分级审查制 — backend/** 必走 PR + reviewer + AI 自 merge sustained)

关联 SSOT (沿用 cite 4 元素 SSOT 锚点 only, 反 hardcoded line#):
- Constitution §L6.2 redline-pretool-block 决议 (4 全新 hook 之一)
- Constitution §L8.1 (b) 真生产红线 user 介入 3 类 enforcement
- IRONLAWS §13 铁律 33 (fail-loud / fail-safe / silent_ok 三选一)
- LL-117 候选 (atomic sediment+wire 反 sediment-only 4 days 0 catch reverse case)
- skill quantmind-v3-redline-verify (PR #273, sub-PR 8 batch 2)
"""

from __future__ import annotations

import json
import os
import re
import sys

# 真账户 / 真生产红线 mutation 模式 — BLOCK 沿用 5/5 sustained
# 沿用 Constitution §L6.2 redline-pretool-block 决议 + skill quantmind-v3-redline-verify §2.

# (1) broker call: xtquant API + 直 module call (反 paper-mode bypass)
# Patterns 沿用 xtquant + xt shorthand 双 cover, _async suffix 沿用 (反 \b
# word-boundary fail on `cancel_order_stock_async`).
BROKER_CALL_PATTERNS: list[str] = [
    r"xtquant.*order_stock\b",
    r"xtquant.*place_order\b",
    r"xtquant.*cancel_order_stock",  # drop \b — accepts _async suffix
    r"xtquant.*\.sell\b",
    r"xtquant.*\.buy\b",
    # xt shorthand variant (e.g. `import xtquant as xt`); parens required to
    # narrow function-call syntax, 反 false positive 'xt.foo' attribute access
    r"\bxt\.sell\s*\(",
    r"\bxt\.buy\s*\(",
    # bare module call (e.g. python -c "from xtquant... order_stock")
    r"\border_stock\s*\(",
    r"\bplace_order\s*\(",
]

# (2) 真账户 .env field mutation via Bash (Windows setx / PowerShell $env: 体例)
# 反 setting LIVE_TRADING_DISABLED / EXECUTION_MODE / QMT_ACCOUNT_ID via shell
# 沿用 Constitution §L8.1 (b) — .env paper→live mutation user 显式授权 only
ENV_REDLINE_PATTERNS: list[str] = [
    r"\bsetx\s+LIVE_TRADING_DISABLED\b",
    r"\bsetx\s+EXECUTION_MODE\b",
    r"\bsetx\s+QMT_ACCOUNT_ID\b",
    r"\bsetx\s+DINGTALK_ALERTS_ENABLED\b",
    r"\bsetx\s+L4_AUTO_MODE_ENABLED\b",
    r"\$env:LIVE_TRADING_DISABLED\s*=",
    r"\$env:EXECUTION_MODE\s*=",
    r"\$env:QMT_ACCOUNT_ID\s*=",
    r"\$env:DINGTALK_ALERTS_ENABLED\s*=",
    r"\$env:L4_AUTO_MODE_ENABLED\s*=",
    # POSIX shell variant
    r"\bexport\s+LIVE_TRADING_DISABLED\s*=",
    r"\bexport\s+EXECUTION_MODE\s*=",
    r"\bexport\s+QMT_ACCOUNT_ID\s*=",
]

# (3) 真生产 yaml direct mutation via Bash — 反 silent overwrite 沿用 ADR-022
# protect_critical_files.py 是 PreToolUse[Edit|Write], 反 cover Bash command 体例
PROD_YAML_PATTERNS: list[str] = [
    # Append via redirect
    r">>\s*configs/pt_live\.yaml\b",
    r">>\s*config/litellm_router\.yaml\b",
    # PowerShell Add-Content / Set-Content
    r"Add-Content\b.*configs/pt_live\.yaml\b",
    r"Add-Content\b.*config/litellm_router\.yaml\b",
    r"Set-Content\b.*configs/pt_live\.yaml\b",
    r"Set-Content\b.*config/litellm_router\.yaml\b",
    # Direct overwrite
    r">\s*configs/pt_live\.yaml\b",
    r">\s*config/litellm_router\.yaml\b",
]

# (4) live-mode broker exec script
LIVE_EXEC_PATTERNS: list[str] = [
    r"run_paper_trading.*--live\b",
    r"run_paper_trading.*--mode\s+live\b",
]

# WARN-only (sustained context-aware, hook 0 拿到 sub-PR scope)
# DB row mutation via psql / python -c — 显式 surface SOP cite
DB_ROW_WARN_PATTERNS: list[str] = [
    r"\bpsql\b.*INSERT INTO\s+(?:trade_log|risk_event_log|llm_cost_daily|llm_call_log)",
    r"\bpsql\b.*UPDATE\s+(?:trade_log|risk_event_log)\s+SET",
    r"\bpsql\b.*DELETE FROM\s+(?:trade_log|risk_event_log|llm_cost_daily|llm_call_log)",
]

# bypass marker (沿用 block_dangerous_git.py + scripts/check_llm_imports.sh allowlist)
BYPASS_MARKER_RE = re.compile(r"#\s*qm-redline-allow:[^\n]*")


def _is_bypassed(command: str) -> bool:
    """Check bypass via env var or per-command marker.

    沿用 quantmind-v3-redline-verify skill §3 user 显式触发 + Constitution §L8.1 (b)
    SSOT — bypass 必 user 显式触发, 反 silent skip.
    """
    if os.environ.get("QM_REDLINE_BYPASS") == "1":
        return True
    if BYPASS_MARKER_RE.search(command):
        return True
    return False


def _check_block(command: str) -> tuple[str, str] | None:
    """Return (category, pattern) if BLOCK matched, else None."""
    for pattern in BROKER_CALL_PATTERNS:
        if re.search(pattern, command):
            return ("broker_call", pattern)
    for pattern in ENV_REDLINE_PATTERNS:
        if re.search(pattern, command):
            return ("env_redline", pattern)
    for pattern in PROD_YAML_PATTERNS:
        if re.search(pattern, command):
            return ("prod_yaml", pattern)
    for pattern in LIVE_EXEC_PATTERNS:
        if re.search(pattern, command):
            return ("live_exec", pattern)
    return None


def _check_warn(command: str) -> tuple[str, str] | None:
    """Return (category, pattern) if WARN matched, else None."""
    for pattern in DB_ROW_WARN_PATTERNS:
        if re.search(pattern, command):
            return ("db_row_mutation", pattern)
    return None


def _emit_warn_and_pass(category: str, pattern: str, command: str) -> None:
    """ALLOW-with-WARN: surface SOP cite via hookSpecificOutput, sys.exit(0).

    沿用 protect_critical_files.py:191-201 ALLOW-with-WARN 体例 sustained.
    """
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": (
                f"WARNING (redline_pretool_block): command 触发 {category} 模式 "
                f"(pattern: {pattern!r}). 沿用 quantmind-v3-redline-verify skill §3 "
                f"5 condition 严核 SOP — verify mutation scope vs sub-PR 声明 + "
                f"reviewer agent verify + rollback path + 真账户 0 risk + user 显式触发. "
                f"反 silent breach 沿用 Constitution §L8.1 (b) 真生产红线 user 介入."
            ),
        }
    }
    print(json.dumps(result))
    sys.exit(0)


def main() -> None:
    try:
        input_data = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        # 沿用 protect_critical_files.py:121-122 + block_dangerous_git.py:88-90
        # fail-soft 体例 (反 break Bash tool 调用)
        sys.exit(0)

    tool_input = input_data.get("tool_input", {})
    command = tool_input.get("command", "")

    if not command:
        sys.exit(0)

    # bypass check 优先 (沿用 quantmind-v3-redline-verify skill §3 user 显式触发 SSOT)
    if _is_bypassed(command):
        sys.exit(0)

    # BLOCK 检查
    block_match = _check_block(command)
    if block_match:
        category, pattern = block_match
        print(
            f"BLOCKED (redline_pretool_block): command 触发 {category} 红线 "
            f"(pattern: {pattern!r}).\n"
            f"沿用 Constitution §L8.1 (b) — 真生产红线 user 介入 SOP. "
            f"5/5 红线 sustained: cash / 0 持仓 / LIVE_TRADING_DISABLED=true / "
            f"EXECUTION_MODE=paper / QMT_ACCOUNT_ID. "
            f"bypass 体例: env QM_REDLINE_BYPASS=1 OR per-command marker "
            f"`# qm-redline-allow:<reason>` (user 显式触发 only).",
            file=sys.stderr,
        )
        sys.exit(2)

    # WARN 检查 (sustained context-aware, hookSpecificOutput surface)
    warn_match = _check_warn(command)
    if warn_match:
        category, pattern = warn_match
        _emit_warn_and_pass(category, pattern, command)

    sys.exit(0)


if __name__ == "__main__":
    main()
