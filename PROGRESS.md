# Phase 0 Progress Tracker

> Last updated: 2026-03-20
> Current stage: Week 1 - Database + Core Data Pull

## Week 0: Data Feasibility Verification ✅ COMPLETED

### Day 1: Tushare API Field Verification ✅
- [x] Verify Tushare credit consumption (pull 1 month sample)
- [x] Check up_limit/down_limit fields in daily interface
- [x] Check ann_date field in fina_indicator interface
- [x] Check industry classification (industry_sw1) in stock_basic

### Day 2-3: Data Quality Validation ✅
- [x] Verify adj_factor correctness (spot check 3 stocks)
- [x] Verify daily_basic field completeness
- [x] Confirm industry classification coverage rate
- [x] Document findings and go/no-go decision → **GO**

## Week 1: Database + Core Data Pull 🔨 IN PROGRESS

### Database Setup ✅
- [x] Execute DDL (43 tables from QUANTMIND_V2_DDL_FINAL.sql)
- [x] Pull symbols (5810 stocks including delisted: L+D+P statuses)
- [x] Board detection + price_limit mapping (main/gem/star/bse/ST)

### Data Fetcher Implementation ✅
- [x] `tushare_fetcher.py` — by-date pull strategy, retry logic, merge_daily_data
- [x] `data_loader.py` — upsert functions with FK filtering, connection reuse
- [x] `pull_full_data.py` — CLI with --table/--start/--end/--dry-run, checkpoint resume
- [x] `refresh_symbols.py` — full stock universe refresh script
- [x] `validate_data.sql` — 12-check verification script

### Core Data Pull 🔨
- [x] klines_daily 2020-01-02 to 2024-01-12 (4.5M rows, first session)
- [ ] klines_daily 2024-01-13 to 2026-03-20 (resuming, ~6.8M total so far)
- [ ] daily_basic full pull (pending klines completion)
- [ ] index_daily CSI300 + CSI500 + CSI1000 (pending)
- [ ] Run validate_data.sql full verification
- [ ] Git commit all data fetcher code

### Fixes Applied (from quant/arch/qa review)
- Fixed: North Exchange (8xx) filtering in stk_limit
- Fixed: pct_chg → pct_change rename in index_daily
- Fixed: Code suffix stripping (000001.SZ → 000001)
- Fixed: FK pre-filtering with symbols cache
- Fixed: Float comparison for is_suspended detection
- Fixed: itertuples for 10x performance over iterrows
- Fixed: Connection reuse across upsert calls
- Fixed: Dynamic end date (today vs hardcoded)
- Fixed: Consecutive failure abort logic

## Week 2: Data Completion + Validation
- [ ] Verify klines_daily completeness
- [ ] daily_basic cross-table validation
- [ ] Adj_close verification (spot check known ex-right dates)
- [ ] Industry classification data confirmation
- [ ] 3-stock sample comparison (600519/000001/300750)

## Week 3: Minimal Factor Set (6 factors)
- [ ] Preprocessing pipeline (MAD → fill → neutralize → zscore)
- [ ] 6 core factors: momentum_20, volatility_20, turnover_mean_20, amihud_20, bp_ratio, ln_market_cap
- [ ] IC calculation pipeline (excess return vs CSI300)
- [ ] Factor determinism test
- [ ] Batch write to factor_values (by-date, single transaction)

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

## Team (Phase 0)

| Role | Scope | Status |
|------|-------|--------|
| **Team Lead** (Claude主线程) | 任务分配、进度跟踪、验收 | Active |
| **quant** | 量化逻辑审查，一票否决权 | Active |
| **arch** | Service层+回测引擎编码 | Active |
| **qa** | 功能测试(API/因子/回测) | Active |
| **data** | 数据管道全权(拉取/清洗/验证/备份) | Active |
| **factor** | 因子研究(审查+新因子设计) | Week 3起深度介入 |
| **strategy** | 策略研究(回测审查+策略优化) | Week 4起深度介入 |

## Key Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-20 | Initial 6 factors, not 18 | Validate pipeline first |
| 2026-03-20 | SimpleBacktester, not Hybrid | Phase 0 is weekly rebalance only |
| 2026-03-20 | Decimal for money, float64+4dp for returns | Balance precision and performance |
| 2026-03-20 | 20 stocks @100万, 30 @200万+ | Control lot-size deviation |
| 2026-03-20 | Excess IC is gold standard | Consistent with CLAUDE.md |
| 2026-03-20 | T-day 17:00 start pull | Give Tushare 1 extra hour |
| 2026-03-20 | By-date pull (not by-stock) | ~5000 API calls for 5 years |
| 2026-03-20 | Industry merge: <30 stocks → nearest large industry | 110→48 categories |
| 2026-03-20 | Skip TimescaleDB Phase 0 | PG16 vs PG17 compatibility |

## Blockers
(none)
