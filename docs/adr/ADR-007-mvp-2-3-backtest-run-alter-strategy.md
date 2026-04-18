---
adr_id: ADR-007
title: MVP 2.3 Sub1 沿用老 backtest_run schema + ALTER ADD 3 列策略
status: accepted
related_ironlaws: [15, 17, 22, 25, 36, 38]
recorded_at: 2026-04-18
supersedes: null
---

## Context

MVP 2.3 Sub1 Plan 阶段 (2026-04-18 Session 7 开场) 用户授权后实施过程中, 执行 migration 幂等测试暴露 P0 precondition 失准:

**DB 实测发现**:
- `backtest_run` 表**已存在** + **7 行研究历史数据** (from `docs/QUANTMIND_V2_DDL_FINAL.sql` 建)
- 4 张 FK 依赖表绑死 run_id: `backtest_daily_nav` / `backtest_holdings` / `backtest_trades` / `backtest_wf_windows` (rows=0 但 FK 约束存在)
- 老 schema 与 MVP 2.3 设计稿 D3 (docs/mvp/MVP_2_3_backtest_parity.md, 2026-04-18 Session 5 末) 不一致

**老 vs 设计稿 schema 差异**:

| 字段 | 老表 | 设计稿 |
|---|---|---|
| run_id | UUID DEFAULT gen_random_uuid() | UUID (客户端生成) |
| hash | `config_yaml_hash VARCHAR(64)` | `config_hash` (重命名) |
| factors | `factor_list TEXT[]` | `factor_pool` (重命名) |
| config | `config_json JSONB` | `config` (重命名) |
| metrics | **独立 DECIMAL 列** (sharpe_ratio / max_drawdown / annual_return / ...) | **JSONB 统一** |
| mode | 无 | `mode VARCHAR(16)` CHECK (quick_1y/full_5y/...) |
| lineage_id | 无 | `UUID FK data_lineage(lineage_id)` |
| extra_decimals | 无 | `NUMERIC[]` (预留扩展) |

**根因** (LL-055 同源 — handoff 凭印象):
- 设计稿 Session 5 末写时, 未 `\d backtest_run` 查实表, 凭印象设计 schema
- `docs/QUANTMIND_V2_DDL_FINAL.sql` 建的表 `backend/migrations/` 不跟踪 — F31 审计 "设计稿与 DB 脱节" 类似问题
- 铁律 36 precondition 只读了设计稿 + Platform interface, 未查 DB 实表

## Decision

**采用方案 A: ALTER TABLE ADD COLUMN IF NOT EXISTS 3 列**

```sql
ALTER TABLE backtest_run
    ADD COLUMN IF NOT EXISTS mode VARCHAR(16),
    ADD COLUMN IF NOT EXISTS lineage_id UUID REFERENCES data_lineage(lineage_id),
    ADD COLUMN IF NOT EXISTS extra_decimals NUMERIC[];

-- mode CHECK 约束独立 ADD (容忍老 7 行 NULL)
ALTER TABLE backtest_run
    ADD CONSTRAINT chk_backtest_run_mode
    CHECK (mode IS NULL OR mode IN ('quick_1y', 'full_5y', 'full_12y', 'wf_5fold', 'live_pt'));
```

**字段名映射** (MVP 2.3 SDK 写入时透明转换):

| 设计稿 (SDK concept) | 老表 (实际列名) | 转换位置 |
|---|---|---|
| `config_hash` | `config_yaml_hash` | `PlatformBacktestRunner._hash_to_column` |
| `factor_pool` | `factor_list` | 同上 |
| `config` | `config_json` | 同上 |
| `metrics.sharpe` | `sharpe_ratio` | 结构化 DECIMAL 列映射 |
| `metrics.<other>` | 独立 DECIMAL 列 (annual_return / max_drawdown / ...) | 同上 |

**metrics 策略**: 沿用老表**独立 DECIMAL 列** (11+ metric 字段), 不引入 `metrics JSONB`.
- 主要 metric (sharpe/mdd/calmar/sortino/IR/beta/win_rate/P&L/annual_return/total_return/turnover) 独立列
- 未来扩展 metric 走新加的 `extra_decimals NUMERIC[]` (ColumnSpec `decimal_array` 支持)
- 极端情况 (JSONB 级自由扩展) 推 MVP 3.x Strategy Framework 或更晚

## Alternatives Considered

### 方案 B: DROP + CREATE 对齐设计稿

**Pros**: Clean slate, schema 100% 对齐设计稿, U1 Parity metrics 比对简单.

**Cons**:
- 7 行研究历史丢 (需先 archive)
- 4 张 FK 依赖表全重建 (blast radius 爆炸)
- **前置实测** (业务代码读路径 grep + 7 行写入时间分布) 工程量 ≥ 方案 A 总和
- 若某研究脚本正在读 `backtest_run.sharpe_ratio` 等列, DROP 会静默 break

**不选理由**: Sub1 硬门焦点是"不破坏 PT + regression max_diff=0", 方案 B 的高破坏性与硬门目标冲突.

### 方案 C: 新表 backtest_run_v2

**Pros**: 0 破坏老表 + 新表完全对齐设计稿.

**Cons**:
- "v2" 后缀是永久 tech debt, 语义分裂
- 2 张 backtest 表共存, 研究脚本混乱
- 4 张 FK 表绑老表, 新表无 FK 集成 (U3 Lineage 断链)

**不选理由**: tech debt 持久, 比方案 A 的字段名映射 tech debt 更严重 (永久 2 张表 vs 可清理的命名差异).

## Consequences

### 好处

- **0 数据破坏**: 7 行研究历史 + 4 张 FK 依赖表全安全
- **Sub1 风险最低**: 硬门 11 (backtest_run.lineage_id 非空) 可验证, 其他硬门不受影响
- **regression max_diff=0 硬门**: 不依赖 backtest_run schema 对齐 (regression 比 nav parquet 不比 DB)
- **U1 Parity max|diff|==0 硬门**: 算 signal 一致即可, 不读 backtest_run

### Tech debt 记录

- **字段名映射**: `config_hash / factor_pool / config` ↔ 老表实际列名. 未来 MVP 3.x Clean-up PR 可选 `ALTER TABLE RENAME COLUMN` 对齐设计稿命名.
- **metrics 扩展方式分裂**: 主 metric 独立 DECIMAL 列 + 扩展走 `extra_decimals NUMERIC[]`. 不是理想的 JSONB 自由扩展, 但工程现实.
- **MVP 2.3 设计稿 D3 需同步更新**: `docs/mvp/MVP_2_3_backtest_parity.md` D3 段必须反映老 schema + 字段映射表. 设计稿 v1.1 bump 同步本 ADR.

### Migration 策略

- **正向 migration**: `backend/migrations/backtest_run.sql` 改为 `ALTER TABLE ADD COLUMN IF NOT EXISTS` (幂等)
- **Rollback migration**: `backend/migrations/backtest_run_rollback.sql` 改为 `ALTER TABLE DROP COLUMN IF EXISTS` (精确回滚 3 列 + 1 constraint)
- **老表不动**: CREATE TABLE / FK / index / 独立 DECIMAL 列全保留

## Follow-up

- [x] 更新 `docs/mvp/MVP_2_3_backtest_parity.md` D3 章节 (v1.0 → v1.1) — 本 PR 已做
- [x] PR A commit message 引用本 ADR — 本 PR 已做
- [ ] **MVP 2.3 Sub1 PR B** (PlatformBacktestRunner) SDK 实现 `_hash_to_column` / `_factor_to_column` / metrics 映射
- [ ] **评估 `artifact_json JSONB` 是否需要 Sub2 migration 补加** (原设计 `{nav: "path", holdings: "path", ...}`, Sub1 未加, 本 PR review 发现 code-reviewer P2). 如 PR B 需写 artifact 路径, 补 migration; 否则走 `error_message TEXT` 或推 MVP 3.x.
- [ ] 未来 MVP 3.x Clean-up backlog: `ALTER TABLE backtest_run RENAME COLUMN config_yaml_hash TO config_hash` 等

## 关联

- `docs/mvp/MVP_2_3_backtest_parity.md` (v1.0 设计稿, 本 ADR 触发 v1.1 bump)
- `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` v1.5 Part 4 MVP 2.3
- `docs/QUANTMIND_V2_DDL_FINAL.sql` (老 backtest_run 建表来源)
- LL-055 (handoff 凭印象腐烂 — 本 P0 发现的同源教训)
- F31 审计 (设计稿与 DB 脱节问题, 本 ADR 是相似主题)
