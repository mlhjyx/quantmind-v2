# MVP 1.4 · Knowledge Registry — Wave 1 完结最后一步

> **Wave**: 1 第 7 步 (Wave 1 终点)
> **耗时**: 3-4 天 (Day 1 DB migration + 框架 / Day 2 ExperimentRegistry + FailedDirectionDB concrete / Day 3 ADRRegistry + migration script + 5 ADR 补录 / Day 4 测试 + 验收 + commit)
> **风险**: 低-中 (纯新表, 不影响现有路径; search_similar 采用 PG LIKE 简路径)
> **Scope B 平衡** (用户批准): ExperimentRegistry + FailedDirectionDB + ADRRegistry 全套 concrete + 补录 5 ADR
> **铁律**: 22 / 23 / 24 / 25 / 32 / 33 / 36 / 37 / 38 / 40

---

## 目标 (Scope B)

1. **新建 `platform_experiments` / `failed_directions` / `adr_records` 3 表** (D1/D2: 新建不混用 mining_knowledge 和老 experiments)
2. **`DBExperimentRegistry` concrete** — register / complete / search_similar (D3: PG LIKE + 关键词)
3. **`DBFailedDirectionDB` concrete** — add / check_similar / list_all
4. **`DBADRRegistry` concrete** — register / supersede / get_by_id / list_by_ironlaw
5. **一次性 migration script** (D4): 扫 `docs/research-kb/failed/*.md` + `CLAUDE.md` L474 表格 → `failed_directions` 入库 (~30 行)
6. **补录 5 ADR** (D5/D6): ADR-001..005 → `docs/adr/` markdown + `adr_records` 入库
7. **Blueprint 验收对齐**: 新实验 API 可用, 过去 3 月实验查询 < 1s

## 非目标 (明确留后续)

- ❌ pgvector embedding / 语义 search (留 Wave 2+, MVP 1.4 LIKE 已满足 ~30-100 行 scale)
- ❌ CLAUDE.md ↔ DB 双向同步 hook (单向 migration 即可)
- ❌ AI Agent pre-check 集成 (Wave 3 AI 闭环做)
- ❌ 改造 `mining_knowledge` 表 (GP 挖掘专用, MVP 1.4 不动)
- ❌ 老 `experiments` 表 drop (只保留 + 不用, 避免破坏其他引用)

## 实施结构

```
backend/migrations/
├── knowledge_registry.sql              ⭐ NEW ~120 行 (3 表 + 索引 + GIN tags + trigger updated_at)
└── knowledge_registry_rollback.sql     ⭐ NEW emergency rollback

backend/platform/knowledge/
├── interface.py                        ⚠️ MVP 1.1 已锁, 本 MVP 不动
├── registry.py                         ⭐ NEW ~500 行:
│                                          DBExperimentRegistry + DBFailedDirectionDB
│                                          + DBADRRegistry + error types
└── errors.py                           (内嵌在 registry.py, 不单拆)

scripts/knowledge/
├── migrate_research_kb.py              ⭐ NEW ~250 行 (扫 md + 解析 CLAUDE.md 表格 → DB)
└── register_adrs.py                    ⭐ NEW ~120 行 (补录 5 ADR 从 docs/adr/*.md → DB)

docs/adr/                               ⭐ NEW 目录
├── README.md                           ⭐ ADR 模板 + 索引
├── ADR-001-platform-package-name.md   ⭐
├── ADR-002-pead-as-second-strategy.md ⭐
├── ADR-003-event-sourcing-streambus.md⭐
├── ADR-004-ci-3-layer-local.md        ⭐
└── ADR-005-critical-not-db-event.md   ⭐ (MVP 1.3c 本 session 决策)

backend/tests/
├── test_knowledge_experiments.py       ⭐ NEW ~12 tests
├── test_knowledge_failed_directions.py ⭐ NEW ~10 tests
├── test_knowledge_adrs.py              ⭐ NEW ~8 tests
└── test_knowledge_migration.py         ⭐ NEW ~3 tests (迁移 script sample)

docs/mvp/MVP_1_4_knowledge_registry.md   ⭐ 本文
```

**规模**: ~800 Platform 代码 + ~370 scripts + ~400 新测试 + 5 ADR markdown (~600 行) ≈ 2200 行.

---

## 关键设计

### D1. `failed_directions` 表 (新建, 不复用 mining_knowledge)

**理由**: `mining_knowledge` schema (factor_hash/ic_stats/embedding/failure_mode/run_id) 是 GP 挖掘**因子级**失败记录; `FailedDirectionDB` 是**研究方向级** (biweekly-rebalance / ML E2E / 微盘效应). 语义不同, 共表会污染。

```sql
CREATE TABLE failed_directions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    direction TEXT NOT NULL UNIQUE,            -- "双周调仓" / "ML E2E Sharpe > 等权"
    reason TEXT NOT NULL,                       -- 失败原因
    evidence JSONB NOT NULL DEFAULT '[]'::jsonb,-- commit/report 路径 list
    severity VARCHAR(16) NOT NULL DEFAULT 'terminal',  -- terminal / conditional
    source VARCHAR(64),                         -- "CLAUDE.md" / "docs/research-kb/failed/xxx.md" / "manual"
    tags TEXT[] DEFAULT ARRAY[]::TEXT[],        -- ["ml", "portfolio", "regime"]
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_failed_dirs_severity ON failed_directions(severity);
CREATE INDEX ix_failed_dirs_tags_gin ON failed_directions USING GIN(tags);
```

### D2. `platform_experiments` 表 (新建 ≠ 老 `experiments`)

```sql
CREATE TABLE platform_experiments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    hypothesis TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'running',  -- running / success / failed / inconclusive
    author VARCHAR(64) NOT NULL,                     -- 提出人 / Agent ID
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    verdict TEXT,
    artifacts JSONB NOT NULL DEFAULT '{}'::jsonb,   -- {"report": "path", "commit": "sha"}
    tags TEXT[] DEFAULT ARRAY[]::TEXT[]
);
CREATE INDEX ix_platform_exp_status ON platform_experiments(status, started_at DESC);
CREATE INDEX ix_platform_exp_tags_gin ON platform_experiments USING GIN(tags);
```

老 `experiments` 表 (0 rows, 使用方 grep 0 hit) 保留不动 (FK/外部脚本可能有残留引用, MVP 1.5 再清理)。

### D3. `adr_records` 表 + docs/adr/ 目录

```sql
CREATE TABLE adr_records (
    adr_id VARCHAR(16) PRIMARY KEY,          -- "ADR-001"
    title TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,             -- proposed/accepted/deprecated/superseded_by:ADR-NNN
    context TEXT NOT NULL,
    decision TEXT NOT NULL,
    consequences TEXT NOT NULL,
    related_ironlaws INTEGER[] DEFAULT ARRAY[]::INTEGER[],
    file_path TEXT,                          -- docs/adr/ADR-001-*.md
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ix_adr_ironlaws_gin ON adr_records USING GIN(related_ironlaws);
```

**ADR 双源**: markdown 是人类可读 + 版本控制权威, DB 是查询用 (list_by_ironlaw / get_by_id). Migration script 双向写 (md 扫出 → DB 落地)。

### D4. search_similar / check_similar — PG LIKE 简路径

```python
def search_similar(self, hypothesis: str, k: int = 5) -> list[ExperimentRecord]:
    """MVP 1.4: LIKE + 关键词提取 (简路径, 足够 30-100 行 scale).

    未来 Wave 2+ 若记录 > 1000 行升级 pg_trgm 或 pgvector embedding.
    """
    keywords = [w for w in hypothesis.split() if len(w) > 2][:5]
    conditions = " OR ".join([f"hypothesis ILIKE %s" for _ in keywords])
    sql = f"""
        SELECT ... FROM platform_experiments
        WHERE {conditions}
        ORDER BY started_at DESC LIMIT %s
    """
    params = [f"%{w}%" for w in keywords] + [k]
    ...
```

类似 `FailedDirectionDB.check_similar`.

### D5. `migrate_research_kb.py` 一次性迁移 (D4 决策)

```python
# 扫 docs/research-kb/failed/*.md → failed_directions
# 解析 CLAUDE.md L474-L512 表格 → failed_directions (source="CLAUDE.md")
# 扫 docs/research-kb/findings/ → platform_experiments (status="success", 完成态)
# 扫 docs/research-kb/experiments/ → platform_experiments (status=从 yaml frontmatter)

# dry-run + --apply 模式, idempotent (ON CONFLICT (direction) DO UPDATE)
```

预期迁移结果:
- `failed_directions`: 8 (research-kb/failed) + ~25 (CLAUDE.md 表格) = **~30 行** (去重后)
- `platform_experiments`: 9 (findings) + 1 (experiments) = **10 行**
- `adr_records`: 5 (ADR-001..005)

### D6. 补录 5 ADR

| ADR | 标题 | 关联铁律 | 来源 |
|---|---|---|---|
| **001** | Platform 包名 `backend.platform` | 38 (Blueprint 真相源) | `memory/project_platform_decisions.md` |
| **002** | 第 2 策略: PEAD Event-driven | 38 | 同上 |
| **003** | Event Sourcing: StreamBus + PG (非 EventStoreDB) | 22, 38 | 同上 |
| **004** | CI 3 层本地 (pre-commit + pre-push + daily full) | 22, 40 | 同上 |
| **005** | MVP 1.3c CRITICAL 不落 DB 走 critical_alert 事件 | 33 (禁 silent) | 本 session MVP 1.3c D1 |

每 ADR 一个 markdown 文件 (~120 行), 按 `docs/adr/ADR-NNN-slug.md` 命名, 入 DB 时 `register()` 自动解析 frontmatter。

### D7. DBFactorRegistry 模式复用

ExperimentRegistry / FailedDirectionDB / ADRRegistry 都走 MVP 1.3b 同款模式:
- `conn_factory: Callable` 依赖注入 (写路径)
- 可选 `paramstyle: str = "%s"` 双路径 (psycopg2 / sqlite 测试)
- 所有写路径 `conn.commit()` 一次性 (Platform 原子操作, 铁律 32 的 Platform 例外, 同 DBFeatureFlag)

---

## 验收标准

| # | 项 | 目标 |
|---|---|---|
| 1 | `backend/migrations/knowledge_registry.sql` apply live PG | ✅ 3 表 + 索引建成 |
| 2 | `test_knowledge_experiments.py` (12 tests) register/complete/search_similar | ✅ PASS |
| 3 | `test_knowledge_failed_directions.py` (10 tests) add/check/list | ✅ PASS |
| 4 | `test_knowledge_adrs.py` (8 tests) register/supersede/get/list_by_ironlaw | ✅ PASS |
| 5 | `test_knowledge_migration.py` (3 tests) md 解析 sample | ✅ PASS |
| 6 | MVP 1.1-1.3c 锚点 (298 tests) | ✅ 不回归 |
| 7 | ruff check 新代码 | ✅ All checks passed |
| 8 | `migrate_research_kb.py --apply` 入库 | ✅ failed_directions ≥ 25, platform_experiments ≥ 8 |
| 9 | `register_adrs.py --apply` 入库 | ✅ adr_records = 5 |
| 10 | `docs/adr/` 5 个 markdown + README.md | ✅ 存在 |
| 11 | regression_test --years 5 | ✅ max_diff=0 (不触 signal/backtest 路径) |
| 12 | 全量 pytest fail | ≤ 24 (MVP 1.3c baseline) |
| 13 | 老代码 git diff | 仅 CLAUDE.md + sprint_state 更新, 老 signal/onboarding/backtest 0 改动 |
| 14 | Blueprint 验收 "查询过去 3 个月实验 < 1s" | ✅ 查空表即毫秒级, 满表 30 行也 < 1s |

---

## 开工协议 (铁律 36 precondition 全部就绪)

- ✅ MVP 1.1 Knowledge interface (ABC + 3 Record dataclass) 锁定
- ✅ MVP 1.2a DAL 可用 (本 MVP 不用 DAL, 直接 conn_factory)
- ✅ MVP 1.3 DBFactorRegistry 模式可套用 (register/_insert/conn_factory/paramstyle)
- ✅ `docs/research-kb/` 23 markdown 源数据就绪
- ✅ `CLAUDE.md` L474 已知失败表格可解析 (Markdown table)
- ✅ PG gen_random_uuid() 可用 (MVP 1.3b apply 过 pgcrypto? — 查 MVP 1.3a 实际用 uuid_generate_v4 / gen_random_uuid 待验)

---

## 禁做 (铁律)

- ❌ 不改 `mining_knowledge` 表 (GP 专用, 语义隔离)
- ❌ 不改 老 `experiments` 表 (0 rows 保留, MVP 1.5 再清理)
- ❌ 不动 CLAUDE.md 表格格式 (migration 适配现状, 不反向改 CLAUDE.md)
- ❌ 不做 pgvector / embedding (留 Wave 2+, LIKE 够用)
- ❌ 不做 CLAUDE.md ↔ DB 双向同步 hook (单向 migration)
- ❌ 不引 AI Agent 自动调 check_similar (Wave 3 再接)

---

## 风险 + 缓解

| R | 描述 | 概率 | 缓解 |
|---|---|---|---|
| R1 | CLAUDE.md 表格解析失败 (格式非标准 markdown table) | 中 | migration script dry-run 输出解析结果, 人工 review 后 --apply |
| R2 | LIKE search 性能 > 1s (记录过多) | 低 | 30-100 行级别 PG LIKE 极快, Wave 2+ 若超 1000 再升级 |
| R3 | failed_directions UNIQUE(direction) 冲突 | 低 | migration ON CONFLICT DO UPDATE 幂等 |
| R4 | ADR markdown frontmatter 格式差异 | 中 | register_adrs.py dry-run + 严格 yaml.safe_load |
| R5 | 老 `experiments` 表 0 row 保留可能被其他脚本误用 | 低 | 注释 DEPRECATED, 不删 (FK 外部引用已 grep=0) |
| R6 | 补录 5 ADR 选得不对 | 低 | 5 个都来自 `memory/project_platform_decisions.md` 或本 session 明确决策, 锚点扎实 |

---

## 下一步 (MVP 2.1 预告, 不在本 MVP 范围)

- Wave 2 MVP 2.1 Data Framework 完整版 (DataSource 抽象 + DataContract 扩展全 10 表)
- 老 `experiments` 表 drop (MVP 1.5 or 2.x 清理)
- pgvector embedding 升级 search_similar (若 > 1000 记录)
- AI Agent 集成 check_similar (Wave 3 AI 闭环)

---

## 变更记录

- 2026-04-17 v1.0 设计稿落盘, 等 plan approval.
- 2026-04-17 v1.1 **已交付** — 用户 approval + plan file + 实施:
  - Day 1: migration SQL 建 3 表 (platform_experiments / failed_directions / adr_records) apply live PG + 10 indexes
  - Day 2: `backend/platform/knowledge/registry.py` 3 concrete (DBExperimentRegistry / DBFailedDirectionDB / DBADRRegistry) ~700 行 + 33 unit tests PASS
  - Day 2-3: `docs/adr/` README + 5 ADR markdown (ADR-001..005 补录)
  - Day 3: 2 migration scripts (migrate_research_kb + register_adrs) + 5 parser tests PASS
  - Day 4: Apply migrations → **DB 行数 25+39+5 都超设计稿目标** (8/25/5). ruff clean + MVP 1.1-1.4 anchor 336 PASS + regression 5yr max_diff=0 + pytest baseline 比对
  - Wave 1 正式完结 (6/6 MVP 全交付)
