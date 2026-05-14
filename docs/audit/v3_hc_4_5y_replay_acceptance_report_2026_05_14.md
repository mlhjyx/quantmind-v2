# V3 HC-4a — 5y Full minute_bars Replay Acceptance Report

**Run date**: 2026-05-15  
**Overall verdict**: ✅ PASS  
**Scope**: V3 横切层 Plan v0.3 §A HC-4a — 5y full minute_bars replay long-tail acceptance, run chunked per-quarter (user 决议 A) over 20 quarters, aggregated incrementally. Methodology sustained ADR-070 (daily-dedup + prev_close baseline counterfactual FP classification). Pure-function replay path per ADR-063.

---

## §1 5y Aggregate — V3 §15.4 4 项 acceptance

| # | Criterion | Threshold | Actual | Result |
|---|---|---|---|---|
| 1 | P0 alert 误报率 | `< 30%` | `4.12% (8,193/199,074)` | ✅ |
| 2 | L1 detection latency P99 | `< 5000ms` | `0.024ms (max-quarter)` | ✅ |
| 3 | L4 STAGED 流程闭环 0 失败 | `= 0` | `0` | ✅ |
| 4 | 元监控 0 P0 元告警 (replay-integrity form) | `= 0` | `0` | ✅ |

- Total minute_bars replayed: **139,303,467** · events: **3,757,195** · raw P0: **3,694,523** · deduped daily P0: **199,074** · classified: **199,074** (FP=8,193, TP=190,881) · unclassifiable: **0**
- STAGED: actionable **1,363** · generated **1,363** · closed-ok **1,363** · failed **0** · deadline-integrity **True** · pure-function-contract **True**
- Total replay wall-clock: **1413.8s**

### Per-rule FP/TP/unclassifiable (5y aggregate)

| rule_id | FP | TP | unclassifiable |
|---|---|---|---|
| `gap_down_open` | 7,510 | 150,360 | 0 |
| `limit_down_detection` | 292 | 17,611 | 0 |
| `near_limit_down` | 391 | 22,910 | 0 |

---

## §2 Per-quarter breakdown

| quarter | minute_bars | events | raw P0 | deduped P0 | FP | TP | P99 ms | staged failed | contract |
|---|---|---|---|---|---|---|---|---|---|
| 2021Q1 | 5,985,648 | 183,473 | 180,484 | 10,833 | 323 | 10,510 | 0.011 | 0 | ✅ |
| 2021Q2 | 6,301,632 | 136,243 | 133,160 | 6,620 | 216 | 6,404 | 0.010 | 0 | ✅ |
| 2021Q3 | 6,833,568 | 224,657 | 221,299 | 12,462 | 373 | 12,089 | 0.023 | 0 | ✅ |
| 2021Q4 | 6,616,272 | 139,792 | 136,677 | 7,429 | 284 | 7,145 | 0.009 | 0 | ✅ |
| 2022Q1 | 6,383,280 | 200,651 | 197,649 | 12,999 | 437 | 12,562 | 0.009 | 0 | ✅ |
| 2022Q2 | 6,555,216 | 269,044 | 265,949 | 15,255 | 603 | 14,652 | 0.023 | 0 | ✅ |
| 2022Q3 | 7,315,776 | 207,801 | 204,512 | 11,097 | 304 | 10,793 | 0.024 | 0 | ✅ |
| 2022Q4 | 6,850,560 | 126,883 | 123,854 | 7,128 | 242 | 6,886 | 0.024 | 0 | ✅ |
| 2023Q1 | 6,803,040 | 55,356 | 52,452 | 3,104 | 88 | 3,016 | 0.023 | 0 | ✅ |
| 2023Q2 | 6,873,648 | 147,119 | 144,126 | 6,915 | 169 | 6,746 | 0.024 | 0 | ✅ |
| 2023Q3 | 7,530,864 | 86,031 | 82,853 | 4,232 | 116 | 4,116 | 0.008 | 0 | ✅ |
| 2023Q4 | 7,089,184 | 82,948 | 79,870 | 4,184 | 144 | 4,040 | 0.009 | 0 | ✅ |
| 2024Q1 | 6,887,700 | 382,670 | 379,657 | 22,990 | 1,383 | 21,607 | 0.009 | 0 | ✅ |
| 2024Q2 | 7,025,207 | 289,680 | 286,613 | 13,264 | 292 | 12,972 | 0.015 | 0 | ✅ |
| 2024Q3 | 7,634,928 | 107,893 | 104,582 | 5,374 | 168 | 5,206 | 0.008 | 0 | ✅ |
| 2024Q4 | 7,289,664 | 353,133 | 349,461 | 18,224 | 641 | 17,583 | 0.009 | 0 | ✅ |
| 2025Q1 | 6,840,576 | 170,167 | 167,229 | 9,323 | 301 | 9,022 | 0.009 | 0 | ✅ |
| 2025Q2 | 7,227,888 | 335,831 | 332,692 | 14,243 | 1,602 | 12,641 | 0.009 | 0 | ✅ |
| 2025Q3 | 7,984,848 | 112,419 | 109,071 | 6,106 | 196 | 5,910 | 0.009 | 0 | ✅ |
| 2025Q4 | 7,273,968 | 145,404 | 142,333 | 7,292 | 311 | 6,981 | 0.009 | 0 | ✅ |

---

## §3 Methodology + caveats

- **Chunked per-quarter** (user 决议 A): the full ~191M-row minute_bars table cannot be materialized at once (TB-5b's `list(loader())` → ~95GB+ at 5y scale). Each quarter (~8M bars / ~3GB) is run + classified + the raw events discarded before the next quarter — only count aggregates are carried. Per-(code, rule_id, day) dedup is quarter-local-safe (quarters never span a day boundary).
- **Latency P99 = max of per-quarter P99** — conservative aggregate (if every quarter's P99 < 5s then the 5y P99 < 5s). A true 5y P99 over ~191M samples would need a streaming t-digest; the latency is already a documented LOWER-BOUND proxy (ADR-070 D6 — per-evaluate_at wall-clock, excludes I/O), so max-quarter is the honest conservative aggregate.
- **FP classification** sustained ADR-070: daily-dedup to first-per-(code, rule_id, day) + prev_close baseline counterfactual (FP = day-end close recovered ≥ prev_close). Methodology limitations carried forward (ADR-066 D3 caveat family): synthetic universe-wide Position = 误报率 upper-bound proxy NOT production-portfolio precision; 3/10 rules silent-skip (avg_daily_volume / industry / atr_pct not in minute_bars — sustained TB-5b §57-69).
- **0 真账户 / 0 broker / 0 .env / 0 INSERT** — pure read-only DB SELECT + in-memory replay, per-quarter pure-function contract audited. 红线 5/5 sustained: cash=￥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102.

关联: V3 §15.4 / §13.1 / §15.5 · ADR-063 / ADR-066 / ADR-070 / ADR-076 ·
Plan v0.3 §A HC-4 row + §D · 铁律 31/33/41 · LL-098 X10 / LL-159

---

## §4 TB-2e north_flow/iv wire — verification + stale-cite finding

HC-4a scope (Plan v0.3 §A line 114 / §D line 163) lists `north_flow_cny` + `iv_50etf`
MarketIndicators real-data-source wire as a HC-4a deliverable (carried from ADR-067 D5,
D3 决议). **Phase 0 fresh-verify finding**: the wire was ALREADY delivered by TB-2e
(PR #338), so HC-4a's deliverable for this item is **verification**, not implementation
(re-shaped per user 决议 A — AskUserQuestion 1 round).

### Verified facts (fresh-verify 2026-05-15)

| # | Fact | Evidence |
|---|---|---|
| 1 | `north_flow_cny` wired — Tushare `moneyflow_hsgt.north_money` (latest trade_date, 亿 CNY) | `backend/qm_platform/risk/regime/default_indicators_provider.py:279-348` `_fetch_north_flow_cny()` |
| 2 | `iv_50etf` wired — 上证 20-day realized volatility × √252 annualized proxy (V3 §5.3 line 658) | `default_indicators_provider.py:229-276` `_fetch_iv_50etf_proxy(conn)` |
| 3 | Both fields populated in `MarketIndicators` build path | `default_indicators_provider.py:147-156` (`north_flow_cny=` + `iv_50etf=`) |
| 4 | Provider is production-active — `_get_provider()` lazy singleton returns `DefaultIndicatorsProvider()` | `backend/app/tasks/market_regime_tasks.py:90` + call site `:129` |
| 5 | Committed in TB-2e | git `c537d13 feat(v3-tb-2e): MarketIndicators 6/6 wire — north_flow_cny + iv_50etf proxy (TB-2 真完全 closure) (#338)` |
| 6 | Both fetchers are read-only + fail-soft to `None` (铁律 1 先读官方文档 / 铁律 33 fail-loud-or-silent_ok) | `_fetch_north_flow_cny` `→ None` on missing data (lines 310/330/348); `_fetch_iv_50etf_proxy` `logger.warning ... → None` (line 276) |

→ **HC-4a north_flow/iv item = ✅ VERIFIED production-active** (0 new code — sustained ADR-022 反 silent 改 closed TB-2e code).

### Stale-cite finding (amend batched to HC-4c per ADR-022)

The following cites pre-date TB-2e #338 and still describe north_flow/iv as DEFERRED /
pending-HC-4-wire. They are **stale** (the wire is done) but are NOT amended here —
batched to HC-4c doc-amend per ADR-022 (反 retroactive scattered edit; one cumulative
amend pass):

- `docs/V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md:46` — "ADR-067 D5 — `north_flow_cny` + `iv_50etf` ... wire → **HC-4** (D3 决议)" (carried-deferral list — routing still valid, but item already done in TB-2e)
- `docs/V3_CROSSCUTTING_SPRINT_PLAN_v0.1.md:261` — "ADR-067 D5 TB-2 left DEFERRED, HC-4 wire 真数据源" (the "TB-2 left DEFERRED" half is stale — TB-2e wired it)
- `ADR-067 D5` itself — describes north_flow/iv as DEFERRED to HC-4 (predates TB-2e closure)
- `ADR-072 D3` — "both into HC-4 ... north_flow/iv wire" (the wire half is already satisfied)

Plan v0.3 §D lines 162-163 ("✅ HC-4a done") are CURRENT (amended during the HC-4a
re-shape) — listed here only to disambiguate from the stale cites above.

关联: ADR-067 D5 / ADR-072 D3 / TB-2e PR #338 `c537d13` · 铁律 1 / 铁律 22 / 铁律 45 ·
ADR-022 (batched amend) · Plan v0.3 §A HC-4a row
