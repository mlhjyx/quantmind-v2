# Frontend Design v3 — Concrete File-Level Refactor + AI Assist Integration (2026-05-19)

> **iteration trail**: v1 (12-page from-scratch IA) deprecated → v2 (incremental refactor + AI assist canonical direction) → **v3 (this doc — concrete file-level plan + deep audit findings)**
>
> **Source**: Synthesis of (a) Deep code audit subagent report 2026-05-19, (b) `docs/DEV_FRONTEND_UI.md` D2=PROGRESSIVE 决议 (12 页保留 + AI 助手保留 + 补运维), (c) `docs/archive/FRONTEND_INVENTORY.md` historical 6473 LOC baseline, (d) `V3_AUDIT_FRONTEND_DESIGN_REVISED_v2.md` (canonical direction).
>
> **Replaces**: v1 + v2 as **canonical implementation guide** for Phase H Frontend Refactor.

---

## §1 Deep Audit Summary

### §1.1 Real Frontend LOC (2026-05-19 verified)
- 35 pages = 9697 lines
- 25 components = 2205 lines  
- 12 API files = 2112 lines
- 4 stores = 156 lines
- 4 hooks ~ 345 lines
- **Total ~14,500 LOC**
- High-frequency 10 业务页 ~ 4400 LOC (30% of total)

### §1.2 Top 3 业务 Critical Findings

1. **EnvStateBanner 完全缺失** (P0) — 用户打开任何页面都不知道当前 paper/live/disabled. **LL-183 root cause UI 化**: 没有任何 visual 显示 .env state, 即使 LIVE_TRADING_DISABLED=false + EXECUTION_MODE=live 用户也看不出.
2. **L4 / Kill-switch / Circuit Breaker 无 UI** (P0) — backend API 全存在 (`/api/risk/state/default` 等), 6 ops 完全无前端 entry. Section XI §41 gap 4/32 ops 直接 LL-183 相关.
3. **风险等级=hardcoded "LOW"** (P1) `RiskManagement.tsx:118` — Silent UI lie. 跟 backend `/risk/state/default` (dashboard.ts:71 已拉) 不通.

### §1.3 Top 3 Technical Debt
- **双轨样式系统** — 414 处 inline `style={{...}}` + 116 处 Tailwind `text-slate-*`. Page 切换时视觉 jump.
- **2 套 axios 实例** — `apiClient` 完整 interceptor + `dashboard.ts:11` 独立 `axios.create()` bypass. 6 处 raw bypass 跳过 401/429/503 toast handler.
- **4 个通知系统并行** — `NotificationContext` (P0-P3) + `NotificationPanel.tsx` (wired sidebar) + `NotificationSystem.tsx` (281 行 dead code) + `notificationStore.ts` (toast). 死代码 281 行 + 概念混淆.

### §1.4 黄金模板

`Execution/index.tsx` (677 lines) — v3 设计 templated pattern:
- ActionBtn + ConfirmModal + AdminTokenModal gate
- danger CONFIRM 输入字符串验证 (≥5 字 reason)
- useMutations cross-page invalidate
- 5/10/15s polling + `enabled: qmtStatus?.state === "connected"` gate
- toast 3s auto-dismiss

**这套泛化 → 新 SafetyControl 页 + ConfirmModal 抽到 `components/ui/` 全局复用**.

---

## §2 5 NEW Components Spec (Phase H Week 1-2)

### §2.1 `components/safety/EnvStateBanner.tsx` (NEW, ~80 lines)

```typescript
interface EnvStateBannerProps {
  // 来自 backend /api/system/env-state endpoint
  mode: 'paper' | 'live' | 'disabled';
  liveTradingDisabled: boolean;
  qmtAccountId: string;
  ptTopN: number;
  dingTalkEnabled: boolean;
  l4AutoEnabled: boolean;
  lastUpdated: string; // ISO timestamp
}
```

**Rendering**:
- `mode=paper && liveTradingDisabled=true` → **GREEN** banner: `[PAPER] safe — LIVE_TRADING_DISABLED=true / PT_TOP_N=5 / QMT=81001102`
- `mode=live && liveTradingDisabled=false` → **RED + pulse 2s** banner: `⚠ [LIVE] hot — LIVE_TRADING_DISABLED=false / PT_TOP_N={N} / verify intentional`
- Mismatch (`mode=live + liveTradingDisabled=true`) → **AMBER + alert icon** banner: `[MIXED] ⚠️ env contradiction`
- `mode=disabled` (post-shutdown like 4-29 清仓) → **GRAY** banner: `[MAINTENANCE] 0 持仓 since {date}`

**Integration**: Insert in `Layout.tsx` 顶部固定 (above TopBar), all 35 pages 自动继承.

### §2.2 `components/safety/SafetyControlPanel.tsx` (NEW, ~250 lines)

业务功能 (6 ops gap from §4):
- `/risk/state/default` circuit breaker state visualization (L0-L4 ladder)
- L4 STAGED approve/reject buttons (call `/api/risk/l4-approve/{approval_id}`)
- L4 force-reset (call `/api/risk/force-reset/{strategy_id}` w/ 三锁)
- env mode toggle (call `POST /api/system/execution-mode` w/ 三锁 + DingTalk push) **NEW endpoint required**
- LIVE_TRADING_DISABLED toggle (same)
- Schtask enable/disable (factor_lifecycle / DailyExecute / etc) **NEW endpoint**

**集成**: 
- **Option A** (推荐 per audit Finding #2 Alt B): RiskManagement 第 4 tab "紧急控制" — 复用现有 tab 系统, 不新增 Sidebar 入口
- **Option B**: 新独立 `/safety` 路由 + Sidebar 系统组下加入口

### §2.3 `components/ai/AssistPanel.tsx` (NEW, ~300 lines)

```typescript
interface AssistContext {
  page: 'dashboard' | 'risk' | 'factor' | 'execution' | 'strategy' | 'backtest' | 'pipeline';
  entity_id?: string;
  data_snapshot?: object;
}

interface AssistPanelProps {
  context: AssistContext;
  mode: 'floating' | 'embedded' | 'inline';
  shortcut?: string; // 'Cmd+J' for floating
  toolWhitelist?: string[]; // CRIT ops 不在 LLM allow list
}
```

**集成 4 entry points** (existing placeholder + new):
1. `StrategyWorkspace.tsx:217-239` — 已 placeholder (4 disabled button + "Sprint 1.18 即将上线"). Wire 真 API → `POST /api/ai/strategy-assist`
2. `FactorLab.tsx:343-371` — 已 placeholder + 输入框 + 显示 `API: POST /api/ai/factor-assist`. Wire 真 API
3. **NEW** `PipelineConsole.tsx` 第 5 tab "AI 助手" — embedded variant
4. **NEW** Layout.tsx 全局 floating button (Cmd+J) — context auto-detect 当前 page

**AI Boundary** (CRIT ops NEVER LLM-triggered):
- ❌ Block list: `execute_phase / env_flip / emergency_close_all / pause_trading_global / L4 force-reset`
- ⚠️ Compose but manual: L4 approve/reject / drift fix / threshold change
- ✅ Direct: cancel single order / factor archive / report generate / explain-only

### §2.4 `components/ui/ConfirmModal.tsx` (PROMOTED from Execution/modals.tsx, ~150 lines)

抽现有 Execution/modals.tsx 的 ConfirmModal + AdminTokenModal + DriftPreviewModal 到全局 `components/ui/`. 4 safety tiers per `V3_AUDIT_S9_UX_CONTROL_PLANE.md` §44:

```typescript
type SafetyTier = 'LOW' | 'MED' | 'HIGH' | 'CRIT';

interface ConfirmModalProps {
  title: string;
  message: string;
  safetyTier: SafetyTier;
  // CRIT-specific:
  requiredPhrase?: string;  // e.g. "EXECUTE-PAPER-20260519"
  envCheckRequired?: 'paper' | 'live';
  cooldownSeconds?: number;  // e.g. 5
  // HIGH-specific:
  requiredReason?: boolean;
  reasonMinLength?: number;  // ≥5 chars per Execution pattern
  requireAdminToken?: boolean;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}
```

**替代 3 处 native window.prompt/alert**:
- `PipelineConsole.tsx:252` reject reason `window.prompt` → ConfirmModal HIGH variant
- `StrategyWorkspace.tsx:76` `alert("请输入策略名称")` → 用 react-hot-toast (已存在)
- `StrategyWorkspace.tsx:84` 同 → 同上

### §2.5 `components/safety/ShutdownBanner.tsx` (NEW, ~60 lines)

Per Dashboard finding "0 持仓 + cash ¥993,520 不显示 reason". Reads from new `GET /api/system/shutdown-notice` (拉 `docs/audit/SHUTDOWN_NOTICE_2026_04_30.md` 摘要):

```
[MAINTENANCE] 2026-04-29 清仓决议 by user
  - 17 股 emergency_close (4-29 10:43:54)  
  - 1 股 GUI sell (4-30, 688121.SH 4500 股)
  - 当前 cash ¥993,520.66, 0 持仓
  - 重启 gate prerequisite: SHUTDOWN_NOTICE §9
[查看完整 notice →]
```

**集成**: Dashboard/index.tsx 顶部 (env banner 下方), 仅在 `mode=disabled` 时显示.

---

## §3 Page-by-Page Refactor Plan (10 高频业务页, P0/P1 优先)

### §3.1 P0 Week 1 (业务 safety critical)

#### 3.1.1 `Layout.tsx` (106 → ~140 lines) — Add EnvStateBanner
- Insert `<EnvStateBanner />` 顶部, 覆盖 35 pages
- New API binding: `GET /api/system/env-state` (NEW endpoint, returns `mode/liveTradingDisabled/qmtAccountId/ptTopN/dingTalk/l4Auto/lastUpdated`)
- 5s refetch (env 变化 immediate visibility)
- LL-183 prevention complete

**Effort**: 4h (component + Layout 接入 + API endpoint)

#### 3.1.2 `Dashboard/index.tsx` (304 → ~320 lines) — Add ShutdownBanner + Remove dead code
- Insert `<ShutdownBanner />` between EnvStateBanner and KPIGrid (only when `mode=disabled`)
- Remove `rtPortfolio` dead code (line 30 destructure, 0 usage)
- Replace 6 raw `axios.get` calls → unified `apiClient` (per finding #5)
- Wire AssistPanel floating button (Cmd+J)

**Effort**: 6h

#### 3.1.3 `RiskManagement.tsx` (304 → ~360 lines) — Add SafetyControlPanel as 4th tab
- New tab "紧急控制" (4th, after 风控总览/压力测试/限额监控)
- Wire `/api/risk/state/default` (dashboard.ts:71 already exists, just consume)
- Wire `/api/risk/l4-approve/{id}` approve/reject buttons (HIGH tier ConfirmModal)
- Replace hardcoded "LOW" badge (line 118) → real `circuit_breaker_state.level`
- Remove double try fallback (line 60-66, hide mode info problem) → use EnvStateBanner mode instead

**Effort**: 12h

#### 3.1.4 `Execution/index.tsx` (677 → no change baseline, add)
- Extract ConfirmModal + AdminTokenModal + DriftPreviewModal → `components/ui/` (per §2.4)
- Keep all existing functionality
- Add `triggerRebalance` 今天 vs 上次调仓 diff preview (per finding #11)

**Effort**: 6h (mostly extraction, low risk)

### §3.2 P1 Week 2-3 (AI Assist + 业务 gap)

#### 3.2.1 `PipelineConsole.tsx` (633 → ~720 lines) — Add AI Assist 5th tab
- Existing 4 tabs (状态流程/待审批/运行历史/AI决策日志) + NEW 5th tab "AI 助手"
- Embedded `<AssistPanel context={{page:'pipeline'}} mode="embedded" />`
- Replace `window.prompt` (line 252) → ConfirmModal HIGH tier with reason field
- Remove `EMPTY_STATUS` mock placeholder (line 49-59) — fail-loud instead

**Effort**: 10h

#### 3.2.2 `StrategyWorkspace.tsx` (249 → ~280 lines) — Wire AI助手 placeholder
- 4 disabled buttons (line 217-239) → enabled, wire `POST /api/ai/strategy-assist`
- Replace `alert("请输入策略名称")` (line 76+84) → react-hot-toast
- Add commit/version diff (defer to Phase I if scope creep)

**Effort**: 8h

#### 3.2.3 `FactorLab.tsx` (375 → ~410 lines) — Wire AI助手 placeholder
- Lines 343-371 placeholder → enabled, wire `POST /api/ai/factor-assist`
- Add AST 相似度 (G9) + 经济机制 (G10 铁律 13) 显示
- Wire `mining_knowledge` UI 入口

**Effort**: 12h

#### 3.2.4 `FactorEvaluation.tsx` (189 → ~250 lines) — Make 5 操作按钮 work
- Currently 5 buttons (编辑/添加/导出/丢弃/入库) all `no-op` (line 86-92)
- Wire each to corresponding `/api/factors/{name}/*` endpoint
- Add IC backfill 入口 (call `/api/factors/backfill-ic`)
- Add dv_ttm warning 显眼提示 + factor_lifecycle status badge
- Replace hardcoded MetricCard 阈值 (line 117-119) → 从 IRONLAWS.md 配置 SSOT

**Effort**: 10h

#### 3.2.5 `Portfolio.tsx` (306 → ~340 lines) — Fix 假数据 + add recon diff
- Fix `days=0` 假数据 (line 49) — call backend new `/api/positions/holding-days`
- Add recon diff view (DB vs xtquant query_stock_positions)
- Better empty state when 0 持仓 (show shutdown date + cash + reason via ShutdownBanner already)

**Effort**: 8h

### §3.3 P2 Week 4-5 (业务 enhance)

#### 3.3.1 `BacktestResults.tsx` (745 → no change baseline, add)
- Add **OOS heterogeneity warning** (5yr 0.61 / 12yr 0.36 / WF 0.87 2.4× spread alert)
- 涉及 audit P0-11 survivorship bias UI flag

**Effort**: 4h

#### 3.3.2 `BacktestRunner.tsx` (327)
- Add cancel confirmation modal (current: no confirm, dangerous)
- Fix 后台运行 button (current: just navigate away)

**Effort**: 4h

#### 3.3.3 `PMS.tsx` (227 lines)
- Wire history view (call backend `/pms/history` if exists)
- 评估是否归并到 RiskManagement (per finding #12)

**Effort**: 6h evaluation + decide

#### 3.3.4 `SystemSettings.tsx` (648)
- Add Servy restart buttons (NEW endpoint `/api/system/services/{name}/restart`)
- Add schtask toggle UI
- Add prompt eval 评估按钮 (跟 `quantmind-v3-prompt-eval-iteration` skill 接通)

**Effort**: 14h

#### 3.3.5 `AgentConfig.tsx` (289)
- Add prompt diff/版本/rollback (per finding 缺 V3 §3.2 NewsClassifier prompt eval)
- Add v4-flash/v4-pro routing 真值 display (94.5%/5.5% per Subagent I supplement)

**Effort**: 8h

### §3.4 P3 Week 6 (cleanup + polish)

- Drop `DashboardForex.tsx` (DEV_FOREX deferred, 39 lines stub)
- Drop `TradeExecution.tsx` legacy (superseded by Execution/index.tsx) 
- Drop `components/NotificationSystem.tsx` (281 lines dead code per audit Finding #9)
- Drop `socket.io-client` dep (no server, replace with EventSource SSE) — per v2 §23.3
- Move admin token from localStorage → httpOnly cookie (P0-22 audit)

**Effort**: 8h cleanup

---

## §4 Migration Strategy — 双轨 + 4 通知 + 2 axios 技术债

### §4.1 双轨样式系统 (414 inline / 116 Tailwind)

**Strategy**: **不一次性 migrate** (50h 风险 > 收益).

- **NEW pages + components**: 强制 Tailwind + GlassCard
- **EXISTING pages 修 P0/P1**: 顺手 migrate (e.g. RiskManagement Week 1 顺手转 GlassCard)
- **EXISTING pages P2/P3**: 接受现状, 标 `// LEGACY STYLE — migrate when refactor` comment

### §4.2 4 通知系统并行

**Strategy**: 合并到 1.5 套.
- **保留**: `NotificationContext` (P0-P3 持久通知) + `react-hot-toast` (transient)
- **删除**: `components/NotificationSystem.tsx` (281 lines dead code) + `store/notificationStore.ts` (43 lines, 用 toast 替代)
- Sidebar `NotificationPanel.tsx` (171 lines) 继续 wire 到 NotificationContext

**Effort**: 4h cleanup

### §4.3 2 套 axios

**Strategy**: 全 migrate to `apiClient`.
- Remove `dashboard.ts:11` `axios.create({baseURL: "/api"})` → use `apiClient`
- 6 raw `axios.get` calls in Dashboard/Portfolio/Risk → all use `apiClient`
- Add lint rule (ESLint `no-restricted-syntax` for `axios.create`) prevent regression

**Effort**: 3h

### §4.4 三套 real-time 体制并行

**Strategy**: Tiered consolidation.
- **高频** (portfolio / orders / market tick): SSE (NEW endpoints `/api/streams/*`)
- **中频** (factor health / risk overview / pipeline status): react-query refetchInterval 5-30s
- **低频** (system settings / agent config): lazy (manual refetch)
- **删除**: 7 处 raw `setInterval` files → migrate to react-query OR SSE
- **保留**: 3 处 socket.io WS (mining/backtest/pipeline progress) since they work

**Effort**: 16h gradual migration (Phase I)

---

## §5 Phase H Roadmap REVISED (4-6 weeks)

| Week | Focus | Effort |
|---|---|---|
| **Week 1** | Layout EnvStateBanner + Dashboard ShutdownBanner + RiskManagement SafetyControl tab + Execution ConfirmModal extraction | ~28h |
| **Week 2** | PipelineConsole 5th tab + StrategyWorkspace AI wire + FactorLab AI wire | ~30h |
| **Week 3** | AssistPanel floating + 4 entry points + Cmd+J shortcut + 4 backend endpoints (POST /api/ai/{domain}-assist) | ~30h |
| **Week 4** | FactorEvaluation 5 操作按钮 + Portfolio 假数据修 + BacktestResults OOS warning | ~22h |
| **Week 5** | SystemSettings Servy/schtask UI + AgentConfig prompt版本 + PMS history | ~28h |
| **Week 6** | Cleanup: dead code (NotificationSystem.tsx + DashboardForex + TradeExecution) + axios unify + 双轨 P2 pages 顺手 migrate | ~16h |
| **Total** | | **~154h** (4-6 weeks, 30h/week solo dev) |

---

## §6 Top 15 Audit Findings → v3 Action Mapping

| Finding | Severity | v3 Action | Week |
|---|---|---|---|
| #1 EnvStateBanner 完全缺失 | P0 | §2.1 + §3.1.1 Layout 接入 | Week 1 |
| #2 L4/kill-switch 无 UI | P0 | §2.2 SafetyControlPanel + §3.1.3 RiskManagement 4th tab | Week 1 |
| #3 双轨样式 414/116 | P0 | §4.1 渐进 migrate strategy | All weeks |
| #4 AssistPanel placeholder | P1 | §2.3 + §3.2.1/2/3 (PipelineConsole + StrategyWorkspace + FactorLab) | Week 2-3 |
| #5 6 raw axios bypass | P1 | §4.3 全 migrate | Week 6 |
| #6 风险等级=hardcoded | P1 | §3.1.3 wire `/risk/state/default` | Week 1 |
| #7 cron + Sprint badge hardcoded | P2 | wire or delete (low priority) | Week 5 |
| #8 window.prompt/alert 3 处 | P2 | §2.4 ConfirmModal 抽取 + replace | Week 1+2 |
| #9 NotificationSystem.tsx dead | P3 | §4.2 删除 | Week 6 |
| #10 dashboard.ts 自建 axios | P2 | §4.3 同 #5 | Week 6 |
| #11 days=0 / todayPnl=0 假数据 | P2 | §3.2.5 Portfolio backend api 补 holding_days | Week 4 |
| #12 PMS 三层硬编码 | P2 | §3.3.3 wire `/pms/history` 或归并 | Week 5 |
| #13 factor_evaluation 5 button no-op | P2 | §3.2.4 wire 5 ops endpoints | Week 4 |
| #14 三套 real-time 并存 | P2 | §4.4 tiered consolidation | Phase I |
| #15 shutdown 状态不显示 | P1 | §2.5 ShutdownBanner + §3.1.2 Dashboard 接入 | Week 1 |

---

## §7 NEW Backend API Endpoints Required (per v3 frontend)

| Endpoint | Purpose | Used by |
|---|---|---|
| `GET /api/system/env-state` | Returns mode/liveTradingDisabled/qmtAccountId/ptTopN/dingTalk/l4Auto + lastUpdated | EnvStateBanner |
| `POST /api/system/execution-mode` (CRIT 三锁) | env flip paper↔live | SafetyControlPanel |
| `POST /api/system/services/{name}/restart` (MED) | Servy restart | SystemSettings |
| `PUT /api/system/schtasks/{name}` (MED) | schtask enable/disable | SystemSettings |
| `GET /api/system/shutdown-notice` | Returns SHUTDOWN_NOTICE summary | ShutdownBanner |
| `POST /api/ai/strategy-assist` | LLM assist for StrategyWorkspace | AssistPanel |
| `POST /api/ai/factor-assist` | LLM assist for FactorLab | AssistPanel |
| `POST /api/ai/risk-assist` | LLM assist for RiskManagement | AssistPanel |
| `POST /api/ai/exec-assist` | LLM assist for Execution | AssistPanel |
| `POST /api/agent/chat` (streaming) | Generic LLM streaming chat | AssistPanel floating |
| `GET /api/positions/holding-days` | Real holding days per code | Portfolio (fix days=0) |
| `POST /api/factors/backfill-ic` | Manual IC backfill trigger | FactorEvaluation |
| `GET /api/streams/portfolio` (SSE) | Real-time portfolio updates | Portfolio + Dashboard |
| `GET /api/streams/risk` (SSE) | Real-time risk events | RiskManagement |
| `GET /api/streams/market` (SSE) | Real-time market tick | Dashboard TopBar |

**Total**: 15 NEW endpoints. Phase H Week 1-3 frontend work overlaps backend addition.

---

## §8 v2 → v3 Delta Summary

| Aspect | v2 (canonical direction) | **v3 (this doc, concrete plan)** |
|---|---|---|
| Approach | "Incremental refactor + AI assist" (high-level) | **Concrete file-level edits + new component spec** |
| Page coverage | 35 pages listed | **10 高频 active 页 P0/P1 + 4 P2 + 2 删除** |
| New components | "AssistPanel" mentioned | **5 components spec (EnvStateBanner + SafetyControlPanel + AssistPanel + ConfirmModal + ShutdownBanner)** |
| Roadmap | 4-6 weeks (vague) | **6 weeks × 30h/week breakdown by file + ~154h total** |
| Backend API requirements | (none specified) | **15 NEW endpoints listed** |
| Migration strategy | (none specified) | **§4 双轨 + 4 通知 + 2 axios + real-time tiered plan** |
| Deep audit findings | (not yet done) | **Top 15 findings → v3 action mapping (§6)** |
| Black gold template | (not mentioned) | **Execution/index.tsx 黄金模板 generalize to SafetyControlPanel** |
| User concern fulfilled | "业务相关 + 在之前 web 改造" | **业务向 (无 audit/ADR/LL 元数据) + 现有 35 pages 文件级 edit list** |

---

## §9 Cross-Reference

- v1 (deprecated): `V3_AUDIT_S5_FRONTEND_REDESIGN_PROPOSAL.md`
- v2 (canonical direction): `V3_AUDIT_FRONTEND_DESIGN_REVISED_v2.md`
- **v3 (this doc, canonical plan)**: `V3_AUDIT_FRONTEND_DESIGN_v3.md`
- Design spec component lib still valid: `V3_AUDIT_FRONTEND_DESIGN_SPEC.md` Part 2-3 (design tokens + components)
- Section XI 32 ops matrix: `V3_AUDIT_S9_UX_CONTROL_PLANE.md` §41
- Deep audit raw report: (this doc §1 condenses it)
- DEV_FRONTEND_UI.md D2=PROGRESSIVE 决议: 12 页保留 + AI 助手保留 + 补运维 — **v3 与此决议一致**

---

**End Frontend Design v3.** 14500 LOC baseline / 10 高频页 P0+P1 refactor / 5 new components / 15 backend endpoints / ~154h effort / 4-6 weeks Phase H. Ready for user 决议 specific implementation start.
