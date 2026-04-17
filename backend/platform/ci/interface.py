"""Framework #9 CI/CD + Test — 3 层本地防线 (pre-commit / pre-push / daily).

目标: 防止测试债务累积 + regression 保证.

关联铁律:
  - 15: 回测可复现 (regression_test max_diff=0 是 pre-push 硬门)
  - 22: 文档跟随代码 (CI 可检测未同步的 CLAUDE.md 引用)
  - 40: 测试债务不得增长 (fail 数不升高)

决策 (platform_decisions Q4):
  - Layer 1 pre-commit: ruff + 快测 (<30s)
  - Layer 2 pre-push: regression_test --years 5 (max_diff=0)
  - Layer 3 daily: full pytest (03:00 Celery Beat)

实施时机:
  - MVP 4.3 CI/CD Framework (Wave 4)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class TestSummary:
    """pytest 运行结果汇总.

    Args:
      total: 收集到的 test 总数
      passed: 通过数
      failed: 失败数
      skipped: 跳过数
      duration_seconds: 耗时
      fail_names: 失败 test 名 (截断 20 个)
    """

    total: int
    passed: int
    failed: int
    skipped: int
    duration_seconds: float
    fail_names: list[str]


class TestRunner(ABC):
    """测试运行器 — 屏蔽 pytest 直接调用.

    CI 三层都用此接口, 实现决定是否并行 / 选择 marker.
    """

    @abstractmethod
    def run_fast(self) -> TestSummary:
        """Layer 1 — 跑快测 (marker=fast), <30s."""

    @abstractmethod
    def run_regression(self) -> TestSummary:
        """Layer 2 — 跑回归测试 (marker=regression), 含 regression_test.py.

        Raises:
          RegressionBroken: max_diff > 0 (铁律 15)
        """

    @abstractmethod
    def run_full(self) -> TestSummary:
        """Layer 3 — 跑全量 (所有 test_*.py).

        不 raise 即使有 fail (daily 告警不 block PT, 决策 Q4a).
        """


class CoverageGate(ABC):
    """覆盖率门禁 — 新代码覆盖率 ≥ 80%.

    对 diff 检测, 不看全仓库 (避免历史债拖累).
    """

    @abstractmethod
    def check_diff(self, base_ref: str = "main") -> float:
        """返回本次 diff 对应的覆盖率.

        Args:
          base_ref: 对比基准 (默认 main)

        Returns:
          0.0-1.0 之间的覆盖率
        """

    @abstractmethod
    def enforce(self, threshold: float = 0.80) -> None:
        """若 diff 覆盖率 < threshold 则 raise.

        Raises:
          CoverageBelowThreshold: 覆盖率不达标
        """


class SmokeTestSuite(ABC):
    """冒烟测试 — PT 启动前 / 大变更后跑.

    检查:
      - DB 连接
      - Redis 连接
      - QMT 数据同步状态
      - 配置对齐 (ConfigAuditor)
      - 关键表 row_count > 0
    """

    @abstractmethod
    def run(self) -> TestSummary:
        """跑全部冒烟, 任一失败立即 raise.

        Raises:
          SmokeTestFailed: 任一检查项失败 (fail-loud)
        """
