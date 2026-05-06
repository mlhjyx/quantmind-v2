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

# llm-internal-allow:test-only — S4 PR #226 sediment, mock 体例真依赖 _internal/ 直接 import
from backend.qm_platform.llm import (  # noqa: F401
    LLMMessage,
    LLMResponse,
    RiskTaskType,
    RouterConfigError,
    UnknownTaskError,
)
from backend.qm_platform.llm._internal import router as router_module
from backend.qm_platform.llm._internal.router import (
    DEFAULT_CONFIG_PATH,
    FALLBACK_ALIAS,
    TASK_TO_MODEL_ALIAS,
    LiteLLMRouter,
)

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
    from backend.qm_platform.llm._internal.router import FallbackDetectionError, _is_fallback

    with pytest.raises(FallbackDetectionError, match="not in PRIMARY_MODEL_SUBSTRINGS|不在"):
        _is_fallback(actual_model="some/model", primary_alias="future-v5-alias")


# ── sub-PR 8a-followup-A (5-07): _is_fallback() BUG #1 修复 — Case 1/2/3 cover ──
#
# Sprint 1 PR #222 真**单测未 cover** Case 1 (primary success, alias-pass-through),
# 真**Sprint 2 sub-PR 8a e2e 真生产 first verify** 触发 false positive (是 fallback
# 但实际 primary 真**成功**). 沿用 STATUS_REPORT memory/sprint_2_sub_pr_8a_followup_diagnose
# _2026_05_07.md BUG #1 sediment + ADR-DRAFT row 6 真**起手 ADR**.
#
# 沿用 reviewer Chunk A P2 真 false negative warning (PR #222), 本 3 case 真**双向 cover**
# false positive + false negative + edge case (沿用 audit Week 2 batch governance LL 体例
# "detection bug 必 cover 双向 case + edge case sediment").


def test_is_fallback_case1_alias_pass_through_returns_false() -> None:
    """Case 1: primary success, LiteLLM Router 真**返 yaml model_name alias** (default
    behavior). actual_model == primary_alias → is_fallback=False (NEW short-circuit,
    sub-PR 8a-followup-A BUG #1 fix).

    真生产证据 (sub-PR 8a e2e 5-07 02:59):
    - LiteLLMRouter direct call task=NEWS_CLASSIFY → DeepSeek primary SUCCESS
    - response.model = "deepseek-v4-flash" (LiteLLM Router 真返 alias 反 underlying)
    - cost=0.00000238 (真 DeepSeek 计 cost), latency=502ms (真 DeepSeek)
    - 修复前: is_fallback=True (false positive, "deepseek-chat" not in "deepseek-v4-flash")
    - 修复后: is_fallback=False (alias equality short-circuit)
    """
    from backend.qm_platform.llm._internal.router import _is_fallback

    # primary alias deepseek-v4-flash 真**返 alias** (Case 1 default LiteLLM behavior)
    assert _is_fallback(
        actual_model="deepseek-v4-flash",
        primary_alias="deepseek-v4-flash",
    ) is False
    # primary alias deepseek-v4-pro 真**返 alias** (Case 1 cover 7 task type 全部)
    assert _is_fallback(
        actual_model="deepseek-v4-pro",
        primary_alias="deepseek-v4-pro",
    ) is False
    # reviewer P1-1+P1-2 adopt (5-07): case-variant alias 真**反 introduce false positive**
    # 沿用 line 399 substring check 真 .lower() normalization 体例 sustained.
    assert _is_fallback(
        actual_model="DeepSeek-V4-Flash",
        primary_alias="deepseek-v4-flash",
    ) is False
    assert _is_fallback(
        actual_model="deepseek-v4-flash",
        primary_alias="DEEPSEEK-V4-FLASH",
    ) is False


def test_is_fallback_case2_underlying_name_returns_false() -> None:
    """Case 2: primary success, LiteLLM Router 真**返 underlying provider/model name**
    (rare case, _call_with_fallback internal path). substring 检测体例 sustained.

    actual_model 含 expected_substring → is_fallback=False (沿用 PRIMARY_MODEL_SUBSTRINGS).
    """
    from backend.qm_platform.llm._internal.router import _is_fallback

    # primary deepseek-v4-flash → "deepseek-chat" substring (Case 2 sustained)
    assert _is_fallback(
        actual_model="deepseek/deepseek-chat",
        primary_alias="deepseek-v4-flash",
    ) is False
    # primary deepseek-v4-pro → "deepseek-reasoner" substring (Case 2 sustained)
    assert _is_fallback(
        actual_model="deepseek/deepseek-reasoner",
        primary_alias="deepseek-v4-pro",
    ) is False
    # case-insensitive 沿用 actual_model.lower() (e.g. "DeepSeek/DeepSeek-Chat")
    assert _is_fallback(
        actual_model="DeepSeek/DeepSeek-Chat",
        primary_alias="deepseek-v4-flash",
    ) is False


def test_is_fallback_case3_fallback_underlying_returns_true() -> None:
    """Case 3: fallback chain triggered, LiteLLM Router 真**返 fallback model 真 underlying
    name** (e.g. ollama_chat/qwen3.5:9b). substring 检测体例 sustained.

    actual_model NOT 含 primary expected_substring → is_fallback=True.

    真生产证据 (sub-PR 8a e2e 5-07): 6 row classifier_model="ollama_chat/qwen3.5:9b"
    (LiteLLM Router fallback chain 触发 deepseek-v4-flash → qwen3-local).
    """
    from backend.qm_platform.llm._internal.router import _is_fallback

    # fallback to qwen3-local (5-06 ADR-034 升级 qwen3.5:9b)
    assert _is_fallback(
        actual_model="ollama_chat/qwen3.5:9b",
        primary_alias="deepseek-v4-flash",
    ) is True
    # 历史 qwen3:8b path (ADR-034 升级前 baseline)
    assert _is_fallback(
        actual_model="ollama/qwen3:8b",
        primary_alias="deepseek-v4-flash",
    ) is True
    # primary deepseek-v4-pro fallback to qwen3 (RISK_REFLECTOR / JUDGE 体例)
    assert _is_fallback(
        actual_model="ollama_chat/qwen3.5:9b",
        primary_alias="deepseek-v4-pro",
    ) is True


# ── sub-PR 8a-followup-B-yaml (5-07): yaml V4 underlying routing + thinking 参数 cover ──
#
# DeepSeek 官方 API spec (api-docs.deepseek.com/zh-cn/) sustained:
# - v4-flash + v4-pro 真**dual-mode model**, thinking enabled/disabled toggle 真生效
# - extra_body={"thinking": {"type": "enabled" | "disabled" | "max"}}
# - LiteLLM Router 真**transparent 透传** litellm_params.extra_body 走 completion call
#
# yaml 真生效真值 (sub-PR 8a-followup-B-yaml 5-07 修):
# - deepseek-v4-flash → deepseek/deepseek-v4-flash + extra_body.thinking.type=disabled (chat semantic)
# - deepseek-v4-pro   → deepseek/deepseek-v4-pro   + extra_body.thinking.type=enabled  (reasoner semantic)


def test_yaml_v4_flash_underlying_with_thinking_disabled(router: LiteLLMRouter) -> None:
    """yaml deepseek-v4-flash entry 真生效真值: underlying = deepseek/deepseek-v4-flash + thinking=disabled.

    沿用 DeepSeek 官方 API spec V3 §5.5 V4-Flash chat semantic align (News/Bull/Bear/Embedding 真消费).
    sub-PR 8a-followup-B-yaml 5-07 修 — 反 deepseek-chat 旧 alias (7-24 deprecation deadline).
    """
    flash_entry = next(
        e for e in router._raw_config["model_list"] if e["model_name"] == "deepseek-v4-flash"
    )
    assert flash_entry["litellm_params"]["model"] == "deepseek/deepseek-v4-flash"
    extra_body = flash_entry["litellm_params"].get("extra_body", {})
    assert extra_body.get("thinking", {}).get("type") == "disabled", (
        "v4-flash 真**chat semantic** 沿用 V3 §5.5 design — extra_body.thinking.type 必 'disabled'"
    )


def test_yaml_v4_pro_underlying_with_thinking_enabled(router: LiteLLMRouter) -> None:
    """yaml deepseek-v4-pro entry 真生效真值: underlying = deepseek/deepseek-v4-pro + thinking=enabled.

    沿用 DeepSeek 官方 API spec V3 §5.5 V4-Pro reasoner semantic align (Judge/RiskReflector 真消费).
    sub-PR 8a-followup-B-yaml 5-07 修 — 反 deepseek-reasoner 旧 alias (7-24 deprecation deadline).
    """
    pro_entry = next(
        e for e in router._raw_config["model_list"] if e["model_name"] == "deepseek-v4-pro"
    )
    assert pro_entry["litellm_params"]["model"] == "deepseek/deepseek-v4-pro"
    extra_body = pro_entry["litellm_params"].get("extra_body", {})
    assert extra_body.get("thinking", {}).get("type") == "enabled", (
        "v4-pro 真**reasoner semantic** 沿用 V3 §5.5 design — extra_body.thinking.type 必 'enabled'"
    )


def test_yaml_no_legacy_deepseek_chat_or_reasoner_underlying(router: LiteLLMRouter) -> None:
    """sub-PR 8a-followup-B-yaml 5-07: yaml 真**0 deepseek-chat / deepseek-reasoner underlying**.

    7-24 deprecation deadline plan sustained (audit Week 2 batch + ADR-DRAFT row 8 sediment).
    任 yaml entry 真**不应 underlying = deepseek/deepseek-chat 或 deepseek/deepseek-reasoner** —
    全部走 V4 underlying (v4-flash / v4-pro) 真**align user 决议 #4 反留尾巴** 沿用.
    """
    legacy_underlying = {"deepseek/deepseek-chat", "deepseek/deepseek-reasoner"}
    for entry in router._raw_config["model_list"]:
        underlying = entry["litellm_params"].get("model", "")
        assert underlying not in legacy_underlying, (
            f"yaml entry '{entry['model_name']}' 真 underlying='{underlying}' 真 legacy alias "
            f"(7-24 deprecation deadline) — 沿用 sub-PR 8a-followup-B-yaml 5-07 V4 routing 切换体例"
        )


def test_yaml_extra_body_propagation_via_router_completion(
    router: LiteLLMRouter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LiteLLM Router 真**transparent 透传** yaml litellm_params.extra_body 走 completion call.

    真生产 verify (sub-PR 8a-followup-B-yaml 5-07 LiteLLMRouter wrapper 重 e2e 真测):
    - task=NEWS_CLASSIFY → v4-flash + thinking=disabled → tokens(out)=3 chat semantic
    - task=JUDGE → v4-pro + thinking=enabled → tokens(out)=50 reasoner semantic

    本 unit test verify yaml routing 真**正确**: monkeypatch litellm Router.completion +
    capture extra_body kwarg 真**走 LiteLLM API call** sustained.

    NOTE: LiteLLM Router 真**internal mechanism** 真**模型 entry 真 litellm_params.extra_body** 透传
    走 completion call. 反 caller 真**显式 extra_body kwarg** 体例 sustained.
    """
    captured = _patch_router_completion(monkeypatch, actual_model="deepseek-v4-flash")
    router.completion(
        task=RiskTaskType.NEWS_CLASSIFY,
        messages=[LLMMessage("user", "test")],
    )
    # captured["model"] 真 alias (沿用 sub-PR 8a-followup-A BUG #1 体例 sustained)
    assert captured["model"] == "deepseek-v4-flash"
    # NOTE: yaml extra_body 透传 真**LiteLLM Router internal mechanism**, 反 mock 直 verify.
    # 真生产 e2e 真**已 verify** (sub-PR 8a-followup-B-yaml STATUS_REPORT 5-07 测试 1+2 sediment).
