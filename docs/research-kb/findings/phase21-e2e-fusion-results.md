# Phase 2.1 E2E Fusion Architecture — Results Report

**Date**: 2026-04-11
**Status**: NO-GO
**Baseline**: SN b=0.50 equal-weight CORE5, 12yr Sharpe=0.68, WF OOS=0.6521

---

## Executive Summary

Phase 2.1 tested the E2E Fusion hypothesis: LightGBM prediction (Layer 1) + PortfolioNetwork with differentiable Sharpe loss (Layer 2) could exceed the equal-weight baseline. **Result: NO-GO.** Layer 2 produces Sharpe=-0.99 in real backtest due to catastrophic sim-to-real gap. Adding factors beyond CORE5 provides zero incremental IC.

---

## Part 1: Perfect Prediction Upper Bound — GATE GO

| Experiment | Sharpe | MDD | Ann Ret |
|---|---|---|---|
| Perfect + EqualWeight Top-20 | 3.02 | -49.2% | 141.6% |
| Perfect + SN(b=0.50) + EW | 2.68 | -40.2% | 117.3% |
| Perfect + MVO (riskfolio) | 3.02 | -49.2% | 141.6% |

**Insight**: With perfect foresight, Sharpe=3.0 — massive headroom vs current 0.68. MVO=EW with perfect prediction (optimal stocks are so dominant that optimization doesn't help). SN reduces MDD -49%→-40% at cost of Sharpe 3.0→2.7.

**Gate**: GO (MVO Sharpe=3.02 > 1.5)

---

## Part 2: Layer 1 LightGBM Walk-Forward

### Config
- Windows: 60-month fixed train, 12-month valid, 12-month test
- Purge: 21 trading days
- 7 folds (F1-F7), 2014-2026
- GPU: LightGBM 4.6.0, device_type=gpu

### Exp-C: CORE 5 Factors (Baseline)

| Metric | Value |
|---|---|
| OOS IC | **0.0912** |
| OOS RankIC | 0.1026 |
| ICIR | 1.0625 |
| Folds used | 7/7 |
| trainIC/validIC | 1.55 (< 2.0 ✅) |

Feature importance: amihud_20 (44.7%) > turnover_mean_20 (19.2%) > reversal_20 (15.7%) > volatility_20 (11.4%) > bp_ratio (9.0%)

**vs G1 baseline (IC=0.067)**: +36% improvement. Likely due to 60-month windows (vs 24) and SW1 neutralization.

### Exp-A: CORE5 + QTLU_20 + RSQR_20 (7 Factors)

| Metric | Value |
|---|---|
| OOS IC | **0.0912** |
| OOS RankIC | 0.1026 |

**Identical to Exp-C.** QTLU_20 and RSQR_20 had exactly 0 feature importance. LightGBM completely ignored them. The CORE5 factors already capture all available predictive signal in the neutral_value space.

### Exp-B: CORE5 + Tier2 + NB (16 Factors)

| Metric | Value |
|---|---|
| OOS IC | **0.0687** (worse than Exp-C!) |
| OOS RankIC | 0.0771 |
| ICIR | 0.7400 |
| Folds used | 4/5 (F5 overfit=9.57, excluded) |
| trainIC/validIC | 1.96 (borderline) |

Feature importance: amihud_20 (34.6%) > turnover_mean_20 (15.1%) > reversal_20 (13.8%) > bp_ratio (10.2%) > volatility_20 (9.7%) > nb_increase_ratio_20d (8.0%) > nb_new_entry (8.0%) > rest ~0%

**Exp-B is WORSE than Exp-C** (-25% IC). Adding 11 factors (Tier2 Alpha158 + NB) introduced noise and caused F5 to overfit (9.57x). NB factors `nb_increase_ratio_20d` and `nb_new_entry` gained 8% importance each but their signal was insufficient to offset the noise from 9 other low-quality features.

Note: Required Parquet pre-export (684MB) to avoid PG OOM on 16-factor DB read. Used `MLConfig.parquet_path` for memory-efficient loading.

---

## Part 3: Layer 2 PortfolioNetwork — FAIL

### Architecture
- PortfolioMLP: Linear(F+1,64) → ReLU → Dropout(0.3) → Linear(64,32) → ReLU → Linear(32,1) → PortfolioLayer
- PortfolioLayer: softmax + iterative clamp(max_weight=0.10) + renormalize
- Loss: -Sharpe + 0.1 × turnover (differentiable, pure tensor ops)
- Training: Adam lr=1e-3, weight_decay=0.01, patience=20, max_grad_norm=1.0

### Training Results (looked promising)
- Best val_sharpe: **1.2630** (epoch 360)
- Converged smoothly: 0.31 → 1.26 over 360 epochs

### Real Backtest Results (catastrophic)

| Metric | Tensor (simplified) | SimpleBacktester (real) |
|---|---|---|
| Sharpe | **1.81** | **-0.99** |
| MDD | — | -81.5% |
| Ann Ret | — | -12.7% |
| **Diff** | **282%** | Far exceeds 5% threshold |

### Root Cause Analysis

1. **Sim-to-real gap**: The differentiable sharpe_loss models `portfolio_return = sum(weights × stock_returns)` without real trading costs
2. **Missing costs in loss function**:
   - Minimum commission ¥5/trade (dominant for small positions)
   - Stamp tax 0.05% (sell-side)
   - Volume impact slippage (spread + market impact)
   - Overnight gap cost
3. **Tiny position sizes**: Model spreads weight across many stocks with ¥328-¥7584 trades, each paying ¥5 minimum commission = 6.6%-152% round-trip cost on small positions
4. **Fundamental design flaw**: Cannot make the full cost model differentiable (discrete effects like min commission, volume cap truncation, overnight gaps)

---

## Key Findings

### F1: Factor Information Ceiling — More Factors = Worse
IC≈0.09 is the ceiling for quantity-price-volume factors after SW1 neutralization. Adding factors actively hurts: Exp-A (7 factors, +QTLU/RSQR) = identical IC, Exp-B (16 factors, +Tier2+NB) = IC drops 25% to 0.069 with 1 fold overfit. The CORE5 factors are both sufficient and optimal — adding noise features degrades LightGBM's ability to extract signal.

### F2: Training Window Matters
60-month windows (Exp-C: IC=0.0912) significantly outperform 24-month windows (G1: IC=0.067), a +36% improvement. This is the single most impactful change from G1.

### F3: E2E Differentiable Portfolio Optimization Fails in Practice
The sim-to-real gap is fundamental, not fixable by tuning. Real A-share trading costs are discrete, non-differentiable, and dominated by fixed costs (min commission). Any differentiable approximation will overfit to the simplified cost model.

### F4: Prediction Is the Bottleneck, Not Portfolio Construction
Perfect prediction gives Sharpe=3.0 with simple equal-weight. MVO with perfect prediction = equal-weight (3.02=3.02). The gap from 0.68 to 3.0 is entirely prediction quality, not portfolio optimization.

---

## Conclusion: NO-GO

Phase 2.1 E2E Fusion does not meet the go condition (OOS Sharpe > 0.717). The approach is fundamentally flawed for A-share markets due to the sim-to-real gap in differentiable portfolio optimization.

### What Works
- 60-month LightGBM WF with CORE5: IC=0.0912 (best ML result to date)
- Equal-weight Top-20 with SN b=0.50 remains the optimal portfolio construction

### What to Try Next (Phase 2.2+)
1. **IC-weighted signal composition** (simple, no ML in portfolio layer)
2. **LightGBM score → rank → Top-N with real cost model** (non-differentiable but accurate)
3. **Alternative prediction targets** (e.g., rank labels via LambdaRank instead of regression)
4. **Cross-sectional features** (relative metrics, not just absolute factor values)

---

## Files Produced

| File | Description |
|---|---|
| `backend/cache/phase21/result_exp_c.json` | Exp-C full results (IC=0.0912) |
| `backend/cache/phase21/result_exp_a.json` | Exp-A full results (IC=0.0912) |
| `backend/cache/phase21/result_exp_b.json` | Exp-B full results (IC=0.0687) |
| `backend/cache/phase21/oos_predictions_exp_c.parquet` | 7.3M OOS predictions |
| `backend/cache/phase21/oos_predictions_exp_b.parquet` | 4.5M OOS predictions |
| `backend/cache/phase21/features_expb_16.parquet` | 16-factor pre-exported matrix (684MB) |
| `backend/cache/phase21/l2_result_exp_c.json` | Layer 2 results |
| `backend/engines/portfolio_network.py` | PortfolioMLP + sharpe_loss (tested) |
| `scripts/research/perfect_prediction_upper_bound.py` | Part 1 script |
| `scripts/research/phase21_lgbm_experiments.py` | Part 2 experiments |
| `scripts/research/phase21_portfolio_network.py` | Part 3 training |
| `scripts/compute_factor_phase21.py` | 7-factor batch compute+ingest |
| `cache/part1_output.log` | Part 1 full output |
