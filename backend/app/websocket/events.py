"""WebSocket事件类型定义 — 回测进度推送协议。

所有事件均通过python-socketio发送到对应的run_id room。
客户端通过join_backtest / leave_backtest加入/离开room。
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Literal

# ─────────────────────────────────────────────────────────
# 事件名称常量
# ─────────────────────────────────────────────────────────

EVENT_PROGRESS = "backtest:progress"
EVENT_STATUS = "backtest:status"
EVENT_REALTIME_NAV = "backtest:realtime_nav"
EVENT_LOG = "backtest:log"

BacktestStatus = Literal["running", "completed", "failed", "cancelled"]


# ─────────────────────────────────────────────────────────
# 事件数据结构
# ─────────────────────────────────────────────────────────


@dataclass
class BacktestProgressEvent:
    """回测进度事件。

    Attributes:
        run_id: 回测任务ID
        progress_pct: 进度百分比 [0.0, 100.0]
        current_date: 当前处理的日期（ISO格式字符串）
        elapsed_sec: 已经过秒数
    """

    run_id: str
    progress_pct: float
    current_date: str
    elapsed_sec: float

    def to_dict(self) -> dict:
        """序列化为字典（用于socketio emit）。"""
        return asdict(self)


@dataclass
class BacktestStatusEvent:
    """回测状态变更事件。

    Attributes:
        run_id: 回测任务ID
        status: 状态字符串 running/completed/failed/cancelled
        message: 附加说明（可选）
    """

    run_id: str
    status: BacktestStatus
    message: str = ""

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return asdict(self)


@dataclass
class BacktestRealtimeNavEvent:
    """实时NAV推送事件。

    Attributes:
        run_id: 回测任务ID
        date: 当日日期（ISO格式）
        nav: 策略净值（元）
        benchmark_nav: 基准净值（元）
    """

    run_id: str
    date: str
    nav: float
    benchmark_nav: float

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return asdict(self)


@dataclass
class BacktestLogEvent:
    """回测日志事件。

    Attributes:
        run_id: 回测任务ID
        level: 日志级别 INFO/WARNING/ERROR
        message: 日志消息
    """

    run_id: str
    level: str
    message: str

    def to_dict(self) -> dict:
        """序列化为字典。"""
        return asdict(self)


def make_progress(
    run_id: str,
    progress_pct: float,
    current_date: date | str,
    elapsed_sec: float,
) -> dict:
    """构造backtest:progress事件payload。

    Args:
        run_id: 回测任务ID
        progress_pct: 进度百分比
        current_date: 当前处理日期
        elapsed_sec: 已过去秒数

    Returns:
        可直接传给sio.emit()的字典
    """
    date_str = current_date.isoformat() if hasattr(current_date, "isoformat") else str(current_date)
    return BacktestProgressEvent(
        run_id=run_id,
        progress_pct=round(progress_pct, 2),
        current_date=date_str,
        elapsed_sec=round(elapsed_sec, 1),
    ).to_dict()


def make_status(run_id: str, status: BacktestStatus, message: str = "") -> dict:
    """构造backtest:status事件payload。

    Args:
        run_id: 回测任务ID
        status: 状态字符串
        message: 附加说明

    Returns:
        可直接传给sio.emit()的字典
    """
    return BacktestStatusEvent(run_id=run_id, status=status, message=message).to_dict()


def make_realtime_nav(
    run_id: str,
    date: date | str,
    nav: float,
    benchmark_nav: float,
) -> dict:
    """构造backtest:realtime_nav事件payload。

    Args:
        run_id: 回测任务ID
        date: 日期
        nav: 策略净值
        benchmark_nav: 基准净值

    Returns:
        可直接传给sio.emit()的字典
    """
    date_str = date.isoformat() if hasattr(date, "isoformat") else str(date)
    return BacktestRealtimeNavEvent(
        run_id=run_id,
        date=date_str,
        nav=round(nav, 4),
        benchmark_nav=round(benchmark_nav, 4),
    ).to_dict()


def make_log(run_id: str, level: str, message: str) -> dict:
    """构造backtest:log事件payload。

    Args:
        run_id: 回测任务ID
        level: 日志级别
        message: 日志消息

    Returns:
        可直接传给sio.emit()的字典
    """
    return BacktestLogEvent(run_id=run_id, level=level.upper(), message=message).to_dict()
