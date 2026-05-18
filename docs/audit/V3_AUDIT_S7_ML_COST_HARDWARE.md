# V3 Audit Section IX + X — ML/AI Closed Loop Maturity + Hardware/Cost/Capacity (NEW v5)

> **Source**: Subagent I §31-35 (ML/AI Closed Loop) + Subagent G §36-40 (Hardware/Cost/Capacity)
> **Plan v5 trigger**: v4 buried ML/AI + Cost + Hardware in §16/§19/§22, surface不够独立
> **Master**: `V3_FULL_PROJECT_DEEP_AUDIT_2026_05_18_MASTER.md`

---

# Section IX — ML/AI Closed Loop Maturity

## §31 LiteLLM Router Cost Per Decision Granularity

### §31.1 Routing Matrix (router.py:107-117)

```python
TASK_TO_MODEL_ALIAS = {
  NEWS_CLASSIFY      → v4-flash
  FUNDAMENTAL_SUMMAR → v4-flash
  BULL_AGENT         → v4-pro  (ADR-036 升 flash→pro)
  BEAR_AGENT         → v4-pro  (ADR-036)
  EMBEDDING          → v4-flash
  JUDGE              → v4-pro
  RISK_REFLECTOR     → v4-pro
}
FALLBACK_ALIAS = "qwen3-local"
```

### §31.2 Budget Compliance
- LLM_MONTHLY_BUDGET_USD = $50 (config.py:62 default)
- LLM_BUDGET_WARN_THRESHOLD = 0.80 (warn at 80%)
- LLM_BUDGET_CAP_THRESHOLD = 1.00 (cap, force Ollama fallback)

**[DB-VERIFY-PENDING]**: 0 file-based evidence of llm_cost_daily MTD vs $50 budget compliance. User can run 30s SQL:
```sql
SELECT call_type, COUNT(*), ROUND(SUM(cost_usd)::numeric,4)
FROM llm_call_log
WHERE created_at > date_trunc('month', NOW())
GROUP BY 1 ORDER BY 3 DESC;
```

### §31.3 P0-16 — No Monthly LLM Cost Audit Aggregator
- `QuantMind_LLMCostDaily` 20:30 daily LastResult=0 — daily only
- No monthly rollup → $50 budget enforcement is procedural only
- **Alt 1**: `scripts/llm_cost_monthly_audit.py` + Beat `crontab(day_of_month=1, hour=8)`
- **Alt 2**: Extend `llm_cost_daily_report.py` with `--monthly` flag
- **Alt 3**: Add monthly view to `/api/notifications/monthly-cost` + UI panel

### §31.4 CLAUDE.md Drift on LLM Cost Throttle
- CLAUDE.md cites "litellm throttle 50%"
- Actual: budget.py uses 80% warn + 100% cap
- **#14 Doc Lying** — update CLAUDE.md

---

## §32 V4-Flash vs V4-Pro Routing Strategy

### §32.1 Configured Ratio
- 5 v4-flash tasks (news_classify / fundamental_summar / embedding) + 2 v4-pro originally
- After ADR-036 BULL/BEAR 升 v4-pro: **3 flash + 4 pro task types**

### §32.2 真生产 Ratio [DB-VERIFY-PENDING]

User can verify:
```sql
SELECT model, COUNT(*) FROM llm_call_log
WHERE created_at > NOW() - INTERVAL '7 days' GROUP BY 1;
```

### §32.3 Throttle Effective?
- budget.py 3 state machine (Normal/Warn_80/Capped_100)
- LiteLLM Router strict=False soft fallback

### §32.4 P2 §32.1 — ADR-036 Cost Impact Risk
- BULL/BEAR upgrade to v4-pro → cost risk ↑
- **Alt 1**: Re-eval ADR-036 in $/decision quality test
- **Alt 2**: BULL/BEAR A/B v4-flash test for cost-quality tradeoff
- **Alt 3**: Introduce DEEPSEEK_V4_FLASH_THINKING (ADR-042) to replace v4-pro 部分场景

---

## §33 LLM Prompt Versioning + Iteration History

### §33.1 5 Prompts in `prompts/risk/*_v1.yaml`
- news_classifier_v1.yaml (ADR-051 NewsClassifier V2 cite)
- bear_agent_v1.yaml
- bull_agent_v1.yaml
- regime_judge_v1.yaml
- reflector_v1.yaml

### §33.2 Versioning Status
- All 5 = `_v1.yaml`, **0 v2 sediment in file system**
- ADR-051 cites "V2 prior" but 0 v2 file 落地

### §33.3 Prompt Eval
- V3 §3.2 line 1313 "S3 prompt eval + 历史 news 回测" 真预约
- `quantmind-v3-prompt-eval-iteration` skill exists but 0 evidence of run history

### §33.4 P1 §33.1 — Prompt v1 → v2 0 Sediment
- **Alt 1**: Force prompt iteration cycle each sprint = 5 prompt × paired test (n=100 historic news) → KL divergence accept gate
- **Alt 2**: prompt registry DB table (prompt_id, version, hash, deployed_at)
- **Alt 3**: Shadow-deploy v2 vs v1 parallel 7d cost-quality compare

---

## §34 RAG Memory Population Strategy

### §34.1 risk_memory Status [DB-VERIFY-PENDING]

User can verify:
```sql
SELECT COUNT(*), MAX(created_at) FROM risk_memory;
```

### §34.2 Documentary Evidence
- ADR-068 "TB-3 risk-memory RAG closure" 沉淀
- ADR-070 "TB-5b replay acceptance" 沉淀
- Population should be > 0 post-TB-3

### §34.3 Bull/Bear/Reflector RAG Consumption
- Designed yaml referenced but specific 调用 path 0 file-grep
- Need DB row count + log retrieval verify

### §34.4 P1 §34.1 — RAG Memory + 消费 0 Trace
- **Alt 1**: DB query verify rows + MAX(created_at)
- **Alt 2**: Bull agent log RAG retrieval k=5 source IDs in llm_call_log.metadata
- **Alt 3**: End-to-end RAG test (10 historic news → 期望 retrieval 命中 historical pattern → 100% recall)

---

## §35 V4 → V5 Migration Readiness

### §35.1 Migration Path
- DeepSeek V4 → V5: 0 release public schedule
- ADR-034 fallback upgrade qwen3 → qwen3.5 sediment

### §35.2 Prompt Portability Cross-Model
- `prompts/risk/*.yaml` 0 model-specific tokens (JSON schema only) → portable

### §35.3 Fallback Chain Reality
- router.py:120 `FALLBACK_ALIAS` only single fallback
- cap_100 → 直接 Ollama, 不经 v4-flash
- **Not真 chain**, is 2-hop not 3-hop

### §35.4 P2 §35.1 — Fallback Chain 2-hop not 3-hop
- **Alt 1**: Add v4-pro → v4-flash → ollama 真 3-hop (router config priority)
- **Alt 2**: Cost-driven step-down (budget 95-100% → 强制 flash)
- **Alt 3**: Capability-driven (ollama judge 质量 0 verify, RISK_REFLECTOR fallback strict=True raise instead of silent)

---

# Section X — Hardware / Cost / Capacity + Ops SSOT

## §36 Strategy Capacity Analysis

### §36.1 Slippage Three-Factor Calibration
- `backend/engines/slippage_model.py` last commits ~2026-03 (Sprint 1.14 era)
- `ac4497c` Bouchaud 2018 sigma_daily; `e81197b` cap-tiered k
- **No commits since Sprint 1.14 for slippage tuning**

### §36.2 Top-N Tradeoff Analysis
- PT_TOP_N = 5 (LL-183 灰度 grade) vs CLAUDE.md table "Top 20"
- Capacity implication: ¥1M / 5 stocks = ¥200K each
- ~30-40K shares per ¥5-7 stock
- Slippage `impact_bps = Y_small * σ_daily * sqrt(Q/V) * 10000` for ¥10B-cap with daily turnover ¥80M
  - = 0.25%-0.4% per trade = 25-40 bps
- **Within R4 target 54-74 bps**

### §36.3 ¥10M / ¥100M Scaling Risk
- ¥10M / 5 stocks = Q/V≈2.5% → impact >80 bps
- ¥100M scaling → ~10% of mid-cap daily volume → impact_bps could exceed 200 bps for Y_small=1.5
- **Capacity ceiling estimated ~¥30-50M for Top-5 small/mid universe**
- Should be documented + stress-tested

### §36.4 P2 — Capacity Scaling Heuristic #16 Pre-Mortem
- ¥1M → ¥10M Top-5 → impact_bps >80 → 铁律 18 review trigger
- **Alt 1**: Tier capital to mid/large-cap when AUM > ¥5M
- **Alt 2**: Re-tune Y_large/Y_mid via fresh bayesian_calibration
- **Alt 3**: Cap Top-5 to large-cap pool when capital >¥5M

---

## §37 Survivorship Bias Audit

### §37.1 Backtest Universe Filter
- `backend/engines/backtest/runner.py:138-154`
- Per-date excludes ST/suspended/new_stock/BJ via flags conditional on column presence (`_has_status = "is_st" in price_data.columns`)
- **No `delisted_at` filter** (Grep `delisted_at|退市` only 1 file)
- Backtest universe likely **EXCLUDES delisted stocks entirely**

### §37.2 P0-11 Bias Risk
- Historically delisted stocks (ST*BL / ST锐电 / etc.) silently absent
- 12yr Sharpe = 0.36 might inflate by 0.1-0.2 if delisted included
- **Alt 1**: Add `historical_universe` view including delisted with last-known-price
- **Alt 2**: Use Tushare `delist_d` field in load_universe
- **Alt 3**: Run sensitivity test 5yr/12yr Sharpe with/without delisted set

---

## §38 Slippage Model 季度复核 (铁律 18)

### §38.1 Last Calibration
- `scripts/bayesian_slippage_calibration.py` last touched `7ebc752` (MVP 4.1 batch 3.7 — Platform SDK migration ONLY, not recalibration)
- Calibration content commits: `b52cf11` / `ac4497c` / `e81197b` ~Sprint 1.14 era (2026-03)
- **Quarterly review expected ~2026-06** (3 months from 03)

### §38.2 Real bps vs Threshold (5bps per 铁律 18)
- No recent calibration log found
- **Calibration job has 0 scheduler entry** (`Bash grep schtask|crontab slippage_calib` = no hits)

### §38.3 P0-10 — 铁律 18 Slippage Quarterly Calibration 0 Scheduler
- 铁律 18 written but 0 enforce
- **Alt 1**: Beat `slippage-calibration-quarterly` crontab(day_of_month=1, month_of_year='1,4,7,10', hour=2)
- **Alt 2**: schtask QuantMind_SlippageCalibration with email alert
- **Alt 3**: Inline calibration as part of monthly factor_lifecycle review

---

## §39 Beat/Schtask Calendar SSOT

### §39.1 SSOT Location
- `backend/app/services/trading_calendar.py`
- Fallback chain: DB `trading_calendar` table → `engines.trading_day_checker.TradingDayChecker` Tushare → weekday heuristic
- 25 callers Grep-confirmed

### §39.2 Coverage
- pt_audit / data_quality_check / pull_moneyflow / daily_pipeline / execution_service all reference it
- Good consolidation

### §39.3 半日市/调休
- Grep `半日市|half_day|调休` → not surfaced in calendar.py:1-80
- Depends on Tushare `is_trading_day` returning 0/1 binary (no half-day flag visible)

### §39.4 Beat ≠ Schtask Alive Probe
- services_healthcheck.log 22:30 has `Beat heartbeat 2.8min ago (fresh)`
- Schtask probe present but only partial (no global QuantMind_* freshness audit)

### §39.5 P0-5/P0-6 — LL-181 Lesson Beat + Schtask Freshness Probe (master)

---

## §40 Daily Critical Path Analysis

### §40.1 Stage Timeline (Verify 2026-05-18)

| Time SH | Stage | LastRun | Status |
|---|---|---|---|
| 09:31 | execute | 2026-04-19 (Disabled) | ⛔ LL-183 |
| 10:00 | risk_event_log | (dark) | — |
| 15:40 | reconciliation | 2026-05-18 15:40:01 | ✅ 0 |
| 16:00 | regime close + fundamental | (Beat) | ✅ |
| 16:30 | DailySignal + daily_metrics_extract | 2026-05-18 16:30:01 | ✅ 0 |
| 17:30 | DailyMoneyflow + FactorHealthDaily | 2026-05-18 17:30:01 | ✅ 0 |
| 17:35 | PT audit | 2026-05-18 17:35:02 | ✅ 0 (5 PASS) |
| 17:40 | daily-quality-report | (Beat) | ✅ |
| 18:00 | DailyIC | 2026-05-18 | ✅ 0 |
| 18:15 | IcRolling | 2026-05-18 | ✅ 0 |
| 18:30 | DataQualityCheck | 2026-05-18 18:30:14 | ❌ **1 FAIL** (P0-7) |
| 18:45 | RiskFrameworkHealth | 2026-05-18 18:45:00 | ❌ **1 FAIL** (P0-7) |
| 19:00 (Fri) | factor-lifecycle | (Beat) | ✅ |
| 20:00 | PT_Watchdog | 2026-05-18 | ✅ 0 |
| 20:30 | LLMCostDaily | 2026-05-18 | ✅ 0 |

### §40.2 Per-Stage Latency (Where Measurable)
- pt_audit 5-check = 0.02s total (very fast)
- DataQualityCheck = ~11.9s (18:30:02 → 18:30:14)
- compute_daily_ic = 1.9s (memory note)
- Beat heartbeat = 30s tick (outbox-publisher)

### §40.3 Peak Hour RAM
- 22 GB used at 22:49 (idle PT-paused window)
- During 09:30 market open with full pipeline, expect +4-6 GB → 28 GB / 31 GB total (90%)
- **Tight headroom #6 SLA**

### §40.4 P0-15 — 09:30 SH Market Open No Watcher
- (master)

---

**End Sections IX + X.**
