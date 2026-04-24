"""audit_orphan_factors.py 回归测试 (Session 27 Task B).

Orphan = factor_registry.name 不在 SELECT DISTINCT factor_name FROM factor_values.
纯函数 + mock DB, 不接触真实数据库.

覆盖:
- find_orphans set-diff 逻辑 (orphan / 非 orphan / only_active filter)
- main() 返回值契约 (0 normal, 1 strict+orphans, 2 FATAL)

同时 re-verify:
- backfill_factor_registry._POOL_DEPRECATED 含 Session 27 新加 11 因子名
- backfill_factor_registry._HARDCODED_DIRECTIONS 已删 mf_momentum_divergence +
  earnings_surprise_car (防 backfill revert migration 后的 status/pool)
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
AUDIT_DIR = SCRIPTS_DIR / "audit"
REGISTRY_DIR = SCRIPTS_DIR / "registry"
for d in (AUDIT_DIR, REGISTRY_DIR):
    if str(d) not in sys.path:
        sys.path.insert(0, str(d))

import audit_orphan_factors as aof  # noqa: E402
import backfill_factor_registry as bfr  # noqa: E402


def _make_conn(factor_values_names: list[str], registry_rows: list[tuple]) -> MagicMock:
    """Build a mock psycopg2 conn emulating 2 queries in find_orphans.

    Sequence:
      1. SELECT DISTINCT factor_name FROM factor_values → list of (name,) tuples
      2. SELECT name, status, pool, direction, category, updated_at FROM factor_registry
         → registry_rows tuples
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    # execute sets up fetchall for the subsequent fetch call
    mock_cursor.fetchall.side_effect = [
        [(n,) for n in factor_values_names],
        registry_rows,
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
    mock_conn.cursor.return_value.__exit__.return_value = False
    return mock_conn


class TestFindOrphans:
    """find_orphans 核心 set-diff 契约."""

    def test_returns_empty_when_all_aligned(self):
        """registry 和 factor_values 完全对齐 → 0 orphan."""
        fv_names = ["bp_ratio", "dv_ttm"]
        reg_rows = [
            ("bp_ratio", "active", "CORE", 1, "fundamental", date(2026, 1, 1)),
            ("dv_ttm", "active", "CORE", 1, "fundamental", date(2026, 1, 1)),
        ]
        conn = _make_conn(fv_names, reg_rows)

        orphans = aof.find_orphans(conn)

        assert orphans == []

    def test_identifies_orphan_registry_names(self):
        """registry 有 / factor_values 无 → orphan."""
        fv_names = ["bp_ratio"]  # dv_ttm 缺
        reg_rows = [
            ("bp_ratio", "active", "CORE", 1, "fundamental", date(2026, 1, 1)),
            ("dv_ttm", "warning", "PASS", 1, "fundamental", date(2026, 1, 1)),
        ]
        conn = _make_conn(fv_names, reg_rows)

        orphans = aof.find_orphans(conn)

        assert len(orphans) == 1
        assert orphans[0]["name"] == "dv_ttm"
        assert orphans[0]["status"] == "warning"
        assert orphans[0]["pool"] == "PASS"

    def test_ignores_factor_values_only_names(self):
        """factor_values 有 / registry 无 → 不算 orphan (另一方向 drift, 本 audit 不查)."""
        fv_names = ["bp_ratio", "rogue_factor_only_in_fv"]
        reg_rows = [
            ("bp_ratio", "active", "CORE", 1, "fundamental", date(2026, 1, 1)),
        ]
        conn = _make_conn(fv_names, reg_rows)

        orphans = aof.find_orphans(conn)

        assert orphans == []  # 反向 drift 不报 orphan

    def test_only_active_emits_where_status_in_sql(self):
        """only_active=True 必须 emit `WHERE status IN` SQL 分支 (非 Python-side filter).

        Reviewer P2 (code + python) 采纳: 原 test 只验 result, 不验 SQL 路径. 若有人
        删 find_orphans 里 `if only_active` 分支改成 Python-side filter, mock 返同样
        结果 test 仍绿, 隐性回归. 本 test 断言 cur.execute 第二次调用的 SQL 字符串
        真含 WHERE status IN — 防御 SQL-path regression.
        """
        fv_names = ["bp_ratio"]
        reg_rows = [
            ("bp_ratio", "active", "CORE", 1, "fundamental", date(2026, 1, 1)),
            ("some_warning", "warning", "PASS", 1, "fundamental", date(2026, 1, 1)),
        ]
        conn = _make_conn(fv_names, reg_rows)

        orphans = aof.find_orphans(conn, only_active=True)

        # 结果契约
        assert len(orphans) == 1
        assert orphans[0]["name"] == "some_warning"

        # SQL 路径契约 (reviewer 采纳强化项)
        mock_cursor = conn.cursor.return_value.__enter__.return_value
        execute_calls = mock_cursor.execute.call_args_list
        assert len(execute_calls) == 2, "期望 2 次 SQL (distinct fv + registry)"
        second_sql = execute_calls[1][0][0]  # call_args[0][0] = first positional = sql string
        assert "WHERE status IN ('active', 'warning')" in second_sql, (
            f"only_active=True 未 emit WHERE 过滤, 实际 SQL: {second_sql!r}"
        )

    def test_only_active_false_omits_where_clause(self):
        """only_active=False (default) 不应 emit WHERE status IN — 全表 registry."""
        fv_names = ["bp_ratio"]
        reg_rows = [
            ("bp_ratio", "active", "CORE", 1, "fundamental", date(2026, 1, 1)),
            ("some_deprecated", "deprecated", "DEPRECATED", 1, "fundamental", date(2026, 1, 1)),
        ]
        conn = _make_conn(fv_names, reg_rows)

        orphans = aof.find_orphans(conn, only_active=False)

        assert len(orphans) == 1
        assert orphans[0]["name"] == "some_deprecated"

        mock_cursor = conn.cursor.return_value.__enter__.return_value
        execute_calls = mock_cursor.execute.call_args_list
        second_sql = execute_calls[1][0][0]
        assert "WHERE status IN" not in second_sql, (
            f"only_active=False 误 emit WHERE, 实际 SQL: {second_sql!r}"
        )


class TestMainExitCodes:
    """main() 返回值契约 (CI gate dependency)."""

    def test_main_exit_0_when_no_orphans(self, monkeypatch):
        monkeypatch.setattr(aof, "_get_conn", lambda: MagicMock())
        monkeypatch.setattr(aof, "find_orphans", lambda conn, only_active=False: [])
        monkeypatch.setattr(sys, "argv", ["audit_orphan_factors.py"])

        assert aof.main() == 0

    def test_main_exit_1_on_strict_with_orphans(self, monkeypatch, capsys):
        monkeypatch.setattr(aof, "_get_conn", lambda: MagicMock())
        fake_orphan = {
            "name": "ghost",
            "status": "warning",
            "pool": "PASS",
            "direction": 1,
            "category": "fundamental",
            "updated_at": date(2026, 1, 1),
        }
        monkeypatch.setattr(
            aof, "find_orphans", lambda conn, only_active=False: [fake_orphan]
        )
        monkeypatch.setattr(sys, "argv", ["audit_orphan_factors.py", "--strict"])

        rc = aof.main()

        assert rc == 1
        captured = capsys.readouterr()
        assert "STRICT fail" in captured.err

    def test_main_exit_0_strict_no_orphans(self, monkeypatch):
        """--strict 与 0 orphan → 仍 0."""
        monkeypatch.setattr(aof, "_get_conn", lambda: MagicMock())
        monkeypatch.setattr(aof, "find_orphans", lambda conn, only_active=False: [])
        monkeypatch.setattr(sys, "argv", ["audit_orphan_factors.py", "--strict"])

        assert aof.main() == 0

    def test_main_exit_2_on_fatal_exception(self, monkeypatch, capsys):
        """_get_conn raise → main 捕 + stderr FATAL + exit 2."""
        def _boom():
            raise RuntimeError("DB unreachable")

        monkeypatch.setattr(aof, "_get_conn", _boom)
        monkeypatch.setattr(sys, "argv", ["audit_orphan_factors.py"])

        rc = aof.main()

        assert rc == 2
        captured = capsys.readouterr()
        assert "FATAL" in captured.err
        assert "RuntimeError" in captured.err
        # Reviewer P1 (python) 采纳: FATAL 必须含完整 traceback 便于 CI/ad-hoc 调试
        assert "Traceback" in captured.err, (
            f"FATAL 输出缺 traceback (reviewer P1 contract): {captured.err[:200]}"
        )


class TestBackfillRevertProtection:
    """Session 27 Task B 核心契约: backfill 重跑不能 revert migration 的 status/pool.

    防护机制: _POOL_DEPRECATED 显式含 11 清理因子 + _SIGNAL_ENGINE_DIRECTION 删 2 条.
    """

    _SESSION27_DEPRECATED = frozenset({
        "mf_momentum_divergence",
        "earnings_surprise_car",
        "pead_q1",
        "eps_acceleration",
        "gross_margin_delta",
        "net_margin_delta",
        "revenue_growth_yoy",
        "roe_delta",
        "debt_change",
        "days_since_announcement",
        "reporting_season_flag",
    })

    def test_pool_deprecated_contains_all_session27_names(self):
        """_POOL_DEPRECATED 必含 11 个 Session 27 清理因子, 否则 backfill 会 revert."""
        missing = self._SESSION27_DEPRECATED - bfr._POOL_DEPRECATED
        assert missing == set(), f"_POOL_DEPRECATED 缺少 Session 27 清理因子: {missing}"

    def test_signal_engine_direction_removed_2_entries(self):
        """_SIGNAL_ENGINE_DIRECTION 已删 mf_momentum_divergence + earnings_surprise_car.

        这 2 个若仍在, backfill Layer 2 merge 会 INSERT/UPDATE 它们, 违反清理意图.
        (对齐 backfill_factor_registry.py:42 实际变量名 _SIGNAL_ENGINE_DIRECTION.)
        """
        assert "mf_momentum_divergence" not in bfr._SIGNAL_ENGINE_DIRECTION
        assert "earnings_surprise_car" not in bfr._SIGNAL_ENGINE_DIRECTION

    def test_infer_pool_deprecates_all_session27_names(self):
        """_infer_pool(name, has_hc=True) 对 11 清理因子必返 DEPRECATED (非 PASS).

        `has_hc=True` 因 FUNDAMENTAL_DELTA/TIME_META 为 Layer 2 提供 direction.
        """
        for name in self._SESSION27_DEPRECATED:
            pool = bfr._infer_pool(name, has_hardcoded_direction=True)
            if name == "mf_momentum_divergence":
                # INVALIDATED 优先级更高 (_POOL_INVALIDATED 先于 _POOL_DEPRECATED 检查)
                assert pool == "INVALIDATED", f"{name}: expected INVALIDATED, got {pool}"
            else:
                assert pool == "DEPRECATED", f"{name}: expected DEPRECATED, got {pool}"

    def test_infer_status_deprecates_all_session27_names(self):
        """_infer_status 对 11 清理因子必返 'deprecated' (非 'warning')."""
        for name in self._SESSION27_DEPRECATED:
            status = bfr._infer_status(name)
            assert status == "deprecated", f"{name}: expected deprecated, got {status}"
