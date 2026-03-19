# Phase 0 Progress Tracker

> Last updated: 2026-03-20
> Current stage: Week 0 - Data Feasibility Verification

## Week 0: Data Feasibility Verification (3 days)

### Day 1: Tushare API Field Verification
- [ ] Verify Tushare credit consumption (pull 1 month sample)
- [ ] Check up_limit/down_limit fields in daily interface
- [ ] Check ann_date field in fina_indicator interface
- [ ] Check industry classification (industry_sw1) in stock_basic

### Day 2-3: Data Quality Validation
- [ ] Verify adj_factor correctness (spot check 3 stocks)
- [ ] Verify daily_basic field completeness
- [ ] Confirm industry classification coverage rate
- [ ] Document findings and go/no-go decision

**Quality Gate**: All 4 assumptions must pass before proceeding to Week 1.

---

## Week 1: Database + Core Data Pull
- [ ] Execute DDL (40 tables + TimescaleDB hypertables)
- [ ] Pull symbols (including delisted stocks)
- [ ] Pull trading_calendar
- [ ] Pull index_daily (CSI300)
- [ ] Pull daily + adj_factor (full 2015-2025, overnight)

## Week 2: Data Completion + Validation
- [ ] Pull daily_basic
- [ ] Cross-table validation SQL
- [ ] Adj_close verification
- [ ] Industry classification data confirmation

## Week 3: Minimal Factor Set (6 factors)
- [ ] Preprocessing pipeline (MAD → fill → neutralize → zscore)
- [ ] 6 core factors implementation
- [ ] IC calculation pipeline
- [ ] Factor determinism test
- [ ] Batch write to factor_values

## Week 4: Signal + SimpleBacktester
- [ ] Equal-weight Top-20 signal composer
- [ ] SimBroker (limit-up/down, lot size, T+1 cash)
- [ ] SimpleBacktester (IBacktester Protocol)
- [ ] Basic metrics (Sharpe/MDD/Annual return)

## Week 5: Credibility Rules + Report
- [ ] Bootstrap Sharpe CI
- [ ] Cost sensitivity (0.5x/1x/1.5x/2x)
- [ ] Overnight gap statistics
- [ ] Annual decomposition
- [ ] Deterministic test framework (Parquet snapshot)
- [ ] End-to-end validation 2020-2025

## Week 6: Expand to 18 Factors
- [ ] Add remaining 12 factors
- [ ] Re-run full backtest
- [ ] Compare 6-factor vs 18-factor performance

---

## Key Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-20 | Initial 6 factors, not 18 | Validate pipeline first |
| 2026-03-20 | SimpleBacktester, not Hybrid | Phase 0 is weekly rebalance only |
| 2026-03-20 | Decimal for money, float64+4dp for returns | Balance precision and performance |
| 2026-03-20 | 20 stocks @100万, 30 @200万+ | Control lot-size deviation |
| 2026-03-20 | Excess IC is gold standard | Consistent with CLAUDE.md |
| 2026-03-20 | T-day 17:00 start pull | Give Tushare 1 extra hour |

## Blockers
(none yet)
