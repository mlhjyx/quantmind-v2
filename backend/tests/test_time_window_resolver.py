"""TimeWindowResolver 单测 — LL-076 真修复 phase 1.

测试覆盖:
    - TimeWindow value object: 不可变 + start>end raise (3 tests)
    - resolve custom 模式: --start / --end / 错误格式 (5 tests)
    - resolve lookback 模式: 正常 / zero / 负数 raise (3 tests)
    - resolve default 模式: 默认 lookback / 0 default / 负数 raise (3 tests)
    - add_args injection: 注入 3 个 CLI options (1 test)
    - _cst_today: 时区是否 Asia/Shanghai (1 test)
    - 模式优先级: --start 优先于 --lookback-days (1 test)

总 22 tests (reviewer 修复后 = 4 + 6 + 3 + 4 + 1 + 2 + 2 = 22).
6 = TestResolveCustomMode (5 原 + 1 P0 fix 验证 empty string raise).

测试不依赖 DB / Redis / network — 纯逻辑单测 (铁律 31 Engine 纯计算同方向).
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from backend.app.utils.time_window_resolver import (
    CST,
    TimeWindow,
    TimeWindowResolver,
    _cst_today,
)


def _make_args(
    start: str | None = None,
    end: str | None = None,
    lookback_days: int | None = None,
) -> argparse.Namespace:
    """构造 argparse.Namespace, 模拟用户 CLI 输入."""
    return argparse.Namespace(
        start=start,
        end=end,
        lookback_days=lookback_days,
    )


# ─────────────────────────────────────────────────────
# TimeWindow value object
# ─────────────────────────────────────────────────────


class TestTimeWindow:
    def test_window_immutable_frozen(self) -> None:
        # reviewer python-reviewer P3 采纳: 改 bare Exception → 显式 FrozenInstanceError
        # (= AttributeError 子类 since Python 3.11). 防测试 setup 异常被 silent 通过.
        from dataclasses import FrozenInstanceError

        w = TimeWindow(date(2026, 4, 1), date(2026, 4, 30), "custom")
        with pytest.raises(FrozenInstanceError):
            w.start_date = date(2026, 5, 1)  # type: ignore[misc]

    def test_window_validates_start_before_end(self) -> None:
        with pytest.raises(ValueError, match="start_date.*>.*end_date"):
            TimeWindow(date(2026, 4, 30), date(2026, 4, 1), "custom")

    def test_window_same_day_ok(self) -> None:
        w = TimeWindow(date(2026, 4, 27), date(2026, 4, 27), "default")
        assert w.days == 1  # 单日窗口 = 1 天

    def test_window_days_property(self) -> None:
        w = TimeWindow(date(2026, 4, 1), date(2026, 4, 3), "custom")
        assert w.days == 3  # 4-1, 4-2, 4-3 含两端


# ─────────────────────────────────────────────────────
# resolve - custom 模式 (--start)
# ─────────────────────────────────────────────────────


class TestResolveCustomMode:
    def test_start_only_uses_today_as_end(self) -> None:
        args = _make_args(start="20260401")
        with patch(
            "backend.app.utils.time_window_resolver._cst_today",
            return_value=date(2026, 4, 27),
        ):
            w = TimeWindowResolver.resolve(args)
        assert w.start_date == date(2026, 4, 1)
        assert w.end_date == date(2026, 4, 27)
        assert w.mode == "custom"

    def test_start_and_end_explicit(self) -> None:
        args = _make_args(start="20260401", end="20260415")
        w = TimeWindowResolver.resolve(args)
        assert w.start_date == date(2026, 4, 1)
        assert w.end_date == date(2026, 4, 15)
        assert w.mode == "custom"

    def test_invalid_start_format_raises(self) -> None:
        args = _make_args(start="not-a-date")
        with pytest.raises(ValueError, match="--start.*格式错"):
            TimeWindowResolver.resolve(args)

    def test_invalid_end_format_raises(self) -> None:
        args = _make_args(start="20260401", end="bad-format")
        with pytest.raises(ValueError, match="--end.*格式错"):
            TimeWindowResolver.resolve(args)

    def test_start_after_end_raises(self) -> None:
        args = _make_args(start="20260415", end="20260401")
        with pytest.raises(ValueError, match="start_date.*>.*end_date"):
            TimeWindowResolver.resolve(args)

    def test_empty_string_start_raises_not_silent_fallthrough(self) -> None:
        """reviewer code-reviewer P0 采纳: args.start='' 应 raise (走 fail-loud) 而非
        silent fall-through 到 lookback/default 模式 (违反铁律 33).

        修复: `if args.start:` → `if args.start is not None:`. 空字符串现在进入
        strptime 路径 → raise ValueError ('' 不是合法 YYYYMMDD).
        """
        args = _make_args(start="")
        with pytest.raises(ValueError, match="--start.*格式错"):
            TimeWindowResolver.resolve(args)


# ─────────────────────────────────────────────────────
# resolve - lookback 模式 (--lookback-days)
# ─────────────────────────────────────────────────────


class TestResolveLookbackMode:
    def test_lookback_30_days(self) -> None:
        args = _make_args(lookback_days=30)
        with patch(
            "backend.app.utils.time_window_resolver._cst_today",
            return_value=date(2026, 4, 27),
        ):
            w = TimeWindowResolver.resolve(args)
        assert w.start_date == date(2026, 3, 28)
        assert w.end_date == date(2026, 4, 27)
        assert w.mode == "lookback"

    def test_lookback_zero_today_only(self) -> None:
        args = _make_args(lookback_days=0)
        with patch(
            "backend.app.utils.time_window_resolver._cst_today",
            return_value=date(2026, 4, 27),
        ):
            w = TimeWindowResolver.resolve(args)
        assert w.start_date == w.end_date == date(2026, 4, 27)
        assert w.days == 1
        assert w.mode == "lookback"

    def test_negative_lookback_raises(self) -> None:
        args = _make_args(lookback_days=-1)
        with pytest.raises(ValueError, match="必须 >= 0"):
            TimeWindowResolver.resolve(args)


# ─────────────────────────────────────────────────────
# resolve - default 模式 (无参数)
# ─────────────────────────────────────────────────────


class TestResolveDefaultMode:
    def test_default_lookback_1(self) -> None:
        args = _make_args()
        with patch(
            "backend.app.utils.time_window_resolver._cst_today",
            return_value=date(2026, 4, 27),
        ):
            w = TimeWindowResolver.resolve(args, default_lookback=1)
        assert w.start_date == date(2026, 4, 26)
        assert w.end_date == date(2026, 4, 27)
        assert w.mode == "default"

    def test_default_lookback_30(self) -> None:
        args = _make_args()
        with patch(
            "backend.app.utils.time_window_resolver._cst_today",
            return_value=date(2026, 4, 27),
        ):
            w = TimeWindowResolver.resolve(args, default_lookback=30)
        assert w.days == 31  # 30 days back + today

    def test_default_lookback_0_today_only(self) -> None:
        args = _make_args()
        w = TimeWindowResolver.resolve(args, default_lookback=0)
        assert w.start_date == w.end_date  # today only

    def test_default_lookback_negative_raises(self) -> None:
        args = _make_args()
        with pytest.raises(ValueError, match="default_lookback.*必须 >= 0"):
            TimeWindowResolver.resolve(args, default_lookback=-1)


# ─────────────────────────────────────────────────────
# 模式优先级 (start > lookback > default)
# ─────────────────────────────────────────────────────


class TestModePriority:
    def test_start_overrides_lookback(self) -> None:
        """同时给 --start 和 --lookback-days, 应走 custom (--start 优先)."""
        args = _make_args(start="20260401", end="20260415", lookback_days=30)
        w = TimeWindowResolver.resolve(args)
        assert w.mode == "custom"
        assert w.start_date == date(2026, 4, 1)
        assert w.end_date == date(2026, 4, 15)


# ─────────────────────────────────────────────────────
# add_args 注入
# ─────────────────────────────────────────────────────


class TestArgsInjection:
    def test_add_args_creates_3_options(self) -> None:
        parser = argparse.ArgumentParser()
        TimeWindowResolver.add_args(parser)
        args = parser.parse_args([])
        assert hasattr(args, "start")
        assert hasattr(args, "end")
        assert hasattr(args, "lookback_days")
        # 默认值都是 None
        assert args.start is None
        assert args.end is None
        assert args.lookback_days is None

    def test_add_args_lookback_days_dest(self) -> None:
        """--lookback-days 应映射到 args.lookback_days (dest with underscore)."""
        parser = argparse.ArgumentParser()
        TimeWindowResolver.add_args(parser)
        args = parser.parse_args(["--lookback-days", "10"])
        assert args.lookback_days == 10


# ─────────────────────────────────────────────────────
# _cst_today (时区)
# ─────────────────────────────────────────────────────


class TestCstToday:
    def test_cst_timezone_used(self) -> None:
        """_cst_today 走 Asia/Shanghai 时区."""
        # 通过 patch 验证 datetime.now(CST) 调用了 CST 时区
        with patch("backend.app.utils.time_window_resolver.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 27, 14, 30, tzinfo=CST)
            result = _cst_today()
            mock_dt.now.assert_called_once_with(CST)
            assert result == date(2026, 4, 27)

    def test_cst_constant_is_shanghai(self) -> None:
        """CST 常量是 Asia/Shanghai (跟 PR #90 / services_healthcheck.py 对齐)."""
        assert CST == ZoneInfo("Asia/Shanghai")
