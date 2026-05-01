# FACTOR_COUNT_GLOSSARY — 因子计数语义防误读 SSOT

> **建立日期**: 2026-05-02 (Task 3 沉淀)
> **触发**: Task 2 audit ([docs/audit/factor_count_drift_2026_05_01.md](docs/audit/factor_count_drift_2026_05_01.md)) 发现 9+ factor count 语义共存, "113 vs 213 drift" 是 category error. user 5-01 已踩坑一次, 沉淀防误读 GLOSSARY.
> **维护责任**: 加新 factor count source / 改 hook canonical 之前必先更新本 GLOSSARY (见末段 §加新 count 流程).
> **关联**: [docs/audit/factor_count_drift_2026_05_01.md](docs/audit/factor_count_drift_2026_05_01.md) (audit 起源) / [CLAUDE.md L40-46](CLAUDE.md) (因子池状态表) / [FACTOR_TEST_REGISTRY.md](FACTOR_TEST_REGISTRY.md) (M SSOT) / [config/hooks/pre-commit](config/hooks/pre-commit) (canonical 5 metric)

---

## 0. TL;DR — 速查表 (5-02 真测真值, drift vs 5-01 audit)

| # | source | 真值 | 5-01 audit | drift | 一句话语义 |
|---|---|---:|---:|---:|---|
| 1 | factor_ic_history DISTINCT factor_name | **113** | 113 | 0% | ⭐ pre-commit hook canonical (有 IC 入库的因子) |
| 2 | factor_values DISTINCT factor_name | **276** | 276 | 0% | 已计算因子值的因子 |
| 3 | factor_compute_version DISTINCT factor_name | **276** | (未列) | n/a 🆕 | 算法版本注册的因子 (= source 2 same SSOT) |
| 4 | factor_registry total | **286** | 286 | 0% | 形式注册总条目 (4-17 后冻结) |
| 4a | factor_registry status='active' | **26** | 26 | 0% | registry 中 active |
| 4b | factor_registry status='deprecated' | **14** | 14 | 0% | registry 已废弃 |
| 4c | factor_registry status='warning' | **246** | 246 | 0% | registry 警告 (lifecycle 未通过) |
| 5 | factor_lifecycle 全 | **6** (4 active + 2 retired) | 6 (4+2) | 0% | 形式 lifecycle 跟踪 |
| 6 | factor_evaluation | **0** | 0 | 0% | 空表 (留存) |
| 7 | factor_profile | **53** | 53 | 0% | Profiler V2 画像输出 |
| 8 | factor_health_log | **5** | 5 | 0% | 健康日志 |
| 9 | **configs/pt_live.yaml** factors[] (生产 SSOT) | **4** (CORE3+dv_ttm) | (未直接列) 🆕 | n/a | ⭐ 真生产 PT 用的因子 (yaml 是 SSOT, signal_engine.py:247 PAPER_TRADING_CONFIG) |
| 10 | DB strategy_configs.config->'factors' (latest version) | **5** (CORE5) | (未直接列) 🆕 | n/a | ⚠️ stale, **不是生产真用**, 仅 DB 历史快照 |
| 11 | FACTOR_TEST_REGISTRY.md "M" (BH-FDR cumulative) | **213** | 213 | 0% | 历史累积测试事件计数 (74+128+6+5, 4-11 末次 sustained) |
| 12 | CLAUDE.md L40-46 因子池状态 (人工 cohort) | **CORE=4 / CORE5=5 / PASS候选=32+16=48 / INVALIDATED=1 / DEPRECATED=5 / 北向 RANKING=15 / LGBM 特征=70** | 同 | 0% | 设计层 cohort 划分 (各 cohort 重叠 / 互斥规则不同) |

**🆕 5-02 新发现**: source #3 / #9 / #10 是本 task Stage A 真测扩展, Task 2 audit 没直接列入对照表.
**关键 finding**: source #9 (yaml) vs source #10 (DB strategy_configs) 不一致 — yaml 4 个 (CORE3+dv_ttm) 是生产 SSOT, DB strategy_configs 5 个 (CORE5) 是 stale snapshot 未同步. **PT 真用 yaml 4 个**, DB 不在生产读路径上 (signal_engine.py:247 走 yaml). 沉淀为 finding 候选, **不在本 GLOSSARY scope 修**.

---

## 1. factor_ic_history DISTINCT factor_name

| 字段 | 值 |
|---|---|
| **当前真值** | 113 (5-02 真测) |
| **真定义** | factor_ic_history 表中 distinct factor_name 数. 即"至少有 1 行 IC 已成功入库" 的因子. 是 source #2 (factor_values) 的 IC 入库子集. |
| **真测命令** | `SELECT count(DISTINCT factor_name) FROM factor_ic_history;` |
| **何时引用** | (a) pre-commit hook canonical (config/hooks/pre-commit:38-41 沿用此 query); (b) 评估因子审批进度 (有 IC 才能算 t-stat / paired bootstrap); (c) BH-FDR 校正 M 候选基准 (但当前 SSOT M 走 source #11) |
| **何时不应该用** | (a) ❌ 不要写"当前 factor 库 113 个" — 是 IC 入库子集, 不是 factor 库全量; (b) ❌ 不要与 source #11 (M=213) 直接做差 — 不同语义 (subset 静态 vs cumulative event); (c) ❌ 不要作为"PT 真用因子数" — PT 真用 source #9 yaml (4 个) |
| **历史 anchor** | hook 引入: PR #193 commit `a6a41f4` (2026-05-01 Phase 4.2 Layer 4 Topic 1 A); 113 真值 sustained 至少自 5-01 audit (PR #194). 写 path: `scripts/compute_daily_ic.py` (Mon-Fri 18:00 schtask, PR #37+#40), `scripts/compute_ic_rolling.py` (PR #43+#44), `scripts/fast_ic_recompute.py` (PR #45 partial UPSERT 例外). |

---

## 2. factor_values DISTINCT factor_name

| 字段 | 值 |
|---|---|
| **当前真值** | 276 (5-02 真测) |
| **真定义** | factor_values 表中 distinct factor_name 数. 即"至少有 1 行因子值已成功计算入库" 的因子. 是 source #4 (factor_registry 286) 的实际计算子集. 与 source #3 (factor_compute_version) 等价 SSOT. |
| **真测命令** | `SELECT count(DISTINCT factor_name) FROM factor_values;` |
| **何时引用** | (a) 评估系统真"装得下" 的因子库容量; (b) factor_engine 计算覆盖率指标; (c) F-D78-60 finding 比对 (M=213 vs factor_values 276 真测漂移) |
| **何时不应该用** | (a) ❌ 不要作为"hook canonical" — hook 走 source #1 (113); (b) ❌ 不要作为"因子审批通过数" — 计算 ≠ 审批 (审批要 IC + 画像 + Gate G1-G10); (c) ❌ 不要直接写到 BH-FDR M cite — M 是历史累积事件, 不是当前 distinct |
| **历史 anchor** | factor_values 是 TimescaleDB hypertable (CLAUDE.md cite 840M+ rows / 152 chunks / ~172GB). MAX trade_date 2026-04-28 (CLAUDE.md cite, audit 实测). 写路径: factor_engine + DataPipeline (铁律 17), 单源入库. |

---

## 3. factor_compute_version DISTINCT factor_name

| 字段 | 值 |
|---|---|
| **当前真值** | 276 (5-02 真测) — 与 source #2 等同 |
| **真定义** | factor_compute_version 表中 distinct factor_name 数. 算法版本注册表, schema: (factor_name, version, compute_commit, compute_start, compute_end, algorithm_desc). 当前 active version 索引 `idx_fcv_factor_active`: `WHERE compute_end IS NULL`. |
| **真测命令** | `SELECT count(DISTINCT factor_name) FROM factor_compute_version;` |
| **何时引用** | (a) factor 算法版本演进追溯 (compute_commit + algorithm_desc); (b) 因子结果可复现验证 (铁律 15: regression_test 复盘); (c) factor_values 与算法版本绑定查询 |
| **何时不应该用** | (a) ❌ 与 source #2 (factor_values) 语义近似但**不要作 single source** — 应同步用; (b) ❌ 不要混入"因子库总数" cite — 是版本注册, 不是因子注册 (后者走 source #4 factor_registry) |
| **历史 anchor** | DDL 在 docs/QUANTMIND_V2_DDL_FINAL.sql 定义. 用于 factor_engine 算法版本切换 (e.g. fast_neutralize 改进时). 与 source #2 同步 (276=276) 是设计 invariant. |

---

## 4. factor_registry (total / active / deprecated / warning)

| 字段 | 值 |
|---|---|
| **当前真值** | total **286** / active **26** / deprecated **14** / warning **246** (5-02 真测) |
| **真定义** | factor_registry 表中 distinct name 数. 形式注册表, schema 含 (id uuid, name, category, direction, expression, code_content, hypothesis, source, lookback_days, status, gate_ic, gate_ir, ...). status 4 值: active / deprecated / warning / (其他可能值). created_at 范围 2026-03-28 ~ 2026-04-17 — **4-17 后冻结**, Phase 3B/3D/3E 后续因子未注册到此表. |
| **真测命令** | `SELECT count(*) FROM factor_registry;`<br>`SELECT status, count(*) FROM factor_registry GROUP BY status ORDER BY status;` |
| **何时引用** | (a) 形式注册的因子总集 (历史 + 当前); (b) 各 status 分布看 lifecycle 健康度; (c) 与 source #5 (factor_lifecycle) 对比看跟踪窄度 |
| **何时不应该用** | (a) ❌ 不要写"系统当前 286 个因子" — 4-17 后冻结, 不反映 Phase 3B/3D/3E ~28 实验; (b) ❌ active=26 不等同于"生产真用" — 生产真用走 source #9 yaml (4 个); (c) ❌ warning=246 不是 bug 大头 — 是 lifecycle 设计标记, 不影响计算 |
| **历史 anchor** | 表 created_at MIN=2026-03-28 / MAX=2026-04-17 (3-28~4-17 注册期). 4-17 后冻结的根因 (Phase 2.4/3B/3D/3E 跑实验但不注册) 关联 F-D78-60 [P2] (Layer 2 sprint 处理). |

---

## 5. factor_lifecycle (total / active / retired)

| 字段 | 值 |
|---|---|
| **当前真值** | total **6** (active **4** + retired **2**) (5-02 真测) |
| **真定义** | factor_lifecycle 表中 GROUP BY status 行数. 形式 lifecycle 跟踪表, 仅 6 个因子被纳入跟踪 — **远窄于 source #4 active=26**. |
| **真测命令** | `SELECT status, count(*) FROM factor_lifecycle GROUP BY status;` |
| **何时引用** | (a) Phase 3 MVP A factor_lifecycle.py 周五 19:00 schtask 评估; (b) factor 生命周期管理 (active → warning → retired); (c) PT 真用因子健康度 (4 active 中 dv_ttm Session 5 lifecycle warning, ratio=0.517 < 0.8) |
| **何时不应该用** | (a) ❌ 不要等同于 "factor_registry status='active' 26" — lifecycle 比 registry active 窄 ~6.5x; (b) ❌ 不要写"系统真有 6 个因子" — 是跟踪子集, 不是因子库; (c) ❌ retired=2 不是"已下线" 真值 — 走 source #4 deprecated=14 |
| **历史 anchor** | factor_lifecycle.py + Celery 周五 19:00 (Phase 3 MVP A, 2026-04-17 引入, 26/26 tests). 当前 active 4 个: turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm (CORE3+dv_ttm) — 与 source #9 yaml 完全对齐. |

---

## 6. factor_evaluation

| 字段 | 值 |
|---|---|
| **当前真值** | 0 (5-02 真测) |
| **真定义** | factor_evaluation 表中行数. 表存在但**当前空**. 设计用途未启用 (留存表 / Wave 5+ 用?). |
| **真测命令** | `SELECT count(*) FROM factor_evaluation;` |
| **何时引用** | 当前**不引用** — 0 行无意义. 沉淀为提示: 表存在但没在生产路径上, 加 metric 前先确认是否启用. |
| **何时不应该用** | ❌ 任何场景 — 0 行不能作为因子计数 |
| **历史 anchor** | DDL 在 docs/QUANTMIND_V2_DDL_FINAL.sql 定义. 启用时机未沉淀, 候选 finding (本 GLOSSARY 不修, user 决议是否走 finding sprint). |

---

## 7. factor_profile

| 字段 | 值 |
|---|---|
| **当前真值** | 53 (5-02 真测) |
| **真定义** | factor_profile 表中行数. 因子画像 (Profiler V2 输出, 5 维 IC + 衰减 + 单调性 + 成本 + 冗余). 53 个因子已生成画像. |
| **真测命令** | `SELECT count(*) FROM factor_profile;` |
| **何时引用** | (a) 因子审批前 5 维评估 (CLAUDE.md "因子画像 V2 评估协议"); (b) 与 source #4 (factor_registry) 对比看画像覆盖率 (53/286 = 18.5%); (c) 模板匹配 (T1-T15 因子模板) 数据来源 |
| **何时不应该用** | (a) ❌ 不要等同于"已审批因子数" — 审批要 Gate G1-G10 + paired bootstrap, 画像仅 1 步; (b) ❌ 53 不是 IC 入库 (走 source #1) 也不是计算覆盖 (走 source #2) |
| **历史 anchor** | factor_profiler V2 在 2026-04-05 引入 (CLAUDE.md "性能优化 8 项 + ARIS"). 53 行 ≈ 18.5% factor_registry 覆盖率, 反映画像滞后于注册. |

---

## 8. factor_health_log

| 字段 | 值 |
|---|---|
| **当前真值** | 5 (5-02 真测) |
| **真定义** | factor_health_log 表中行数. 健康日志, 短滚动窗口 (近期 health check 输出). |
| **真测命令** | `SELECT count(*) FROM factor_health_log;` |
| **何时引用** | (a) 短期健康监测; (b) 钉钉告警关联因子健康问题 (FactorHealthDaily schtask 17:30) |
| **何时不应该用** | ❌ 任何"factor 总数" cite — 5 是健康日志条数, 不是因子数 |
| **历史 anchor** | FactorHealthDaily schtask (CLAUDE.md cite). 滚动写入, 老 log 自动 GC, 5 行是当前快照. |

---

## 9. configs/pt_live.yaml — 生产 SSOT (⭐)

| 字段 | 值 |
|---|---|
| **当前真值** | **4** (CORE3+dv_ttm: turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm) |
| **真定义** | configs/pt_live.yaml 中 `strategy.factors[]` 列表长度. **生产 PT 真用因子的 SSOT** (signal_engine.py:247 `PAPER_TRADING_CONFIG = _build_paper_trading_config()` 加载本 yaml). 替代散落在 .env / config.py / signal_engine 的旧配置 (Step 4-B sustained, 铁律 15). |
| **真测命令** | `grep -A8 "^  factors:" configs/pt_live.yaml`<br>或: `python -c "import yaml; print(len(yaml.safe_load(open('configs/pt_live.yaml'))['strategy']['factors']))"` |
| **何时引用** | (a) ⭐ "PT 真用 N 个因子" — N 走本 source; (b) 回测入口 `python scripts/run_backtest.py --config configs/pt_live.yaml`; (c) 与 source #5 (factor_lifecycle active=4) 对照, **应一致**, 不一致是 finding |
| **何时不应该用** | (a) ❌ 不要回 DB strategy_configs (source #10) 拿生产因子 — 那是 stale; (b) ❌ 不要凭印象写 "5 个因子 (CORE5)" — CORE5 是历史 (Session 17 之前), 4-12 已 cutover 到 CORE3+dv_ttm |
| **历史 anchor** | yaml 引入: Step 4-B (configs/pt_live.yaml 创建, 替代散落配置). 因子从 CORE5 (5 个) cutover 到 CORE3+dv_ttm (4 个) 时间 2026-04-12 (WF OOS Sharpe=0.8659 PASS). 详见 [SYSTEM_STATUS.md §0](SYSTEM_STATUS.md). |

---

## 10. DB strategy_configs.config->'factors' (latest version) ⚠️

| 字段 | 值 |
|---|---|
| **当前真值** | **5** (CORE5: turnover_mean_20 / volatility_20 / reversal_20 / amihud_20 / bp_ratio) — **stale, 不是生产真用** |
| **真定义** | strategy_configs 表 latest version 的 config jsonb 中 factors 数组长度. 当前 strategy `28fc37e5-2d32-4ada-92e0-41c11a5103d0` (PAPER_STRATEGY_ID) 有 v1 + v2 两版, 都是 5 因子 CORE5. 与 source #9 yaml (4 个 CORE3+dv_ttm) **不一致** = stale snapshot, 未同步到生产 cutover. |
| **真测命令** | `SELECT version, jsonb_array_length(config->'factors') AS factor_count, config->'factors' FROM strategy_configs ORDER BY created_at DESC LIMIT 5;` |
| **何时引用** | ⚠️ **几乎不引用** — 生产 PT 不读此表 (走 yaml). 仅 (a) DB schema 历史 audit; (b) finding 候选 (yaml vs DB drift, 沉淀但本 GLOSSARY 不修) |
| **何时不应该用** | (a) ❌ **不要作为"PT 真用因子"** — 生产真用 source #9 yaml; (b) ❌ 不要写"系统配置 5 个因子" — yaml 已 cutover 到 4 个 (CORE3+dv_ttm); (c) ❌ 不要 backfill / 同步此表 — 见 §加新 count 流程 (本 GLOSSARY scope 0 改) |
| **历史 anchor** | strategy_configs v1 + v2 都是 CORE5, 4-12 yaml cutover 到 CORE3+dv_ttm 时未同步 DB strategy_configs (流程债, 候选 finding). 真生产读路径走 [`backend/engines/signal_engine.py:247`](backend/engines/signal_engine.py:247) `PAPER_TRADING_CONFIG = _build_paper_trading_config()`, 不读 DB. |

---

## 11. FACTOR_TEST_REGISTRY.md "M" — BH-FDR 累积测试事件计数

| 字段 | 值 |
|---|---|
| **当前真值** | **213** (74 原始 + 128 Alpha158批量 + 6 Alpha158用户定义 + 5 PEAD-SUE验证, 4-11 末次正式更新) |
| **真定义** | FACTOR_TEST_REGISTRY.md L13 cite 的累积测试事件计数. **不是当前 factor 数**, 而是历史累积**测试事件**计数, 用于 BH-FDR (Benjamini-Hochberg False Discovery Rate) 多重测试校正阈值 α/M (Harvey Liu Zhu 2016 模型). 一次因子测试 = 一个事件, 测试 N 次同因子 = N 个事件. |
| **真测命令** | `grep "累积测试总数 M" FACTOR_TEST_REGISTRY.md`<br>或: `grep "M=213" CLAUDE.md FACTOR_TEST_REGISTRY.md` |
| **何时引用** | (a) BH-FDR α 校正阈值计算 (因子审批硬标准 t > 2.5 + α/M FDR 校正); (b) 学术/审计沉淀历史测试规模 |
| **何时不应该用** | (a) ❌ **绝不要写"系统当前 M 个因子"** — M 是事件计数, 不是 factor 数. user 5-01 task 2 audit 实测踩坑此 trap (113 vs 213 framing 是 category error); (b) ❌ 不要与 source #1 (113) 或 source #2 (276) 直接做差; (c) ❌ 不要凭印象写"M=84"或其他旧值 — Step 6.4 G1 commit `53d6218` 把 CLAUDE.md L328 "M=84" 改 "M=213" 是 5-01 修订, 当前 SSOT 213 |
| **历史 anchor** | 4-11 末次正式更新 (FACTOR_TEST_REGISTRY.md), 不含 Phase 2.4/3B/3D/3E ~28 后续实验. Step 6.4 G1 STATUS_REPORT 自身 broader+1 标注 "真 M ≈ 240". F-D78-60 [P2] finding (Layer 2 sprint 处理) 提议 sync 到 ≥276. 当前 sustained 4-11 SSOT, 不在本 GLOSSARY scope 修. |

---

## 12. CLAUDE.md L40-46 因子池状态 (人工 cohort)

| 字段 | 值 |
|---|---|
| **当前真值** | CORE=**4** (PT 在用) / CORE5=**5** (前任基线) / PASS候选=**32+16** / INVALIDATED=**1** / DEPRECATED=**5** / 北向 RANKING=**15** / LGBM 特征=**70** |
| **真定义** | CLAUDE.md L40-46 表格中 7 个因子 cohort 划分 (人工编辑维护). 各 cohort 重叠 / 互斥规则不同, 不直接相加. 是设计层语义视图, 不是 DB 一行一查的真值. |
| **真测命令** | `grep -A10 "^### 因子池状态" CLAUDE.md`<br>或: `sed -n '40,46p' CLAUDE.md` |
| **何时引用** | (a) 设计文档 / 协作上下文里需要 "因子分群语义" (e.g. CORE 是生产 / CORE5 是回测基线 / 北向是 G1 特征池); (b) 与 DB query 真值交叉验证 |
| **何时不应该用** | (a) ❌ 不要把这些数字当 DB 真值 — 是人工维护, 可能漂移; (b) ❌ 不要直接相加 cohort 数 (4+5+48+1+5+15+70 ≠ 因子库总数) — 重叠 cohort 不互斥; (c) ❌ "PASS 候选 32+16" 实际 = 32 PASS (含 Alpha158 6 + PEAD-SUE) + 16 microstructure WF FAIL — 加号语义不是简单求和 |
| **历史 anchor** | CLAUDE.md 维护时人工同步, 铁律 22 (文档跟随代码). Phase 3B/3D/3E NO-GO 后 PASS 候选数字 sustained, 4 因子 = 等权 alpha 上限 closed. 详见 [research-kb/findings/](docs/research-kb/findings/). |

---

## 13. (历史 cite) "factor=213 / factor count 213" — **不要用** ❌

| 字段 | 值 |
|---|---|
| **当前真值** | **不存在此语义** ❌ |
| **真定义** | 没有 source 真定义 "factor count = 213". 凡引用 "213" 而以为是 factor 数, 全是 source #11 (BH-FDR M cumulative test events) 误读. user 5-01 task 2 audit 实测此 framing 是 category error. |
| **真测命令** | `grep -rnE "factor[s]?=213|factor.*=.*213" --include="*.md" --include="*.py" .` → 实测 0 行 |
| **何时引用** | ❌ **永不引用** — 无 source |
| **何时不应该用** | (a) ❌ 任何 framing "drift = 213 - X" 都是 category error; (b) ❌ task 2 audit 完整记录此 trap, 走那里 cross-link 防再踩 |
| **历史 anchor** | task 2 audit ([docs/audit/factor_count_drift_2026_05_01.md](docs/audit/factor_count_drift_2026_05_01.md)) 5-01 实测沉淀, 本 GLOSSARY 显式列入"反 cohort" 防再 framing. |

---

## §A. 常见误读模式 (基于 task 2 audit 教训)

### A.1 "X vs Y drift Z%" 类 trap

错误 framing 模板: "[source A 真值 X] vs [source B cite Y], drift = (Y - X) / X = Z%, 远超 hook 1% threshold".

**真因**: source A 与 source B 是不同语义 metric (如 ic_history subset vs BH-FDR cumulative event), 不可减.

**user 5-01 实测踩坑案例**:
- A = factor_ic_history DISTINCT (source #1, 113)
- B = BH-FDR M cumulative (source #11, 213)
- drift framing: 47% gap
- 实测真因: A 是当前因子的 IC 子集, B 是历史累积测试事件 — **incommensurable**, 减法无意义

**防范**:
- 任何 "factor=N" cite 必显式 source (e.g. "factor_ic_history DISTINCT N", 不写 "factor N")
- 任何 drift framing 必先验证两 metric 同语义
- 走 handoff_template.md §3 cite SOP (Phase 4.2 Layer 4 Topic 1 C, sustained sprint state cite SOP)

### A.2 "PT 真用 N 个因子" 类 stale

错误源:
- DB strategy_configs (source #10) — **stale 5 个 CORE5**
- 凭印象 / 旧 handoff cite

**真源 SSOT**:
- configs/pt_live.yaml (source #9) — **生产 4 个 CORE3+dv_ttm**
- factor_lifecycle status='active' (source #5) — 应同步 yaml, 4 个

**防范**:
- 引 PT 因子数必走 yaml SSOT
- DB strategy_configs **不在生产读路径上** (signal_engine.py:247 走 yaml)
- 加 finding (本 GLOSSARY scope 0 修, 仅沉淀): yaml vs DB drift, 候选 sync schtask 或 cutover deprecate strategy_configs

### A.3 cohort 求和 trap

错误 framing 模板: "CLAUDE.md 因子池 = CORE(4) + CORE5(5) + PASS(48) + ... = N 总因子".

**真因**: cohort 重叠 (CORE5 ⊃ CORE / PASS 候选含 Alpha158 也在 factor_values / 北向独立池). 求和无意义.

**防范**:
- cohort 视图仅做语义分群, 不算总因子数
- 算总数走 source #2 (factor_values 276) 或 #4 (factor_registry 286)

### A.4 "M = 当前因子数" trap

错误等价: "M=213 = 系统现有 213 个因子".

**真因**: M 是 BH-FDR 多重测试校正用的**累积测试事件**计数, 4-11 sustained, 不是 distinct factor 数.

**防范**:
- M 必显式标 "BH-FDR cumulative test events"
- CLAUDE.md L328 / FACTOR_TEST_REGISTRY.md L13 已含 "累积测试总数" 表述, 引用时不剥离语义
- 与 source #2 (factor_values) 真测对照看 M stale (F-D78-60 finding)

### A.5 hook canonical 113 ≠ "因子库容量"

错误等价: "pre-commit hook factor=113 = 当前因子库 113 个".

**真因**: hook 选 source #1 (factor_ic_history) 是 design 决议 (Layer 4 Topic 1 A), 是 IC 入库子集, 不是因子库容量. 因子库容量走 source #2 (276) 或 #4 (286).

**防范**:
- hook canonical 名字加 "_ic" 后缀提示语义 (候选改进, 本 GLOSSARY 不修)
- 引用 hook 真值时显式 "ic_history subset"

---

## §B. 加新 count source 流程 (将来加新表 / 新 metric, 必先沉淀)

任何加新的 factor count source (新 DB 表 / 新 yaml / 新 hook metric / 新 doc cite) 必须先做完以下步骤再 PR:

1. **先在本 GLOSSARY 加新 section** (#14, #15, ...), 5 字段全填:
   - 当前真值 (附测试命令运行的真值 + 测试时间)
   - 真定义 (semantic, 一句话区分于其他 source)
   - 真测命令 (能复现的 SQL / grep / Python)
   - 何时引用 (使用场景)
   - 何时不应该用 (防误读, 显式列出与哪些 source 易混淆)

2. **更新 §0 速查表**

3. **检查 §A 误读模式** — 是否新 source 引入新 trap, 必加新 §A.x

4. **Cross-link**:
   - 引入 PR # + commit hash (历史 anchor)
   - 与已有 source 的对应关系 (subset / equivalent / orthogonal)

5. **PR 走 review** — 不预设方向, 不 AI self-merge (本 GLOSSARY 防误读 SSOT, 改动需 user 显式确认)

6. **同步铁律 22** (文档跟随代码) — 加新表 / 新 yaml 时, 此 GLOSSARY 同步是 commit 必带条件 OR `NO_DOC_IMPACT` 显式声明

### B.1 反例 (不要做)

- ❌ 加新 hook metric 但不更新本 GLOSSARY → user 下次又踩 framing 误判
- ❌ 加新表 (e.g. factor_evaluation 启用) 但本 GLOSSARY 还写 "0 行" → cite stale
- ❌ 改 source #1 (hook canonical 选其他 query) 但本 GLOSSARY 还写 113 → user/CC 误读
- ❌ DB strategy_configs sync 到 yaml 但本 GLOSSARY 还写 source #10 stale → cite stale

---

## §C. 关联文档 / cross-link

| 文档 | 关系 |
|---|---|
| [docs/audit/factor_count_drift_2026_05_01.md](docs/audit/factor_count_drift_2026_05_01.md) | ⭐ task 2 audit, 本 GLOSSARY 起源. 详细列 9+ source 真测 + "213" cite 全 grep + 7 候选 root cause + framing 修订建议 |
| [CLAUDE.md L40-46](CLAUDE.md) | 因子池 cohort 表 (source #12), 本 GLOSSARY §12 引用 |
| [CLAUDE.md L328](CLAUDE.md) | BH-FDR M cite (source #11), 本 GLOSSARY §11 引用 |
| [FACTOR_TEST_REGISTRY.md L13](FACTOR_TEST_REGISTRY.md) | M=213 SSOT 定义, 本 GLOSSARY §11 引用 |
| [configs/pt_live.yaml](configs/pt_live.yaml) | 生产 SSOT (source #9), 本 GLOSSARY §9 引用 |
| [config/hooks/pre-commit](config/hooks/pre-commit) | hook canonical 实现 (source #1), 本 GLOSSARY §1 引用 |
| [backend/engines/signal_engine.py:247](backend/engines/signal_engine.py:247) | 生产读 yaml 入口, 本 GLOSSARY §9 引用 |
| [docs/handoff_template.md §3](docs/handoff_template.md) | cite SOP (Phase 4.2 Layer 4 Topic 1 C), 本 GLOSSARY §A.1 引用 |
| F-D78-60 [P2] | M=213 vs factor_values 276 stale finding, Layer 2 sprint 处理, 本 GLOSSARY §11 引用 |
| F-D78-163 [P3] | Bailey & López de Prado 高级多重测试校正 (White Reality Check / SPA) 0 sustained finding, 本 GLOSSARY 不直接覆盖 |
| 候选新 finding | yaml vs DB strategy_configs drift (source #9 vs #10), 本 GLOSSARY §10 提示, 不在本 scope 修 |

---

## §D. 文档版本 / 维护

- **v0.1** (2026-05-02): 初稿, 13 section + 5 误读模式 + 6 步加新流程. 基于 task 2 audit 5-01 实测 + task 3 5-02 真测扩展. 0 修代码 / 0 改 cite / 0 backfill.
- 维护频次: 任何 source 真值变化 / 加新 source / 改 hook canonical 时必同步.
- 真测复现: 本 GLOSSARY 中所有 "真测命令" 5-02 真验证可复现. 后续维护必保持此 invariant.
