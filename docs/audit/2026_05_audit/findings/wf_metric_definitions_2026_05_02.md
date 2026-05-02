# Walk-Forward 4 指标真定义 + 4 治理债 finding (5-02 sprint sediment)

> **沉淀日期**: 2026-05-02
> **触发**: 5-02 双合并调查任务 B (4 指标真定义 + 4-12 cite verdict). 4 项 finding F-WF-1/2/3/4 候选 sediment 落地.
> **关联铁律**: 25 (改什么读什么) / 26 (验证不可跳过) / 36 (precondition)
> **关联 LL**: LL-101 (audit cite 必 SQL/git/log/file 真测 verify before 复用) 沿用 SOP
> **0 prod 代码改 / 0 SQL 写 / 0 schtask / 0 hook bypass**

---

## §1 5 折真定义 (Walk-Forward 5-fold)

### 1.1 真测 source

[scripts/research/wf_phase24_validation.py:275](../../../../scripts/research/wf_phase24_validation.py#L275):

```python
WFConfig(
    n_splits=5,
    train_window=750,    # ~3 年
    gap=5,               # 防前瞻偏差
    test_window=250,     # ~1 年
)
```

[cache/phase24/wf_validation_results.json](../../../../cache/phase24/wf_validation_results.json) timestamp `2026-04-12 16:30:04` (config_id=1 "CORE3+dv_ttm+SN050 Top20 Monthly").

### 1.2 真定义

| 项 | 真值 | source |
|---|---|---|
| n_splits | **5** | wf_phase24_validation.py:275 |
| train_window | **750 交易日** (~3 年) | wf_phase24_validation.py:275 |
| gap | **5 交易日** (防前瞻偏差) | wf_phase24_validation.py:275 |
| test_window | **250 交易日** (~1 年) | wf_phase24_validation.py:275 |
| 总跨度需要 | 750 + 5 + 5×250 = **2005 交易日 (~8 年)** | 推算 |
| 滚动方式 | **滚动** (rolling), 每 fold train 起点向后推 ~1 年 | cache wf_validation_results.json:36-105 fold train_period diff |
| 真 train 起点 | **2018-01-02** (NOT 2014, fold 0 train_start) | cache wf_validation_results.json:34 |
| 5 fold test 期 | 2021-02 / 2022-02 / 2023-03 / 2024-03 / 2025-03 (滚动 1 年间隔) | cache fold[0-4] test_period |

→ 真**有效 train+test 窗口 = 2018-2026 8 年**, NOT 12 年.

---

## §2 OOS Sharpe 真定义 (combined.oos_sharpe)

### 2.1 真测 source

[scripts/research/wf_phase24_validation.py:351](../../../../scripts/research/wf_phase24_validation.py#L351):

```python
oos_sharpe = result.combined_oos_sharpe
```

`result` 来自 `WalkForwardEngine.run()`. `combined_oos_sharpe` = 5 fold OOS daily NAV 拼接 (1250 trade days total) → calc_sharpe(returns).

### 2.2 真定义 + 真值

| 项 | 真值 | source |
|---|---|---|
| **真公式** | `combined_oos_sharpe` = 5 fold OOS NAV 拼接 1250 day → calc_sharpe | wf_phase24_validation.py:351 |
| **NOT** fold mean | (1.6786 + 0.286 + 0.1882 + 0.5192 + 1.2652) / 5 = **0.7874** ≠ 0.8659 | 算术 verify |
| CORE3+dv_ttm 真值 | **0.8659** ✅ | cache wf_validation_results.json results.1.combined.oos_sharpe |
| 5 fold 真值 (chronological) | fold 0=**1.6786** / fold 1=**0.286** / fold 2=**0.1882** / fold 3=**0.5192** / fold 4=**1.2652** | cache results.1.folds[0-4].oos_sharpe |
| dispersion | max/min = 1.6786 / 0.1882 = **8.92x** | 算术 |
| total OOS days | 1250 (5 × 250) | cache results.1.combined.total_oos_days |

### 2.3 真新 finding (顺手发现)

prompt cite "5 fold 真值 0.1882/0.286/0.5192/1.2652/1.6786" 是**升序排序后值**, 真**chronological 顺序**为 1.6786/0.286/0.1882/0.5192/1.2652 (fold 0→4). 不影响指标真值, 但**真 fold-by-fold 时序信息被 cite 丢失**. 真应保留 chronological 顺序 cite.

---

## §3 STABLE 真定义 — 🔴 跨脚本两套标准

### 3.1 LOOSE (wf_phase24_validation.py:385)

```python
stability = "STABLE" if sharpe_std < 1.0 and n_negative <= 1 else "UNSTABLE"
```

**2-tier**: `STABLE` (std<1.0 AND neg≤1) / `UNSTABLE` (其他).

### 3.2 STRICT (wf_equal_weight_oos.py:395-402)

```python
if std < 0.15 and neg_folds == 0:
    verdict = "STABLE — 折间 Sharpe std < 0.15 且无负 fold"
elif std < 0.4 and neg_folds == 0:
    verdict = "REGIME_DEPENDENT — std 中等, 需要分年度归因"
elif neg_folds > 0:
    verdict = "UNSTABLE — 存在负 Sharpe fold, 策略在某时期失效"
else:
    verdict = "HIGH_VARIANCE — 折间差异大"
```

**4-tier**: `STABLE` (std<0.15 AND neg=0) / `REGIME_DEPENDENT` (std<0.4 AND neg=0) / `UNSTABLE` (neg>0) / `HIGH_VARIANCE` (其他).

### 3.3 CORE3+dv_ttm 真值在两套下分别判定

| 真值 | LOOSE (wf_phase24:385) | STRICT (wf_equal_weight:395-402) |
|---|---|---|
| sharpe_std=**0.5839** | < 1.0 ✅ | < 0.15 ❌ / < 0.4 ❌ |
| n_negative=**0** | ≤ 1 ✅ | == 0 ✅ |
| **判定** | **STABLE** ✅ | **HIGH_VARIANCE** (std 0.5839 >> 0.15 阈值, neg=0) |

→ 同 CORE3+dv_ttm 真值, **两套标准判定相反** (LOOSE STABLE / STRICT HIGH_VARIANCE).

---

## §4 Overfit Ratio 真定义 — 🔴 跨脚本阈值不一致

### 4.1 wf_phase24_validation.py 真定义

[scripts/research/wf_phase24_validation.py:348](../../../../scripts/research/wf_phase24_validation.py#L348):

```python
overfit_ratio = round(result.combined_oos_sharpe / full_sample_sharpe, 4)
```

[scripts/research/wf_phase24_validation.py:327](../../../../scripts/research/wf_phase24_validation.py#L327):

```python
p20 = price_df[price_df["trade_date"] >= date(2020, 1, 1)]
```

→ `full_sample_sharpe` 真**6 年窗口** (2020-2026), NOT 12 年.

[scripts/research/wf_phase24_validation.py:377](../../../../scripts/research/wf_phase24_validation.py#L377):

```python
logger.info("  Overfit Ratio:        %s (full=%.4f, >0.50 needed)", overfit_ratio, full_sample_sharpe or 0)
```

→ 阈值: **>0.50 needed**.

### 4.2 wf_equal_weight_oos.py 真定义

[scripts/wf_equal_weight_oos.py:386-388](../../../../scripts/wf_equal_weight_oos.py#L386-L388):

```python
"overfit_ratio": round(chain_sharpe / in_sample_sharpe, 4)
if in_sample_sharpe
else None,
```

→ 公式: `chain_sharpe / in_sample_sharpe` (in_sample 来自 metrics_12yr.json, **真 12 年 in-sample**).

[scripts/wf_equal_weight_oos.py:467](../../../../scripts/wf_equal_weight_oos.py#L467):

```python
print(f"  过拟合比率:        {summary['overfit_ratio']} (>0.7 好, <0.5 严重过拟合)")
```

→ 阈值: **>0.7 好 / <0.5 严重**.

### 4.3 真值验算

CORE3+dv_ttm 真值: combined_oos_sharpe=0.8659 / full_sample_sharpe=1.0341 → 0.8659/1.0341 = **0.8373** ✅ (cache results.1.analysis.overfit_ratio).

| 阈值 | wf_phase24 (>0.50) | wf_equal_weight (>0.7 好) |
|---|---|---|
| 真值 0.8373 | ✅ pass (>0.50) | ✅ "好" (>0.7) |

CORE3+dv_ttm 真**两套阈值都过**, 但 marginal config (e.g. 0.6) 真**两套结果矛盾**.

### 4.4 真新 finding (顺手发现)

- wf_phase24 full_sample 真**6yr 窗口** (2020-2026)
- wf_equal_weight in_sample 真**12yr 窗口** (来自 metrics_12yr.json cache)
- 同一"过拟合比率"概念真**分母窗口不一致** — wf_phase24 真 OOS / 6yr-in-sample, wf_equal_weight 真 OOS / 12yr-in-sample. 两套真**不可比**.

---

## §5 4 项治理债 finding

### F-WF-1 [P3 治理] STABLE 跨脚本判定不一致

**触发**: §3 真证据. wf_phase24:385 LOOSE (std<1.0+neg≤1) vs wf_equal_weight:395-402 STRICT (std<0.15+neg=0). 同 CORE3+dv_ttm 真值 std=0.5839, **LOOSE 判 STABLE / STRICT 判 HIGH_VARIANCE 真矛盾**.

**真生产含义**: 4-12 PT 配置 PASS 决议**真依赖 LOOSE 标准**, 若用 STRICT 会判定 PT 配置不稳 (sharpe_std=0.5839 远超 0.15 阈值).

**修法 (留 future PR)**: 统一 STABLE 判定. 候选: (a) 全用 LOOSE 沿用 wf_phase24 / (b) 全用 STRICT 沿用 wf_equal_weight / (c) 第三套 (e.g. std<0.5+neg=0) 重新校准. **真治理决议留 user 决议**.

### F-WF-2 [P3 治理] Overfit Ratio 阈值跨脚本不一致

**触发**: §4 真证据. wf_phase24:377 ">0.50 needed" vs wf_equal_weight:467 ">0.7 好/<0.5 严重". 阈值差 0.2.

**真生产含义**: marginal config (overfit ratio=0.6) 真**两套结果矛盾** — wf_phase24 PASS, wf_equal_weight 不算"好". CORE3+dv_ttm 0.8373 不踩此 boundary.

**修法 (留 future PR)**: 统一 Overfit Ratio 阈值. 候选: (a) 全 ">0.5" / (b) 全 ">0.7 好/<0.5 严重" 三档.

### F-WF-3 [P2 doc] wf_equal_weight_oos.py docstring 12yr 误导

**触发**: [scripts/wf_equal_weight_oos.py docstring](../../../../scripts/wf_equal_weight_oos.py) cite "数据范围: 2014-01-01 ~ 2026-04-09 (cache/backtest/2014-2026/*.parquet)". 真**train 起点 2018-01-02** (need 750 trade days warmup → 2018 起跑), fold 4 test 终 2026-04-10. 真有效 train+test 跨度 **~8 年 (2018-2026)**, NOT 12 年.

**真生产含义**: docstring 12yr 是 cache 数据范围, NOT train 范围. 误导读者认为 WF 真用 12yr train. 真**8yr train + 4yr cache 历史 (2014-2018) 真未参与 WF**.

**修法 (留 future PR)**: docstring "数据范围: 2014-2026 12 年" → "Cache 数据范围: 2014-2026 12 年; 真 WF train 范围: 2018-2026 8 年 (前 4 年 warmup)".

### F-WF-4 [P2 真值] full_sample_sharpe 真 6yr 窗口 (NOT 12yr)

**触发**: [scripts/research/wf_phase24_validation.py:327](../../../../scripts/research/wf_phase24_validation.py#L327) 真值 `price_df[price_df["trade_date"] >= date(2020, 1, 1)]` (6yr filter). full_sample_sharpe=1.0341 (CORE3+dv_ttm config_id=1) 真跑的是 **2020-2026 6 年**, 不是 docstring 暗示的 12 年.

**真生产含义**: Overfit Ratio 真分母是 6 年 in-sample Sharpe, **不是 cite 的"12 年 in-sample"**. 真"过拟合"判定窗口偏短, 6yr 含 2022-2024 弱 alpha 期 ⇒ in-sample sharpe 偏低 ⇒ overfit_ratio 偏高 (artifact 真**视觉过拟合反而不严重**).

**修法 (留 future PR)**: (a) wf_phase24 改用 12yr full_sample (与 wf_equal_weight 对齐) / (b) 文档明示 6yr 真窗口 + reasoning 选 6yr 不选 12yr / (c) 留 4-12 历史决议保持现状, 仅 doc reference.

---

## §6 4-12 cite vs 真值 verdict (4 项)

| 4-12 cite | 真值 | verdict |
|---|---|---|
| OOS Sharpe = 0.8659 | 0.8659 | ✅ 一致 |
| 5 fold 全正 (n_negative=0) | n_negative_folds=0 | ✅ 一致 |
| STABLE | "STABLE" (LOOSE 标准 wf_phase24) | ✅ 一致 (但 STRICT 标准会判 HIGH_VARIANCE — F-WF-1) |
| Overfit Ratio = 0.84 | 0.8373 | ✅ 一致 (rounding 误差 0.7%) |

→ **4 项指标真值 vs 4-12 cite 完全一致** ✅, 真 PASS 条件 (sharpe>=0.72 / mdd>=-0.4 / beats_baseline>0.6521) 三件全过.

**rounding 误差 0.7%** 在 LL-101 SOP 接受范围 (≥5% 漂移 STOP). 0.84 vs 0.8373 真值四舍五入合规.

---

## §7 真重要 finding — sim-to-real gap 不被 WF 验证 (audit F-D78-85 真证据加深)

### 7.1 真测 source

[cache/phase24/wf_validation_results.json](../../../../cache/phase24/wf_validation_results.json) results.1.folds[4].test_period = `["2025-03-31", "2026-04-10"]`.

### 7.2 真发现

5 fold test 期最后 = **2026-04-10**. **4-29 PT 真生产事件** (688121.SH 卓然新能 -29% / 000012.SZ 南玻 -10%) 发生在 2026-04-29, **不在任何 fold test 期内**.

| fold | test 期 | 含 4-29 真生产事件? |
|---|---|---|
| 0 | 2021-02-08 ~ 2022-02-23 | ❌ |
| 1 | 2022-02-24 ~ 2023-03-06 | ❌ |
| 2 | 2023-03-07 ~ 2024-03-15 | ❌ |
| 3 | 2024-03-18 ~ 2025-03-28 | ❌ |
| 4 | 2025-03-31 ~ 2026-04-10 | ❌ (终止 2026-04-10, 早于 4-29) |

→ **WF Sharpe=0.8659 PASS 不验证 4-29 真期间 sim-to-real gap**.

### 7.3 audit F-D78-85 真证据加深

audit F-D78-85 (sim-to-real gap, sediment in [docs/research-kb/](../../../../docs/research-kb/) Phase 2.1 Layer2 NO-GO) 真**Phase 2.1 E2E Fusion 282% sim-to-real gap, 历史已闭环结论**. 本 finding 真**新增证据**: WF Sharpe PASS 不能等同 sim-to-real PASS — 真生产真期间 (4-29) 不在 fold 内, sim-to-real gap 不被 WF 验证.

### 7.4 真生产含义 (PT 重启决议)

**PT 重启决议必须含独立 sim-to-real gap verify, 不能仅 WF PASS**.

候选 verify 方法:
- (a) paper-mode 5d dry-run (用 4-30~5-08 真行情验证策略真期间表现)
- (b) WF refresh: 5 fold test 期延伸到 4-29 后 (rerun WF with cutoff=2026-05-08+)
- (c) 真生产事件 case-study: 卓然 -29% / 南玻 -10% 真期间策略 hypothetical 表现 (反事实回测)

**留 PT 重启 prerequisite 决议**.

---

## §8 cite source (CC 5-02 真测 file:line)

| 来源 | 真 file:line | 真定义 |
|---|---|---|
| WFConfig | [wf_phase24_validation.py:275](../../../../scripts/research/wf_phase24_validation.py#L275) | n_splits=5, train_window=750, gap=5, test_window=250 |
| LOOSE STABLE | [wf_phase24_validation.py:385](../../../../scripts/research/wf_phase24_validation.py#L385) | std<1.0 AND neg≤1 |
| STRICT STABLE | [wf_equal_weight_oos.py:395-402](../../../../scripts/wf_equal_weight_oos.py#L395-L402) | std<0.15+neg=0 / std<0.4+neg=0 / neg>0 / 其他 (4-tier) |
| Overfit Ratio (wf_phase24) | [wf_phase24_validation.py:348](../../../../scripts/research/wf_phase24_validation.py#L348) | combined_oos / full_sample, >0.50 needed |
| Overfit Ratio (wf_equal_weight) | [wf_equal_weight_oos.py:386-388](../../../../scripts/wf_equal_weight_oos.py#L386-L388) | chain_sharpe / in_sample_sharpe (12yr), >0.7 好/<0.5 严重 |
| full_sample 6yr | [wf_phase24_validation.py:327](../../../../scripts/research/wf_phase24_validation.py#L327) | `price_df[price_df["trade_date"] >= date(2020, 1, 1)]` |
| OOS Sharpe 真定义 | [wf_phase24_validation.py:351](../../../../scripts/research/wf_phase24_validation.py#L351) | `oos_sharpe = result.combined_oos_sharpe` |
| 真值 cache | [cache/phase24/wf_validation_results.json](../../../../cache/phase24/wf_validation_results.json) | timestamp 2026-04-12 16:30:04, config_id=1 CORE3+dv_ttm |
| 4-29 PT 真生产事件 | sustained sprint state + [F_D78_240_correction.md](F_D78_240_correction.md) | 卓然 -29% / 南玻 -10%, fold test 期不含 |
| audit F-D78-85 historical | [docs/research-kb/](../../../../docs/research-kb/) Phase 2.1 Layer2 NO-GO sediment | 282% sim-to-real gap |

---

## §9 验收 checklist

- [x] §1 5 折真定义 (n_splits / train_window / gap / test_window / 滚动 / train 起点 2018) ✅
- [x] §2 OOS Sharpe 真定义 (combined_oos_sharpe NOT fold mean) + 5 fold chronological 真值 ✅
- [x] §3 STABLE 跨脚本两套对照 (LOOSE wf_phase24:385 vs STRICT wf_equal_weight:395-402) ✅
- [x] §4 Overfit Ratio 真定义 + 阈值跨脚本两套 + full_sample 真 6yr ✅
- [x] §5 4 项治理债 finding (F-WF-1/2/3/4) ✅
- [x] §6 4-12 cite vs 真值 verdict (4 项一致, rounding 0.7%) ✅
- [x] §7 真重要 finding (sim-to-real gap 不被 WF 验证, audit F-D78-85 真证据加深) ✅
- [x] §8 cite source (CC 5-02 真测 file:line) ✅
- [x] **0 prod 改 / 0 SQL 写 / 0 schtask / 0 .env 改 / 0 hook bypass** sustained ✅

---

**文档结束**.
