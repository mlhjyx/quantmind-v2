"""开盘跳空预检单元测试。

测试 _check_opening_gap 的告警逻辑：
- 单股跳空 >5% → P1告警
- 组合跳空 >3% → P0告警
- dry-run不发通知
"""

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pandas as pd
import pytest

# 确保scripts目录可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))


def _make_price_data(
    codes_gaps: dict[str, float],
    pre_close_base: float = 10.0,
) -> pd.DataFrame:
    """创建模拟价格数据。

    Args:
        codes_gaps: {code: gap_ratio}，如 {"600519": 0.06} 表示开盘上涨6%。
        pre_close_base: pre_close基准价格。

    Returns:
        pd.DataFrame with columns: code, open, pre_close
    """
    rows = []
    for code, gap in codes_gaps.items():
        pre_close = pre_close_base
        open_price = pre_close * (1 + gap)
        rows.append({"code": code, "open": open_price, "pre_close": pre_close})
    return pd.DataFrame(rows)


class TestOpeningGapCheck:
    """_check_opening_gap 测试。"""

    def setup_method(self):
        """导入被测函数（每次测试前重新导入避免mock污染）。"""
        # 延迟导入，避免依赖整个scripts模块
        import importlib
        import run_paper_trading as rpt
        self.check_opening_gap = rpt._check_opening_gap

    def _make_conn(self, position_rows=None):
        """创建mock conn，fetchall返回持仓数据。"""
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value = cur
        if position_rows is not None:
            cur.fetchall.return_value = position_rows
        else:
            cur.fetchall.return_value = []
        return conn

    def _make_notif(self):
        """创建mock通知服务。"""
        return MagicMock()

    def test_no_large_gaps_no_alert(self):
        """无大幅跳空时不发告警。"""
        price_data = _make_price_data({
            "600519": 0.01,  # +1%，不超过5%
            "000001": -0.02,  # -2%，不超过5%
        })
        notif = self._make_notif()
        conn = self._make_conn()

        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=price_data,
            conn=conn,
            notif_svc=notif,
            dry_run=False,
        )

        notif.send_sync.assert_not_called()

    def test_single_stock_gap_over_5pct_sends_p1(self):
        """单股跳空>5%时发P1告警。"""
        price_data = _make_price_data({
            "600519": 0.06,  # +6%，超过5%阈值
            "000001": 0.01,
        })
        notif = self._make_notif()
        conn = self._make_conn()

        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=price_data,
            conn=conn,
            notif_svc=notif,
            dry_run=False,
        )

        notif.send_sync.assert_called()
        call_args = notif.send_sync.call_args
        assert call_args[0][1] == "P1"  # 第2个位置参数是level

    def test_single_stock_gap_negative_over_5pct_sends_p1(self):
        """单股跳空-6%（下跌超5%）也触发P1告警。"""
        price_data = _make_price_data({
            "000001": -0.07,  # -7%
        })
        notif = self._make_notif()
        conn = self._make_conn()

        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=price_data,
            conn=conn,
            notif_svc=notif,
            dry_run=False,
        )

        notif.send_sync.assert_called()
        call_args = notif.send_sync.call_args
        assert call_args[0][1] == "P1"

    def test_dry_run_no_notification(self):
        """dry-run模式：单股跳空>5%不发通知，只记录日志。"""
        price_data = _make_price_data({
            "600519": 0.10,  # +10%
        })
        notif = self._make_notif()
        conn = self._make_conn()

        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=price_data,
            conn=conn,
            notif_svc=notif,
            dry_run=True,  # dry-run
        )

        notif.send_sync.assert_not_called()

    def test_portfolio_gap_over_3pct_sends_p0(self):
        """组合加权跳空>3%触发P0告警。"""
        # 持仓：600519权重0.5，000001权重0.5
        # 跳空：600519 +8%，000001 +6% → 组合平均 7% > 3%
        price_data = _make_price_data({
            "600519": 0.08,
            "000001": 0.06,
            "600030": 0.01,  # 不在持仓中
        })
        notif = self._make_notif()
        # position_snapshot rows: [(code, weight), ...]
        conn = self._make_conn(position_rows=[("600519", 0.485), ("000001", 0.485)])

        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=price_data,
            conn=conn,
            notif_svc=notif,
            dry_run=False,
        )

        calls = notif.send_sync.call_args_list
        levels = [c[0][1] for c in calls]
        # 应该有P0告警（可能也有P1单股告警）
        assert "P0" in levels

    def test_portfolio_gap_under_3pct_no_p0(self):
        """组合加权跳空≤3%不触发P0告警（可能有P1）。"""
        # 600519跳空6%（触发P1），但持仓里只有小权重
        price_data = _make_price_data({
            "600519": 0.06,   # P1单股
            "000001": 0.001,  # 小跳空
            "000002": -0.001,
        })
        notif = self._make_notif()
        # 持仓中600519只有5%权重，其余权重在低跳空股票
        conn = self._make_conn(position_rows=[
            ("600519", 0.05),
            ("000001", 0.475),
            ("000002", 0.475),
        ])

        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=price_data,
            conn=conn,
            notif_svc=notif,
            dry_run=False,
        )

        calls = notif.send_sync.call_args_list
        levels = [c[0][1] for c in calls]
        assert "P0" not in levels

    def test_empty_price_data_skips_gracefully(self):
        """空价格数据时安全跳过，不报错。"""
        notif = self._make_notif()
        conn = self._make_conn()

        # 应该不抛异常
        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=pd.DataFrame(),
            conn=conn,
            notif_svc=notif,
            dry_run=False,
        )

        notif.send_sync.assert_not_called()

    def test_custom_threshold(self):
        """自定义告警阈值：单股10%才告警。"""
        price_data = _make_price_data({
            "600519": 0.08,  # +8% < 自定义阈值10%
        })
        notif = self._make_notif()
        conn = self._make_conn()

        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=price_data,
            conn=conn,
            notif_svc=notif,
            dry_run=False,
            single_stock_gap_threshold=0.10,  # 自定义阈值
        )

        # +8% < 10%，不触发P1
        notif.send_sync.assert_not_called()

    def test_p0_commits_transaction(self):
        """P0告警后应commit事务。"""
        price_data = _make_price_data({
            "600519": 0.08,
            "000001": 0.06,
        })
        notif = self._make_notif()
        conn = self._make_conn(position_rows=[("600519", 0.485), ("000001", 0.485)])

        self.check_opening_gap(
            exec_date=date(2026, 3, 24),
            price_data=price_data,
            conn=conn,
            notif_svc=notif,
            dry_run=False,
        )

        # P0发送后应commit
        conn.commit.assert_called()
