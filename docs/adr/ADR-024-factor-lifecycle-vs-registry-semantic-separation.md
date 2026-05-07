# ADR-024: factor_lifecycle 与 factor_registry 语义分工显式声明

> **Status**: Proposed (5-02 起草, 等 user 决议; user merge PR = Accept signal)
> **Date**: 2026-05-02
> **Authors**: Claude.ai 起草 + CC task 5 reconnaissance evidence
> **Related**:
> - [docs/audit/factor_registry_lifecycle_audit_2026_05_02.md](../audit/factor_registry_lifecycle_audit_2026_05_02.md) (5-02 task 5 真测证据)
> - [docs/FACTOR_COUNT_GLOSSARY.md](../FACTOR_COUNT_GLOSSARY.md) §4 (registry) §5 (lifecycle)
> - [docs/adr/ADR-023-yaml-ssot-vs-db-strategy-configs-deprecation.md](ADR-023-yaml-ssot-vs-db-strategy-configs-deprecation.md) (5-02 配套, yaml SSOT 系列)

## §1 Context

### 1.1 当前状态 (5-02 task 5 实测)

GLOSSARY §4 + §5 列两表, 真值差 4.3x:
- factor_lifecycle = 6 行 (4 active + 2 retired)
- factor_registry = 286 行 (26 active / 14 deprecated / 246 warning)

初始 frame 怀疑是 "SSOT 决议" 问题 (哪个是 SSOT, 解冻 / deprecate 哪个), 但 task 5 真测推翻 framing.

### 1.2 真测因 — 字段 0 重叠是设计

两表 schema 真测 (PK 不同, 字段 0 重叠除 status / factor_name 共通名):

| 表 | PK | 用途 | 关键字段 |
|---|---|---|---|
| factor_lifecycle | factor_name | 生产策略生命周期 (yaml 镜像) | entry_date / entry_ic / entry_t_stat / rolling_ic_12m / warning_date / retired_date |
| factor_registry | id (uuid), name UNIQUE | 设计审批 + Gate G1-G8 评估历史 | gate_ic / gate_ir / gate_mono / gate_t / pool / direction / category / source / hypothesis / expression / ic_decay_ratio |

Table comment 真值:
- lifecycle: "Sprint 1.5 lifecycle"
- registry: "状态机: candidate→active→warning→critical→retired"

### 1.3 cross-source 真测 (5-02)

| 关系 | 真值 | 判定 |
|---|---|---|
| `lifecycle.active` ∩ yaml | **4 完全对齐** | lifecycle 是 yaml 镜像 |
| `registry.active` ∩ yaml | **0** | yaml CORE 4 在 registry 中 status='warning' (Gate decay 监控状态) |
| `lifecycle.active` ∩ `registry.active` | **0** | 设计正常, 不是 drift |
| `factor_ic_history` DISTINCT | 113 | (GLOSSARY §1) |

### 1.4 4-17 冻结因 (反 zombie 假设)

CC task 5 真测推翻 "schtask zombie / Celery 任务死" 假设 (LL-074 模式不适用):

- factor_registry created_at MAX = 2026-04-17 18:31:52, 281/286 行同 timestamp = mass batch INSERT
- commit: `3a6c200` (jyxren, 2026-04-17 18:44) "feat(platform): MVP 1.3a Registry Schema + 回填"
- 4-17 后设计层切走新 onboarding (`qm_platform/factor/registry.py G9+G10`)
- Phase 2.4/3B/3D/3E 实验全 NO-GO, **不形式注册** (设计如此)

**结论**: 不是 zombie / 不是流程废, 是 MVP 1.3a 设计层切换 + 后续实验 NO-GO 自然不写.

### 1.5 风险评估

`grep -rn "factor_lifecycle\|factor_registry"` 365 行引用真测:

- **生产 trading path 0 引用** (`signal_engine.py` 仅 1 处注释; `run_paper_trading.py` + `execution_service.py` 0 hit)
- 写路径 11 处全在: 研究 onboarding (`registry.py G9+G10`) / 监控 (`monitor_factor_ic` / `factor_health_daily`) / 画像 (`factor_profile`) / 前端管理 (`api/factors.py`) / 一次性 migration

**结论**: 0 prod risk. 设计正确.

## §2 Decision

### 2.1 语义分工显式声明

**factor_lifecycle 与 factor_registry 是不同语义层 SSOT, 不是 drift**.

| SSOT 角色 | 表 | 用途 |
|---|---|---|
| 生产生命周期 SSOT | `factor_lifecycle` | yaml 真生产因子 4 个的运行时跟踪 (entry / warning / retired 时序 + IC 监控) |
| 设计审批 SSOT | `factor_registry` | 历史所有设计过的因子 286 个的 Gate G1-G8 评估 + hypothesis + expression 沉淀 |

**两表互不替代**:
- 看"PT 真生产用什么因子" → 走 yaml (ADR-023 已声明)
- 看"PT 因子运行时状态" → 走 lifecycle (yaml 镜像)
- 看"某因子设计依据 / Gate 评估" → 走 registry
- 看"某因子有无 IC 历史" → 走 factor_ic_history (113 distinct)

### 2.2 现状保留 (反 SSOT 合并)

采纳 task 5 audit §B.3 推荐 (c): **两表保留 + GLOSSARY footnote + ADR 沉淀**.

- 两表 read-only 保留, 不合并 / 不 deprecate
- 不强制 lifecycle ⊆ registry.active (yaml CORE 4 在 registry 中 status='warning' 是设计 — Gate decay 监控状态机, 不是 stale)
- 不解冻 registry (4-17 后实验 NO-GO 不入是设计正常)

### 2.3 Decision reversibility

此 ADR 决议**可逆**. 如果未来:
- 多策略并行需要 lifecycle 扩展 (支持非 yaml 因子的运行时跟踪)
- 或 Gate G1-G8 评估流程改变, registry 不再适用

可走新 ADR supersedes 此 ADR.

## §3 Consequences

### 3.1 立即影响

- ✅ 0 caller 改动 (生产 0 引用)
- ✅ 0 数据 backfill / migration / 解冻
- ✅ 0 prod 风险 (LIVE_TRADING_DISABLED 整期保持, 0 .env / 0 schema 改动)
- ⚠️ GLOSSARY §4 + §5 footnote 加 (FU-1, ~10 行)
- ⚠️ FACTOR_COUNT_GLOSSARY §A 加新误读模式 (FU-2, ~20 行)

### 3.2 长期影响

- 任何 "lifecycle vs registry drift" 类 framing 走本 ADR cross-link, 不再走 SSOT 决议路径 (反 task 5 踩坑模式)
- 防 "lifecycle.active ⊆ registry.active" 类直觉假设 (设计反此假设)
- 与 ADR-023 (yaml SSOT) 配套, "DB 多表非 SSOT, yaml 是 SSOT" 系列 thesis 完整

### 3.3 反对意见 (alternative considered, task 5 audit §B.3)

- **(a) lifecycle SSOT, registry deprecate**: 反对. registry G1-G8 评估历史价值 (设计审批 sediment), deprecate 损失 hypothesis / expression / Gate 历史
- **(b) registry SSOT, lifecycle deprecate**: 反对. lifecycle 运行时跟踪 (entry_date / warning_date / rolling_ic_12m) registry 无, 是另一语义
- **(d) yaml 唯一 SSOT, 两表都 deprecate**: 强反对. yaml 是配置 SSOT, 不含运行时状态 + 不含 Gate 历史. 两表是 yaml 之外的 SSOT (各自 domain), 不可被 yaml 替代

## §4 Follow-up

| # | 项 | 优先级 | 归属 |
|---|---|---|---|
| FU-1 | GLOSSARY §4 (registry) footnote: "registry.active ∩ lifecycle.active = 0 是设计 (语义不同, 非 drift), 走 ADR-024" | P3 | 本 ADR PR |
| FU-2 | GLOSSARY §5 (lifecycle) footnote: "lifecycle.active ∩ yaml = 4 完全对齐, 是 yaml 镜像; lifecycle 表无 ratio 字段, 'ratio=0.X' 类 cite 实际指 monitor_factor_ic.py rolling_ic" | P3 | 本 ADR PR |
| FU-3 | GLOSSARY §A 新增误读模式 A.6: "lifecycle vs registry SSOT 决议 trap" | P3 | 本 ADR PR |
| FU-4 | docs/audit/factor_registry_lifecycle_audit_2026_05_02.md 末尾加 ADR-024 反向 cross-link | P3 | 本 ADR PR |
| FU-5 | registry yaml CORE 4 status='warning' 是否设计 — task 5 标 "需 Layer 2.5 评估". **proposed: 接受为设计** (Gate decay 监控状态机, active→warning 是 G1-G8 状态机正常流), Layer 2.5 仅 verify 不实施 | P3 | Layer 2.5 (proposed) |
| FU-6 | registry DDL comment 5 状态 vs 实际 3 状态 drift fix (CHECK 约束缺失) — 设计 vs 实施 drift, 微 fix | P3 | Layer 2.5 (proposed) micro PR |
| FU-7 | sprint state cite "ratio=0.517<0.8" 修正建议 — 不动 sprint state (是 user 历史 handoff), 仅 GLOSSARY footnote 沉淀 (FU-2 cover) | done by FU-2 | — |

## §5 Verification

### ADR PR scope (反 scope creep)

本 ADR PR **仅** 包含:
- `docs/adr/ADR-024-factor-lifecycle-vs-registry-semantic-separation.md` 新文件 (本 ADR)
- `docs/FACTOR_COUNT_GLOSSARY.md` §4 + §5 footnote (FU-1 + FU-2)
- `docs/FACTOR_COUNT_GLOSSARY.md` §A 新增 A.6 (FU-3)
- `docs/audit/factor_registry_lifecycle_audit_2026_05_02.md` 末尾 ADR cross-link (FU-4)

**禁止** scope:
- ❌ 修任何代码 (registry.py / lifecycle 任何 caller)
- ❌ 改 DB schema / DDL / 任何 row UPDATE / DELETE / INSERT
- ❌ 解冻 registry / deprecate 任何 caller
- ❌ DDL CHECK 约束修复 (FU-6 单独 micro PR, 不在本 ADR)
- ❌ 跑 PT / 重启 / 改 .env

### Merge 后 verify

```bash
# 1. 两表真值仍稳 (无 row 改动)
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT (SELECT COUNT(*) FROM factor_lifecycle) AS lifecycle_n, \
          (SELECT COUNT(*) FROM factor_registry) AS registry_n;"
# 期望: lifecycle_n=6 / registry_n=286 (5-02 真测)

# 2. yaml 真值未变
grep -A 8 "factors:" configs/pt_live.yaml

# 3. cross-link 完整
grep "ADR-024" docs/FACTOR_COUNT_GLOSSARY.md docs/audit/factor_registry_lifecycle_audit_2026_05_02.md

# 4. lifecycle.active ∩ yaml 仍 = 4 (yaml 镜像 invariant)
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT factor_name FROM factor_lifecycle WHERE status='active' ORDER BY factor_name;"
# 期望: bp_ratio / dv_ttm / turnover_mean_20 / volatility_20
```

## §6 Change Log

| Date | Author | Change |
|---|---|---|
| 2026-05-02 v0.1 | Claude.ai 起草 + CC task 5 reconnaissance evidence | Proposed |
| (TBD) | user | Accepted / Rejected / Modified |
