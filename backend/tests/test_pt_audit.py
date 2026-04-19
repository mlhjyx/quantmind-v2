"""Unit tests for ``scripts.pt_audit`` — PR-C Session 16 5-check guard.

覆盖矩阵 (9 tests):
  1. st_leak detects is_st=true buy
  2. st_leak passes NULL is_st (status_date lag 保守)
  3. mode_mismatch detects mixed paper+live
  4. mode_mismatch passes pure live
  5. turnover_abnormal triggers > threshold
  6. rebalance_date_mismatch detects 非月末
  7. db_drift reconstructs + diffs
  8. integration no_findings green path
  9. module constants & contract (CHECK_LIST / check_* fn exist)

仿 test_restore_snapshot_20260417.py 模式:
  - sync psycopg2 real DB + isolated UUID strategy_id + 远未来 fixture dates
  - teardown DELETE by sid (FK-less columns)
  - dynamic import scripts/pt_audit.py (非 package)
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import sys
import uuid
from datetime import date, datetime, time
from pathlib import Path

import psycopg2
import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_REPO))

# .env 加载 DATABASE_URL
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


def _load_mod():
    """Dynamic import ``scripts/pt_audit.py`` (非 package)."""
    spec_path = _REPO / "scripts" / "pt_audit.py"
    module_name = "pt_audit_test_shim"
    if module_name in sys.modules:
        return sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, spec_path)
    assert spec is not None and spec.loader is not None, f"Cannot load {spec_path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_mod()


# ─── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def sync_conn():
    """psycopg2 autocommit=True. 铁律 35: .env 未配 → skip."""
    if not _PG_URL:
        pytest.skip("DATABASE_URL not set — skipping integration tests")
    conn = psycopg2.connect(_PG_URL)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def isolated_strategy(sync_conn):
    """独立 UUID sid + 远未来 audit_date + ref_date + teardown DELETE."""
    sid = str(uuid.uuid4())
    # 2099-04 — 远未来, 非真实 PT 数据; 4-30 是月末 (2099 4-30 恰逢周四), 4-15 非月末
    # 实际测试用 audit_date=2099-04-15 (非月末), ref_date=2099-04-14
    audit_date = date(2099, 4, 15)
    ref_date = date(2099, 4, 14)
    cur = sync_conn.cursor()
    cur.execute(
        "INSERT INTO strategy (id, name, market, mode, active_version, status) "
        "VALUES (%s, %s, 'astock', 'visual', 1, 'draft')",
        (sid, f"test_audit_{sid[:8]}"),
    )
    # Seed trading_calendar 本月 (2099-04) 条目, 保证 is_month_last 可判
    for d, is_td in [
        (date(2099, 4, 14), True),
        (date(2099, 4, 15), True),  # 非月末
        (date(2099, 4, 16), True),
        (date(2099, 4, 30), True),  # 月末最后交易日
    ]:
        with contextlib.suppress(Exception):
            cur.execute(
                """INSERT INTO trading_calendar (trade_date, market, is_trading_day, is_half_day)
                   VALUES (%s, 'astock', %s, false) ON CONFLICT DO NOTHING""",
                (d, is_td),
            )
    try:
        yield sid, audit_date, ref_date
    finally:
        for tbl in ("trade_log", "position_snapshot", "performance_series"):
            with contextlib.suppress(Exception):
                cur.execute(f"DELETE FROM {tbl} WHERE strategy_id = %s", (sid,))  # noqa: S608
        with contextlib.suppress(Exception):
            cur.execute(
                "DELETE FROM stock_status_daily WHERE trade_date BETWEEN %s AND %s AND code LIKE 'TA%%'",
                (ref_date, audit_date),
            )
        with contextlib.suppress(Exception):
            cur.execute(
                "DELETE FROM klines_daily WHERE trade_date BETWEEN %s AND %s AND code LIKE 'TA%%'",
                (ref_date, audit_date),
            )
        with contextlib.suppress(Exception):
            cur.execute(
                "DELETE FROM trading_calendar WHERE trade_date BETWEEN %s AND %s",
                (date(2099, 4, 1), date(2099, 4, 30)),
            )
        # Stage 4: 清理 pt_audit 写入的 scheduler_task_log 行 (按 sid 隔离)
        with contextlib.suppress(Exception):
            cur.execute(
                "DELETE FROM scheduler_task_log "
                "WHERE task_name = 'pt_audit' AND result_json->>'strategy_id' = %s",
                (sid,),
            )
        with contextlib.suppress(Exception):
            cur.execute("DELETE FROM strategy WHERE id = %s", (sid,))


def _seed_trade_log(
    conn: psycopg2.extensions.connection,
    sid: str,
    td: date,
    code: str,
    direction: str,
    qty: int,
    price: float,
    execution_mode: str = "live",
    executed_at: datetime | None = None,
) -> None:
    if executed_at is None:
        # 铁律 41 waiver: trade_log.executed_at 是 TIMESTAMPTZ 但测试数据无真实时区语义
        executed_at = datetime.combine(td, time(9, 32))
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO trade_log
           (code, trade_date, strategy_id, market, direction, quantity, fill_price,
            commission, stamp_tax, swap_cost, total_cost, execution_mode, executed_at)
           VALUES (%s, %s, %s, 'astock', %s, %s, %s, 5.0, 0.0, 0.0, 5.0, %s, %s)""",
        (code, td, sid, direction, qty, price, execution_mode, executed_at),
    )


def _seed_st_status(
    conn: psycopg2.extensions.connection, td: date, code: str, is_st: bool,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO stock_status_daily
           (code, trade_date, is_st, is_suspended, is_new_stock, board)
           VALUES (%s, %s, %s, false, false, 'main')
           ON CONFLICT (code, trade_date) DO UPDATE SET is_st=EXCLUDED.is_st""",
        (code, td, is_st),
    )


def _seed_perf(
    conn: psycopg2.extensions.connection, sid: str, td: date, nav: float,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO performance_series
           (trade_date, strategy_id, market, nav, daily_return, cumulative_return,
            drawdown, cash_ratio, position_count, turnover, execution_mode)
           VALUES (%s, %s, 'astock', %s, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 'live')
           ON CONFLICT (trade_date, strategy_id, execution_mode) DO UPDATE SET nav=EXCLUDED.nav""",
        (td, sid, nav),
    )


def _seed_snapshot(
    conn: psycopg2.extensions.connection,
    sid: str,
    td: date,
    code: str,
    qty: int,
    avg_cost: float = 10.0,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO position_snapshot
           (code, trade_date, strategy_id, market, quantity, avg_cost, market_value,
            weight, execution_mode)
           VALUES (%s, %s, %s, 'astock', %s, %s, %s, 0.01, 'live')""",
        (code, td, sid, qty, avg_cost, qty * avg_cost),
    )


def _seed_kline(
    conn: psycopg2.extensions.connection, td: date, code: str, close: float,
) -> None:
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO klines_daily (code, trade_date, open, high, low, close,
                                     pre_close, volume, amount, adj_factor)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 1000, 10000, 1.0)
           ON CONFLICT DO NOTHING""",
        (code, td, close, close, close, close, close),
    )


# ─── Tests ───────────────────────────────────────────────────────


def test_check_st_leak_detects_is_st_true_buy(sync_conn, isolated_strategy):
    """C1: seed today buy + is_st=true → finding non-empty."""
    sid, audit_date, _ = isolated_strategy
    _seed_trade_log(sync_conn, sid, audit_date, "TA001.SH", "buy", 100, 10.0)
    _seed_st_status(sync_conn, audit_date, "TA001.SH", is_st=True)

    findings = mod.check_st_leak(sync_conn, sid, audit_date)
    assert len(findings) == 1
    assert findings[0].check == "st_leak"
    assert findings[0].level == "P0"
    assert findings[0].detail["code"] == "TA001.SH"


def test_check_st_leak_passes_no_is_st_record(sync_conn, isolated_strategy):
    """C1: seed today buy + 无 ss row → pass (保守 COALESCE FALSE)."""
    sid, audit_date, _ = isolated_strategy
    _seed_trade_log(sync_conn, sid, audit_date, "TA002.SH", "buy", 100, 10.0)
    # 不 seed stock_status_daily

    findings = mod.check_st_leak(sync_conn, sid, audit_date)
    assert findings == [], "NULL is_st 应保守 FALSE 不告警"


def test_check_mode_mismatch_detects_mixed(sync_conn, isolated_strategy):
    """C2: 同 day 同 sid 既 paper 又 live → P1 finding."""
    sid, audit_date, _ = isolated_strategy
    _seed_trade_log(sync_conn, sid, audit_date, "TA003.SH", "buy", 100, 10.0, execution_mode="live")
    _seed_trade_log(sync_conn, sid, audit_date, "TA004.SH", "buy", 100, 10.0, execution_mode="paper")

    findings = mod.check_mode_mismatch(sync_conn, sid, audit_date)
    assert len(findings) == 1
    assert findings[0].level == "P1"
    assert set(findings[0].detail["modes"]) == {"live", "paper"}


def test_check_mode_mismatch_passes_pure_live(sync_conn, isolated_strategy):
    """C2: seed only live → pass."""
    sid, audit_date, _ = isolated_strategy
    _seed_trade_log(sync_conn, sid, audit_date, "TA005.SH", "buy", 100, 10.0, execution_mode="live")

    findings = mod.check_mode_mismatch(sync_conn, sid, audit_date)
    assert findings == []


def test_check_turnover_abnormal_triggers_above_threshold(sync_conn, isolated_strategy):
    """C3: seed turnover_value=40k, NAV=100k → ratio=0.40 > 0.30 default → finding."""
    sid, audit_date, _ = isolated_strategy
    _seed_perf(sync_conn, sid, audit_date, nav=100000.0)
    # turnover = 4000 * 10 = 40000
    _seed_trade_log(sync_conn, sid, audit_date, "TA006.SH", "buy", 4000, 10.0)

    findings = mod.check_turnover_abnormal(sync_conn, sid, audit_date, threshold=0.30)
    assert len(findings) == 1
    assert findings[0].level == "P1"
    assert findings[0].detail["ratio"] == pytest.approx(0.40, rel=1e-3)


def test_check_rebalance_date_detects_non_month_end(sync_conn, isolated_strategy):
    """C4: 2099-04-15 非月末 + turnover 5% > 1% 阈 → P2 finding."""
    sid, audit_date, _ = isolated_strategy  # audit_date = 2099-04-15 (非月末)
    _seed_perf(sync_conn, sid, audit_date, nav=100000.0)
    _seed_trade_log(sync_conn, sid, audit_date, "TA007.SH", "buy", 500, 10.0)  # 5000 / 100000 = 5%

    findings = mod.check_rebalance_date_mismatch(sync_conn, sid, audit_date)
    assert len(findings) == 1
    assert findings[0].level == "P2"


def test_check_db_drift_reconstructs_and_diffs(sync_conn, isolated_strategy):
    """C5: seed yesterday 1 code + today 1 new buy → expected=2, snapshot=1 → drift.

    Reviewer P2-5: reconstruct_positions 只读 position_snapshot + trade_log, 不读 klines,
    故本测试不 seed klines (原 seed 是 dead fixture).
    """
    sid, audit_date, ref_date = isolated_strategy
    # Yesterday snapshot: 1 code
    _seed_snapshot(sync_conn, sid, ref_date, "TA008.SH", 100, 10.0)
    # Today: 1 new buy of TA009.SH
    _seed_trade_log(sync_conn, sid, audit_date, "TA009.SH", "buy", 50, 12.0)
    # Today snapshot: only TA008.SH (missing TA009 = drift)
    _seed_snapshot(sync_conn, sid, audit_date, "TA008.SH", 100, 10.0)

    findings = mod.check_db_drift(sync_conn, sid, audit_date)
    assert len(findings) == 1
    assert findings[0].level == "P1"
    assert "TA009.SH" in findings[0].detail["missing_from_snapshot"]


def test_check_db_drift_skips_when_no_prev_snapshot(sync_conn, isolated_strategy):
    """C5 boundary: prev_date 存在 but 无 live snapshot → reconstruct 空 expected.

    Reviewer P1-5 补强: 防 Integration test green path 巧合 pass.
    expected_codes={}, actual_codes={} → 相等 → pass.
    """
    sid, audit_date, _ = isolated_strategy
    # 不 seed 任何 yesterday snapshot / today fills / today snapshot
    findings = mod.check_db_drift(sync_conn, sid, audit_date)
    assert findings == [], "empty expected + empty actual 应 pass"


def test_integration_no_findings_green_path(sync_conn, isolated_strategy, monkeypatch):
    """Integration: 月末 + 正常换手 + live only + 无 ST + 无 drift → all pass, exit=0.

    Reviewer P1-5 提点: seed ref_date snapshot + today snapshot 确保 C5
    真正 reconstruct → match (非空 expected vs 非空 actual), 非巧合空集合 match.
    """
    sid, _fixture_audit, _fixture_ref = isolated_strategy
    audit_date = date(2099, 4, 30)  # 月末最后交易日
    ref_date = date(2099, 4, 16)  # 前一交易日 (fixture 已种 calendar)
    # Yesterday snapshot 1 code (reconstruct 起点, 非空 expected 确保 C5 真跑 reconstruct)
    _seed_snapshot(sync_conn, sid, ref_date, "TA010.SH", 200, 10.0)
    _seed_perf(sync_conn, sid, audit_date, nav=100000.0)
    # turnover 2% < 30% (C3 pass), 月末 (C4 skip 因月末)
    _seed_trade_log(sync_conn, sid, audit_date, "TA010.SH", "buy", 200, 10.0)  # +200 shares, qty=400
    # 无 ST status → C1 pass (保守 FALSE)
    # Today snapshot: qty=400 (reconstruct 期望 = 200+200)
    _seed_snapshot(sync_conn, sid, audit_date, "TA010.SH", 400, 10.0)

    exit_code, findings = mod.run_audit(
        strategy_id=sid, audit_date=audit_date, only_checks=None, alert=False,
    )
    assert exit_code == 0, f"Expected clean pass, got {len(findings)} findings: {findings}"
    assert findings == []


def test_module_constants_and_contract():
    """模块契约: CHECK_LIST 长度 5 + 5 check_* 函数存在 (防未来误删)."""
    assert len(mod.CHECK_LIST) == 5
    assert set(mod.CHECK_LIST) == {
        "st_leak", "mode_mismatch", "turnover_abnormal",
        "rebalance_date_mismatch", "db_drift",
    }
    assert callable(mod.check_st_leak)
    assert callable(mod.check_mode_mismatch)
    assert callable(mod.check_turnover_abnormal)
    assert callable(mod.check_rebalance_date_mismatch)
    assert callable(mod.check_db_drift)
    assert callable(mod.run_audit)
    assert callable(mod.send_aggregated_alert)
    # Stage 4 contract: 新 helpers 暴露供测试 + monitoring
    assert callable(mod._is_trading_day)
    assert callable(mod._write_scheduler_log)
    assert mod.TURNOVER_THRESHOLD_DEFAULT == 0.30
    assert mod.REBAL_TURNOVER_THRESHOLD == 0.01


# ─── Stage 4 Tests ───────────────────────────────────────────────


def _query_scheduler_log(
    conn: psycopg2.extensions.connection, sid: str,
) -> list[dict]:
    """Return pt_audit scheduler_task_log rows for this sid (test helper)."""
    cur = conn.cursor()
    cur.execute(
        """SELECT status, result_json FROM scheduler_task_log
           WHERE task_name = 'pt_audit'
             AND result_json->>'strategy_id' = %s
           ORDER BY created_at ASC""",
        (sid,),
    )
    rows = []
    for status, result_json in cur.fetchall():
        rows.append({"status": status, "result_json": result_json})
    return rows


def test_run_audit_skips_non_trading_day(sync_conn, isolated_strategy):
    """Stage 4 guard: 非交易日 → exit 0, skipped log row, 无 check 执行."""
    sid, _audit_date, _ref_date = isolated_strategy
    # fixture 种的 4-15 是 trading_day, 用 4-17 (fixture 未种) 且强制 is_trading_day=false
    non_td = date(2099, 4, 17)
    cur = sync_conn.cursor()
    cur.execute(
        """INSERT INTO trading_calendar (trade_date, market, is_trading_day, is_half_day)
           VALUES (%s, 'astock', false, false) ON CONFLICT DO NOTHING""",
        (non_td,),
    )
    try:
        exit_code, findings = mod.run_audit(
            strategy_id=sid, audit_date=non_td, only_checks=None, alert=False,
        )
        assert exit_code == 0
        assert findings == []
        logs = _query_scheduler_log(sync_conn, sid)
        assert len(logs) == 1, f"expected 1 skipped log row, got {logs}"
        assert logs[0]["status"] == "skipped"
        assert logs[0]["result_json"]["exit_code"] == 0
        assert logs[0]["result_json"]["findings_count"] == 0
    finally:
        with contextlib.suppress(Exception):
            cur.execute("DELETE FROM trading_calendar WHERE trade_date = %s", (non_td,))


def test_run_audit_writes_scheduler_task_log_on_success(sync_conn, isolated_strategy):
    """Stage 4: 全部 check pass → 1 row status='success' + result_json 完整."""
    sid, _fixture_audit, _fixture_ref = isolated_strategy
    audit_date = date(2099, 4, 30)  # 月末 (C4 skip)
    ref_date = date(2099, 4, 16)
    _seed_snapshot(sync_conn, sid, ref_date, "TA020.SH", 200, 10.0)
    _seed_perf(sync_conn, sid, audit_date, nav=100000.0)
    _seed_trade_log(sync_conn, sid, audit_date, "TA020.SH", "buy", 200, 10.0)
    _seed_snapshot(sync_conn, sid, audit_date, "TA020.SH", 400, 10.0)

    exit_code, findings = mod.run_audit(
        strategy_id=sid, audit_date=audit_date, only_checks=None, alert=False,
    )
    assert exit_code == 0
    assert findings == []

    logs = _query_scheduler_log(sync_conn, sid)
    assert len(logs) == 1, f"expected 1 success log, got {logs}"
    assert logs[0]["status"] == "success"
    assert logs[0]["result_json"]["exit_code"] == 0
    assert logs[0]["result_json"]["findings_count"] == 0
    assert set(logs[0]["result_json"]["checks_run"]) == set(mod.CHECK_LIST)


def test_run_audit_writes_scheduler_task_log_on_findings(sync_conn, isolated_strategy):
    """Stage 4: C3 触发 → status='alert' + findings 入 result_json + exit_code=2 (P1)."""
    sid, audit_date, _ = isolated_strategy  # fixture audit_date = 2099-04-15 (非月末)
    _seed_perf(sync_conn, sid, audit_date, nav=100000.0)
    # turnover = 4000 * 10 = 40000 / 100000 = 0.40 > 0.30 → C3 P1 trigger
    # 且非月末 + 40% > 1% → C4 P2 也 trigger
    _seed_trade_log(sync_conn, sid, audit_date, "TA021.SH", "buy", 4000, 10.0)

    exit_code, findings = mod.run_audit(
        strategy_id=sid, audit_date=audit_date, only_checks=None, alert=False,
    )
    # top level = P1 (C3) → exit_code=2; C4 P2 同 findings 列表但非 top
    assert exit_code == 2
    assert len(findings) >= 1  # 至少 C3, 可能还有 C4

    logs = _query_scheduler_log(sync_conn, sid)
    assert len(logs) == 1, f"expected 1 alert log, got {logs}"
    assert logs[0]["status"] == "alert"
    assert logs[0]["result_json"]["exit_code"] == 2
    assert logs[0]["result_json"]["findings_count"] >= 1
    # 验证 findings 结构 (check / level / title / detail 都入 JSON)
    first = logs[0]["result_json"]["findings"][0]
    assert "check" in first
    assert "level" in first
    assert "title" in first
    assert "detail" in first
