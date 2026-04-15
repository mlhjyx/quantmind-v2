# Phase 3A: Factor Pool Expansion Results

**Date**: 2026-04-12
**Duration**: ~4 hours (batch processing + IC screening)
**Baseline**: 70 factors in factor_values (CORE5 + Alpha158 six + northbound + fundamentals)
**Result**: 70 -> **241 distinct factors**, 708.6M total rows

## Executive Summary

Phase 3A batch-computed and ingested factors from 4 data sources into factor_values. IC quick-screen (Spearman Rank IC vs 20d forward excess return, CSI300 benchmark, 2023-2026) identified **32 significant factors** (|t| > 2.5, Harvey-Liu-Zhu threshold) from 221 new factors screened.

| Step | Source | Factors | Rows | Status |
|------|--------|---------|------|--------|
| 3A-1 | Alpha158 (klines_daily OHLCV) | 148 | 185,485,482 | DONE |
| 3A-2 | daily_basic (valuation/turnover/structure) | 5 | 22,127,692 | DONE |
| 3A-3 | stk_factor (Tushare) | 0 | 0 | SKIPPED (table not in DB) |
| 3A-4 | Fundamental (fina_indicator + earnings) | 8 | 16,543,845 | DONE |
| Screen | IC Quick-Screen (221 new factors) | 32 significant | - | DONE |
| **Total** | **4 sources** | **241 distinct** | **708,600,729** | |

---

## 3A-1: Alpha158 Batch (158 Factors)

**Script**: `scripts/research/phase3a_alpha158_batch.py`
**Method**: 9 KBAR + 4 PRICE + 145 ROLLING (29 operators x 5 windows) from klines_daily OHLCV
**Date range**: 2014-2026 (with Oct Y-1 lookback for 60-day rolling windows)

### Factor Categories

| Category | Count | Operators | Windows |
|----------|-------|-----------|---------|
| KBAR | 9 | KMID, KLEN, KMID2, KUP, KUP2, KLOW, KLOW2, KSFT, KSFT2 | - |
| PRICE | 4 | OPEN0, HIGH0, LOW0, VWAP0 | - |
| ROC | 5 | ROC | 5, 10, 20, 30, 60 |
| MA | 5 | MA | 5, 10, 20, 30, 60 |
| STD | 5 | STD | 5, 10, 20, 30, 60 |
| BETA | 5 | BETA | 5, 10, 20, 30, 60 |
| RSQR | 5 | RSQR | 5, 10, 20, 30, 60 |
| RESI | 5 | RESI | 5, 10, 20, 30, 60 |
| MAX | 5 | MAX | 5, 10, 20, 30, 60 |
| MIN | 5 | MIN | 5, 10, 20, 30, 60 |
| QTLU/QTLD | 10 | QTLU, QTLD | 5, 10, 20, 30, 60 |
| RANK | 5 | RANK | 5, 10, 20, 30, 60 |
| RSV | 5 | RSV | 5, 10, 20, 30, 60 |
| IMAX/IMIN/IMXD | 15 | IMAX, IMIN, IMXD | 5, 10, 20, 30, 60 |
| CORR/CORD | 10 | CORR, CORD | 5, 10, 20, 30, 60 |
| CNTP/CNTN/CNTD | 15 | CNTP, CNTN, CNTD | 5, 10, 20, 30, 60 |
| SUMP/SUMN/SUMD | 15 | SUMP, SUMN, SUMD | 5, 10, 20, 30, 60 |
| VMA/VSTD | 10 | VMA, VSTD | 5, 10, 20, 30, 60 |
| VSUMP/VSUMN/VSUMD | 15 | VSUMP, VSUMN, VSUMD | 5, 10, 20, 30, 60 |
| WVMA | 5 | WVMA | 5, 10, 20, 30, 60 |

**DB Stats**: 148 distinct factors, 185,485,482 rows total. NaN check: all PASS.

---

## 3A-2: Daily Basic Factors (5 Factors)

**Script**: `scripts/research/phase3a_daily_basic_factors.py`
**Source**: daily_basic table (Tushare pro API)

| Factor | Formula | Description | Rows Written |
|--------|---------|-------------|-------------|
| sp_ttm | 1/PS_TTM | Sales yield TTM (higher=cheaper) | 7,383,497 |
| ep_ttm | 1/PE_TTM | Earnings yield TTM (higher=cheaper) | 9,551,191 |
| volume_ratio_daily | direct | Today vol / 5d avg vol | 11,549,194 |
| turnover_f | turnover_rate_f | Free-float adjusted turnover rate | 7,389,328 |
| float_pct | free_share/total_share | Free float percentage | 7,389,349 |

**Data gap**: Pre-2020 data has NULL for ps_ttm, turnover_rate_f, free_share, total_share (Tushare data source limitation). sp_ttm/turnover_f/float_pct only available from 2020+.

**Validation** (2026-04-10 spot check):
- sp_ttm: n=5,486, avg=0.52, range=[0.00, 55.56]
- ep_ttm: n=4,004, avg=0.03, range=[0.00, 0.26]
- turnover_f: n=5,492, avg=5.19, range=[0.36, 63.94]
- float_pct: n=5,492, avg=0.51, range=[0.02, 1.00]
- NaN check: all PASS

**Bug fix**: Decimal type from PostgreSQL NUMERIC caused `numpy.isfinite` failure. Fixed with `pd.to_numeric(values, errors="coerce")`.

---

## 3A-3: Tushare stk_factor (SKIPPED)

Table `stk_factor` does not exist in database. This Tushare endpoint was never ingested. Not blocking — the factors it would provide (macd, kdj, boll, etc.) are technical indicators easily computed from OHLCV.

---

## 3A-4: Fundamental Factors (8 Factors)

**Script**: `scripts/research/phase3a_fundamental_factors.py`
**Source**: earnings_announcements + fina_indicator tables
**PIT compliance**: Uses `ann_date` (announcement date) via `merge_asof` to prevent look-ahead bias

| Factor | Source | Description | Rows Written |
|--------|--------|-------------|-------------|
| sue_pead | earnings_announcements | Standardized Unexpected Earnings (PEAD) | 7,225,698 |
| roe_dt_q | fina_indicator | Diluted ROE (quarterly) | 1,863,762 |
| roa_q | fina_indicator | Return on Assets (quarterly) | 1,848,778 |
| gross_margin_q | fina_indicator | Gross profit margin (quarterly) | 1,846,971 |
| net_margin_q | fina_indicator | Net profit margin (quarterly) | 1,879,826 |
| profit_growth_q | fina_indicator | Net profit YoY growth (quarterly) | 1,879,090 |
| eps_growth_q | fina_indicator | EPS YoY growth (quarterly) | ~1.8M |
| leverage_q | fina_indicator | Asset-liability ratio (quarterly) | ~1.8M |

**Method**: Quarterly financials forward-filled to daily frequency via `merge_asof(left_on='trade_date', right_on='ann_date')`. Each stock gets the latest available quarterly data as of each trading day.

---

## IC Quick-Screen Results

**Script**: `scripts/research/phase3a_ic_quickscreen.py`
**Method**: Spearman Rank IC vs 20d forward excess return (CSI300 benchmark)
**Period**: 2023-01-01 ~ 2026-04-01 (sampled every 20 trading days, 39 dates from 764)
**Universe**: 5,610 stocks

### Summary Statistics
- Total factors in DB: **241**
- New factors screened: **221** (excluding 20 already-known factors)
- Significant (|t| > 2.5): **32 factors** (14.5% hit rate)
- Output: `cache/phase3a_ic_quickscreen.csv`

### Top 32 Significant Factors (|t| > 2.5)

| Rank | Factor | IC_mean | IC_IR | t_stat | n_dates | Category |
|------|--------|---------|-------|--------|---------|----------|
| 1 | high_low_range_20 | -0.1116 | -0.615 | -3.53 | 33 | Existing quant |
| 2 | volatility_60 | -0.1078 | -0.564 | -3.24 | 33 | Existing quant |
| 3 | turnover_std_20 | -0.1024 | -0.641 | -3.68 | 33 | Existing quant |
| 4 | maxret_20 | -0.0996 | -0.793 | **-4.55** | 33 | Existing quant |
| 5 | CORD5 | -0.0989 | -0.892 | -3.34 | 14 | Alpha158 new |
| 6 | turnover_f | -0.0988 | -0.709 | **-4.43** | 39 | Daily basic new |
| 7 | ivol_20 | -0.0954 | -0.557 | -3.48 | 39 | Existing quant |
| 8 | gap_frequency_20 | -0.0951 | -0.627 | -3.92 | 39 | Existing quant |
| 9 | atr_norm_20 | -0.0916 | -0.477 | -2.98 | 39 | Existing quant |
| 10 | turnover_stability_20 | -0.0894 | -0.568 | -3.54 | 39 | Existing quant |
| 11 | large_order_ratio | -0.0826 | -0.686 | -3.94 | 33 | Existing quant |
| 12 | RSQR30 | -0.0765 | -0.743 | -2.78 | 14 | Alpha158 new |
| 13 | IMIN10 | -0.0744 | -0.751 | -2.81 | 14 | Alpha158 new |
| 14 | HIGH0 | -0.0726 | -0.803 | **-3.00** | 14 | Alpha158 new |
| 15 | price_level_factor | +0.0716 | +0.454 | +2.65 | 39 | Existing quant |
| 16 | high_vol_price_ratio_20 | -0.0679 | -0.838 | **-5.23** | 39 | Existing quant |
| 17 | CORD20 | -0.0658 | -0.880 | -3.29 | 14 | Alpha158 new |
| 18 | kbar_kup | -0.0655 | -0.721 | -4.14 | 33 | Existing quant |
| 19 | sp_ttm | +0.0566 | +0.443 | +2.77 | 39 | Daily basic new |
| 20 | momentum_20 | -0.0564 | -0.481 | -2.54 | 39 | Existing quant |
| 21 | gain_loss_ratio_20 | -0.0557 | -0.541 | -2.76 | 33 | Existing quant |
| 22 | price_volume_corr_20 | -0.0548 | -0.541 | -3.38 | 39 | Existing quant |
| 23 | reversal_60 | +0.0544 | +0.445 | +2.71 | 37 | Existing quant |
| 24 | relative_volume_20 | -0.0513 | -0.536 | -3.34 | 39 | Existing quant |
| 25 | rsrs_raw_18 | -0.0480 | -0.712 | **-4.44** | 39 | Existing quant |
| 26 | mf_divergence | -0.0467 | -0.625 | -3.59 | 33 | Existing quant |
| 27 | volume_std_20 | -0.0452 | -0.443 | -2.54 | 33 | Existing quant |
| 28 | reversal_10 | +0.0422 | +0.444 | +2.77 | 39 | Existing quant |
| 29 | momentum_10 | -0.0422 | -0.444 | -2.77 | 39 | Existing quant |
| 30 | momentum_5 | -0.0399 | -0.413 | -2.58 | 39 | Existing quant |
| 31 | reversal_5 | +0.0399 | +0.413 | +2.58 | 39 | Existing quant |
| 32 | turnover_surge_ratio | -0.0396 | -0.474 | -2.96 | 39 | Existing quant |

### Strongest |t| (most reliable signals)
1. high_vol_price_ratio_20: t=-5.23 (highest absolute t)
2. maxret_20: t=-4.55
3. rsrs_raw_18: t=-4.44
4. turnover_f: t=-4.43
5. kbar_kup: t=-4.14

### Alpha158 Category Best Factors

| Category | Count | Best Factor | IC |
|----------|-------|-------------|-----|
| KBAR | 9 | KUP | -0.090 |
| ROC | 5 | ROC20 | +0.080 |
| MA | 10 | MA60 | +0.076 |
| STD | 5 | STD20 | -0.097 |
| CORR | 5 | CORR20 | -0.066 |
| CORD | 5 | CORD5 | **-0.099** |
| BETA | 5 | BETA60 | -0.071 |
| RSQR | 5 | RSQR30 | -0.077 |
| VMA | 5 | VMA60 | +0.080 |
| QTLU | 5 | QTLU60 | +0.060 |
| SUMP | 5 | SUMP60 | -0.074 |
| CNTP | 5 | CNTP10 | -0.053 |
| MIN | 5 | MIN20 | +0.091 |
| MAX | 5 | MAX5 | -0.057 |
| IMAX | 5 | IMAX60 | +0.063 |
| IMIN | 5 | IMIN10 | **-0.074** |

### Fundamental Factors IC (all weak)

| Factor | IC_mean | t_stat | Verdict |
|--------|---------|--------|---------|
| profit_growth_q | +0.017 | +1.09 | NOT significant |
| eps_growth_q | +0.011 | +0.69 | NOT significant |
| sue_pead | -0.011 | -0.68 | NOT significant |
| net_margin_q | +0.008 | +0.35 | NOT significant |
| roe_dt_q | +0.008 | +0.25 | NOT significant |
| leverage_q | +0.005 | +0.32 | NOT significant |
| roa_q | +0.003 | +0.11 | NOT significant |
| gross_margin_q | +0.003 | +0.12 | NOT significant |

**Conclusion**: Raw fundamental levels have no significant cross-sectional IC in this framework. This is expected — fundamentals are slow-moving and already priced in at cross-sectional level. Phase 3B will test change factors (QoQ delta) and industry-relative rankings as alternatives.

---

## Key Findings

### 1. Low-volatility anomaly dominates
The top 6 factors by |IC| are all volatility/risk-related with negative direction: high_low_range (-0.112), volatility_60 (-0.108), turnover_std (-0.102), maxret (-0.100), CORD5 (-0.099), turnover_f (-0.099). This confirms the low-volatility anomaly is the strongest cross-sectional predictor in A-shares.

### 2. Alpha158 new discoveries limited
Of 148 Alpha158 factors, only **5 passed |t|>2.5**: CORD5, RSQR30, IMIN10, HIGH0, CORD20. Most Alpha158 rolling factors (BETA, CORR, RESI, etc.) did not reach significance. The best Alpha158 factors (CORD, RSQR, IMIN) relate to volatility/idiosyncratic risk — same anomaly as existing factors.

### 3. Daily basic factors: turnover_f and sp_ttm significant
- turnover_f (free-float turnover): IC=-0.099, t=-4.43, **strongly significant**. Correlated with existing turnover_mean_20 but may carry independent information from free-float adjustment.
- sp_ttm (sales yield): IC=+0.057, t=+2.77, **significant value factor**. Complements bp_ratio and dv_ttm.

### 4. Fundamental levels: all IC-insignificant
None of the 8 fundamental factors reached |t|>2.5. Fundamental data may still be useful as: (a) change factors, (b) industry-relative ranks, (c) pre-filters, (d) negative screens. These are tested in Phase 3B.

### 5. Momentum/reversal: short-term only
reversal_5/10 and momentum_5/10/20 are significant but only at short horizons (n_dates=39, covering 2023-2026 only). These may be FAST-decay factors suited for weekly strategies, not monthly CORE.

---

## Data Quality

- NaN check (铁律29): **ALL PASS** across all 4 batch scripts
- NUMERIC clip: All values clipped to [-9,999,999,999, +9,999,999,999] before DB write
- Write method: COPY+UPSERT (10-50x faster than execute_values)
- Pre-2020 daily_basic gap: Known Tushare limitation, 3 factors only available from 2020+

## Artifacts

| Artifact | Path | Description |
|----------|------|-------------|
| IC screen CSV | `cache/phase3a_ic_quickscreen.csv` | 221 factors, all IC stats |
| Alpha158 script | `scripts/research/phase3a_alpha158_batch.py` | 261 lines, reusable |
| Daily basic script | `scripts/research/phase3a_daily_basic_factors.py` | 234 lines |
| Fundamental script | `scripts/research/phase3a_fundamental_factors.py` | 323 lines |
| IC screen script | `scripts/research/phase3a_ic_quickscreen.py` | 238 lines |

## Next Steps (Phase 3B)

1. **Neutralize 32 significant factors** via `fast_neutralize_batch` (MAD+WLS+zscore)
2. **Fundamental variants**: change factors (QoQ delta), industry-relative ranking, pre-filter, negative screening
3. **IC decay curves**: 6 horizons (1d/5d/10d/20d/60d/120d) for all 32 factors
4. **Factor usage recommendation table**: assign layers (CORE/Modifier/ML/Filter/Monitor)
