"""Framework #12 Backup & Disaster Recovery — 生产就绪的最后一层.

目标: DB 165GB + factor cache 43GB + code / config / 事件流 的一致性备份 +
有演练的恢复路径 (不是"我有 pg_dump 就够了").

关联铁律:
  - 29: 禁止写 NaN 到 DB (备份校验要覆盖 NaN 检测)
  - 30: 缓存一致性必须保证 (恢复后缓存必须重建)

实施时机:
  - MVP 4.4 Backup & DR (Wave 4 收尾)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BackupResult:
    """一次备份的结果.

    Args:
      backup_id: UUID 字符串
      started_at: ISO UTC
      completed_at: ISO UTC (None 若运行中)
      backup_type: "full" / "incremental" / "config_only"
      targets: 备份覆盖的组件 (e.g. ["pg_dump", "parquet_cache", "configs"])
      size_bytes: 总占用
      artifact_path: 备份文件 / 目录路径
      checksum: SHA256 用于恢复时校验
      passed: 备份完整性 (校验 row count / checksum)
    """

    backup_id: str
    started_at: str
    completed_at: str | None
    backup_type: str
    targets: list[str]
    size_bytes: int
    artifact_path: str
    checksum: str
    passed: bool


@dataclass(frozen=True)
class RestoreResult:
    """一次恢复的结果.

    Args:
      restore_id: UUID 字符串
      backup_id: 源备份 ID
      started_at / completed_at: ISO UTC
      targets_restored: 实际恢复的组件
      rows_restored: dict, 表名 → 行数
      cache_rebuilt: 缓存是否已重建 (铁律 30)
      verification_passed: 恢复后回放 regression_test 是否 max_diff=0
      issues: 非致命问题 (e.g. stale 缓存清理)
    """

    restore_id: str
    backup_id: str
    started_at: str
    completed_at: str
    targets_restored: list[str]
    rows_restored: dict[str, int]
    cache_rebuilt: bool
    verification_passed: bool
    issues: list[str]


class BackupManager(ABC):
    """备份管理 — 每日自动 + 手动触发.

    策略:
      - 每日 00:00 Celery Beat: full backup (pg_dump + parquet_cache + configs)
      - 每小时: event_outbox incremental (保留 7 天, decisions Q3a)
      - 每次 config 变更: config_only backup (秒级)
    """

    @abstractmethod
    def backup(self, backup_type: str, targets: list[str]) -> BackupResult:
        """执行备份.

        Args:
          backup_type: "full" / "incremental" / "config_only"
          targets: 组件列表, 空 list 表示全部

        Returns:
          BackupResult, 含完整性校验

        Raises:
          BackupCorruption: 备份后校验 fail (铁律 29 等)
        """

    @abstractmethod
    def list_backups(self, since: date | None = None) -> list[BackupResult]:
        """列所有备份 (按时间倒序)."""

    @abstractmethod
    def verify(self, backup_id: str) -> bool:
        """校验备份文件未损坏 (checksum 比对)."""


class DisasterRecoveryRunner(ABC):
    """灾难恢复 — 真实跑过的演练脚本, 不是只写在 doc 里.

    原则: DR 每季度演练一次, 演练失败的 DR 不算 DR.
    """

    @abstractmethod
    def dry_run(self, backup_id: str) -> RestoreResult:
        """演练恢复 (不写入生产 DB, 走 shadow instance).

        Returns:
          RestoreResult, verification_passed 必须为 True 才算演练成功.
        """

    @abstractmethod
    def execute(self, backup_id: str, confirm_token: str) -> RestoreResult:
        """真实恢复 (需 confirm_token 防误触).

        Args:
          backup_id: 要恢复的备份
          confirm_token: 人工输入的确认字符串 (e.g. "RESTORE-2026-04-18")

        Raises:
          ConfirmTokenMissing: 未提供 confirm_token
          PTStillRunning: PT 未暂停, 拒绝恢复 (避免数据冲突)
        """

    @abstractmethod
    def quarterly_drill(self) -> RestoreResult:
        """季度演练入口 (由 Celery Beat 触发).

        自动: dry_run + 回放 regression_test + 报告.
        """
