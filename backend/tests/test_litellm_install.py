"""S1 LiteLLM install + provider config smoke tests.

关联:
- ADR-031 (S2 LiteLLMRouter implementation path 决议)
- V3 §5.5 (LLM 路由真预约)
- docs/LLM_IMPORT_POLICY.md §10 (LiteLLM install 状态)

scope:
- 验证 litellm SDK install 成功 + 版本满足 >=1.83.14
- 验证 cascade 装 openai SDK (deepseek_client.py:222 lazy import 依赖, S6 allowlist marker)
- 验证 config/litellm_router.yaml schema 合法 + 含 DeepSeek + Ollama 各 model
- 0 真生产 API call (本 PR 只验 install + config 解析, 不调真 endpoint)
- LiteLLMRouter wrapper 初始化在 S2 sub-task scope (NOT 本 PR)
"""
from __future__ import annotations

import re
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROUTER_CONFIG = REPO_ROOT / "config" / "litellm_router.yaml"

MIN_LITELLM_VERSION = (1, 83, 14)


def _parse_version(v: str) -> tuple[int, ...]:
    parts: list[int] = []
    for raw in v.split(".")[:3]:
        digits = "".join(ch for ch in raw if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def test_litellm_import() -> None:
    """litellm SDK import 不报 ImportError.

    NOTE: LiteLLM 1.83.x 不导出 `__version__` module attribute, 走
    importlib.metadata 查询 distribution metadata (沿用 PEP 396 deprecation).
    """
    import litellm  # noqa: F401

    try:
        installed = pkg_version("litellm")
    except PackageNotFoundError as exc:
        pytest.fail(f"litellm distribution metadata 缺失: {exc}")
    assert installed, "litellm distribution version 空"


def test_litellm_version_meets_minimum() -> None:
    """litellm 版本 >= 1.83.14 (沿用 ADR-031 + S1 audit informed).

    通过 importlib.metadata 查询 distribution version (LiteLLM 不导出
    module-level __version__).
    """
    raw = pkg_version("litellm")
    actual = _parse_version(raw)
    assert actual >= MIN_LITELLM_VERSION, (
        f"litellm 版本 {raw} < 最低要求 "
        f"{'.'.join(str(p) for p in MIN_LITELLM_VERSION)}; "
        "修: pip install --upgrade 'litellm>=1.83.14'"
    )


def test_openai_cascade_installed() -> None:
    """cascade 装 openai SDK (deepseek_client.py:222 lazy import 真依赖, S6 marker preserve).

    openai SDK 仍导出 module-level __version__, 用 hasattr 验证 OK.
    distribution metadata 也走 importlib.metadata 双 verify.
    """
    import openai

    assert hasattr(openai, "__version__"), "openai 缺 __version__ 属性 (cascade 装失败)"
    try:
        installed = pkg_version("openai")
    except PackageNotFoundError as exc:
        pytest.fail(f"openai distribution metadata 缺失: {exc}")
    assert installed, "openai distribution version 空"


def test_router_config_yaml_loads() -> None:
    """config/litellm_router.yaml schema 合法, 0 YAML parse error."""
    assert ROUTER_CONFIG.exists(), f"config 文件缺失: {ROUTER_CONFIG}"
    with ROUTER_CONFIG.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    assert isinstance(data, dict), "router config 顶层应是 dict"
    for required_key in ("model_list", "router_settings", "litellm_settings"):
        assert required_key in data, f"router config 缺 key: {required_key}"


def test_router_config_has_deepseek_and_ollama() -> None:
    """provider config 含 DeepSeek V4-Flash/V4-Pro + Ollama Qwen3 (V3 §5.5 真预约)."""
    with ROUTER_CONFIG.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    model_list = data["model_list"]
    assert isinstance(model_list, list) and len(model_list) >= 3, (
        f"model_list 至少应含 3 个 model (V4-Flash + V4-Pro + Ollama), 实际: {len(model_list)}"
    )

    model_names = {entry["model_name"] for entry in model_list}
    expected = {"deepseek-v4-flash", "deepseek-v4-pro", "qwen3-local"}
    missing = expected - model_names
    assert not missing, f"model_list 缺 model: {missing}"


def test_router_config_no_hardcoded_keys() -> None:
    """敏感数据全走 os.environ/<NAME>, 0 hardcode API key (沿用 SOP).

    注释行 (`#` 开头, 含 inline `#` 后) 真 placeholder cite 不触发误报
    (沿用 reviewer Chunk A P1 finding).
    """
    with ROUTER_CONFIG.open("r", encoding="utf-8") as f:
        text = f.read()

    code_lines = []
    for raw in text.splitlines():
        # YAML inline comment cut: 取 # 前真值, 跳整行注释
        before_hash = raw.split("#", 1)[0]
        if before_hash.strip():
            code_lines.append(before_hash)
    code_only = "\n".join(code_lines)

    real_key_pattern = re.compile(r"sk-[A-Za-z0-9]{10,}")
    matches = real_key_pattern.findall(code_only)
    assert not matches, (
        f"router config 含真 sk-* hardcode key (跳注释扫): {matches}; "
        "API key 必须走 os.environ/<NAME>"
    )

    bearer_pattern = re.compile(r"Bearer\s+[A-Za-z0-9\-_.~+/]{16,}")
    bearer_matches = bearer_pattern.findall(code_only)
    assert not bearer_matches, f"router config 含 Bearer token hardcode: {bearer_matches}"

    inline_quote_pattern = re.compile(r"api_key:\s*[\"'][^\"']+[\"']")
    inline_quote_matches = inline_quote_pattern.findall(code_only)
    assert not inline_quote_matches, (
        f"router config 含 quoted api_key inline value: {inline_quote_matches}; "
        "改走 os.environ/<NAME>"
    )

    assert "os.environ/DEEPSEEK_API_KEY" in text, "DeepSeek 缺 env var 引用"
    assert "os.environ/OLLAMA_BASE_URL" in text, "Ollama 缺 env var 引用 (S3 prerequisite)"


@pytest.mark.skipif(
    not ROUTER_CONFIG.exists(),
    reason="router config 缺失, 跳过 LiteLLM Router 实例化",
)
def test_router_can_initialize_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """LiteLLM Router 真实例化 (set_verbose=False, 0 真 API call).

    NOTE: Router 初始化只解析 config + 准备路由表, 不调真 endpoint.
    完整 wrapper logic 在 S2 sub-task scope (本 PR 不消费).

    用 monkeypatch 隔离 env var 改动 (沿用 reviewer Chunk A P2 finding,
    避免 process-wide env pollution 影响后续 test).
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-placeholder-not-used")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    from litellm import Router

    with ROUTER_CONFIG.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    router = Router(
        model_list=data["model_list"],
        num_retries=data["router_settings"].get("num_retries", 0),
    )
    assert router is not None
    assert len(router.model_list) >= 3, "Router 加载后 model_list 应至少 3 entries"
