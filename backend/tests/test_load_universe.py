"""Unit tests for ``scripts.run_backtest.load_universe`` — PR-B ST filter.

Session 10 P0-ε: 4-14 PT live 错买 688184.SH (ST), 4-15 错卖. 根因 load_universe
2026-04-14 "fix" 用 INNER JOIN + status_date 回退, 当 status_date 滞后 (4-13) 时,
688184 4-13 is_st=false 记录被用作 4-14 过滤 → 漏过. PR-B 修:
  - LEFT JOIN + ss.trade_date = k.trade_date (correlated 实际日, 不用 status_date)
  - COALESCE(is_st/is_suspended/is_new_stock, TRUE) = false (缺记录保守排除)

测试矩阵 (≥5 要求 + 2 bonus):
  1. missing ss row → excluded (COALESCE TRUE)
  2. all flags false → included (happy path)
  3. is_st=true → excluded (P0-ε 回归, 688184 场景)
  4. is_suspended/is_new_stock=true (parametrize) → excluded
  5. status_date lag 场景 (昨日 is_st=false, 今日 is_st=true) → 走今日 k.trade_date 关联, excluded
  6. board='bse' → excluded (backward compat)
  7. code LIKE '%%.BJ' → excluded (backward compat)
"""

from __future__ import annotations

import contextlib
import importlib.util
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

# .env 加载 DATABASE_URL (standalone pattern)
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


# scripts/ 不是 package, 动态 import run_backtest
def _load_load_universe():
    """Dynamic import `load_universe` from scripts/run_backtest.py (非 package 路径)."""
    spec_path = _REPO / "scripts" / "run_backtest.py"
    spec = importlib.util.spec_from_file_location("run_backtest", spec_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_universe


load_universe = _load_load_universe()


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
def test_prefix():
    """独立测试 code 前缀. 所有 code 列 VARCHAR(10), 实股 XXXXXX.SH 9 字符刚好.

    用 'T' + 3 hex = 4 字符 + 'NN.SX' (5 字符) = 9 字符, 不超 VARCHAR(10).
    避免污染真实 stock 数据 (T 开头非 A 股代码).
    """
    return "T" + uuid.uuid4().hex[:3].upper()


@pytest.fixture
def seeded_universe(sync_conn, test_prefix):
    """插入测试专属 code 到 klines_daily + stock_status_daily + symbols, 测试后清理.

    仿 test_pt_qmt_state.py:80-108 isolated_strategy 模式.
    返回 (trade_date, dict[code, config]).
    """
    today = date(2099, 1, 15)  # 远未来日, 无真实数据冲突
    cur = sync_conn.cursor()
    created_codes: list[str] = []

    def _seed(code: str, ss_config: dict | None, board: str | None = None):
        """Insert one test code. ss_config=None → 无 stock_status_daily 行 (missing 场景).
        ss_config={'is_st': True/False, 'is_suspended': ..., 'is_new_stock': ...}.
        """
        # klines_daily: 必需
        cur.execute(
            """INSERT INTO klines_daily (code, trade_date, open, high, low, close,
                                         pre_close, volume, amount, adj_factor)
               VALUES (%s, %s, 10.0, 10.5, 9.5, 10.0, 10.0, 1000, 10000, 1.0)
               ON CONFLICT DO NOTHING""",
            (code, today),
        )
        # symbols: 默认 list_status='L'. name VARCHAR(20) 充裕.
        cur.execute(
            """INSERT INTO symbols (code, name, list_status)
               VALUES (%s, %s, 'L') ON CONFLICT DO NOTHING""",
            (code, f"TST_{code[:5]}"),
        )
        # stock_status_daily: 可选 (None 模拟缺记录)
        if ss_config is not None:
            cur.execute(
                """INSERT INTO stock_status_daily
                   (code, trade_date, is_st, is_suspended, is_new_stock, board)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (code, trade_date) DO UPDATE SET
                     is_st=EXCLUDED.is_st, is_suspended=EXCLUDED.is_suspended,
                     is_new_stock=EXCLUDED.is_new_stock, board=EXCLUDED.board""",
                (
                    code,
                    today,
                    ss_config.get("is_st", False),
                    ss_config.get("is_suspended", False),
                    ss_config.get("is_new_stock", False),
                    board or ss_config.get("board"),
                ),
            )
        created_codes.append(code)

    try:
        yield today, _seed, test_prefix, created_codes
    finally:
        for code in created_codes:
            # silent_ok: 测试 cleanup (铁律 33)
            with contextlib.suppress(Exception):
                cur.execute(
                    "DELETE FROM klines_daily WHERE code = %s AND trade_date = %s",
                    (code, today),
                )
            with contextlib.suppress(Exception):
                cur.execute(
                    "DELETE FROM stock_status_daily WHERE code = %s AND trade_date >= %s",
                    (code, today - timedelta(days=5)),
                )
            with contextlib.suppress(Exception):
                cur.execute("DELETE FROM symbols WHERE code = %s", (code,))


# ─── Tests ───────────────────────────────────────────────────────


def test_excludes_ss_missing_row_conservative(sync_conn, seeded_universe):
    """缺 stock_status_daily 行 → COALESCE(is_st, TRUE) 触发, 排除.

    回归: 4-14 "fix" 之前的 LEFT JOIN + COALESCE(is_st, false) 宽松漏过 bug.
    """
    today, _seed, prefix, _ = seeded_universe
    code = f"{prefix}01.SH"
    _seed(code, ss_config=None)  # 不插 stock_status_daily

    universe = load_universe(today, sync_conn)
    assert code not in universe, "缺 ss 行时必须保守排除 (COALESCE TRUE)"


def test_includes_when_all_flags_false(sync_conn, seeded_universe):
    """happy path: ss 行 is_st=false/is_suspended=false/is_new_stock=false → 包含."""
    today, _seed, prefix, _ = seeded_universe
    code = f"{prefix}02.SH"
    _seed(code, ss_config={"is_st": False, "is_suspended": False, "is_new_stock": False},
          board="main")

    universe = load_universe(today, sync_conn)
    assert code in universe, "所有 flag false 时应包含"


def test_excludes_ss_is_st_true(sync_conn, seeded_universe):
    """P0-ε 回归: 688184 场景 — is_st=true → 排除."""
    today, _seed, prefix, _ = seeded_universe
    code = f"{prefix}03.SH"
    _seed(code, ss_config={"is_st": True, "is_suspended": False, "is_new_stock": False},
          board="main")

    universe = load_universe(today, sync_conn)
    assert code not in universe, "is_st=true 必须排除 (P0-ε 688184 场景)"


@pytest.mark.parametrize(
    "flag_name",
    ["is_suspended", "is_new_stock"],
)
def test_excludes_single_flag_true(sync_conn, seeded_universe, flag_name):
    """单独 is_suspended=true 或 is_new_stock=true → 排除."""
    today, _seed, prefix, _ = seeded_universe
    code = f"{prefix}04.SH"
    cfg = {"is_st": False, "is_suspended": False, "is_new_stock": False}
    cfg[flag_name] = True
    _seed(code, ss_config=cfg, board="main")

    universe = load_universe(today, sync_conn)
    assert code not in universe, f"{flag_name}=true 必须排除"


def test_uses_actual_trade_date_not_status_date_lag(sync_conn, seeded_universe):
    """核心 P0-ε 回归: 昨日 ss 行 is_st=false, 今日 ss 行 is_st=true, 今日 k.trade_date → 走实际日.

    旧 INNER JOIN + status_date 回退: 如 status_date=昨日, 用昨日 is_st=false → 漏过.
    新 LEFT JOIN + ss.trade_date=k.trade_date: 走今日 is_st=true → 正确排除.
    """
    today, _seed, prefix, _ = seeded_universe
    code = f"{prefix}05.SH"
    cur = sync_conn.cursor()
    yesterday = today - timedelta(days=1)
    # 昨日 ss 行: is_st=false (旧状态)
    cur.execute(
        """INSERT INTO stock_status_daily (code, trade_date, is_st, is_suspended,
                                           is_new_stock, board)
           VALUES (%s, %s, false, false, false, 'main')
           ON CONFLICT (code, trade_date) DO NOTHING""",
        (code, yesterday),
    )
    # 今日 ss 行: is_st=true (新状态, 688184 场景)
    _seed(code, ss_config={"is_st": True, "is_suspended": False, "is_new_stock": False},
          board="main")

    universe = load_universe(today, sync_conn)
    assert code not in universe, (
        "load_universe 必须走 k.trade_date (今日 is_st=true) "
        "而非昨日 status_date (is_st=false), 否则 P0-ε 重现"
    )


def test_excludes_bse_board(sync_conn, seeded_universe):
    """board='bse' → 排除 (backward compat)."""
    today, _seed, prefix, _ = seeded_universe
    code = f"{prefix}06.SH"
    _seed(code, ss_config={"is_st": False, "is_suspended": False, "is_new_stock": False},
          board="bse")

    universe = load_universe(today, sync_conn)
    assert code not in universe, "board='bse' 必须排除"


def test_excludes_bj_suffix(sync_conn, seeded_universe):
    """code LIKE '%%.BJ' → 排除 (backward compat)."""
    today, _seed, prefix, _ = seeded_universe
    code = f"{prefix}07.BJ"
    _seed(code, ss_config={"is_st": False, "is_suspended": False, "is_new_stock": False},
          board="main")

    universe = load_universe(today, sync_conn)
    assert code not in universe, "code LIKE '%%.BJ' 必须排除"


def test_source_contains_pr_b_marker():
    """源码 inspection: run_backtest.py 含 PR-B 关键特征 (防未来误删)."""
    import inspect

    src = inspect.getsource(load_universe)
    assert "LEFT JOIN stock_status_daily" in src, "必须是 LEFT JOIN (非 INNER JOIN)"
    assert "ss.trade_date = k.trade_date" in src, "必须 k.trade_date correlated"
    assert "COALESCE(ss.is_st, TRUE)" in src, "COALESCE TRUE 守门 (非 false 方向)"
    assert "P0-ε" in src, "docstring 必须含 P0-ε 背景"
