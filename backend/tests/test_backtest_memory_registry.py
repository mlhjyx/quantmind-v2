"""MVP 2.3 Sub1 PR C2 · InMemoryBacktestRegistry 单测.

覆盖:
  - log_run no-op: 记内存 list, 返 None (对齐 abstract)
  - log_run 累积: 多次调 → list 增长
  - get_by_hash 恒 None (强制 cache miss)
  - list_recent: 返最后 N 条
  - max_history trim: 防 long-lived 进程 OOM
  - clear() 清空内存

铁律: 17 (DataPipeline — InMem 显式选择不入库) / 40 (InMem 测试债务隔离).
"""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from backend.platform._types import BacktestMode
from backend.platform.backtest.interface import BacktestConfig, BacktestResult
from backend.platform.backtest.memory_registry import InMemoryBacktestRegistry

# ─── Fixtures ──────────────────────────────────────────────


def _make_config() -> BacktestConfig:
    return BacktestConfig(
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
        universe="csi300",
        factor_pool=("bp_ratio",),
        rebalance_freq="monthly",
        top_n=20,
        industry_cap=1.0,
        size_neutral_beta=0.50,
        cost_model="full",
        capital="1000000.0",
        benchmark="csi300",
        extra={},
    )


def _make_result(hash_suffix: str = "a") -> BacktestResult:
    return BacktestResult(
        run_id=uuid4(),
        config_hash=f"hash_{hash_suffix}",
        git_commit="abc123",
        sharpe=1.0,
        annual_return=0.1,
        max_drawdown=-0.05,
        total_return=0.5,
        trades_count=10,
        metrics={},
    )


# ─── log_run (3 tests) ─────────────────────────────────────


def test_log_run_returns_none():
    """InMem log_run 永 return None (无 DB/lineage)."""
    reg = InMemoryBacktestRegistry()
    out = reg.log_run(_make_config(), _make_result(), artifact_paths={})
    assert out is None


def test_log_run_accumulates_into_internal_list():
    """多次 log_run → 内存 list 线性增长 (测试断言 __len__)."""
    reg = InMemoryBacktestRegistry()
    assert len(reg) == 0
    reg.log_run(_make_config(), _make_result("a"), artifact_paths={})
    reg.log_run(_make_config(), _make_result("b"), artifact_paths={})
    reg.log_run(_make_config(), _make_result("c"), artifact_paths={})
    assert len(reg) == 3


def test_log_run_accepts_extended_kwargs_without_raising():
    """DBBacktestRegistry.log_run 扩签名 (mode/elapsed_sec/lineage/perf/dates) InMem 必兼容 — 调用方 Runner 按扩签名调."""
    reg = InMemoryBacktestRegistry()
    out = reg.log_run(
        _make_config(),
        _make_result(),
        artifact_paths={},
        mode=BacktestMode.QUICK_1Y,
        elapsed_sec=42,
        lineage=None,
        perf=None,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 12, 31),
    )
    assert out is None
    assert len(reg) == 1


# ─── get_by_hash (1 test) ─────────────────────────────────


def test_get_by_hash_always_returns_none():
    """核心契约: InMem get_by_hash 恒 None → 强制 Runner cache miss 每次真跑 (ad-hoc 场景)."""
    reg = InMemoryBacktestRegistry()
    r = _make_result()
    reg.log_run(_make_config(), r, artifact_paths={})
    # 即使 log_run 过了, get_by_hash 仍返 None (不做 hash → result 映射)
    assert reg.get_by_hash(r.config_hash) is None
    assert reg.get_by_hash("any_hash") is None


# ─── list_recent (2 tests) ────────────────────────────────


def test_list_recent_returns_last_n_in_insertion_order():
    """list_recent(N) → 最后 N 条, 最新在尾 (insertion order)."""
    reg = InMemoryBacktestRegistry()
    results = [_make_result(f"r{i}") for i in range(5)]
    for r in results:
        reg.log_run(_make_config(), r, artifact_paths={})

    recent = reg.list_recent(limit=3)
    assert len(recent) == 3
    assert [r.config_hash for r in recent] == ["hash_r2", "hash_r3", "hash_r4"]


def test_list_recent_limit_zero_returns_empty():
    """list_recent(0) → 空 list (不 raise)."""
    reg = InMemoryBacktestRegistry()
    reg.log_run(_make_config(), _make_result(), artifact_paths={})
    assert reg.list_recent(limit=0) == []
    assert reg.list_recent(limit=-1) == []


# ─── max_history trim + clear (2 tests) ─────────────────


def test_max_history_trims_oldest_entries():
    """max_history=3 → 第 4 条进来后, 第 1 条被 trim (保最新 3 条)."""
    reg = InMemoryBacktestRegistry(max_history=3)
    for i in range(5):
        reg.log_run(_make_config(), _make_result(f"r{i}"), artifact_paths={})

    assert len(reg) == 3
    recent = reg.list_recent(limit=10)
    # 仅保留 r2/r3/r4 (最旧 r0/r1 被 trim)
    assert [r.config_hash for r in recent] == ["hash_r2", "hash_r3", "hash_r4"]


def test_max_history_none_disables_trim():
    """max_history=None → 无上限, 全量保留 (测试场景)."""
    reg = InMemoryBacktestRegistry(max_history=None)
    for i in range(50):
        reg.log_run(_make_config(), _make_result(f"r{i}"), artifact_paths={})
    assert len(reg) == 50


def test_clear_empties_internal_list():
    """clear() 清空 list, len=0."""
    reg = InMemoryBacktestRegistry()
    reg.log_run(_make_config(), _make_result(), artifact_paths={})
    reg.log_run(_make_config(), _make_result(), artifact_paths={})
    assert len(reg) == 2
    reg.clear()
    assert len(reg) == 0
    assert reg.list_recent() == []
