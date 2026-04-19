"""Unit tests for pt_qmt_state.py D2-a L1 fail-loud (QMT 持仓蒸发检测).

Session 10 (2026-04-19) P1-b: QMTClient 读 0 持仓时 ``save_qmt_state`` 无校验
DELETE + INSERT 0 行覆盖真实 snapshot → DB state 滞后 QMT 真实 19 持仓 ¥1.008M,
4-17 snapshot 缺失至今. 本 session 13 补 L1 guard (铁律 33):
"前一交易日 live snapshot ≥1 持仓 + 今日 QMT 返 0 → RAISE QMTEmptyPositionsError".

测试矩阵 (铁律 40 不增 fail 基线):
  1. fail-loud trigger (prev 5 pos + today {} → raise)
  2. fresh start bypass (prev 无 row + today {} → 无 raise)
  3. prev all 0 qty bypass (prev row 但 qty=0 + today {} → 无 raise)
  4. today non-empty bypass (prev 5 + today 3 → 无 raise 正常写入)
  5. 跨周末 (prev=周五 + today=周一 → 无 raise)
  6. 源码契约 (inspect 含 FAIL-LOUD + raise QMTEmptyPositionsError)
  7. 错误消息 runbook hint (str(exc) 含 Servy/redis/xtquant)
"""

from __future__ import annotations

import contextlib
import inspect
import os
import sys
import uuid
from datetime import date
from pathlib import Path

import psycopg2
import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_REPO))

# backend/.env 加载 DATABASE_URL (standalone pattern, 对齐 test_execution_mode_isolation.py)
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


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def sync_conn():
    """psycopg2 同步连接, autocommit=True. 铁律 35: .env 未配置 → skip."""
    if not _PG_URL:
        pytest.skip("DATABASE_URL not set (backend/.env 未配置) — skipping integration tests")
    conn = psycopg2.connect(_PG_URL)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def isolated_strategy(sync_conn):
    """独立测试 strategy_id + 测试后清理相关表."""
    sid = str(uuid.uuid4())
    cur = sync_conn.cursor()
    cur.execute(
        "INSERT INTO strategy (id, name, market, mode, active_version, status) "
        "VALUES (%s, %s, 'astock', 'visual', 1, 'draft')",
        (sid, f"test_qmt_state_{sid[:8]}"),
    )
    try:
        yield sid
    finally:
        for tbl in ("trade_log", "position_snapshot", "performance_series"):
            # silent_ok: 测试 cleanup 吞异常 (不影响生产链路)
            with contextlib.suppress(Exception):
                cur.execute(f"DELETE FROM {tbl} WHERE strategy_id = %s", (sid,))  # noqa: S608
        # silent_ok: 测试 cleanup
        with contextlib.suppress(Exception):
            cur.execute("DELETE FROM strategy WHERE id = %s", (sid,))


def _seed_prev_position(conn, sid, td, code, qty):
    """种一行 prev position_snapshot (execution_mode='live')."""
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO position_snapshot
           (code, trade_date, strategy_id, market, quantity, market_value,
            weight, execution_mode)
           VALUES (%s, %s, %s, 'astock', %s, 100.0, 0.01, 'live')
           ON CONFLICT (code, trade_date, strategy_id, execution_mode) DO UPDATE SET
             quantity=EXCLUDED.quantity""",
        (code, td, sid, qty),
    )


def _monkey_strategy(monkeypatch, sid):
    """替换 settings.PAPER_STRATEGY_ID 为测试 sid."""
    from app.config import settings

    monkeypatch.setattr(settings, "PAPER_STRATEGY_ID", sid)


# ─── Tests ───────────────────────────────────────────────────────


def test_fail_loud_when_prev_has_positions_today_empty(
    sync_conn, isolated_strategy, monkeypatch
):
    """回归 Session 10 P1-b: 前日 5 持仓 + 今日 QMT 返 0 → RAISE."""
    from app.services.pt_qmt_state import QMTEmptyPositionsError, save_qmt_state

    sid = isolated_strategy
    _monkey_strategy(monkeypatch, sid)
    prev_date = date(2026, 4, 16)
    today = date(2026, 4, 17)

    for i in range(5):
        _seed_prev_position(sync_conn, sid, prev_date, f"00000{i}.SZ", 100)

    with pytest.raises(QMTEmptyPositionsError, match=r"FAIL-LOUD.*5 只 live"):
        save_qmt_state(
            sync_conn,
            today,
            qmt_positions={},
            today_close={},
            nav=1_000_000.0,
            prev_nav=1_000_000.0,
            qmt_nav_data={"cash": 1_000_000},
            benchmark_close=None,
        )


def test_no_raise_when_no_prev_snapshot(sync_conn, isolated_strategy, monkeypatch):
    """fresh start: prev 无 row + 今日 {} → 无 raise, 正常写入 performance_series."""
    from app.services.pt_qmt_state import save_qmt_state

    sid = isolated_strategy
    _monkey_strategy(monkeypatch, sid)
    today = date(2026, 4, 17)

    save_qmt_state(
        sync_conn,
        today,
        qmt_positions={},
        today_close={},
        nav=1_000_000.0,
        prev_nav=1_000_000.0,
        qmt_nav_data={"cash": 1_000_000},
        benchmark_close=None,
    )
    cur = sync_conn.cursor()
    cur.execute(
        "SELECT position_count FROM performance_series "
        "WHERE strategy_id=%s AND trade_date=%s AND execution_mode='live'",
        (sid, today),
    )
    r = cur.fetchone()
    assert r is not None and r[0] == 0, "fresh start 应正常写入 performance_series"


def test_no_raise_when_prev_zero_qty_today_empty(
    sync_conn, isolated_strategy, monkeypatch
):
    """prev row 但 quantity=0 + 今日 {} → 无 raise (prev_count=0 不触发)."""
    from app.services.pt_qmt_state import save_qmt_state

    sid = isolated_strategy
    _monkey_strategy(monkeypatch, sid)
    prev_date = date(2026, 4, 16)
    today = date(2026, 4, 17)

    _seed_prev_position(sync_conn, sid, prev_date, "000001.SZ", 0)

    save_qmt_state(
        sync_conn,
        today,
        qmt_positions={},
        today_close={},
        nav=1_000_000.0,
        prev_nav=1_000_000.0,
        qmt_nav_data={"cash": 1_000_000},
        benchmark_close=None,
    )


def test_no_raise_when_today_has_positions(sync_conn, isolated_strategy, monkeypatch):
    """prev 5 pos + 今日 3 pos → 正常 DELETE+INSERT, 无 raise."""
    from app.services.pt_qmt_state import save_qmt_state

    sid = isolated_strategy
    _monkey_strategy(monkeypatch, sid)
    prev_date = date(2026, 4, 16)
    today = date(2026, 4, 17)

    for i in range(5):
        _seed_prev_position(sync_conn, sid, prev_date, f"00000{i}.SZ", 100)

    qmt_positions = {"000001.SZ": 100, "000002.SZ": 200, "000003.SZ": 300}
    today_close = {"000001.SZ": 10.0, "000002.SZ": 20.0, "000003.SZ": 30.0}

    save_qmt_state(
        sync_conn,
        today,
        qmt_positions=qmt_positions,
        today_close=today_close,
        nav=1_000_000.0,
        prev_nav=1_000_000.0,
        qmt_nav_data={"cash": 100_000},
        benchmark_close=4000.0,
    )
    cur = sync_conn.cursor()
    cur.execute(
        "SELECT COUNT(*) FROM position_snapshot "
        "WHERE strategy_id=%s AND trade_date=%s AND execution_mode='live'",
        (sid, today),
    )
    assert cur.fetchone()[0] == 3


def test_no_raise_across_weekend_gap(sync_conn, isolated_strategy, monkeypatch):
    """prev=周五 + today=周一 + 今日非空 → prev_date 正确跨周末, 无 raise."""
    from app.services.pt_qmt_state import save_qmt_state

    sid = isolated_strategy
    _monkey_strategy(monkeypatch, sid)
    friday = date(2026, 4, 17)
    monday = date(2026, 4, 20)

    for i in range(3):
        _seed_prev_position(sync_conn, sid, friday, f"00000{i}.SZ", 100)

    save_qmt_state(
        sync_conn,
        monday,
        qmt_positions={"000001.SZ": 100},
        today_close={"000001.SZ": 10.0},
        nav=1_000_000.0,
        prev_nav=1_000_000.0,
        qmt_nav_data={"cash": 990_000},
        benchmark_close=None,
    )


def test_source_contains_fail_loud_marker():
    """源码 inspection: 含 FAIL-LOUD marker + raise QMTEmptyPositionsError (防未来误删)."""
    from app.services import pt_qmt_state as m

    src = inspect.getsource(m)
    assert "FAIL-LOUD" in src, "FAIL-LOUD marker 必须在源码 (铁律 33)"
    assert "raise QMTEmptyPositionsError" in src, "raise QMTEmptyPositionsError 必须存在"
    assert "_assert_positions_not_evaporated" in src, "helper 必须存在"


def test_error_message_contains_runbook_hint(sync_conn, isolated_strategy, monkeypatch):
    """raise message 含 runbook hint (Servy QMTData / redis portfolio:current / xtquant)."""
    from app.services.pt_qmt_state import QMTEmptyPositionsError, save_qmt_state

    sid = isolated_strategy
    _monkey_strategy(monkeypatch, sid)
    prev_date = date(2026, 4, 16)
    today = date(2026, 4, 17)
    _seed_prev_position(sync_conn, sid, prev_date, "000001.SZ", 100)

    with pytest.raises(QMTEmptyPositionsError) as exc_info:
        save_qmt_state(
            sync_conn,
            today,
            qmt_positions={},
            today_close={},
            nav=1_000_000.0,
            prev_nav=1_000_000.0,
            qmt_nav_data={"cash": 1_000_000},
            benchmark_close=None,
        )
    msg = str(exc_info.value)
    assert "Servy QMTData" in msg
    assert "redis portfolio:current" in msg
    assert "xtquant" in msg
