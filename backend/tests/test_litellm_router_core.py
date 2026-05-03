"""S2.1 LiteLLMRouter core 单元测试 — 路由 + LLMResponse 包装 + fallback 检测.

scope:
- 7 任务 → model alias mapping verify
- unknown task fail-loud (反 silent fallback, 铁律 33)
- LLMResponse 字段完整 + decision_id 透传
- fallback 检测 (actual_model 跟 primary alias 不一致 → is_fallback=True)
- 并发 completion 0 race condition (asyncio gather 多 task type)

体例: monkeypatch.setattr(LiteLLM Router.completion → mock_fn), 0 真 API call.
跟 PR #221 test_litellm_install.py 体例对齐 (ROUTER_CONFIG fixture 复用).

关联:
- ADR-031 (S2 LiteLLMRouter implementation path 决议)
- V3 §5.5 (LLM 路由真预约, 7 任务 mapping)
- config/litellm_router.yaml (PR #221 sediment, 本 test consume only)
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.qm_platform.llm import (
    DEFAULT_CONFIG_PATH,
    FALLBACK_ALIAS,
    TASK_TO_MODEL_ALIAS,
    LiteLLMRouter,
    LLMMessage,
    LLMResponse,
    RiskTaskType,
    RouterConfigError,
    UnknownTaskError,
)
from backend.qm_platform.llm import router as router_module

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROUTER_CONFIG = REPO_ROOT / "config" / "litellm_router.yaml"


def _make_completion_obj(
    *,
    model: str,
    content: str = "ok",
    prompt_tokens: int = 12,
    completion_tokens: int = 8,
    cost: float = 0.000123,
) -> SimpleNamespace:
    """构造 LiteLLM ChatCompletion 兼容对象 (走 SimpleNamespace 真 attribute access).

    NOTE: _hidden_params 真 LiteLLM 真 dict attribute (走 getattr 路径),
    SimpleNamespace 真 attribute store 跟 dict-attribute 真 dual-access 兼容. 若
    LiteLLM 升级后 _hidden_params 真 property/descriptor, 本 mock 真 silent 漂移 —
    届时 _extract_cost_usd 真 hidden_params.get("response_cost") 真 0 返就是真破.
    """
    message = SimpleNamespace(content=content)
    choice = SimpleNamespace(message=message)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(
        choices=[choice],
        model=model,
        usage=usage,
        _hidden_params={"response_cost": cost},
    )


def _patch_router_completion(
    monkeypatch: pytest.MonkeyPatch,
    *,
    actual_model: str,
    content: str = "ok",
    cost: float = 0.000123,
) -> dict[str, Any]:
    """monkeypatch litellm.Router.completion → 固定 mock."""
    captured: dict[str, Any] = {}

    def mock_completion(self: Any, **kwargs: Any) -> SimpleNamespace:
        captured["model"] = kwargs.get("model")
        captured["messages"] = kwargs.get("messages")
        captured["timeout"] = kwargs.get("timeout")
        captured["extra"] = {k: v for k, v in kwargs.items() if k not in {"model", "messages", "timeout"}}
        return _make_completion_obj(model=actual_model, content=content, cost=cost)

    monkeypatch.setattr(router_module.Router, "completion", mock_completion, raising=True)
    return captured


@pytest.fixture
def router(monkeypatch: pytest.MonkeyPatch) -> LiteLLMRouter:
    """LiteLLMRouter 实例化 (走 yaml config, 0 真 API call)."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-placeholder-not-used")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return LiteLLMRouter()


def test_router_initialization(router: LiteLLMRouter) -> None:
    """LiteLLMRouter 实例化 sustained config/litellm_router.yaml PR #221 sediment."""
    assert router.config_path == DEFAULT_CONFIG_PATH
    assert ROUTER_CONFIG.exists()


def test_route_news_classify_to_v4_flash(router: LiteLLMRouter) -> None:
    """L0.2 NewsClassifier → deepseek-v4-flash."""
    assert router.model_for(RiskTaskType.NEWS_CLASSIFY) == "deepseek-v4-flash"


def test_route_judge_to_v4_pro(router: LiteLLMRouter) -> None:
    """L2.3 Judge → deepseek-v4-pro."""
    assert router.model_for(RiskTaskType.JUDGE) == "deepseek-v4-pro"


def test_all_seven_tasks_have_alias(router: LiteLLMRouter) -> None:
    """V3 §5.5 真预约 7 任务全部跟 alias 真 mapping."""
    expected_count = 7
    assert len(TASK_TO_MODEL_ALIAS) == expected_count
    for task in RiskTaskType:
        alias = router.model_for(task)
        assert alias in {"deepseek-v4-flash", "deepseek-v4-pro"}, (
            f"task {task} 真 alias '{alias}' 不在 V3 §5.5 真预约 (V4-Flash / V4-Pro)"
        )


def test_unknown_task_raises(router: LiteLLMRouter) -> None:
    """task 不在 RiskTaskType enum → UnknownTaskError (反 silent fallback, 铁律 33)."""
    with pytest.raises(UnknownTaskError):
        router.model_for("not_a_real_task")  # type: ignore[arg-type]


def test_completion_mock_happy_path(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """基本 happy path — JUDGE 路由 → deepseek-v4-pro → 真返 LLMResponse."""
    captured = _patch_router_completion(
        monkeypatch, actual_model="deepseek/deepseek-reasoner", cost=0.0042
    )

    response = router.completion(
        task=RiskTaskType.JUDGE,
        messages=[LLMMessage("user", "判定 stock A")],
    )

    assert isinstance(response, LLMResponse)
    assert response.content == "ok"
    assert response.model == "deepseek/deepseek-reasoner"
    assert response.tokens_in == 12
    assert response.tokens_out == 8
    assert response.cost_usd == Decimal("0.0042")
    assert response.latency_ms >= 0.0
    assert response.is_fallback is False
    assert captured["model"] == "deepseek-v4-pro"
    assert captured["messages"] == [{"role": "user", "content": "判定 stock A"}]


def test_response_dataclass_fields_complete(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LLMResponse 真 dataclass 7 字段全部齐 (含 decision_id + is_fallback)."""
    _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-chat")

    response = router.completion(
        task=RiskTaskType.NEWS_CLASSIFY,
        messages=[LLMMessage("user", "分类")],
    )

    expected_fields = {
        "content",
        "model",
        "tokens_in",
        "tokens_out",
        "cost_usd",
        "latency_ms",
        "decision_id",
        "is_fallback",
    }
    assert set(response.__dataclass_fields__.keys()) == expected_fields


def test_decision_id_propagation(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """caller 传 decision_id → response 透传 (S2.3 audit trail 真依赖)."""
    _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-chat")

    decision_id = "risk-event-uuid-1234abcd"
    response = router.completion(
        task=RiskTaskType.BULL_AGENT,
        messages=[LLMMessage("user", "bull case")],
        decision_id=decision_id,
    )

    assert response.decision_id == decision_id


def test_decision_id_default_none(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """caller 不传 decision_id → response 真 None (S2.3 真 fail-loud check 候选)."""
    _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-chat")
    response = router.completion(
        task=RiskTaskType.EMBEDDING, messages=[LLMMessage("user", "embed me")]
    )
    assert response.decision_id is None


def test_fallback_detection_v4_flash_to_qwen(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """primary deepseek-v4-flash 真 fallback 走 qwen → is_fallback=True."""
    _patch_router_completion(monkeypatch, actual_model="ollama/qwen3:8b")

    response = router.completion(
        task=RiskTaskType.NEWS_CLASSIFY,
        messages=[LLMMessage("user", "分类")],
    )

    assert response.is_fallback is True


def test_fallback_detection_v4_pro_stays_primary(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """primary deepseek-v4-pro 真返 deepseek-reasoner → is_fallback=False."""
    _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-reasoner")

    response = router.completion(
        task=RiskTaskType.RISK_REFLECTOR,
        messages=[LLMMessage("user", "反思")],
    )

    assert response.is_fallback is False


def test_unknown_task_completion_raises(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """completion(unknown_task) → UnknownTaskError (反 silent fallback)."""
    _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-chat")
    with pytest.raises(UnknownTaskError):
        router.completion(
            task="bogus",  # type: ignore[arg-type]
            messages=[LLMMessage("user", "x")],
        )


def test_messages_dict_input_supported(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """caller 传 dict messages (NOT LLMMessage) 也兼容 (沿用 OpenAI Chat 体例)."""
    captured = _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-chat")
    raw_messages = [
        {"role": "system", "content": "你是 NewsClassifier"},
        {"role": "user", "content": "分类这条消息"},
    ]
    router.completion(task=RiskTaskType.NEWS_CLASSIFY, messages=raw_messages)
    assert captured["messages"] == raw_messages


def test_kwargs_passthrough(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kwargs (temperature / max_tokens) 透传 LiteLLM completion."""
    captured = _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-chat")
    router.completion(
        task=RiskTaskType.JUDGE,
        messages=[LLMMessage("user", "x")],
        temperature=0.0,
        max_tokens=512,
        timeout=15.0,
    )
    assert captured["timeout"] == 15.0
    assert captured["extra"]["temperature"] == 0.0
    assert captured["extra"]["max_tokens"] == 512


def test_concurrent_completions_all_succeed(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """asyncio gather 7 task type 并发 → 全部 PASS (router 真 stateless on call).

    NOTE: 本 test 真 mock 真 deterministic, 0 shared mutable state — 证据强度
    限于 "7 path 真 0 异常" + "完成". 真 race condition 测试需 BudgetGuard /
    LLMCallLogger 真 shared counter, 留 S2.2/S2.3 真 sediment.
    """
    _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-chat")

    async def _drive() -> list[LLMResponse]:
        loop = asyncio.get_event_loop()
        return await asyncio.gather(
            *[
                loop.run_in_executor(
                    None,
                    lambda t=task: router.completion(
                        task=t, messages=[LLMMessage("user", t.value)]
                    ),
                )
                for task in RiskTaskType
            ]
        )

    responses = asyncio.run(_drive())
    assert len(responses) == len(RiskTaskType)
    assert all(isinstance(r, LLMResponse) for r in responses)


def test_config_missing_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """config_path 不存在 → RouterConfigError (fail-loud, 铁律 33+34)."""
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    bogus = tmp_path / "does_not_exist.yaml"
    with pytest.raises(RouterConfigError, match="缺失"):
        LiteLLMRouter(config_path=bogus)


def test_config_alias_completeness(router: LiteLLMRouter) -> None:
    """yaml model_list 必须 cover TASK_TO_MODEL_ALIAS + FALLBACK_ALIAS 全 alias."""
    needed = set(TASK_TO_MODEL_ALIAS.values()) | {FALLBACK_ALIAS}
    yaml_aliases = {entry["model_name"] for entry in router._raw_config["model_list"]}
    missing = needed - yaml_aliases
    assert not missing, f"yaml model_list 缺 alias: {missing}"


def test_unknown_primary_alias_raises_fallback_detection_error() -> None:
    """`_is_fallback` 真 primary_alias 不在 PRIMARY_MODEL_SUBSTRINGS → raise (反 silent miss).

    沿用 reviewer Chunk A P2: 未来加 alias 必同步 PRIMARY_MODEL_SUBSTRINGS table,
    否则 _is_fallback 真 silent return False 真 fallback 状态漏报.
    """
    from backend.qm_platform.llm import FallbackDetectionError
    from backend.qm_platform.llm.router import _is_fallback

    with pytest.raises(FallbackDetectionError, match="not in PRIMARY_MODEL_SUBSTRINGS|不在"):
        _is_fallback(actual_model="some/model", primary_alias="future-v5-alias")
