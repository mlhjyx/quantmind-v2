# PN-001 — Automation-Level Persistence (D1 O8)

> **Loop iteration**: iter 10 (L4+R Inner-loop-B, spec §10 step 3 design)
> **Trigger**: Frontend `setAutomationLevel()` POSTs to non-existent `/api/pipeline/automation-level` → 404 today (API_COVERAGE §6 O8 orphan)
> **Severity**: Feature-level — §6 8-trigger STOP self-check: NEGATIVE(详 §4)
> **§7 重蹈 defense**: PASS — 0 permanent-dead / conditional-fail precedent(LL + research-kb fresh-scan iter 10,UI infra novel territory)

## §1 Background

`PipelineConsole.tsx` 通过 `setAutomationLevel(level: AutomationLevel)` 让 user 选择 pipeline 自动化级别(L0-L4 per L4R spec semantics)。Frontend 已 wired,见 `frontend/src/api/pipeline.ts:163-167`:

```typescript
export async function setAutomationLevel(level: AutomationLevel): Promise<void> {
  // NOTE: No backend endpoint exists yet. PUT /api/pipeline/automation-level is not
  // implemented in backend/app/api/pipeline.py. Will return 404 until added.
  await apiClient.put("/pipeline/automation-level", { level });
}
```

Backend 当前 0 endpoint → 任何 user 调整 = 404。Audit 确认: `backend/app/services/param_defaults.py` 是 backend 唯一 reference "automation level" 之处,但是 defaults 逻辑,非 user-settable persistence。

## §2 Design choice

### §2.1 Schema — singleton `pipeline_settings` table

```sql
CREATE TABLE IF NOT EXISTS pipeline_settings (
    id               INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton enforce
    automation_level VARCHAR(8) NOT NULL DEFAULT 'L0',
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by       VARCHAR(64)
);

INSERT INTO pipeline_settings (id, automation_level)
VALUES (1, 'L0')
ON CONFLICT (id) DO NOTHING;
```

**为何 singleton(不走 generic key-value)**:
- Smallest spec-fitting(per iter-9 RESUME POINT "smallest-design 候选")
- `CHECK (id = 1)` 强制 1 row,0 orphan row 风险
- 后续新 pipeline setting 直接 ALTER TABLE ADD COLUMN,简单可演进
- 避开 JSONB / 反序列化 / 类型校验复杂性 — `automation_level` 就是 typed enum

### §2.2 Endpoint contract

| Method | Path | Body | Response | Status |
|---|---|---|---|---|
| GET | `/api/pipeline/automation-level` | — | `{ level: "L0\|L1\|L2\|L3\|L4" }` | 200 |
| PUT | `/api/pipeline/automation-level` | `{ level: AutomationLevel }` | `{ level: ... }` | 200 |

- **Auth**: unguarded(沿用 `factors.py:/{name}/archive` 同文件 sibling POST 体例;localhost-bound 单 user;0 trading-path 触碰)
- **Validation**: `level` 必须 ∈ {`L0`,`L1`,`L2`,`L3`,`L4`}(FastAPI pydantic `Literal`),非法 → 422
- **Concurrency**: 单 user / 低频写,不加显式锁;`UPDATE` 原子性 sufficient
- **Audit**: `updated_at` + `updated_by`(default NULL,future user-auth 接管时填充)

### §2.3 `GET /api/pipeline/status` 整合 —— 本 iter scope 外

Existing `/pipeline/status` 当前 contract 跟 frontend `PipelineStatus` interface 整体断裂(API_COVERAGE.md §6.1 记)。**本 iter 仅交付独立 GET + PUT**;status 整合属 iter-9 RESUME POINT 的 `GET /pipeline/status contract refactor`,defer 到 iter 12+。理由:status 重构是 medium-large scope,跟 O8 解耦更易 reviewer / 更易回滚。

## §3 Implementation steps(Inner-loop-A,本 design 通过后执行)

1. **DDL**: `docs/QUANTMIND_V2_DDL_FINAL.sql` 加 `pipeline_settings` table + singleton INSERT(铁律 22 文档跟随代码)
2. **Migration**: `backend/migrations/pipeline_settings.sql` —— idempotent `CREATE TABLE IF NOT EXISTS` + `INSERT ... ON CONFLICT DO NOTHING`(沿用 strategy_registry.sql 体例,smoke `test_migration_idempotent_rerun` 自动覆盖)
3. **Schemas**: `backend/app/schemas/pipeline.py` —— `AutomationLevelRequest` / `AutomationLevelResponse` (`Literal["L0","L1","L2","L3","L4"]`)
4. **Endpoint**: `backend/app/api/pipeline.py` —— GET + PUT handlers(sync def,psycopg2 via `get_sync_conn`,沿用 factors.py 体例)
5. **Tests**: `backend/tests/test_pipeline_automation_level.py` —— 至少 4 tests(default value / GET / PUT / 422 invalid level)
6. **Doc sync**: `docs/API_COVERAGE.md` §6.1 append "O8 resolved iter 10 PR #..."

## §4 §6 8-trigger STOP self-check —— NEGATIVE

| # | 触发器 | 命中? | 理由 |
|---|---|---|---|
| ① | 真账户 LIVE / broker / 真发单 | ❌ | pipeline 设置 ≠ broker 路径 |
| ② | 新 trading strategy / risk threshold / factor mining | ❌ | UI config persistence,非策略/风控/挖矿 |
| ③ | 修改 5+1 层架构 / Tier A/B / 横切层 边界 | ❌ | 普通 CRUD endpoint |
| ④ | 新增 Framework(12 封顶) | ❌ | 0 framework |
| ⑤ | 新增 governance SSOT 新概念 | ❌ | 0 governance |
| ⑥ | 引入新 DB 表影响交易/风控 | ❌ | 新表 `pipeline_settings` 但 0 trading/风控 impact(纯 UI config) |
| ⑦ | 改 risk rule 触发逻辑 | ❌ | 0 risk rule 触碰 |
| ⑧ | 修改 L4R loop 自身安全机制(§1/§4/§5/§6/§9/§14) | ❌ | 0 spec safety touch |

→ **Feature 级**。Proceed to ADR-DRAFT(spec §10 step 4)+ Inner-loop-A implement(step 5)。

## §5 Acceptance criteria

- Migration idempotent rerun OK(`pytest -m smoke and not live_tushare` 覆盖)
- `setAutomationLevel('L2')` → 200,DB `updated_at` 刷新,后续 GET 返回 `L2`
- Invalid level(`'L5'` / `'foo'`)→ 422
- Default value `L0` exists post-migration(`SELECT automation_level FROM pipeline_settings WHERE id=1` → `L0`)
- 4 backend tests 全绿 + ruff clean + pre-push smoke 61/61
- 0 frontend code change(pipeline.ts:163 already wired)
- 0 红线触碰(self-verify)

## §6 Out of scope(本 iter,显式 defer)

- `GET /api/pipeline/status` 整合 → iter 12+ status-contract refactor 一并做
- `updated_by` user-auth 接管 → defer 到 auth/RBAC 整体引入时
- L0-L4 各级实际行为差异(本 iter 仅 persist value,行为 dispatch 是更大 scope)

## §7 Risk + rollback

- **Risk**: 新表加 column 易,但 enum 值若后续扩(L5+)需 migration + frontend 同步。当前 L0-L4 来自 L4R spec,固定 5 级。
- **Rollback**: `DROP TABLE pipeline_settings` 安全(0 FK refs,0 downstream consumer 除本 endpoint)。frontend 仍跑得通(setAutomationLevel 会再次 404,跟当前 baseline 一致)。
