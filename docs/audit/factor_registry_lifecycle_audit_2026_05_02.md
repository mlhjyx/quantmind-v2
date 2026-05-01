# Audit — factor_lifecycle vs factor_registry reconnaissance (2026-05-02)

> **触发**: Task 2 + Task 3 真测发现两表都自称"当前活跃因子" 但 active 数 6 vs 26 差 4.3x, 哪个 SSOT 不清.
> **范围**: 纯 reconnaissance, 0 修代码 / 0 改数据 / 0 解冻 / 0 deprecate / 0 PR. 仅交付证据 + 候选 decision + Layer 2.5 sprint 决议参考.
> **顶层结论**: **不是 drift, 是 category error** (类似 task 2 audit 213 framing). lifecycle 与 registry 是**不同语义层**: lifecycle = 生产策略真用因子的运行生命周期 (4 active = yaml 4 因子完全对齐), registry = 设计/审批层注册表 + Gate G1-G8 历史. 两表 active 交集 = **0** 是设计正常, 不是 bug.

---

## §0 TL;DR (3 句)

1. **lifecycle 4 active = yaml CORE3+dv_ttm 4 因子完全对齐** (bp_ratio / dv_ttm / turnover_mean_20 / volatility_20). 真测 lifecycle.active ∩ yaml = **4** ⭐. lifecycle 是**生产策略运行生命周期** SSOT.
2. **registry 26 active = Gate G1-G8 PASS 的研究候选 (LEGACY + alpha158 + microstructure)**, **不含 yaml CORE 4 任一**. yaml 4 因子在 registry 中状态 = **'warning'** (Gate decay 监控). registry 是**设计/审批/Gate 评估层** SSOT.
3. **真测 lifecycle.active ∩ registry.active = 0** — 不是 drift 不是 bug 是设计. 4-17 registry 冻结是 commit `3a6c200` MVP 1.3a 一次性 schema migration + 282 行 backfill (5→287), 后续无 formal onboarding 走过该路径, 不是 schtask zombie.

---

## §A 真测五块

### A.1 Schema 对照

| 字段 | factor_lifecycle | factor_registry |
|---|---|---|
| **表 comment** | "Factor lifecycle management - Sprint 1.5" | "因子注册表。状态机: candidate→active→warning→critical→retired" |
| **PK** | factor_name (varchar 50) | id (uuid) |
| **factor name field** | factor_name | name (UNIQUE) |
| **status CHECK** | ✅ {candidate, active, monitoring, warning, retired} | ❌ 无 CHECK (DDL comment 写状态机但 DB 不强制) |
| **状态机字段** | entry_date / entry_ic / entry_t_stat / rolling_ic_12m / rolling_ic_updated / warning_date / retired_date | gate_ic / gate_ir / gate_mono / gate_t / pool / direction / category / source / lookback_days / hypothesis / expression / code_content / ic_decay_ratio |
| **指标语义** | 时序 (entry_date / rolling_ic / 转换日期) — **运行时跟踪** | 静态 (Gate 评估 + 元数据) — **设计审批** |
| **timestamps** | created_at / updated_at (无 tz) | created_at / updated_at (with tz) |
| **总行数** | 6 | 286 |

✅ **判定**: 字段对照证实**两表语义不同** — lifecycle 跟踪生命周期演进 (entry/warning/retired 时序), registry 跟踪 Gate 评估 + 因子元数据 (静态). 字段 0 重叠 (除 status / factor_name 共通名).

### A.2 当前真值 (重测 5-01 snapshot)

**factor_lifecycle 全 6 行 dump**:

| factor_name | status | entry_date | entry_ic | entry_t_stat | retired_date | notes |
|---|---|---|---:|---:|---|---|
| bp_ratio | active | 2026-03-20 | 0.0523 | 6.02 | | v1.1 Active, strongest value factor |
| dv_ttm | active | 2026-04-12 | 0.1070 | 26.00 | | CORE3+dv_ttm WF PASS Sharpe=0.8659 direction=+1 |
| turnover_mean_20 | active | 2026-03-20 | -0.0643 | -7.31 | | v1.1 Active, IR=-0.73, 7/7 year consistent |
| volatility_20 | active | 2026-03-20 | -0.0690 | -6.37 | | v1.1 Active, &#124;IC&#124; largest, 7/7 year consistent |
| amihud_20 | retired | 2026-03-20 | 0.0215 | 2.69 | **2026-04-12** | Retired from CORE5, kept as baseline (CORE3+dv_ttm WF PASS) |
| reversal_20 | retired | 2026-03-20 | 0.0386 | 3.50 | **2026-04-12** | Retired from CORE5, kept as baseline |

✅ 4 active = yaml CORE3+dv_ttm 4 因子. retired_date 2026-04-12 = yaml cutover commit `51b1409` 同日.

**factor_registry GROUP BY status**:

| status | count | 备注 |
|---|---:|---|
| warning | 246 | (Gate decay 监控, 含 yaml CORE 4) |
| active | 26 | (Gate G1-G8 PASS 研究候选) |
| deprecated | 14 | |
| **(候选 / 监控 / retired / critical) DDL comment 提及但 0 行** | 0 | |

🆕 **discovery**: registry DDL 状态机 comment 写 "candidate→active→warning→critical→retired" (5 状态), 但 DB 实际只有 3 个 (active / warning / deprecated). DDL 与实际不一致.

**registry 26 active 真 enumerate** (5-02 真测):
```
CORD20, CORD5, HIGH0, IMIN10, RSQR30, RSQR_20,
a158_vstd30, a158_vsump60, high_vol_price_ratio_20,
intraday_kurtosis_20, intraday_momentum_20, intraday_skewness_20,
kbar_kup, large_order_ratio, max_intraday_drawdown_20,
money_flow_strength, nb_ratio_change_5d, opening_volume_share_20,
price_volume_corr_20, rsrs_raw_18, sp_ttm, turnover_f,
up_days_ratio_20, updown_vol_ratio_20, volume_autocorr_20, volume_std_20
```
分布: phase21=4, alpha158=2, legacy=11, microstructure=4, price_volume=1, risk=1, northbound=1, liquidity=1.

⚠️ **registry 26 active 0 含 yaml CORE 4** (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm 都不在此 26 中).

**真测 yaml CORE 4 在 registry 中的真状态**:
```
bp_ratio        | warning
dv_ttm          | warning
turnover_mean_20| warning
volatility_20   | warning
```
⚠️ 4 个生产真用因子都是 registry status='warning'. 这是 design (Gate decay 监控) 还是 stale, 需 Layer 2.5 sprint 进一步评估.

### A.3 yaml ↔ lifecycle ↔ registry ↔ ic_history 关系真值

| 关系 | 真值 | 判定 |
|---|---:|---|
| yaml total | 4 | (CORE3+dv_ttm SSOT) |
| lifecycle.active total | 4 | |
| registry.active total | 26 | |
| **lifecycle.active ∩ yaml** | **4** ⭐ | ✅ 完全对齐 (lifecycle 是 yaml 镜像) |
| **registry.active ∩ yaml** | **0** ⚠️ | yaml 因子在 registry 中 status='warning', 不是 'active' |
| **lifecycle.active ∩ registry.active** | **0** | ⭐ 设计正常 — 两表不同语义, 0 交集是预期 |
| factor_ic_history DISTINCT | 113 | (GLOSSARY §1, 5-01 真测 sustained) |

**关键 finding**: lifecycle.active ∩ registry.active = 0 不是 drift, 是**两表语义层不同**:
- lifecycle.active: "**生产策略当前真用**" (yaml 4 因子镜像)
- registry.active: "**Gate G1-G8 PASS 研究候选**" (LEGACY + alpha158 + microstructure 26 个)
- 一个是运行时, 一个是研究审批; 无应有交集

类似 task 2 audit 113 vs 213 framing — 不是 drift, 是 category error.

### A.4 caller path 真测

`grep -rn "factor_lifecycle\|factor_registry"` 真 enumerate: **365 行 hit** (重度引用).

**写路径** (INSERT / UPDATE):

| # | file:line | 表 | 操作 | 真用途 | 在生产 trading path? |
|---|---|---|---|---|---|
| W.1 | [backend/qm_platform/factor/registry.py:284](backend/qm_platform/factor/registry.py:284) | factor_registry | INSERT | MVP 1.3c onboarding 主入口 (G9+G10 硬门) | ❌ 研究 onboarding |
| W.2 | [backend/qm_platform/factor/registry.py:332](backend/qm_platform/factor/registry.py:332) | factor_registry | UPDATE | MVP 1.3c onboarding gate 更新 | ❌ 研究 onboarding |
| W.3 | [backend/app/services/factor_onboarding.py:248](backend/app/services/factor_onboarding.py:248) | factor_registry | UPDATE | onboarding gate 统计 (gate_ic/gate_t) | ❌ 研究 onboarding |
| W.4 | [backend/app/api/factors.py:1034](backend/app/api/factors.py:1034) | factor_registry | UPDATE 'archived' | 软删除 API | ❌ 前端管理 |
| W.5 | [scripts/factor_health_daily.py:270](scripts/factor_health_daily.py:270) | factor_registry | UPDATE status | 日常健康 schtask | ❌ 健康监控, 非 trading |
| W.6 | [backend/scripts/compute_factor_ic.py:494](backend/scripts/compute_factor_ic.py:494) | factor_registry | UPDATE | IC 计算回写 Gate | ❌ IC 评估 |
| W.7 | [backend/engines/factor_profile.py:278](backend/engines/factor_profile.py:278) | factor_lifecycle | UPDATE | Profiler V2 输出 | ❌ 画像 |
| W.8 | [scripts/monitor_factor_ic.py:340/360](scripts/monitor_factor_ic.py:340) | factor_lifecycle | UPDATE | active monitoring lifecycle 转换 | ❌ 监控, 非 trading |
| W.9 | [scripts/archive/setup_factor_lifecycle.py:69](scripts/archive/setup_factor_lifecycle.py:69) | factor_lifecycle | INSERT | archived setup script | ❌ 一次性 |
| W.10 | [scripts/create_factor_lifecycle.sql:28](scripts/create_factor_lifecycle.sql:28) | factor_lifecycle | INSERT | DDL seed | ❌ 一次性 |
| W.11 | [backend/migrations/cleanup_orphan_factors_session27.sql](backend/migrations/cleanup_orphan_factors_session27.sql) | factor_registry | UPDATE/INSERT | Session 27 migration | ❌ 一次性 |

**生产 trading path 真测**:
```bash
grep -nE "factor_lifecycle|factor_registry" backend/engines/signal_engine.py scripts/run_paper_trading.py backend/app/services/execution_service.py
# → signal_engine.py:43: 仅 1 处注释 (PAPER_TRADING_CONFIG.factor_names 是 CORE3+dv_ttm), factor_registry
# → run_paper_trading.py / execution_service.py: 0 hit
```

✅ **生产 trading path 0 引用** lifecycle / registry. 所有读写都是研究 / 监控 / 前端管理.

**STOP trigger #1 评估**: "两表真有生产 trading path 引用" — ❌ **不满足**, 不 STOP.

### A.5 4-17 冻结根因真测

**factor_registry created_at MIN/MAX 真测**:
- MIN = 2026-03-28 20:18:37.624481+08 (initial seed)
- MAX = **2026-04-17 18:31:52.987416+08** ⭐

**4-17 18:31 真值 — 281/286 行同 timestamp** (一次性 mass INSERT):
```sql
SELECT count(DISTINCT name) FROM factor_registry
 WHERE created_at = '2026-04-17 18:31:52.987416+08';
-- → 281
```

**冻结时点真 commit** (2026-04-17 18:44):

```
commit 3a6c2005e360347eade902e1329e8f18899c9d91
Author: jyxren <7528324@qq.com>
Date:   Fri Apr 17 18:44:46 2026 +0800

    feat(platform): MVP 1.3a Registry Schema + 回填 — 修复 6 drift, 287 行 registry

    Wave 1 第 4 步. 解锁 MVP 1.3b direction DB 化 + MVP 1.3c onboarding 强制化 + lifecycle 迁移.

    修复 6 个 drift:
      1. DB factor_registry 无 pool 列 → ALTER TABLE ADD pool VARCHAR(30)
      2. DB 无 ic_decay_ratio → ALTER TABLE ADD
      ...
      6. DB 5 行 vs factor_values 276 distinct gap → 回填 282 新行, 总 287 行
```

**4-17 后 INSERT path 真测**:
- MVP 1.3c onboarding 是 new INSERT path ([backend/qm_platform/factor/registry.py:284](backend/qm_platform/factor/registry.py:284) — G9+G10 硬门)
- 4-17 后 0 新 INSERT (factor_registry 行数静止 286)
- Phase 2.4/3B/3D/3E (~28 实验) 都是研究脚本, 没走 formal onboarding (research-driven, NO-GO closed, 不形式注册)

**4-17 冻结真因**:
1. ✅ MVP 1.3a 一次性 schema migration + backfill (commit `3a6c200`) 把 5 行 registry 扩到 287 行.
2. ✅ 设计层切换: 4-17 后所有新因子需走 MVP 1.3c onboarding (G9+G10 硬门). Phase 2.4/3B/3D/3E 实验全 NO-GO, 没形式 onboarding.
3. ❌ **不是 schtask zombie / Celery 任务死** (LL-074 模式不适用). registry INSERT 不是 schtask 而是按需 onboarding.
4. ⚠️ FACTOR_TEST_REGISTRY.md "M=213 累积测试" 4-11 末次更新, 与 4-17 registry 287 行也不同步 — 是文档 SSOT vs DB SSOT 的另一 drift (F-D78-60 P2, 已 GLOSSARY §11 沉淀).

**STOP trigger #3 评估**: "4-17 冻结是因为 INSERT path 真生产死" — ❌ **不满足**, 是设计层切换 (onboarding 走新路径, 实验不形式注册), 不是 schtask zombie. 不 STOP.

---

## §B Stage B — 候选 decision

### §B.1 SSOT 候选

| # | 候选 | 真证据 | 反证 | 概率 |
|---|---|---|---|---:|
| #1 | lifecycle 是 SSOT, registry 是 archive (deprecate registry) | A.4 0 prod path 引用 registry trading | A.4 W.1-W.6 6 处生产代码写 registry, 是 onboarding+health+IC 路径活跃 | ~10% (反证强, registry 不 archive) |
| #2 | registry 是 SSOT, lifecycle 是 subset 视图 | registry 286 行远超 lifecycle 6 行 | A.3 lifecycle.active ∩ registry.active=0, registry status='warning' 不等于 lifecycle 'active'; 字段语义不同 | ~5% (反证强) |
| #3 | yaml 是真 SSOT, 两表都是 archive | A.3 yaml.factor[] 是生产 SSOT (signal_engine.py:247) | A.4 lifecycle 真在 monitor_factor_ic.py / factor_profile.py 活跃 UPDATE; registry 在 onboarding 活跃 INSERT | ~15% (yaml 是生产 SSOT 没错, 但两表都不是 archive) |
| **#4** | **两表语义不同 — lifecycle = 生产策略生命周期 / registry = 设计审批 + Gate 评估 (不是 drift)** | A.1 字段 0 重叠 (除共通名); A.2 lifecycle.active=yaml 镜像 / registry.active=Gate PASS 研究候选; A.3 lifecycle.active ∩ registry.active=0 是设计; A.4 写路径分工清楚 (lifecycle=monitor / registry=onboarding); A.5 4-17 mass migration 是设计层切换 | 无 | **~95% ⭐** |
| #5 | 两表都 stale, yaml 真 SSOT, 两表 deprecate | A.3 lifecycle 4 active = yaml 4 (实时同步, dv_ttm 4-12 同步入 lifecycle); registry 4-17 mass backfill 后冻结 | lifecycle 不 stale (yaml cutover 4-12 当日 retired_date 同步; dv_ttm 4-12 created_at 同日入 lifecycle) | ~10% (lifecycle 不 stale) |
| #6 (🆕) | **lifecycle 与 yaml 双向同步是一个 invariant** (4-12 cutover 同日 retired amihud_20 + reversal_20 + entry dv_ttm) | A.2 retired_date 2026-04-12 = yaml commit `51b1409` 同日; dv_ttm.entry_date=2026-04-12 同日 | 无 (反而是 #4 的强佐证) | ~85% (是 #4 子证据) |

**主根**: 候选 #4 ~95% — **不是 drift, 是 category error**. 类似 task 2 audit 113 vs 213 教训.

### §B.2 4-17 冻结根因候选

| # | 候选 | 真证据 | 反证 | 概率 |
|---|---|---|---|---:|
| #F1 | INSERT schtask / Celery task 真死 (LL-074 zombie) | 无 | A.5 commit `3a6c200` 4-17 18:44 有意图 mass migration; 没 schtask schedule registry INSERT (按需 onboarding) | ~2% |
| **#F2** | **流程改变 — 4-17 MVP 1.3a schema migration + 282 backfill, 4-17 后走新 onboarding path (G9+G10), 实验不形式注册** | A.5 commit `3a6c200` 真存在; A.5 281/286 行同 timestamp 4-17 18:31:52 (mass batch); Phase 2.4/3B/3D/3E NO-GO 不走 formal onboarding | 无 | **~95% ⭐** |
| #F3 | 手工流程 — 之前手工 INSERT, 4-17 后 user 没再做 | qm_platform/factor/registry.py:284 是代码 INSERT 路径 (非手工), 但 4-17 后 0 调用 | A.5 写明 "MVP 1.3c onboarding 强制化" — 即将代码化, 不是手工 | ~30% (部分真: 4-17 后实际无 onboarding 调用) |
| #F4 | registry 已 deprecate 但代码 / 文档没标 | 无 deprecate 文档 | A.4 W.1-W.6 6 处生产代码 active 写 registry | ~5% |
| #F5 | 文档 SSOT (FACTOR_TEST_REGISTRY.md "M=213") 4-11 末次更新, registry 4-17 mass backfill, 之间也漂移 | F-D78-60 P2 finding (已 GLOSSARY §11 沉淀) | 不是冻结根因, 是另一 drift | (与本 task 平行 finding, 不是冻结因) |

**主根**: #F2 ~95% — 设计层切换, 4-17 后无 formal onboarding 触发, 设计意图 (实验 NO-GO 不形式注册) 与 cite "registry 冻结" 自洽.

### §B.3 候选 action

| # | action | 描述 | 影响面 | 风险 | 优先级 |
|---|---|---|---|---|---|
| (a) | lifecycle 作 SSOT, registry deprecate | caller migrate 走 lifecycle, registry 表保留 read-only 或删 | A.4 6 处 W.1-W.6 写路径全改, factor_onboarding / qm_platform/factor/registry / health_daily / compute_factor_ic 全重构. 大改面 ~800 行 | 大改面, 中风险, 损失 Gate G1-G8 评估能力 (lifecycle 没 gate_ic/gate_ir/gate_t 字段) | P3 (反推荐) |
| (b) | registry 作 SSOT, 4-17 解冻 + 后续因子 backfill, lifecycle deprecate | 走 registry 替代 lifecycle | lifecycle 5 处写路径全改 (factor_profile / monitor_factor_ic), registry 加 entry_date / retired_date 字段; backfill 历史 lifecycle | 大改面, 中风险, 损失 lifecycle 时序追踪 | P3 (反推荐) |
| (c) | 两表保留, 显式语义分工 (lifecycle = 生命周期 / registry = 设计审批 + Gate), GLOSSARY enforce | 加 GLOSSARY footnote 沉淀两表语义不同; 加 ADR 显式 design 决策; 0 caller 改 | 加 1 GLOSSARY entry, 加 1 ADR. 0 代码改. | 极低 | **P2 (推荐 ⭐)** |
| (d) | yaml 作唯一 SSOT, 两表都 deprecate | 同 (a)+(b) 全 deprecate | 全部 caller (~365 行 hit) 全改 | 极大改面, 高风险, 损失 onboarding + lifecycle + Gate 全套 | P3 (强反推荐) |
| (e) | 现状保留 + ADR 沉淀 + GLOSSARY footnote (类似 task 4 (d)) | 0 改动 + 文档显式说明 | 加 1 ADR + 1 GLOSSARY entry | 极低 | (与 c 等价, 合并) |

### §B.4 推荐 (基于真证据)

**推荐 action (c) — 两表保留, GLOSSARY + ADR 沉淀语义分工**:

理由:
1. **不是 drift, 是设计正确分工** (主根 #4 ~95%) — lifecycle 跟踪生产生命周期 (yaml 4 镜像), registry 跟踪研究审批 + Gate 历史. 0 交集是预期.
2. **0 prod risk** — A.4 真测两表均不在生产 trading path 上.
3. **改动成本最低** — 加 1 GLOSSARY footnote + 1 ADR, vs (a)/(b)/(d) 大改面 ~800 行.
4. **保留两表能力** — Gate G1-G8 评估 (registry) + 生命周期 (lifecycle) 都是有价值的语义视图, 不该互相替代.

**user 决议参考**:
- 若优先 mental model 简化 → 走 (a) 或 (b) 大重构 (P3)
- 若优先 0 改动安全 → 走 **(c) ⭐ 推荐** (P2)
- 若担忧 latent risk → 同 (c), 加监控 invariant assertion (lifecycle.active = yaml.factors[] 强同步检查)

---

## §C 我没真测的 (transparency)

- **registry 26 active 各因子 last UPDATE 时间** — 是否 4-17 后有 UPDATE 但无 INSERT? 没真测 (本 task 仅测 created_at, 未测 updated_at).
- **factor_health_daily.py UPDATE registry 真行为** — schtask 真触发频率 + 真改 status 的行为没真测 (仅 grep).
- **monitor_factor_ic.py UPDATE lifecycle** — schtask 真触发频率 + 真改 status 的行为没真测.
- **registry status='warning' 246 行** — 各因子是 Gate decay 触发还是其他? 没分类.
- **factor_profile (53 行)** — 与 lifecycle 关系? 是 lifecycle 子集? 没深查 (boundary 候选第三 SSOT 但 row 数最少, 不像 SSOT).
- **factor_compute_version (276 行)** — 与 registry 关系? 没深查 (覆盖 GLOSSARY §3, 非本 task scope).
- **dv_ttm 在 registry 中 status='warning'** 真原因 — 是 Gate decay (合理) 还是 stale (bug)? 没真测.
- **DDL 状态机 comment 漂移** (factor_registry comment 写 5 状态, 实际 3 状态) — 是 finding 候选 (设计 vs 实施 drift), 沉淀但没深查.

---

## §D STOP trigger 评估

| # | 触发条件 | 真测结果 | 行动 |
|---|---|---|---|
| 1 | 两表真有生产 trading path 引用 + active list 真用 | A.4 真测 signal_engine 仅 1 处注释, run_paper_trading + execution_service 0 hit; 写路径全是研究/监控/前端 | ❌ 不 STOP |
| 2 | yaml 4 因子 与 lifecycle 4 active factor_name 真差 | 4 完全对齐 (bp_ratio / dv_ttm / turnover_mean_20 / volatility_20) | ❌ 不 STOP |
| 3 | 4-17 冻结因 INSERT path 生产死 | A.5 commit `3a6c200` MVP 1.3a 设计层 schema migration, 不是 schtask zombie | ❌ 不 STOP |
| 4 | 第三个相关表 (factor_status / factor_active / factor_metadata 类) | factor_profile/factor_compute_version/factor_evaluation/factor_health_log 各有不同语义 (GLOSSARY §3/§6/§7/§8 已覆盖); factor_profile 53 行 boundary 候选但语义不同 (画像不是 lifecycle/registry) | ⚠️ 边界, 一并报告但不 STOP |
| 5 | DB 表损坏 / 真测无法跑 | 全部 SQL 真跑 (除 1 unicode encoding 重试 ASCII 后通过) | ❌ 不 STOP |

**总结**: 0 硬 STOP. 1 边界 (#4 factor_profile/etc 已 GLOSSARY 覆盖). 全部 STOP 触发条件未达成.

---

## §E Memory / GLOSSARY / sprint state 更新建议

| 当前 cite | 实测真值 | 建议 |
|---|---|---|
| sprint state "factor_lifecycle 6 行 (4 active + 2 retired)" | ✅ 真测一致 | 沿用, 但加显式语义: "**生产策略生命周期 SSOT** = yaml 4 因子镜像 + 2 retired CORE5" |
| sprint state "factor_registry 286 行 (26 active / 14 deprecated / 246 warning)" | ✅ 真测一致 | 沿用, 但加显式语义: "**Gate G1-G8 评估 + 设计审批 SSOT**, 与 yaml 不直接对应 (yaml CORE 4 在 registry 中状态='warning'是设计)" |
| sprint state "Session 5 lifecycle, ratio=0.517 < 0.8" | ⚠️ **真测发现 lifecycle 表无 ratio 字段** | sprint state cite 可能误指 monitor_factor_ic.py 计算的 rolling_ic ratio, 不是 lifecycle 表字段. 建议 sprint state 修正 cite. |
| GLOSSARY §5 "factor_lifecycle = 6 (4+2)" | ✅ 真测一致 | 加 footnote: "**lifecycle.active ∩ yaml = 4** (完全对齐, 是 yaml 镜像)" |
| GLOSSARY §4 "registry 26 active" | ✅ 真测一致 | 加 footnote: "**registry.active ∩ lifecycle.active = 0**, 是设计 (语义不同), 不是 drift; yaml CORE 4 在 registry 中状态='warning'" |
| 推测"两表 SSOT 不清" | ❌ 真测两表语义不同 (lifecycle=生产生命周期 / registry=设计审批+Gate), 各自是其语义层的 SSOT | 修正 framing: "两表都是 SSOT, 但语义层不同, 不可比" (类似 task 2 113 vs 213 教训) |

🆕 新发现:
- **lifecycle.active 与 yaml 完全对齐 invariant** (4-12 cutover 同步: amihud_20 + reversal_20 retired_date=4-12, dv_ttm entry_date=4-12). lifecycle 是 yaml 镜像, 真主动同步.
- **registry yaml CORE 4 status='warning'** — 设计 (Gate decay 监控) 还是 stale, 需 Layer 2.5 评估.
- **registry DDL comment 状态机 5 状态 vs 实际 3 状态** drift — 设计 vs 实施 drift, 候选 finding (本 task 不修).
- **registry 4-17 冻结真因** = MVP 1.3a commit `3a6c200` mass migration + 设计层切换 (实验 NO-GO 不形式注册), 不是 zombie.
- **365 行代码引用** (lifecycle + registry) 全部在研究/监控/前端管理路径, 0 trading path 引用 — 与 task 4 strategy_configs 类似 (设计上不在生产 trading 链).

---

## §F 关联文档 / cross-link

- [docs/audit/factor_count_drift_2026_05_01.md](docs/audit/factor_count_drift_2026_05_01.md) — task 2 audit, framing 教训
- [docs/audit/yaml_vs_db_strategy_configs_drift_2026_05_02.md](docs/audit/yaml_vs_db_strategy_configs_drift_2026_05_02.md) — task 4 audit, 类似 category error 模式
- [docs/FACTOR_COUNT_GLOSSARY.md §4 / §5 / §11](docs/FACTOR_COUNT_GLOSSARY.md) — 两表的 GLOSSARY entry
- [configs/pt_live.yaml](configs/pt_live.yaml) — yaml SSOT
- [backend/qm_platform/factor/registry.py:284](backend/qm_platform/factor/registry.py:284) — MVP 1.3c onboarding 主入口
- [scripts/monitor_factor_ic.py:340](scripts/monitor_factor_ic.py:340) — lifecycle UPDATE 主路径
- commit `3a6c200` MVP 1.3a (4-17 18:44 schema migration + 282 backfill)
- commit `51b1409` (4-12 17:30 yaml cutover, lifecycle 同步)
- F-D78-60 P2 — registry/M cite stale (与本 task 平行, 不在 scope)
- 候选 ADR (本 audit 推荐 c): "ADR-XXX lifecycle 与 registry 语义分工显式声明" (P2, 走另一 sprint)

---

## §G 文档版本

- **v0.1** (2026-05-02): 初稿, 5 块真测 + 6 SSOT 候选 + 5 冻结根因候选 + 5 action 候选 + 推荐 (c). 0 修代码 / 0 改数据 / 0 解冻 / 0 PR. push branch `audit/factor-registry-lifecycle-2026-05-02` 等 user review.
