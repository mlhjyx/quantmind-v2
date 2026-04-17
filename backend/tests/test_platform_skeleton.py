"""MVP 1.1 验收测试: backend.platform 骨架.

验收点:
  1. SDK 全部符号可 import (__all__ ≥ 40, 实际 67)
  2. 12 Framework × ABC 类不可直接实例化 (抽象契约)
  3. SDK __all__ 列表完整无重复
  4. 共享类型 dataclass frozen (不可变值对象)
  5. Platform 代码严格隔离老代码 (AST 扫描 import)
  6. Framework 间不互相 import (跨 Framework 必走 EventBus)
  7. import backend.platform 无 IO 副作用 (不访问 DB / Redis)

执行:
  pytest backend/tests/test_platform_skeleton.py -v
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import is_dataclass

import pytest

# pytest.ini 不在 backend/tests 下, 手动定位 Platform 根
PLATFORM_ROOT = pathlib.Path(__file__).resolve().parents[1] / "platform"


# ---------- test 1: SDK import ----------


def test_sdk_imports_all_symbols() -> None:
    """全部 67 个符号可通过 `from backend.platform import ...` 取得."""
    import backend.platform as platform_pkg

    expected_symbols = [
        "ADRRecord", "ADRRegistry", "AdmissionController", "AdmissionResult",
        "Alert", "AlertRouter", "AuditChain", "BacktestConfig", "BacktestMode",
        "BacktestRegistry", "BacktestResult", "BacktestRunner", "BackupManager",
        "BackupResult", "BatchBacktestExecutor", "BudgetGuard", "CapitalAllocator",
        "ConfigAuditor", "ConfigLoader", "ConfigSchema", "CoverageGate",
        "DataAccessLayer", "DataContract", "DataSource", "DisasterRecoveryRunner",
        "EvaluationPipeline", "EventBus", "ExecutionAuditTrail", "ExperimentRecord",
        "ExperimentRegistry", "FactorCacheProtocol", "FactorLifecycleMonitor",
        "FactorMeta", "FactorOnboardingPipeline", "FactorRegistry", "FactorSpec",
        "FactorStatus", "FailedDirectionDB", "FailedDirectionRecord", "FeatureFlag",
        "GateResult", "Metric", "MetricExporter", "OnboardResult", "Order",
        "OrderRouter", "Priority", "RebalanceFreq", "ResourceManager",
        "ResourceProfile", "ResourceSnapshot", "RestoreResult", "Severity",
        "Signal", "SignalPipeline", "SmokeTestSuite", "Strategy", "StrategyContext",
        "StrategyEvaluator", "StrategyRegistry", "StrategyStatus", "TestRunner",
        "TestSummary", "TransitionDecision", "ValidationResult", "Verdict",
        "requires_resources",
    ]
    missing = [s for s in expected_symbols if not hasattr(platform_pkg, s)]
    assert not missing, f"SDK 缺符号: {missing}"

    # 枚举值一致性抽查
    assert platform_pkg.BacktestMode.QUICK_1Y.value == "quick_1y"
    assert platform_pkg.Priority.PT_PRODUCTION.value == "pt_production"
    assert platform_pkg.Severity.P0.value == "p0"
    assert platform_pkg.FactorStatus.ACTIVE.value == "active"
    assert platform_pkg.StrategyStatus.LIVE.value == "live"
    assert platform_pkg.RebalanceFreq.MONTHLY.value == "monthly"


def test_sdk_all_symbols_complete() -> None:
    """__all__ 至少 40 个符号, 实际 67 (12 Framework × 平均 5)."""
    from backend.platform import __all__

    assert len(__all__) >= 40
    assert len(__all__) == len(set(__all__)), "__all__ 不允许重复"
    assert "Signal" in __all__
    assert "ResourceManager" in __all__
    assert "BackupManager" in __all__


# ---------- test 2: ABC 不可直接实例化 ----------


@pytest.mark.parametrize(
    "abstract_class_name",
    [
        "DataSource",
        "DataAccessLayer",
        "FactorCacheProtocol",
        "FactorRegistry",
        "FactorOnboardingPipeline",
        "FactorLifecycleMonitor",
        "Strategy",
        "StrategyRegistry",
        "CapitalAllocator",
        "SignalPipeline",
        "OrderRouter",
        "ExecutionAuditTrail",
        "BacktestRunner",
        "BacktestRegistry",
        "BatchBacktestExecutor",
        "EvaluationPipeline",
        "StrategyEvaluator",
        "MetricExporter",
        "AlertRouter",
        "EventBus",
        "ConfigSchema",
        "ConfigLoader",
        "ConfigAuditor",
        "FeatureFlag",
        "TestRunner",
        "CoverageGate",
        "SmokeTestSuite",
        "ExperimentRegistry",
        "FailedDirectionDB",
        "ADRRegistry",
        "ResourceManager",
        "AdmissionController",
        "BudgetGuard",
        "BackupManager",
        "DisasterRecoveryRunner",
    ],
)
def test_abstract_classes_cannot_instantiate(abstract_class_name: str) -> None:
    """每个 Framework 的核心 ABC 不可直接实例化 (契约层约束)."""
    import backend.platform as platform_pkg

    cls = getattr(platform_pkg, abstract_class_name)
    with pytest.raises(TypeError, match="abstract"):
        cls()


# ---------- test 3: dataclass frozen ----------


@pytest.mark.parametrize(
    "dc_name",
    [
        "Signal",
        "Order",
        "Verdict",
        "ResourceProfile",
        "FactorSpec",
        "FactorMeta",
        "OnboardResult",
        "TransitionDecision",
        "StrategyContext",
        "AuditChain",
        "BacktestConfig",
        "BacktestResult",
        "GateResult",
        "Metric",
        "Alert",
        "ExperimentRecord",
        "FailedDirectionRecord",
        "ADRRecord",
        "AdmissionResult",
        "ResourceSnapshot",
        "BackupResult",
        "RestoreResult",
        "TestSummary",
        "ValidationResult",
        "DataContract",
    ],
)
def test_dataclasses_are_frozen(dc_name: str) -> None:
    """所有共享类型 dataclass 必须 frozen (不可变 + 线程安全)."""
    import backend.platform as platform_pkg

    dc = getattr(platform_pkg, dc_name, None)
    # ConfigDriftReport 未导出在 __init__, 但同文件, 这里按 __all__ 限定.
    if dc is None:
        pytest.skip(f"{dc_name} not in SDK __all__")
    assert is_dataclass(dc), f"{dc_name} must be a dataclass"
    # frozen 体现为实例的 __setattr__ 抛 FrozenInstanceError
    # 不实例化 (构造参数多), 改查 dataclass 元数据
    assert dc.__dataclass_params__.frozen, f"{dc_name} must be frozen"


# ---------- test 4: 严格隔离老代码 ----------


def test_platform_isolated_from_legacy_code() -> None:
    """AST 扫描 — Platform 不 import backend.app/engines/data/scripts."""
    forbidden_prefixes = ("backend.app", "backend.engines", "backend.data", "scripts")
    violations: list[str] = []

    for py_file in PLATFORM_ROOT.rglob("*.py"):
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for prefix in forbidden_prefixes:
                    if node.module.startswith(prefix):
                        violations.append(f"{py_file}: from {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        if alias.name.startswith(prefix):
                            violations.append(f"{py_file}: import {alias.name}")

    assert not violations, "Platform 严格隔离违规:\n" + "\n".join(violations)


# ---------- test 5: Framework 间不互相 import ----------


def _is_inside_type_checking(tree: ast.AST, target_node: ast.AST) -> bool:
    """判断 target_node 是否位于 `if TYPE_CHECKING:` 块内 (runtime 不执行)."""
    for outer in ast.walk(tree):
        if not isinstance(outer, ast.If):
            continue
        cond = outer.test
        is_tc = (
            (isinstance(cond, ast.Name) and cond.id == "TYPE_CHECKING")
            or (
                isinstance(cond, ast.Attribute)
                and cond.attr == "TYPE_CHECKING"
            )
        )
        if not is_tc:
            continue
        # target 在 outer.body 子树内?
        for child in ast.walk(outer):
            if child is target_node:
                return True
    return False


def test_frameworks_do_not_cross_import() -> None:
    """跨 Framework 通信必须走 EventBus, interface.py 不得 runtime 互相 import.

    允许: backend.platform._types (共享) / 自身 Framework 内部 / TYPE_CHECKING guard 下的类型注解.
    """
    framework_names = (
        "data", "factor", "strategy", "signal", "backtest", "eval",
        "observability", "config", "ci", "knowledge", "resource", "backup",
    )
    cross_imports: list[str] = []

    for fw in framework_names:
        fw_root = PLATFORM_ROOT / fw
        for py_file in fw_root.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.ImportFrom) and node.module):
                    continue
                if not node.module.startswith("backend.platform."):
                    continue
                # 允许 _types 共享
                if node.module == "backend.platform._types":
                    continue
                # 允许自身 Framework 内部
                if node.module.startswith(f"backend.platform.{fw}"):
                    continue
                # 允许 TYPE_CHECKING guard 内部 (类型注解, runtime 不执行)
                if _is_inside_type_checking(tree, node):
                    continue
                cross_imports.append(
                    f"{py_file.relative_to(PLATFORM_ROOT)}: "
                    f"from {node.module} at line {node.lineno}"
                )

    assert not cross_imports, (
        "Framework 间违规 runtime import (应走 EventBus 或走 TYPE_CHECKING):\n"
        + "\n".join(cross_imports)
    )


# ---------- test 6: import 无副作用 ----------


def test_platform_import_has_no_side_effects() -> None:
    """import backend.platform 不得触发 DB / Redis 连接 (IO 副作用).

    通过子进程验证 — 父进程环境可能已加载过依赖.

    MVP 1.1 v1.0 曾禁 pandas 加载, MVP 1.2a 起放宽: Platform DAL 返回 DataFrame
    是一等公民设计, pandas 必加载 (纯 module 加载, 非 IO 副作用). 只禁真正 IO 类
    依赖 (DB 驱动 / Redis 客户端 / ORM).
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import backend.platform; "
            "import sys; "
            "forbidden = ['psycopg2', 'redis', 'sqlalchemy']; "
            "loaded = [m for m in forbidden if m in sys.modules]; "
            "print('LOADED:' + ','.join(loaded))",
        ],
        capture_output=True,
        text=True,
        cwd=str(PLATFORM_ROOT.parent.parent),
    )
    assert result.returncode == 0, f"import 失败: {result.stderr}"
    assert "LOADED:" in result.stdout
    loaded_str = result.stdout.strip().split("LOADED:")[-1].strip()
    loaded_modules = [m for m in loaded_str.split(",") if m]
    assert not loaded_modules, (
        f"Platform import 触发了 IO 依赖加载: {loaded_modules}. "
        f"Platform 应通过依赖注入接收 conn, 不自持 DB / Redis 客户端."
    )
