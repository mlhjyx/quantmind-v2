"""Unit tests for ``scripts.repair.restore_snapshot_20260417`` — D2-c Session 15.

Session 10 P1-b: 4-17 `position_snapshot` live 行蒸发 (save_qmt_state 在 D2-a 合并前
覆盖了 reconciliation 写的 19 行). D2-a PR #25 已根除未来复现, 但 4-17 数据需手工补.
本测试覆盖一次性修复脚本的 precondition + reconstruction + atomic apply 语义.

测试矩阵 (8 项):
  1. precondition fail: target 已有行 → RAISE (防重复 apply)
  2. precondition fail: baseline 0 行 → RAISE (无 ground truth)
  3. precondition fail: fills 0 行 → RAISE (无 transition)
  4. reconstruction: qty/avg_cost 重算 (4-16 3 codes + 4-17 1 buy + 1 sell)
  5. apply 全流程: 验 market_value = qty × close + avg_cost 加权均值
  6. dry-run 不写: run 后 DB 无新行
  7. 幂等守卫: 第 2 次 apply → RAISE (target 已有行)
  8. 源码契约: inspect 含 "D2-c" / "Session 15" docstring 标记

本测试用 isolated UUID strategy_id + 远未来日期 (2099-xx-xx) 避开真 4-17 数据,
不碰生产 snapshot.
"""

from __future__ import annotations

import contextlib
import importlib.util
import inspect
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import psycopg2
import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_REPO))

# .env 加载 DATABASE_URL (standalone pattern, 对齐 test_pt_qmt_state.py)
_ENV = _BACKEND / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

_PG_URL = os.environ.get("DATABASE_URL")
if _PG_URL and _PG_URL.startswith("postgresql+asyncpg://"):
    _PG_URL = "postgresql://" + _PG_URL[len("postgresql+asyncpg://") :]


# scripts/repair 非 package, dynamic import (对齐 test_load_universe.py 模式)
def _load_module():
    """Dynamic import `restore_snapshot_20260417` from scripts/repair/."""
    spec_path = _REPO / "scripts" / "repair" / "restore_snapshot_20260417.py"
    module_name = "restore_snapshot_20260417_test_shim"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, spec_path)
    assert spec is not None and spec.loader is not None, f"Cannot load {spec_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def sync_conn():
    """psycopg2 同步连接, autocommit=False (脚本自管 tx, 对齐生产行为).

    铁律 35: .env 未配置 → skip (不允许硬编码 fallback).
    """
    if not _PG_URL:
        pytest.skip("DATABASE_URL not set (backend/.env 未配置) — skipping integration tests")
    conn = psycopg2.connect(_PG_URL)
    conn.autocommit = False
    try:
        yield conn
    finally:
        conn.rollback()  # 清尾巴 tx
        conn.close()


@pytest.fixture
def isolated_strategy(sync_conn):
    """独立 UUID strategy_id + 远未来 repair/ref 日期, teardown DELETE 相关行."""
    sid = str(uuid.uuid4())
    repair_date = date(2099, 4, 17)
    ref_date = date(2099, 4, 16)
    cur = sync_conn.cursor()
    cur.execute(
        "INSERT INTO strategy (id, name, market, mode, active_version, status) "
        "VALUES (%s, %s, 'astock', 'visual', 1, 'draft')",
        (sid, f"test_d2c_{sid[:8]}"),
    )
    sync_conn.commit()
    try:
        yield sid, repair_date, ref_date
    finally:
        for tbl in ("trade_log", "position_snapshot", "performance_series"):
            with contextlib.suppress(Exception):
                cur.execute(f"DELETE FROM {tbl} WHERE strategy_id = %s", (sid,))  # noqa: S608
        # 清除测试用 klines_daily (用 T 前缀 codes)
        with contextlib.suppress(Exception):
            cur.execute(
                "DELETE FROM klines_daily WHERE trade_date BETWEEN %s AND %s AND code LIKE 'T%%'",
                (ref_date - timedelta(days=1), repair_date + timedelta(days=1)),
            )
        with contextlib.suppress(Exception):
            cur.execute("DELETE FROM strategy WHERE id = %s", (sid,))
        sync_conn.commit()


def _seed_snapshot(conn, sid, td, code, qty, avg_cost=10.0):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO position_snapshot
           (code, trade_date, strategy_id, market, quantity, avg_cost, market_value,
            weight, execution_mode)
           VALUES (%s, %s, %s, 'astock', %s, %s, %s, 0.01, 'live')""",
        (code, td, sid, qty, avg_cost, qty * avg_cost),
    )
    conn.commit()


def _seed_fill(conn, sid, td, code, direction, qty, price):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO trade_log
           (code, trade_date, strategy_id, market, direction, quantity, fill_price,
            commission, stamp_tax, swap_cost, total_cost, execution_mode)
           VALUES (%s, %s, %s, 'astock', %s, %s, %s, 5.0, 0.0, 0.0, 5.0, 'live')""",
        (code, td, sid, direction, qty, price),
    )
    conn.commit()


def _seed_kline(conn, td, code, close):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO klines_daily (code, trade_date, open, high, low, close,
                                     pre_close, volume, amount, adj_factor)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 1000, 10000, 1.0)
           ON CONFLICT DO NOTHING""",
        (code, td, close, close, close, close, close),
    )
    conn.commit()


class _ConnNoCloseProxy:
    """Proxy forwarding all attrs to real psycopg2 conn but no-op close().

    psycopg2 connection.close is read-only, can't monkey-patch. We need to
    share a single conn between fixture (for seeds + teardown) and
    ``mod.run()`` (which calls conn.close()) — proxy allows sharing.
    """

    def __init__(self, conn):
        object.__setattr__(self, "_conn", conn)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    def close(self):
        pass  # silent_ok: 测试复用 fixture conn, teardown 负责真 close


# ─── Tests ───────────────────────────────────────────────────────


def test_precondition_fail_when_target_already_populated(sync_conn, isolated_strategy):
    """target date 已有 live 行 → PreconditionError (防重复 apply)."""
    sid, repair_date, ref_date = isolated_strategy
    # 种 target date (4-17) 已有 1 行
    _seed_snapshot(sync_conn, sid, repair_date, "T0001.SH", 100)
    # 种 baseline (满足 #2 以隔离验 #1 触发)
    _seed_snapshot(sync_conn, sid, ref_date, "T0002.SH", 200)
    _seed_fill(sync_conn, sid, repair_date, "T0002.SH", "buy", 100, 10.0)

    cur = sync_conn.cursor()
    with pytest.raises(mod.PreconditionError, match="target .* 已有"):
        mod.assert_preconditions(cur, sid, repair_date, ref_date)


def test_precondition_fail_when_no_baseline(sync_conn, isolated_strategy):
    """baseline date 无 live 行 → PreconditionError (无 ground truth)."""
    sid, repair_date, ref_date = isolated_strategy
    # 不种 baseline, 种 fill 以隔离 #2 触发
    _seed_fill(sync_conn, sid, repair_date, "T0002.SH", "buy", 100, 10.0)

    cur = sync_conn.cursor()
    with pytest.raises(mod.PreconditionError, match="baseline .* 0 行"):
        mod.assert_preconditions(cur, sid, repair_date, ref_date)


def test_precondition_fail_when_no_fills(sync_conn, isolated_strategy):
    """target date 无 live trade_log → PreconditionError (无 transition)."""
    sid, repair_date, ref_date = isolated_strategy
    _seed_snapshot(sync_conn, sid, ref_date, "T0001.SH", 100)
    # 不种 fill

    cur = sync_conn.cursor()
    with pytest.raises(mod.PreconditionError, match="trade_log 0 行"):
        mod.assert_preconditions(cur, sid, repair_date, ref_date)


def test_reconstruction_quantity_math(sync_conn, isolated_strategy):
    """4-16 snapshot 3 codes + 4-17 2 fills → 验 qty/avg_cost 重算.

    场景:
      baseline: A=100@10.0 / B=200@20.0 / C=50@5.0
      fills:    buy A 50 @ 12.0  (加仓 → qty=150, avg=(100*10+50*12)/150=10.667)
                sell B 200 @ 25.0 (全平 → 丢弃)
      expected: A=150 avg=10.667 / C=50@5.0
    """
    sid, repair_date, ref_date = isolated_strategy
    _seed_snapshot(sync_conn, sid, ref_date, "T000A.SH", 100, 10.0)
    _seed_snapshot(sync_conn, sid, ref_date, "T000B.SH", 200, 20.0)
    _seed_snapshot(sync_conn, sid, ref_date, "T000C.SH", 50, 5.0)
    _seed_fill(sync_conn, sid, repair_date, "T000A.SH", "buy", 50, 12.0)
    _seed_fill(sync_conn, sid, repair_date, "T000B.SH", "sell", 200, 25.0)

    cur = sync_conn.cursor()
    positions = mod.reconstruct_positions(cur, sid, repair_date, ref_date)

    assert set(positions.keys()) == {"T000A.SH", "T000C.SH"}, "B 应全平被丢弃"
    assert positions["T000A.SH"]["qty"] == 150
    assert abs(positions["T000A.SH"]["avg_cost"] - (100 * 10 + 50 * 12) / 150) < 1e-6
    assert positions["T000C.SH"]["qty"] == 50
    assert positions["T000C.SH"]["avg_cost"] == pytest.approx(5.0)


def test_apply_inserts_rows_with_correct_mv(sync_conn, isolated_strategy, monkeypatch):
    """全流程 apply → 验 target 行数 + market_value 公式 + weight 归一."""
    sid, repair_date, ref_date = isolated_strategy
    _seed_snapshot(sync_conn, sid, ref_date, "T000A.SH", 100, 10.0)
    _seed_snapshot(sync_conn, sid, ref_date, "T000B.SH", 200, 20.0)
    _seed_fill(sync_conn, sid, repair_date, "T000A.SH", "buy", 50, 12.0)
    _seed_fill(sync_conn, sid, repair_date, "T000B.SH", "sell", 50, 25.0)  # partial
    _seed_kline(sync_conn, repair_date, "T000A.SH", 15.0)
    _seed_kline(sync_conn, repair_date, "T000B.SH", 22.0)

    # monkeypatch get_sync_conn 返复用 fixture 连接 (本测试 tx 已 commit seeds)
    monkeypatch.setattr(mod, "get_sync_conn", lambda: _ConnNoCloseProxy(sync_conn))
    # monkeypatch REPAIR_DATE / REF_DATE 为 fixture 远未来日
    monkeypatch.setattr(mod, "REPAIR_DATE", repair_date)
    monkeypatch.setattr(mod, "REF_DATE", ref_date)

    rc = mod.run(strategy_id=sid, apply=True)
    assert rc == 0

    cur = sync_conn.cursor()
    cur.execute(
        "SELECT code, quantity, market_value, avg_cost, weight FROM position_snapshot "
        "WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'live' ORDER BY code",
        (repair_date, sid),
    )
    rows = cur.fetchall()
    assert len(rows) == 2
    code_map = {r[0]: r for r in rows}

    # A: qty=150, mv=150*15=2250
    assert code_map["T000A.SH"][1] == 150
    assert float(code_map["T000A.SH"][2]) == pytest.approx(150 * 15.0)
    # B: qty=150 (partial), mv=150*22=3300
    assert code_map["T000B.SH"][1] == 150
    assert float(code_map["T000B.SH"][2]) == pytest.approx(150 * 22.0)
    # weight 归一 (允 1e-4 四舍五入误差)
    total = sum(float(r[4]) for r in rows)
    assert abs(total - 1.0) < 1e-3


def test_dry_run_does_not_write(sync_conn, isolated_strategy, monkeypatch):
    """`--dry-run` (apply=False) 后 target date 仍无行."""
    sid, repair_date, ref_date = isolated_strategy
    _seed_snapshot(sync_conn, sid, ref_date, "T000A.SH", 100, 10.0)
    _seed_fill(sync_conn, sid, repair_date, "T000A.SH", "buy", 50, 12.0)
    _seed_kline(sync_conn, repair_date, "T000A.SH", 15.0)

    monkeypatch.setattr(mod, "get_sync_conn", lambda: _ConnNoCloseProxy(sync_conn))
    monkeypatch.setattr(mod, "REPAIR_DATE", repair_date)
    monkeypatch.setattr(mod, "REF_DATE", ref_date)

    rc = mod.run(strategy_id=sid, apply=False)
    assert rc == 0

    cur = sync_conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM position_snapshot WHERE trade_date = %s AND strategy_id = %s",
        (repair_date, sid),
    )
    assert cur.fetchone()[0] == 0, "dry-run 不应写任何行"


def test_apply_is_idempotent_via_precondition_guard(
    sync_conn, isolated_strategy, monkeypatch
):
    """第 2 次 apply → precondition (target count=0) fail → exit 1 (幂等守卫)."""
    sid, repair_date, ref_date = isolated_strategy
    _seed_snapshot(sync_conn, sid, ref_date, "T000A.SH", 100, 10.0)
    _seed_fill(sync_conn, sid, repair_date, "T000A.SH", "buy", 50, 12.0)
    _seed_kline(sync_conn, repair_date, "T000A.SH", 15.0)

    monkeypatch.setattr(mod, "get_sync_conn", lambda: _ConnNoCloseProxy(sync_conn))
    monkeypatch.setattr(mod, "REPAIR_DATE", repair_date)
    monkeypatch.setattr(mod, "REF_DATE", ref_date)

    rc1 = mod.run(strategy_id=sid, apply=True)
    assert rc1 == 0

    rc2 = mod.run(strategy_id=sid, apply=True)
    assert rc2 == 1, "第 2 次 apply 应 precondition fail (target 已有行)"


def test_source_has_session_15_marker():
    """源码 inspect: 确保 D2-c / Session 15 标记保留 (防未来误删)."""
    src = inspect.getsource(mod)
    assert "D2-c" in src, "源码 docstring 必须含 'D2-c' 定位 Session 15 修复"
    assert "Session 15" in src, "源码必须含 'Session 15' 时序标记"
    assert "PreconditionError" in src, "fail-loud 异常类必须保留"
    assert "REPAIR_DATE = date(2026, 4, 17)" in src, "修复日期硬编码 (铁律 36 不可动态)"
