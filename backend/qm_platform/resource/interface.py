"""Framework #11 Resource Orchestration Framework (ROF) — 兑现铁律 9 / 升维 U6.

目标: 所有资源密集任务 (回测 / 研究 / GP / LightGBM / 数据拉取) 必须通过 ResourceManager
仲裁, 禁止裸并发. 防止 OOM / GPU 抢占 / DB 连接耗尽.

关联铁律:
  - 9: 资源密集任务必须经资源仲裁 (32GB RAM → max 2 并发重数据)

U6 Resource Awareness: 系统知道自己硬件边界, 主动调度.

实施时机:
  - MVP 3.0 Resource Orchestration (Wave 3 前置)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .._types import Priority, ResourceProfile


@dataclass(frozen=True)
class AdmissionResult:
    """AdmissionController 决策结果.

    Args:
      admitted: 是否允许执行
      lease_id: 准入令牌 (执行完需 release)
      wait_seconds: 预估等待时间 (若 admitted=False)
      reason: 决策原因 (人类可读)
    """

    admitted: bool
    lease_id: str | None
    wait_seconds: float
    reason: str


@dataclass(frozen=True)
class ResourceSnapshot:
    """当前资源快照 (ResourceManager.snapshot).

    Args:
      ram_used_gb / ram_total_gb
      cpu_load: 0-1 (平均最近 1 分钟)
      gpu_vram_used_gb / gpu_vram_total_gb
      db_active_connections
      active_leases: 活跃 lease 列表 {lease_id: {"caller": "...", "profile": ...}}
    """

    ram_used_gb: float
    ram_total_gb: float
    cpu_load: float
    gpu_vram_used_gb: float
    gpu_vram_total_gb: float
    db_active_connections: int
    active_leases: dict[str, dict[str, Any]]


class ResourceManager(ABC):
    """资源管理总入口 — 跟踪全局资源 + 发 lease.

    硬件约束 (reference_hardware):
      - 32GB RAM (shared_buffers=2GB 固定开销)
      - RTX 5070 12GB VRAM
      - R9-9900X3D 12C/24T
      - PG 连接池 (最大 20 连接)
    """

    @abstractmethod
    def snapshot(self) -> ResourceSnapshot:
        """返回当前资源快照 (给观察方用)."""

    @abstractmethod
    def acquire(
        self, profile: ResourceProfile, priority: Priority, caller: str
    ) -> AdmissionResult:
        """申请资源 lease (阻塞直到可用 / 超时 / 拒绝).

        Args:
          profile: 资源声明
          priority: 优先级 (PT_PRODUCTION 最高)
          caller: 调用方标识 (用于 snapshot 诊断)

        Returns:
          AdmissionResult, admitted=True 时含 lease_id.

        Raises:
          ResourceStarvation: 等待超过 max_wait, priority 低被饿死
        """

    @abstractmethod
    def release(self, lease_id: str) -> None:
        """释放 lease.

        Raises:
          InvalidLease: lease_id 不存在或已释放
        """


class AdmissionController(ABC):
    """准入控制器 — ResourceManager 内部决策逻辑.

    策略:
      - PT_PRODUCTION: 立即准入, 抢占 BACKGROUND
      - GP_MINING: 等 PT 空闲窗口 (16:00-09:30)
      - RESEARCH_ACTIVE: FIFO + 优先级
      - BACKGROUND: 资源充裕时跑
    """

    @abstractmethod
    def admit(
        self, profile: ResourceProfile, priority: Priority, snapshot: ResourceSnapshot
    ) -> AdmissionResult:
        """决策是否准入.

        Returns:
          AdmissionResult, 含 wait_seconds 预估.
        """


class BudgetGuard(ABC):
    """预算守护 — 限制 AI Agent / 研究任务的累积资源消耗.

    场景: AI Idea Agent 过度调 LLM / 过度回测 → 触发 BudgetGuard 暂停.
    """

    @abstractmethod
    def check(self, caller: str, window_hours: int = 24) -> bool:
        """检查 caller 最近 window 内消耗是否超预算.

        Returns:
          True 若在预算内, False 若超支.
        """

    @abstractmethod
    def record(self, caller: str, cost_units: float) -> None:
        """记录一次消耗 (cost_units 由实现定义, 如 API token / 回测次数)."""


def requires_resources(
    ram_gb: float = 0.0,
    cpu_cores: int = 1,
    gpu_vram_gb: float = 0.0,
    exclusive_pools: tuple[str, ...] = (),
    priority: Priority = Priority.RESEARCH_BATCH,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """装饰器 — 自动走 ResourceManager 仲裁.

    Usage:
        @requires_resources(ram_gb=4, exclusive_pools=("heavy_data",),
                            priority=Priority.GP_MINING)
        def gp_weekly_mining():
            ...

    实现 (MVP 3.0 时): 包裹函数, 调 acquire/release.
    """
    raise NotImplementedError("MVP 3.0 to implement (Framework #11)")
