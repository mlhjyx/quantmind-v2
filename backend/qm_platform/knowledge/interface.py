"""Framework #10 Knowledge Registry — 实验 / 失败方向 / 架构决策三合一.

目标: 防止重复踩坑 (Phase 2.1 sim-to-real / 5 次 ML NO-GO / Phase 3E 等权上限).

关联铁律:
  - 38: Blueprint 是唯一长期架构记忆 (ADRRegistry 与 Blueprint 互文)

实施时机:
  - MVP 1.4 Knowledge Registry (Wave 1)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ExperimentRecord:
    """一次实验记录 (研究 / AI Agent 探索).

    Args:
      experiment_id: UUID
      hypothesis: 待验证假设 (e.g. "LightGBM 在 33 因子下 OOS Sharpe > 等权")
      status: "running" / "success" / "failed" / "inconclusive"
      author: 提出人 / Agent ID
      started_at: ISO UTC
      completed_at: ISO UTC (可空, 运行中)
      verdict: 结论总结
      artifacts: 关联文件路径 (回测 / IC 报告等)
      tags: 分类 (e.g. ["ml", "walk_forward"])
    """

    experiment_id: UUID
    hypothesis: str
    status: str
    author: str
    started_at: str
    completed_at: str | None
    verdict: str | None
    artifacts: dict[str, str]
    tags: list[str]


@dataclass(frozen=True)
class FailedDirectionRecord:
    """失败方向记录 — 防重复踩坑.

    Args:
      direction: 简短描述 (e.g. "LightGBM E2E Sharpe > 等权")
      reason: 失败原因 (e.g. "5 次独立验证 Sharpe 均显著 < 基线")
      evidence: 证据列表 (commit / report 路径)
      recorded_at: ISO UTC
      severity: "terminal" (永不重试) / "conditional" (特定条件下可重试)
    """

    direction: str
    reason: str
    evidence: list[str]
    recorded_at: str
    severity: str


@dataclass(frozen=True)
class ADRRecord:
    """Architecture Decision Record.

    Args:
      adr_id: ADR-001 / ADR-002 ...
      title: 决策标题
      status: "proposed" / "accepted" / "deprecated" / "superseded_by:ADR-XXX"
      context: 背景
      decision: 决策内容
      consequences: 后果 (正反面)
      related_ironlaws: 关联铁律 ID 列表
      recorded_at: ISO UTC
    """

    adr_id: str
    title: str
    status: str
    context: str
    decision: str
    consequences: str
    related_ironlaws: list[int]
    recorded_at: str


class ExperimentRegistry(ABC):
    """实验登记 — 所有研究 / AI Agent 实验必录.

    用途:
      - 查重: 这假设做过吗? (search_similar)
      - 复盘: 过去一周跑了什么?
      - 统计: 成功率 / 常见失败模式
    """

    @abstractmethod
    def register(self, record: ExperimentRecord) -> UUID:
        """登记新实验 (status="running")."""

    @abstractmethod
    def complete(
        self, experiment_id: UUID, verdict: str, status: str, artifacts: dict[str, str]
    ) -> None:
        """标记完成.

        Args:
          status: "success" / "failed" / "inconclusive"
        """

    @abstractmethod
    def search_similar(self, hypothesis: str, k: int = 5) -> list[ExperimentRecord]:
        """搜相似实验 (embedding / BM25 实现).

        Returns:
          前 k 条相似度降序记录.
        """


class FailedDirectionDB(ABC):
    """失败方向数据库 — 新实验前 check_similar 防重复."""

    @abstractmethod
    def add(self, record: FailedDirectionRecord) -> None:
        """添加失败方向."""

    @abstractmethod
    def check_similar(self, direction: str, k: int = 3) -> list[FailedDirectionRecord]:
        """搜相似失败方向.

        Returns:
          相似度降序. AI Agent 在生成 hypothesis 前必查.
        """

    @abstractmethod
    def list_all(self, severity: str | None = None) -> list[FailedDirectionRecord]:
        """列所有失败方向 (按 severity 过滤)."""


class ADRRegistry(ABC):
    """ADR 注册表 — 补充 Blueprint (铁律 38) 的细粒度决策记录.

    Blueprint 记载略, ADR 记载每次微决策.
    """

    @abstractmethod
    def register(self, record: ADRRecord) -> str:
        """登记 ADR, 返回 adr_id (自动编号 ADR-NNN)."""

    @abstractmethod
    def supersede(self, old_adr_id: str, new_adr_id: str) -> None:
        """标记旧 ADR 被新 ADR 取代."""

    @abstractmethod
    def get_by_id(self, adr_id: str) -> ADRRecord:
        """按 ID 取."""

    @abstractmethod
    def list_by_ironlaw(self, ironlaw_id: int) -> list[ADRRecord]:
        """查某铁律关联的 ADR (e.g. 铁律 17 → 所有 DataPipeline 决策)."""
