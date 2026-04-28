"""MVP 3.5.1 — DBStrategyRegistry update_status(LIVE) 强制 evaluation_required 真启动 smoke (铁律 10b).

subprocess 真启动验证:
  - DBStrategyRegistry + EvaluationRequired + record_evaluation 可 import
  - DEFAULT_LIVE_EVAL_FRESHNESS_DAYS 常量 == 30
  - update_status(LIVE) 无 prior evaluation 抛 EvaluationRequired
  - update_status(LIVE) 失败 verdict 抛 EvaluationRequired
  - update_status(LIVE) stale (>30d) 抛 EvaluationRequired
  - update_status(LIVE) fresh+passed 越过守门 (走主流程)
  - record_evaluation 接受 Verdict
  - migration SQL 静态 marker (表定义 + 索引 + ON DELETE RESTRICT)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


_SMOKE_TEMPLATE = '''
import platform as _stdlib_platform
_stdlib_platform.python_implementation()
import sys
sys.path.insert(0, r"{backend_path}")
sys.path.insert(0, r"{project_root}")
from qm_platform.strategy import (
    DBStrategyRegistry,
    EvaluationRequired,
    StrategyStatus,
    DEFAULT_LIVE_EVAL_FRESHNESS_DAYS,
)
from qm_platform._types import Verdict
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4
from pathlib import Path

# 常量 marker (设计 invariant)
assert DEFAULT_LIVE_EVAL_FRESHNESS_DAYS == 30, (
    f"expected 30, got {{DEFAULT_LIVE_EVAL_FRESHNESS_DAYS}}"
)
assert callable(DBStrategyRegistry)
assert issubclass(EvaluationRequired, RuntimeError)


def _mk(fetchone_queue):
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value = cur
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)
    conn.closed = 0
    it = iter(fetchone_queue)
    cur.fetchone.side_effect = lambda: next(it, None)
    factory = lambda: conn  # noqa: E731
    factory._cursor = cur
    return factory


now = datetime.now(timezone.utc)

# 场景 1: 无 prior evaluation → raise
sid1 = uuid4()
reg1 = DBStrategyRegistry(conn_factory=_mk([("draft",), None]))
try:
    reg1.update_status(str(sid1), StrategyStatus.LIVE, reason="promote")
except EvaluationRequired as e:
    assert "无 strategy_evaluations" in str(e), str(e)
else:
    raise AssertionError("expected EvaluationRequired without prior eval")

# 场景 2: failed verdict → raise
sid2 = uuid4()
reg2 = DBStrategyRegistry(
    conn_factory=_mk([("draft",), (False, ["G1prime"], now)])
)
try:
    reg2.update_status(str(sid2), StrategyStatus.LIVE, reason="promote")
except EvaluationRequired as e:
    assert "blockers" in str(e), str(e)
else:
    raise AssertionError("expected EvaluationRequired on failed verdict")

# 场景 3: stale (>30d) → raise
sid3 = uuid4()
stale = now - timedelta(days=45)
reg3 = DBStrategyRegistry(conn_factory=_mk([("draft",), (True, [], stale)]))
try:
    reg3.update_status(str(sid3), StrategyStatus.LIVE, reason="promote")
except EvaluationRequired as e:
    assert "过期" in str(e), str(e)
else:
    raise AssertionError("expected EvaluationRequired on stale verdict")

# 场景 4: fresh + passed 越过守门 + 主流程 UPDATE + INSERT log 全跑通
sid4 = uuid4()
factory4 = _mk([("draft",), (True, [], now)])
reg4 = DBStrategyRegistry(conn_factory=factory4)
reg4.update_status(str(sid4), StrategyStatus.LIVE, reason="promote")
# 验 4 SQL: SELECT status / SELECT eval / UPDATE registry / INSERT status_log
calls4 = [str(c.args[0]) for c in factory4._cursor.execute.call_args_list]
assert len(calls4) == 4, f"expected 4 SQL execs, got {{len(calls4)}}: {{calls4}}"
assert "SELECT status FROM strategy_registry" in calls4[0]
assert "FROM strategy_evaluations" in calls4[1]
assert "UPDATE strategy_registry" in calls4[2]
assert "INSERT INTO strategy_status_log" in calls4[3]

# 场景 5: record_evaluation 执行 INSERT
sid5 = uuid4()
factory5 = _mk([])
reg5 = DBStrategyRegistry(conn_factory=factory5)
v = Verdict(
    subject=str(sid5), passed=True, p_value=0.01, blockers=[], details={{"g": "G1"}}
)
reg5.record_evaluation(v)
assert factory5._cursor.execute.called, "record_evaluation 应执行 INSERT"

# migration SQL marker
mig = Path(r"{backend_path}") / "migrations" / "strategy_evaluations.sql"
assert mig.exists(), "migration 文件缺失"
mig_src = mig.read_text(encoding="utf-8")
assert "CREATE TABLE IF NOT EXISTS strategy_evaluations" in mig_src
assert "idx_strategy_evaluations_strategy_latest" in mig_src
assert "ON DELETE RESTRICT" in mig_src
rb = Path(r"{backend_path}") / "migrations" / "strategy_evaluations_rollback.sql"
assert rb.exists(), "rollback 文件缺失"

# 源码 marker
reg_src = (
    Path(r"{backend_path}") / "qm_platform" / "strategy" / "registry.py"
).read_text(encoding="utf-8")
assert "class EvaluationRequired" in reg_src
assert "def record_evaluation" in reg_src
assert "_assert_eval_passed_for_live" in reg_src
assert "DEFAULT_LIVE_EVAL_FRESHNESS_DAYS" in reg_src

print("MVP_3_5_1_SMOKE_OK")
'''


def _build_smoke_code() -> str:
    backend_path = str(PROJECT_ROOT / "backend")
    project_root = str(PROJECT_ROOT)
    return _SMOKE_TEMPLATE.format(
        backend_path=backend_path, project_root=project_root
    )


@pytest.mark.smoke
def test_mvp_3_5_1_subprocess_evaluation_required():
    """subprocess 真启动 5 场景守门 + migration + 源码 marker (铁律 10b)."""
    code = _build_smoke_code()
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"smoke subprocess failed: returncode={result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "MVP_3_5_1_SMOKE_OK" in result.stdout, (
        f"missing success marker, stdout={result.stdout}"
    )
