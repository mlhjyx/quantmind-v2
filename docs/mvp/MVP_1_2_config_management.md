# MVP 1.2 · Config Management

> **Wave**: 1 — 架构基础层 (第 2 步)
> **耗时**: 1 天实施 (plan 预估 3-5 天, 实际骨架 + shim 收编轻量)
> **范围**: Pydantic ConfigSchema 7 类 (60+ 参数) + Loader (env>yaml>default) + Auditor (校验+审计日志) + DB-backed FeatureFlag + `config_guard.py` 改造为 shim
> **铁律**: 15 (regression 复现), 22 (文档跟随代码), 23 (独立可执行), 24 (≤ 2 页), 25 (变更前验代码), 32 (Service 不 commit), 33 (禁 silent failure), 34 (配置 SSOT), 40 (测试债不增长)

---

## 目标 (已兑现)

1. Pydantic Schema 驱动校验 (替代 6 参数硬编码), 扩展字段只改映射表
2. `ConfigLoader` 三层合并 (env > yaml > default) 消除 `.env` / yaml / Python 常量漂移
3. `ConfigAuditor.dump_on_startup` → `logs/config_audit_YYYY-MM-DD.json` (含 config_hash + git_commit)
4. DBFeatureFlag (binary on/off + removal_date 过期守护)
5. 老 `config_guard.py` 改为 shim (`check_config_alignment` / `ConfigDriftError`) 保 API 兼容
6. 不改 `pt_live.yaml` / `.env` / PT 运行时行为

## 非目标 (留后续 MVP)

- ❌ 覆盖 150 项参数 (本 MVP 60+ 渐进)
- ❌ AB 实验 / percentage rollout / user bucketing
- ❌ 迁移老 `app/services/config_loader.py` (MVP 1.3)
- ❌ DB 支持热更新 (PT 参数变更走重启)

---

## 目录结构 (实际落地)

```
backend/platform/config/
├── __init__.py           # 导出 23 符号 (interfaces + concrete + dataclass + errors)
├── interface.py          # MVP 1.1 abstract (不动)
├── schema.py             # 7 Pydantic Schema + RootConfigSchema + PlatformConfigSchema wrapper
├── loader.py             # PlatformConfigLoader + env 映射表 + yaml 结构适配
├── auditor.py            # PlatformConfigAuditor (check_alignment + dump_on_startup) + ConfigDriftError
└── feature_flag.py       # DBFeatureFlag + FlagNotFound + FlagExpired

backend/migrations/
└── feature_flags.sql     # DB 表 + trigger 维护 updated_at (已应用到 live PG)

backend/engines/config_guard.py  # 改造为 shim, 老 API (check_config_alignment/ConfigDriftError) 转调 Platform

backend/tests/
├── test_config_schema.py    # 29 tests (Schema 默认/值域/env>yaml 优先级 + loader helpers)
├── test_config_auditor.py   # 15 tests (三源对齐 + dump_on_startup + 漂移场景)
├── test_feature_flag.py     # 9 tests (sqlite in-memory, 不碰 live PG)
└── test_config_guard.py     # 24 tests (老测试, shim 等价 PASS)

logs/
└── config_audit_YYYY-MM-DD.json  # 运行时产出 (gitignore 已覆盖)
```

**规模**: ~1300 行新代码 + ~390 行测试 + 25 行 SQL = 1715 行.

---

## 关键设计

### Pydantic Schema 7 类 (60+ 参数, 2 层 nested)

```
RootConfigSchema
├── strategy: StrategyConfigSchema          10 字段 (factor_names/top_n/SN/turnover_cap/...)
├── execution: ExecutionConfigSchema
│   ├── slippage: SlippageConfigSchema      9 字段 (volume_impact/Y_*/base_bps_*)
│   ├── costs:    CostConfigSchema          5 字段 (commission/stamp_tax/...)
│   └── pms:      PMSConfigSchema           2 字段 + list[PMSTier] × 3
├── universe: UniverseConfigSchema          5 字段 (exclude_*/min_listing_days)
├── backtest: BacktestConfigSchema          4 字段 (capital/benchmark/lot_size/volume_cap)
├── database: DatabaseConfigSchema          3 字段 (url/pool_size/echo)
└── paper_trading: PaperTradingConfigSchema 4 字段 (strategy_id/initial_capital/QMT_*)
```

**全员 `extra="forbid"`** — 拼错字段名立即 fail (防 F62 类事故).

### env > yaml > default 优先级

env 映射表 (10 项显式):
```
PT_TOP_N              → strategy.top_n
PT_INDUSTRY_CAP       → strategy.industry_cap
PT_SIZE_NEUTRAL_BETA  → strategy.size_neutral_beta
EXECUTION_MODE        → execution.mode
PMS_ENABLED           → execution.pms.enabled
DATABASE_URL          → database.url
PAPER_STRATEGY_ID     → paper_trading.strategy_id
PAPER_INITIAL_CAPITAL → paper_trading.initial_capital
QMT_PATH              → paper_trading.qmt_path
QMT_ACCOUNT_ID        → paper_trading.qmt_account_id
```

其他 `.env` 参数 (LOG_LEVEL / TUSHARE_TOKEN / ADMIN_TOKEN) 继续由 `backend/app/config.py::Settings` 管, 不进 Platform Schema (非策略参数, 纳入 Schema 无价值).

### Auditor 三源对齐 (Schema 驱动)

`_TRIPLE_SOURCE_FIELDS` 映射表 (5 条) 代替 old config_guard 硬编码. 新字段加一行即生效:

| 参数 | .env | yaml | python |
|---|---|---|---|
| top_n | PT_TOP_N | strategy.top_n | SignalConfig.top_n |
| industry_cap | PT_INDUSTRY_CAP | strategy.industry_cap | SignalConfig.industry_cap |
| size_neutral_beta | PT_SIZE_NEUTRAL_BETA | strategy.size_neutral_beta | SignalConfig.size_neutral_beta |
| turnover_cap | — | strategy.turnover_cap | SignalConfig.turnover_cap |
| rebalance_freq | — | strategy.rebalance_freq | SignalConfig.rebalance_freq |
| factor_list | — | strategy.factors[].name | SignalConfig.factor_names |

任一漂移 → `ConfigDriftError` (铁律 34 fail-loud, 不允许 warning).

### Audit 日志格式 (`logs/config_audit_YYYY-MM-DD.json`)

```json
[
  {
    "timestamp_utc": "2026-04-17T...",
    "caller": "pt_start",
    "git_commit": "13873fe...",
    "config_hash": "d84e9cc9026f5cdf",
    "config": { "strategy": {...}, "execution": {...}, ... }
  }
]
```

同日多次启动 append. config_hash = sha256 of canonical JSON (sort_keys), 稳定复现 (铁律 15 锚点).

### FeatureFlag binary on/off

DB 表:
```sql
CREATE TABLE feature_flags (
    name TEXT PRIMARY KEY,
    enabled BOOLEAN DEFAULT FALSE,
    removal_date DATE NOT NULL,
    description TEXT NOT NULL,
    created_at / updated_at TIMESTAMPTZ
);
```

API:
- `is_enabled(name)` → bool; 过期 raise `FlagExpired`; 未注册 raise `FlagNotFound`
- `register(name, default, removal_date, description)` → UPSERT; `removal_date` 早于今天 raise `ValueError`
- `list_all()` → 按 name 排序 list

依赖注入 `conn_factory: Callable[[], Connection]` (不 import `backend.app.services.db`, 保 Platform 隔离).

---

## 验收标准 (实测)

| # | 项 | 实测 |
|---|---|---|
| 1 | `from backend.platform.config import ...` | 23 符号无 ImportError |
| 2 | MVP 1.2 tests (schema + auditor + feature_flag) | **53 PASS** (0.30s) |
| 3 | 老 `test_config_guard.py` (shim 等价) | **24 PASS** |
| 4 | `test_platform_skeleton` (MVP 1.1 锚点) | **65 PASS** |
| 5 | ruff check 新代码 | All checks passed |
| 6 | regression_test --years 5 | **max_diff=0.0**, Sharpe 0.6095 不变 |
| 7 | 全量 pytest fail ≤ 24 (本轮基线, 铁律 40) | (后台运行中, commit 前确认) |
| 8 | DB migration 已应用到 live PG | feature_flags 表存在, 0 行 |
| 9 | 老代码 diff (backend/app/* etc.) | 空 (只改 backend/engines/config_guard.py shim) |

---

## 爆炸半径

- **Platform 新增模块**: 未被任何老代码 import, 不触发运行时
- **`config_guard.py` shim**: 老 API (`check_config_alignment` / `ConfigDriftError`) 签名+行为一致, 老 24 test PASS 证明
- **`feature_flags` 表**: 新增表, 不影响任何现有表
- **回滚**: `drop table feature_flags; revert backend/engines/config_guard.py; rm -rf backend/platform/config/{schema,loader,auditor,feature_flag}.py backend/migrations/feature_flags.sql`

## 风险

| 风险 | 缓解 |
|---|---|
| MVP 1.3 Factor Framework 迁移时 registry 字段未入 Schema | 本 Schema 主要覆盖 PT 策略+执行, Factor registry 留 MVP 1.3 增字段 |
| `backend/platform/` 被 sys.path insert(0) 会覆盖 stdlib platform | auditor.py 走 append 保 stdlib 优先, 测试用 .venv python 验证通过 |
| Pydantic nested + yaml 结构差 | loader `_transform_yaml_for_schema` 处理 (factors 列表 / slippage 嵌套) |

## 后续依赖 (解锁)

- **MVP 1.2a DAL Minimal** (Blueprint v1.4 新增, Wave 1→2 衔接层)
- **MVP 1.3 Factor Framework** (factor_registry 回填 + direction 走 DB + onboarding 强制)
- **MVP 1.4 Knowledge Registry** (ExperimentRegistry 表)

## 变更记录

- 2026-04-17 v1.0 初稿 — MVP 1.2 plan 批准 + 当天实施 (Day 1-3 压缩到 1 天)
- 实施顺序: Day 1 (schema + loader + 29 tests) → Day 2 (auditor + feature_flag + migration + 24 tests) → Day 3 (shim 改造 + 老 test PASS + ruff + regression + 文档)
