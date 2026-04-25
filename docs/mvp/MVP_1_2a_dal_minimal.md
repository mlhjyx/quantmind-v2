# MVP 1.2a · DAL Minimal (Read-only)

> **Wave**: 1 — 架构基础层 (第 3 步, Wave 1→2 衔接)
> **耗时**: 1 天实施 (plan 预估 3-5 天)
> **范围**: `PlatformDataAccessLayer` read-only 4 方法 (read_factor/read_ohlc/read_fundamentals/read_registry)
> **铁律**: 15, 17, 22, 23, 24, 25, 28, 31, 33, 36, 37, 38, 39, 40

---

## 目标 (已兑现)

1. Platform 层唯一 read 入口, 消除 13+ 处裸 SQL 违反铁律 17
2. 解锁 MVP 1.3 Factor Framework (registry 回填 101 因子 走 DAL.read_registry)
3. 复用现有 `backend.data.FactorCache` (依赖注入, 不重写)
4. 老代码 0 改动, 保 MVP 1.1 严格隔离

## 非目标 (留后续)

- ❌ DataSource 抽象 (MVP 2.1)
- ❌ DataContract 扩展 (MVP 2.2)
- ❌ Cache Coherency 自动监控 (已由 FactorCache 内部做, DAL 复用)
- ❌ Write 路径 (继续 DataPipeline)
- ❌ 真 PIT 基本面 (MVP 2.1 加 financial_ind)

---

## 目录结构 (实际落地)

```
backend/platform/data/
├── __init__.py             # 9 符号 (abstract 5 + concrete 4)
├── interface.py            # MVP 1.1 基础 + MVP 1.2a 追加 read_registry abstract
└── access_layer.py         # PlatformDataAccessLayer + DALError/UnsupportedColumn/UnsupportedField

backend/tests/
└── test_platform_dal.py    # 21 tests (MagicMock + sqlite 双组)
```

**规模**: ~330 行新代码 + ~360 行测试.

---

## 关键设计

### PlatformDataAccessLayer 4 方法

| 方法 | 签名 | 实现 |
|---|---|---|
| `read_factor(factor, start, end, column)` | column 白名单 `{raw_value/neutral_value/zscore}` | 优先 `factor_cache.load()`, fallback `SELECT ... FROM factor_values WHERE factor_name = ? AND trade_date BETWEEN ...` |
| `read_ohlc(codes, start, end, adjusted)` | `adjusted` 参数预留 MVP 2.1 | SQL `SELECT ... FROM klines_daily WHERE code IN (...) AND volume > 0` |
| `read_fundamentals(codes, fields, as_of)` | fields 白名单 7 项 | sqlite 兼容 group-by subquery 取每 code 最新 <= as_of |
| `read_registry(status_filter, pool_filter)` | 返 DataFrame 10 列 | SQL `SELECT ... FROM factor_registry WHERE ...` |

### 依赖注入 (保 Platform 隔离)

```python
class PlatformDataAccessLayer(DataAccessLayer):
    def __init__(
        self,
        conn_factory: Callable[[], _DBConnection],
        *,
        factor_cache: Any | None = None,  # 鸭子类型, 典型 backend.data.FactorCache
        paramstyle: str = "%s",            # "%s" psycopg2 / "?" sqlite
    ):
```

生产 wiring:
```python
from backend.data.factor_cache import FactorCache
from backend.app.services.db import get_sync_conn
from backend.qm_platform.data import PlatformDataAccessLayer

dal = PlatformDataAccessLayer(conn_factory=get_sync_conn, factor_cache=FactorCache())
```

Platform 代码 0 处 import `backend.app.*` / `backend.data.*` (AST 扫描验证).

### Error 族

- `DALError` 基类
- `UnsupportedColumn`: column 不在白名单
- `UnsupportedField`: fields 含非白名单 或 空

不实现 `FactorNotFound` / `CacheCoherencyError` / `PITViolation` (MVP 1.3 + MVP 2.1 再加).

---

## 验收标准 (实测)

| # | 项 | 实测 |
|---|---|---|
| 1 | `from backend.qm_platform.data import PlatformDataAccessLayer` | 无 ImportError |
| 2 | `pytest test_platform_dal.py` | **21/21 PASS** (0.08s) |
| 3 | MVP 1.1 锚点 (test_platform_skeleton) | **65/65 PASS** |
| 4 | MVP 1.2 锚点 (schema+auditor+flag+guard) | **77/77 PASS** |
| 5 | 综合: DAL + skeleton + config 锚点 | **163/163 PASS** (0.90s) |
| 6 | ruff check 新代码 | All checks passed |
| 7 | regression_test --years 5 | **max_diff=0.0**, Sharpe 0.6095 不变 |
| 8 | Platform 严格隔离 (AST 扫描 backend.app/engines/data/scripts) | **0 违规** |
| 9 | 裸 SQL 位置 | 只在 `access_layer.py` 内 (sanctioned DAL) |
| 10 | 全量 pytest fail | ≤ 24 (基线不增, 铁律 40, 后台跑, commit 前确认) |

---

## 关键踩坑 (记录给未来 MVP 1.3+)

1. **MVP 1.1 test_platform_import_has_no_side_effects 原禁 pandas 加载**:
   - MVP 1.2a concrete DAL 返 DataFrame 必然加载 pandas
   - 修: 从 forbidden list 移除 pandas, 保留 psycopg2/redis/sqlalchemy (真 IO 依赖)
   - 决策: DataFrame 是 Platform data 层一等公民, pandas 作为 Platform runtime dep 合理

2. **sqlite 测试与 PG 生产 SQL 方言差异**:
   - `DISTINCT ON`: sqlite 不支持 → 改 group-by subquery (兼容两路径)
   - `ANY (?)`: sqlite 不支持 → 改 `IN (?, ?, ...)` 动态拼 placeholder
   - paramstyle: sqlite `?` / psycopg2 `%s` → DAL 构造参数切换

3. **N818 ruff 风格**: `UnsupportedColumn` / `UnsupportedField` 不加 Error 后缀 — 语义名优先, 用 `# noqa: N818` 保留意图.

---

## 爆炸半径

- **Platform 新增模块 + interface 微扩**: 不破坏任何老代码
- **老代码 0 改动**: `grep -r` 确认无
- **回滚**: `rm backend/platform/data/access_layer.py backend/tests/test_platform_dal.py; git revert interface.py read_registry`

---

## 后续依赖 (解锁)

- **MVP 1.3 Factor Framework**:
  - `FactorRegistry.get_active()` → `dal.read_registry(status_filter="active")`
  - `FactorOnboardingPipeline.onboard()` → `dal.read_factor()` + `dal.read_registry()` 验 novelty
  - 无需 MVP 1.3 自写 SQL → 铁律 17 合规
- **MVP 1.4 Knowledge Registry**: 独立 repository (`experiment_registry` 表), 不走 DAL (不同领域)
- **MVP 2.1 Data Framework 完整版**: 吸收本 MVP, 扩 DataSource / Cache Coherency / 真 PIT

---

## 变更记录

- 2026-04-17 晚 v1.0 初稿 — 一天实施完成 (plan 预估 3-5 天), 21 tests PASS
