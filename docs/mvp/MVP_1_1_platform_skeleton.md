# MVP 1.1 · Platform Skeleton

> **Wave**: 1 — 架构基础层
> **耗时**: 3 天
> **范围**: Platform/Application 分层骨架, 10 个 Framework 的 `interface.py` 只签名 (全部 `NotImplementedError`)
> **禁**: 任何实现代码, 老代码 100% 不动
> **依赖**: 无 (本 MVP 是所有其他 MVP 的依赖)
> **铁律**: 23 (独立可执行), 24 (≤ 2 页), 31 (Engine 纯计算, 此处定义 Platform 边界)

---

## 目标

1. 建立 `backend/quantmind/platform/` 包结构, 作为 QuantMind Core Platform (QCP) 的代码根
2. 定义 10 个 Framework 的对外接口 (Python ABC / Protocol), 签名 + docstring
3. 实现 Platform SDK 导出面 (`from quantmind.platform import *`)
4. 单测验证 import 通过 + 接口调用 raise NotImplementedError (契约检测)
5. 不动任何老代码, 不影响 PT

## 非目标

- ❌ 任何 Framework 的具体实现
- ❌ 从老代码迁移任何逻辑
- ❌ 引入新依赖 (pydantic/sqlalchemy/etc)
- ❌ 改 `backend/app/` / `backend/engines/` / `scripts/`

---

## 目录结构

```
backend/quantmind/
├── __init__.py
├── platform/
│   ├── __init__.py               # 导出 10 个 Framework 的 Protocol/ABC
│   ├── _types.py                 # 共享 dataclass (Signal/Order/Verdict/Lineage)
│   ├── data/
│   │   ├── __init__.py
│   │   └── interface.py          # DataSource / DataContract / DataAccessLayer / FactorCache
│   ├── factor/
│   │   ├── __init__.py
│   │   └── interface.py          # FactorRegistry / FactorOnboardingPipeline / FactorLifecycle
│   ├── strategy/
│   │   ├── __init__.py
│   │   └── interface.py          # Strategy / StrategyRegistry / CapitalAllocator
│   ├── signal/
│   │   ├── __init__.py
│   │   └── interface.py          # SignalPipeline / OrderRouter / ExecutionAuditTrail
│   ├── backtest/
│   │   ├── __init__.py
│   │   └── interface.py          # BacktestRunner / BacktestMode (enum) / BacktestRegistry
│   ├── eval/
│   │   ├── __init__.py
│   │   └── interface.py          # EvaluationPipeline / Verdict / GateResult
│   ├── observability/
│   │   ├── __init__.py
│   │   └── interface.py          # MetricExporter / AlertRouter / EventBus
│   ├── config/
│   │   ├── __init__.py
│   │   └── interface.py          # ConfigSchema (ABC) / ConfigLoader / ConfigAuditor
│   ├── ci/
│   │   ├── __init__.py
│   │   └── interface.py          # TestRunner / CoverageGate / SmokeTestSuite
│   └── knowledge/
│       ├── __init__.py
│       └── interface.py          # ExperimentRegistry / FailedDirectionDB / ADRRegistry
└── tests/
    └── test_platform_skeleton.py # 单测: import + interface 抛 NotImplementedError
```

## 接口定义原则

每个 `interface.py` 必须:

1. 使用 `abc.ABC` + `abstractmethod` 或 `typing.Protocol`
2. 每个方法 docstring 必须含:
   - `Args:` 参数含义
   - `Returns:` 返回类型含义
   - `Raises:` 预期异常
   - `Implementation Note:` 后续实现方向
3. 类型注解完整 (mypy strict 通过)
4. 默认方法 raise `NotImplementedError("MVP X.Y to implement")` 标明实现时机
5. 禁止任何 import 老代码 (严格隔离)

## 共享类型 `_types.py`

最小子集 (扩展延后):

```python
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

@dataclass(frozen=True)
class Signal:
    strategy_id: str
    code: str
    target_weight: float
    score: float
    trade_date: date
    metadata: dict[str, Any]

@dataclass(frozen=True)
class Order:
    order_id: str
    strategy_id: str
    code: str
    side: str  # BUY / SELL
    quantity: int
    trade_date: date

@dataclass(frozen=True)
class Verdict:
    """Evaluation Gate 统一输出"""
    subject: str  # factor_name or strategy_id
    passed: bool
    p_value: float | None
    blockers: list[str]
    details: dict[str, Any]

class BacktestMode(Enum):
    QUICK_1Y = "quick_1y"
    FULL_5Y = "full_5y"
    FULL_12Y = "full_12y"
    WF_5FOLD = "wf_5fold"

class Severity(Enum):
    P0 = "p0"
    P1 = "p1"
    P2 = "p2"
    INFO = "info"
```

## Platform SDK 导出面 (`platform/__init__.py`)

```python
"""QuantMind Core Platform (QCP) SDK — 10 Frameworks 统一导出.

Applications (PT/GP/Research/AI闭环) 必须通过本 SDK 消费 Platform 能力.
禁止 Application 跨 Framework import / 裸访问 Infrastructure.
"""
from quantmind.platform._types import (
    Signal, Order, Verdict, BacktestMode, Severity,
)
from quantmind.platform.data.interface import (
    DataSource, DataContract, DataAccessLayer, FactorCacheProtocol,
)
from quantmind.platform.factor.interface import (
    FactorRegistry, FactorOnboardingPipeline, FactorLifecycleMonitor,
)
from quantmind.platform.strategy.interface import (
    Strategy, StrategyRegistry, CapitalAllocator,
)
from quantmind.platform.signal.interface import (
    SignalPipeline, OrderRouter, ExecutionAuditTrail,
)
from quantmind.platform.backtest.interface import (
    BacktestRunner, BacktestRegistry, BatchBacktestExecutor,
)
from quantmind.platform.eval.interface import (
    EvaluationPipeline, StrategyEvaluator, GateResult,
)
from quantmind.platform.observability.interface import (
    MetricExporter, AlertRouter, EventBus,
)
from quantmind.platform.config.interface import (
    ConfigSchema, ConfigLoader, ConfigAuditor, FeatureFlag,
)
from quantmind.platform.ci.interface import (
    TestRunner, CoverageGate, SmokeTestSuite,
)
from quantmind.platform.knowledge.interface import (
    ExperimentRegistry, FailedDirectionDB, ADRRegistry,
)

__all__ = [
    "Signal", "Order", "Verdict", "BacktestMode", "Severity",
    "DataSource", "DataContract", "DataAccessLayer", "FactorCacheProtocol",
    "FactorRegistry", "FactorOnboardingPipeline", "FactorLifecycleMonitor",
    "Strategy", "StrategyRegistry", "CapitalAllocator",
    "SignalPipeline", "OrderRouter", "ExecutionAuditTrail",
    "BacktestRunner", "BacktestRegistry", "BatchBacktestExecutor",
    "EvaluationPipeline", "StrategyEvaluator", "GateResult",
    "MetricExporter", "AlertRouter", "EventBus",
    "ConfigSchema", "ConfigLoader", "ConfigAuditor", "FeatureFlag",
    "TestRunner", "CoverageGate", "SmokeTestSuite",
    "ExperimentRegistry", "FailedDirectionDB", "ADRRegistry",
]
```

## 单测 `test_platform_skeleton.py`

```python
"""MVP 1.1 验收: 骨架 import OK, 所有接口 raise NotImplementedError."""
import pytest

def test_sdk_imports():
    """Platform SDK 全部符号可 import."""
    from quantmind.platform import (
        Signal, Order, Verdict, BacktestMode,
        DataSource, FactorRegistry, Strategy, SignalPipeline,
        BacktestRunner, EvaluationPipeline, MetricExporter,
        ConfigSchema, TestRunner, ExperimentRegistry,
    )
    # 简单验证类型存在
    assert Signal is not None
    assert BacktestMode.QUICK_1Y.value == "quick_1y"

def test_each_interface_is_abstract():
    """每个 Framework 接口不可直接实例化或 raise NotImplementedError."""
    from quantmind.platform import DataSource, FactorRegistry, Strategy
    # ABC 无法直接实例化
    with pytest.raises(TypeError):
        DataSource()  # abstract class
    # ... 其他 interface 同理

def test_no_old_code_leakage():
    """Platform 骨架不 import 老代码 (严格隔离)."""
    import quantmind.platform as qcp
    import sys
    platform_modules = [m for m in sys.modules if m.startswith("quantmind.platform")]
    for mod_name in platform_modules:
        mod = sys.modules[mod_name]
        mod_src = getattr(mod, "__file__", "")
        # 禁 import backend.app / backend.engines / backend.data (老路径)
        # (通过 ast 扫描 imports 或 runtime 检测)
```

---

## 验收标准

| 项 | 验收 |
|---|---|
| `from quantmind.platform import *` | 无 ImportError |
| `pytest backend/tests/test_platform_skeleton.py` | PASS |
| mypy strict 通过 | 0 error |
| 每个 `interface.py` 行数 ≤ 200 行 | 轻量契约 |
| 老代码 0 改动 | `git diff backend/app backend/engines scripts` 为空 |
| regression_test max_diff=0 | PT 行为无变化 |
| 设计文档 ≤ 2 页 | 本文件 (已满足) |

## 爆炸半径

- **本 MVP 影响**: 仅新增 `backend/quantmind/platform/*`，不 import 到任何老代码
- **对 PT 影响**: 无 (不加载 Platform 模块)
- **回滚**: `rm -rf backend/quantmind/platform/` 即完全恢复

## 风险

| 风险 | 缓解 |
|---|---|
| 接口设计粒度错 (Wave 2 发现需重构) | 接口是骨架, Wave 2 允许**增加**方法, 不鼓励**改签名**. 改签名需 ADR 记录 |
| mypy strict 严苛 | 先 `mypy --strict-optional --warn-unused-ignores`, 完美 strict 后续迭代 |
| 单测过于宽松 | test_each_interface_is_abstract 逐个 Framework 断言, 不放水 |

## 实施步骤 (3 天)

**Day 1**:
- 创建目录结构 + 空 `__init__.py`
- 定义 `_types.py` 共享 dataclass
- 写 `data/interface.py` + `factor/interface.py` (最先需要的两个)

**Day 2**:
- 写剩余 8 个 `interface.py`
- 完善 `platform/__init__.py` 导出面

**Day 3**:
- 写 `test_platform_skeleton.py` 单测
- mypy strict 检查
- PR review + regression_test 验证 + 合入

## 后续依赖

本 MVP 完成后解锁 (不一定立即做):
- MVP 1.2 Config Management → 实现 `ConfigSchema / ConfigLoader / ConfigAuditor`
- MVP 1.3 Factor Framework → 实现 `FactorRegistry / FactorOnboardingPipeline / FactorLifecycleMonitor`
- MVP 1.4 Knowledge Registry → 实现 `ExperimentRegistry / FailedDirectionDB / ADRRegistry`

## 参考

- 主蓝图: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Part 1 (Platform/Application 分层) + Part 4 (MVP 拆分)
- Python Protocol 参考: PEP 544
- ABC 参考: Python docs `abc` module

## 变更记录

- 2026-04-17 v1.0 初稿
