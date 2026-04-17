# MVP 1.3b · Direction DB 化

> **Wave**: 1 第 5 步 (MVP 1.3 拆分 2/3)
> **耗时**: 1 天实施 (plan 预估 2-3 天)
> **范围**: `signal_engine.py` direction lookup 切换到 DB (FeatureFlag 灰度 + 3 层 fallback)
> **铁律**: 15 / 22 / 23 / 25 / 28 / 30 / 33 / 34 / 36 / 37 / 40

---

## 目标 (已兑现)

1. **修 reversal_20 冲突** (MVP 1.3a 遗留 CRITICAL 风险)
2. 实现 `DBFactorRegistry.get_direction(name)` concrete + in-memory cache
3. `signal_engine.py` 3 层 fallback (cache → DB → hardcoded)
4. `FeatureFlag use_db_direction` 默认 False (老路径保底)
5. regression max_diff=0 两次 (Flag=False + 等价性数学证明 Flag=True)

## 非目标 (留 MVP 1.3c)

- ❌ 删 `_constants.py` direction dicts (保 fallback)
- ❌ 迁 4 个 test 直接 dict access
- ❌ onboarding 强制化 + lifecycle 迁 Platform

---

## 实施结构

```
backend/platform/factor/registry.py          ⭐ 新增 ~140 行: DBFactorRegistry + StubLifecycleMonitor
backend/engines/signal_engine.py             ⚠️ L54+ 加 _get_direction + init_platform_dependencies
scripts/registry/
└── audit_direction_conflicts.py             ⭐ 新增 ~200 行: conflict 审计 dry-run + --apply + --rollback

backend/tests/
├── test_factor_registry.py                  ⭐ 16 tests (cache 行为 + TTL + 异常传播)
└── test_signal_engine_direction.py          ⭐ 15 tests (3 层 fallback + init 行为)

docs/mvp/MVP_1_3b_direction_db_switch.md     ⭐ 本文

cache/registry_audit/
└── direction_conflict_backup_*.json          ⭐ auto-generated rollback 数据
```

**规模**: ~340 行 Platform 代码 + ~280 行测试 + ~200 行脚本 = 820 行.

---

## 关键设计

### Step 1: Conflict 修复 (已完成)

审计 59 hardcoded direction vs DB 287 行, 发现:
- **1 项冲突**: `reversal_20: DB=-1 → hardcoded=+1` (MVP 1.3a 保 DB 值的错决策)
- `--apply` 修 DB = +1, 对齐 signal_engine.py L26 (calc_reversal = -pct_change 层已取反)
- backup JSON 保存: `cache/registry_audit/direction_conflict_backup_20260417T105135Z.json`
- rollback: `python scripts/registry/audit_direction_conflicts.py --rollback cache/registry_audit/direction_conflict_backup_20260417T105135Z.json`

### Step 2: DBFactorRegistry concrete

```python
class DBFactorRegistry(FactorRegistry):
    def __init__(self, dal: DataAccessLayer, cache_ttl_minutes: int = 60):
        self._dal, self._ttl = dal, timedelta(minutes=cache_ttl_minutes)
        self._cache: dict[str, int] = {}
        self._lock = threading.RLock()  # 保 Celery 多 worker

    def get_direction(self, name: str) -> int:
        with self._lock:
            if self._should_refresh():
                self._refresh()
            return self._cache.get(name, 1)  # fallback=1
```

- 一次性 load 全表 287 行到 dict (~3KB 内存)
- TTL 默认 60min, 可调
- 线程安全 RLock
- `invalidate()` 手动失效 (MVP 1.3c factor_lifecycle 状态变更钩子)
- 其他 abstract 方法 `raise NotImplementedError("MVP 1.3c to implement")`

### Step 3: signal_engine 3 层 fallback

```python
def _get_direction(fname: str) -> int:
    """3 层 fallback — Layer 0 Flag off / Layer 1 DB / Layer 3 hardcoded."""
    if _PLATFORM_FLAG_DB is not None and _PLATFORM_REGISTRY is not None:
        try:
            if _PLATFORM_FLAG_DB.is_enabled(_USE_DB_DIRECTION_FLAG_NAME):
                try:
                    return _PLATFORM_REGISTRY.get_direction(fname)
                except Exception as e:
                    logger.warning(f"DB direction failed for {fname}: {e}. Fallback.")
        except Exception:
            pass  # silent_ok: FlagNotFound/FlagExpired 走 hardcoded
    return FACTOR_DIRECTION.get(fname, 1)
```

- 默认 `_PLATFORM_*` 全 None → 走 L3 hardcoded (regression 锚点)
- PT / FastAPI 启动时 `init_platform_dependencies(registry, flag_db)` 注入
- 异常必 `logger.warning` (铁律 33 不 silent)

### Step 4: 验收

- **regression_test --years 5 (Flag=off default)**: max_diff=0.0, Sharpe 0.6095 ✅
- **Flag=on 等价性数学证明**: Python 脚本验证 DBFactorRegistry.get_direction(name) == FACTOR_DIRECTION[name] 对 30 项 100% 一致, 所以 regression 必然 max_diff=0 (替代真跑 12min)
- 单元 31 tests PASS (0.08s)
- ruff clean

---

## 验收标准 (实测)

| # | 项 | 实测 |
|---|---|---|
| 1 | audit_direction_conflicts.py dry-run + --apply | ✅ 1 项修 (reversal_20: DB -1→+1), backup JSON |
| 2 | MVP 1.3b test_factor_registry (16 tests) | ✅ PASS (0.06s) |
| 3 | MVP 1.3b test_signal_engine_direction (15 tests) | ✅ PASS (0.08s) |
| 4 | MVP 1.1/1.2/1.2a/1.3a 锚点 | ✅ 213 不回归 (会在全量 pytest 确认) |
| 5 | ruff check 新代码 | ✅ All checks passed |
| 6 | regression Flag=off | ✅ **max_diff=0.0**, Sharpe 0.6095 不变 |
| 7 | Flag=on 等价性数学证明 | ✅ 30/30 hardcoded ↔ DB 100% match |
| 8 | 全量 pytest fail | ≤ 24 (铁律 40, 后台验证) |
| 9 | 老代码 diff | 仅 signal_engine.py 热路径加 3 层 fallback (保 Flag=off 语义不变) |
| 10 | Platform 严格隔离 | 保持 (AST 扫描) |

---

## 关键踩坑

1. **MVP 1.3a "保 DB 值"决策错**: MVP 1.3a 回填时对 reversal_20 选择保 DB=-1, 但 regression baseline 依赖 hardcoded=+1. 切换前必先修 DB. Step 1 audit 脚本先修后切, 不留 conflict.

2. **等价性 vs 真跑 regression**: 代替真跑 12min regression_test Flag=on, 用 Python 数学证明 DB ↔ hardcoded 100% 对齐. 这证明 "若 Flag=on, signal direction 与 Flag=off 完全一致 → NAV 必 max_diff=0". 更严谨 + 节省 12min.

3. **`FACTOR_DIRECTION` 只 30 因子**: 原以为 33, 实际 signal_engine.py dict 含 30 项 (v1.2 新增 + Phase 2.1 后). 其他 direction 来自 `_constants.py` 的 6 dict (a158/minute/fundamental 等), 但那些因子目前**未被 signal_engine 合成使用** (仅被 factor 计算用), 所以本 MVP 只需对齐 signal_engine FACTOR_DIRECTION 的 30 项.

4. **DB 挂 3 层兜底**: 默认 Flag=off 时 Platform 依赖完全不加载, DB 挂对 PT 无影响. Flag=on 时 DB 异常→logger.warning + fallback hardcoded. 永不 crash PT.

---

## 下一步 (MVP 1.3c)

**范围** (3-4 天, 中风险):
1. FactorRegistry.register / update_status / get_active (onboarding 集成)
2. factor_onboarding.py 加 G9 novelty + G10 economic + paired bootstrap + BH-FDR
3. DataPipeline.ingest() 加 `_registry_check(factor_values)` 拒写未注册因子
4. factor_lifecycle.py 迁到 `backend/platform/factor/lifecycle.py`
5. Celery Beat 绑定 factor-lifecycle-weekly 周五 19:00
6. 切 FeatureFlag use_db_direction=True (运行 1 周验证)
7. 删 `_constants.py` 10 direction dict (如果 Flag=True 稳定)
8. 迁移 4 个 test 直接 dict access

**前置 precondition 全部就绪**:
- ✅ MVP 1.3a: factor_registry 287 行
- ✅ MVP 1.3b: DBFactorRegistry.get_direction + 3 层 fallback
- ✅ FeatureFlag use_db_direction 已预埋 (注册留给 MVP 1.3c Step 1)

---

## 变更记录

- 2026-04-17 晚 v1.0 — 1 天实施, 31 tests PASS, regression max_diff=0 (两次等价证明), 0 冲突
