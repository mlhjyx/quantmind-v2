"""sub-PR 8b-llm-fix 5-07 — _propagate_settings_to_environ smoke tests.

scope (~110 line, single chunk per LL-100):
- whitelist propagate (DEEPSEEK_API_KEY + OLLAMA_BASE_URL) when os.environ empty
- idempotent (不覆盖已 set os.environ value, 沿用 shell env priority)
- empty Pydantic Settings value skip (反 propagate "" 真**误 set** misleading)
- graceful import failure (test contexts without backend.app installed)
- LiteLLMRouter __init__ 真**自动调** propagate (反 caller 真自调)

真因 sediment 关联 (5-07 sub-PR 8b-llm-diag root cause):
- yaml `api_key: os.environ/DEEPSEEK_API_KEY` LiteLLM 自 read os.environ → empty
- Pydantic-settings v2.x 0 propagate `.env` → os.environ by design
- DeepSeek 401 "Authentication Fails (governor)" → Ollama fallback 4 days sustained

关联铁律:
- 33 (fail-loud, propagate 真**显式 sync** 反 silent miss)
- 34 (Config SSOT — Pydantic Settings 真 source-of-truth, os.environ 真 derived layer)

关联文档:
- backend/qm_platform/llm/_internal/router.py:_propagate_settings_to_environ
- memory/sprint_2_sub_pr_8b_llm_diag_2026_05_07.md (root cause sediment)
- LL-110 web_fetch SOP / LL-112 user push back 体例 sustained
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from backend.qm_platform.llm._internal.router import (
    _YAML_REFERENCED_ENVS,
    _propagate_settings_to_environ,
)

# ── whitelist correctness ──


def test_yaml_referenced_envs_contains_deepseek_and_ollama() -> None:
    """白名单含 yaml line 34/48 + line 66 真**真消费** env vars."""
    assert "DEEPSEEK_API_KEY" in _YAML_REFERENCED_ENVS
    assert "OLLAMA_BASE_URL" in _YAML_REFERENCED_ENVS


def test_yaml_referenced_envs_excludes_secrets() -> None:
    """白名单反含 production secrets (TUSHARE_TOKEN / DATABASE_URL / etc.).

    沿用 sub-PR 8b-pre-hook field-level whitelist 体例 sustained.
    """
    forbidden = {"TUSHARE_TOKEN", "DATABASE_URL", "REDIS_URL", "ADMIN_TOKEN", "DINGTALK_SECRET"}
    assert not (set(_YAML_REFERENCED_ENVS) & forbidden)


def test_whitelist_covers_all_yaml_environ_refs() -> None:
    """yaml 真**全 os.environ/X refs** 必 align _YAML_REFERENCED_ENVS (drift-detection).

    沿用 reviewer P-MEDIUM adopt: 反**hardcoded list** silent miss future yaml refs.
    任 future PR 新加 `os.environ/NEW_KEY` 反同步 whitelist → 本 test 真**fail loud**
    (反 4-day production sustained drift 重演).

    沿用 LL-110 web_fetch SOP + LL-112 user push back 体例 sustained.
    """
    import re
    from pathlib import Path

    yaml_path = Path(__file__).resolve().parents[2] / "config" / "litellm_router.yaml"
    assert yaml_path.exists(), f"yaml config not found: {yaml_path}"
    text = yaml_path.read_text(encoding="utf-8")

    # Match `os.environ/IDENTIFIER` (LiteLLM yaml syntax sustained PR #221+)
    refs = set(re.findall(r"os\.environ/(\w+)", text))
    whitelist = set(_YAML_REFERENCED_ENVS)

    missing_in_whitelist = refs - whitelist
    extra_in_whitelist = whitelist - refs
    assert not missing_in_whitelist, (
        f"yaml refs {missing_in_whitelist} 反 in _YAML_REFERENCED_ENVS — "
        f"future PR 真**4-day production sustained drift** repro 风险. "
        f"沿用 sub-PR 8b-llm-diag root cause sediment, 必 sync whitelist."
    )
    assert not extra_in_whitelist, (
        f"_YAML_REFERENCED_ENVS 含 {extra_in_whitelist} 反 referenced in yaml — "
        f"沿用 sub-PR 8b-pre-hook field-level whitelist 体例, 反 dead entry."
    )


# ── propagate behavior ──


def _make_settings(**fields: str) -> MagicMock:
    """Build a mock Pydantic Settings with specified field values."""
    m = MagicMock()
    for name, value in fields.items():
        setattr(m, name, value)
    # Default empty for unset fields
    for env in _YAML_REFERENCED_ENVS:
        if env not in fields:
            setattr(m, env, "")
    return m


def test_propagate_sets_env_when_empty(monkeypatch) -> None:
    """os.environ empty + Pydantic settings.X set → os.environ[X] = settings.X."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    fake = _make_settings(
        DEEPSEEK_API_KEY="sk-test-fake-key", OLLAMA_BASE_URL="http://localhost:11434"
    )
    with patch("backend.app.config.settings", fake):
        _propagate_settings_to_environ()
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-test-fake-key"
    assert os.environ.get("OLLAMA_BASE_URL") == "http://localhost:11434"


def test_propagate_idempotent_no_override(monkeypatch) -> None:
    """已 set os.environ value 反 propagate (沿用 shell env priority sustained)."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-shell-priority")
    fake = _make_settings(DEEPSEEK_API_KEY="sk-pydantic-from-env-file")
    with patch("backend.app.config.settings", fake):
        _propagate_settings_to_environ()
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-shell-priority"


def test_propagate_skips_empty_settings_value(monkeypatch) -> None:
    """settings.X 真**空** → 反 propagate 真**空 string** 到 os.environ."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    fake = _make_settings(DEEPSEEK_API_KEY="")
    with patch("backend.app.config.settings", fake):
        _propagate_settings_to_environ()
    assert os.environ.get("DEEPSEEK_API_KEY") is None


def test_propagate_graceful_import_failure(monkeypatch) -> None:
    """backend.app.config import fail → no-op (反 raise, test contexts 沿用)."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    # Simulate ImportError by patching __import__ to raise for backend.app.config
    real_import = (
        __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
    )

    def _bad_import(name, *args, **kwargs):
        if name == "backend.app.config":
            raise ImportError("backend.app.config not installed (test context)")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_bad_import):
        # Should not raise
        _propagate_settings_to_environ()
    # No env should be set
    assert os.environ.get("DEEPSEEK_API_KEY") is None


def test_propagate_partial_only_set_one(monkeypatch) -> None:
    """settings only DEEPSEEK_API_KEY set → only that env propagated."""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    fake = _make_settings(DEEPSEEK_API_KEY="sk-only-this", OLLAMA_BASE_URL="")
    with patch("backend.app.config.settings", fake):
        _propagate_settings_to_environ()
    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-only-this"
    assert os.environ.get("OLLAMA_BASE_URL") is None


# ── LiteLLMRouter __init__ 自动调 propagate ──


def test_litellm_router_init_invokes_propagate(monkeypatch, tmp_path) -> None:
    """LiteLLMRouter() init 真**自动调** _propagate_settings_to_environ.

    反 caller 真自调 (反**漏 propagate** 真生产 silent miss 沿用 sub-PR 8b-llm-diag
    root cause sediment).
    """
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    fake = _make_settings(DEEPSEEK_API_KEY="sk-init-test-key", OLLAMA_BASE_URL="http://x:11434")

    # Use minimal valid yaml config to allow LiteLLMRouter init to succeed
    config_path = tmp_path / "router.yaml"
    config_path.write_text(
        """\
model_list:
  - model_name: deepseek-v4-flash
    litellm_params:
      model: deepseek/deepseek-v4-flash
      api_key: os.environ/DEEPSEEK_API_KEY
  - model_name: deepseek-v4-pro
    litellm_params:
      model: deepseek/deepseek-v4-pro
      api_key: os.environ/DEEPSEEK_API_KEY
  - model_name: qwen3-local
    litellm_params:
      model: ollama_chat/qwen3.5:9b
      api_base: os.environ/OLLAMA_BASE_URL
router_settings:
  num_retries: 0
  fallbacks: []
""",
        encoding="utf-8",
    )

    from backend.qm_platform.llm._internal.router import LiteLLMRouter

    with patch("backend.app.config.settings", fake):
        LiteLLMRouter(config_path=config_path)

    assert os.environ.get("DEEPSEEK_API_KEY") == "sk-init-test-key"
    assert os.environ.get("OLLAMA_BASE_URL") == "http://x:11434"
