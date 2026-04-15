# Phase 3E: ML Model Diversity + Microstructure Factors

**Date**: 2026-04-14
**Status**: COMPLETED
**Decision**: ML Track B CLOSED (6th independent validation), Track A microstructure factors promising (17/20 PASS raw IC)

## Background

User explicitly requested exploration beyond LightGBM after 5 failures: "ML models are diverse, need to find the right one." Phase 3E ran two parallel tracks:
- **Track A**: 20 microstructure factors from 5-min bars (191M rows, 8 years)
- **Track B**: 6 ML model architectures through WF validation

## Track B Results: ML Model Comparison

All models run through identical 5-fold Walk-Forward with:
- WFConfig: 750d train, 250d test, gap=5
- BacktestConfig: commission=0.854bps, historical stamp tax, volume_impact slippage
- Portfolio: Top-20, monthly, equal-weight, SN b=0.50

| Model | OOS Sharpe | OOS MDD | Neg Folds | Time |
|-------|-----------|---------|-----------|------|
| **Equal-weight baseline** | **0.8659** | **-13.9%** | **0/5** | — |
| Stacking (3 GBDT avg) | 0.6012 | -26.3% | 0/5 | 45s |
| LightGBM | 0.5501 | -25.7% | 0/5 | 36s |
| XGBoost | 0.4888 | -26.4% | 0/5 | 34s |
| CatBoost | 0.4875 | -27.1% | 2/5 | 39s |
| MLP (3-layer, 256-128-64) | 0.3500 | -32.3% | 0/5 | 90min |
| TabNet (attention) | 0.1195 | -36.1% | 2/5 | 3.7h |

### Key Findings

1. **Model complexity inversely correlated with performance**: Tree ensembles (0.49-0.60) > MLP (0.35) > TabNet (0.12). Attention mechanisms hurt rather than help.

2. **Stacking provides marginal improvement**: Averaging 3 GBDT models (0.60) slightly better than single LightGBM (0.55), but still 31% below equal-weight.

3. **MLP underfits rapidly**: best_iter=1-2 in 3/5 folds (early stopping fires after 1 epoch), Train IC=0.10-0.20 but Valid IC=0.04-0.09. The signal is too weak for gradient descent to capture.

4. **All models share same weakness**: Fold 2 (2023-03 to 2024-03, bear market) is worst for every model. This is regime sensitivity, not model architecture issue.

5. **6th independent validation**: G1(LightGBM) → Step 6-H → Phase 2.1 → Phase 2.2 → Phase 3D → Phase 3E. Consistent conclusion: ML predict-then-optimize cannot beat simple equal-weight factor scoring with A-share data at this factor information level.

### Root Cause Analysis

The problem is NOT model architecture — it's **signal quality**:
- Valid IC = 0.04-0.10 across all models (near noise floor)
- 11 daily factors provide ~0.09 IC ceiling (confirmed in Phase 2.1)
- Converting IC to portfolio weights via Top-N ranking loses information
- Equal-weight avoids this information loss entirely

## Track A Results: Microstructure Factor IC Screen

20 factors computed from 5-min OHLCV bars, 2019-2026, ~75M rows written to factor_values.

### IC Quick-Screen (raw_value, 20d excess return, Spearman Rank)

| Factor | Category | IC | IR | t-stat | Status |
|--------|----------|-----|-----|--------|--------|
| volume_autocorr_20 | B: Volume | -0.1016 | -0.639 | -26.10 | PASS |
| high_freq_volatility_20 | A: Return | -0.0986 | -0.591 | -24.13 | PASS |
| max_intraday_drawdown_20 | A: Return | +0.0840 | 0.429 | 17.55 | PASS |
| intraday_kurtosis_20 | A: Return | -0.0777 | -0.714 | -29.16 | PASS |
| weighted_price_contribution_20 | D: Efficiency | -0.0776 | -0.619 | -25.30 | PASS |
| intraday_skewness_20 | A: Return | -0.0726 | -0.679 | -27.76 | PASS |
| smart_money_ratio_20 | B: Volume | +0.0501 | 0.432 | 17.66 | PASS |
| volume_return_corr_20 | B: Volume | -0.0499 | -0.493 | -20.16 | PASS |
| autocorr_5min_20 | D: Efficiency | -0.0474 | -0.316 | -12.89 | PASS |
| price_path_efficiency_20 | D: Efficiency | -0.0402 | -0.356 | -14.56 | PASS |
| open_drive_20 | C: Session | -0.0351 | -0.396 | -16.19 | PASS |
| variance_ratio_20 | D: Efficiency | -0.0345 | -0.254 | -10.40 | PASS |
| volume_concentration_20 | B: Volume | -0.0328 | -0.259 | -10.58 | PASS |
| morning_afternoon_ratio_20 | C: Session | -0.0250 | -0.288 | -11.76 | PASS |
| close_drive_20 | C: Session | -0.0143 | -0.254 | -10.38 | PASS |
| updown_vol_ratio_20 | A: Return | -0.0143 | -0.126 | -5.16 | PASS |
| amihud_intraday_20 | B: Volume | +0.0075 | 0.264 | 8.54 | PASS |
| lunch_break_gap_20 | C: Session | +0.0029 | 0.032 | 1.30 | FAIL |
| last_bar_volume_share_20 | C: Session | -0.0026 | -0.024 | -0.96 | FAIL |
| intraday_reversal_strength_20 | D: Efficiency | +0.0003 | 0.005 | 0.23 | FAIL |

**17/20 PASS** (|t| > 2.5), 3 FAIL.

### Top Factor Economic Logic

1. **volume_autocorr_20** (IC=-0.10): High volume persistence = herding/momentum trading -> reversal
2. **high_freq_volatility_20** (IC=-0.10): Intraday volatility = overreaction -> mean reversion
3. **max_intraday_drawdown_20** (IC=+0.08): Large drawdowns = panic selling -> recovery bounce
4. **smart_money_ratio_20** (IC=+0.05): Smart money presence -> future outperformance

### Critical Next Steps (NOT DONE YET)

1. **Neutralized IC confirmation** (铁律4): raw IC may contain size/industry exposure
2. **Correlation with CORE4**: if corr > 0.7, these are redundant not new alpha
3. **WF validation**: Top candidates through equal-weight WF to test incremental Sharpe
4. **Noise robustness** (铁律20): G_robust test at 5%/20% noise

## Files Created

- `scripts/research/minute_data_loader.py` — Minute bar Parquet cache builder
- `scripts/research/phase3e_minute_factors.py` — 20 microstructure factor computation
- `scripts/research/phase3e_ml_models.py` — Multi-model ML comparison framework
- `scripts/research/phase3e_ic_screen.py` — IC quick-screen for microstructure factors
- `cache/phase3e/factors_*.parquet` — Per-year factor results (8 files)
- `cache/phase3e/ic_screen_results.csv` — IC screen summary
- `cache/phase3e_ml/ml_model_comparison.json` — ML model comparison results
- `cache/minute_bars/minute_bars_*.parquet` — Minute bar cache (8 years)

## Decision

- **Track B ML**: CLOSED. 6th validation. No model architecture can overcome the IC ceiling.
- **Track A Microstructure**: PROMISING. Top 5 factors have CORE-level raw IC. Next step is neutralized IC + correlation check to determine if they represent genuinely new alpha or just size/volatility repackaging.
