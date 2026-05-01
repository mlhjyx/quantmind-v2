# Frontend Review — 完整 audit (sustained frontend/01)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 7 WI 4 / frontend/02
**Date**: 2026-05-01
**Type**: 评判性 + Frontend 完整深审 (sustained frontend/01 重大盲点 F-D78-196)

---

## §1 Frontend 完整真测 (CC 5-01 实测)

### 1.1 src/api/ — 真 12 files

```
agent.ts / backtest.ts / client.ts / dashboard.ts / execution.ts /
factors.ts / mining.ts / pipeline.ts / QueryProvider.tsx / realtime.ts /
strategies.ts / system.ts
```

**真值**: **12 API 模块** (vs backend 128 routes — F-D78-122 sustained 漂移 verify candidate)

### 1.2 src/store/ — 真 4 stores (Zustand)

```
authStore.ts / backtestStore.ts / miningStore.ts / notificationStore.ts
```

**真值**: 4 Zustand stores (auth + backtest + mining + notification)

### 1.3 src/pages/ — 真 17+ pages (含 Dashboard subdivision)

```
Dashboard/ (10 panels: AIPipelinePanel / AlertsPanel / EquityCurve / FactorLibraryPanel / HoldingsTable / IndustryAndSystem / KPIGrid / MonthlyHeatmap / StrategiesPanel + index)
DashboardAstock.tsx + DashboardForex.tsx
Execution/ (ActionBtn + index + modals)
AgentConfig.tsx + BacktestConfig.tsx + BacktestResults.tsx + BacktestRunner.tsx
ComingSoon.tsx
```

**真值**: ~17+ pages + Dashboard 10 panels = 27+ tsx pages real

### 1.4 src/components/ — 真 4+ subdirs

```
agent / backtest / factor (含 evaluation) / layout
```

### 1.5 package.json 13 deps 真测

```
@tanstack/react-query 5.95
axios 1.7
echarts 5.6 + echarts-for-react 3.0
lucide-react 0.344
react 18.3 + react-dom 18.3
react-router-dom 7.13 ⚠️ (大版本 7, sprint period sustained CLAUDE.md "React Router" 沉淀)
recharts 3.8 ⚠️ (大版本 3, sprint period sustained sustained)
socket.io-client 4.8
zustand 5.0
```

**真测 finding**:
- F-D78-214 [P3] react-router-dom 7.13 + recharts 3.8 + zustand 5 大版本依赖, sprint period sustained sustained 0 sustained 度量, candidate breaking change 风险

---

## §2 Frontend ↔ Backend API 调用契约 真测

实测真值:
- Frontend 12 api modules vs Backend 128 routes (snapshot/05 §1)
- Frontend 12 modules cover ~12+ domains (agent / backtest / client / dashboard / execution / factors / mining / pipeline / realtime / strategies / system + QueryProvider)
- 真 1:N (12 API modules : 128 routes) 候选: 平均每模块 ~10 routes, 真 enforce 候选 0 sustained 度量

候选 finding:
- F-D78-215 [P1] Frontend 12 API modules vs Backend 128 routes 真 1:N 契约 enforcement 0 sustained 度量, candidate frontend 候选 0 cover routes (sustained F-D78-203 sustained)

---

## §3 Forex Dashboard 真状态

实测真值:
- DashboardForex.tsx 真存 (sprint period sustained sustained CLAUDE.md "外汇模块 ⏳ DEFERRED" sustained sustained)
- 真 Forex 路径 0 sustained 度量 (sprint period sustained 沉淀 sustained 但 真生产 0 active candidate)

候选 finding:
- F-D78-216 [P3] Forex Dashboard 真存 vs sprint period sustained "DEFERRED" disconnect, 真生产 candidate 0 active

---

## §4 Realtime + WebSocket 候选

实测真值:
- realtime.ts in src/api (真存)
- socket.io-client 4.8 dep (真存)
- 但 backend WebSocket 真 0 endpoint (snapshot/05 §1 F-D78-123 sustained)

**🔴 finding**:
- **F-D78-217 [P1]** Frontend realtime.ts + socket.io-client 4.8 dep sustained vs Backend WebSocket 真 0 endpoint = **frontend ↔ backend disconnect** (frontend 期望 ws / backend 0 ws), sprint period sustained sustained 沉淀 sustained 但真测 candidate disconnect

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-214 | P3 | Frontend 大版本依赖 (router 7.13 + recharts 3.8 + zustand 5) breaking change 风险候选 |
| F-D78-215 | P1 | Frontend 12 API modules vs Backend 128 routes 真 1:N 契约 enforcement 0 sustained |
| F-D78-216 | P3 | Forex Dashboard 真存 vs sprint period "DEFERRED" disconnect |
| **F-D78-217** | **P1** | Frontend realtime.ts + socket.io-client 4.8 vs Backend WebSocket 真 0 endpoint = disconnect |

---

**文档结束**.
