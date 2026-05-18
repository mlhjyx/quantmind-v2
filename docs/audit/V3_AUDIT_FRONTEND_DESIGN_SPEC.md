# QuantMind-V2 Frontend Design Specification (Phase 4-bis Step A, NEW v7)

> ⚠️ **PARTIAL CORRECTION 2026-05-19** — Design tokens (Part 2) + Component lib (Part 3) + Real-time strategy (Part 7) + Auth (Part 11) **仍然 valid**. Pages-by-page layout (Part 4 "12 page IA from scratch") **deprecated** — user feedback "在之前的 web 基础上进行改造". Refactor existing 35 pages instead.
> **Canonical direction**: `V3_AUDIT_FRONTEND_DESIGN_REVISED_v2.md` §1 existing-pages inventory + §3 Phase H REVISED.
> Spec doc 可仍用 feed claude.ai/design 网页 for **component library + design tokens**, but **NOT 整页 12-page IA**.
>
> **Purpose**: This spec is **feedable to https://claude.ai/design** (web tool) for full frontend mockup generation, OR usable directly by `oh-my-claudecode:designer` agent
> **Source**: Synthesis of `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` + `V3_AUDIT_S9_UX_CONTROL_PLANE.md` + backend inventory (132 API endpoints / 36 services / Redis Streams) + user persona (single-user, full-time quant developer, expects Team Lead-style proactive UI)
> **User decision (post-audit)**: choose path 1 (user feeds claude.ai/design web) / path 2 (CC spawns designer agent for HTML mockup) / path 3 (hybrid both)

---

## Part 1 — Project Context (Brief)

QuantMind-V2 is a personal A股 quant trading system (single user, full-time quant developer). Stack: FastAPI + Celery + Redis + TimescaleDB + Python backend, React 18 + TypeScript + Tailwind 4 + Zustand frontend. Currently paused (cash ¥993,520.66 / 0 持仓) post LL-183 incident 2026-05-18.

**Core problem to solve**: User explicitly stated "**所有后端操作都需要能在前端进行操作, 交互式**". Currently CC (Claude Code CLI) is the primary actor; frontend is a passive dashboard. New design must invert: **frontend = primary control plane, CC = automation backend**.

---

## Part 2 — Design Tokens

### 2.1 Color Palette

**Theme**: Dark, glass-morphism aesthetic (preserve current `frontend/src/theme/GlassCard.tsx` style).

```typescript
// Primary palette
export const colors = {
  // Background layers
  bg: {
    base: '#0a0e1a',       // Page background
    surface: '#111827',    // Card background
    elevated: '#1f2937',   // Modal / popover
    glass: 'rgba(31, 41, 55, 0.6)' // Glass blur overlay
  },
  // Brand
  primary: {
    50: '#ecfeff',
    500: '#06b6d4',  // Cyan-500 (主品牌)
    600: '#0891b2',
    700: '#0e7490',
  },
  // Status — semantic
  success: '#10b981', // emerald-500 — PASS / 多头 / 涨
  warning: '#f59e0b', // amber-500 — WARN / 待审批
  danger: '#ef4444',  // red-500 — FAIL / 空头 / 跌
  info: '#3b82f6',    // blue-500 — INFO / 中性
  // Trading colors (Chinese convention: 红涨绿跌 reversed from West)
  bullish: '#ef4444', // red (涨) — Chinese A-share
  bearish: '#10b981', // green (跌) — Chinese A-share
  // Text
  text: {
    primary: '#f9fafb',    // gray-50
    secondary: '#9ca3af',  // gray-400
    muted: '#6b7280',      // gray-500
    inverse: '#111827'     // dark text on light bg
  },
  // Border
  border: {
    subtle: 'rgba(75, 85, 99, 0.3)',
    default: 'rgba(75, 85, 99, 0.5)',
    strong: '#374151'
  }
};
```

### 2.2 Typography

```typescript
export const typography = {
  fontFamily: {
    sans: '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif',
    mono: '"JetBrains Mono", "Consolas", monospace', // For code / numbers
  },
  fontSize: {
    xs: '0.75rem',   // 12px — meta info
    sm: '0.875rem',  // 14px — body
    base: '1rem',    // 16px — base
    lg: '1.125rem',  // 18px — section header
    xl: '1.25rem',   // 20px — page title
    '2xl': '1.5rem', // 24px — KPI numbers
    '3xl': '1.875rem' // 30px — main NAV display
  },
  fontWeight: {
    normal: 400,
    medium: 500,
    semibold: 600,
    bold: 700
  }
};
```

### 2.3 Spacing + Sizing

```typescript
export const spacing = {
  0: '0',
  1: '0.25rem',  // 4px
  2: '0.5rem',   // 8px
  3: '0.75rem',  // 12px
  4: '1rem',     // 16px
  5: '1.25rem',  // 20px
  6: '1.5rem',   // 24px
  8: '2rem',     // 32px
  10: '2.5rem',  // 40px
  12: '3rem',    // 48px
  16: '4rem',    // 64px
};

export const borderRadius = {
  sm: '0.25rem',  // 4px
  md: '0.5rem',   // 8px
  lg: '0.75rem',  // 12px
  xl: '1rem',     // 16px
  full: '9999px'  // Pill
};
```

### 2.4 Shadows + Glass

```typescript
export const shadow = {
  sm: '0 1px 2px 0 rgb(0 0 0 / 0.05)',
  md: '0 4px 6px -1px rgb(0 0 0 / 0.1)',
  lg: '0 10px 15px -3px rgb(0 0 0 / 0.1)',
  glass: '0 8px 32px 0 rgba(0, 0, 0, 0.37)',
  glow: '0 0 20px rgba(6, 182, 212, 0.3)' // Cyan glow for primary actions
};

export const glass = {
  backdropFilter: 'blur(12px) saturate(180%)',
  background: 'rgba(31, 41, 55, 0.6)',
  border: '1px solid rgba(255, 255, 255, 0.08)'
};
```

---

## Part 3 — Component Library Spec

### 3.1 Button

```typescript
interface ButtonProps {
  variant: 'primary' | 'secondary' | 'danger' | 'ghost' | 'success';
  size: 'sm' | 'md' | 'lg';
  loading?: boolean;
  disabled?: boolean;
  icon?: ReactNode;
  children: ReactNode;
  onClick?: () => void;
  safety?: 'low' | 'med' | 'high' | 'crit'; // NEW: Safety tier for ops
}
```

**Variants**:
- `primary` (cyan-500 background, white text) — main actions
- `secondary` (gray border, transparent bg) — secondary actions
- `danger` (red-500 background) — destructive ops (cancel, force-reset)
- `ghost` (no background) — text-like buttons
- `success` (emerald-500) — confirm actions

**Safety integration**:
- `safety="crit"` → renders with red glow + auto-opens ConfirmModal 三锁 on click
- `safety="high"` → opens ConfirmModal w/ typed reason
- `safety="med"` → opens basic ConfirmModal
- `safety="low"` → fires immediately + toast undo (10s)

### 3.2 ConfirmModal (三锁 variant for CRIT ops)

```typescript
interface ConfirmModalProps {
  title: string;
  message: string;
  safetyTier: 'low' | 'med' | 'high' | 'crit';
  // For CRIT tier:
  requiredPhrase?: string; // e.g. "EXECUTE-PAPER-20260518"
  cooldownSeconds?: number; // e.g. 5
  envCheckRequired?: 'paper' | 'live'; // assert env match
  // For HIGH tier:
  requiredReason?: boolean; // free-text reason field
  requireTokenReEnter?: boolean; // admin token re-enter
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}
```

**CRIT tier flow**:
1. Modal opens
2. Show current env state: `[PAPER] LIVE_TRADING_DISABLED=true`
3. If `envCheckRequired` mismatch → show RED warning + disable confirm
4. If `requiredPhrase` set → show input field, validate exact match
5. Cooldown timer counts down (e.g. 5s) — confirm button disabled during
6. After confirm: API call + DingTalk push + audit_log immutable + toast

### 3.3 Form

```typescript
interface FormFieldProps {
  label: string;
  name: string;
  type: 'text' | 'number' | 'select' | 'checkbox' | 'date' | 'multi-select';
  required?: boolean;
  validation?: ZodSchema; // Zod-based validation
  placeholder?: string;
  helperText?: string;
  error?: string;
}
```

### 3.4 Table

```typescript
interface TableColumnDef<T> {
  key: keyof T;
  header: string;
  sortable?: boolean;
  filterable?: boolean;
  render?: (row: T) => ReactNode;
  width?: string;
  align?: 'left' | 'right' | 'center';
}

interface TableProps<T> {
  data: T[];
  columns: TableColumnDef<T>[];
  pagination?: { pageSize: number };
  selection?: 'single' | 'multi' | false;
  onRowClick?: (row: T) => void;
  // Real-time
  streaming?: boolean; // Append new rows from SSE
}
```

### 3.5 Chart (ECharts wrapper)

```typescript
type ChartType = 'line' | 'bar' | 'candlestick' | 'heatmap' | 'sankey' | 'scatter';

interface ChartProps {
  type: ChartType;
  data: ChartData; // Type-specific data shape
  height: number;
  realtime?: { stream: string; field: string }; // SSE binding
  title?: string;
  toolbox?: boolean; // ECharts toolbox (download / zoom)
}
```

### 3.6 AlertBanner (Always-visible env state — anti LL-183)

```typescript
interface EnvBannerProps {
  env: 'paper' | 'live';
  liveTradingDisabled: boolean;
  ptTopN: number;
  qmtAccountId: string;
}
```

**Rendering**:
- `env=paper && liveTradingDisabled=true` → GREEN banner: `[PAPER] safe — LIVE_TRADING_DISABLED=true / PT_TOP_N=5 / QMT=81001102`
- `env=live && liveTradingDisabled=false` → RED banner pulse animation: `⚠ [LIVE] hot — LIVE_TRADING_DISABLED=false / PT_TOP_N={N} / verify intentional`
- Mismatch (e.g. `env=live && liveTradingDisabled=true`) → AMBER + alert icon

### 3.7 AuditLogPanel

```typescript
interface AuditLogEntry {
  id: string;
  timestamp: ISO8601String;
  actor: string; // 'CC' | 'user' | 'beat:<task>' | 'schtask:<name>'
  action: string;
  target?: string;
  metadata?: Record<string, unknown>;
  severity: 'info' | 'warn' | 'error' | 'crit';
}
```

### 3.8 StreamingTickView (SSE consumer)

```typescript
interface StreamingTickViewProps {
  endpoint: string; // e.g. '/api/streams/market'
  pattern?: string; // Filter pattern
  bufferSize?: number; // Default 1000
  onMessage: (event: { type: string; data: unknown; ts: number }) => void;
  fallbackPolling?: number; // ms — fall back to polling if SSE fails
}
```

### 3.9 CommandPalette (Cmd+K)

```typescript
interface Command {
  id: string;
  label: string;
  hotkey?: string;
  safety: 'low' | 'med' | 'high' | 'crit';
  category: string;
  action: () => void;
}
```

---

## Part 4 — Page-by-Page Layout (12 Pages, Role-Tabbed IA)

### IA Structure

```
A. OPERATOR (生产, 每日)
   1. Control Center (NEW)        — 单页命令中枢 (Section XI)
   2. PT Dashboard                 — NAV/PnL/持仓/今日交易 + live tick
   3. Risk Monitor                 — V3 L0-L5 state + alert timeline
   4. Trade Audit                  — trade_log + recon diff + fill detail

B. RESEARCHER (研究)
   5. Factor Explorer              — 库/IC 趋势/画像/生命周期
   6. Strategy Lab                 — multi-factor combine + WF simulate
   7. Backtest Viewer              — regression/WF/比较
   8. Signal Explorer              — 今天 signal + 历史 + drift

C. AUDITOR (审计)
   9. Audit Trail                  — LL/ADR/sediment 文档浏览
   10. L5 Reflector Reports        — weekly/monthly/event
   11. System Health               — Servy + Beat + Schtask + DB freshness

D. ALL
   12. News Stream                 — 6 sources + classified + sentiment
```

### Page 1: Control Center (NEW v6 CRITICAL)

**Purpose**: Single-page operator command center. Inverts CC-only ops to UI buttons.

**Layout**:
```
┌──────────────────────────────────────────────────────────────────────┐
│ [EnvBanner: [PAPER] safe — LIVE_TRADING_DISABLED=true ...]            │
├──────────────────────────────────────────────────────────────────────┤
│ Control Center                                          [⌘K palette] │
├──────────────────────────────────────────────────────────────────────┤
│  ┌─ Trading Ops ─────────────────┐  ┌─ Data Ops ─────────────────┐   │
│  │ [Trigger Signal] (LOW)        │  │ [Pull Tushare] [Pull QMT]  │   │
│  │ [Execute] (CRIT)              │  │ [Force Factor Lifecycle]   │   │
│  │ [Cancel Stale Orders] (LOW)   │  │ [Run Reconciliation] (MED) │   │
│  │ [Emergency Close] (CRIT)      │  │                            │   │
│  └───────────────────────────────┘  └────────────────────────────┘   │
│                                                                      │
│  ┌─ System Ops ──────────────────┐  ┌─ Audit Ops ────────────────┐   │
│  │ [Servy Restart: 4 svcs] (MED) │  │ [LL Sediment +] (LOW)      │   │
│  │ [Schtask Manager] (MED)       │  │ [ADR Create +] (LOW)       │   │
│  │ [Env Flip paper↔live] (CRIT)  │  │ [Backup Run] (LOW)         │   │
│  │ [Beat Status]                 │  │                            │   │
│  └───────────────────────────────┘  └────────────────────────────┘   │
│                                                                      │
│  Recent Activity (last 50, SSE)                                      │
│  [AuditLogPanel]                                                     │
└──────────────────────────────────────────────────────────────────────┘
```

**Action behavior**:
- LOW: 1-click + toast undo 10s
- MED: ConfirmModal basic
- HIGH: ConfirmModal + typed reason + admin token re-enter
- CRIT: ConfirmModal **三锁** (env match + typed phrase + cooldown)

**API bindings**: per §41 matrix (32 ops mapped, 19 to be added).

### Page 2: PT Dashboard

**Purpose**: Real-time PT state (NAV / 持仓 / 今日交易 / live tick).

**Layout**:
```
┌──────────────────────────────────────────────────────────────────────┐
│ [EnvBanner]                                                          │
├──────────────────────────────────────────────────────────────────────┤
│ PT Dashboard                                          [Refresh: 30s] │
├──────────────────────────────────────────────────────────────────────┤
│ ┌─KPI Cards (4)─────────────────────────────────────────────────────┐│
│ │ NAV ¥993,520.66 ▼-0.05% │ Cash ¥993,520 │ 持仓 0 │ Sharpe 0.8659 ││
│ └────────────────────────────────────────────────────────────────────┘│
│ ┌─NAV Chart (ECharts line + drawdown shading) ─────────────────────┐│
│ │  ┌─ Last 30 days ────────────────────────────────────────────────┐││
│ │  │                                                                │││
│ │  │  ╲╱╲                                                            │││
│ │  │     ╲╱╲╱                                                        │││
│ │  └──────────────────────────────────────────────────────────────┘ ││
│ └────────────────────────────────────────────────────────────────────┘│
│ ┌─持仓 Table──────────┐ ┌─今日交易 Live Feed (SSE)───────────────────┐│
│ │ Code | Qty | Cost  │ │ 09:31:02 buy 600519.SH 100@1530.50 ✓       ││
│ │ (empty)            │ │ 09:31:04 buy 601398.SH 6700@7.41 ✓         ││
│ │                    │ │ (SSE stream from /api/streams/trade)        ││
│ └────────────────────┘ └─────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

**API bindings**:
- `GET /api/dashboard/nav` — NAV history
- `GET /api/portfolio/current` — 持仓
- `GET /api/streams/trade` (SSE) — live trade feed

### Page 3: Risk Monitor

**Purpose**: V3 L0-L5 risk state visualization + alert timeline + 元告警.

**Layout**:
```
┌──────────────────────────────────────────────────────────────────────┐
│ Risk Monitor                                                         │
├──────────────────────────────────────────────────────────────────────┤
│ V3 Risk Framework State (Live)                                        │
│ ┌─L0 News────┐ ┌─L1 Realtime─┐ ┌─L2 Regime───┐ ┌─L3 Threshold──┐    │
│ │ 6 src OK   │ │ 10 rules OK │ │ Bull/Neutral│ │ 6 SLA OK      │    │
│ └────────────┘ └─────────────┘ └─────────────┘ └───────────────┘    │
│ ┌─L4 STAGED ──────────────────┐ ┌─L5 Reflector─┐ ┌─元监控 ──────┐    │
│ │ Pending: 0                  │ │ Last: Sun    │ │ 7 rules OK   │    │
│ │ [Approve all] [Reject all]  │ │ Next: Sun 19 │ │              │    │
│ └─────────────────────────────┘ └──────────────┘ └──────────────┘    │
│                                                                      │
│ Alert Timeline (Last 24h)                            [Severity ▼]   │
│ ┌─time────┬─rule───────────────┬─severity─┬─action───────────────┐  │
│ │ 18:30   │ DataQualityCheck   │ P0       │ [View] [Acknowledge] │  │
│ │ 18:45   │ RiskFrameworkHlth  │ P0       │ [View] [Acknowledge] │  │
│ └─────────┴────────────────────┴──────────┴──────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

**API bindings**:
- `GET /api/risk/framework-state` — L0-L5 + 元监控 state
- `GET /api/risk/alerts?severity=&since=` — Alert timeline
- `POST /api/risk/l4-approve/{id}` — Approve L4 STAGED
- `POST /api/risk/l4-recovery/{id}` — Recover

### Page 4: Trade Audit

**Purpose**: trade_log + reconciliation diff + fill detail (audit-grade).

**Layout**:
```
┌──────────────────────────────────────────────────────────────────────┐
│ Trade Audit                                                          │
├──────────────────────────────────────────────────────────────────────┤
│ [Date Range Picker] [Filter: side/code/strategy] [Export CSV]        │
│                                                                      │
│ trade_log (immutable view)                                            │
│ ┌─ts───────┬─code──────┬─side──┬─qty──┬─price──┬─cost──┬─audit─┐    │
│ │ ...      │ ...       │ ...   │ ...  │ ...    │ ...   │ ✓     │    │
│ └──────────┴───────────┴───────┴──────┴────────┴───────┴───────┘    │
│                                                                      │
│ Reconciliation Diff (DB vs xtquant query_stock_positions)             │
│ ┌─code──────┬─DB qty──┬─xtquant qty─┬─diff──┬─action────┐           │
│ │ (empty — both 0)                                       │           │
│ └────────────────────────────────────────────────────────┘           │
└──────────────────────────────────────────────────────────────────────┘
```

### Page 5: Factor Explorer

**Purpose**: 因子库 / IC 趋势 / 画像 / 生命周期.

**Layout**:
```
┌──────────────────────────────────────────────────────────────────────┐
│ Factor Explorer                                                      │
├──────────────────────────────────────────────────────────────────────┤
│ ┌─Sidebar: factor list────────┐  ┌─Main: factor detail─────────────┐│
│ │ [Search 213 factors]        │  │ Factor: turnover_mean_20         ││
│ │ ── CORE Active (4) ──        │  │ Status: ✅ active                ││
│ │ • turnover_mean_20 ✅        │  │ Direction: -1                    ││
│ │ • volatility_20 ✅           │  │                                  ││
│ │ • bp_ratio ✅                │  │ IC History (last 90d, ECharts)   ││
│ │ • dv_ttm ⚠️                  │  │ ┌────────────────────────────────┐││
│ │ ── Warning (12) ──           │  │ │       ╱╲                       │││
│ │ ...                          │  │ │   ╱╲╱   ╲                      │││
│ │ ── Deprecated (8) ──         │  │ │  ╱       ╲╲                    │││
│ │                              │  │ └────────────────────────────────┘││
│ │                              │  │                                  ││
│ │                              │  │ Profile (5 维):                  ││
│ │                              │  │ • IC: 0.0234 (top quintile)      ││
│ │                              │  │ • Decay rate: 18%                ││
│ │                              │  │ • Monotonicity: 0.78             ││
│ │                              │  │ • Cost feasibility: PASS         ││
│ │                              │  │ • Redundancy: 0.32 (vs reversal) ││
│ │                              │  │                                  ││
│ │                              │  │ Gate G1-G10:                     ││
│ │                              │  │ ✅✅✅✅✅✅✅✅✅✅ (10/10)            ││
│ └─────────────────────────────┘  └──────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

### Page 6: Strategy Lab

**Purpose**: Multi-factor combine simulator + WF preview.

### Page 7: Backtest Viewer

**Purpose**: Regression / WF / 比较 charts.

### Page 8: Signal Explorer

**Purpose**: 今天 signal + 历史 + drift detection.

### Page 9: Audit Trail

**Purpose**: LL / ADR / sediment 文档 browser + diff view.

**Layout**:
```
┌──────────────────────────────────────────────────────────────────────┐
│ Audit Trail                                                          │
├──────────────────────────────────────────────────────────────────────┤
│ ┌─Tabs────────────────────────────────────────────────────────────┐  │
│ │ [LL (~160)] [ADR (67)] [STATUS_REPORT (31)] [docs/audit (122)]   │  │
│ └─────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│ ┌─List view (with reverse-chrono + filters)────────────────────────┐ │
│ │ # LL-183 2026-05-18 — dry-run silent NOT-GATING (P0)              │ │
│ │ # LL-182 2026-05-18 — QMT 5-axis fix                              │ │
│ │ # LL-181 2026-05-18 — Beat death lesson                           │ │
│ │ ...                                                                │ │
│ └────────────────────────────────────────────────────────────────────┘│
│                                                                      │
│ ┌─Detail view (markdown render + diff to prev version)──────────────┐│
│ │ LL-183 content...                                                 ││
│ └────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
```

### Page 10: L5 Reflector Reports

**Purpose**: weekly / monthly / event reflection viewer.

### Page 11: System Health

**Purpose**: Servy + Beat + Schtask + DB freshness dashboard.

**Layout**:
```
┌──────────────────────────────────────────────────────────────────────┐
│ System Health                                                         │
├──────────────────────────────────────────────────────────────────────┤
│ ┌─Servy Services (4)──────────────────────────────────────────────┐  │
│ │ ● QuantMind-FastAPI       Running    1.2 GB    [Restart] [Logs] │  │
│ │ ● QuantMind-Celery        Running    700 MB    [Restart] [Logs] │  │
│ │ ● QuantMind-CeleryBeat    Running    300 MB    [Restart] [Logs] │  │
│ │ ● QuantMind-QMTData       Running    400 MB    [Restart] [Logs] │  │
│ └─────────────────────────────────────────────────────────────────┘  │
│ ┌─Beat Schedule (32 entries) ─────────────────────────────────────┐  │
│ │ [Schedule visualization timeline]                                │  │
│ └─────────────────────────────────────────────────────────────────┘  │
│ ┌─Schtask (19, 4 Disabled)─────────────────────────────────────────┐  │
│ │ ● QuantMind_DailyExecute    Disabled (LL-183)   [Enable] [Info] │  │
│ │ ● QuantMind_DailyIC         Ready   LastResult=0  [Disable]     │  │
│ │ ⚠ QuantMind_DataQualityCheck Ready  LastResult=1  [Diagnose]    │  │
│ │ ⚠ QuantMind_RiskFrameworkHealth Ready LastResult=1 [Diagnose]   │  │
│ │ ... (15 more)                                                    │  │
│ └─────────────────────────────────────────────────────────────────┘  │
│ ┌─DB Health──────────────────────────────────────────────────────┐  │
│ │ factor_values: 840M rows, last INSERT 18 days ago                │  │
│ │ trade_log: last entry 2026-04-17 (PT paused since)               │  │
│ │ daily_basic: latest 2026-05-18 ✅                                │  │
│ │ klines_daily: latest 2026-05-18 ✅                               │  │
│ └─────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

### Page 12: News Stream

**Purpose**: 6 sources / classified / sentiment.

---

## Part 5 — User Flow (Trader / Researcher / Auditor 3 Journey)

### 5.1 Trader Daily Journey

```
[08:50 SH Preflight] → Control Center: check QMT status / schtask / Beat
   ↓
[09:15] → PT Dashboard: pre-market signal preview
   ↓
[09:30 Market Open] → PT Dashboard: live tick view (SSE)
   ↓
[09:31] → Control Center: [Trigger Execute] (CRIT 三锁) OR auto via schtask
   ↓
[09:30-15:00 Monitor] → PT Dashboard: live fill feed + P&L tick
   ↓
[15:00 Close] → Auto-generated summary
   ↓
[15:40] → Trade Audit: reconciliation diff view
   ↓
[17:35] → System Health: PT audit report
   ↓
[Evening] → Audit Trail: LL sediment form + ADR create
```

### 5.2 Researcher Factor Onboarding Journey

```
[Idea] → Factor Explorer: search existing factors
   ↓
[IC Compute] → Factor Explorer: select factor → run --compute-ic button
   ↓
[Profile V2] → Factor Explorer: 5维 profile display
   ↓
[Gate G1-G10] → Factor Explorer: gate result display
   ↓
[Backtest] → Backtest Viewer: paired bootstrap p<0.05 test
   ↓
[Onboard] → Strategy Lab: add to PT config
   ↓
[Lifecycle] → Factor Explorer: track active → warning → deprecated
```

### 5.3 Auditor Incident Response Journey

```
[Incident Detected] → Risk Monitor: view alert timeline + root cause
   ↓
[Investigate] → Trade Audit: trade_log + recon diff
   ↓
[Mitigate] → Control Center: cancel orders / pause trading / emergency_close
   ↓
[Sediment] → Audit Trail: LL form + ADR create
   ↓
[Verify Fix] → System Health: Servy / Beat / Schtask state
```

---

## Part 6 — Interactive Spec (CC Ops → Frontend Button)

Per `V3_AUDIT_S9_UX_CONTROL_PLANE.md` §41 — 32 operations matrix. Key safety tiers:

| Op | Safety | Confirmation flow |
|---|---|---|
| signal_phase trigger | LOW | 1-click + toast undo 10s |
| execute_phase | **CRIT** | Modal + env match check + typed `EXECUTE-PAPER-{date}` + 5s cooldown |
| env_flip paper↔live | **CRIT** | Modal + DingTalk push + audit immutable + 30s cooldown |
| emergency_close_all | **CRIT** | Modal + typed `CONFIRM-LIQUIDATE-{date}` + 5s cooldown |
| Servy restart | MED | Modal + per-service select |
| schtask enable/disable | MED | Modal + reason |
| L4 STAGED approve/reject | HIGH | Modal + typed reason |
| pull_tushare force | LOW | 1-click + toast |
| LL sediment | LOW | Form + 1-click submit |

---

## Part 7 — Real-Time Strategy

### 7.1 SSE Endpoints (Backend需新加)

| Endpoint | Stream binding | Frequency |
|---|---|---|
| `/api/streams/market` | qm:market:* Redis | tick (sub-second during market hours) |
| `/api/streams/trade` | qm:fill:executed | per-fill event |
| `/api/streams/risk` | qm:risk:l1_triggered + qm:risk:l4 | per-event |
| `/api/streams/news` | qm:news:* | per-news ingest |
| `/api/streams/system` | qm:beat:heartbeat + qm:servy:* | 60s |
| `/api/streams/audit` | audit_log table tail | per-action |

### 7.2 Polling Fallback

If SSE fails → fall back to polling 5s for high-priority / 30s for low-priority.

### 7.3 Client-Side Buffer

- `bufferSize: 1000` per stream
- Older events auto-evicted FIFO
- Persistent storage: only critical alerts to localStorage

---

## Part 8 — API Endpoint Binding (New Endpoints Needed)

Per §41 matrix, **~15 new endpoints** required:

```typescript
// Trading ops
POST /api/paper-trading/signal-trigger
POST /api/paper-trading/execute-trigger  // CRIT
POST /api/execution/cancel-stale
POST /api/system/execution-mode  // CRIT env_flip

// System ops
POST /api/system/services/{name}/restart
PUT /api/system/schtasks/{name}
GET /api/system/celery/schedule
POST /api/system/backup/run

// Data ops
POST /api/data/pull/tushare
POST /api/data/pull/baostock
POST /api/factors/lifecycle/run

// Audit ops
POST /api/audit/lessons  // LL sediment
POST /api/audit/adrs
GET /api/audit/timeline  // unified LL+ADR+sediment chrono

// AI ops (Phase 5+)
POST /api/agent/chat  // streaming
```

### 8.1 Existing Endpoints Used

Per `V3_AUDIT_S2_INVENTORY.md` §4.1 — 132 existing endpoints, frontend already consumes ~33 mutation endpoints.

---

## Part 9 — Accessibility, Responsive, Mobile

### 9.1 Accessibility
- WCAG 2.1 AA target
- Keyboard navigation (tab order + focus indicators)
- aria-* labels
- Screen reader compatible
- Color contrast ≥ 4.5:1

### 9.2 Responsive
- Min width 1280px (desktop primary)
- Tablet 768-1280px: 折叠 sidebar
- Mobile <768px: emergency-only view (alerts + emergency_close button)

### 9.3 Mobile Strategy (Minimal)
- Single-user usage → desktop primary
- Mobile: read-only dashboard + emergency abort button
- PWA optional Phase 6+

---

## Part 10 — Performance Budget

| Metric | Target |
|---|---|
| TTI (Time to Interactive) | < 1.5s on LAN |
| Page transition | < 200ms |
| Real-time tick lag | < 500ms (SSE) |
| Initial bundle | < 500 KB gzipped (excluding charts) |
| Charts lazy-load | YES |
| Code splitting | per-page chunk |

---

## Part 11 — Authentication & RBAC

### 11.1 Current (Anti-Pattern, P0-22)
- Admin token in localStorage
- Single bearer
- No rotation
- XSS vulnerable

### 11.2 New Design
- **httpOnly cookie** for session token
- **CSRF token** in header on mutations
- **TOTP step-up** for CRIT ops (`execute_phase`, `env_flip`, `emergency_close`)
- **2 admin tokens**:
  - `researcher_token` for read + factor / backtest ops
  - `operator_token` for CRIT ops, stored separately + requires re-auth

### 11.3 Audit Trail
- Every authenticated UI action → `audit_log` immutable
- No DELETE on log
- DingTalk push on CRIT

---

## Part 12 — Build Stack

```json
{
  "framework": "React 18.3 + TypeScript 5.7 + Vite 6",
  "styling": "Tailwind CSS 4.1",
  "state": "Zustand 5",
  "data": "@tanstack/react-query 5",
  "router": "react-router-dom 7",
  "charts": "ECharts 5 (only — drop Recharts)",
  "realtime": "Native EventSource API (drop socket.io)",
  "forms": "react-hook-form + zod",
  "i18n": "skip (single Chinese user)",
  "test": "Vitest + RTL"
}
```

---

## Part 13 — Feeding to claude.ai/design

To use this spec at https://claude.ai/design:

1. Copy entire Part 2 (Design Tokens) → paste as design system input
2. Copy Part 3 (Component Library) → paste as component spec
3. Copy Part 4 (Page Layouts) → paste page-by-page as separate inputs
4. Copy relevant Part 5/6/7 (Flow / Interactive / Real-time) sections per page
5. Generated React + Tailwind code → download zip
6. CC Phase H integration: place under `frontend/src/__new_redesign/` + incremental migration
7. Each page validated against existing `/api/*` endpoints

---

## Part 14 — Heuristic #18 Alternative Design Paths

Beyond claude.ai/design web tool:

1. **Path 1 (User-driven, this spec)**: User feeds spec to claude.ai/design web → download code → CC integrates
2. **Path 2 (CC-autonomous)**: `oh-my-claudecode:designer` agent generates HTML mockup (A/B/C variants) directly. See `V3_AUDIT_FRONTEND_DESIGN_PROPOSAL.md`.
3. **Path 3 (Hybrid recommended)**: Both — designer agent for quick HTML mockup audit-time (0 touchpoint); spec doc preserved for user to feed claude.ai/design post-audit for polished version.

---

**End Frontend Design Spec. ~900 lines.** Feedable to claude.ai/design for full Tailwind+React mockup generation. CC Phase H integration sequenced per `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md` §24 roadmap.
