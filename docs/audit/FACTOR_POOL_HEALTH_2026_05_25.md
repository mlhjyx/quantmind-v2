# Factor Pool Health Audit — 2026-05-25

> Read-only file-based scan. No DB queries. Iter 52 cumulative (Wave 4 closeout window).
> Triggered by Session 50+ audit cycle (factor pool drift vs CORE 4 PT closure sustained 4-29~5-25).

---

## §1. CLAUDE.md "113 factor" cite location

- **Not in CLAUDE.md root.** Grep `113` in CLAUDE.md (D:\quantmind-v2\CLAUDE.md) returns 0 hits in factor-pool context (line 64 `840M` is row count; no `113 factor` literal).
- Truth source: **SYSTEM_STATUS.md:365** (D:\quantmind-v2\SYSTEM_STATUS.md) — "**113 factors** with ic_20d, **83 factors** with valid ic_ma20 (min_periods=5 限制)". Section header: "factor_ic_history 当前状态 (Session 23 Part 2 实测, 2026-04-22 01:35)".
- CLAUDE.md §因子池状态 (line 71-80) instead uses category buckets: CORE 4 / CORE5 5 / PASS候选 32+16 / INVALIDATED 1 / DEPRECATED 5 / 北向 15 / LGBM 70.

## §2. FACTOR_TEST_REGISTRY.md active count fresh verify

- **Cumulative M = 213** (74原始 + 128 Alpha158批量 + 6 Alpha158用户定义 + 5 PEAD-SUE验证, 2026-04-11 last formal update). FACTOR_TEST_REGISTRY.md:13.
- **PASS = 32** (FACTOR_TEST_REGISTRY.md:14) → 23 + 6 Alpha158-六 + 3 PEAD-SUE.
- **Active (PT 生产) = 4** (CORE: turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm), FACTOR_TEST_REGISTRY.md:36-38.
- Step 6.4 G1 sediment (2026-05-01): ~28+ post-4-11 experiments全 FAIL 未追加注册表; strict BH-FDR M ≈ 240 (FACTOR_TEST_REGISTRY.md:34).

## §3. factor_ic_history coverage claim location (CLAUDE.md)

- CLAUDE.md:84 — "factor_ic_history: **145,938 rows** (~36 MB) [iter 52 2026-05-25 fresh verify; vs Session 45 4-30 145,894 = +44 / +0.030% drift]".
- SYSTEM_STATUS.md:809 — "factor_ic_history | 145,938 | 2021-01-04 ~ ~2026-05-24 | **iter 52 2026-05-25 fresh verify**".
- SYSTEM_STATUS.md:363 — stale 4-22 snapshot 145,874 (note: "§2 table 57,711 是 2026-04-06 前的 stale 数字, **本 section 为准**"). 4-22 → 5-25 drift = +64 rows (+0.044%).

## §4. Alpha158 / 北向 15 / microstructure 16 / CORE 4 categorization sustained?

- **CORE 4**: ✅ sustained (CLAUDE.md:74, FACTOR_TEST_REGISTRY.md:36-38). PT config CORE3+dv_ttm WF OOS Sharpe=0.8659 4-12 PASS.
- **Alpha158 (158 因子)**: ✅ implemented `backend\engines\alpha158_factors.py` (9 KBAR + 4 PRICE + 145 ROLLING). Session 24 实测 alpha158_factors.py 完整, 仅 11 PEAD/earnings orphan (非 Alpha158).
- **北向 15**: ✅ CLAUDE.md:79 — "nb_ratio_change_5d 等, IC反向 (direction=-1), G1特征池".
- **microstructure 16**: ✅ CLAUDE.md:76 + FACTOR_TEST_REGISTRY.md:32 (Phase 3E-II 16/16 noise ROBUST + neutral IC PASS, WF 0/6 PASS — alpha 等权框架无法利用, not active).
- **LGBM 70**: ⚠️ CLAUDE.md:80 (48 核心 + 15 北向 + 7 新因子 Phase2.1, DB 自动发现). LGBM ML synthesis Phase 3D CLOSED, ML 特征池 retain.

## §5. Drift findings (claims vs actual files)

1. **"113 active factors" 用语漂移**: 113 是 factor_ic_history 有 ic_20d 的因子数 (SYSTEM_STATUS.md:365 Session 23 Part 2 4-22 snapshot), **非 active PT 因子数** (实际 active = 4 CORE). Audit prompt 用 "113 active factors" 不准确, 应为 "113 factors with ic_20d coverage".
2. **113 是 4-22 stale snapshot**: SYSTEM_STATUS.md:362 标 "Session 23 Part 2 实测, 2026-04-22 01:35". 5-25 当前 factor_ic_history=145,938 (vs 4-22 145,874 = +64 rows), factor count drift 未 fresh verify (留 future audit DB query: `SELECT COUNT(DISTINCT factor_name) FROM factor_ic_history WHERE ic_20d IS NOT NULL`).
3. **M=213 vs 实际实验 ≈ 240**: 28+ Phase 2.4/3B/3D/3E 实验未追加注册表 (理由: 全 FAIL + alpha 上限 closed). 不影响生产, 但严格 BH-FDR 视角下 M 应订正 (FACTOR_TEST_REGISTRY.md:34 已 sediment audit log).
4. **factor_ic_history vs factor_values 存在性匹配**: 0 DB query, 无法实测. 留 future audit. 历史 Session 24 实测仅 11 orphan (alpha158 完整, PEAD/earnings 基本面缺失).
5. **dv_ttm 健康 warning**: FACTOR_TEST_REGISTRY.md:39 — "dv_ttm ⚠️ active → warning (ratio=0.517 < 0.8)" Session 5 lifecycle, PT 仍包含, 4-29 PT 已 cleared (0 持仓), warning 状态自然冻结.

## §6. Cite source (4 元素 / each claim, V3 §quantmind-v3-cite-source-lock)

| Claim | path | line# | section | fresh verify timestamp |
|---|---|---|---|---|
| "113 factors with ic_20d" | D:\quantmind-v2\SYSTEM_STATUS.md | 365 | factor_ic_history 当前状态 | 2026-04-22 01:35 (Session 23 Part 2, **stale by 33d**) |
| CORE 4 active | D:\quantmind-v2\CLAUDE.md | 74 | §因子池状态 | iter 52 2026-05-25 |
| M = 213 / PASS = 32 | D:\quantmind-v2\FACTOR_TEST_REGISTRY.md | 13-14 | §累积统计 | 2026-04-11 末次正式 |
| factor_ic_history = 145,938 | D:\quantmind-v2\CLAUDE.md | 84 | §因子存储 | iter 52 2026-05-25 fresh verify |
| factor_ic_history = 145,938 | D:\quantmind-v2\SYSTEM_STATUS.md | 809 | DB 表 | iter 52 2026-05-25 fresh verify |
| Alpha158 = 158 factors | D:\quantmind-v2\backend\engines\alpha158_factors.py | 4 | docstring header | 文件 mtime (未 fresh verify) |
| dv_ttm warning | D:\quantmind-v2\FACTOR_TEST_REGISTRY.md | 39 | §累积统计 active 因子池 | Session 5 lifecycle (4-18) |

---

## Recommendation (≤5 lines)

1. **Update "113" stale 33d** — SYSTEM_STATUS.md:365 引用 4-22 snapshot, 5-25 iter 52 已有 fresh row count (145,938) 但 distinct factor_name 未 fresh verify. 留 next DB query window (`pg_ctl` + `psql`).
2. **Clarify "113" 语义** — 改 "113 factors with ic_20d coverage" 替代 "113 active factors" 防 confusion. Active PT = 4 sustained.
3. **M 漂移 sediment ok** — FACTOR_TEST_REGISTRY.md:34 已注明 M ≈ 240 strict BH-FDR, 生产决策 unaffected.
4. **Factor pool 整体健康**: CORE 4 sustained / Alpha158 完整 / 北向 15 完整 / microstructure 16 (not active by design). PT 4-29 cleared, factor 评估冻结状态自然.
5. **红线 5/5 sustained**: cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / Audit doc read-only no commit.
