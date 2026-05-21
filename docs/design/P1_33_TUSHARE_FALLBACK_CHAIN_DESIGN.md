# P1-33 Tushare Fallback Chain Design (SPF 6 mitigation)

> **Plan v8 P1-33 closure prep** — design only, multi-week implementation deferred.
> **Source**: Plan v8 SPF 6 (Single Point of Failure 6: Tushare 唯一数据源)
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**SPF 6 risk** (Plan v8 audit §11 Failure Cascade Map):
- Tushare API 是 daily OHLCV / 财务 / 资金流 唯一上游
- Tushare 限流 / 维护 / 商业模式变更 = backend daily pipeline 全停
- 历史发生: 2026-05-15 daily 17:30 schtask 偶尔 5-attempt retry 全失败 (LL-N 候选)
- 当前 mitigation: 5 retry + DingTalk alert + 17:45 deferred DataQualityCheck

**为什么 P1 (非 P0)**: PT 当前 paper-mode, 1-2 天数据 stale 不阻塞 trade. 但 live trading 启动后 P0 升级.

---

## §2 Fallback Source Inventory

### §2.1 Tushare (primary, current)
- API: tushare-pro
- Coverage: 全 A 股 OHLCV / 财务 / 资金流 / 北向 / 沪深港通 / dividend
- Auth: 5000 积分 token
- 限流: 2-3 req/s (free tier)
- 数据精度: 行业 SSOT 类
- Cost: 免费 (token-based)

### §2.2 Baostock (current backup, minute-level only)
- API: baostock public REST
- Coverage: A 股 5min minute_bars (1 yr lookback)
- Auth: 0 (anonymous)
- 限流: 较宽松
- 数据精度: 良好
- Cost: 免费
- Current usage: minute_bars sync (5 yrs / 2537 stocks)
- **Extension candidate**: daily OHLCV (fallback if Tushare down)

### §2.3 Akshare (open source aggregator)
- API: Python akshare lib (pypi)
- Coverage: 全 A 股 + 港股 + 美股 OHLCV (scrapes various sources)
- Auth: 0
- 限流: depends on upstream
- 数据精度: 不稳 (scraper底层, 接口频繁变化)
- Cost: 免费
- **Risk**: 反爬虫 ban (depends on upstream provider's policy)
- Use as: tertiary fallback only

### §2.4 Wind (商业)
- API: Wind官方 Python SDK (WindPy)
- Coverage: 全 A 股 + 港股 + 美股 + 期货 + 期权
- Auth: Wind 终端 license (商业, ~3 万/年)
- 限流: 无 (按 license)
- 数据精度: 行业 SSOT
- Cost: NOT FREE
- **Use as**: defer (cost vs single-user)

### §2.5 同花顺 iFinD (商业)
- 类似 Wind, 商业, defer

---

## §3 Fallback Chain Design

### §3.1 Chain order

```
Tushare (primary)
    ↓ on FAIL (5 retry exhausted + 2 hour stale)
Baostock (secondary)
    ↓ on FAIL (data不完整 / API 不通 / 1 hour 内 2 attempts)
Akshare (tertiary, best-effort)
    ↓ on FAIL
DingTalk P0 alert + manual intervention
```

**Decision criteria**:
- 5-attempt Tushare retry exhausted → mark `tushare_fail_event` in DB
- 2 hours sustained no fresh data → trigger Baostock fallback
- Baostock partial data acceptable (degraded mode)
- Akshare only as last resort (reliability concerns)

### §3.2 Trigger flags

```python
@dataclass
class DataSourceFallbackState:
    primary_status: Literal["healthy", "degraded", "failed"]
    last_primary_success: datetime
    fallback_active: bool
    fallback_source: str | None  # "baostock" or "akshare"
    sustained_failure_count: int
    next_retry_at: datetime | None
```

### §3.3 Data quality reconciliation

When Tushare recovers:
1. Refresh window: re-fetch all data from primary
2. Compare fallback data vs primary truth
3. Surface discrepancies (LL candidate sediment)
4. Restore primary, clear fallback flag

---

## §4 Implementation Phases

### §4.1 Phase 1 (Week 1): Baostock daily OHLCV adapter

- New `backend/qm_platform/data/baostock_daily_source.py` (mirror of `baostock_source.py` for minute_bars)
- Same DataPipeline contract (insertion via partial UPSERT)
- Test: fetch 1 trading day, verify data quality vs Tushare same date

### §4.2 Phase 2 (Week 2): Fallback orchestrator

- New `backend/app/services/data_fallback_orchestrator.py`
- Wraps existing `pull_tushare_daily.py` + new Baostock fallback
- State machine: healthy → degraded → failed → recovery
- Sustained-failure detection: 5 retry exhausted + 2h stale
- Test: simulate Tushare 503, verify fallback triggers

### §4.3 Phase 3 (Week 3): Schtask wire + DingTalk integration

- Update `QuantMind_DailyDataIngest_Postclose` schtask → wrap orchestrator
- DingTalk P1 alert on fallback activation (not P0 because data still flowing)
- DingTalk P0 alert on ALL sources failed
- Test: e2e fallback chain

### §4.4 Phase 4 (Week 4): Akshare tertiary (optional, defer Phase J)

- akshare integration deferred — reliability concerns + single-user blast radius low
- Document as Phase J candidate

### §4.5 Phase 5 (Ongoing): Quarterly reconciliation audit

- Quarterly: compare Tushare vs Baostock historical (1 year sample)
- Surface systematic discrepancies (e.g. Baostock dividend handling)
- Sediment LL on any drift > 0.5%

---

## §5 Alternatives Considered

### Alt 1: Cache-based fallback (degraded mode)
- Read latest cached snapshot (no fresh data)
- Continue trading on stale assumption
- **Risk**: paper-mode OK, live-mode dangerous
- Decision: cache fallback for read-only, not for trade decisions

### Alt 2: Pause trading until source recovery
- DingTalk P0 → user intervenes
- Simple, current de-facto behavior
- **Limitation**: 无 self-healing, requires manual

### Alt 3: Multi-source quorum (consensus)
- All 3 sources fetch, take consensus
- High latency + bandwidth cost
- Defer Phase J

### Alt 4: PT live downsides
- Direct broker query (xtquant) as data source
- Only OHLCV not 财务/资金流
- Defer — not viable for full daily pipeline

---

## §6 Risk Mitigations

### §6.1 Akshare 反爬虫 ban
- Use rotating User-Agent + jitter
- Cap requests/min < 60
- Fail gracefully on 403/429

### §6.2 Baostock data 差异
- Field mapping table sediment
- Conversion utility (e.g. PE ratio handling differs)
- Quarterly audit (§4.5)

### §6.3 Source switch transparency
- All sources write to same DB tables
- New column: `source_provenance` (tushare/baostock/akshare)
- Backtest can opt to filter by source

---

## §7 Effort Estimate

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Baostock daily adapter | 3-5 days | Existing baostock_source.py |
| 2 Fallback orchestrator | 3-4 days | Phase 1 |
| 3 Schtask wire + DingTalk | 2-3 days | Phase 2 |
| 4 Akshare tertiary | 5-7 days (deferred) | Phase 3 |
| 5 Quarterly audit | Ongoing | Phase 1+ |

**Total to Phase 3**: ~2 weeks
**Total to Phase 4**: ~3 weeks
**Quarterly maintenance**: ~1 day/quarter

---

## §8 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (design only)
- Phase B-2 (5-27 Wed): NOT prerequisite
- Phase J (post 5-27): Phase 1-3 priority — PT live exposes SPF 6 risk
- Phase J+1 (Quarter 2-3): Phase 4+5

---

## §9 Iron Law Compliance

- Iron Law 17: All DB writes via DataPipeline
- Iron Law 33: Fail-loud per-source, no silent fallback
- Iron Law 34: Source config single-source-of-truth (`backend/.env` per source)
- Iron Law 41: Timezone aware (Tushare UTC+8, Baostock UTC+8, Akshare varies)

---

**Maintained by**: CC autonomous (Plan v8 P1-33 design sediment, 2026-05-20 Day 1)
**Cross-ref**:
- V3 §3.1 Data source design
- backend/qm_platform/data/baostock_source.py (minute_bars precedent)
- scripts/pull_tushare_daily.py (current primary path)
- Plan v8 §11 SPF 6 finding
