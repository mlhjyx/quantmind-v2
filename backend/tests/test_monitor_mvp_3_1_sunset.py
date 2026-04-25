"""Unit tests for scripts/monitor_mvp_3_1_sunset.py (ADR-010 addendum Follow-up #5).

覆盖:
- check_condition_a: 3 维度 (days < 30 / days ≥ 30 / events = 0 / events ≥ 1)
- check_condition_b: L4 审批 + cb_recover_l0 event 2 列组合
- check_condition_c: feature_flags 表 wave_4_observability_started flag (Session 31 修正, 替原启发式)
- build_report: 聚合 3 条件 + recommendation
- should_send_dingtalk: notifications 去重
- boundary: 29.9 / 30.0 / 30.1 日边界
- JSON schema: to_dict 输出可序列化

关联铁律:
- 铁律 33 fail-loud: DB error 传播 (本 test 验 raise 不 swallow)
- 铁律 43: schtask script 4 项硬化 (statement_timeout / FileHandler / boot probe / 顶层 try/except)
"""
from __future__ import annotations

# PR-E1 (Session 36 2026-04-25) 后包名 backend/platform/ 已重命名 qm_platform/,
# 原 shadow 根因消除. 此 alias + python_implementation() probe 现仅守 hypothetical
# `scripts/platform.py` 同名文件 shadow (该 dir 由 sys.path.insert(0,...) 加在前面).
import platform as _stdlib_platform  # noqa: I001
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_stdlib_platform.python_implementation()
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from monitor_mvp_3_1_sunset import (  # noqa: E402
    ADAPTER_LIVE_DATE,
    CONDITION_A_DAYS_THRESHOLD,
    PG_STATEMENT_TIMEOUT_MS,
    ConditionResult,
    SunsetReport,
    _connect_db,
    build_report,
    check_condition_a,
    check_condition_b,
    check_condition_c,
    format_text_report,
    should_send_dingtalk,
)

# ═════════════════════════════════════════════════════════════════
# check_condition_a — days × events 2×2 matrix
# ═════════════════════════════════════════════════════════════════


class TestConditionA:
    """adapter live ≥ 30 日 + cb_* 真事件 ≥ 1."""

    def _mock_conn_with_events(self, events_count: int, latest_at=None):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (events_count, latest_at)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False
        return mock_conn

    def test_days_lt_30_events_0_not_satisfied(self):
        """Session 31 初态: 0 日 + 0 event → 未满足."""
        conn = self._mock_conn_with_events(events_count=0)
        r = check_condition_a(
            conn, today=ADAPTER_LIVE_DATE, adapter_live=ADAPTER_LIVE_DATE
        )
        assert r.satisfied is False
        assert r.details["days_elapsed"] == 0
        assert r.details["days_satisfied"] is False
        assert r.details["cb_events_count"] == 0
        assert r.details["events_satisfied"] is False
        assert r.details["days_remaining"] == CONDITION_A_DAYS_THRESHOLD

    def test_days_eq_30_events_0_not_satisfied(self):
        """30 日但 0 event → 未满足 (events 必须 ≥ 1)."""
        conn = self._mock_conn_with_events(events_count=0)
        r = check_condition_a(
            conn,
            today=date(2026, 5, 24),  # 30 日后
            adapter_live=ADAPTER_LIVE_DATE,
        )
        assert r.satisfied is False
        assert r.details["days_elapsed"] == 30
        assert r.details["days_satisfied"] is True
        assert r.details["cb_events_count"] == 0
        assert r.details["events_satisfied"] is False

    def test_days_eq_29_events_1_not_satisfied(self):
        """边界: 29 日 + 1 event → 未满足 (days 必须 ≥ 30)."""
        conn = self._mock_conn_with_events(events_count=1)
        r = check_condition_a(
            conn,
            today=date(2026, 5, 23),  # 29 日后
            adapter_live=ADAPTER_LIVE_DATE,
        )
        assert r.satisfied is False
        assert r.details["days_elapsed"] == 29
        assert r.details["days_satisfied"] is False
        assert r.details["days_remaining"] == 1
        assert r.details["events_satisfied"] is True

    def test_days_eq_30_events_1_satisfied(self):
        """边界: 刚好 30 日 + 1 event → 满足."""
        # P1 database reviewer 采纳: latest_at 用 UTC 与查询 lower_bound 对齐
        # (adapter_live CST midnight → UTC 后 4-23T16:00 UTC, 5-20T14:30 UTC 落 range 内)
        conn = self._mock_conn_with_events(
            events_count=1, latest_at=datetime(2026, 5, 20, 14, 30, tzinfo=UTC)
        )
        r = check_condition_a(
            conn,
            today=date(2026, 5, 24),
            adapter_live=ADAPTER_LIVE_DATE,
        )
        assert r.satisfied is True
        assert r.details["days_elapsed"] == 30
        assert r.details["days_satisfied"] is True
        assert r.details["cb_events_count"] == 1
        assert r.details["events_satisfied"] is True
        assert r.details["days_remaining"] == 0
        assert r.details["latest_event_at"] is not None

    def test_days_gt_30_events_multiple_satisfied(self):
        """> 30 日 + 多 events → 满足."""
        conn = self._mock_conn_with_events(events_count=5)
        r = check_condition_a(
            conn,
            today=date(2026, 6, 24),  # 61 日后
            adapter_live=ADAPTER_LIVE_DATE,
        )
        assert r.satisfied is True
        assert r.details["days_elapsed"] == 61
        assert r.details["cb_events_count"] == 5


# ═════════════════════════════════════════════════════════════════
# check_condition_b — L4 审批 × cb_recover_l0 event 2 列
# ═════════════════════════════════════════════════════════════════


class TestConditionB:
    """1 次 L4 审批完整跑通 (approved + cb_recover_l0)."""

    def _mock_conn_b(self, l4_approved: int, cb_recover: int):
        """模拟 2 次 fetchone 调用: 第 1 次 L4, 第 2 次 cb_recover."""
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [
            (l4_approved, None),
            (cb_recover, None),
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False
        return mock_conn

    def test_zero_approvals_zero_events_not_satisfied(self):
        """初态: 0 审批 + 0 event → 未满足."""
        conn = self._mock_conn_b(l4_approved=0, cb_recover=0)
        r = check_condition_b(conn)
        assert r.satisfied is False
        assert r.details["l4_approved_count"] == 0
        assert r.details["cb_recover_count"] == 0

    def test_one_approval_zero_events_not_satisfied(self):
        """L4 approved 但 cb_recover 事件未记 → 未满足 (流程未闭环)."""
        conn = self._mock_conn_b(l4_approved=1, cb_recover=0)
        r = check_condition_b(conn)
        assert r.satisfied is False

    def test_zero_approval_one_event_not_satisfied(self):
        """cb_recover 事件但 L4 审批无记录 → 未满足 (异常状态)."""
        conn = self._mock_conn_b(l4_approved=0, cb_recover=1)
        r = check_condition_b(conn)
        assert r.satisfied is False

    def test_one_approval_one_event_satisfied(self):
        """L4 approved + cb_recover_l0 event 均 ≥ 1 → 满足."""
        conn = self._mock_conn_b(l4_approved=1, cb_recover=1)
        r = check_condition_b(conn)
        assert r.satisfied is True
        assert r.details["l4_approved_count"] == 1
        assert r.details["cb_recover_count"] == 1


# ═════════════════════════════════════════════════════════════════
# check_condition_c — Wave 4 Observability feature_flag (Session 31 修正)
# ═════════════════════════════════════════════════════════════════


class TestConditionC:
    """Wave 4 Observability 启动 (feature_flags 表显式 flag, Session 31 post-dry-run 修正).

    原启发式 `/risk` endpoint 路径存在检测过宽松 (老 Wave 3 前 FastAPI risk 路由已有),
    default True 会在 A/B 未满足时 false positive 推批 3b. 改为显式 feature flag.
    """

    def _mock_conn_flag(self, flag_row):
        """模拟 feature_flags 表查询返 (enabled,) 元组 或 None (flag 不存在)."""
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = flag_row
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False
        return mock_conn

    def test_flag_not_registered_not_satisfied(self):
        """默认: flag 不存在 → 未满足 (安全默认, 防 false positive)."""
        conn = self._mock_conn_flag(flag_row=None)
        r = check_condition_c(conn)
        assert r.satisfied is False
        assert r.details["flag_exists"] is False
        assert r.details["flag_enabled"] is False

    def test_flag_registered_disabled_not_satisfied(self):
        """flag 已注册但 enabled=False → 未满足."""
        conn = self._mock_conn_flag(flag_row=(False,))
        r = check_condition_c(conn)
        assert r.satisfied is False
        assert r.details["flag_exists"] is True
        assert r.details["flag_enabled"] is False

    def test_flag_registered_enabled_satisfied(self):
        """Wave 4 MVP 4.x 启动: flag enabled=True → 满足."""
        conn = self._mock_conn_flag(flag_row=(True,))
        r = check_condition_c(conn)
        assert r.satisfied is True
        assert r.details["flag_exists"] is True
        assert r.details["flag_enabled"] is True


# ═════════════════════════════════════════════════════════════════
# build_report — 聚合 3 条件
# ═════════════════════════════════════════════════════════════════


class TestBuildReport:
    """聚合 3 条件 + recommendation."""

    def _mock_conn_all_unsatisfied(self):
        """Session 31 初态 mock: A=0日+0事件, B=0+0, C=feature_flag 不存在 → 全未满足."""
        mock_cur = MagicMock()
        # A: (events_count, latest_at)
        # B.1: (l4_approved, latest_approval)
        # B.2: (cb_recover, latest_recover)
        # C:   None (feature_flags 无 wave_4_observability_started 行, 安全默认)
        mock_cur.fetchone.side_effect = [
            (0, None),  # A events
            (0, None),  # B.1 L4 approved
            (0, None),  # B.2 cb_recover
            None,       # C feature_flag 不存在
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False
        return mock_conn

    def test_initial_state_no_conditions_satisfied(self):
        """Session 31 初态: 0 日 live + flag 未注册 → 无条件满足."""
        conn = self._mock_conn_all_unsatisfied()
        report = build_report(conn, today=ADAPTER_LIVE_DATE)
        assert report.any_satisfied is False
        assert report.days_since_activation == 0
        assert "继续观察" in report.recommendation

    def test_condition_a_satisfied_recommends_batch_3b(self):
        """条件 A 满足 → recommendation 推批 3b (B/C 仍未满足)."""
        # 手造 A 条件满足 mock: events≥1 + days≥30, B/C 未满足
        mock_cur = MagicMock()
        mock_cur.fetchone.side_effect = [
            (3, datetime(2026, 5, 20, 14, 30, tzinfo=UTC)),  # A
            (0, None),  # B.1
            (0, None),  # B.2
            None,       # C feature_flag 不存在
        ]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False

        report = build_report(mock_conn, today=date(2026, 5, 24))

        assert report.any_satisfied is True
        assert report.condition_a.satisfied is True
        assert report.condition_b.satisfied is False
        assert report.condition_c.satisfied is False
        assert "启动批 3b" in report.recommendation


# ═════════════════════════════════════════════════════════════════
# should_send_dingtalk — 钉钉去重
# ═════════════════════════════════════════════════════════════════


class TestDingtalkDedup:
    """防重复钉钉告警 (notifications 表查询去重)."""

    def _mock_conn_with_notifications_count(self, count: int):
        mock_cur = MagicMock()
        mock_cur.fetchone.return_value = (count,)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False
        return mock_conn

    def _mock_report(self, any_satisfied: bool) -> SunsetReport:
        def _cr(name: str, satisfied: bool) -> ConditionResult:
            return ConditionResult(
                name=name, description="test", satisfied=satisfied, details={}
            )

        return SunsetReport(
            generated_at=datetime.now(UTC),
            adapter_live_date=ADAPTER_LIVE_DATE,
            days_since_activation=30,
            condition_a=_cr("A", any_satisfied),
            condition_b=_cr("B", False),
            condition_c=_cr("C", False),
        )

    def test_not_send_when_no_conditions_satisfied(self):
        """无条件满足 → 无需发钉钉."""
        conn = self._mock_conn_with_notifications_count(0)
        report = self._mock_report(any_satisfied=False)
        assert should_send_dingtalk(conn, report) is False

    def test_send_when_satisfied_and_no_prior_alert(self):
        """首次条件满足 + 无历史告警 → 发."""
        conn = self._mock_conn_with_notifications_count(0)
        report = self._mock_report(any_satisfied=True)
        assert should_send_dingtalk(conn, report) is True

    def test_not_send_when_satisfied_but_already_alerted(self):
        """条件满足但已发过告警 → 去重不重发."""
        conn = self._mock_conn_with_notifications_count(1)
        report = self._mock_report(any_satisfied=True)
        assert should_send_dingtalk(conn, report) is False


# ═════════════════════════════════════════════════════════════════
# JSON schema + text format
# ═════════════════════════════════════════════════════════════════


class TestOutputFormat:
    def _make_report(self) -> SunsetReport:
        def _cr(name: str, satisfied: bool) -> ConditionResult:
            return ConditionResult(
                name=name,
                description=f"test {name}",
                satisfied=satisfied,
                details={"key": f"value_{name}"},
            )

        return SunsetReport(
            generated_at=datetime(2026, 4, 24, 21, 0, tzinfo=UTC),
            adapter_live_date=ADAPTER_LIVE_DATE,
            days_since_activation=0,
            condition_a=_cr("A", False),
            condition_b=_cr("B", False),
            condition_c=_cr("C", False),
        )

    def test_to_dict_serializable(self):
        """JSON 输出 date/datetime 转 ISO string, 可 json.dumps."""
        import json

        report = self._make_report()
        d = report.to_dict()
        # Must be JSON-serializable
        s = json.dumps(d, ensure_ascii=False)
        assert "2026-04-24T21:00:00+00:00" in s
        assert "2026-04-24" in s
        assert "any_satisfied" in d
        assert d["any_satisfied"] is False
        assert "recommendation" in d

    def test_text_report_contains_all_conditions(self):
        """human-readable 含 3 条件 + 推荐."""
        report = self._make_report()
        text = format_text_report(report)
        assert "【条件 A】" in text
        assert "【条件 B】" in text
        assert "【条件 C】" in text
        assert "继续观察" in text
        assert "⏳" in text  # 未达标记

    def test_text_report_renders_satisfied_checkmark(self):
        """P3 reviewer 采纳: 验 ✅ satisfied branch 覆盖 (原 test 全 False 漏).

        构造 A 满足 mock, 验 format_text_report 含 ✅ 符号 + "启动批 3b" 推荐.
        """

        def _cr(name: str, satisfied: bool) -> ConditionResult:
            return ConditionResult(
                name=name,
                description=f"test {name}",
                satisfied=satisfied,
                details={"test_detail": "value"},
            )

        report = SunsetReport(
            generated_at=datetime(2026, 4, 24, 21, 0, tzinfo=UTC),
            adapter_live_date=ADAPTER_LIVE_DATE,
            days_since_activation=30,
            condition_a=_cr("A", True),  # ← satisfied
            condition_b=_cr("B", False),
            condition_c=_cr("C", False),
        )
        text = format_text_report(report)
        assert "✅" in text  # satisfied 符号
        assert "⏳" in text  # 同时 B/C 未达
        assert "启动批 3b" in text  # recommendation 切换


# ═════════════════════════════════════════════════════════════════
# 铁律 33 fail-loud regression guard
# ═════════════════════════════════════════════════════════════════


class TestFailLoud:
    """铁律 33: DB error 不 silent swallow, raise 给顶层."""

    def test_check_condition_a_raises_on_db_error(self):
        """DB error 应 raise, 不 silent 返 0 (防 CB column drift 类 bug)."""
        import psycopg2.errors

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = psycopg2.errors.ConnectionException(
            "conn lost mid-query"
        )

        with pytest.raises(psycopg2.errors.ConnectionException):
            check_condition_a(mock_conn, today=date.today())

    def test_check_condition_b_raises_on_db_error(self):
        """同上, condition B 也 fail-loud."""
        import psycopg2.errors

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = psycopg2.errors.ConnectionException(
            "conn lost mid-query"
        )

        with pytest.raises(psycopg2.errors.ConnectionException):
            check_condition_b(mock_conn)

    def test_check_condition_c_raises_on_db_error(self):
        """P3 reviewer 采纳: condition C 也 fail-loud (铁律 33 规范对称).

        防 feature_flags 表查询异常 silent 返 False 伪装 "Wave 4 未启动".
        """
        import psycopg2.errors

        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = psycopg2.errors.ConnectionException(
            "feature_flags query failed"
        )

        with pytest.raises(psycopg2.errors.ConnectionException):
            check_condition_c(mock_conn)


# ═════════════════════════════════════════════════════════════════
# _connect_db — PR #73 fix regression guard (铁律 43 a)
# ═════════════════════════════════════════════════════════════════


class TestConnectDb:
    """PR #73 review (python-reviewer LOW 采纳): 防 statement_timeout 回归.

    原 _connect_db 只被 main() 间接调用, 无直接单测. PR #73 重构
    psycopg2.connect(DB_DSN) → get_sync_conn() 后若未来再次重构若漏掉
    SET statement_timeout (铁律 43 a) 会静默降级为 unlimited query 风险.
    本 test 锚定 3 不变式 (get_sync_conn 调用 / parametrized SET / commit).
    """

    def test_connect_db_sets_statement_timeout_and_commits(self, monkeypatch):
        """_connect_db 必调 get_sync_conn + parametrized SET timeout + commit."""
        mock_cur = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cur
        mock_conn.cursor.return_value.__exit__.return_value = False

        call_log = []

        def _fake_get_sync_conn():
            call_log.append("get_sync_conn")
            return mock_conn

        monkeypatch.setattr(
            "monitor_mvp_3_1_sunset.get_sync_conn", _fake_get_sync_conn
        )

        result = _connect_db()

        # 1. 走项目 SSOT get_sync_conn (不是裸 psycopg2.connect 原 landmine)
        assert call_log == ["get_sync_conn"]
        # 2. parametrized SET statement_timeout (铁律 43 a + LL-068 SQL 注入防御)
        mock_cur.execute.assert_called_once_with(
            "SET statement_timeout = %s", (PG_STATEMENT_TIMEOUT_MS,)
        )
        # 3. commit 关闭事务 (铁律 32 wiring 层管事务)
        mock_conn.commit.assert_called_once_with()
        # 4. 返回 conn instance 供 main() 用
        assert result is mock_conn


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
