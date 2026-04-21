"""单股急跌告警单测 (scripts/intraday_monitor.py, ADR-010 过渡期保险丝).

覆盖: _compute_stock_daily_pnl / _get_current_price / dedup mechanism /
      ALERT_EMERGENCY_STOCK 常量锁定 (防未来误改)
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(scope="module")
def intraday_monitor():
    """动态 import scripts/intraday_monitor.py (不在 pythonpath)."""
    script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "intraday_monitor.py"
    spec = importlib.util.spec_from_file_location("intraday_monitor", script_path)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as e:
        pytest.skip(f"intraday_monitor import failed: {e}")
    return module


class TestEmergencyThreshold:
    """ALERT_EMERGENCY_STOCK 常量锁定 (防未来误改)."""

    def test_threshold_is_negative_eight_percent(self, intraday_monitor):
        """ADR-010 D6 阈值锁定 -0.08."""
        assert intraday_monitor.ALERT_EMERGENCY_STOCK == -0.08


class TestComputeStockDailyPnl:
    """_compute_stock_daily_pnl 边界 + 异常."""

    def test_normal_case_down_10pct(self, intraday_monitor):
        """current=90, prev=100 → pnl=-0.10."""
        with patch.object(intraday_monitor, "_get_current_price", return_value=90.0), \
             patch.object(intraday_monitor, "_get_prev_close", return_value=100.0):
            result = intraday_monitor._compute_stock_daily_pnl("600000.SH")
        assert result == pytest.approx(-0.10)

    def test_boundary_exactly_minus_8pct(self, intraday_monitor):
        """边界: 恰 -8% (触发阈值)."""
        with patch.object(intraday_monitor, "_get_current_price", return_value=92.0), \
             patch.object(intraday_monitor, "_get_prev_close", return_value=100.0):
            result = intraday_monitor._compute_stock_daily_pnl("600000.SH")
        assert result == pytest.approx(-0.08)
        assert result <= intraday_monitor.ALERT_EMERGENCY_STOCK  # 触发

    def test_just_above_threshold_minus_7_99pct(self, intraday_monitor):
        """边界: -7.99% 不触发."""
        with patch.object(intraday_monitor, "_get_current_price", return_value=92.01), \
             patch.object(intraday_monitor, "_get_prev_close", return_value=100.0):
            result = intraday_monitor._compute_stock_daily_pnl("600000.SH")
        assert result > intraday_monitor.ALERT_EMERGENCY_STOCK  # 不触发

    def test_up_ignored(self, intraday_monitor):
        """涨幅不会被 emergency 规则捕获 (仅跌才告警)."""
        with patch.object(intraday_monitor, "_get_current_price", return_value=110.0), \
             patch.object(intraday_monitor, "_get_prev_close", return_value=100.0):
            result = intraday_monitor._compute_stock_daily_pnl("600000.SH")
        assert result == pytest.approx(0.10)
        assert result > intraday_monitor.ALERT_EMERGENCY_STOCK

    def test_current_missing_returns_none(self, intraday_monitor):
        """Redis current_price 缺失 → None (fail-safe)."""
        with patch.object(intraday_monitor, "_get_current_price", return_value=None):
            result = intraday_monitor._compute_stock_daily_pnl("600000.SH")
        assert result is None

    def test_prev_close_missing_returns_none(self, intraday_monitor):
        """klines_daily prev_close 缺失 → None."""
        with patch.object(intraday_monitor, "_get_current_price", return_value=95.0), \
             patch.object(intraday_monitor, "_get_prev_close", return_value=None):
            result = intraday_monitor._compute_stock_daily_pnl("600000.SH")
        assert result is None

    def test_prev_close_zero_no_zerodiv(self, intraday_monitor):
        """prev_close=0 不触 ZeroDivisionError → None."""
        with patch.object(intraday_monitor, "_get_current_price", return_value=95.0), \
             patch.object(intraday_monitor, "_get_prev_close", return_value=0.0):
            result = intraday_monitor._compute_stock_daily_pnl("600000.SH")
        assert result is None


class TestGetCurrentPrice:
    """_get_current_price Redis 读取 + JSON 字段兼容."""

    def test_price_field_v2(self, intraday_monitor):
        """MVP 2.1c Sub3 contract v2 用 'price' 字段."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps({"price": 12.5, "volume": 10000})
        with patch("redis.Redis", return_value=mock_redis):
            result = intraday_monitor._get_current_price("600000.SH")
        assert result == 12.5

    def test_last_price_fallback_v1(self, intraday_monitor):
        """旧 contract v1 用 'last_price' 字段 (向后兼容)."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps({"last_price": 13.0})
        with patch("redis.Redis", return_value=mock_redis):
            result = intraday_monitor._get_current_price("600000.SH")
        assert result == 13.0

    def test_zero_price_returns_none(self, intraday_monitor):
        """价格 0 视为异常数据 → None."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps({"price": 0})
        with patch("redis.Redis", return_value=mock_redis):
            result = intraday_monitor._get_current_price("600000.SH")
        assert result is None

    def test_key_missing_returns_none(self, intraday_monitor):
        """Redis key 不存在 → None."""
        mock_redis = MagicMock()
        mock_redis.get.return_value = None
        with patch("redis.Redis", return_value=mock_redis):
            result = intraday_monitor._get_current_price("600000.SH")
        assert result is None

    def test_redis_down_returns_none(self, intraday_monitor):
        """Redis 连接异常 → None (不抛)."""
        with patch("redis.Redis", side_effect=Exception("Redis down")):
            result = intraday_monitor._get_current_price("600000.SH")
        assert result is None


class TestBatchPrevClose:
    """_get_prev_closes_batch 批量查询 (review P1 MEDIUM 优化 验收)."""

    def test_empty_codes_returns_empty(self, intraday_monitor):
        """空 list → 空 dict (短路, 不触 DB)."""
        result = intraday_monitor._get_prev_closes_batch([])
        assert result == {}

    def test_db_failure_returns_empty(self, intraday_monitor):
        """DB 连接失败 → 空 dict (fail-safe)."""
        with patch("psycopg2.connect", side_effect=Exception("DB down")):
            result = intraday_monitor._get_prev_closes_batch(["600000.SH"])
        assert result == {}


class TestRedisReuse:
    """helpers 接受 optional r 参数 (review P1 reuse 优化 验收)."""

    def test_current_price_accepts_r_kwarg(self, intraday_monitor):
        """_get_current_price 支持传入 redis client 避免重复 new."""
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps({"price": 15.0})
        result = intraday_monitor._get_current_price("600000.SH", r=mock_r)
        assert result == 15.0
        mock_r.get.assert_called_once_with("market:latest:600000.SH")

    def test_already_alerted_accepts_r_kwarg(self, intraday_monitor):
        """_already_alerted_emergency 支持传入 redis client."""
        mock_r = MagicMock()
        mock_r.exists.return_value = 1
        result = intraday_monitor._already_alerted_emergency("600000.SH", r=mock_r)
        assert result is True
        mock_r.exists.assert_called_once()

    def test_mark_alerted_accepts_r_kwarg(self, intraday_monitor):
        """_mark_alerted_emergency 支持传入 redis client."""
        mock_r = MagicMock()
        intraday_monitor._mark_alerted_emergency("600000.SH", r=mock_r)
        mock_r.setex.assert_called_once()

    def test_compute_pnl_accepts_prev_close_kwarg(self, intraday_monitor):
        """_compute_stock_daily_pnl 支持预先 batch 查好的 prev_close, 避免 N 次 DB."""
        mock_r = MagicMock()
        mock_r.get.return_value = json.dumps({"price": 92.0})
        # prev_close 预先传入, 不应触发 _get_prev_close DB 调用
        with patch.object(intraday_monitor, "_get_prev_close") as mock_get_prev:
            result = intraday_monitor._compute_stock_daily_pnl(
                "600000.SH", r=mock_r, prev_close=100.0
            )
        assert result == pytest.approx(-0.08)
        mock_get_prev.assert_not_called()  # 关键: 未触 DB 查询


class TestDedupMechanism:
    """同股同日告警去重 (Redis 24h TTL)."""

    def test_dedup_key_format_stable(self, intraday_monitor):
        """Key format 稳定 (regression 锚点)."""
        key = intraday_monitor._emergency_dedup_key("600000.SH")
        expected = f"intraday_alerted:emergency:600000.SH:{date.today().isoformat()}"
        assert key == expected

    def test_already_alerted_returns_true(self, intraday_monitor):
        """Redis exists>0 → 已告警过 → True 跳过."""
        mock_redis = MagicMock()
        mock_redis.exists.return_value = 1
        with patch("redis.Redis", return_value=mock_redis):
            result = intraday_monitor._already_alerted_emergency("600000.SH")
        assert result is True

    def test_first_time_returns_false(self, intraday_monitor):
        """Redis 无 key → 允许告警."""
        mock_redis = MagicMock()
        mock_redis.exists.return_value = 0
        with patch("redis.Redis", return_value=mock_redis):
            result = intraday_monitor._already_alerted_emergency("600000.SH")
        assert result is False

    def test_redis_failure_fail_safe(self, intraday_monitor):
        """Redis 异常 → fail-safe 返 False (宁重复勿漏报)."""
        with patch("redis.Redis", side_effect=Exception("Redis down")):
            result = intraday_monitor._already_alerted_emergency("600000.SH")
        assert result is False

    def test_mark_alerted_sets_ttl_86400(self, intraday_monitor):
        """setex 调用 TTL=86400s + value='1'."""
        mock_redis = MagicMock()
        with patch("redis.Redis", return_value=mock_redis):
            intraday_monitor._mark_alerted_emergency("600000.SH")
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args[0]
        assert args[1] == 86400  # TTL
        assert args[2] == "1"
