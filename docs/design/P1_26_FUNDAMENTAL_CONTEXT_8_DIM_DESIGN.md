# P1-26 FundamentalContextService 8-dim Expansion Design

> **Plan v8 P1-26 closure prep** — design only, V3 §3.3 8-dim multi-week implementation deferred.
> **Source**: V3 §3.3 FundamentalContext design — currently 1/8 dims implemented (basic financial only)
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 P1-26)**:
- V3 §3.3 design proposes 8-dim fundamental context for LLM/factor decisions
- Current `backend/app/services/fundamental_context_service.py` covers 1/8 dims:
  - Dim 1: 财务基本面 (PE/PB/ROE/营收增长) — implemented

**Missing 7 dims** (per V3 §3.3):
- Dim 2: 行业宏观 (industry GDP / sector rotation context)
- Dim 3: 股东结构 (前 10 大股东 / 北向持仓 / 高管持股变化)
- Dim 4: 经营质量 (毛利率 / ROIC / FCF / WC turnover)
- Dim 5: 治理 (审计意见 / 立案调查 / 集体诉讼)
- Dim 6: 估值相对 (PE percentile in industry / 历史 percentile)
- Dim 7: 资金流 (主力 / 散户 / 北向 / 大单)
- Dim 8: 公告与事件 (重大公告 / 业绩快报 / 股东减持)

---

## §2 Per-Dim Implementation Sketch

### §2.1 Dim 2: 行业宏观

**Data sources**:
- 行业 GDP / 工业增加值 (国家统计局)
- 申万行业涨跌幅 / 资金流向 (Tushare)
- PMI / 社融数据 (央行)

**Service**: `industry_macro_service.py`
**Cache TTL**: 1 day (monthly data)

### §2.2 Dim 3: 股东结构

**Data sources**:
- top10_holders (Tushare)
- 北向持仓变化 (hsgt_hold_stock)
- 高管增减持 (Tushare stk_holdertrade)

**Service**: `shareholder_structure_service.py`
**Cache TTL**: 1 week (quarterly reports)

### §2.3 Dim 4: 经营质量

**Data sources**:
- fina_indicator (Tushare 财务指标)
- 毛利率 / ROIC / FCF / WC turnover 计算
- 季度趋势分析

**Service**: `operating_quality_service.py`
**Cache TTL**: 90 days (quarterly)

### §2.4 Dim 5: 治理

**Data sources**:
- 审计意见 (Tushare audit_opinion)
- 立案调查 (CSRC announcements)
- 集体诉讼 (Tushare litigation)

**Service**: `governance_service.py`
**Cache TTL**: 1 month

### §2.5 Dim 6: 估值相对

**Data sources**:
- daily_basic.pe_ttm / pb_ttm
- 行业聚合 (申万一级行业)
- 历史 percentile 计算

**Service**: `valuation_relative_service.py`
**Cache TTL**: 1 day

### §2.6 Dim 7: 资金流

**Data sources**:
- moneyflow (Tushare 个股资金流)
- 主力 / 散户分类
- 北向 hsgt_hold_stock

**Service**: `capital_flow_service.py`
**Cache TTL**: 1 day

### §2.7 Dim 8: 公告与事件

**Data sources**:
- announcement (Tushare 公告)
- earnings_announcement_calendar
- shareholder_holdtrade

**Service**: `announcement_event_service.py`
**Cache TTL**: 1 day (often updated intra-day)

---

## §3 Architecture

### §3.1 Aggregator pattern

```python
# backend/app/services/fundamental_context_service.py (expanded)
class FundamentalContextService:
    def __init__(self):
        self.dim1 = FinancialBasicsService()
        self.dim2 = IndustryMacroService()
        self.dim3 = ShareholderStructureService()
        # ... etc 8 dims

    def get_context(self, code: str, trade_date: date) -> FundamentalContext:
        return FundamentalContext(
            dim1=self.dim1.get(code, trade_date),
            dim2=self.dim2.get(code, trade_date),
            # ... lazy-load 8 dims
        )
```

### §3.2 Consumer

- NewsClassifier (V3 §3.2): 公告 → 触发何 dim?
- Bull/Bear LLM (V3 §16): 多 dim 综合判断
- Factor research: 8-dim 作为新 factor 候选 inputs

---

## §4 Implementation Phases

### §4.1 Phase 1 (Week 1-2): Dim 6+7 highest priority
- Dim 6 估值相对 — 量化 alpha 直接相关
- Dim 7 资金流 — moneyflow 已 partial implemented

### §4.2 Phase 2 (Week 3-4): Dim 2+4
- Dim 2 行业宏观 — regime context for V3 §16
- Dim 4 经营质量 — 长期 alpha source

### §4.3 Phase 3 (Week 5-6): Dim 3+8
- Dim 3 股东结构 — 北向 leading indicator
- Dim 8 公告与事件 — event-driven trading

### §4.4 Phase 4 (Week 7-8): Dim 5 治理
- 低频但高 alpha (退市风险 / 立案调查)
- 复杂数据源整合

### §4.5 Phase 5 (Week 9+): Aggregator + LLM integration
- FundamentalContextService 聚合 8 dims
- V3 §16 Bull/Bear 真消费
- Factor pipeline 候选 dimension

---

## §5 Effort Estimate

| Phase | Dims | Effort | Risk |
|---|---|---|---|
| 1 Dim 6+7 | 估值 + 资金流 | 1-2 weeks | LOW (data已 ingested) |
| 2 Dim 2+4 | 行业 + 经营 | 2 weeks | MEDIUM (new Tushare APIs) |
| 3 Dim 3+8 | 股东 + 公告 | 2 weeks | MEDIUM |
| 4 Dim 5 | 治理 | 1-2 weeks | HIGH (低频 + 复杂) |
| 5 Aggregator + LLM | All | 1 week | LOW |

**Total**: ~7-9 weeks for full 8-dim closure

---

## §6 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (design only)
- Phase B-2 (5-27 Wed): NOT prerequisite, NOT during first week
- Phase J Week 4+: Phase 1 (Dim 6+7)
- Phase K (~3 months post live): Phase 2-3
- Phase L: Phase 4-5

---

## §7 Iron Law Compliance

- Iron Law 11: IC 必须有可追溯入库 (8 dims 派生 factor 必走 factor_ic_history)
- Iron Law 17: All DB writes via DataPipeline
- Iron Law 24: Design ≤2 pages per dim (本 doc 8 dims aggregate)
- Iron Law 32: Service-layer 不 commit (8 new services 必合规)

---

**Maintained by**: CC autonomous (Plan v8 P1-26 design sediment, 2026-05-20 Day 1)
**Cross-ref**:
- V3 §3.3 FundamentalContext 8-dim design
- backend/app/services/fundamental_context_service.py (Dim 1 implemented)
- backend/qm_platform/news/ (NewsClassifier consumer pattern)
- V3 §16 Bull/Bear LLM debate (Dim consumer)
