"""AlertDispatcher — L0 告警实时化 分发器 (S6).

P0/P1/P2 3 级 priority 路由:
  - P0 (秒级): 立即 dispatch → send_fn callback
  - P1 (分钟级): 缓冲 60s → flush("5min") 批量 send
  - P2 (日次级): 缓冲 5min → flush("15min") 批量 send

设计:
  - 纯内存缓冲 + callback 解耦 (铁律 31: 不直调 DingTalk)
  - 线程安全 (Lock)
  - send_fn 由调用方注入 (dingtalk_alert.send_with_retry 或其他)
  - stats 跟踪 dispatch/flush/send_failed 计数

用法:
    dispatcher = AlertDispatcher(send_fn=send_alert_with_retry)
    # S5 RealtimeRiskEngine 产出 results
    dispatcher.dispatch(engine.on_tick(ctx))   # P0 立即, P1/P2 缓冲
    dispatcher.dispatch(engine.on_5min_beat(ctx))  # P1 立即, P2 缓冲
    # Beat scheduler 触发 flush
    dispatcher.flush("5min")   # 每 60s
    dispatcher.flush("15min")  # 每 5min

关联铁律: 24 / 31 (纯内存, 0 IO) / 33 (send_fn 内部 fail-loud)
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from ..interface import RuleResult

# send_fn 签名: (RuleResult) -> bool (True=发送成功)
SendFn = Callable[[RuleResult], bool]


class AlertDispatcher:
    """P0 立即 / P1+P2 批量缓冲告警分发器."""

    def __init__(self, send_fn: SendFn) -> None:
        self._send_fn = send_fn
        self._p1_buffer: list[RuleResult] = []
        self._p2_buffer: list[RuleResult] = []
        self._lock = threading.Lock()
        # Stats
        self._p0_sent: int = 0
        self._p1_buffered: int = 0
        self._p2_buffered: int = 0
        self._p1_flushed: int = 0
        self._p2_flushed: int = 0
        self._send_failed: int = 0

    # ---- dispatch ----

    def dispatch(self, results: list[RuleResult]) -> int:
        """分发 RuleResult 列表.

        P0 → 立即 send_fn.
        P1/P2 → 缓冲 (等下次 flush).

        Returns:
            P0 立即发送数量 (不含缓冲).
        """
        immediate = 0
        with self._lock:
            for r in results:
                sev = _rule_severity_str(r)
                if sev == "p0":
                    if self._send_fn(r):
                        self._p0_sent += 1
                    else:
                        self._send_failed += 1
                    immediate += 1
                elif sev == "p1":
                    self._p1_buffer.append(r)
                    self._p1_buffered += 1
                elif sev == "p2":
                    self._p2_buffer.append(r)
                    self._p2_buffered += 1
                # info / unknown → skip (no alert)
        return immediate

    # ---- flush ----

    def flush(self, cadence: str) -> list[RuleResult]:
        """取出并清空指定 cadence buffer.

        Args:
            cadence: "5min" (P1 buffer) 或 "15min" (P2 buffer).

        Returns:
            被 flush 的 RuleResult 列表 (调用方负责 send).

        Raises:
            ValueError: cadence 无效.
        """
        if cadence == "5min":
            with self._lock:
                batch = self._p1_buffer
                self._p1_buffer = []
                self._p1_flushed += len(batch)
        elif cadence == "15min":
            with self._lock:
                batch = self._p2_buffer
                self._p2_buffer = []
                self._p2_flushed += len(batch)
        else:
            raise ValueError(f"Invalid flush cadence {cadence!r}, must be '5min' or '15min'")
        return batch

    def flush_and_send(self, cadence: str) -> int:
        """flush + 逐条 send_fn.

        Returns:
            成功发送数量.
        """
        batch = self.flush(cadence)
        sent = 0
        for r in batch:
            if self._send_fn(r):
                sent += 1
            else:
                with self._lock:
                    self._send_failed += 1
        return sent

    # ---- query ----

    @property
    def buffer_sizes(self) -> dict[str, int]:
        """当前缓冲区大小 (不含 lock — 近似值)."""
        return {
            "p1": len(self._p1_buffer),
            "p2": len(self._p2_buffer),
        }

    @property
    def stats(self) -> dict[str, int]:
        """dispatch/flush 累计统计."""
        with self._lock:
            return {
                "p0_sent": self._p0_sent,
                "p1_buffered": self._p1_buffered,
                "p2_buffered": self._p2_buffered,
                "p1_flushed": self._p1_flushed,
                "p2_flushed": self._p2_flushed,
                "send_failed": self._send_failed,
            }


def _rule_severity_str(result: RuleResult) -> str:
    """从 RuleResult 提取 severity 字符串.

    RuleResult 不含 severity 字段 — 从 rule_id 前缀推断:
      - correlated_drop / limit_down → P0
      - rapid_drop / volume_spike / liquidity_collapse → P1
      - industry_concentration → P2
      - 默认 → p1
    """
    rid = result.rule_id
    p0_rules = {
        "limit_down_detection",
        "near_limit_down",
        "gap_down_open",
        "correlated_drop",
    }
    p2_rules = {"industry_concentration"}

    if rid in p0_rules:
        return "p0"
    if rid in p2_rules:
        return "p2"
    # rapid_drop_5min / rapid_drop_15min / volume_spike / liquidity_collapse /
    # and any unknown rules → P1 default
    return "p1"
