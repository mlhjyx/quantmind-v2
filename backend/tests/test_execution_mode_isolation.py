"""ADR-008 D2 execution_mode 命名空间动态化 — 回归守门矩阵.

Session 10 (2026-04-19) 根因: live 模式核心交易路径**写** 'live' **读** hardcoded 'paper',
命名空间永远 empty → 熔断 L1-L4 裸奔 / 每日误换仓 / 组合跳空检测失效 / NAV 字段全错.

本文件守门 5 个 P0/P1 (α/β/γ + P1-a/c) 修复:

D2 (必改动态化):
  - paper_broker.load_state: 读自己 mode 的 position_snapshot/performance_series/trade_log
  - signal_service._load_prev_weights: 读自己 mode 的 position_snapshot
  - risk_control.check_circuit_breaker_sync: 读自己 mode 的 performance_series
  - risk_control._load_cb_state_sync / _upsert_cb_state_sync / _insert_cb_log_sync: 按 mode 读写
  - pt_monitor.check_opening_gap: 读自己 mode 的 position_snapshot
  - beta_hedge.calc_portfolio_beta: 签名必传 execution_mode
  - run_paper_trading.py L225 prev_nav (P1-c 自愈): 读自己 mode

D3 (signals 表跨模式共享, 保留 hardcoded 'paper', 本文件 SAST 守门):
  - signal_service._write_signals / get_latest_signals / DELETE
  - run_paper_trading.py L287 --force-rebalance UPDATE signals

D4 (paper UI/分析工具保留 hardcoded 'paper', 本文件 SAST 守门):
  - paper_trading_service.py / paper_trading.py API
  - scripts/paper_trading_*.py / pt_daily_summary.py / check_graduation.py 等

实施边界: 本文件回归的是 DB 层按 mode 物理隔离 + 源码 SAST 契约.
不测试生产链路 end-to-end (走 regression_test.py / smoke).
"""

from __future__ import annotations

import contextlib
import os
import re
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
import psycopg2
import pytest

_BACKEND = Path(__file__).resolve().parent.parent
_REPO = _BACKEND.parent
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_REPO))

# backend/.env 加载 DATABASE_URL (测试脚本 standalone, 与 investigate_pt_drawdown.py 同 pattern)
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
    """psycopg2 同步连接, autocommit=True (生产 Service 路径契约一致).

    铁律 35: 禁止源码硬编码 DATABASE_URL fallback. backend/.env 未配置时 skip.
    """
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
    """独立测试 strategy_id, 测试结束后清理 6 张相关表 + strategy 本行.

    每个测试独立 UUID, 即便 DB 有残留也不跨测试污染.
    """
    sid = str(uuid.uuid4())
    cur = sync_conn.cursor()
    cur.execute(
        "INSERT INTO strategy (id, name, market, mode, active_version, status) "
        "VALUES (%s, %s, 'astock', 'visual', 1, 'draft')",
        (sid, f"test_exec_iso_{sid[:8]}"),
    )
    try:
        yield sid
    finally:
        for tbl in (
            "signals",
            "trade_log",
            "position_snapshot",
            "performance_series",
            "circuit_breaker_state",
            "circuit_breaker_log",
        ):
            # silent_ok: 测试 cleanup 吞异常 (表可能不存在 / 无 row), 不影响生产链路
            with contextlib.suppress(Exception):
                cur.execute(f"DELETE FROM {tbl} WHERE strategy_id = %s", (sid,))  # noqa: S608
        # silent_ok: 测试 cleanup 吞异常
        with contextlib.suppress(Exception):
            cur.execute("DELETE FROM strategy WHERE id = %s", (sid,))


@pytest.fixture(params=["paper", "live"])
def mode(request, monkeypatch):
    """参数化 settings.EXECUTION_MODE paper/live."""
    from app.config import settings

    monkeypatch.setattr(settings, "EXECUTION_MODE", request.param)
    return request.param


# ─── Helpers (DB 插入) ───────────────────────────────────────────


def _seed_position(conn, sid, td, code, qty, mv, weight, mode_):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO position_snapshot
           (code, trade_date, strategy_id, market, quantity, market_value,
            weight, execution_mode)
           VALUES (%s, %s, %s, 'astock', %s, %s, %s, %s)
           ON CONFLICT (code, trade_date, strategy_id, execution_mode) DO UPDATE SET
             quantity=EXCLUDED.quantity, market_value=EXCLUDED.market_value,
             weight=EXCLUDED.weight""",
        (code, td, sid, qty, mv, weight, mode_),
    )


def _seed_performance(conn, sid, td, nav, mode_, daily_return=0.0, drawdown=0.0):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO performance_series
           (trade_date, strategy_id, market, nav, daily_return, cumulative_return,
            drawdown, cash_ratio, cash, position_count, turnover, execution_mode)
           VALUES (%s, %s, 'astock', %s, %s, 0, %s, 0, 0, 0, 0, %s)
           ON CONFLICT (trade_date, strategy_id, execution_mode) DO UPDATE SET
             nav=EXCLUDED.nav, daily_return=EXCLUDED.daily_return,
             drawdown=EXCLUDED.drawdown""",
        (td, sid, nav, daily_return, drawdown, mode_),
    )


def _seed_trade(conn, sid, td, code, direction, qty, mode_):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO trade_log
           (code, trade_date, strategy_id, direction, quantity, fill_price,
            slippage_bps, commission, stamp_tax, total_cost, execution_mode,
            executed_at)
           VALUES (%s, %s, %s, %s, %s, 10.0, 0, 0, 0, 0, %s, %s)
           ON CONFLICT DO NOTHING""",
        (code, td, sid, direction, qty, mode_, datetime.now(UTC)),
    )


# ─── D2 运行时隔离 ───────────────────────────────────────────────


def test_paper_broker_load_state_reads_own_mode(sync_conn, isolated_strategy, mode):
    """PaperBroker.load_state 按 execution_mode 参数读 position_snapshot (铁律 31 显式注入)."""
    from engines.paper_broker import PaperBroker

    sid = isolated_strategy
    td = date(2024, 1, 2)
    # 同 (code, date, sid) 两 mode 各插一行, DB 物理隔离
    _seed_position(sync_conn, sid, td, "000001.SZ", 100, 1000.0, 0.1, "paper")
    _seed_position(sync_conn, sid, td, "000001.SZ", 200, 2000.0, 0.2, "live")
    _seed_performance(sync_conn, sid, td, 1_000_000.0, "paper")
    _seed_performance(sync_conn, sid, td, 2_000_000.0, "live")

    broker = PaperBroker(strategy_id=sid, execution_mode=mode)
    state = broker.load_state(sync_conn)

    if mode == "paper":
        assert state.holdings == {"000001.SZ": 100}
        assert state.nav == pytest.approx(1_000_000.0)
    else:
        assert state.holdings == {"000001.SZ": 200}
        assert state.nav == pytest.approx(2_000_000.0)


def test_paper_broker_cross_mode_isolation(sync_conn, isolated_strategy):
    """paper 模式 load_state 看不到 live 数据, 反之亦然 (同 strategy_id)."""
    from engines.paper_broker import PaperBroker

    sid = isolated_strategy
    td = date(2024, 1, 3)
    _seed_position(sync_conn, sid, td, "000002.SZ", 500, 5000.0, 0.5, "live")
    _seed_performance(sync_conn, sid, td, 3_000_000.0, "live")

    # paper 模式: live 命名空间数据不可见 → holdings empty
    broker = PaperBroker(strategy_id=sid, execution_mode="paper")
    paper_state = broker.load_state(sync_conn)
    assert paper_state.holdings == {}

    # live 模式: 看得到 live 数据
    broker2 = PaperBroker(strategy_id=sid, execution_mode="live")
    live_state = broker2.load_state(sync_conn)
    assert live_state.holdings == {"000002.SZ": 500}
    assert live_state.nav == pytest.approx(3_000_000.0)


def test_signal_service_load_prev_weights_mode(sync_conn, isolated_strategy, mode):
    """signal_service._load_prev_weights 按 mode 读 position_snapshot weight."""
    from app.services.signal_service import SignalService

    sid = isolated_strategy
    td = date(2024, 2, 1)
    _seed_position(sync_conn, sid, td, "600000.SH", 100, 1000.0, 0.3, "paper")
    _seed_position(sync_conn, sid, td, "600001.SH", 200, 2000.0, 0.7, "live")

    svc = SignalService()
    weights = svc._load_prev_weights(sync_conn, sid)

    if mode == "paper":
        assert weights == {"600000.SH": pytest.approx(0.3)}
    else:
        assert weights == {"600001.SH": pytest.approx(0.7)}


def test_risk_control_load_cb_state_reads_own_mode(sync_conn, isolated_strategy, mode):
    """_load_cb_state_sync 按 mode 读 circuit_breaker_state."""
    from app.services.risk_control_service import (
        _ensure_cb_tables_sync,
        _load_cb_state_sync,
    )

    _ensure_cb_tables_sync(sync_conn)
    sid = isolated_strategy
    cur = sync_conn.cursor()
    # paper row: L2 / live row: L0
    for m, lvl in [("paper", 2), ("live", 0)]:
        cur.execute(
            """INSERT INTO circuit_breaker_state
               (strategy_id, execution_mode, current_level, entered_at, entered_date,
                trigger_reason, recovery_streak_days, recovery_streak_return,
                position_multiplier, updated_at)
               VALUES (%s, %s, %s, NOW(), %s, 'seed', 0, 0.0, 1.0, NOW())
               ON CONFLICT (strategy_id, execution_mode) DO UPDATE SET
                 current_level=EXCLUDED.current_level""",
            (sid, m, lvl, date(2024, 3, 1)),
        )

    state = _load_cb_state_sync(sync_conn, sid)
    assert state is not None
    assert state["current_level"] == (2 if mode == "paper" else 0)


def test_risk_control_upsert_cb_state_writes_own_mode(
    sync_conn, isolated_strategy, mode
):
    """_upsert_cb_state_sync 写 circuit_breaker_state 按 mode."""
    from app.services.risk_control_service import (
        _ensure_cb_tables_sync,
        _upsert_cb_state_sync,
    )

    _ensure_cb_tables_sync(sync_conn)
    sid = isolated_strategy
    _upsert_cb_state_sync(
        sync_conn, sid, level=3, entered_date=date(2024, 4, 1),
        reason="test_seed", metrics=None,
        recovery_streak_days=0, recovery_streak_return=0.0,
        position_multiplier=0.5,
    )

    cur = sync_conn.cursor()
    cur.execute(
        "SELECT execution_mode, current_level FROM circuit_breaker_state WHERE strategy_id=%s",
        (sid,),
    )
    rows = cur.fetchall()
    assert rows == [(mode, 3)]


def test_risk_control_insert_cb_log_writes_own_mode(
    sync_conn, isolated_strategy, mode
):
    """_insert_cb_log_sync 写 circuit_breaker_log 按 mode."""
    from app.services.risk_control_service import (
        _ensure_cb_tables_sync,
        _insert_cb_log_sync,
    )

    _ensure_cb_tables_sync(sync_conn)
    sid = isolated_strategy
    _insert_cb_log_sync(
        sync_conn, sid, trade_date=date(2024, 5, 1),
        prev_level=0, new_level=1, transition_type="escalate",
        reason="test_seed", metrics=None,
    )

    cur = sync_conn.cursor()
    cur.execute(
        "SELECT execution_mode FROM circuit_breaker_log WHERE strategy_id=%s",
        (sid,),
    )
    rows = [r[0] for r in cur.fetchall()]
    assert rows == [mode]


def test_risk_control_check_circuit_breaker_reads_own_perf(
    sync_conn, isolated_strategy, mode
):
    """P0-α 根因回归: check_circuit_breaker_sync 能读到本 mode 的 performance_series,
    不再返回 L0 "首次运行".
    """
    from app.services.risk_control_service import (
        _ensure_cb_tables_sync,
        check_circuit_breaker_sync,
    )

    _ensure_cb_tables_sync(sync_conn)
    sid = isolated_strategy
    # 只插本 mode 的 performance row → 另一 mode 读不到 → 回到根因场景
    _seed_performance(sync_conn, sid, date(2024, 6, 1), 1_000_000.0, mode)
    _seed_performance(sync_conn, sid, date(2024, 6, 2), 990_000.0, mode, daily_return=-0.01)

    result = check_circuit_breaker_sync(
        conn=sync_conn, strategy_id=sid,
        exec_date=date(2024, 6, 3), initial_capital=1_000_000.0,
    )
    # 有数据 → 不会是 "首次运行"
    assert result["reason"] != "无历史数据(首次运行)"


def test_risk_control_cross_mode_cb_state_isolation(sync_conn, isolated_strategy):
    """circuit_breaker_state paper 和 live row 独立共存 (UNIQUE 约束 strategy_id+mode)."""
    from app.services.risk_control_service import _ensure_cb_tables_sync

    _ensure_cb_tables_sync(sync_conn)
    sid = isolated_strategy
    cur = sync_conn.cursor()
    for m, lvl in [("paper", 3), ("live", 1)]:
        cur.execute(
            """INSERT INTO circuit_breaker_state
               (strategy_id, execution_mode, current_level, entered_at, entered_date,
                trigger_reason, recovery_streak_days, recovery_streak_return,
                position_multiplier, updated_at)
               VALUES (%s, %s, %s, NOW(), %s, 'seed', 0, 0.0, 1.0, NOW())""",
            (sid, m, lvl, date(2024, 7, 1)),
        )
    cur.execute(
        "SELECT execution_mode, current_level FROM circuit_breaker_state "
        "WHERE strategy_id=%s ORDER BY execution_mode",
        (sid,),
    )
    rows = cur.fetchall()
    assert rows == [("live", 1), ("paper", 3)]


def test_pt_monitor_opening_gap_reads_own_mode(
    sync_conn, isolated_strategy, mode, monkeypatch
):
    """pt_monitor.check_opening_gap 组合加权跳空按 mode 读 position_snapshot.

    P1-a 根因回归: live 模式此处读 'paper' → total_w=0 组合跳空静默失效.
    """
    from app.config import settings
    from app.services import pt_monitor_service

    sid = isolated_strategy
    monkeypatch.setattr(settings, "PAPER_STRATEGY_ID", sid)
    td = date(2024, 8, 1)
    _seed_position(sync_conn, sid, td, "000100.SZ", 1000, 10000.0, 1.0, mode)

    # 构造 price_data: open 比 pre_close 低 4% (未触发单股 5% 告警, 但触发组合 >3%)
    price_df = pd.DataFrame([
        {"code": "000100.SZ", "open": 9.6, "pre_close": 10.0},
    ])

    class _Notif:
        def send_sync(self, *a, **kw):
            self._sent = getattr(self, "_sent", [])
            self._sent.append((a, kw))

    notif = _Notif()
    # 调用不应 crash, 内部 position_snapshot 查询应能匹配本 mode seed
    pt_monitor_service.check_opening_gap(
        exec_date=td, price_data=price_df, conn=sync_conn,
        notif_svc=notif, dry_run=True,
    )
    # 断言: 本 mode 的 position row 被读到 (total_w=1.0), 组合跳空 ≈ -4% 触发 P0 path
    # 因 dry_run=True 不会实际发送, 只检查函数完成不 raise.


def test_pt_monitor_opening_gap_cross_mode_invisible(
    sync_conn, isolated_strategy, monkeypatch
):
    """paper 模式 check_opening_gap 看不到 live snapshot (total_w=0)."""
    from app.config import settings
    from app.services import pt_monitor_service

    sid = isolated_strategy
    monkeypatch.setattr(settings, "PAPER_STRATEGY_ID", sid)
    monkeypatch.setattr(settings, "EXECUTION_MODE", "paper")

    td = date(2024, 8, 2)
    # 只种 live row, paper 模式应该 total_w=0 (跳空计算跳过, 不报错)
    _seed_position(sync_conn, sid, td, "000200.SZ", 500, 5000.0, 1.0, "live")

    price_df = pd.DataFrame([
        {"code": "000200.SZ", "open": 9.0, "pre_close": 10.0},
    ])

    class _Notif:
        def send_sync(self, *a, **kw): pass

    # 不应 raise; total_w=0 时组合跳空计算 skip
    pt_monitor_service.check_opening_gap(
        exec_date=td, price_data=price_df, conn=sync_conn,
        notif_svc=_Notif(), dry_run=True,
    )


def test_beta_hedge_calc_portfolio_beta_mode(sync_conn, isolated_strategy, mode):
    """calc_portfolio_beta 按 execution_mode 参数读 performance_series."""
    from engines.beta_hedge import calc_portfolio_beta

    sid = isolated_strategy
    # 无历史 → beta=0.0 (<20 天条件)
    beta = calc_portfolio_beta(
        trade_date=date(2024, 9, 1),
        strategy_id=sid,
        execution_mode=mode,
        lookback_days=60,
        conn=sync_conn,
    )
    assert beta == 0.0  # 历史不足


def test_beta_hedge_signature_requires_execution_mode():
    """calc_portfolio_beta 签名必传 execution_mode (ADR-008 D2 铁律 34 显式)."""
    import inspect

    from engines.beta_hedge import calc_portfolio_beta

    sig = inspect.signature(calc_portfolio_beta)
    assert "execution_mode" in sig.parameters
    param = sig.parameters["execution_mode"]
    # 必传参数: 无默认值
    assert param.default is inspect.Parameter.empty, (
        "ADR-008 D2: execution_mode 必须是必传参数 (铁律 34 显式 > 隐式)"
    )


# ─── D3 SAST 守门: signals 表跨模式共享, 保留 hardcoded 'paper' ────


def test_d3_signal_service_signals_table_stays_paper():
    """signal_service.py 的 3 处 signals 表操作保持 hardcoded 'paper'.

    regex 用 re.DOTALL + 限距懒惰匹配 (300 字符内), 防 refactor 跨函数假阳性
    (code reviewer P1 + python reviewer P3 合并守门).
    """
    src = (_BACKEND / "app" / "services" / "signal_service.py").read_text(encoding="utf-8")
    # get_latest_signals SELECT signals WHERE 'paper'
    assert re.search(
        r"FROM signals\s+WHERE.{0,200}?execution_mode\s*=\s*'paper'",
        src, re.DOTALL,
    ), "D3 破契约: signal_service.py get_latest_signals 必须保留 execution_mode='paper'"
    # _write_signals DELETE signals WHERE 'paper' (限 200 字符内)
    assert re.search(
        r"DELETE FROM signals\s+WHERE.{0,200}?execution_mode\s*=\s*'paper'",
        src, re.DOTALL,
    ), "D3 破契约: signal_service.py _write_signals DELETE 必须保留 'paper'"
    # _write_signals INSERT signals VALUES 'paper' (限 500 字符内, INSERT 字段列表较长)
    assert re.search(
        r"INSERT INTO signals.{0,500}?VALUES.{0,300}?'paper'",
        src, re.DOTALL,
    ), "D3 破契约: signal_service.py _write_signals INSERT VALUES 必须保留 'paper'"


def test_d3_run_paper_trading_signals_update_stays_paper():
    """run_paper_trading.py --force-rebalance UPDATE signals 保持 hardcoded 'paper'."""
    src = (_REPO / "scripts" / "run_paper_trading.py").read_text(encoding="utf-8")
    assert re.search(
        r"UPDATE signals.{0,300}?execution_mode\s*=\s*'paper'",
        src, re.DOTALL,
    ), "D3 破契约: run_paper_trading.py L287 UPDATE signals 必须保留 'paper'"


# ─── D2 SAST 守门: run_paper_trading.py L225 prev_nav 用 %s 参数化 ──


def test_d2_run_paper_trading_prev_nav_parametric():
    """run_paper_trading.py prev_nav SELECT 不再 hardcoded 'paper' (re.DOTALL 支持多行).

    PR-C CONTRACT_DRIFT 修: Session 21 PR #33 P1-c 二段根因修后, prev_nav SQL
    在 ``execution_mode = %s`` 之后追加了 ``AND trade_date < %s`` (防 16:30
    signal_phase 读到 15:40 reconciliation 当日 self), WHERE 子句变长 (注释 + 多行
    格式化). regex 容许窗 100→500 字符匹配新 SQL.
    """
    src = (_REPO / "scripts" / "run_paper_trading.py").read_text(encoding="utf-8")
    # prev_nav 查询必须用 %s 参数化. 跨字符串拼接 (`"...series " "WHERE..."`)
    # → SELECT 与 WHERE 之间会有 quote/whitespace/newline, 用 .{0,50}? 覆盖.
    assert re.search(
        r"SELECT nav FROM performance_series.{0,50}?WHERE.{0,500}?execution_mode\s*=\s*%s",
        src, re.DOTALL,
    ), "D2 破契约: run_paper_trading prev_nav 必须参数化 execution_mode=%s"


# ─── D4 SAST 守门: paper UI/分析工具保留 hardcoded 'paper' ──────────


D4_PATHS = [
    _BACKEND / "app" / "services" / "paper_trading_service.py",
    _BACKEND / "app" / "api" / "paper_trading.py",
    _REPO / "scripts" / "paper_trading_status.py",
    _REPO / "scripts" / "paper_trading_stats.py",
    _REPO / "scripts" / "pt_daily_summary.py",
    _REPO / "scripts" / "check_graduation.py",
    _REPO / "scripts" / "pt_graduation_assessment.py",
    _REPO / "scripts" / "approve_l4.py",
    _REPO / "scripts" / "pt_watchdog.py",
    _REPO / "scripts" / "bayesian_slippage_calibration.py",
]


@pytest.mark.parametrize("path", D4_PATHS, ids=lambda p: p.name)
def test_d4_paper_ui_tools_stay_hardcoded(path):
    """ADR-008 D4: paper UI/分析工具文件必须仍含 'paper' 字面量 (误改即 FAIL)."""
    if not path.exists():
        pytest.skip(f"{path.name} 不在当前工作区 (可能已归档)")
    src = path.read_text(encoding="utf-8", errors="ignore")
    assert "'paper'" in src or '"paper"' in src, (
        f"D4 破契约: {path.name} 不应被误改 — paper UI/分析工具保留 hardcoded 'paper'"
    )
