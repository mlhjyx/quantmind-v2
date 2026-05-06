"""S2.2 BudgetGuard + BudgetAwareRouter 单元测试.

scope:
- BudgetGuard.check 月聚合 cost + 3 state 计算
- BudgetGuard.record_cost UPSERT 原子 (并发 100x 累加)
- BudgetAwareRouter wrapper composition (LiteLLMRouter + BudgetGuard)
- WARN_80 logger.warning structured (extra dict)
- CAPPED_100 强制 fallback (走 router.completion_with_alias_override)
- CAPPED_100 + strict → BudgetExceededError raise
- decision_id 透传 chain (PR #222 LLMResponse contract)
- LiteLLMRouter.completion_with_alias_override (path C, additive)

体例: monkeypatch + in-memory dict mock conn_factory (沿用 risk engine tests, 0 testcontainers).

关联:
- ADR-031 §6 (S2 渐进 deprecate plan)
- V3 §20.1 #6 (LLM 月预算 $50 + 80% warn + 100% fallback)
- LL-109 候选 (race window, P3 audit Week 2 候选, 本 PR cite 不 sediment)
"""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from pathlib import Path
from threading import Lock, Thread
from types import SimpleNamespace
from typing import Any

import pytest

# llm-internal-allow:test-only — S4 PR #226 sediment, mock 体例真依赖 _internal/ 直接 import
from backend.qm_platform.llm import (
    LLMMessage,
    LLMResponse,
    RiskTaskType,
)
from backend.qm_platform.llm._internal import router as router_module
from backend.qm_platform.llm._internal.budget import (
    BudgetAwareRouter,
    BudgetExceededError,
    BudgetGuard,
    BudgetSnapshot,
    BudgetState,
)
from backend.qm_platform.llm._internal.router import FALLBACK_ALIAS, LiteLLMRouter

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ROUTER_CONFIG = REPO_ROOT / "config" / "litellm_router.yaml"


# ─────────────────────────────────────────────────────────────
# In-memory mock conn_factory (沿用 risk engine tests 体例)
# ─────────────────────────────────────────────────────────────


class _FakeRow:
    """日期 row 内部状态 (跟 llm_cost_daily 列对齐)."""

    def __init__(self, day: date) -> None:
        self.day = day
        self.cost_usd_total = Decimal("0")
        self.call_count = 0
        self.fallback_count = 0
        self.capped_count = 0


class _FakeStorage:
    """in-memory dict 模拟 llm_cost_daily 表 (UPSERT + SUM 查询)."""

    def __init__(self) -> None:
        self._rows: dict[date, _FakeRow] = {}
        self._lock = Lock()

    def upsert(self, day: date, cost_usd: Decimal, fallback_inc: int, capped_inc: int) -> None:
        with self._lock:
            row = self._rows.setdefault(day, _FakeRow(day))
            row.cost_usd_total += cost_usd
            row.call_count += 1
            row.fallback_count += fallback_inc
            row.capped_count += capped_inc

    def sum_cost(self, month_start: date, today: date) -> Decimal:
        with self._lock:
            total = Decimal("0")
            for d, row in self._rows.items():
                if month_start <= d <= today:
                    total += row.cost_usd_total
            return total

    def get(self, day: date) -> _FakeRow | None:
        with self._lock:
            return self._rows.get(day)


class _FakeCursor:
    """SQL 模式解析: INSERT ... ON CONFLICT (UPSERT) / SELECT SUM."""

    def __init__(self, storage: _FakeStorage) -> None:
        self._storage = storage
        self._fetchone_value: tuple | None = None

    def execute(self, sql: str, params: tuple = ()) -> None:
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT INTO LLM_COST_DAILY"):
            day, cost_usd, fallback_inc, capped_inc = params
            self._storage.upsert(day, cost_usd, fallback_inc, capped_inc)
            self._fetchone_value = None
        elif sql_upper.startswith("SELECT COALESCE(SUM(COST_USD_TOTAL)"):
            month_start, today = params
            total = self._storage.sum_cost(month_start, today)
            self._fetchone_value = (total,)
        else:
            raise NotImplementedError(f"_FakeCursor 真未模拟 SQL: {sql_upper[:80]}")

    def fetchone(self) -> tuple | None:
        return self._fetchone_value

    def close(self) -> None:
        pass


class _FakeConn:
    def __init__(self, storage: _FakeStorage) -> None:
        self._storage = storage
        self.commit_called = 0
        self.close_called = 0

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._storage)

    def commit(self) -> None:
        self.commit_called += 1

    def close(self) -> None:
        self.close_called += 1


@pytest.fixture
def storage() -> _FakeStorage:
    return _FakeStorage()


@pytest.fixture
def conn_factory(storage: _FakeStorage):
    def factory() -> _FakeConn:
        return _FakeConn(storage)

    return factory


@pytest.fixture
def budget(conn_factory) -> BudgetGuard:
    return BudgetGuard(
        conn_factory,
        monthly_budget_usd=Decimal("50.0"),
        warn_threshold=Decimal("0.80"),
        cap_threshold=Decimal("1.00"),
    )


@pytest.fixture
def litellm_router(monkeypatch: pytest.MonkeyPatch) -> LiteLLMRouter:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    return LiteLLMRouter()


def _patch_router_completion(
    monkeypatch: pytest.MonkeyPatch,
    *,
    actual_model: str,
    cost: float = 0.001,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def mock_completion(self: Any, **kwargs: Any) -> SimpleNamespace:
        captured["model"] = kwargs.get("model")
        captured["messages"] = kwargs.get("messages")
        message = SimpleNamespace(content="ok")
        choice = SimpleNamespace(message=message)
        usage = SimpleNamespace(prompt_tokens=5, completion_tokens=3)
        return SimpleNamespace(
            choices=[choice],
            model=actual_model,
            usage=usage,
            _hidden_params={"response_cost": cost},
        )

    monkeypatch.setattr(router_module.Router, "completion", mock_completion, raising=True)
    return captured


# ─────────────────────────────────────────────────────────────
# BudgetGuard tests
# ─────────────────────────────────────────────────────────────


def test_budget_invalid_thresholds_raise(conn_factory) -> None:
    """非法阈值 (0/负/warn≥cap) → ValueError fail-loud (铁律 33)."""
    with pytest.raises(ValueError, match="monthly_budget_usd 必须 >0"):
        BudgetGuard(
            conn_factory,
            monthly_budget_usd=Decimal("0"),
            warn_threshold=Decimal("0.80"),
            cap_threshold=Decimal("1.00"),
        )
    with pytest.raises(ValueError, match="阈值非法"):
        BudgetGuard(
            conn_factory,
            monthly_budget_usd=Decimal("50"),
            warn_threshold=Decimal("1.00"),
            cap_threshold=Decimal("1.00"),
        )


def test_budget_check_normal_state(budget: BudgetGuard, storage: _FakeStorage) -> None:
    """0 cost → state == NORMAL."""
    snapshot = budget.check(today=date(2026, 5, 15))
    assert isinstance(snapshot, BudgetSnapshot)
    assert snapshot.state is BudgetState.NORMAL
    assert snapshot.month_to_date_cost_usd == Decimal("0")
    assert snapshot.warn_threshold_usd == Decimal("40.0")
    assert snapshot.cap_threshold_usd == Decimal("50.0")


def test_budget_check_warn_80_state(budget: BudgetGuard, storage: _FakeStorage) -> None:
    """cost = 42 (84%) → state == WARN_80."""
    storage.upsert(date(2026, 5, 1), Decimal("42"), 0, 0)
    snapshot = budget.check(today=date(2026, 5, 15))
    assert snapshot.state is BudgetState.WARN_80


def test_budget_check_capped_100_state(budget: BudgetGuard, storage: _FakeStorage) -> None:
    """cost = 55 (110%) → state == CAPPED_100."""
    storage.upsert(date(2026, 5, 1), Decimal("55"), 0, 0)
    snapshot = budget.check(today=date(2026, 5, 15))
    assert snapshot.state is BudgetState.CAPPED_100


def test_budget_record_cost_upsert_atomic_concurrent_100x(budget: BudgetGuard, storage: _FakeStorage) -> None:
    """并发 record_cost(0.001) × 100 → SUM == 0.1 (0 lost update, 沿用 lock 体例)."""
    today = date(2026, 5, 15)

    def worker() -> None:
        budget.record_cost(Decimal("0.001"), is_fallback=False, is_capped=False, today=today)

    threads = [Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    row = storage.get(today)
    assert row is not None
    assert row.cost_usd_total == Decimal("0.100")
    assert row.call_count == 100
    assert row.fallback_count == 0
    assert row.capped_count == 0


def test_budget_record_cost_increments_3_counters(budget: BudgetGuard, storage: _FakeStorage) -> None:
    """fallback_count + capped_count + call_count 区分 record."""
    today = date(2026, 5, 15)
    budget.record_cost(Decimal("0.01"), is_fallback=False, is_capped=False, today=today)
    budget.record_cost(Decimal("0.02"), is_fallback=True, is_capped=False, today=today)
    budget.record_cost(Decimal("0.03"), is_fallback=True, is_capped=True, today=today)

    row = storage.get(today)
    assert row is not None
    assert row.cost_usd_total == Decimal("0.06")
    assert row.call_count == 3
    assert row.fallback_count == 2
    assert row.capped_count == 1


# ─────────────────────────────────────────────────────────────
# BudgetAwareRouter tests
# ─────────────────────────────────────────────────────────────


def test_aware_router_normal_passes_through(
    litellm_router: LiteLLMRouter,
    budget: BudgetGuard,
    storage: _FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NORMAL 状态 → 透传 inner LiteLLMRouter.completion + record_cost."""
    captured = _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-v4-flash", cost=0.0042)
    aware = BudgetAwareRouter(litellm_router, budget)

    response = aware.completion(
        task=RiskTaskType.NEWS_CLASSIFY,
        messages=[LLMMessage("user", "分类")],
        decision_id="d-001",
    )

    assert isinstance(response, LLMResponse)
    assert response.is_fallback is False
    assert response.decision_id == "d-001"
    assert captured["model"] == "deepseek-v4-flash"


def test_aware_router_warn_80_logs_structured_warning(
    litellm_router: LiteLLMRouter,
    budget: BudgetGuard,
    storage: _FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """WARN_80 → logger.warning 含 extra dict (S2.3 audit ingest 前向兼容)."""
    storage.upsert(date.today().replace(day=1), Decimal("42"), 0, 0)
    _patch_router_completion(monkeypatch, actual_model="deepseek/deepseek-v4-flash", cost=0.001)
    aware = BudgetAwareRouter(litellm_router, budget)

    with caplog.at_level(logging.WARNING, logger="backend.qm_platform.llm.budget"):
        aware.completion(task=RiskTaskType.JUDGE, messages=[LLMMessage("user", "x")])

    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warn_records, "WARN_80 状态未触发 logger.warning"
    rec = warn_records[0]
    assert rec.message == "llm_budget_warn"
    assert getattr(rec, "event", None) == "llm_budget_warn"
    assert getattr(rec, "state", None) == "warn_80"
    assert getattr(rec, "task", None) == "judge"


def test_aware_router_capped_forces_fallback(
    litellm_router: LiteLLMRouter,
    budget: BudgetGuard,
    storage: _FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CAPPED_100 + strict=False → 强制 router.completion_with_alias_override(qwen3-local)."""
    storage.upsert(date.today().replace(day=1), Decimal("55"), 0, 0)
    captured = _patch_router_completion(monkeypatch, actual_model="ollama/qwen3:8b", cost=0.0)
    aware = BudgetAwareRouter(litellm_router, budget, strict=False)

    response = aware.completion(
        task=RiskTaskType.JUDGE,
        messages=[LLMMessage("user", "x")],
        decision_id="d-cap-1",
    )

    assert captured["model"] == FALLBACK_ALIAS == "qwen3-local"
    assert response.is_fallback is True
    assert response.decision_id == "d-cap-1"

    today_row = storage.get(date.today())
    assert today_row is not None
    assert today_row.capped_count == 1
    assert today_row.fallback_count == 1


def test_aware_router_capped_strict_raises(
    litellm_router: LiteLLMRouter,
    budget: BudgetGuard,
    storage: _FakeStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CAPPED_100 + strict=True → BudgetExceededError raise (反 silent fallback)."""
    storage.upsert(date.today().replace(day=1), Decimal("55"), 0, 0)
    _patch_router_completion(monkeypatch, actual_model="should-not-be-called")
    aware = BudgetAwareRouter(litellm_router, budget, strict=True)

    with pytest.raises(BudgetExceededError, match="capped"):
        aware.completion(
            task=RiskTaskType.RISK_REFLECTOR,
            messages=[LLMMessage("user", "反思")],
            decision_id="strict-d-1",
        )


def test_router_completion_with_alias_override_path_c(
    litellm_router: LiteLLMRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """path C — completion_with_alias_override 强制 model_alias 不改 task → primary 默认 mapping."""
    captured = _patch_router_completion(monkeypatch, actual_model="ollama/qwen3:8b")

    response = litellm_router.completion_with_alias_override(
        task=RiskTaskType.JUDGE,            # primary v4-pro, 强制覆盖到 qwen3-local
        messages=[LLMMessage("user", "x")],
        model_alias=FALLBACK_ALIAS,
        decision_id="d-override-1",
    )

    assert captured["model"] == FALLBACK_ALIAS
    assert response.is_fallback is True       # primary v4-pro 期望 deepseek-reasoner, qwen 命中 fallback 检测
    assert response.decision_id == "d-override-1"


def test_router_completion_with_alias_override_unknown_task_raises(
    litellm_router: LiteLLMRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """path C 仍 fail-loud unknown task (反 silent fallback, 沿用铁律 33)."""
    from backend.qm_platform.llm import UnknownTaskError
    _patch_router_completion(monkeypatch, actual_model="x")

    with pytest.raises(UnknownTaskError):
        litellm_router.completion_with_alias_override(
            task="bogus",  # type: ignore[arg-type]
            messages=[LLMMessage("user", "x")],
            model_alias=FALLBACK_ALIAS,
        )


def test_router_completion_with_alias_override_unknown_alias_raises(
    litellm_router: LiteLLMRouter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """path C — model_alias 不在 yaml model_list → RouterConfigError (反 caller typo/silent miss).

    沿用 reviewer Chunk C P3 hardening (defensive fail-loud, 铁律 33).
    """
    from backend.qm_platform.llm import RouterConfigError
    _patch_router_completion(monkeypatch, actual_model="x")

    with pytest.raises(RouterConfigError, match="不在 yaml model_list"):
        litellm_router.completion_with_alias_override(
            task=RiskTaskType.JUDGE,
            messages=[LLMMessage("user", "x")],
            model_alias="future-v5-alias-typo",
        )
