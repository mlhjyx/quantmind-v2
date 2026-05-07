"""sub-PR 8b-pre-hook 5-07 — protect_critical_files.py field-level whitelist smoke tests.

scope (~140 line, single chunk per LL-100):
- whitelist allow tests: News URL fields (ANSPIRE/MARKETAUX/ZHIPU/TAVILY/GDELT/RSSHUB_BASE_URL)
- production secret block tests (DEEPSEEK_API_KEY / LIVE_TRADING_DISABLED / EXECUTION_MODE /
  QMT_ACCOUNT_ID / DATABASE_URL / ADMIN_TOKEN)
- multi-line mixed (whitelist + production secret) → BLOCKED
- 0-field detection (anti-bypass) → BLOCKED
- Write to .env → BLOCKED (整文件覆盖)
- .env.local + .env.production + credentials + .git/ → BLOCKED (任 tool sustained)
- DDL + DESIGN_V5 → ALLOW with WARN
- unrelated file → ALLOW

真生产证据沿用 5-07 sub-PR 8b-pre-hook field-level whitelist 修订:
- 反 .env file-level BLOCKED 体例
- 改 ENV_EDITABLE_FIELDS whitelist 真 News URL fields
- 真生效 沿用 sub-PR 8a-followup-pre block_dangerous_git.py 测试体例 sustained

关联铁律: 33 (fail-loud, parse error 沿用 fail-soft sys.exit(0)) / 42 (PR 分级审查制)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "protect_critical_files.py"


def _run_hook(payload: dict) -> tuple[int, str, str]:
    """Run hook subprocess with JSON stdin, return (rc, stdout, stderr)."""
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
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


def _multiedit(file_path: str, edits: list[dict]) -> dict:
    return {
        "tool_name": "MultiEdit",
        "tool_input": {"file_path": file_path, "edits": edits},
    }


def _write(file_path: str, content: str = "x") -> dict:
    return {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }


# ── WHITELIST allow ──


def test_env_edit_anspire_base_url_allowed() -> None:
    rc, out, err = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "ANSPIRE_BASE_URL=https://open.anspire.cn",
            "ANSPIRE_BASE_URL=https://plugin.anspire.cn",
        )
    )
    assert rc == 0, f"rc={rc} stderr={err}"
    assert "ANSPIRE_BASE_URL" in out


def test_env_edit_marketaux_base_url_allowed() -> None:
    rc, out, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "MARKETAUX_BASE_URL=https://api.marketaux.com/v1",
            "MARKETAUX_BASE_URL=https://api.marketaux.com",
        )
    )
    assert rc == 0
    assert "MARKETAUX_BASE_URL" in out


def test_env_edit_zhipu_base_url_allowed() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "ZHIPU_BASE_URL=https://x",
            "ZHIPU_BASE_URL=https://y",
        )
    )
    assert rc == 0


def test_env_edit_tavily_base_url_allowed() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "TAVILY_BASE_URL=https://x",
            "TAVILY_BASE_URL=https://y",
        )
    )
    assert rc == 0


def test_env_edit_gdelt_base_url_allowed() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "GDELT_BASE_URL=https://x",
            "GDELT_BASE_URL=https://y",
        )
    )
    assert rc == 0


def test_env_edit_rsshub_base_url_allowed() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "RSSHUB_BASE_URL=http://x",
            "RSSHUB_BASE_URL=http://y",
        )
    )
    assert rc == 0


def test_env_multiedit_two_news_urls_allowed() -> None:
    rc, out, _ = _run_hook(
        _multiedit(
            "D:/quantmind-v2/backend/.env",
            [
                {
                    "old_string": "ANSPIRE_BASE_URL=https://open.anspire.cn",
                    "new_string": "ANSPIRE_BASE_URL=https://plugin.anspire.cn",
                },
                {
                    "old_string": "MARKETAUX_BASE_URL=https://api.marketaux.com/v1",
                    "new_string": "MARKETAUX_BASE_URL=https://api.marketaux.com",
                },
            ],
        )
    )
    assert rc == 0
    assert "ANSPIRE_BASE_URL" in out
    assert "MARKETAUX_BASE_URL" in out


# ── BLOCKED production secret ──


def test_env_edit_deepseek_api_key_blocked() -> None:
    rc, _, err = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "DEEPSEEK_API_KEY=sk-old",
            "DEEPSEEK_API_KEY=sk-new",
        )
    )
    assert rc == 2
    assert "DEEPSEEK_API_KEY" in err


def test_env_edit_live_trading_disabled_blocked() -> None:
    rc, _, err = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "LIVE_TRADING_DISABLED=true",
            "LIVE_TRADING_DISABLED=false",
        )
    )
    assert rc == 2
    assert "LIVE_TRADING_DISABLED" in err


def test_env_edit_execution_mode_blocked() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "EXECUTION_MODE=paper",
            "EXECUTION_MODE=live",
        )
    )
    assert rc == 2


def test_env_edit_qmt_account_id_blocked() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "QMT_ACCOUNT_ID=81001102",
            "QMT_ACCOUNT_ID=00000000",
        )
    )
    assert rc == 2


def test_env_edit_database_url_blocked() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "DATABASE_URL=postgresql://x",
            "DATABASE_URL=postgresql://y",
        )
    )
    assert rc == 2


def test_env_edit_admin_token_blocked() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "ADMIN_TOKEN=old",
            "ADMIN_TOKEN=new",
        )
    )
    assert rc == 2


def test_env_edit_anspire_api_key_blocked() -> None:
    """API key 反 BASE_URL — 必 BLOCKED 沿用 production secret 体例."""
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "ANSPIRE_API_KEY=sk-old",
            "ANSPIRE_API_KEY=sk-new",
        )
    )
    assert rc == 2


# ── BLOCKED multi-line mixed ──


def test_env_edit_mixed_whitelist_plus_secret_blocked() -> None:
    """multi-line edit 含 whitelist + secret → BLOCKED (任一 non-whitelisted 触发)."""
    rc, _, err = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "ANSPIRE_BASE_URL=https://open.anspire.cn\nDEEPSEEK_API_KEY=sk-old",
            "ANSPIRE_BASE_URL=https://plugin.anspire.cn\nDEEPSEEK_API_KEY=sk-new",
        )
    )
    assert rc == 2
    assert "DEEPSEEK_API_KEY" in err


def test_env_multiedit_mixed_whitelist_plus_secret_blocked() -> None:
    rc, _, err = _run_hook(
        _multiedit(
            "D:/quantmind-v2/backend/.env",
            [
                {"old_string": "ANSPIRE_BASE_URL=x", "new_string": "ANSPIRE_BASE_URL=y"},
                {"old_string": "DEEPSEEK_API_KEY=a", "new_string": "DEEPSEEK_API_KEY=b"},
            ],
        )
    )
    assert rc == 2
    assert "DEEPSEEK_API_KEY" in err


# ── BLOCKED 0-field (anti-bypass) ──


def test_env_edit_zero_field_detection_blocked() -> None:
    rc, _, err = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env",
            "some random text",
            "different text",
        )
    )
    assert rc == 2
    assert "0 field detected" in err


# ── BLOCKED Write to .env ──


def test_env_write_blocked() -> None:
    rc, _, err = _run_hook(
        _write(
            "D:/quantmind-v2/backend/.env",
            "ANSPIRE_BASE_URL=https://plugin.anspire.cn",
        )
    )
    assert rc == 2
    assert "整文件覆盖" in err or "Write" in err


# ── BLOCKED other env-like / sensitive files ──


def test_env_local_edit_blocked() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env.local",
            "ANSPIRE_BASE_URL=x",
            "ANSPIRE_BASE_URL=y",
        )
    )
    assert rc == 2


def test_env_production_edit_blocked() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/.env.production",
            "ANSPIRE_BASE_URL=x",
            "ANSPIRE_BASE_URL=y",
        )
    )
    assert rc == 2


def test_credentials_edit_blocked() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/credentials.json",
            "x",
            "y",
        )
    )
    assert rc == 2


def test_git_dir_edit_blocked() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/.git/HEAD",
            "x",
            "y",
        )
    )
    assert rc == 2


# ── WARN but allow ──


def test_ddl_file_edit_warns_but_allows() -> None:
    rc, out, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/docs/QUANTMIND_V2_DDL_FINAL.sql",
            "CREATE TABLE x",
            "CREATE TABLE y",
        )
    )
    assert rc == 0
    assert "WARNING" in out


def test_design_v5_file_edit_warns_but_allows() -> None:
    rc, out, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/docs/QUANTMIND_V2_DESIGN_V5.md",
            "old",
            "new",
        )
    )
    assert rc == 0
    assert "WARNING" in out


# ── ALLOW unrelated ──


def test_unrelated_file_edit_allowed() -> None:
    rc, _, _ = _run_hook(
        _edit(
            "D:/quantmind-v2/backend/app/main.py",
            "old",
            "new",
        )
    )
    assert rc == 0


def test_unrelated_write_allowed() -> None:
    rc, _, _ = _run_hook(
        _write(
            "D:/quantmind-v2/backend/app/main.py",
            "content",
        )
    )
    assert rc == 0


# ── 边界 graceful ──


def test_empty_input_passes() -> None:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0


def test_no_file_path_passes() -> None:
    rc, _, _ = _run_hook({"tool_name": "Edit", "tool_input": {}})
    assert rc == 0


def test_env_other_tool_blocked() -> None:
    """非 Edit/MultiEdit/Write tool 触发 .env → BLOCKED."""
    rc, _, _ = _run_hook(
        {
            "tool_name": "NotebookEdit",
            "tool_input": {"file_path": "D:/quantmind-v2/backend/.env"},
        }
    )
    assert rc == 2
