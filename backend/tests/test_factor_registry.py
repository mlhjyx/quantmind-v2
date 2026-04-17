"""DBFactorRegistry 单测 — MVP 1.3b (get_direction + cache) + MVP 1.3c (register/get_active/update_status/novelty_check)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import UUID

import pandas as pd
import pytest

from backend.platform.factor.interface import FactorSpec, FactorStatus
from backend.platform.factor.registry import (
    DBFactorRegistry,
    DuplicateFactor,
    FactorNotFound,
    OnboardingBlocked,
    StubLifecycleMonitor,
    WriteNotConfigured,
    _default_ast_jaccard,
)

# ================================================================
# Fixtures
# ================================================================


@pytest.fixture
def mock_dal() -> MagicMock:
    """DAL mock, read_registry 返 3 因子 DataFrame (get_direction 用)."""
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        {
            "name": ["turnover_mean_20", "bp_ratio", "reversal_20"],
            "direction": [-1, 1, 1],
        }
    )
    return dal


@pytest.fixture
def empty_dal() -> MagicMock:
    """DAL mock, read_registry 默认返空 DataFrame."""
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        columns=["id", "name", "direction", "expression", "hypothesis", "status", "pool", "category", "source"]
    )
    return dal


def _make_conn_factory(insert_id: UUID | None = None) -> tuple[MagicMock, MagicMock, MagicMock]:
    """构造 mock conn_factory + conn + cursor (INSERT 路径测试用)."""
    cursor = MagicMock()
    if insert_id is not None:
        cursor.fetchone.return_value = (insert_id,)
    cursor.rowcount = 1
    ctx = MagicMock()
    ctx.__enter__.return_value = cursor
    ctx.__exit__.return_value = False
    conn = MagicMock()
    conn.cursor.return_value = ctx
    factory = MagicMock(return_value=conn)
    return factory, conn, cursor


VALID_HYPOTHESIS = (
    "高换手率的股票短期有流动性冲击预期, 截面上低换手率因子能捕捉到"
    "未来 20 日的反向收益 — 流动性溢价."
)


def _valid_spec(name: str = "new_alpha_xyz", expression: str = "rank(close / open)") -> FactorSpec:
    return FactorSpec(
        name=name,
        hypothesis=VALID_HYPOTHESIS,
        expression=expression,
        direction=1,
        category="alpha",
        pool="CANDIDATE",
        author="test",
    )


# ================================================================
# MVP 1.3b: get_direction 基本功能
# ================================================================


def test_get_direction_reads_from_dal(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    assert r.get_direction("turnover_mean_20") == -1
    assert r.get_direction("bp_ratio") == 1
    assert r.get_direction("reversal_20") == 1
    assert mock_dal.read_registry.call_count == 1


def test_get_direction_fallback_for_unknown(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    assert r.get_direction("nonexistent_factor") == 1


def test_get_direction_first_call_loads_cache(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    assert r.cache_size() == 0
    r.get_direction("turnover_mean_20")
    assert r.cache_size() == 3


# ================================================================
# MVP 1.3b: Cache TTL 行为
# ================================================================


def test_cache_hit_no_dal_call(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    r.get_direction("turnover_mean_20")
    r.get_direction("bp_ratio")
    r.get_direction("reversal_20")
    assert mock_dal.read_registry.call_count == 1


def test_cache_refresh_after_ttl(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal, cache_ttl_minutes=60)
    r.get_direction("turnover_mean_20")
    r._last_refresh = datetime.now(UTC) - timedelta(minutes=61)
    r.get_direction("bp_ratio")
    assert mock_dal.read_registry.call_count == 2


def test_cache_no_refresh_within_ttl(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal, cache_ttl_minutes=60)
    r.get_direction("turnover_mean_20")
    r._last_refresh = datetime.now(UTC) - timedelta(minutes=55)
    r.get_direction("bp_ratio")
    assert mock_dal.read_registry.call_count == 1


def test_invalidate_forces_refresh(mock_dal) -> None:
    r = DBFactorRegistry(dal=mock_dal)
    r.get_direction("turnover_mean_20")
    assert r.cache_size() == 3
    r.invalidate()
    assert r.cache_size() == 0
    r.get_direction("turnover_mean_20")
    assert mock_dal.read_registry.call_count == 2


def test_custom_ttl_minutes() -> None:
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame({"name": ["x"], "direction": [1]})
    r = DBFactorRegistry(dal=dal, cache_ttl_minutes=5)
    r.get_direction("x")
    r._last_refresh = datetime.now(UTC) - timedelta(minutes=6)
    r.get_direction("x")
    assert dal.read_registry.call_count == 2


# ================================================================
# MVP 1.3b: DAL 异常传播 (铁律 33)
# ================================================================


def test_dal_exception_propagates() -> None:
    dal = MagicMock()
    dal.read_registry.side_effect = RuntimeError("DB down")
    r = DBFactorRegistry(dal=dal)
    with pytest.raises(RuntimeError, match="DB down"):
        r.get_direction("x")


def test_dal_exception_on_refresh_doesnt_corrupt_cache() -> None:
    dal = MagicMock()
    dal.read_registry.side_effect = [
        pd.DataFrame({"name": ["x"], "direction": [-1]}),
        RuntimeError("DB transient"),
    ]
    r = DBFactorRegistry(dal=dal, cache_ttl_minutes=60)
    r.get_direction("x")
    assert r._cache == {"x": -1}
    r._last_refresh = datetime.now(UTC) - timedelta(minutes=61)
    with pytest.raises(RuntimeError, match="transient"):
        r.get_direction("x")
    assert r._cache == {"x": -1}


# ================================================================
# MVP 1.3b: direction 修复 reversal_20
# ================================================================


def test_direction_fix_reversal_20() -> None:
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        {"name": ["reversal_20"], "direction": [1]}
    )
    r = DBFactorRegistry(dal=dal)
    assert r.get_direction("reversal_20") == 1


# ================================================================
# MVP 1.3c: get_active concrete
# ================================================================


def test_get_active_empty_returns_empty_list(empty_dal) -> None:
    r = DBFactorRegistry(dal=empty_dal)
    assert r.get_active() == []
    empty_dal.read_registry.assert_called_with(status_filter="active")


def test_get_active_returns_factor_meta_list() -> None:
    uid = UUID("12345678-1234-5678-1234-567812345678")
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        [
            {
                "id": uid,
                "name": "bp_ratio",
                "category": "value",
                "direction": 1,
                "expression": "book / price",
                "code_content": None,
                "hypothesis": "价值回归",
                "source": "manual",
                "lookback_days": 60,
                "status": "active",
                "pool": "CORE",
                "gate_ic": 0.107,
                "gate_ir": 0.5,
                "gate_mono": 0.9,
                "gate_t": 3.2,
                "ic_decay_ratio": 0.85,
                "created_at": "2024-01-01",
                "updated_at": "2024-01-02",
            }
        ]
    )
    r = DBFactorRegistry(dal=dal)
    metas = r.get_active()
    assert len(metas) == 1
    m = metas[0]
    assert m.name == "bp_ratio"
    assert m.factor_id == uid
    assert m.direction == 1
    assert m.status == FactorStatus.ACTIVE
    assert m.pool == "CORE"
    assert m.gate_ic == pytest.approx(0.107)


def test_get_active_handles_null_optional_fields() -> None:
    """NULL 字段 (gate_ic / lookback_days / hypothesis) 保 None."""
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        [
            {
                "id": None, "name": "x", "category": None, "direction": -1,
                "expression": None, "code_content": None, "hypothesis": None,
                "source": None, "lookback_days": None, "status": "active", "pool": None,
                "gate_ic": None, "gate_ir": None, "gate_mono": None, "gate_t": None,
                "ic_decay_ratio": None, "created_at": None, "updated_at": None,
            }
        ]
    )
    r = DBFactorRegistry(dal=dal)
    m = r.get_active()[0]
    assert m.gate_ic is None
    assert m.hypothesis is None
    assert m.pool == "LEGACY"  # 容错默认


def test_get_active_invalid_status_falls_back_to_active() -> None:
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        [
            {
                "id": UUID("11111111-1111-1111-1111-111111111111"),
                "name": "x", "category": "alpha", "direction": 1,
                "expression": None, "code_content": None, "hypothesis": None,
                "source": "manual", "lookback_days": None, "status": "unknown_status",
                "pool": "CORE", "gate_ic": None, "gate_ir": None, "gate_mono": None,
                "gate_t": None, "ic_decay_ratio": None, "created_at": None, "updated_at": None,
            }
        ]
    )
    r = DBFactorRegistry(dal=dal)
    m = r.get_active()[0]
    assert m.status == FactorStatus.ACTIVE  # 容错


# ================================================================
# MVP 1.3c: novelty_check (G9 AST Jaccard)
# ================================================================


def test_novelty_check_empty_expression_passes(empty_dal) -> None:
    """无 expression 的 builtin 因子不走 AST, 依赖 G10 兜底."""
    r = DBFactorRegistry(dal=empty_dal)
    spec = _valid_spec(expression="")
    assert r.novelty_check(spec) is True


def test_novelty_check_passes_low_similarity() -> None:
    """dissimilar exprs → Jaccard < 0.7 → novelty pass."""
    uid = UUID("11111111-1111-1111-1111-111111111111")
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        [
            {
                "id": uid, "name": "existing", "category": "alpha", "direction": 1,
                "expression": "close / open", "code_content": None,
                "hypothesis": None, "source": "manual", "lookback_days": None,
                "status": "active", "pool": "CORE", "gate_ic": None, "gate_ir": None,
                "gate_mono": None, "gate_t": None, "ic_decay_ratio": None,
                "created_at": None, "updated_at": None,
            }
        ]
    )
    r = DBFactorRegistry(dal=dal)
    spec = _valid_spec(expression="rank(turnover / volatility) + bp_ratio * dv_ttm")
    assert r.novelty_check(spec) is True


def test_novelty_check_rejects_high_similarity() -> None:
    """Near-identical AST → Jaccard > 0.7 → novelty fail."""
    uid = UUID("11111111-1111-1111-1111-111111111111")
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        [
            {
                "id": uid, "name": "existing_factor", "category": "alpha", "direction": 1,
                "expression": "rank(close / open)", "code_content": None,
                "hypothesis": None, "source": "manual", "lookback_days": None,
                "status": "active", "pool": "CORE", "gate_ic": None, "gate_ir": None,
                "gate_mono": None, "gate_t": None, "ic_decay_ratio": None,
                "created_at": None, "updated_at": None,
            }
        ]
    )
    r = DBFactorRegistry(dal=dal)
    spec = _valid_spec(expression="rank(close / open)")  # 完全相同
    assert r.novelty_check(spec) is False


def test_novelty_check_custom_ast_similarity_fn() -> None:
    """ast_similarity_fn 依赖注入: 允许替换默认 Jaccard."""
    uid = UUID("11111111-1111-1111-1111-111111111111")
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        [
            {
                "id": uid, "name": "existing", "category": "alpha", "direction": 1,
                "expression": "a + b", "code_content": None, "hypothesis": None,
                "source": "manual", "lookback_days": None, "status": "active",
                "pool": "CORE", "gate_ic": None, "gate_ir": None, "gate_mono": None,
                "gate_t": None, "ic_decay_ratio": None,
                "created_at": None, "updated_at": None,
            }
        ]
    )
    calls: list[tuple[str, str]] = []

    def always_high(e1: str, e2: str) -> float:
        calls.append((e1, e2))
        return 0.99

    r = DBFactorRegistry(dal=dal, ast_similarity_fn=always_high)
    spec = _valid_spec(expression="x * y")
    assert r.novelty_check(spec) is False
    assert len(calls) == 1


# ================================================================
# MVP 1.3c: register (G9 + G10 + INSERT)
# ================================================================


def test_register_success_inserts_and_returns_uuid(empty_dal) -> None:
    uid = UUID("12345678-1234-5678-1234-567812345678")
    factory, conn, cursor = _make_conn_factory(insert_id=uid)
    r = DBFactorRegistry(dal=empty_dal, conn_factory=factory)
    result_id = r.register(_valid_spec())
    assert result_id == uid
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_register_invalidates_cache_after_insert(empty_dal) -> None:
    uid = UUID("12345678-1234-5678-1234-567812345678")
    factory, _, _ = _make_conn_factory(insert_id=uid)
    r = DBFactorRegistry(dal=empty_dal, conn_factory=factory)
    r._cache = {"old_factor": -1}
    r._last_refresh = datetime.now(UTC)
    r.register(_valid_spec())
    assert r.cache_size() == 0
    assert r._last_refresh is None


def test_register_g10_blocks_empty_hypothesis(empty_dal) -> None:
    factory, _, _ = _make_conn_factory(insert_id=UUID(int=1))
    r = DBFactorRegistry(dal=empty_dal, conn_factory=factory)
    spec = FactorSpec(
        name="x", hypothesis="", expression="a", direction=1,
        category="alpha", pool="CANDIDATE", author="test",
    )
    with pytest.raises(OnboardingBlocked, match="G10"):
        r.register(spec)


def test_register_g10_blocks_short_hypothesis(empty_dal) -> None:
    factory, _, _ = _make_conn_factory(insert_id=UUID(int=1))
    r = DBFactorRegistry(dal=empty_dal, conn_factory=factory)
    spec = FactorSpec(
        name="x", hypothesis="short", expression="a", direction=1,
        category="alpha", pool="CANDIDATE", author="test",
    )
    with pytest.raises(OnboardingBlocked, match="G10"):
        r.register(spec)


@pytest.mark.parametrize(
    "forbidden_prefix",
    ["GP自动挖掘: some expr", "GP auto-generated", "TODO: fill hypothesis", "待填写 hypothesis"],
)
def test_register_g10_blocks_forbidden_prefixes(empty_dal, forbidden_prefix) -> None:
    factory, _, _ = _make_conn_factory(insert_id=UUID(int=1))
    r = DBFactorRegistry(dal=empty_dal, conn_factory=factory)
    spec = FactorSpec(
        name="x",
        hypothesis=forbidden_prefix + " padding to be long enough for length check",
        expression="a", direction=1, category="alpha", pool="CANDIDATE", author="test",
    )
    with pytest.raises(OnboardingBlocked, match="G10"):
        r.register(spec)


def test_register_g9_blocks_high_ast_similarity() -> None:
    uid = UUID("11111111-1111-1111-1111-111111111111")
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        [
            {
                "id": uid, "name": "existing", "category": "alpha", "direction": 1,
                "expression": "rank(close / open)", "code_content": None,
                "hypothesis": None, "source": "manual", "lookback_days": None,
                "status": "active", "pool": "CORE", "gate_ic": None, "gate_ir": None,
                "gate_mono": None, "gate_t": None, "ic_decay_ratio": None,
                "created_at": None, "updated_at": None,
            }
        ]
    )
    factory, _, _ = _make_conn_factory(insert_id=UUID(int=2))
    r = DBFactorRegistry(dal=dal, conn_factory=factory)
    spec = _valid_spec(name="near_duplicate", expression="rank(close / open)")
    with pytest.raises(OnboardingBlocked, match="G9"):
        r.register(spec)


def test_register_duplicate_factor() -> None:
    uid = UUID("11111111-1111-1111-1111-111111111111")
    dal = MagicMock()
    dal.read_registry.return_value = pd.DataFrame(
        [
            {
                "id": uid, "name": "existing_name", "category": "alpha", "direction": 1,
                "expression": "foo()", "code_content": None, "hypothesis": None,
                "source": "manual", "lookback_days": None, "status": "active",
                "pool": "CORE", "gate_ic": None, "gate_ir": None, "gate_mono": None,
                "gate_t": None, "ic_decay_ratio": None,
                "created_at": None, "updated_at": None,
            }
        ]
    )
    factory, _, _ = _make_conn_factory(insert_id=UUID(int=2))
    r = DBFactorRegistry(dal=dal, conn_factory=factory)
    spec = _valid_spec(name="existing_name", expression="completely_different_expr()")
    with pytest.raises(DuplicateFactor, match="existing_name"):
        r.register(spec)


def test_register_write_not_configured(empty_dal) -> None:
    r = DBFactorRegistry(dal=empty_dal, conn_factory=None)
    with pytest.raises(WriteNotConfigured, match="conn_factory"):
        r.register(_valid_spec())


# ================================================================
# MVP 1.3c: update_status
# ================================================================


def test_update_status_success(empty_dal) -> None:
    factory, conn, cursor = _make_conn_factory()
    cursor.rowcount = 1
    r = DBFactorRegistry(dal=empty_dal, conn_factory=factory)
    r._cache = {"f1": 1}
    r._last_refresh = datetime.now(UTC)
    r.update_status("f1", FactorStatus.DEPRECATED, "IC decay > 3 months")
    cursor.execute.assert_called_once()
    conn.commit.assert_called_once()
    assert r.cache_size() == 0  # invalidated


def test_update_status_factor_not_found(empty_dal) -> None:
    factory, _, cursor = _make_conn_factory()
    cursor.rowcount = 0  # UPDATE 命中 0 行
    r = DBFactorRegistry(dal=empty_dal, conn_factory=factory)
    with pytest.raises(FactorNotFound, match="not_exist"):
        r.update_status("not_exist", FactorStatus.DEPRECATED, "reason")


def test_update_status_write_not_configured(empty_dal) -> None:
    r = DBFactorRegistry(dal=empty_dal, conn_factory=None)
    with pytest.raises(WriteNotConfigured):
        r.update_status("x", FactorStatus.ACTIVE, "reason")


def test_update_status_accepts_string_status(empty_dal) -> None:
    """容错: 允许 new_status 传字符串 (兼容老代码调用)."""
    factory, _, cursor = _make_conn_factory()
    cursor.rowcount = 1
    r = DBFactorRegistry(dal=empty_dal, conn_factory=factory)
    r.update_status("f1", "active", "reason")  # type: ignore[arg-type]
    cursor.execute.assert_called_once()


# ================================================================
# _default_ast_jaccard 纯函数
# ================================================================


def test_default_ast_jaccard_self_similarity() -> None:
    assert _default_ast_jaccard("a + b", "a + b") == 1.0


def test_default_ast_jaccard_syntax_error_returns_zero() -> None:
    assert _default_ast_jaccard("invalid (((", "a + b") == 0.0
    assert _default_ast_jaccard("a + b", "invalid (((") == 0.0


def test_default_ast_jaccard_unrelated_expressions_below_half() -> None:
    sim = _default_ast_jaccard("rank(close / open)", "bp_ratio + dv_ttm * 0.5")
    assert 0.0 <= sim < 0.5


def test_default_ast_jaccard_similar_but_not_identical() -> None:
    """相同结构, 不同变量名 — 中高相似度."""
    sim = _default_ast_jaccard("a + b * c", "x + y * z")
    # 相同运算符节点, 不同 Name → Jaccard 约 0.5-0.7
    assert sim > 0.0


# ================================================================
# StubLifecycleMonitor (MVP 1.3b 占位)
# ================================================================


def test_stub_lifecycle_raises() -> None:
    monitor = StubLifecycleMonitor()
    with pytest.raises(NotImplementedError, match="PlatformLifecycleMonitor"):
        monitor.evaluate_all()
