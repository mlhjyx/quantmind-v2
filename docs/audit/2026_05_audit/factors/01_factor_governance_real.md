# Factors Review — 因子治理 + Model Risk + Real IC

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / factors/01
**Date**: 2026-05-01
**Type**: 评判性 + 实测 IC + Model Risk Management (CC 扩 M1/M3/M4)

---

## §1 因子库真测 (CC 5-01 实测 PG)

### 1.1 真 schema 真值

| 表 | DISTINCT factor 数 | 真 schema |
|---|---|---|
| **factor_values** | **276 distinct factor_name** | code/trade_date/factor_name/raw_value/neutral_value/zscore |
| **factor_ic_history** | **113 distinct factor_name** | factor_name/trade_date/ic_1d/5d/10d/20d/abs/ma20/ma60/decay_level |

**🔴 重大 finding**:
- **F-D78-57 [P2]** sprint state CLAUDE.md 多次写 "factor_id" 字段, 真 schema 是 **`factor_name`** (字段名漂移 + 同 type alias 漂移, 沿用 F-D78-2 cb_state 同源 anti-pattern)
- **F-D78-58 [P2]** factor_values 276 distinct factor_name vs factor_ic_history 113 distinct = **163 因子有 raw 数据但 0 IC 入库** (沿用铁律 11 sustained "未入库 IC 视为不存在", 163 因子 candidate 全等同不存在)

### 1.2 CORE3+dv_ttm 真测 IC (2026-04-28 latest)

实测 SQL:
```sql
SELECT factor_name, MAX(trade_date), AVG(ic_20d)
FROM factor_ic_history
WHERE factor_name IN ('turnover_mean_20','volatility_20','bp_ratio','dv_ttm')
GROUP BY factor_name;
```

| factor_name | latest trade_date | AVG(ic_20d) | direction sustained |
|---|---|---|---|
| turnover_mean_20 | 2026-04-28 | -0.0957 | -1 ✅ (negative) |
| volatility_20 | 2026-04-28 | -0.0905 | -1 ✅ (negative) |
| bp_ratio | 2026-04-28 | +0.0586 | +1 ✅ (positive) |
| dv_ttm | 2026-04-28 | +0.0397 | +1 ✅ (positive) |

**判定**: ✅ CORE3+dv_ttm 4 因子全 sustained sign + magnitude reasonable. **0 推翻 sprint period sustained "CORE3+dv_ttm WF OOS Sharpe=0.8659" 假设** (本审查 IC 真测 + 历史 WF 验证 align).

**finding**:
- F-D78-23 (复) [P2] dv_ttm 4-28 IC=+0.0397 (绝对值小, sustained Session 5 lifecycle ratio < 0.8 警告 sustained, 真测 verify warning sustained). 沿用 sprint period sustained 未升级决议

---

## §2 Model Risk Management gap (CC 扩 M4)

简化 SR 11-7 框架审 (项目 0 沉淀):

| Model Risk 维度 | sprint period sustained | gap |
|---|---|---|
| **Model documentation** | CORE3+dv_ttm WF PASS 沉淀 / docs/research-kb/findings | ⚠️ research-kb 8 failed + 25 findings + 5 decisions, 但 model card 0 sustained (无 Datasheets for Datasets / Model Cards) |
| **Independent validation** | reviewer agents (sprint period sustained) | ⚠️ reviewer 是 LL-098 同源 AI 自审, 不是真独立 |
| **Performance monitoring** | factor_lifecycle weekly Beat (周五 19:00) + IC monitor | ✅ 部分 cover, 但 Wave 4 MVP 4.1 alert 真触发统计 0 (沿用 risk_event_log 仅 2 行) |
| **Limit framework** | T1.3 V3 design 沉淀 (D-L0~L5 5+1 层) | 🔴 L0/L2/L3/L4/L5 全 ❌ 0 实施 |
| **Stress testing** | Phase 3D ML Synthesis 4 实验 + Phase 3E 16 微结构 | ⚠️ 测试历史在 docs/research-kb 但 stress test sustained 0 自动 (无 auto stress test pipeline) |
| **Backtesting validation** | regression max_diff=0 sustained 铁律 15 | ⚠️ 真 last-run + 真 max_diff 未本审查 verify |

**finding**:
- **F-D78-59 [P1]** Model Risk Management 框架 0 sustained, model card / independent validation / auto stress test pipeline 全 candidate 缺. 1 人项目走简化版 SR 11-7 候选 (本审查 0 决议, 仅候选)

---

## §3 Multiple Testing 校正 verify (CC 扩 M1)

CLAUDE.md sustained "BH-FDR校正: M=213 累积测试" sustained:

实测 SQL:
- factor_values 276 distinct vs CLAUDE.md "M=213 累积测试" — **M=213 候选 stale** (因子库已扩到 276 factor_name, M 应同步扩)
- 沿用 ADR-022 sustained 反 "数字漂移高发" — M=213 是 sprint period sustained 4-11 末次更新 (CLAUDE.md sustained sustained), Phase 3B/3D/3E 后续实验未沉淀 (CLAUDE.md sustained sustained 沉淀)

**finding**:
- **F-D78-60 [P2]** CLAUDE.md "BH-FDR M=213" 数字漂移, factor_values 276 distinct factor_name 真测 = 累积测试已 ≥ 276 (M sustained 4-11 末次更新, Phase 3B/3D/3E 后续未同步), BH-FDR 校正阈值候选 stale

---

## §4 因子谱系 + alpha decay (CC 扩 M3 候选)

(本审查未深查 CORE3+dv_ttm + 历史因子 alpha decay 时序. 留 sub-md 深查. 候选 finding):

- 候选 sub-md factors/02_alpha_decay.md
- 真测: 30/90/180/365 day rolling IC mean trend by factor

---

## §5 因子拥挤度 (CC 扩 — 未深查)

(本审查未深查因子拥挤度 vs 学术因子 + vs 公开量化基金风格. 留 sub-md 深查 candidate finding):

- 候选 sub-md factors/03_crowding.md
- 真测: CORE3+dv_ttm 4 因子 vs 公开量化基金披露因子 (e.g. AQR / 等) 真重叠度

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-57 | P2 | sprint state CLAUDE.md 写 "factor_id" 字段, 真 schema 是 `factor_name` (字段名漂移) |
| F-D78-58 | P2 | factor_values 276 distinct vs factor_ic_history 113 distinct, 163 因子有 raw 数据但 0 IC 入库 (铁律 11 sustained 等同不存在) |
| **F-D78-59** | **P1** | Model Risk Management 框架 0 sustained (model card / independent validation / auto stress test 全缺), 1 人项目候选简化版 SR 11-7 |
| F-D78-60 | P2 | CLAUDE.md "BH-FDR M=213" 数字漂移 (4-11 末次更新, factor_values 276 distinct 已超), BH-FDR 校正阈值候选 stale |
| F-D78-23 (复) | P2 | dv_ttm 4-28 IC=+0.0397 绝对值小, sustained Session 5 lifecycle warning 未升级决议 |

---

**文档结束**.
