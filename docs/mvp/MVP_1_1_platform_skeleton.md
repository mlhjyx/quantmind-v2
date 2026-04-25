# MVP 1.1 · Platform Skeleton

> **Wave**: 1 — 架构基础层
> **耗时**: 1 天实施 (预估 3 天, 实际骨架天然轻量)
> **范围**: Platform/Application 分层骨架, **12 个 Framework** 的 `interface.py` 只签名 (全部 `@abstractmethod` / `NotImplementedError`)
> **禁**: 任何实现代码, 老代码 100% 不动
> **依赖**: 无 (本 MVP 是所有其他 MVP 的依赖)
> **铁律**: 15 (regression 复现), 23 (独立可执行), 24 (≤ 2 页), 31 (Engine 纯计算), 38 (Blueprint 对齐)

---

## 目标

1. 建立 `backend/platform/` 包结构, 作为 QuantMind Core Platform (QCP) 的代码根
2. 定义 **12 个 Framework** 的对外接口 (Python ABC), 签名 + docstring
3. 实现 Platform SDK 统一导出面 (`from backend.qm_platform import *`)
4. 单测验证 import 通过 + 接口调用 raise NotImplementedError + 严格隔离老代码
5. 不动任何老代码, 不影响 PT

## 非目标

- ❌ 任何 Framework 的具体实现
- ❌ 从老代码迁移任何逻辑
- ❌ 引入新依赖 (pydantic/sqlalchemy/mypy 等)
- ❌ 改 `backend/app/` / `backend/engines/` / `backend/data/` / `scripts/`

---

## 目录结构 (实际落地)

```
backend/platform/
├── __init__.py                    # 12 Framework SDK 统一导出面 (67 个 __all__ 符号)
├── _types.py                      # 共享 dataclass + enum (Signal/Order/Verdict/BacktestMode/Severity/ResourceProfile/Priority)
├── data/                          # #1 Data Framework
│   ├── __init__.py
│   └── interface.py               # DataSource / DataContract / DataAccessLayer / FactorCacheProtocol / ValidationResult
├── factor/                        # #2 Factor Framework
│   ├── __init__.py
│   └── interface.py               # FactorRegistry / FactorOnboardingPipeline / FactorLifecycleMonitor + 5 dataclass
├── strategy/                      # #3 Strategy Framework
│   ├── __init__.py
│   └── interface.py               # Strategy (ABC) / StrategyRegistry / CapitalAllocator + RebalanceFreq/StrategyStatus/StrategyContext
├── signal/                        # #6 Signal & Execution
│   ├── __init__.py
│   └── interface.py               # SignalPipeline / OrderRouter / ExecutionAuditTrail / AuditChain
├── backtest/                      # #5 Backtest Framework
│   ├── __init__.py
│   └── interface.py               # BacktestRunner / BacktestRegistry / BatchBacktestExecutor / BacktestConfig / BacktestResult
├── eval/                          # #4 Evaluation Gate
│   ├── __init__.py
│   └── interface.py               # EvaluationPipeline / StrategyEvaluator / GateResult
├── observability/                 # #7 Observability
│   ├── __init__.py
│   └── interface.py               # MetricExporter / AlertRouter / EventBus / Metric / Alert
├── config/                        # #8 Config Management
│   ├── __init__.py
│   └── interface.py               # ConfigSchema (ABC) / ConfigLoader / ConfigAuditor / FeatureFlag
├── ci/                            # #9 CI/CD + Test
│   ├── __init__.py
│   └── interface.py               # TestRunner / CoverageGate / SmokeTestSuite / TestSummary
├── knowledge/                     # #10 Knowledge Registry
│   ├── __init__.py
│   └── interface.py               # ExperimentRegistry / FailedDirectionDB / ADRRegistry + 3 Record dataclass
├── resource/                      # #11 Resource Orchestration (ROF, U6)
│   ├── __init__.py
│   └── interface.py               # ResourceManager / AdmissionController / BudgetGuard + requires_resources 装饰器
└── backup/                        # #12 Backup & Disaster Recovery
    ├── __init__.py
    └── interface.py               # BackupManager / DisasterRecoveryRunner / BackupResult / RestoreResult

backend/tests/
└── test_platform_skeleton.py      # 65 tests (1+2+1+1+20+25+1+1+7+1 parametrize 展开)
```

## 接口定义硬规则 (所有 12 Framework 遵守)

1. `from __future__ import annotations` + 文件级 docstring (Framework # + 目标 + 关联铁律 + 实施时机)
2. `abc.ABC` + `@abstractmethod` (优先) 或 `typing.Protocol` (鸭子类型场景)
3. 每个方法 docstring 结构: 摘要 / Args / Returns / Raises / Implementation Note
4. 完整类型注解 + PEP 585 泛型 (`list[X]` 而非 `List[X]`)
5. 非 abstract 方法一律 `raise NotImplementedError("MVP X.Y to implement")`
6. **严禁 import `backend.app.*` / `backend.engines.*` / `backend.data.*` / `scripts.*`**
7. 跨 Framework import 通过 TYPE_CHECKING guard (runtime 不执行, 语义上仍要走 EventBus)

## 验收标准 (实测结果)

| # | 项 | 期望 | 实测 |
|---|---|---|---|
| 1 | `from backend.qm_platform import *` | 无 ImportError | ✅ 67 符号全导出 |
| 2 | `pytest backend/tests/test_platform_skeleton.py` | PASS | ✅ **65 passed in 0.15s** |
| 3 | `ruff check backend/platform/ backend/tests/test_platform_skeleton.py` | 0 violations | ✅ All checks passed |
| 4 | 老代码 git diff | 为空 | ✅ `git status`: 只有 backend/platform/ + test 新增 |
| 5 | regression_test --years 5 | max_diff=0 | (后台跑, 见 commit message) |
| 6 | 全量 pytest fail 数 | ≤ 32 (历史债基线) | (后台跑, 见 commit message) |
| 7 | 每个 interface.py 行数 | ≤ 200 | ✅ 全部合规 |
| 8 | Platform 严格隔离老代码 | AST 扫描 PASS | ✅ test_platform_isolated_from_legacy_code |
| 9 | Framework 间不 runtime 互相 import | 走 EventBus | ✅ test_frameworks_do_not_cross_import |
| 10 | import 无 IO 副作用 | 不加载 psycopg2/redis/sqlalchemy/pandas | ✅ 子进程验证 PASS |

## 爆炸半径

- **本 MVP 影响**: 仅新增 `backend/platform/*`, 不 import 到任何老代码
- **对 PT 影响**: 无 (不加载 Platform 模块)
- **回滚**: `rm -rf backend/platform/ backend/tests/test_platform_skeleton.py` 即完全恢复

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| 接口设计粒度错, Wave 2+ 需重构 | **增加方法**非破坏性, **改签名** 必写 ADR 入 Blueprint (铁律 38) |
| 未来 Wave 实施发现缺 Framework | 反膨胀规则锁 12, 13 必走 ADR (Blueprint v1.4 §Part 0) |
| factor_lifecycle 老实现 (engines/factor_lifecycle.py) 签名与 interface drift | interface 对齐老实现 public API, MVP 1.3 迁移时打平 |

## 后续依赖 (解锁)

本 MVP 完成后解锁 (不一定立即做):
- **MVP 1.2 Config Management** → 实现 `ConfigSchema / ConfigLoader / ConfigAuditor / FeatureFlag`
- **MVP 1.3 Factor Framework** → 实现 `FactorRegistry / FactorOnboardingPipeline / FactorLifecycleMonitor`
- **MVP 1.4 Knowledge Registry** → 实现 `ExperimentRegistry / FailedDirectionDB / ADRRegistry`
- Wave 2+ 所有 Framework 实施均以本骨架为依赖

## 参考

- **主蓝图**: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Part 1 (Platform/Application 分层) + Part 2 (12 Framework 设计) + Part 4 (MVP 拆分)
- **决策**: `memory/project_platform_decisions.md` Q1 (包名 `backend.qm_platform`)
- **铁律**: `CLAUDE.md` §铁律 (全局 40 条, 本 MVP 关联 15/17/22/23/24/25/28/31/33/34/36/37/38/39/40)

## 变更记录

- 2026-04-17 v1.0 初稿 (10 Framework, `backend/quantmind/platform/`)
- 2026-04-18 **v1.1 对齐 Blueprint v1.4** — 升级到 **12 Framework** (+#11 Resource + #12 Backup & DR), 包名改为 `backend.qm_platform` (platform_decisions Q1), SDK 导出 67 符号
- 2026-04-18 v1.1 实施完成 — 65 tests PASS, ruff clean, 老代码 0 改动
