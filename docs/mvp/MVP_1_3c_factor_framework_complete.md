# MVP 1.3c · Factor Framework 收尾 — Lifecycle 迁 Platform + G9/G10 Gate + Flag 切 True

> **Wave**: 1 第 6 步 (MVP 1.3 拆分 3/3, 本 MVP 后 Factor Framework 基本成型)
> **耗时**: 3-4 天 (Day 1 Status 统一 + lifecycle / Day 2 G9/G10 + register / Day 3 onboarding 改造 + Flag 切 / Day 4 收尾 + 验收)
> **风险**: 中 (shim + 3 层 fallback 兜底, regression max_diff=0 硬门)
> **范围 Scope B** (用户批准推荐): lifecycle 迁移 + Registry 4 method + G9/G10 + Flag 切 True
> **铁律**: 12 (G9) / 13 (G10) / 15 / 22 / 23 / 24 / 25 / 30 / 33 / 34 / 36 / 37 / 38 / 40

---

## 目标 (Scope B)

1. **FactorStatus 统一** — `backend/platform/factor/interface.py` 版 7 值为唯一源, `engines/factor_lifecycle.py` 改 shim re-export (D2 superset, DB 零迁移)
2. **Platform lifecycle concrete** — `backend/platform/factor/lifecycle.py::PlatformLifecycleMonitor` 实现 `evaluate_all()`, 纯规则 `engines.factor_lifecycle.evaluate_transition` 保留 (铁律 31)
3. **DBFactorRegistry 4 method concrete** — `register` / `get_active` / `update_status` / `novelty_check` (`FactorMeta list / UUID / None / bool`)
4. **G9 novelty** — `AstDeduplicator.compute_ast_similarity > 0.7` 拒绝 (铁律 12)
5. **G10 economic hypothesis** — `spec.hypothesis` 非空且不以 `GP自动挖掘:` 开头, 否则 `OnboardingBlocked` (铁律 13)
6. **factor_onboarding.py 改走 Platform register** — L279 `_upsert_factor_registry` 改调 `DBFactorRegistry.register(FactorSpec)` (替代裸 INSERT INTO factor_registry)
7. **FeatureFlag `use_db_direction` 注册 + 切 True** — `scripts/registry/register_feature_flags.py` 补注册, PT 重启后观察 3 天

## 非目标 (明确留 MVP 1.3d 或后续)

- ❌ DataPipeline.ingest 加 `_registry_check` (中风险, 影响铁律 17 全入库路径)
- ❌ 删 `_constants.py` 6 direction dict (5/6 只 test 消费, 1/6 minute_feature 生产用, 等 Flag 稳定后一起迁)
- ❌ 迁 4 test 的 `_constants` 直接 dict import
- ❌ paired bootstrap p<0.05 集成 onboarding (跨 Framework #2↔#5 边界, 单独 plan)
- ❌ BH-FDR 累积校正 (需 `FactorTestRegistry` 历史累积数, 单独 plan)

## 实施结构

```
backend/platform/factor/
├── registry.py          ⚠️ 扩 4 method (register/get_active/update_status/novelty_check) ~150 行
└── lifecycle.py         ⭐ NEW PlatformLifecycleMonitor + 纯规则依赖注入 ~120 行

backend/engines/factor_lifecycle.py     ⚠️ FactorStatus → shim re-export Platform 版, 保 evaluate_transition 纯规则不动
backend/app/services/factor_onboarding.py  ⚠️ L279 _upsert_factor_registry 改调 DBFactorRegistry.register
scripts/factor_lifecycle_monitor.py       ⚠️ 主执行逻辑改调 PlatformLifecycleMonitor (shim 保老 CLI API)

scripts/registry/
└── register_feature_flags.py  ⭐ NEW ~80 行 (注册 use_db_direction=True, removal_date=2026-06-01)

backend/tests/
├── test_factor_registry.py              ⚠️ 扩 ~20 tests (16→36): register/novelty/get_active/update_status
├── test_platform_lifecycle.py           ⭐ NEW ~15 tests
└── test_factor_onboarding_gates.py      ⭐ NEW ~10 tests (G9/G10)

docs/mvp/MVP_1_3c_factor_framework_complete.md  ⭐ 本文
```

**规模**: ~400 Platform 代码 + ~200 shim/改造 + ~300 新测试 + ~80 Flag 脚本 ≈ 1000 行.

---

## 关键设计

### D1. FactorStatus 统一 (7 值 superset, DB 零迁移)

**DB 现状** (实测): `factor_registry` 无 CHECK constraint, status 现存 3 值 (active/warning/deprecated). Enum 加新值 **零迁移**.

**映射策略**:
- `interface.FactorStatus` (7 值) 为**唯一源**
- `engines/factor_lifecycle.py::FactorStatus` 改为 `FactorStatus = InterfaceFactorStatus` re-export (保 StrEnum 语义)
- **CRITICAL 不落 DB**: 老规则 `warning→critical (ratio<0.5 持续 20 天)` 改为 — 触发 critical 阈值时保 DB status=WARNING 但 publish `qm:ai:monitoring:critical_alert` 事件给 L2 人确认 (隐式, 不破坏老 factor_lifecycle_monitor.py 行为)
- **CANDIDATE / TESTING / INVALIDATED / RETIRED** 4 新状态: 由 onboarding (candidate→testing→active) 和人工 L2 (active→retired/invalidated) 写入, lifecycle monitor 不自动触发

### D2. G9 novelty_check (AST Jaccard)

```python
def novelty_check(self, spec: FactorSpec) -> bool:
    """G9 Gate — AST 相似度 > 0.7 → 拒绝 (铁律 12)."""
    from engines.mining.ast_dedup import AstDeduplicator
    if not spec.expression:
        return True  # 无表达式 (如 builtin 手写因子) 不走 AST, 依赖 G10
    dedup = AstDeduplicator()
    for active in self.get_active():
        if not active.expression:
            continue
        sim = dedup.compute_ast_similarity(spec.expression, active.expression)
        if sim > 0.7:
            logger.warning(
                "[G9] block: {new} vs {active} Jaccard sim={sim:.3f} > 0.7",
                new=spec.name, active=active.name, sim=sim,
            )
            return False
    return True
```

### D3. G10 hypothesis 强制

```python
def register(self, spec: FactorSpec) -> UUID:
    """onboarding 入口 — G9 + G10 必过."""
    # G10: 铁律 13
    hypo = (spec.hypothesis or "").strip()
    if not hypo or hypo.startswith("GP自动挖掘") or len(hypo) < 20:
        raise OnboardingBlocked(
            f"G10 失败: hypothesis 必须人工填写经济机制描述 (铁律 13), 现: {hypo!r}"
        )
    # G9: 铁律 12
    if not self.novelty_check(spec):
        raise OnboardingBlocked(f"G9 失败: {spec.name} AST 相似度 > 0.7 已有 ACTIVE 因子")
    # 入库 (DBFactorRegistry concrete)
    return self._insert_via_dal(spec)
```

`OnboardingBlocked` 在 `backend/platform/factor/registry.py` 定义 (`class OnboardingBlocked(RuntimeError)`, `# noqa: N818`).

### D4. PlatformLifecycleMonitor concrete

```python
class PlatformLifecycleMonitor(FactorLifecycleMonitor):
    def __init__(
        self,
        registry: DBFactorRegistry,
        ic_reader: Callable[[str, int], list[dict]],  # factor_name, lookback → tail rows
    ) -> None:
        self._registry = registry
        self._ic_reader = ic_reader

    def evaluate_all(self) -> list[TransitionDecision]:
        from engines.factor_lifecycle import evaluate_transition, count_days_below_critical
        decisions: list[TransitionDecision] = []
        for meta in self._registry.get_active():  # 只评估 ACTIVE + WARNING
            tail = self._ic_reader(meta.name, lookback=30)
            # 调 engines 纯规则 → 转 interface TransitionDecision
            ...
        return decisions
```

**关键**: 老 `scripts/factor_lifecycle_monitor.py` 保持 CLI API (`--dry-run` / `--factor`), 内部改调 `PlatformLifecycleMonitor.evaluate_all()` + 仍走 `_apply_transition` + StreamBus publish (保 MVP A Celery Beat 行为).

### D5. factor_onboarding.py L279 改造 (铁律 25 验代码)

```python
# 旧: _upsert_factor_registry 裸 INSERT INTO
# 新: 走 DBFactorRegistry.register (G9+G10 自动)
def _upsert_factor_registry(self, conn, factor_name, factor_expr, gate_result, ...) -> str:
    from backend.platform.factor.interface import FactorSpec
    from backend.platform.factor.registry import DBFactorRegistry, OnboardingBlocked
    from backend.platform.data.access_layer import PlatformDataAccessLayer

    dal = PlatformDataAccessLayer(lambda: conn)  # 复用 Service 层传入 conn
    registry = DBFactorRegistry(dal)
    spec = FactorSpec(
        name=factor_name,
        hypothesis=gate_result.get("hypothesis", ""),  # 空/GP默认 会被 G10 拒
        expression=factor_expr,
        direction=gate_result.get("direction", 1),
        category="alpha",
        pool="CANDIDATE",  # 新入 CANDIDATE, L2 人工确认 → ACTIVE
        author="gp",
    )
    return str(registry.register(spec))  # raises OnboardingBlocked if G9/G10 fail
```

### D6. FeatureFlag `use_db_direction` 注册 + 切 True

**当前状态实测**: `feature_flags` 表空, `use_db_direction` 未注册, 所以 `_PLATFORM_FLAG_DB.is_enabled(...)` 会 raise `FlagNotFound` 被 `except Exception: pass  # silent_ok` 吃掉, **signal_engine 实际走 Layer 3 hardcoded**. MVP 1.3b 的 3 层 fallback "切 Flag=True" 路径尚未真激活.

**新脚本** `scripts/registry/register_feature_flags.py`:

```python
flag_db.register(
    name="use_db_direction",
    default=True,  # MVP 1.3c 直接切 True (30/30 等价数学证明保证)
    removal_date="2026-06-01",  # 2 个月后强制清理 (Flag 不得永久化)
    description="MVP 1.3c: signal_engine.FACTOR_DIRECTION lookup 走 DBFactorRegistry (DB 权威). MVP 1.3d 稳定后删除 hardcoded dict.",
)
```

PT 重启 (`service_manager.ps1 restart fastapi celery celery-beat`) 后观察 3 天, 日志应见 `[signal_engine] DB direction lookup` 无 warning.

---

## 验收标准

| # | 项 | 目标 |
|---|---|---|
| 1 | `test_factor_registry.py` 扩 (16→36 tests) | ✅ PASS |
| 2 | `test_platform_lifecycle.py` ~15 tests | ✅ PASS |
| 3 | `test_factor_onboarding_gates.py` ~10 tests (G9/G10 边界 + OnboardingBlocked) | ✅ PASS |
| 4 | MVP 1.1-1.3b 锚点全保 (65+77+21+50+31 = 244 tests) | ✅ 不回归 |
| 5 | ruff check 新代码 | ✅ All checks passed |
| 6 | `regression_test --years 5` Flag=False (默认切前) | ✅ max_diff=0.0, Sharpe 0.6095 |
| 7 | `regression_test --years 5` Flag=True (切后) | ✅ max_diff=0.0 (30/30 hardcoded↔DB 数学证明保证) |
| 8 | 老 `scripts/factor_lifecycle_monitor.py --dry-run` | ✅ 仍检测 `reversal_20: active→warning` (MVP A 锚点行为不变) |
| 9 | `scripts/registry/register_feature_flags.py` 执行 | ✅ feature_flags 表新增 `use_db_direction=True` |
| 10 | PT 重启后首日日志 | ✅ 无 `[signal_engine] DB direction lookup failed` warning |
| 11 | 全量 pytest fail 数 | ≤ 32 (铁律 40 不增加, session 初为 32) |
| 12 | 老代码 git diff (非 Platform / tests / docs / migration) | 仅 `factor_onboarding.py` L279 改造 + `factor_lifecycle.py` shim + `factor_lifecycle_monitor.py` 内部改调 |
| 13 | Platform 严格隔离 AST 扫描 | ✅ 0 违规 (Platform 不 import `backend.app.*`) |

---

## 开工协议 (铁律 36 precondition 核查 — 全部已就绪)

- ✅ `DBFactorRegistry.get_direction` + 3 层 fallback 在位 (MVP 1.3b)
- ✅ `DAL.read_registry` 支持 status_filter / pool_filter (MVP 1.2a, 已验证 sqlite + live PG)
- ✅ `AstDeduplicator.compute_ast_similarity` 在位 (Jaccard, `backend/engines/mining/ast_dedup.py` L391)
- ✅ `engines.factor_lifecycle.evaluate_transition` + `count_days_below_critical` 纯规则在位 (MVP A)
- ✅ `DBFeatureFlag.register / is_enabled` 在位 (MVP 1.2), `feature_flags` 表存在
- ✅ `factor_registry` DB 无 CHECK constraint (status 加 testing/candidate/invalidated/retired 零迁移)
- ✅ `FactorMeta.expression` 字段存在 (MVP 1.3a 已对齐 DB 18 字段)

---

## 禁做 (铁律)

- ❌ 改 DataPipeline (_registry_check 留 MVP 1.3d)
- ❌ 删任何 `_constants.py` direction dict (留 MVP 1.3d)
- ❌ 改 `signal_engine.FACTOR_DIRECTION` hardcoded 内容 (保 regression 锚点 + Layer 3 fallback)
- ❌ 改 `factor_registry` DDL 加 status/pool CHECK constraint (零迁移更安全)
- ❌ 切 `use_db_direction=True` 前不先 `register` (必先落 DB 才能 Layer 1 生效)
- ❌ G9/G10 对 LEGACY 228 因子做回溯检查 (只作用于新 `register()`, 老数据不动)
- ❌ `evaluate_all()` 产生的 transition 直接改 DB status (仍走 `_apply_transition` + commit, 保 Service 不 commit 原则)

---

## 风险 + 缓解

| R | 描述 | 概率 | 缓解 |
|---|---|---|---|
| R1 | engines.FactorStatus shim 后 CRITICAL 消费方断裂 | 低 | engines shim 保 `CRITICAL` 常量名 alias 到 interface.WARNING, 老代码 `if status == FactorStatus.CRITICAL` 仍 truthy |
| R2 | G9 AST 对 LEGACY 228 因子产生误伤 | 低 | `novelty_check` 只遍历 `get_active()` 返的 CORE/PASS 因子 (MVP 1.3a 4 + 48 = 52 项), 不与 LEGACY 比对 |
| R3 | Flag=True 后 DB 查询失败 PT crash | 低 | 3 层 fallback 兜底 (MVP 1.3b 15 tests 已覆盖), `logger.warning` 后走 Layer 3 hardcoded |
| R4 | `factor_onboarding.py` 改造后 approval_queue 老数据 (hypothesis=`GP自动挖掘:`) 全部入库失败 | 中 | 设计上 G10 本就要拒这类 (铁律 13); approval_queue 数据流动性, 没积压 (生产现状) |
| R5 | 老 `scripts/factor_lifecycle_monitor.py` 改调 Platform 后 MVP A 周五 19:00 Celery Beat 行为漂移 | 中 | 保 CLI 层不变 (`--dry-run / --factor`), 内部走 `PlatformLifecycleMonitor.evaluate_all()`; dry-run 对照 `reversal_20: active→warning` 同结论 |

---

## 下一步 (MVP 1.3d 预告, 不在本 MVP 范围)

- DataPipeline `_registry_check` warn-mode → reject-mode
- 删 `_constants.py` 6 direction dict (观察 Flag=True 稳定 2 周后)
- 迁 4 test 的 `_constants` 直接 dict import 到 Platform registry 接口
- paired bootstrap p<0.05 集成 `FactorOnboardingPipeline.onboard`
- BH-FDR 累积校正 (依赖 FACTOR_TEST_REGISTRY 累积 M=84)

---

## 变更记录

- 2026-04-18 v1.0 设计稿落盘, 等 plan approval.
- 2026-04-17 v1.1 **已交付** — 用户批准 Scope B 后实施:
  - Day 1: Platform lifecycle concrete (21 tests PASS)
  - Day 2: DBFactorRegistry 4 method + G9/G10 (test_factor_registry 扩 16→39, PASS)
  - Day 3: factor_onboarding L279 改造 + 6 集成 tests + feature_flag apply + regression max_diff=0 (Sharpe 0.6095)
  - Day 4: 修 test_factor_onboarding.py 10 fail (G10 block fixture + mock Platform register) → 28/28 PASS
  - MVP 1.1-1.3c anchor 298 tests PASS 无回归, ruff 全 clean
  - feature_flags 表: use_db_direction=True 已 apply live PG
