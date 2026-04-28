"""MVP 3.5 Follow-up A — factor_lifecycle_monitor.py 历史回放 unit tests.

Session 43, 2026-04-28. 加速 4 周观察期 → 历史 12 周 replay 一日内验证.

覆盖:
  - _generate_replay_fridays (5 tests): basic Friday start / 非 Friday advance /
    clamped to today / weeks=0 raises / 跨年.
  - _replay_one_factor (3 tests): tail 空 None / ic_series<30 None / happy path.
  - replay() (5 tests): aggregation counters / SUNSET 推荐 / DEFER P1 reverse /
    NO_DATA / JSON report 写入.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Load script as module via importlib (script path sourced, not package import)
_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "factor_lifecycle_monitor.py"


@pytest.fixture(scope="module")
def flm():
    """Load factor_lifecycle_monitor.py once per test module."""
    project_root = Path(__file__).resolve().parents[2]
    backend_dir = project_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.append(str(backend_dir))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    spec = importlib.util.spec_from_file_location("flm_under_test", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ─── _generate_replay_fridays (5 tests) ───────────────────────────────


def test_generate_replay_fridays_starts_on_friday(flm):
    """2026-01-02 是 Friday, 起始即 first Friday."""
    fridays = flm._generate_replay_fridays(date(2026, 1, 2), 3)
    assert fridays == [date(2026, 1, 2), date(2026, 1, 9), date(2026, 1, 16)]


def test_generate_replay_fridays_advances_to_next_friday(flm):
    """2026-01-01 (Thursday) → advances to 2026-01-02 (Friday)."""
    fridays = flm._generate_replay_fridays(date(2026, 1, 1), 2)
    assert fridays == [date(2026, 1, 2), date(2026, 1, 9)]


def test_generate_replay_fridays_clamped_to_today(flm):
    """weeks=200 远超 today → clamped 到 today 之前的最后 Friday."""
    fridays = flm._generate_replay_fridays(date(2026, 1, 2), 200)
    # 2026-01-02 ~ today 范围内的 Fridays, 最后一个 <= today
    today = date.today()
    assert all(f <= today for f in fridays)
    assert all(f.weekday() == 4 for f in fridays)
    assert len(fridays) >= 1
    assert fridays[0] == date(2026, 1, 2)


def test_generate_replay_fridays_weeks_zero_raises(flm):
    with pytest.raises(ValueError, match="weeks 必须 > 0"):
        flm._generate_replay_fridays(date(2026, 1, 2), 0)


def test_generate_replay_fridays_weeks_negative_raises(flm):
    with pytest.raises(ValueError, match="weeks 必须 > 0"):
        flm._generate_replay_fridays(date(2026, 1, 2), -1)


# ─── _replay_one_factor (3 tests) ───────────────────────────────────


def _mock_conn_with_queries(tail_rows=None, ic_series_rows=None, factor_meta_row=None):
    """Build mock conn that returns specified rows for tail / ic_series / meta queries.

    tail_rows: list[(trade_date, ic_ma20, ic_ma60)] or [] for empty.
    ic_series_rows: list[(trade_date, ic_20d)] or [] for empty.
    factor_meta_row: tuple matching SELECT columns or None.
    """
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    # Each fetchall/fetchone call sequentially returns from queue
    fetchall_queue = [tail_rows or [], ic_series_rows or []]
    fetchall_idx = [0]

    def _fetchall():
        if fetchall_idx[0] >= len(fetchall_queue):
            return []
        result = fetchall_queue[fetchall_idx[0]]
        fetchall_idx[0] += 1
        return result

    cur.fetchall.side_effect = _fetchall
    cur.fetchone.return_value = factor_meta_row

    # cur.description for _load_ic_tail uses dict access
    # tail SQL returns columns: trade_date, ic_ma20, ic_ma60
    # factor_meta SQL returns 18 columns (id..updated_at)
    # ic_series query uses positional row[1], does not access cur.description.
    # 故 description_queue 仅含 tail / factor_meta 两个 description 访问.
    description_queue = [
        [("trade_date",), ("ic_ma20",), ("ic_ma60",)],  # tail
        [
            ("id",), ("name",), ("category",), ("direction",), ("expression",),
            ("code_content",), ("hypothesis",), ("source",), ("lookback_days",),
            ("status",), ("pool",), ("gate_ic",), ("gate_ir",), ("gate_mono",),
            ("gate_t",), ("ic_decay_ratio",), ("created_at",), ("updated_at",),
        ],  # factor_meta
    ]
    desc_idx = [0]

    def _description():
        if desc_idx[0] >= len(description_queue):
            return None
        result = description_queue[desc_idx[0]]
        desc_idx[0] += 1
        return result

    type(cur).description = property(lambda _: _description())
    return conn


def test_replay_one_factor_returns_none_when_tail_empty(flm):
    conn = _mock_conn_with_queries(tail_rows=[])
    result = flm._replay_one_factor(conn, "test_factor", date(2026, 4, 25))
    assert result is None


def test_replay_one_factor_returns_none_when_ic_series_too_short(flm):
    """ic_series.size < 30 → G1 跳过 → None."""
    tail = [(date(2026, 4, 24), 0.05, 0.06)]
    short_ic = [(date(2026, 4, d), 0.05) for d in range(15, 25)]  # 10 rows, < 30
    conn = _mock_conn_with_queries(tail_rows=tail, ic_series_rows=short_ic)
    result = flm._replay_one_factor(conn, "test_factor", date(2026, 4, 25))
    assert result is None


def test_replay_one_factor_returns_dict_on_happy_path(flm):
    """tail + ic_series >= 30 + factor_meta → 返完整 dict."""
    # tail: 30 rows, ascending in DB but query returns DESC then reversed
    tail_db = [
        (date(2026, 4, 25) - timedelta(days=i), 0.05, 0.06)
        for i in range(30)
    ]  # DB returns DESC
    ic_series_db = [
        (date(2026, 4, 25) - timedelta(days=i), 0.05 + 0.001 * (i % 5))
        for i in range(40)
    ]
    factor_meta = (
        1, "test_factor", "momentum", 1, "expr", None, "test hypothesis 长度 ≥ 20",
        "manual", 60, "active", "CORE", 0.05, None, None, None, 0.5,
        datetime(2026, 1, 1), datetime(2026, 4, 28),
    )
    conn = _mock_conn_with_queries(
        tail_rows=tail_db, ic_series_rows=ic_series_db, factor_meta_row=factor_meta
    )
    result = flm._replay_one_factor(conn, "test_factor", date(2026, 4, 25))
    assert result is not None
    assert result["snapshot"] == "2026-04-25"
    assert result["factor"] == "test_factor"
    assert "old_label" in result
    assert "new_label" in result
    assert "consistent" in result


# ─── replay() integration (5 tests) ────────────────────────────────


def test_replay_no_data_when_no_factors(flm):
    """空 factor_registry → recommendation=NO_DATA."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = []  # no factors
    type(cur).description = property(
        lambda _: [("name",), ("status",), ("updated_at",)]
    )
    with patch.object(flm, "_get_conn", return_value=conn):
        result = flm.replay(start_date=date(2026, 4, 1), weeks=2)
    assert result["summary"]["recommendation"] == "NO_DATA"
    assert result["summary"]["total_evaluations"] == 0


def test_replay_aggregates_counters_and_writes_json(flm, tmp_path):
    """replay 全 happy path: 1 factor × 2 fridays = 2 evaluations, both consistent."""
    # Mock factors query returns 1 factor
    # Then for each (snapshot, factor) pair, _replay_one_factor runs
    # We patch _replay_one_factor directly to control output deterministically
    fake_rows = [
        {
            "snapshot": "2026-04-17",
            "factor": "f1",
            "old_label": "keep",
            "new_label": "keep",
            "new_decision_value": "accept",
            "consistent": True,
            "old_to_status": None,
            "ic_ma20": 0.05,
            "ic_ma60": 0.06,
        },
        {
            "snapshot": "2026-04-24",
            "factor": "f1",
            "old_label": "keep",
            "new_label": "keep",
            "new_decision_value": "accept",
            "consistent": True,
            "old_to_status": None,
            "ic_ma20": 0.05,
            "ic_ma60": 0.06,
        },
    ]
    iter_rows = iter(fake_rows)

    def _fake_replay_one(_conn, _name, _snap):
        try:
            return next(iter_rows)
        except StopIteration:
            return None

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [("f1", "active", datetime(2026, 4, 1))]
    type(cur).description = property(
        lambda _: [("name",), ("status",), ("updated_at",)]
    )

    report_path = tmp_path / "replay.json"
    with patch.object(flm, "_get_conn", return_value=conn), \
         patch.object(flm, "_replay_one_factor", side_effect=_fake_replay_one):
        # Use start in past with weeks=2 to get 2 fridays, both <= today
        result = flm.replay(
            start_date=date(2026, 4, 17),  # 2026-04-17 is Friday
            weeks=2,
            report_out=str(report_path),
        )
    summary = result["summary"]
    assert summary["total_evaluations"] == 2
    assert summary["consistent_count"] == 2
    assert summary["mismatch_count"] == 0
    assert summary["mismatch_rate"] == 0.0
    assert summary["recommendation"] == "SUNSET"
    assert summary["by_label_matrix"]["keep_keep"] == 2

    # JSON report 写入
    assert report_path.exists()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["summary"]["recommendation"] == "SUNSET"
    assert len(persisted["details"]) == 2


def test_replay_defer_when_p1_reverse_mismatch_present(flm):
    """1 P1 reverse mismatch (老 demote / 新 keep) → DEFER (老路径捕获 decay)."""
    fake_rows = [
        {
            "snapshot": "2026-04-17",
            "factor": "f1",
            "old_label": "demote",
            "new_label": "keep",
            "new_decision_value": "accept",
            "consistent": False,
            "old_to_status": "warning",
            "ic_ma20": 0.04,
            "ic_ma60": 0.06,
        },
        {
            "snapshot": "2026-04-24",
            "factor": "f1",
            "old_label": "keep",
            "new_label": "keep",
            "new_decision_value": "accept",
            "consistent": True,
            "old_to_status": None,
            "ic_ma20": 0.05,
            "ic_ma60": 0.06,
        },
    ]
    iter_rows = iter(fake_rows)

    def _fake_replay_one(_conn, _name, _snap):
        try:
            return next(iter_rows)
        except StopIteration:
            return None

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [("f1", "active", datetime(2026, 4, 1))]
    type(cur).description = property(
        lambda _: [("name",), ("status",), ("updated_at",)]
    )

    with patch.object(flm, "_get_conn", return_value=conn), \
         patch.object(flm, "_replay_one_factor", side_effect=_fake_replay_one):
        result = flm.replay(start_date=date(2026, 4, 17), weeks=2)

    summary = result["summary"]
    assert summary["mismatch_count"] == 1
    assert summary["p1_reverse_mismatch"] == 1
    assert summary["recommendation"] == "DEFER"
    assert "P1 反向 mismatch" in summary["reasoning"]


def test_replay_defer_when_mismatch_rate_exceeds_threshold(flm):
    """mismatch_rate >= 5% AND 0 P1 reverse → DEFER (rate-only)."""
    # 9 evaluations: 1 mismatch (keep_demote, P2 forward), 8 consistent → 1/9 ≈ 11% > 5%
    fake_rows = []
    for i in range(8):
        fake_rows.append({
            "snapshot": "2026-04-17",
            "factor": f"f{i}",
            "old_label": "keep",
            "new_label": "keep",
            "new_decision_value": "accept",
            "consistent": True,
            "old_to_status": None,
            "ic_ma20": 0.05, "ic_ma60": 0.06,
        })
    fake_rows.append({
        "snapshot": "2026-04-17",
        "factor": "f8",
        "old_label": "keep",
        "new_label": "demote",
        "new_decision_value": "reject",
        "consistent": False,
        "old_to_status": None,
        "ic_ma20": 0.05, "ic_ma60": 0.06,
    })
    iter_rows = iter(fake_rows)

    def _fake_replay_one(_conn, _name, _snap):
        try:
            return next(iter_rows)
        except StopIteration:
            return None

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [
        (f"f{i}", "active", datetime(2026, 4, 1)) for i in range(9)
    ]
    type(cur).description = property(
        lambda _: [("name",), ("status",), ("updated_at",)]
    )

    with patch.object(flm, "_get_conn", return_value=conn), \
         patch.object(flm, "_replay_one_factor", side_effect=_fake_replay_one):
        result = flm.replay(start_date=date(2026, 4, 17), weeks=1)

    summary = result["summary"]
    assert summary["mismatch_rate"] > 0.05
    assert summary["p1_reverse_mismatch"] == 0
    assert summary["recommendation"] == "DEFER"


def test_replay_skips_factors_with_no_data(flm):
    """_replay_one_factor 返 None → skipped_no_data 累计, 不影响 mismatch_rate 分母."""
    iter_returns = iter([None, None])

    def _fake_replay_one(_conn, _name, _snap):
        try:
            return next(iter_returns)
        except StopIteration:
            return None

    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [("f1", "active", datetime(2026, 4, 1))]
    type(cur).description = property(
        lambda _: [("name",), ("status",), ("updated_at",)]
    )

    with patch.object(flm, "_get_conn", return_value=conn), \
         patch.object(flm, "_replay_one_factor", side_effect=_fake_replay_one):
        result = flm.replay(start_date=date(2026, 4, 17), weeks=2)

    summary = result["summary"]
    assert summary["total_evaluations"] == 0
    assert summary["skipped_no_data"] == 2
    assert summary["recommendation"] == "NO_DATA"


# ─── snapshot_date filter on _load_ic_tail / _load_ic_series ───────


def test_load_ic_tail_with_snapshot_uses_filter(flm):
    """snapshot_date 设置时 SQL 含 trade_date <= %s."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = []
    type(cur).description = property(
        lambda _: [("trade_date",), ("ic_ma20",), ("ic_ma60",)]
    )

    flm._load_ic_tail(conn, "f1", 30, snapshot_date=date(2026, 4, 25))

    sql_call = str(cur.execute.call_args[0][0])
    params = cur.execute.call_args[0][1]
    assert "trade_date <= %s" in sql_call
    assert params == ("f1", date(2026, 4, 25), 30)


def test_load_ic_tail_without_snapshot_omits_filter(flm):
    """snapshot_date=None 走原 SQL 路径 (生产 Beat 行为不变)."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = []
    type(cur).description = property(
        lambda _: [("trade_date",), ("ic_ma20",), ("ic_ma60",)]
    )

    flm._load_ic_tail(conn, "f1", 30)

    sql_call = str(cur.execute.call_args[0][0])
    params = cur.execute.call_args[0][1]
    assert "trade_date <=" not in sql_call
    assert params == ("f1", 30)


def test_load_ic_series_with_snapshot_returns_array(flm):
    """ic_series snapshot 路径返 ndarray."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    cur.fetchall.return_value = [
        (date(2026, 4, 25), 0.05),
        (date(2026, 4, 24), 0.04),
    ]

    result = flm._load_ic_series(conn, "f1", 60, snapshot_date=date(2026, 4, 25))

    assert isinstance(result, np.ndarray)
    assert result.shape == (2,)
    # rows 倒序输入, ascending 输出 → [0.04, 0.05]
    assert result[0] == pytest.approx(0.04)
    assert result[1] == pytest.approx(0.05)
