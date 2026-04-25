"""TimeWindowResolver — 4 schtask scripts 共用的时间窗口语义抽象 (LL-076 真修复).

LL-076 (Session 36 末 2026-04-25 沉淀): schtask Python 脚本中, args.start 与
date.today() 混淆导致 weekend backfill silent skip (pull_moneyflow PR #90 已部分
修, 但 compute_daily_ic / compute_ic_rolling / fast_ic_recompute 仍各自 hardcoded
date.today(), 没 --start arg). 抽象成统一 resolver, 4 schtask 共用.

支持 3 种解析模式:
    - custom: --start YYYYMMDD [--end YYYYMMDD] (人工 backfill, 周末 OK)
    - lookback: --lookback-days N (回溯 N 天到 today, 通用 schtask)
    - default: 无参数, 走调用方传 default_lookback (默认 schtask daily 行为)

铁律遵守:
    - 41 (timezone): today() 走 Asia/Shanghai, 不裸 date.today() 避免 UTC 服务器 18:00 CST 跨日 bug
    - 33 (fail-loud): --start 格式错 raise ValueError, 不 silent skip
    - 32 (Service 不 commit): 本模块纯计算, 无 IO
    - 17 不适用: 本模块不写 DB

关联文档:
    - docs/research/QUANTMIND_LANDSCAPE_ANALYSIS_2026.md Part 5 #6 (LL-076 真修复模式)
    - memory/project_borrowable_patterns.md P1 #6
    - LESSONS_LEARNED.md LL-076

Phase 1 (本 commit): 抽象 + 单测.
Phase 2 (Monday 后): 4 schtask scripts 迁移 (compute_daily_ic / compute_ic_rolling
                     / fast_ic_recompute / pull_moneyflow refactor).
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

# 铁律 41 时区统一 (跟 PR #90 / scripts/services_healthcheck.py 对齐)
CST = ZoneInfo("Asia/Shanghai")

ResolveMode = Literal["default", "lookback", "custom"]
"""Type alias for TimeWindow.mode. **For annotations only — not a runtime Enum**.
reviewer python-reviewer P3 采纳: 防 callers 误以为可作 runtime value. 用作字符串字面量比对."""

# reviewer code-reviewer P1.2 采纳 (2026-04-26): 显式 __all__ 标注 public API surface,
# 防 phase 2 schtask scripts 误用 _cst_today 私有函数. 测试可绕 __all__ 直 import (Python 惯例 OK).
__all__ = ["CST", "ResolveMode", "TimeWindow", "TimeWindowResolver"]


@dataclass(frozen=True)
class TimeWindow:
    """时间窗口 [start_date, end_date] (含两端).

    Attributes:
        start_date: 起始日期 (含).
        end_date: 结束日期 (含).
        mode: 解析模式标识, 用于 logging / 审计.

    Invariants:
        start_date <= end_date
    """

    start_date: date
    end_date: date
    mode: ResolveMode

    def __post_init__(self) -> None:
        if self.start_date > self.end_date:
            raise ValueError(
                f"TimeWindow invariant violated: start_date {self.start_date} "
                f"> end_date {self.end_date} (mode={self.mode})"
            )

    @property
    def days(self) -> int:
        """窗口跨度 (含两端). e.g. start=4-1, end=4-1 → 1; start=4-1, end=4-3 → 3."""
        return (self.end_date - self.start_date).days + 1


class TimeWindowResolver:
    """schtask Python 脚本统一窗口解析 — argparse → TimeWindow.

    使用模式:
        ```python
        parser = argparse.ArgumentParser()
        TimeWindowResolver.add_args(parser)
        # ... 其他 schtask-specific args ...
        args = parser.parse_args()
        window = TimeWindowResolver.resolve(args, default_lookback=30)
        # 用 window.start_date / window.end_date / window.mode
        ```

    解析优先级 (最高优先级先触发):
        1. --start (custom 模式): 周末 backfill 友好, end 可选 (默认 today)
        2. --lookback-days (lookback 模式): 显式回溯, 跟 today 自动对齐
        3. default 模式: 调用方传 default_lookback (schtask daily 自动触发用)
    """

    @staticmethod
    def add_args(parser: argparse.ArgumentParser) -> None:
        """注入共用 CLI args (--start / --end / --lookback-days).

        4 schtask scripts 调用 TimeWindowResolver.add_args(parser) 后, 自动支持:
            --start YYYYMMDD       人工 backfill 起始日 (custom 模式)
            --end YYYYMMDD         人工 backfill 结束日, 默认 today
            --lookback-days N      回溯 N 天 (lookback 模式)

        Args:
            parser: argparse.ArgumentParser, 调用方已 init 的 parser
        """
        parser.add_argument(
            "--start",
            type=str,
            default=None,
            help="起始日期 YYYYMMDD (人工 backfill 模式, 跟 --end 配对)",
        )
        parser.add_argument(
            "--end",
            type=str,
            default=None,
            help="结束日期 YYYYMMDD (默认 today, 仅 --start 模式生效)",
        )
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=None,
            dest="lookback_days",
            help="回溯天数 N (lookback 模式, 跟 --start 互斥)",
        )

    @staticmethod
    def resolve(
        args: argparse.Namespace,
        default_lookback: int = 1,
    ) -> TimeWindow:
        """从 argparse 解析窗口.

        Args:
            args: argparse.Namespace, 须含 start / end / lookback_days 三个属性.
                  (即 add_args 注入过)
            default_lookback: default 模式下回溯天数. e.g. 1 = today only,
                              30 = today-30 to today.

        Returns:
            TimeWindow (含 start_date / end_date / mode)

        Raises:
            ValueError: --start / --end 格式错, 或 start > end.
            AttributeError: args 缺 start / end / lookback_days 属性 (调用方未 add_args).

        Examples:
            >>> # custom 模式 (周末 backfill)
            >>> args = parser.parse_args(["--start", "20260427", "--end", "20260427"])
            >>> w = TimeWindowResolver.resolve(args)
            >>> w.start_date, w.end_date, w.mode
            (date(2026, 4, 27), date(2026, 4, 27), 'custom')

            >>> # lookback 模式
            >>> args = parser.parse_args(["--lookback-days", "30"])
            >>> w = TimeWindowResolver.resolve(args)  # today=2026-4-27
            >>> w.start_date  # 30 天前
            date(2026, 3, 28)

            >>> # default 模式
            >>> args = parser.parse_args([])
            >>> w = TimeWindowResolver.resolve(args, default_lookback=7)
            >>> w.days
            8  # today included + 7 days back
        """
        today = _cst_today()

        # 模式 1: --start 显式指定 (custom)
        # reviewer code-reviewer P0 采纳 (2026-04-26): `if args.start:` 会让 args.start=""
        # 空字符串 silent fall-through 到 lookback/default 模式, 违反铁律 33 fail-loud.
        # 改 `is not None` 后, 空字符串 → strptime raise ValueError (走 fail-loud 路径).
        if args.start is not None:
            try:
                start = datetime.strptime(args.start, "%Y%m%d").date()
            except ValueError as e:
                raise ValueError(
                    f"--start '{args.start}' 格式错: 期望 YYYYMMDD (e.g. 20260427), "
                    f"got {e}"
                ) from e

            # reviewer python-reviewer P2 采纳 (2026-04-26): `--end` 用 `is not None` 跟
            # `--start` P0 fix rationale 一致, 防 args.end="" 空字符串 silent fall-through
            # (违反铁律 33). 空字符串现进 strptime → raise ValueError.
            if args.end is not None:
                try:
                    end = datetime.strptime(args.end, "%Y%m%d").date()
                except ValueError as e:
                    raise ValueError(
                        f"--end '{args.end}' 格式错: 期望 YYYYMMDD (e.g. 20260427), "
                        f"got {e}"
                    ) from e
            else:
                end = today

            return TimeWindow(start_date=start, end_date=end, mode="custom")

        # 模式 2: --lookback-days
        if args.lookback_days is not None:
            if args.lookback_days < 0:
                raise ValueError(
                    f"--lookback-days {args.lookback_days} 必须 >= 0 "
                    f"(0 = today only, 1 = today-1 to today, ...)"
                )
            start = today - timedelta(days=args.lookback_days)
            return TimeWindow(start_date=start, end_date=today, mode="lookback")

        # 模式 3: default
        if default_lookback < 0:
            raise ValueError(
                f"default_lookback {default_lookback} 必须 >= 0 "
                f"(由调用方传, 错配会 silent 错)"
            )
        start = today - timedelta(days=default_lookback)
        return TimeWindow(start_date=start, end_date=today, mode="default")


def _cst_today() -> date:
    """返 Asia/Shanghai 时区当前日期 (铁律 41 时区统一).

    避免 schtask 在 UTC server 时 date.today() 跨日 bug. e.g. UTC 16:00 = CST 00:00,
    UTC date.today() 仍是 yesterday CST. 实际 schtask 14:30 CST = 06:30 UTC, 这种
    场景不易发生但通用化保险.
    """
    return datetime.now(CST).date()
