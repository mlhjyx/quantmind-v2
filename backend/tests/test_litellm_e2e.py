r"""S3 LiteLLM e2e 冒烟 — Ollama qwen3:8b fallback path 真生产验证.

scope (2 e2e tests, sustained pytest.mark.requires_ollama):
- test_e2e_ollama_chat_qwen3_via_alias_override: 走 LiteLLMRouter.completion_with_alias_override
  强制 model_alias=FALLBACK_ALIAS, 验证 ollama_chat/qwen3:8b endpoint 沿用 + is_fallback 检测.
- test_e2e_budget_capped_forces_ollama_fallback: 走 BudgetAwareRouter.completion 真生产 flow,
  mock budget conn_factory 强制 CAPPED_100 状态 → 验证 fallback 触发 + actual_model 含 "qwen3".

skip logic:
- 模块级 socket probe localhost:11434 — 0 listening → skip 全模块.
- pytest -m "not requires_ollama" 真**默认排除** (反 CI / pre-push 跑).
- 沿用 LL-098 X10: e2e tests 仅本地 user 跑过 ollama install + ollama pull qwen3:8b 后跑.

依赖 (S3 runbook 03 user 接触 sediment):
1. Ollama D 盘 install (D:\Program Files\Ollama)
2. ollama pull qwen3:8b (~5.2 GB, D:\ollama-models)
3. Ollama service running (Get-Service Ollama → Status=Running)
4. config/litellm_router.yaml ollama_chat/qwen3:8b 沿用 PR #225 patch

关联:
- ADR-031 §6 (S3 Ollama wire sediment)
- docs/runbook/cc_automation/03_ollama_install_runbook.md
- backend/tests/test_litellm_budget.py (mock conn_factory 体例沿用)
"""
from __future__ import annotations

import socket
from datetime import date
from decimal import Decimal

import pytest

from backend.qm_platform.llm import (
    FALLBACK_ALIAS,
    BudgetAwareRouter,
    BudgetGuard,
    BudgetState,
    LiteLLMRouter,
    LLMMessage,
    RiskTaskType,
)

# ─────────────────────────────────────────────────────────────
# 模块级 Ollama 沿用 probe — 0 listening → skip 全模块
# ─────────────────────────────────────────────────────────────


def _ollama_running(host: str = "localhost", port: int = 11434, timeout: float = 1.0) -> bool:
    """TCP probe Ollama API endpoint (沿用 Test-NetConnection 体例)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (TimeoutError, OSError):
        return False


# requires_ollama marker + 自动 skip if 0 running (沿用 pyproject.toml markers cite)
pytestmark = [
    pytest.mark.requires_ollama,
    pytest.mark.skipif(
        not _ollama_running(),
        reason="Ollama not running on localhost:11434 — sustained S3 runbook 03 install + ollama pull qwen3:8b",
    ),
]


# ─────────────────────────────────────────────────────────────
# Mock budget conn_factory (沿用 test_litellm_budget.py 体例)
# ─────────────────────────────────────────────────────────────


class _CappedFakeCursor:
    """SELECT SUM(cost_usd_total) → 沿用强制 CAPPED 状态 (cost = $60 > $50 cap)."""

    def __init__(self) -> None:
        self._fetchone_value: tuple | None = None

    def execute(self, sql: str, params: tuple = ()) -> None:
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("SELECT COALESCE(SUM(COST_USD_TOTAL)"):
            # 强制返 $60 cost (> $50 monthly_budget × 1.00 cap = capped)
            self._fetchone_value = (Decimal("60.0"),)
        elif sql_upper.startswith("INSERT INTO LLM_COST_DAILY"):
            # record_cost UPSERT → 沿用 noop 模拟 (e2e 0 关心 UPSERT)
            self._fetchone_value = None
        else:
            raise NotImplementedError(f"e2e CappedFakeCursor 未模拟 SQL: {sql_upper[:80]}")

    def fetchone(self) -> tuple | None:
        return self._fetchone_value

    def close(self) -> None:
        pass


class _CappedFakeConn:
    def __init__(self) -> None:
        self.commit_called = 0
        self.close_called = 0

    def cursor(self) -> _CappedFakeCursor:
        return _CappedFakeCursor()

    def commit(self) -> None:
        self.commit_called += 1

    def close(self) -> None:
        self.close_called += 1


@pytest.fixture
def capped_conn_factory():
    def factory() -> _CappedFakeConn:
        return _CappedFakeConn()

    return factory


@pytest.fixture
def litellm_router_real(monkeypatch: pytest.MonkeyPatch) -> LiteLLMRouter:
    """走 yaml config 真生产 LiteLLMRouter (NOT mock).

    DEEPSEEK_API_KEY 沿用 .env (e2e 跑前 user 已 export).
    OLLAMA_BASE_URL 沿用 default http://localhost:11434 (Settings sediment).
    """
    # 反 .env 真值缺失 → fallback dummy key 防 yaml schema 检验 fail.
    # 真 fallback path 走 ollama_chat/qwen3:8b 反需 DeepSeek key.
    import os

    if not os.environ.get("DEEPSEEK_API_KEY"):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-used-fallback-only")
    if not os.environ.get("OLLAMA_BASE_URL"):
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    return LiteLLMRouter()


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────


def test_e2e_ollama_chat_qwen3_via_alias_override(
    litellm_router_real: LiteLLMRouter,
) -> None:
    """走 LiteLLMRouter.completion_with_alias_override(model_alias=FALLBACK_ALIAS).

    验证:
    - ollama_chat/qwen3:8b endpoint 走通 (沿用 yaml PR #225 patch)
    - response.content 非空 (qwen3 真生成)
    - response.is_fallback = True (actual_model 含 "qwen" 子串, 反 deepseek-chat / deepseek-reasoner)
    - response.cost_usd = 0 (本地 Ollama 0 cost, LiteLLM _hidden_params response_cost None or 0)
    - response.latency_ms > 0 (真生产沿用 measure)
    """
    response = litellm_router_real.completion_with_alias_override(
        task=RiskTaskType.NEWS_CLASSIFY,
        messages=[LLMMessage("user", "Reply with the single word 'OK' and nothing else.")],
        model_alias=FALLBACK_ALIAS,
        decision_id="e2e-s3-fallback-001",
        timeout=120.0,  # qwen3:8b CPU 沿用 ~30s, GPU ~2-5s, 120s 沿用 buffer
    )

    # 1. content 非空
    assert response.content, f"Ollama 返空 content: {response!r}"
    # 2. is_fallback (PRIMARY_MODEL_SUBSTRINGS 检测 actual_model 不含 "deepseek-chat" / "deepseek-reasoner" 子串)
    assert response.is_fallback is True, f"is_fallback 反 True, actual_model={response.model}"
    # 3. cost_usd = 0 (本地 Ollama 0 cost)
    assert response.cost_usd == Decimal("0"), f"cost_usd 反 0: {response.cost_usd}"
    # 4. latency_ms > 0 (沿用 measure)
    assert response.latency_ms > 0, f"latency_ms 反 measured: {response.latency_ms}"
    # 5. decision_id 透传 (沿用 PR #222 contract)
    assert response.decision_id == "e2e-s3-fallback-001"
    # 6. actual_model 含 "qwen" (沿用 ollama_chat/qwen3:8b 路由)
    assert "qwen" in response.model.lower(), f"actual_model 反 qwen: {response.model}"


def test_e2e_budget_capped_forces_ollama_fallback(
    litellm_router_real: LiteLLMRouter,
    capped_conn_factory,
) -> None:
    """走 BudgetAwareRouter.completion 真生产 flow, 强制 CAPPED_100 → fallback.

    Mock budget conn_factory 返 cost=$60 > $50 cap → BudgetState.CAPPED_100.
    BudgetAwareRouter 4 步 flow:
        1. snapshot.state == CAPPED_100
        2. is_capped + strict=False (default) → 0 raise
        3. router.completion_with_alias_override(model_alias=FALLBACK_ALIAS) → ollama_chat/qwen3:8b
        4. budget.record_cost(0, is_fallback=True, is_capped=True) → mock UPSERT noop

    验证:
    - response.is_fallback = True (强制 fallback)
    - actual_model 含 "qwen" (走 ollama_chat 路由)
    - response.content 非空 (qwen3 真生成)
    """
    budget = BudgetGuard(
        capped_conn_factory,
        monthly_budget_usd=Decimal("50.0"),
        warn_threshold=Decimal("0.80"),
        cap_threshold=Decimal("1.00"),
    )

    # 验证 mock 真返 CAPPED 状态
    snapshot = budget.check(today=date(2026, 5, 15))
    assert snapshot.state is BudgetState.CAPPED_100, (
        f"mock 反返 CAPPED, state={snapshot.state}"
    )

    aware = BudgetAwareRouter(litellm_router_real, budget, strict=False)

    response = aware.completion(
        task=RiskTaskType.JUDGE,  # primary deepseek-v4-pro, capped 后强制 fallback
        messages=[LLMMessage("user", "Reply with 'OK' only.")],
        decision_id="e2e-s3-capped-002",
        timeout=120.0,
    )

    # 1. is_fallback = True
    assert response.is_fallback is True, f"is_fallback 反 True: {response.model}"
    # 2. actual_model 含 "qwen"
    assert "qwen" in response.model.lower(), f"actual_model 反 qwen: {response.model}"
    # 3. content 非空
    assert response.content, f"Ollama 返空 content: {response!r}"
    # 4. decision_id 透传
    assert response.decision_id == "e2e-s3-capped-002"
