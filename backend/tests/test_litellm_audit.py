"""S2.3 LLMCallLogger + LLMCallRecord + compute_prompt_hash 单元测试.

scope (10 tests):
- compute_prompt_hash sha256 truncated 16 hex (决议 5 沿用)
- compute_prompt_hash 幂等 (sort_keys=True, dict 顺序无关)
- LLMCallRecord frozen + 13 字段对齐 llm_call_log
- LLMCallLogger.log_call INSERT 模拟 (mock conn_factory)
- LLMCallLogger 失败 path: INSERT 异常 → fail-loud warning + return False (决议 7)
- LLMCallLogger 失败 path: conn_factory raise → fail-loud warning + return False
- BudgetAwareRouter 加 audit param 后 → completion 真触发 audit.log_call (additive)
- BudgetAwareRouter 不传 audit (None) → 0 audit log (反 break 老 caller)
- BudgetAwareRouter audit failure → completion 沿用返 success (决议 7 反 break)
- LLMCallRecord decision_id None 允许 (决议 6 沿用)

体例:
- 沿用 backend/tests/test_litellm_budget.py mock conn_factory (FakeStorage + FakeCursor + FakeConn)
- 沿用 backend/tests/test_litellm_budget.py monkeypatch Router.completion
"""
from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError
from datetime import datetime
from decimal import Decimal
from threading import Lock
from types import SimpleNamespace
from typing import Any

import pytest

# llm-internal-allow:test-only — S4 PR #226 sediment, mock 体例真依赖 _internal/ 直接 import
from backend.qm_platform.llm import LLMMessage, RiskTaskType
from backend.qm_platform.llm._internal import router as router_module
from backend.qm_platform.llm._internal.audit import (
    LLMCallLogger,
    LLMCallRecord,
    compute_prompt_hash,
)
from backend.qm_platform.llm._internal.budget import (
    BudgetAwareRouter,
    BudgetGuard,
    BudgetState,
)
from backend.qm_platform.llm._internal.router import LiteLLMRouter

# ─────────────────────────────────────────────────────────────
# In-memory mock conn_factory for llm_call_log (新增, 沿用 budget tests 体例)
# ─────────────────────────────────────────────────────────────


class _FakeCallLogRow:
    """llm_call_log 单行 (跟 13 字段对齐)."""

    def __init__(self, **kwargs: Any) -> None:
        self.triggered_at: datetime = kwargs["triggered_at"]
        self.task: str = kwargs["task"]
        self.primary_alias: str = kwargs["primary_alias"]
        self.actual_model: str = kwargs["actual_model"]
        self.is_fallback: bool = kwargs["is_fallback"]
        self.budget_state: str = kwargs["budget_state"]
        self.tokens_in: int = kwargs["tokens_in"]
        self.tokens_out: int = kwargs["tokens_out"]
        self.cost_usd: Decimal = kwargs["cost_usd"]
        self.latency_ms: int | None = kwargs["latency_ms"]
        self.decision_id: str | None = kwargs["decision_id"]
        self.prompt_hash: str | None = kwargs["prompt_hash"]
        self.error_class: str | None = kwargs["error_class"]


class _FakeCallLogStorage:
    """in-memory list 模拟 llm_call_log (INSERT only)."""

    def __init__(self) -> None:
        self.rows: list[_FakeCallLogRow] = []
        self._lock = Lock()

    def insert(self, **kwargs: Any) -> None:
        with self._lock:
            self.rows.append(_FakeCallLogRow(**kwargs))

    def count(self) -> int:
        with self._lock:
            return len(self.rows)


class _FakeCallLogCursor:
    """SQL 模式解析: INSERT INTO llm_call_log."""

    def __init__(self, storage: _FakeCallLogStorage, *, raise_on_execute: bool = False) -> None:
        self._storage = storage
        self._raise = raise_on_execute

    def execute(self, sql: str, params: tuple = ()) -> None:
        if self._raise:
            raise RuntimeError("simulated INSERT failure")

        sql_upper = sql.strip().upper()
        if "INSERT INTO LLM_CALL_LOG" in sql_upper:
            (
                triggered_at, task, primary_alias, actual_model,
                is_fallback, budget_state,
                tokens_in, tokens_out, cost_usd, latency_ms,
                decision_id, prompt_hash, error_class,
            ) = params
            self._storage.insert(
                triggered_at=triggered_at,
                task=task,
                primary_alias=primary_alias,
                actual_model=actual_model,
                is_fallback=is_fallback,
                budget_state=budget_state,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                decision_id=decision_id,
                prompt_hash=prompt_hash,
                error_class=error_class,
            )
        else:
            raise NotImplementedError(f"_FakeCallLogCursor 未模拟 SQL: {sql_upper[:80]}")

    def close(self) -> None:
        pass


class _FakeCallLogConn:
    def __init__(self, storage: _FakeCallLogStorage, *, raise_on_execute: bool = False) -> None:
        self._storage = storage
        self._raise = raise_on_execute
        self.commit_called = 0
        self.rollback_called = 0
        self.close_called = 0

    def cursor(self) -> _FakeCallLogCursor:
        return _FakeCallLogCursor(self._storage, raise_on_execute=self._raise)

    def commit(self) -> None:
        self.commit_called += 1

    def rollback(self) -> None:
        self.rollback_called += 1

    def close(self) -> None:
        self.close_called += 1


@pytest.fixture
def call_log_storage() -> _FakeCallLogStorage:
    return _FakeCallLogStorage()


@pytest.fixture
def call_log_conn_factory(call_log_storage: _FakeCallLogStorage):
    def factory() -> _FakeCallLogConn:
        return _FakeCallLogConn(call_log_storage)

    return factory


@pytest.fixture
def llm_audit(call_log_conn_factory) -> LLMCallLogger:
    return LLMCallLogger(call_log_conn_factory)


# ─────────────────────────────────────────────────────────────
# Combined fixtures for BudgetAwareRouter integration (沿用 test_litellm_budget.py)
# ─────────────────────────────────────────────────────────────


class _CombinedFakeConn:
    """同时模拟 llm_cost_daily UPSERT + llm_call_log INSERT (BudgetAwareRouter integration)."""

    def __init__(self, cost_storage: dict, call_log_storage: _FakeCallLogStorage) -> None:
        self._cost_storage = cost_storage
        self._call_log_storage = call_log_storage
        self.commit_called = 0
        self.rollback_called = 0
        self.close_called = 0

    def cursor(self) -> Any:
        return _CombinedFakeCursor(self._cost_storage, self._call_log_storage)

    def commit(self) -> None:
        self.commit_called += 1

    def rollback(self) -> None:
        self.rollback_called += 1

    def close(self) -> None:
        self.close_called += 1


class _CombinedFakeCursor:
    def __init__(self, cost_storage: dict, call_log_storage: _FakeCallLogStorage) -> None:
        self._cost_storage = cost_storage
        self._call_log_storage = call_log_storage
        self._fetchone_value: tuple | None = None

    def execute(self, sql: str, params: tuple = ()) -> None:
        sql_upper = sql.strip().upper()
        if sql_upper.startswith("INSERT INTO LLM_COST_DAILY"):
            day, cost_usd, fallback_inc, capped_inc = params
            row = self._cost_storage.setdefault(day, {"cost": Decimal("0"), "calls": 0, "fb": 0, "cap": 0})
            row["cost"] += cost_usd
            row["calls"] += 1
            row["fb"] += fallback_inc
            row["cap"] += capped_inc
            self._fetchone_value = None
        elif sql_upper.startswith("SELECT COALESCE(SUM(COST_USD_TOTAL)"):
            month_start, today = params
            total = Decimal("0")
            for d, row in self._cost_storage.items():
                if month_start <= d <= today:
                    total += row["cost"]
            self._fetchone_value = (total,)
        elif "INSERT INTO LLM_CALL_LOG" in sql_upper:
            (
                triggered_at, task, primary_alias, actual_model,
                is_fallback, budget_state,
                tokens_in, tokens_out, cost_usd, latency_ms,
                decision_id, prompt_hash, error_class,
            ) = params
            self._call_log_storage.insert(
                triggered_at=triggered_at,
                task=task,
                primary_alias=primary_alias,
                actual_model=actual_model,
                is_fallback=is_fallback,
                budget_state=budget_state,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                decision_id=decision_id,
                prompt_hash=prompt_hash,
                error_class=error_class,
            )
            self._fetchone_value = None
        else:
            raise NotImplementedError(f"_CombinedFakeCursor 未模拟 SQL: {sql_upper[:80]}")

    def fetchone(self) -> tuple | None:
        return self._fetchone_value

    def close(self) -> None:
        pass


@pytest.fixture
def combined_storage() -> tuple[dict, _FakeCallLogStorage]:
    return {}, _FakeCallLogStorage()


@pytest.fixture
def combined_conn_factory(combined_storage):
    cost, call_log = combined_storage

    def factory() -> _CombinedFakeConn:
        return _CombinedFakeConn(cost, call_log)

    return factory


# ─────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────


def test_compute_prompt_hash_returns_16_char_lowercase_hex() -> None:
    """compute_prompt_hash 返 16-char hex (决议 5 沿用 sha256 truncated)."""
    h = compute_prompt_hash([LLMMessage("user", "hello")])
    assert len(h) == 16
    assert h == h.lower()
    assert all(c in "0123456789abcdef" for c in h)


def test_compute_prompt_hash_idempotent_dict_order_invariant() -> None:
    """compute_prompt_hash 真幂等 + dict 顺序无关 (sort_keys=True)."""
    h1 = compute_prompt_hash([LLMMessage("user", "msg1"), LLMMessage("assistant", "reply")])
    h2 = compute_prompt_hash([LLMMessage("user", "msg1"), LLMMessage("assistant", "reply")])
    h3 = compute_prompt_hash(
        [{"role": "user", "content": "msg1"}, {"role": "assistant", "content": "reply"}]
    )
    h4 = compute_prompt_hash(
        [{"content": "msg1", "role": "user"}, {"content": "reply", "role": "assistant"}]
    )
    assert h1 == h2 == h3 == h4
    h_diff = compute_prompt_hash([LLMMessage("user", "msg2")])
    assert h1 != h_diff


def test_llm_call_record_frozen_and_field_alignment() -> None:
    """LLMCallRecord frozen + 13 字段全 (跟 llm_call_log 列对齐)."""
    record = LLMCallRecord(
        task=RiskTaskType.JUDGE,
        primary_alias="deepseek-v4-pro",
        actual_model="deepseek/deepseek-reasoner",
        is_fallback=False,
        budget_state=BudgetState.NORMAL,
        tokens_in=120,
        tokens_out=80,
        cost_usd=Decimal("0.0042"),
        latency_ms=450,
        decision_id="risk-001",
        prompt_hash="abcdef0123456789",
        error_class=None,
    )
    # frozen 反 mutation
    with pytest.raises(FrozenInstanceError):
        record.tokens_in = 999  # type: ignore[misc]
    # 字段值
    assert record.task is RiskTaskType.JUDGE
    assert record.budget_state is BudgetState.NORMAL
    assert record.cost_usd == Decimal("0.0042")
    assert record.decision_id == "risk-001"
    assert record.error_class is None


def test_llm_call_record_decision_id_optional() -> None:
    """LLMCallRecord decision_id None 允许 (决议 6 沿用反 break)."""
    record = LLMCallRecord(
        task=RiskTaskType.NEWS_CLASSIFY,
        primary_alias="deepseek-v4-flash",
        actual_model="deepseek/deepseek-chat",
        is_fallback=False,
        budget_state=BudgetState.NORMAL,
        decision_id=None,
        prompt_hash=None,
    )
    assert record.decision_id is None
    assert record.prompt_hash is None


def test_llm_call_logger_inserts_row_on_success(
    llm_audit: LLMCallLogger,
    call_log_storage: _FakeCallLogStorage,
) -> None:
    """LLMCallLogger.log_call → INSERT 1 row (success path)."""
    record = LLMCallRecord(
        task=RiskTaskType.JUDGE,
        primary_alias="deepseek-v4-pro",
        actual_model="deepseek/deepseek-reasoner",
        is_fallback=False,
        budget_state=BudgetState.WARN_80,
        tokens_in=50, tokens_out=20,
        cost_usd=Decimal("0.005"),
        latency_ms=300,
        decision_id="d-100",
        prompt_hash="0123456789abcdef",
    )
    ok = llm_audit.log_call(record)
    assert ok is True
    assert call_log_storage.count() == 1
    row = call_log_storage.rows[0]
    assert row.task == "judge"
    assert row.primary_alias == "deepseek-v4-pro"
    assert row.budget_state == "warn_80"
    assert row.cost_usd == Decimal("0.005")
    assert row.decision_id == "d-100"
    assert row.error_class is None
    # 沿用 reviewer Chunk C P2-2 修: triggered_at 真 datetime 实例 (反 silent string drift)
    assert isinstance(row.triggered_at, datetime)


def test_llm_call_logger_insert_failure_returns_false_and_logs_warning(
    call_log_storage: _FakeCallLogStorage,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """INSERT 异常 → fail-loud warning + return False (决议 7 反 break completion)."""
    def factory() -> _FakeCallLogConn:
        return _FakeCallLogConn(call_log_storage, raise_on_execute=True)

    audit = LLMCallLogger(factory)
    record = LLMCallRecord(
        task=RiskTaskType.JUDGE,
        primary_alias="deepseek-v4-pro",
        actual_model="deepseek/deepseek-reasoner",
        is_fallback=False,
        budget_state=BudgetState.NORMAL,
    )
    with caplog.at_level(logging.WARNING, logger="backend.qm_platform.llm.audit"):
        ok = audit.log_call(record)
    assert ok is False
    assert call_log_storage.count() == 0  # 0 row inserted
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("llm_audit_insert_failed" in r.message for r in warn_records)


def test_llm_call_logger_conn_factory_failure_returns_false(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """conn_factory raise → fail-loud warning + return False (反 break completion)."""
    def factory() -> _FakeCallLogConn:
        raise ConnectionError("PG unavailable")

    audit = LLMCallLogger(factory)
    record = LLMCallRecord(
        task=RiskTaskType.NEWS_CLASSIFY,
        primary_alias="deepseek-v4-flash",
        actual_model="deepseek/deepseek-chat",
        is_fallback=False,
        budget_state=BudgetState.NORMAL,
    )
    with caplog.at_level(logging.WARNING, logger="backend.qm_platform.llm.audit"):
        ok = audit.log_call(record)
    assert ok is False
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("llm_audit_conn_factory_failed" in r.message for r in warn_records)


def test_aware_router_with_audit_triggers_log_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BudgetAwareRouter 加 audit → completion 后 audit.log_call 真触发 (additive)."""
    cost_storage: dict = {}
    call_log_storage = _FakeCallLogStorage()

    def factory() -> _CombinedFakeConn:
        return _CombinedFakeConn(cost_storage, call_log_storage)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def mock_completion(self: Any, **kwargs: Any) -> SimpleNamespace:
        message = SimpleNamespace(content="ok")
        choice = SimpleNamespace(message=message)
        usage = SimpleNamespace(prompt_tokens=12, completion_tokens=7)
        return SimpleNamespace(
            choices=[choice],
            model="deepseek/deepseek-chat",
            usage=usage,
            _hidden_params={"response_cost": 0.0021},
        )

    monkeypatch.setattr(router_module.Router, "completion", mock_completion, raising=True)

    router = LiteLLMRouter()
    budget = BudgetGuard(
        factory,
        monthly_budget_usd=Decimal("50.0"),
        warn_threshold=Decimal("0.80"),
        cap_threshold=Decimal("1.00"),
    )
    audit = LLMCallLogger(factory)
    aware = BudgetAwareRouter(router, budget, audit=audit)

    response = aware.completion(
        task=RiskTaskType.NEWS_CLASSIFY,
        messages=[LLMMessage("user", "分类")],
        decision_id="d-999",
    )

    assert response.is_fallback is False
    assert call_log_storage.count() == 1
    row = call_log_storage.rows[0]
    assert row.task == "news_classify"
    assert row.primary_alias == "deepseek-v4-flash"
    assert row.actual_model == "deepseek/deepseek-chat"
    assert row.budget_state == "normal"
    assert row.tokens_in == 12
    assert row.tokens_out == 7
    assert row.decision_id == "d-999"
    assert row.prompt_hash is not None
    assert len(row.prompt_hash) == 16
    assert row.error_class is None


def test_aware_router_without_audit_skips_log_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """audit None → 0 audit log (反 break 老 caller, 沿用决议 6 NULL 允许 体例)."""
    cost_storage: dict = {}
    call_log_storage = _FakeCallLogStorage()

    def factory() -> _CombinedFakeConn:
        return _CombinedFakeConn(cost_storage, call_log_storage)

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def mock_completion(self: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            model="deepseek/deepseek-chat",
            usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            _hidden_params={"response_cost": 0.001},
        )

    monkeypatch.setattr(router_module.Router, "completion", mock_completion, raising=True)

    router = LiteLLMRouter()
    budget = BudgetGuard(
        factory,
        monthly_budget_usd=Decimal("50.0"),
        warn_threshold=Decimal("0.80"),
        cap_threshold=Decimal("1.00"),
    )
    aware = BudgetAwareRouter(router, budget)  # audit None default

    aware.completion(
        task=RiskTaskType.JUDGE,
        messages=[LLMMessage("user", "x")],
    )
    assert call_log_storage.count() == 0
    assert aware.audit is None


def test_aware_router_audit_failure_does_not_break_completion(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """audit.log_call 失败 → completion 沿用返 success (决议 7 反 break, 铁律 33)."""
    cost_storage: dict = {}

    def cost_factory() -> _CombinedFakeConn:
        return _CombinedFakeConn(cost_storage, _FakeCallLogStorage())

    # audit conn_factory 真 raise (模拟 PG conn fail)
    def audit_factory() -> _FakeCallLogConn:
        raise ConnectionError("audit PG unavailable")

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-used")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def mock_completion(self: Any, **kwargs: Any) -> SimpleNamespace:
        # JUDGE → primary deepseek-v4-pro → expected "deepseek-reasoner" 子串
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
            model="deepseek/deepseek-reasoner",
            usage=SimpleNamespace(prompt_tokens=2, completion_tokens=2),
            _hidden_params={"response_cost": 0.001},
        )

    monkeypatch.setattr(router_module.Router, "completion", mock_completion, raising=True)

    router = LiteLLMRouter()
    budget = BudgetGuard(
        cost_factory,
        monthly_budget_usd=Decimal("50.0"),
        warn_threshold=Decimal("0.80"),
        cap_threshold=Decimal("1.00"),
    )
    audit = LLMCallLogger(audit_factory)
    aware = BudgetAwareRouter(router, budget, audit=audit)

    with caplog.at_level(logging.WARNING, logger="backend.qm_platform.llm.audit"):
        response = aware.completion(
            task=RiskTaskType.JUDGE,
            messages=[LLMMessage("user", "x")],
            decision_id="d-fail",
        )
    # completion 沿用 success (audit 失败不 break)
    assert response.content == "ok"
    assert response.is_fallback is False
    # 但 fail-loud warning 真 emit
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("llm_audit_conn_factory_failed" in r.message for r in warn_records)
