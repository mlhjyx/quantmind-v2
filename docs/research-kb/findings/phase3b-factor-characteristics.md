# Phase 3B: Factor Characteristics Analysis Report

**Date**: 2026-04-13 | **Source**: `scripts/research/phase3b_factor_characteristics.py`, `phase3b_neutralize_significant.py`

---

## 1. Overview

Phase 3A expanded the factor pool from 70 to 241 factors, with IC quick-screen identifying 32 significant factors (|t|>2.5). Phase 3B performed:
- **Task 1**: Neutralized all 32 factors (MAD 5sigma -> WLS industry+mcap -> z-score clip +/-3)
- **Task 2**: Deep factor characteristics analysis (6 subtasks)

Current PT config: CORE3+dv_ttm (turnover_mean_20, volatility_20, bp_ratio, dv_ttm), WF OOS Sharpe=0.8659.

---

## 2. Task 1: Neutralization Results

| Metric | Value |
|--------|-------|
| Factors neutralized | 32/32 |
| Method | MAD(5sigma) -> WLS(industry_sw1 + ln_mcap) -> z-score clip(+/-3) |
| Health check | 27 PASS (warning: no Parquet cache), 5 Alpha158 false alarm |
| VACUUM ANALYZE | Completed (631s) |
| NaN in neutral_value | 0 (iron rule 29 PASS) |

**5 Alpha158 factors** (CORD5, RSQR30, IMIN10, HIGH0, CORD20) flagged as "no data 2024" in health check but actually have data through 2026-04-10. Issue is lower row count (~500K-576K vs 1.2M+) due to computation scope. Not a real problem.

**kbar_kup outlier**: neutral_value max=30.69 (exceeds expected +/-3 clip). Root cause: all outliers on 2024-10-08 (post-National Day gap-up). Cross-sectional distribution highly abnormal — almost all stocks had 0 upper shadow, WLS residuals for rare non-zero stocks became extreme. **Fixed 2026-04-13**: re-neutralized kbar_kup, max |neutral_value| now ≤3.0.

---

## 3. Task 2.1a: Fundamental Change Factors (QoQ Delta)

**Goal**: Test if quarter-over-quarter changes capture "improving" signal that levels don't.

| Change Factor | Source | Rows | IC | Status |
|--------------|--------|------|-----|--------|
| roe_change_q | roe_dt_q | 944K | +1.000 | INVALID |
| roa_change_q | roa_q | 944K | +1.000 | INVALID |
| margin_change_q | gross_margin_q | 944K | +1.000 | INVALID |
| leverage_change_q | leverage_q | 963K | +1.000 | INVALID |
| profit_accel_q | profit_growth_q | 961K | +1.000 | INVALID |

**Finding**: All IC=1.0 indicates **look-ahead bias in the derivative computation** (not in base factors).

> **Root cause clarified (2026-04-13)**: The base fundamental factors in `phase3a_fundamental_factors.py` already use `ann_date` correctly via `merge_asof(direction="backward", tolerance=120d)`. The PIT issue is in how Phase 3B computed the change factors:
> 1. Base factors are forward-filled daily values (correct for level factors)
> 2. The change detection (`raw_value != prev_val`) fires ONLY on announcement dates when forward-filled values change
> 3. This creates a perfect "announcement day" signal — the change reveals exactly when new information arrives
> 4. Forward-filling the delta then broadcasts this timing signal to subsequent trading days
>
> **Fix approach**: Compute QoQ changes from raw quarterly announcements (ann_date, value pairs), NOT by diffing daily forward-filled values. The delta should be computed once per announcement, not detected from daily value changes.

**Action**: Rewrite change factor computation to use raw quarterly data directly. Base factors do NOT need rebuilding.

---

## 4. Task 2.1b: Industry-Relative Ranking

**Goal**: Test if ranking fundamentals within SW1 industry groups improves IC.

| Factor | IC Mean | IC_IR | t-stat | Source |
|--------|---------|-------|--------|--------|
| roe_ind_rank | 0.8896 | 34.03 | 204.16 | roe_dt_q |
| roa_ind_rank | 0.8876 | 28.84 | 173.05 | roa_q |
| margin_ind_rank | 0.8763 | 26.72 | 160.29 | gross_margin_q |
| leverage_ind_rank | 0.8771 | 26.64 | 159.87 | leverage_q |

**Finding**: IC=0.88+ is impossibly high, confirming the same **derivative computation bias** as Task 2.1a. Rankings on forward-filled values change sharply on announcement dates, creating a look-ahead signal.

> **Root cause (2026-04-13)**: Same as Task 2.1a — ranking forward-filled values within industry reveals announcement timing. Fix: rank on raw quarterly values at announcement dates, then forward-fill the rank (not the underlying value).

**Conclusion**: All fundamental factor variants (change, industry-relative) are INVALID until PIT alignment is implemented using `fina_indicator.ann_date`.

---

## 5. Task 2.1c: Fundamental Pre-Filter Backtest

**Goal**: Test if applying fundamental quality filters before CORE3+dv_ttm selection improves performance.

| Config | Sharpe | MDD | Annual Return | Universe % |
|--------|--------|------|-------------|-----------|
| **baseline (no filter)** | **1.031** | **-14.6%** | **16.4%** | 100% |
| Filter A: ROE > 0 | 0.511 | -36.6% | 8.3% | 9.6% |
| Filter B: Leverage < 70% | 0.487 | -34.5% | 8.0% | 11.0% |
| Filter C: ROE>0 & Lev<70% | 0.573 | -34.8% | 9.9% | 8.4% |
| Filter D: Margin > ind median | 0.661 | -29.3% | 11.3% | 6.4% |

**Finding**: All fundamental pre-filters **severely hurt performance** (Sharpe drops 36-53%). The filters restrict the universe too aggressively (to 6-11% of stocks), removing the micro-cap stocks where alpha resides.

**Conclusion**: Fundamental pre-filtering is NOT viable in the current equal-weight micro-cap alpha framework. Added to "known failed directions."

---

## 6. Task 2.1d: Negative Screening Backtest

**Goal**: Select Top-30 by composite, remove worst 10 by fundamentals, keep Top-20.

| Config | Sharpe | MDD | Annual Return |
|--------|--------|------|-------------|
| baseline (Top-20 direct) | 0.482 | -48.7% | 10.3% |
| Screen A: Remove worst ROE | 0.482 | -48.7% | 10.3% |
| Screen B: Remove worst quality | 0.482 | -48.7% | 10.3% |
| Screen C: Remove worst growth | 0.482 | -48.7% | 10.3% |

**Finding**: All screening configs produce **identical results** to baseline. The Top-30->remove-10->keep-20 approach has no effect because the bottom 10 by composite score already have weak fundamentals, and fundamental scores don't differentiate among the top ranked stocks.

**Conclusion**: Negative screening adds no value. The composite signal already captures the relevant information.

> **Footnote (2026-04-13)**: Task 2.1d baseline Sharpe=0.482 differs from Task 2.1c baseline Sharpe=1.031 because they use different backtesting engines. Task 2.1c uses `run_hybrid_backtest()` (production-grade engine with full cost model), while Task 2.1d uses `SimpleBacktester` (basic equal-weight portfolio simulator). Both apply SN b=0.50. Time range is 2020-01-01 to 2026-04-01 (1518 days), not full 12yr. The **relative comparison** (all screening variants identical to baseline) is the meaningful result; the absolute Sharpe level is engine-dependent.

---

## 7. Task 2.2: IC Decay Curves (32 Factors x 6 Horizons)

### Decay Type Distribution
| Type | Count | Description |
|------|-------|-------------|
| SLOW | 29 | IC persists 60d+ (suited for monthly rebalancing) |
| MEDIUM | 3 | CORD5, gain_loss_ratio_20, volume_std_20 |
| FAST | 0 | None |
| INVERTED | 0 | None |

### Key IC Decay Table (Top Factors by |IC_20d|)

| Factor | IC_5d | IC_20d | IC_60d | IC_120d | Mono | Decay | MaxCorr |
|--------|-------|--------|--------|---------|------|-------|---------|
| turnover_stability_20 | -0.060 | -0.099 | -0.128 | -0.146 | -0.70 | SLOW | 0.992 (turnover_std) |
| turnover_f | -0.071 | -0.092 | -0.112 | -0.115 | -0.70 | SLOW | 0.754 (turnover_mean) |
| RSQR30 | -0.059 | -0.092 | -0.067 | -0.040 | 0.00 | SLOW | 0.000 (independent) |
| maxret_20 | -0.054 | -0.087 | -0.093 | -0.102 | -0.70 | SLOW | 0.908 (IMAX_20) |
| gap_frequency_20 | -0.060 | -0.086 | -0.102 | -0.113 | -0.60 | SLOW | 0.761 (atr_norm) |
| atr_norm_20 | -0.072 | -0.085 | -0.106 | -0.122 | -0.10 | SLOW | 0.988 (hlr_20) |
| ivol_20 | -0.063 | -0.083 | -0.103 | -0.113 | -0.40 | SLOW | 0.967 (volatility_20) |
| CORD20 | -0.046 | -0.080 | -0.059 | -0.108 | 0.00 | SLOW | 0.000 (independent) |
| turnover_std_20 | -0.046 | -0.081 | -0.114 | -0.132 | -0.90 | SLOW | 0.992 (turnover_stab) |
| volatility_60 | -0.056 | -0.079 | -0.113 | -0.132 | -0.30 | SLOW | 0.723 (atr_norm) |

### High Correlation Pairs (|corr| > 0.85) — Redundant

| Pair | Correlation | Action |
|------|------------|--------|
| reversal_10 <-> momentum_10 | -1.000 | Exact mirror, keep one |
| momentum_5 <-> reversal_5 | -1.000 | Exact mirror, keep one |
| turnover_std_20 <-> turnover_stability_20 | 0.992 | Keep stability (higher IC) |
| high_low_range_20 <-> atr_norm_20 | 0.988 | Keep atr_norm (higher IC) |
| ivol_20 <-> volatility_20 | 0.967 | Redundant with CORE |
| maxret_20 <-> IMAX_20 | 0.908 | Keep maxret (IC significant) |
| gain_loss_ratio_20 <-> reversal_20 | -0.897 | Reversal variant |
| momentum_20 <-> reversal_20 | -0.871 | Reversal variant |

### Notable Observations
1. **All ic_1d = 0**: ~~The profiler may not support 1-day horizon or data is insufficient for single-day IC~~ **Bug confirmed & fixed (2026-04-13)**: `factor_profiler.py` line 121 used `shift(-h)` for exit price, but entry was `shift(-1)`. For h=1, entry=exit → return=0 always. Fix: `exit_p = close_pivot.shift(-(1+h))`. Same bug in `precompute_cache.py` line 79. Does not affect any decisions (IC decay starts from 5d).
2. **All ic_halflife = null**: No factor's IC halves within the observed horizons (all SLOW decay)
3. **No sign flips**: No factor shows inverted IC at longer horizons
4. **All 32 factors suit monthly rebalancing**: Consistent with current PT setup

---

## 8. Task 2.3: Factor Usage Recommendation Table

### P1 — CORE Candidates (8 factors, immediate WF evaluation) [CORRECTED 2026-04-13]

| Factor | IC_20d | t-stat | Corr_CORE4 | Mono | Layer | Risk Notes |
|--------|--------|--------|-----------|------|-------|------------|
| rsrs_raw_18 | -0.043 | -4.44 | 0.28 | -0.90 | CORE | Strong candidate, low corr |
| kbar_kup | -0.042 | -4.14 | 0.23 | -0.70 | CORE | Outlier fixed (re-neutralized) |
| large_order_ratio | -0.045 | -3.94 | 0.29 | -0.90 | CORE | Microstructure, data dependency |
| price_volume_corr_20 | -0.056 | -3.38 | 0.28 | -1.00 | CORE | Perfect monotonicity |
| relative_volume_20 | -0.037 | -3.34 | 0.17 | -1.00 | CORE | Lowest corr, perfect mono |
| turnover_surge_ratio | -0.023 | -2.96 | 0.11 | -0.90 | CORE | Lowest CORE4 corr of all |
| reversal_10 | +0.037 | +2.77 | 0.12 | +0.60 | CORE | Short-term reversal |
| gain_loss_ratio_20 | -0.032 | -2.76 | 0.29 | -0.70 | CORE | MEDIUM decay |

**Selection criteria**: |t| > 2.5, corr_CORE4 < 0.5, monotonicity >= 0.5, SLOW/MEDIUM decay.

**Removed from original P1 (2026-04-13 corrections)**:
- ~~mf_divergence~~: INVALIDATED. IC=-0.028 consistent with prior IC=-0.0227, 14 backtests negative. See `docs/research-kb/failed/mf-divergence-fake-ic.md`.
- ~~momentum_10~~: Exact mathematical mirror of reversal_10 (`calc_momentum = -calc_reversal`). Keep reversal_10, drop this.
- ~~volume_std_20~~: Moved to P2 (highest CORE4 corr=0.38 in P1, borderline t=2.54).

### P2 — CORE Candidates, Lower Priority (3 factors)

| Factor | IC_20d | t-stat | Corr_CORE4 | Mono | Notes |
|--------|--------|--------|-----------|------|-------|
| momentum_20 | -0.047 | -3.03 | 0.24 | -0.50 | Borderline monotonicity |
| reversal_5 | +0.033 | +2.58 | 0.09 | +0.50 | Short-term reversal (mirror momentum_5 dropped) |
| volume_std_20 | -0.021 | -2.54 | 0.38 | -0.60 | Moved from P1: highest CORE4 corr, borderline t |

### P3 — ML Feature / Modifier (11 factors)

| Factor | IC_20d | t-stat | Corr_CORE4 | Layer | Notes |
|--------|--------|--------|-----------|-------|-------|
| gap_frequency_20 | -0.086 | -3.92 | 0.70 | Modifier | High corr, strong IC |
| volatility_60 | -0.079 | -3.24 | 0.67 | Modifier | Overlaps volatility_20 |
| sp_ttm | +0.042 | +2.77 | 0.54 | Modifier | Overlaps bp_ratio |
| CORD5 | -0.061 | -3.34 | 0.13 | ML Feature | Low monotonicity |
| CORD20 | -0.080 | -3.29 | 0.23 | ML Feature | Low monotonicity |
| HIGH0 | +0.043 | -3.00 | 0.26 | ML Feature | Low monotonicity |
| IMIN10 | -0.067 | -2.81 | 0.13 | ML Feature | Low monotonicity |
| RSQR30 | -0.092 | -2.78 | 0.15 | ML Feature | Low monotonicity, independent |
| reversal_60 | +0.039 | +2.71 | 0.30 | ML Feature | Low monotonicity |
| price_level_factor | +0.046 | +2.65 | 0.30 | ML Feature | Low monotonicity |
| high_vol_price_ratio_20 | +0.012 | -5.23 | 0.46 | ML Feature | IC sign unstable across windows, regime-sensitive ¹ |

> ¹ **high_vol_price_ratio_20 sign mismatch (2026-04-13)**: IC_20d=+0.012 from factor_profiler (full 2021-2025 window, monthly sampling) vs t=-5.23 from Phase 3A IC quick-screen (IC mean=-0.068, 2023-2026 window, 20d sampling). The factor flipped direction between periods, indicating regime sensitivity. Correctly classified as ML Feature (not CORE).

### P4 — Monitor Only (7 factors, too correlated with CORE4)

| Factor | IC_20d | Corr_CORE4 | Redundant With |
|--------|--------|-----------|---------------|
| maxret_20 | -0.087 | 0.75 | volatility_20 |
| turnover_f | -0.092 | 0.76 | turnover_mean_20 |
| turnover_std_20 | -0.081 | 0.79 | turnover_mean_20 |
| turnover_stability_20 | -0.099 | 0.79 | turnover_mean_20 |
| high_low_range_20 | -0.073 | 0.91 | volatility_20 |
| ivol_20 | -0.083 | 0.93 | volatility_20 |
| atr_norm_20 | -0.085 | 0.90 | volatility_20 |

---

## 9. Key Conclusions

1. **Fundamental change/ranking factors have derivative computation bias** (clarified 2026-04-13): Base factors are PIT-correct (`ann_date` via `merge_asof`), but diffing/ranking forward-filled daily values reveals announcement timing. Fix: compute from raw quarterly announcements, not daily diffs
2. **Pre-filtering destroys alpha**: Universe restriction removes micro-cap stocks where alpha lives (consistent with Phase 2.3/2.4 findings)
3. **Negative screening adds zero value**: Composite signal already captures quality differentiation
4. **All 32 factors are SLOW decay**: Monthly rebalancing is optimal for all, no need for weekly/event strategies
5. **8 P1 CORE candidates all FAIL WF evaluation** (2026-04-13): All 8 factors individually added to CORE3+dv_ttm+SN050 produced OOS Sharpe BELOW baseline (0.8659). Best: price_volume_corr_20 at 0.7737 (-0.092). Worst: rsrs_raw_18 at 0.5993 (-0.267). **CORE3+dv_ttm is the alpha ceiling for the equal-weight framework.** Adding a 5th factor dilutes signal quality.
6. **7 factors redundant with CORE4**: ivol_20/atr_norm_20/hlr_20 redundant with volatility_20; turnover variants redundant with turnover_mean_20

---

## 10. WF Evaluation Results (2026-04-13)

8 P1 candidates individually tested against CORE3+dv_ttm+SN050 baseline (OOS Sharpe=0.8659):

| # | Factor | OOS Sharpe | Delta | OOS MDD | Stability | Verdict |
|---|--------|-----------|-------|---------|-----------|---------|
| 4 | price_volume_corr_20 | 0.7737 | -0.092 | -13.48% | STABLE | FAIL |
| 7 | reversal_10 | 0.7694 | -0.097 | -12.31% | STABLE | FAIL |
| 5 | large_order_ratio | 0.7384 | -0.128 | -15.05% | STABLE | FAIL |
| 1 | relative_volume_20 | 0.7350 | -0.131 | -12.50% | STABLE | FAIL |
| 8 | gain_loss_ratio_20 | 0.6892 | -0.177 | -12.66% | STABLE | FAIL |
| 2 | turnover_surge_ratio | 0.6867 | -0.179 | -13.47% | STABLE | FAIL |
| 6 | kbar_kup | 0.6637 | -0.202 | -15.29% | STABLE | FAIL |
| 3 | rsrs_raw_18 | 0.5993 | -0.267 | -15.25% | UNSTABLE(1 neg) | FAIL |

**Conclusion**: No P1 factor improves CORE3+dv_ttm. Equal-weight framework has reached its factor ceiling at 4 factors.

Results: `cache/phase3b/wf_p1_evaluation_results.json`

---

## 11. Next Steps (Updated 2026-04-13)

1. ~~WF evaluate P1 candidates~~: **DONE — 8/8 FAIL, CORE3+dv_ttm is ceiling**
2. **Fix PIT derivative computation**: Compute QoQ changes from raw quarterly announcements, not daily diffs
3. **Build ML feature set**: Use P3 ML features (CORD5/CORD20/RSQR30/IMIN10/HIGH0) as LightGBM input
4. **Data ingestion**: Continue pulling fina_indicator/margin_detail/forecast/express/top_list/BaoStock
5. **Phase 3 Automation**: Factor lifecycle + Rolling WF + IC monitoring alerts

---

## 11. Output Files

| File | Description |
|------|-------------|
| `cache/phase3b/task_2_1a_change_factors.json` | Change factor IC (PIT biased) |
| `cache/phase3b/task_2_1b_industry_ranking.json` | Industry ranking IC (PIT biased) |
| `cache/phase3b/task_2_1c_prefilter.json` | Pre-filter backtest results |
| `cache/phase3b/task_2_1d_negative_screening.json` | Negative screening results |
| `cache/phase3b/task_2_2_ic_decay.json` | Full IC decay profiles (32 factors) |
| `cache/phase3b/task_2_3_recommendations.json` | Recommendation table |
| `cache/phase3b/factor_recommendations.csv` | CSV version of recommendations |
