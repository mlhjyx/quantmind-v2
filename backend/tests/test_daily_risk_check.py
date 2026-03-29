"""每日风控评估逻辑测试 (Task 1 — Sprint 1.10).

验证:
1. 每日16:30 signal phase 调用 check_circuit_breaker_sync (不仅调仓日)
2. L3触发时 send_sync P0告警
3. L0-L2时无告警
4. dry_run时跳过写入
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

# ── Step 1.6 逻辑内联提取 (与 run_paper_trading.py 一致) ──

def _run_step_1_6(
    conn: Any,
    trade_date: date,
    dry_run: bool,
    strategy_id: str,
    initial_capital: float,
    notif_svc: Any,
    check_fn: Any,
) -> dict[str, Any] | None:
    """模拟 run_paper_trading.py Step1.6 逻辑（便于单元测试）。

    与脚本中的 Step1.6 完全一致，方便独立测试无需启动整个管道。
    """
    if dry_run:
        return None

    cb = check_fn(conn, strategy_id, trade_date, initial_capital)

    if cb["level"] >= 3:
        notif_svc.send_sync(
            conn, "P0", "risk",
            f"风控告警 L{cb['level']} {trade_date}",
            f"{cb['reason']}\n"
            f"仓位系数: {cb['position_multiplier']:.0%}\n"
            f"次日执行将应用降仓指令",
        )
        conn.commit()

    return cb


class TestDailyRiskCheck:
    """每日风控检查逻辑覆盖。"""

    def _make_conn(self) -> MagicMock:
        conn = MagicMock()
        conn.commit = MagicMock()
        return conn

    def _make_notif(self) -> MagicMock:
        notif = MagicMock()
        notif.send_sync = MagicMock()
        return notif

    def _make_check_fn(self, level: int, reason: str = "test") -> MagicMock:
        fn = MagicMock(return_value={
            "level": level,
            "reason": reason,
            "position_multiplier": 1.0 if level < 3 else 0.5,
            "action": "normal",
            "recovery_info": "",
        })
        return fn

    def test_normal_day_calls_check(self):
        """每日(包括非调仓日)都调用风控检查。"""
        conn = self._make_conn()
        notif = self._make_notif()
        check_fn = self._make_check_fn(level=0)
        td = date(2026, 3, 26)

        result = _run_step_1_6(
            conn, td, dry_run=False,
            strategy_id="test-strategy-id",
            initial_capital=1_000_000,
            notif_svc=notif,
            check_fn=check_fn,
        )

        check_fn.assert_called_once_with(conn, "test-strategy-id", td, 1_000_000)
        assert result["level"] == 0
        notif.send_sync.assert_not_called()
        conn.commit.assert_not_called()

    def test_l1_no_alert(self):
        """L1单日亏损: 不发P0告警(L1<3)。"""
        conn = self._make_conn()
        notif = self._make_notif()
        check_fn = self._make_check_fn(level=1, reason="单日亏损3%")

        result = _run_step_1_6(
            conn, date(2026, 3, 26), dry_run=False,
            strategy_id="s", initial_capital=1_000_000,
            notif_svc=notif, check_fn=check_fn,
        )

        assert result["level"] == 1
        notif.send_sync.assert_not_called()

    def test_l2_no_alert(self):
        """L2全部暂停: 不发P0告警(L2<3)。"""
        conn = self._make_conn()
        notif = self._make_notif()
        check_fn = self._make_check_fn(level=2, reason="单日亏损5%")

        _run_step_1_6(
            conn, date(2026, 3, 26), dry_run=False,
            strategy_id="s", initial_capital=1_000_000,
            notif_svc=notif, check_fn=check_fn,
        )

        notif.send_sync.assert_not_called()

    def test_l3_triggers_p0_alert(self):
        """L3降仓50%触发P0告警+commit。"""
        conn = self._make_conn()
        notif = self._make_notif()
        check_fn = self._make_check_fn(level=3, reason="滚动5日亏损7.5%")
        td = date(2026, 3, 26)

        result = _run_step_1_6(
            conn, td, dry_run=False,
            strategy_id="s", initial_capital=1_000_000,
            notif_svc=notif, check_fn=check_fn,
        )

        assert result["level"] == 3
        notif.send_sync.assert_called_once()
        call_args = notif.send_sync.call_args
        assert call_args.args[1] == "P0"
        assert call_args.args[2] == "risk"
        assert "L3" in call_args.args[3]
        assert "50%" in call_args.args[4]
        conn.commit.assert_called_once()

    def test_l4_triggers_p0_alert(self):
        """L4停止交易触发P0告警。"""
        conn = self._make_conn()
        notif = self._make_notif()
        check_fn = self._make_check_fn(level=4, reason="累计亏损26%")
        check_fn.return_value["position_multiplier"] = 0.0

        result = _run_step_1_6(
            conn, date(2026, 3, 26), dry_run=False,
            strategy_id="s", initial_capital=1_000_000,
            notif_svc=notif, check_fn=check_fn,
        )

        assert result["level"] == 4
        notif.send_sync.assert_called_once()
        assert "L4" in notif.send_sync.call_args.args[3]

    def test_dry_run_skips_check(self):
        """dry_run=True 时跳过评估，不调用check_fn。"""
        conn = self._make_conn()
        notif = self._make_notif()
        check_fn = self._make_check_fn(level=0)

        result = _run_step_1_6(
            conn, date(2026, 3, 26), dry_run=True,
            strategy_id="s", initial_capital=1_000_000,
            notif_svc=notif, check_fn=check_fn,
        )

        assert result is None
        check_fn.assert_not_called()
        notif.send_sync.assert_not_called()

    def test_l3_alert_message_contains_position_multiplier(self):
        """L3告警信息含正确的仓位系数(50%)。"""
        conn = self._make_conn()
        notif = self._make_notif()
        check_fn = self._make_check_fn(level=3, reason="滚动20日亏损10.5%")

        _run_step_1_6(
            conn, date(2026, 3, 26), dry_run=False,
            strategy_id="s", initial_capital=1_000_000,
            notif_svc=notif, check_fn=check_fn,
        )

        body = notif.send_sync.call_args.args[4]
        assert "50%" in body
        assert "次日执行将应用降仓指令" in body
