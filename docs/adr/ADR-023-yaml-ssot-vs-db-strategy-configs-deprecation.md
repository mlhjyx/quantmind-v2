# ADR-023: yaml SSOT vs DB strategy_configs deprecation

> **Status**: Proposed (5-02 起草, 等 user 决议; user merge PR = Accept signal)
> **Date**: 2026-05-02
> **Authors**: Claude.ai 起草 + CC task 4 audit evidence
> **Related**:
> - [docs/audit/yaml_vs_db_strategy_configs_drift_2026_05_02.md](../audit/yaml_vs_db_strategy_configs_drift_2026_05_02.md) (5-02 task 4 真测证据)
> - [docs/audit/strategy_factor_config_callers_deep_2026_05_02.md](../audit/strategy_factor_config_callers_deep_2026_05_02.md) (5-02 task 2.5.1 audit, FU-1 真测 + v0.4 metadata patch trigger)
> - [docs/FACTOR_COUNT_GLOSSARY.md](../FACTOR_COUNT_GLOSSARY.md) §10 (5-02 task 3, DB strategy_configs ⚠️ stale 标注)
> - [docs/audit/factor_count_drift_2026_05_01.md](../audit/factor_count_drift_2026_05_01.md) (5-01 task 2, 9+ factor count semantic)
> - [docs/adr/ADR-024-factor-lifecycle-vs-registry-semantic-separation.md](ADR-024-factor-lifecycle-vs-registry-semantic-separation.md) (5-02 task 5 配套, 因子治理域 yaml SSOT 系列)

## §1 Context

### 1.1 当前真状态 (5-02 task 4 实测)

QuantMind PT 生产策略配置存在双源:

| Source | 真值 | 真路径 |
|---|---|---|
| `configs/pt_live.yaml` | 4 因子 (CORE3+dv_ttm: turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm) | ✅ 生产读路径 (`backend/engines/signal_engine.py:247`) |
| DB `strategy_configs.config->'factors'` (latest version) | 5 因子 (CORE5: turnover_mean_20 / volatility_20 / reversal_20 / amihud_20 / bp_ratio) | ⚠️ stale, 47 天冻结 (5-02 真测) |
| DB `strategy.factor_config` (jsonb) | 同 5 因子 + 真 stale 参数详见下表 (v0.4 修订) | ⚠️ stale, 同根 |

第二字段 `strategy.factor_config` 字段 drift 真测 (v0.4 patch, Layer 2.5.1 真测):

| 字段 | DB 真值 | yaml 真值 | drift 判定 (5-02 task 2.5.1 真测) |
|---|---|---|---|
| factors | 5 (CORE5) | 4 (CORE3+dv_ttm) | ⚠️ stale |
| industry_cap | 0.25 | 1.0 | ⚠️ stale |
| commission_rate | 0.00015 | 0.0000854 | ⚠️ stale (差 1.76x) |
| slippage_bps | 10.0 (fixed_bps mode) | (volume_impact mode) | ⚠️ mode 不匹配 (不只是值差异) |
| turnover_cap | 0.5 | 0.5 | ✅ same (本 ADR v0.3 误标, v0.4 修正) |
| weight_method | "equal" | "equal_weight" (compose) | ✅ 字段名差异等价 (本 ADR v0.3 误标, v0.4 修正) |
| **🆕 top_n** | **v2=15 / v1=20** | **20** | **⚠️ v2 漂移 (本 ADR v0.3 漏列, v0.4 加)** |

> **v0.4 修订** (2026-05-02 task 2.5.1 真测): 原 v0.3 表标 "6 字段全 stale", 真测后判定: **4 真 stale + 2 字段误标 + 1 字段漏列**. ADR §2 决议 (yaml SSOT + 防御层) 不变 — 0 prod path 真用 stale (FU-1 真测 sustained). 仅元数据修订, 不触发 §2 reversibility (§2.4).

### 1.2 历史 timeline (5-02 task 4 git 真测)

| 时点 | commit | 事件 |
|---|---|---|
| 2026-03-21 19:03 | (setup) | `setup_paper_trading.py:85` 一次性 INSERT 5 CORE5 进 strategy_configs + strategy.factor_config |
| 2026-03-22 03:39 | (setup) | strategy_configs v2 同 CORE5 |
| 2026-04-09 12:36 | `2eb2e56` | yaml 系统引入 (Step 4-B "YAML 配置驱动") |
| 2026-04-12 17:30 | `51b1409` | yaml CORE5→CORE3+dv_ttm cutover (WF OOS Sharpe=0.8659). **0 DB sync / 0 migration / 0 ADR** ⚠️ |
| 5-02 | (本 ADR) | stale 沉淀决议 |

### 1.3 真风险评估 (5-02 task 4 + task 5 caller 真测)

`grep -rn` 全代码库引用真测:

| Source | 真路径数 | 真用途 | prod risk |
|---|---|---|---|
| `strategy_configs` (14 处) | 14 | 0 trading / 1 API factors 仅前端 / 1 一次性 INSERT (3-22 后冻结) / 4 docstring / 3 测试 / 1 archived | ⚠️ medium (前端展示 stale) |
| **`factor_lifecycle / factor_registry` (365 行)** | **365** | **0 trading path** (signal_engine.py 仅 1 处注释; run_paper_trading.py + execution_service.py 0 hit). 写路径全在研究 onboarding / 监控 / 画像 / 前端管理 / 一次性 migration (task 5 audit 真测沉淀) | ✅ 无 |

`/api/execution/algo-config` (execution.py:190): 不取 factors, **真读哪些字段未深查 (FU-1 范围)**.

**结论**: 0 生产 trading path 引用. 仅前端展示 + `/api/execution/algo-config` 真读字段未深查 (FU-1).

## §2 Decision

### 2.1 SSOT 决议

**`configs/pt_live.yaml` 是 PT 生产策略配置唯一 SSOT**.

DB `strategy_configs` + `strategy.factor_config` 是 **legacy snapshot** (setup 时一次性 INSERT 后冻结), **不在生产读路径**, 仅作历史版本记录 + 前端展示用途.

### 2.2 处理方式 — 现状保留 + 防御层

采纳 task 4 audit 推荐 (d), 加防御层:

**保留**:
- DB 两字段 (strategy_configs.config + strategy.factor_config) **read-only 保留**, 不删除 (历史版本价值)
- DB 不再 sync yaml (反 (a) sync schtask — cutover 频率低不值得)
- DB 不 deprecate 表 (反 (b) — 13 caller 改动成本 vs 0 prod risk 不划算)

**防御层** (反"修文档不修根因"反驳):
- `setup_paper_trading.py` 顶部加 deprecated comment + module-level fail-loud (`raise DeprecationWarning(...)` 防未来再跑 INSERT 重演 stale 模式)
- 前端 `/api/strategies/{id}` 加静态 banner: "DB 配置为历史快照. 当前生产以 configs/pt_live.yaml 为准 (cutover 2026-04-12). DB 不 sync."
- 任何代码 / 文档 / 分析需引用生产策略配置时, **必走 yaml**, 不读 DB

### 2.3 Cutover SOP 与 enforce 机制

为防"4-12 cutover 0 ADR" 重演, 任何修改 `configs/pt_live.yaml` 的 commit 必须:

1. commit message 显式 cite 此 ADR-023 (或后续替代 ADR)
2. PR description 列出 cutover 影响面 (因子 / 风险参数 / 等)
3. 不需要 sync DB (设计如此, DB 是 archive)

**Enforce**: pre-commit hook 加 check (Layer 2.2 CI enforce sub-task 范围) — touch `configs/pt_live.yaml` 的 commit 必须 message 含 "ADR-" 或 "skip-adr-check" 标记, 否则 fail. 实施由 Layer 2.2 sprint, 本 ADR 仅声明.

**反向条款**: 任何后续修改 DB strategy_configs / strategy.factor_config 的 PR 需:
1. 显式说明为何不走 yaml
2. cite 此 ADR-023 并说明 exception
3. user 显式授权

### 2.4 Decision reversibility

此 ADR 决议**可逆**. 如果未来真生产真有 driver 改 SSOT (例:多策略并行, yaml 单文件无法表达; 或 DB 真有读路径需求), 可重新决议:
- 走新 ADR supersedes 此 ADR
- 真测 driver 后再决议, 不预设方向

## §3 Consequences

### 3.1 立即影响

- ✅ 0 生产 trading caller 改动 (0 引用)
- ✅ 0 数据 backfill / migration
- ✅ 0 prod 风险 (LIVE_TRADING_DISABLED 整期保持, 0 .env / 0 schema 改动)
- ⚠️ 前端 `/api/strategies/{id}` UI banner 改动 (FU-2, ~30 行 React)
- ⚠️ `setup_paper_trading.py` deprecated comment + fail-loud (FU-7, 新加)
- ✅ GLOSSARY §10 footnote 已加 (5-02 task 3, 与本 ADR 同步)

### 3.2 长期影响

- 任何分析 / 报表 / backtest 引用生产策略配置必走 yaml — 减少踩坑 (类似 task 2 audit "X vs Y drift Z%" trap 防范)
- DB 历史版本保留作 archive — 后续审计 / 复盘可用
- Cutover SOP + pre-commit hook enforce — 反"4-12 cutover 0 ADR 真 gap"重演

### 3.3 反对意见 (alternative considered)

- **(a) sync DB → yaml**: 反对. cutover 频率低 (3-22~4-12 唯一一次), schtask 维护成本 > 真受益. sync 后 DB 仍非 SSOT, 不消除 mental model 双源.
- **(b) deprecate DB strategy_configs**: 反对. 13 caller 改动 (尤其 `/api/strategies/{id}` 前端展示链), P3 工作量, 0 prod risk 不值得.
- **(c) 双向同步 yaml ↔ DB**: 反对. race / divergence 风险, 测试覆盖成本高. CC task 4 audit 显式反推荐.

## §4 Stale 字段清单 (本 ADR cover 范围, v0.4 patch)

DB `strategy.factor_config` 真 stale 字段清单 (v0.4 修订, Layer 2.5.1 真测):

| 字段 | DB stale | yaml | 防误读处理 |
|---|---|---|---|
| factors | 5 (CORE5) | 4 (CORE3+dv_ttm) | GLOSSARY §10 footnote ✅ + 前端 banner |
| industry_cap | 0.25 | 1.0 | 前端 banner + 本 ADR §1 真值表 |
| commission_rate | 0.00015 | 0.0000854 | 同上 |
| slippage_bps | fixed_bps mode @ 10 | volume_impact mode | 同上 (mode 不一致, 比值差异更深) |
| **🆕 top_n** | **v2=15 / v1=20** | **20** | **同上 (v0.4 加)** |

> v0.4 修订: 去 turnover_cap 行 (实测 yaml=DB=0.5 same) + 去 weight_method 行 (字段名差异不是值差异) + 加 top_n 行 (strategy_configs v2 漂 yaml=20 vs v2=15). 详见 §1.1 v0.4 修订段.

## §5 Follow-up

| # | 项 | 优先级 | 归属 |
|---|---|---|---|
| FU-1 | 6 字段 caller 深查 — ✅ **DONE** (5-02 task 2.5.1 audit, 0 prod path 真用 stale, ADR §2 决议 sustained) | P2→done | [docs/audit/strategy_factor_config_callers_deep_2026_05_02.md](../audit/strategy_factor_config_callers_deep_2026_05_02.md) |
| FU-2 | 前端 `/api/strategies/{id}` UI banner 实施 (静态文案, ~30 行 React) | P2 | frontend ticket (随时起) |
| FU-3 | GLOSSARY §10 footnote 与本 ADR cross-link verify (双向) | P3 | 本 ADR PR 顺手做 |
| FU-4 | factor_evaluation 表 (5-02 task 3 标 0 行) 启用时机决议 | P3 | Layer 2.5 (proposed) sub-task |
| FU-5 | strategy_evaluations / strategy_status_log / strategy_registry 表是否同 stale (5-02 task 4 transparency) | P3 | Layer 2.5 (proposed) sub-task |
| FU-6 | docs/audit/yaml_vs_db_strategy_configs_drift_2026_05_02.md 末尾加 ADR-023 反向 cross-link | P3 | 本 ADR PR 顺手做 |
| FU-7 | `setup_paper_trading.py` 标 deprecated + module-level fail-loud | P2 | 本 ADR PR 顺手做 (~10 行) |
| FU-8 | pre-commit hook 加 yaml change 验 ADR cite (cutover SOP enforce) | P2 | Layer 2.2 CI enforce sub-task |
| **FU-9** | **lifecycle vs registry 语义分工显式声明 → 见 ADR-024 (5-02 task 5 配套)** | P2 | ADR-024 已 cover |
| **FU-10** | **registry DDL comment 5 状态 vs 实际 3 状态 drift fix (CHECK 约束缺失) — 设计 vs 实施 drift, 微 fix** | P3 | Layer 2.5 (proposed) micro PR |

## §6 Verification

### ADR PR scope (反 scope creep)

本 ADR PR **仅** 包含:
- `docs/adr/ADR-023-yaml-ssot-vs-db-strategy-configs-deprecation.md` 新文件 (本 ADR)
- `docs/FACTOR_COUNT_GLOSSARY.md` §10 cross-link 修正 (FU-3)
- `docs/audit/yaml_vs_db_strategy_configs_drift_2026_05_02.md` 末尾 ADR cross-link (FU-6)
- `scripts/setup_paper_trading.py` 顶部 deprecated comment + fail-loud (FU-7, ~10 行)

**禁止** scope:
- ❌ 修任何 prod 代码 (signal_engine / execution_service / run_paper_trading)
- ❌ 改 DB schema / schema migration / 任何 row UPDATE
- ❌ 实施前端 banner (FU-2 frontend ticket)
- ❌ 实施 pre-commit hook (FU-8 Layer 2.2)
- ❌ deprecate caller / 删 endpoint
- ❌ 跑 PT / 重启 / 改 .env

### Merge 后 verify

```bash
# 1. yaml 真值未变 (cutover 后 stable)
grep -A 8 "factors:" configs/pt_live.yaml

# 2. signal_engine 仍走 yaml
grep -n "_build_paper_trading_config\|PAPER_TRADING_CONFIG" backend/engines/signal_engine.py

# 3. DB strategy_configs 真值仍 < ADR proposed date (验证我们没动)
PGPASSWORD=quantmind psql -U xin -h localhost -d quantmind_v2 -c \
  "SELECT MAX(created_at) FROM strategy_configs;"
# 期望: < 2026-05-02 (本 ADR 起草日)

# 4. cross-link 完整
grep "ADR-023" docs/FACTOR_COUNT_GLOSSARY.md docs/audit/yaml_vs_db_strategy_configs_drift_2026_05_02.md

# 5. setup_paper_trading.py deprecated marker 真存在
grep -n "DeprecationWarning\|deprecated" scripts/setup_paper_trading.py
```

## §7 Change Log

| Date | Author | Change |
|---|---|---|
| 2026-05-02 v0.1 | Claude.ai 起草 + CC task 4 audit evidence | Proposed |
| 2026-05-02 v0.2 | Claude.ai self-reflection | 10 项修订 (enforce / 防御层 / scope / reversibility / 反 calendar bias) |
| 2026-05-02 v0.3 | Claude.ai post-task5 reflection | 4 项修订: §1 Related 加 ADR-024 / §1.3 caller 表加 lifecycle+registry 365 行 row / §5 FU-9 加 ADR-024 cross-link / §5 FU-10 加 registry DDL drift fix |
| 2026-05-02 v0.4 | Claude.ai + CC task 2.5.1 audit | metadata patch (§2 决议不变): §1.1 表 6→7 字段 (修 turnover_cap+weight_method 误标 / 加 top_n / 修 slippage_bps mode 描述 + v0.4 修订段) / §4 stale 清单 5 行同步修订 / §5 FU-1 standdone (cite Layer 2.5.1 audit) / §1 Related 加 audit cross-link / GLOSSARY §10 footnote 同步 |
| (TBD) | user | Accepted / Rejected / Modified |
