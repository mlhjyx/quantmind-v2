"""MVP 3.5 Follow-up B Phase 2 — factor_lifecycle_monitor.run() composite_mode wire-up.

Session 43 (2026-04-28). 验证 run() 主路径 composite_mode 接 wire-up 正确,
默认 g1-only 立即生效 (无观察期, 来源用户 Session 42-43 反复明确).

覆盖:
  - run() composite_mode=OFF: 仅老路径 (regression, Phase 1 兼容)
  - run() composite_mode=G1_ONLY: 老 None + G1 fail → 合成 demote 入 transitions + composite_synthesized
  - run() composite_mode=G1_ONLY: 老 demote + G1 fail → 透传老 (composite_synthesized 空)
  - result dict 含 composite_mode + composite_synthesized 字段
  - main() CLI 默认 composite-mode=g1-only (backward-compat 防破)
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "factor_lifecycle_monitor.py"


@pytest.fixture(scope="module")
def flm():
    project_root = Path(__file__).resolve().parents[2]
    backend_dir = project_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.append(str(backend_dir))
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    spec = importlib.util.spec_from_file_location("flm_run_composite", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mk_conn(factor_rows: list, tail_rows: list):
    """Mock conn returning factor_registry rows + ic_tail rows."""
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn.closed = 0

    fetchall_queue = [factor_rows, tail_rows]
    fetchall_idx = [0]

    def _fetchall():
        if fetchall_idx[0] >= len(fetchall_queue):
            return []
        result = fetchall_queue[fetchall_idx[0]]
        fetchall_idx[0] += 1
        return result

    cur.fetchall.side_effect = _fetchall
    cur.fetchone.return_value = None  # SELECT FOR UPDATE / etc.

    description_queue = [
        [("name",), ("status",), ("updated_at",)],
        [("trade_date",), ("ic_ma20",), ("ic_ma60",)],
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


def _mk_report(failed_gates: list[str]):
    all_gates = ["G1_ic_significance", "G10_hypothesis"]
    results = [
        SimpleNamespace(gate_name=g, passed=(g not in failed_gates))
        for g in all_gates
    ]
    return SimpleNamespace(
        gate_results=results,
        decision=SimpleNamespace(value=("reject" if failed_gates else "accept")),
    )


# ─── run() composite_mode 行为矩阵 (4 tests) ────────────────────────


def test_run_composite_off_skips_pipeline_evaluation(flm):
    """OFF mode: 不调 _evaluate_pipeline_report (生产兼容, Phase 1 行为)."""
    factor_rows = [("f1", "active", datetime(2026, 4, 1))]
    # tail: ratio ~ 1.0 → 老路径无 transition
    tail_rows = [
        (date(2026, 4, 25), 0.06, 0.06),
        (date(2026, 4, 24), 0.06, 0.06),
    ]
    conn = _mk_conn(factor_rows, tail_rows)

    with patch.object(flm, "_get_conn", return_value=conn), \
         patch.object(flm, "_evaluate_pipeline_report") as eval_mock, \
         patch.object(flm, "_publish_event"):
        result = flm.run(
            dry_run=True,
            factor_filter="f1",
            composite_mode=flm.CompositeMode.OFF,
        )

    eval_mock.assert_not_called()  # OFF 不跑 pipeline
    assert result["composite_mode"] == "off"
    assert result["composite_synthesized"] == []
    assert result["transitions"] == []  # 老路径 ratio=1.0 也无 transition


def test_run_composite_g1_only_synthesizes_demote_when_g1_fails(flm):
    """G1_ONLY: 老路径 keep (ratio 高) + G1 fail → 合成 active→warning."""
    factor_rows = [("f1", "active", datetime(2026, 4, 1))]
    tail_rows = [
        (date(2026, 4, 25), 0.06, 0.06),  # ratio=1.0 老路径 keep
    ]
    conn = _mk_conn(factor_rows, tail_rows)

    with patch.object(flm, "_get_conn", return_value=conn), \
         patch.object(
             flm, "_evaluate_pipeline_report",
             return_value=_mk_report(["G1_ic_significance"]),
         ), \
         patch.object(flm, "_publish_event"):
        result = flm.run(
            dry_run=True,
            factor_filter="f1",
            composite_mode=flm.CompositeMode.G1_ONLY,
        )

    assert result["composite_mode"] == "g1-only"
    assert len(result["composite_synthesized"]) == 1
    syn = result["composite_synthesized"][0]
    assert syn["factor"] == "f1"
    assert syn["from"] == "active"
    assert syn["to"] == "warning"
    assert "G1_ic_significance" in syn["reason"]
    # Transitions 也应包含合成
    assert len(result["transitions"]) == 1


def test_run_composite_g1_only_preserves_old_demote(flm):
    """G1_ONLY: 老路径已 demote (ratio < 0.8) → 透传老 (不计入 composite_synthesized)."""
    factor_rows = [("f1", "active", datetime(2026, 4, 1))]
    tail_rows = [
        (date(2026, 4, 25), 0.04, 0.06),  # ratio=0.667 老路径 demote
    ]
    conn = _mk_conn(factor_rows, tail_rows)

    with patch.object(flm, "_get_conn", return_value=conn), \
         patch.object(
             flm, "_evaluate_pipeline_report",
             return_value=_mk_report(["G1_ic_significance"]),
         ), \
         patch.object(flm, "_publish_event"):
        result = flm.run(
            dry_run=True,
            factor_filter="f1",
            composite_mode=flm.CompositeMode.G1_ONLY,
        )

    # 老路径触发 demote (含真 ic_ma 数据), 不被合成 reason 覆盖
    assert len(result["transitions"]) == 1
    assert result["transitions"][0]["reason"].startswith("|IC_MA20|/|IC_MA60|=")
    # composite_synthesized 空 (老 demote 优先权, 不算 synthesized)
    assert result["composite_synthesized"] == []


def test_run_composite_g1_only_default_when_unspecified(flm):
    """run() 默认 composite_mode=G1_ONLY (Phase 2 立即生效, 无观察期)."""
    factor_rows = [("f1", "active", datetime(2026, 4, 1))]
    tail_rows = [(date(2026, 4, 25), 0.06, 0.06)]
    conn = _mk_conn(factor_rows, tail_rows)

    with patch.object(flm, "_get_conn", return_value=conn), \
         patch.object(
             flm, "_evaluate_pipeline_report",
             return_value=_mk_report([]),  # 全 pass
         ), \
         patch.object(flm, "_publish_event"):
        # 不传 composite_mode, 期望默认 g1-only
        result = flm.run(dry_run=True, factor_filter="f1")

    assert result["composite_mode"] == "g1-only"


# ─── result dict schema (1 test) ───────────────────────────────────


def test_run_result_includes_composite_fields(flm):
    """result dict 含 composite_mode (字符串) + composite_synthesized (list)."""
    factor_rows = []  # 0 因子, 走 happy path
    tail_rows = []
    conn = _mk_conn(factor_rows, tail_rows)

    with patch.object(flm, "_get_conn", return_value=conn):
        result = flm.run(
            dry_run=True,
            composite_mode=flm.CompositeMode.STRICT,
        )

    assert "composite_mode" in result
    assert result["composite_mode"] == "strict"
    assert "composite_synthesized" in result
    assert result["composite_synthesized"] == []
