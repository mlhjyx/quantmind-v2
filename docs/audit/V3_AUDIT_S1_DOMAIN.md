# V3 Audit Section I — Domain & Strategy Edge (2026-05-18 evening)

> **Source**: Subagent A §1-2 / Cross-validated by CC main process
> **Master**: `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`

---

## §1 A股 Domain Anchor Map

| Domain feature | Code anchor | Status | Finding (heuristic#) |
|---|---|---|---|
| T+1 settlement | `backend/app/services/pt_data_service.py:301` (`is_st`), no `t_plus_1`/`t1_settle` symbol grep | **GAP** | **#1 / #14** — CLAUDE.md "排除新股 (list<60 天)" implies T+1 but no canonical enforcement function. Risk: backtest signal day = sell day silently allowed |
| 涨跌停 limit_up/down | 15 files: `backend/engines/broker_qmt.py`, `backend/qm_platform/risk/rules/intraday.py:33` (Redis `qm:qmt:status`), `backend/engines/backtest/validators.py` | OK | **#4** — Widely referenced. LL-183 incident 11 buy orders frozen — likely limit-up rejection path. Need spec-vs-code parity audit |
| 集合竞价 (auction) | `Grep 集合竞价\|auction_phase` → **0 hits** in backend/scripts | **MISSING** | **#1 / #14** — 9:15-9:25 auction handling not isolated. CC may submit during opening auction → 0 fills (aligns with LL-183 11 orders 0 fills) |
| ST/*ST exclusion | `backend/app/services/pt_data_service.py:301` `is_st(code, td)` — single anchor | Risk | **#2 / #20** — only 1 `is_st` def entire codebase. No `is_star_st` or `is_delisted`. Passive ST tagging via daily_basic flag only |
| 北交所 BJ exclusion | 15 files (broker_qmt, news/akshare_cninfo, data/sources/baostock, tushare) | OK | Universe filter active per CLAUDE.md |
| 科创板 20% limit | Found in 15-file batch alongside BJ + ST; `backend/engines/backtest/validators.py` | Partial | **#1 Drift** — 20% limit implementation depth uncertain |
| 分红除权 adjust | `backend/qm_platform/data/sources/tushare_source.py` (qfq/hfq) | OK | klines_daily front-adjust per CLAUDE.md |
| Failed direction catalog (8 项) | `CLAUDE.md §已知失败方向` (12 rows + research-kb 30+) | OK | Sustained per memory |
| Phase 2/3 NO-GO (7 项) | memory `project_research_nogo_revisit` 2026-04-18 | **STALE** | **#15 Time-decay** — 7 items pending re-eval after U1 Parity / U3 Lineage / U5 Attribution platform完成 |

### §1.1 Quant Philosophy Embedded

- **Alpha source theory**: 4 CORE = turnover (流动性溢价 / 关注度回归) + volatility (低波异象) + bp_ratio (Value FF-style) + dv_ttm (Dividend yield cash flow signal). Simple linear avg.
- **Portfolio theory**: Equal-weight (Step 6-G NO-GO on MVO/RP/BL — 等权最优 per CLAUDE.md). Risk parity / min variance both降 alpha (G2 7组实验 sediment).
- **Risk attribution**: Partial Size-Neutral b=0.50 (Step 6-H 唯一有效 Modifier). 7 candidate modifiers全 FAIL.

### §1.2 Market Regime Taxonomy

- L2 MarketRegime (09:00 / 14:30 / 16:00 Beat) Bull/Bear/Judge debate
- L3 DynamicThresholdEngine reads regime → adapts thresholds
- **Open-loop**: regime → signal disconnect (Loop 4 broken per Subagent E)
- vol_regime ≠ news_regime (bifurcated, only vol_regime affects position size)

### §1.3 Trading Edge Identification ("Moat")

- CORE3+dv_ttm WF OOS Sharpe=0.8659 (2026-04-12 PASS)
- 5yr 0.6095 / 12yr 0.3594 / WF 0.8659 — **2.4× spread suggests regime-dependent edge** (post-2020 small-cap rally favorable)
- Single-bet on this strategy = single point of failure (no diversification)
- Capacity ceiling estimated ~¥10-30M for Top-5 small/mid universe (¥100M+ would push impact_bps >200, beach 铁律 18)

### §1.4 Universe Characteristics

- A股 全市场 - BJ - ST - 新股 60d
- Daily volume floor ≥ ¥5000万 20日均
- 100 股整手 (lot size enforcement)
- **Survivorship bias risk** (Subagent G P0-011): backtest excludes历史退市 stocks → may inflate Sharpe by 0.1-0.2

---

## §2 Strategy Edge Audit (4 CORE Active)

| Factor | Direction | Alpha source hypothesis | Health Status | Finding (heuristic#) |
|---|---|---|---|---|
| **turnover_mean_20** | -1 | 流动性溢价 / 关注度回归 | active | **#7 Anchor Bias** — 20-day window arbitrary, not adaptive to regime |
| **volatility_20** | -1 | 低波异象 | active | Standard. Sharpe contribution via SN partial b=0.50 |
| **bp_ratio** | +1 | Value FF-style book-to-price | active | Standard |
| **dv_ttm** | +1 | Dividend yield cash flow signal | **⚠️ warning sustained 30+ days** (ratio=0.517 < 0.8) | **#1 / #4** — 4-week+ warning, no escalation/degradation. Lifecycle Beat (Fri 19:00) running but not removing from PT |

### §2.1 OOS Robustness Heterogeneity

- 5yr Sharpe=0.6095 (CORE3+SN inner 0.68)
- 12yr Sharpe=0.3594 (CORE5 baseline)
- WF Sharpe=0.8659 (CORE3+dv_ttm+SN, current PT配置)
- **2.4× spread (12yr vs WF)** = **#10 Selection Bias** suggests WF window favorable
- Post-2020 small-cap rally may skew

### §2.2 Single-Bet Risk

- 1 strategy on entire ¥1M portfolio
- **#5 Single-Point-of-Failure**
- 0 diversification across factor categories beyond linear avg
- Failed direction 8 项 + Phase 2/3 NO-GO 7 项 — backup strategy candidates exist but unvalidated

### §2.3 Capacity Considerations (preview §X-§36)

- ¥1M paper current
- ¥10M scaling untested
- slippage_model 三因素 calibrated for ¥1M (per CLAUDE.md performance table)
- 铁律 18 H0 < 5bps target — calibration date stale (Sprint 1.14 era 2026-03)

### §2.4 P0/P1 Findings (with #18 alternatives)

| # | Finding | Severity | Heuristic | Alt 1 | Alt 2 | Alt 3 |
|---|---|---|---|---|---|---|
| 1 | dv_ttm warning state 30+ days unmanaged | P1 | #1 / #4 | Demote to candidate, run PT on CORE3 | Threshold escalate (warning >4w → P1 alert + auto-demote) | Counterfactual replay 2025-04→2026-04 |
| 2 | Single-strategy concentration (CORE3+dv_ttm = 100% portfolio) | P1 | #5 / #10 | Multi-sleeve (70/30 reserve) | Regime-conditional weighting | Capital cap ¥1M until validated at ¥3M |
| 3 | A股 T+1 / 集合竞价 enforcement function MISSING | P1 | #1 / #14 / LL-183 link | Add `backend/engines/board_calendar.py` with `is_t1_settled`, `is_auction_phase`, `is_tradable_minute` | Embed checks in `qmt_execution_adapter.py` pre-submit | Pre-trade validator verify exists |
| 4 | OOS heterogeneity (5yr 0.6095 / 12yr 0.3594 / WF 0.8659) underdisclosed | P2 | #10 selection / #8 | Disclose 12yr Sharpe prominently | Stress-test 2018-2020 bear separately | Out-of-time-bucket holdout (2026-future) |
| 5 | Capacity scaling ¥1M → ¥10M Top-5 → impact_bps >80bps | P2 | #6 SLA | Tier capital to mid/large-cap when AUM > ¥5M | Re-tune Y_large/Y_mid via fresh bayesian_calibration | Cap Top-5 to large-cap pool when capital >¥5M |

---

## §3 Cross-Reference

- Master P0/P1: see MASTER §1.1-1.2 (P0-1 .env / P0-10 slippage / P0-11 survivorship)
- Section X §36 capacity deep dive: `V3_AUDIT_S7_ML_COST_HARDWARE.md`
- Strategy lifecycle: `V3_AUDIT_S4_HEALTH_AND_DEAD_CODE.md` Workflow 1 factor onboarding

**End Section I.**
