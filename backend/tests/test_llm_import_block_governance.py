"""S6 governance hook: scripts/check_llm_imports.sh BLOCK on anthropic/openai import.

V3 §5.5 + ADR-020 enforce — LiteLLMRouter (S2 sub-task) only path.

测试覆盖:
- 现 codebase clean (含 deepseek_client.py:222 marker) → exit 0 放行
- anthropic 直接 import (无 marker) → BLOCK exit 1
- openai 直接 import (无 marker) → BLOCK exit 1
- from anthropic / from openai → BLOCK exit 1
- allowlist marker (`# llm-import-allow:...`) → 放行 + stderr log
- tests/ subdir 的 mock import → 不触发 BLOCK
- deepseek_client.py:222 必须保留 marker (防意外删除)
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT_REL = "scripts/check_llm_imports.sh"  # bash 在 Windows 用 forward slash + relative path 跨平台兼容
VIOLATOR_PATH = REPO_ROOT / "scripts" / "_s6_governance_test_violator.py"
DEEPSEEK_CLIENT = REPO_ROOT / "backend" / "engines" / "mining" / "deepseek_client.py"


def _run_full() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", SCRIPT_REL, "--full"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=15,
    )


@pytest.fixture
def violator_cleanup():
    """Ensure tmp violator file cleaned up even on assertion failure."""
    yield
    VIOLATOR_PATH.unlink(missing_ok=True)


def test_clean_codebase_passes_with_allowlist_log() -> None:
    """现 codebase 含 deepseek_client.py:222 marker → exit 0, allowlist log 显示该行."""
    assert not VIOLATOR_PATH.exists(), (
        f"violator file {VIOLATOR_PATH} 已存在 (test pollution); 修: 手动 unlink."
    )
    result = _run_full()
    assert result.returncode == 0, (
        f"现 codebase 应放行 (含 deepseek_client.py:222 marker), 但 exit={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "0 unauthorized import" in result.stdout
    assert "放行" in result.stdout
    # allowlist log 必须显示 deepseek_client.py:222 (透明 + 可审计)
    assert "ALLOWLIST_HIT" in result.stderr
    assert "deepseek_client.py:222" in result.stderr
    assert "S2-deferred" in result.stderr


@pytest.mark.parametrize(
    "violator_content,expected_keyword",
    [
        ("import anthropic\n", "anthropic"),
        ("from anthropic import Anthropic\n", "anthropic"),
        ("import openai\n", "openai"),
        ("from openai import OpenAI\n", "openai"),
        ("from openai.types import ChatCompletion\n", "openai"),
    ],
)
def test_violator_without_marker_blocks(
    violator_cleanup,
    violator_content: str,
    expected_keyword: str,
) -> None:
    """禁 import pattern (无 allowlist marker) 触发 BLOCK exit 1."""
    VIOLATOR_PATH.write_text(violator_content, encoding="utf-8")
    result = _run_full()
    assert result.returncode == 1, (
        f"violator 未触发 BLOCK, exit={result.returncode}\n"
        f"violator content: {violator_content!r}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "BLOCK" in result.stdout, f"BLOCK marker missing in stdout: {result.stdout}"
    assert expected_keyword in result.stdout
    assert "LiteLLMRouter" in result.stdout, "修复 cite missing"
    assert "ADR-020" in result.stdout, "背景 ADR cite missing"


def test_violator_with_allowlist_marker_passes(violator_cleanup) -> None:
    """含 `# llm-import-allow:<reason>` marker 的违反行 → 放行 + stderr 日志."""
    VIOLATOR_PATH.write_text(
        "import openai  # llm-import-allow:test-allowlist-marker-PR-219\n",
        encoding="utf-8",
    )
    result = _run_full()
    assert result.returncode == 0, (
        f"含 marker 的违反应放行, 但 exit={result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # stderr 必须 log allowlist hit (透明)
    assert "ALLOWLIST_HIT" in result.stderr
    assert "_s6_governance_test_violator.py:1" in result.stderr
    assert "test-allowlist-marker-PR-219" in result.stderr


def test_tests_subdir_mock_excluded() -> None:
    """tests/ 内 mock cite 合法 → 不触发 BLOCK."""
    test_violator = REPO_ROOT / "backend" / "tests" / "_s6_test_mock_anthropic.py"
    test_violator.write_text(
        "# mock cite 合法 (unittest.mock.patch)\nimport anthropic  # noqa\n",
        encoding="utf-8",
    )
    try:
        result = _run_full()
        assert result.returncode == 0, (
            f"tests/ 内 mock 应不触发 BLOCK, exit={result.returncode}\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
    finally:
        test_violator.unlink(missing_ok=True)


def test_deepseek_client_marker_preserved() -> None:
    """deepseek_client.py:222 必须保留 allowlist marker (防意外删除).

    S2 LiteLLMRouter 完成后会 refactor 这个 lazy import. 在那之前 marker 必须保持,
    否则 hook --full 会 BLOCK 整个 push.
    """
    content = DEEPSEEK_CLIENT.read_text(encoding="utf-8")
    lines = content.splitlines()
    # line 222 (1-indexed) → index 221
    line_222 = lines[221] if len(lines) > 221 else ""
    assert "from openai import OpenAI" in line_222, (
        f"deepseek_client.py:222 现 lazy import 行已变, 当前内容: {line_222!r}\n"
        "可能 S2 LiteLLMRouter 已完成 (期待 marker 已删除), 请确认并更新 test."
    )
    assert "# llm-import-allow:" in line_222, (
        f"deepseek_client.py:222 缺 allowlist marker, hook --full 会 BLOCK push.\n"
        f"当前内容: {line_222!r}\n"
        "修复: 加 `# llm-import-allow:S2-deferred-PR-219` 或在 S2 完成后 refactor 这一行."
    )


def test_invalid_mode() -> None:
    """无效 mode → exit 2 + usage."""
    result = subprocess.run(
        ["bash", SCRIPT_REL, "--bogus"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode == 2
    assert "usage" in result.stderr
