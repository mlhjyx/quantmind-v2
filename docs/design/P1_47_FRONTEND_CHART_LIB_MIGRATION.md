# P1-47 Frontend Chart Library Consolidation Migration Plan

> **Plan v8 P1-47 closure prep** — design only, Frontend Phase H+/I multi-day implementation.
> **Source**: Plan v8 §21-24 Frontend redesign — dual chart libs (ECharts + Recharts) anti-pattern
> **Created**: 2026-05-20 Day 1 morning (Path B-1 active, autonomous-safe design sediment).

---

## §1 Background

**Audit finding (Plan v8 P1-47)**:
- Frontend uses **TWO** chart libraries simultaneously:
  - `echarts` + `echarts-for-react` (5+ pages)
  - `recharts` (3+ pages)
- Anti-pattern: duplicate dependencies, inconsistent UX, ~200KB bundle waste
- Decision needed: keep one, migrate other

---

## §2 Library Comparison

### §2.1 ECharts (Apache, Baidu fork)

**Pros**:
- 行业标准 in China (FinTech / Quant)
- Mature financial chart types (candlestick, depth chart, kline)
- Themes built-in (Apache version)
- Aggressive optimization (Canvas + WebGL)

**Cons**:
- Imperative API (less React-idiomatic)
- Larger bundle (~150KB minified)
- Steeper learning curve

**Current usage** (5+ pages):
- BacktestResults.tsx (kline + NAV curve)
- Dashboard.tsx (multi-line + bar)
- RiskMonitor.tsx (heatmap + gauge)
- FactorAnalysis.tsx (heatmap + scatter)
- SystemHealth.tsx (gauge cluster)

### §2.2 Recharts (React-first)

**Pros**:
- Declarative React API (`<Line dataKey="value">`)
- Smaller bundle (~85KB minified)
- TypeScript-native types
- Easier learning curve

**Cons**:
- Limited financial chart types (no candlestick built-in)
- Less mature for complex visualizations
- Limited theming flexibility

**Current usage** (6 files — code review MEDIUM fix 5-20, grep verified):
- `components/mining/GPPanel.tsx`
- `pages/Dashboard/EquityCurve.tsx`
- `pages/MarketData.tsx`
- `pages/MiningTaskCenter.tsx`
- `pages/Portfolio.tsx`
- `pages/RiskManagement.tsx`

---

## §3 Migration Decision

### §3.1 Decision: Consolidate to ECharts

**Rationale**:
- ECharts dominates the financial visualization market in China
- Candlestick + kline natively supported (critical for backtest visualization)
- 5+ pages already invested in ECharts (sunk cost favors consolidation)
- Recharts limited for complex risk heatmaps

**Migrate** (6 files — code review MEDIUM fix 5-20):
- `components/mining/GPPanel.tsx` (Recharts → ECharts)
- `pages/Dashboard/EquityCurve.tsx` (Recharts → ECharts)
- `pages/MarketData.tsx` (Recharts → ECharts)
- `pages/MiningTaskCenter.tsx` (Recharts → ECharts)
- `pages/Portfolio.tsx` (Recharts → ECharts)
- `pages/RiskManagement.tsx` (Recharts → ECharts)

**Remove**:
- `recharts` from package.json
- `recharts` type imports

---

## §4 Migration Approach

### §4.1 Pattern translation map

| Recharts | ECharts |
|---|---|
| `<LineChart>` | `option: { xAxis, yAxis, series: [{type: "line"}] }` |
| `<Line dataKey="value">` | `series[0].data = [...] from dataKey="value"` |
| `<XAxis dataKey="date">` | `xAxis.type = "category", xAxis.data = [...]` |
| `<Tooltip>` | `option.tooltip = { trigger: "axis" }` |
| `<Legend>` | `option.legend = { data: [...] }` |
| `<ResponsiveContainer>` | `useResize` hook → `chart.resize()` |

### §4.2 Helper hook

```tsx
// frontend/src/hooks/useECharts.ts
import { useEffect, useRef } from "react"
import * as echarts from "echarts"

export function useECharts(option: echarts.EChartsOption, deps: any[] = []) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (!ref.current) return
    if (!chartRef.current) {
      chartRef.current = echarts.init(ref.current)
    }
    chartRef.current.setOption(option)
    const onResize = () => chartRef.current?.resize()
    window.addEventListener("resize", onResize)
    return () => {
      window.removeEventListener("resize", onResize)
    }
  }, deps)

  return ref
}
```

### §4.3 Per-page migration steps

For each Recharts page:
1. Identify chart types used
2. Translate to ECharts option object
3. Replace `<LineChart>` → `<div ref={useECharts(option)} className="h-64 w-full" />`
4. Test responsive (resize) + theme alignment
5. PR with screenshot before/after

---

## §5 Implementation Phases

### §5.1 Phase 1 (Day 1): Setup
- Create `useECharts` hook + test
- Theme alignment (single ECharts theme for all pages)

### §5.2 Phase 2 (Day 2-5): Migrate 6 files
- `components/mining/GPPanel.tsx`
- `pages/Dashboard/EquityCurve.tsx`
- `pages/MarketData.tsx`
- `pages/MiningTaskCenter.tsx`
- `pages/Portfolio.tsx`
- `pages/RiskManagement.tsx`

### §5.3 Phase 3 (Day 4): Cleanup
- Remove `recharts` from package.json
- Remove `recharts` type imports
- Verify bundle size delta (-85KB expected)
- E2E test (Playwright) for migrated pages

### §5.4 Phase 4 (Day 5): Documentation
- DEV_FRONTEND_UI.md update (chart lib SSOT)
- Decision Log §5 sediment (ECharts vs Recharts decision)

---

## §6 Risk + Rollback

### §6.1 Risk
- Visual regression on migrated pages
- ECharts theme differs slightly from Recharts default
- Edge cases (sparkline minimal styling)

### §6.2 Mitigation
- Side-by-side screenshots before/after (manual review)
- Visual regression test (chromatic OR Playwright snapshot)
- Phase 3 incremental rollout (test 1 page at a time)

### §6.3 Rollback
- Per-page revert via git
- Keep `recharts` dep until all 3 pages confirmed PASS

---

## §7 Phase B-1 + Path B-2 Compatibility

- Phase B-1 (5-20 → 5-26): 0 implementation (design only)
- Phase B-2 (5-27 Wed): NOT prerequisite
- Phase H (Frontend redesign): Phase 1-4 candidate (Frontend W7+ scope)
- Phase J (post 5-27): user-facing if dashboards changed

---

## §8 Effort Estimate

| Phase | Effort | Dependencies |
|---|---|---|
| 1 Setup hook + theme | 1 day | None |
| 2 Migrate 6 files | 4-5 days | Phase 1 |
| 3 Cleanup + bundle verify | 1 day | Phase 2 |
| 4 Docs sediment | 0.5 day | Phase 3 |

**Total**: 6-8 days (code review MEDIUM fix — was understated as 4-5 days)

---

## §9 Iron Law Compliance

- Iron Law 22: docs/DEV_FRONTEND_UI.md update follow code change
- Iron Law 24: docs ≤2 pages MVP scope (本 doc 1 page)
- Iron Law 42: PR分级 — frontend/ MUST go through PR review

---

**Maintained by**: CC autonomous (Plan v8 P1-47 design sediment, 2026-05-20 Day 1)
**Cross-ref**:
- Plan v8 §21-24 Frontend redesign proposal
- docs/DEV_FRONTEND_UI.md (target update path)
- Decision Log §5 (decision recording)
