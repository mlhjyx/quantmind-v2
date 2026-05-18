# Frontend Design REVISED v2 — Incremental Business Refactor + AI Assist Integration

> **修正时机**: 2026-05-19 user 反馈 "A/B/C 偏离我的设计, 并不是将 adr/ll 都体现在 web, 而是业务相关的. 你可以在之前的 web 基础上进行改造, 但是 C 的 AI 辅助这个很有用, 可以弄到之前的 web 上"
>
> **方向修正** (vs `V3_AUDIT_FRONTEND_DESIGN_PROPOSAL.md` v1):
> - ❌ v1 错: "Control Center 单页命令中枢" + audit/ADR/LL metadata 在 web 上 + 从零重新设计 12 页 IA
> - ✅ v2 对: **现有 35 pages 业务功能 incremental refactor** + **AI 辅助 panel 集成 (来自 C variant)**
>
> **A/B/C HTML mockup status**: 保留为**探索性 artifact** (体现 LL-183 prevention safety patterns + Cmd+K command palette + AI chat panel pattern), 但**不作为新设计 canonical direction**. v2 是 canonical.

---

## §1 现有 Frontend 35 Pages 业务功能 Inventory

per Sidebar IA (`frontend/src/components/layout/Sidebar.tsx:35-75`):

### §1.1 总览 (Dashboard)
| Page | 业务功能 | 当前状态 | 改造优先级 |
|---|---|---|---|
| `Dashboard/index.tsx` | PT 总览 (NAV / 持仓 / pnl / alert) | 主入口, 7 sub-panels | **P0** — 加 AI 辅助 panel + 修 LL-183 后 env banner 不显眼 |
| `Dashboard/KPIGrid.tsx` | NAV/cash/持仓/Sharpe 4 KPI cards | ✅ active | P2 — 加实时 SSE |
| `Dashboard/EquityCurve.tsx` | NAV chart ECharts line | ✅ active | P2 — 加 drawdown shading |
| `Dashboard/HoldingsTable.tsx` | 持仓表格 | ✅ active (currently 0 持仓) | P3 |
| `Dashboard/AlertsPanel.tsx` | 风控告警列表 | partial | P1 — 接 V3 L0-L5 alert stream |
| `Dashboard/StrategiesPanel.tsx` | 当前策略状态 | partial | P2 |
| `Dashboard/FactorLibraryPanel.tsx` | 4 CORE active factor 缩略 | ✅ | P2 — 显示 dv_ttm warning |
| `Dashboard/MonthlyHeatmap.tsx` | 月度 pnl 热图 | ✅ active | P3 |
| `Dashboard/IndustryAndSystem.tsx` | 行业分布 + 系统状态 | partial | P2 — 加 Servy + Beat heartbeat |
| `Dashboard/AIPipelinePanel.tsx` | AI 闭环状态缩略 | partial | P1 — **直接关 AI 辅助 panel 集成点** |

### §1.2 交易 (Trading)
| Page | 业务功能 | 当前状态 | 改造优先级 |
|---|---|---|---|
| `Portfolio.tsx` | 持仓详细 (历史 + 当前 + recon diff) | ✅ active | P1 — recon diff view 缺失, 加 trade_audit 视图 |
| `RiskManagement.tsx` | 风控监控页 (实时 L0-L5 + 告警时间线) | partial | **P0** — 缺 L4 STAGED approve/reject button (P1-49 audit finding) + 元监控 panel |
| `Execution/index.tsx` | 交易执行页 (今日 signal + execute trigger) | ✅ active | **P0** — execute_phase trigger 应加 三锁 confirmation modal (P0-13 audit) |
| `Execution/ActionBtn.tsx` + `modals.tsx` | 执行按钮 + 确认弹窗 | ✅ active | P0 — 加 三锁 variant for CRIT ops (env_flip / emergency_close) |
| `PMS.tsx` | 阶梯利润保护 | 🟡 partial (PMS 已并入 V3 §3.1 ADR-010) | P2 — 简化或归并到 RiskManagement |
| `TradeExecution.tsx` | (legacy, 可能 superseded by Execution/) | ⚠️ 重叠 | P3 — 评估归并 / 删除 |

### §1.3 策略 (Strategy)
| Page | 业务功能 | 当前状态 | 改造优先级 |
|---|---|---|---|
| `StrategyWorkspace.tsx` | 策略编辑工作台 (因子组合 + 参数) | ✅ active | P2 — 加 promote to PT config 按钮 (P1-W2 audit) |
| `BacktestConfig.tsx` | 回测配置 (5yr/12yr/WF yaml) | ✅ active | P3 |
| `BacktestRunner.tsx` | 回测运行控制台 | ✅ active | P2 |
| `BacktestResults.tsx` | 回测结果展示 (paired bootstrap + Sharpe) | ✅ active | P2 — 加 OOS heterogeneity warning (5yr/12yr/WF 2.4× spread) |
| `StrategyLibrary.tsx` | 历史策略库 + 版本回滚 | partial | P2 — wire `/api/strategies/{id}/rollback` |

### §1.4 因子 (Factor)
| Page | 业务功能 | 当前状态 | 改造优先级 |
|---|---|---|---|
| `FactorLibrary.tsx` | 因子库列表 (213 cumulative) | ✅ active | P2 — 加 Gate G1-G10 status display (P1-34 audit) |
| `FactorLab.tsx` | 因子实验室 (新因子 propose + test) | ✅ active | P2 — 加 IC compute "Run Now" 按钮 + lifecycle force trigger |
| `FactorEvaluation.tsx` | 因子评估 (5 维 profile + IC decay + correlation) | ✅ active | P1 — 加 dv_ttm warning 显眼提示 + factor_lifecycle status badge |
| `MiningTaskCenter.tsx` | GP / LLM agent / brute-force mining | ✅ active | P2 — 加 GP closed-loop status (DEV_AI_EVOLUTION partial) |

### §1.5 AI (AI Pipeline)
| Page | 业务功能 | 当前状态 | 改造优先级 |
|---|---|---|---|
| `PipelineConsole.tsx` | AI 闭环控制台 (Idea/Factor/Eval Agent) | ✅ active | **P0** — **AI 辅助 panel 主集成点** (来自 C variant) + LLM cost MTD tracker (F-S7-001 P0) + RAG status (F-S7-005 P0) |
| `AgentConfig.tsx` | Agent 配置 (DeepSeek / V4-Flash/Pro routing) | ✅ active | P1 — 加 routing 真值显示 (94.5%/5.5%) + budget compliance |

### §1.6 系统 (System)
| Page | 业务功能 | 当前状态 | 改造优先级 |
|---|---|---|---|
| `PTGraduation.tsx` | PT 毕业评估 (paper → live cutover gate) | ✅ active | P1 — 加 LL-183 sediment + .env state always-visible banner |
| `SystemSettings.tsx` | 系统设置 (参数 / API token / Servy) | ✅ active | P1 — 加 Servy restart buttons + schtask toggle UI (per Section XI §41 matrix) |
| `MarketData.tsx` | 行情数据浏览 (klines / daily_basic) | ✅ active | P3 |
| `ReportCenter.tsx` | 报表中心 (daily summary / weekly L5) | ✅ active | P2 — 加 L5 Reflector weekly/monthly view |

### §1.7 Placeholders / Dead
| Page | 业务功能 | 当前状态 | 改造优先级 |
|---|---|---|---|
| `DashboardForex.tsx` | 外汇仪表盘 (deferred) | DEAD per DEV_FOREX.md DEFERRED | **删除** (P3 cleanup) |
| `ComingSoon.tsx` | 占位页 | placeholder | P3 — 评估删除 OR 改用作错误页 |

---

## §2 AI 辅助 Panel 集成方案 (来自 C variant, 业务向)

### §2.1 集成位置
- **主入口**: `frontend/src/pages/PipelineConsole.tsx` — AI 闭环页是天然 home
- **全局浮动 panel**: 右下角 floating button (Cmd+J 快捷) 可在任意页面打开 — 类似 ChatGPT in-app assistant pattern
- **嵌入式 panel**: 在特定 page (FactorEvaluation / RiskManagement / Dashboard) 嵌入"问 AI"按钮 — context-aware (page + 当前数据 自动传 prompt)

### §2.2 AI 辅助 业务能力 (重点是 业务, 不是 governance)

| 业务场景 | AI 辅助任务 | 实现路径 |
|---|---|---|
| **Dashboard 总览** | "今天 PT 表现如何?" → AI 综合 NAV/持仓/告警/signal drift → 300字摘要 | `POST /api/agent/chat?context=dashboard` |
| **RiskManagement** | "为什么 L4 STAGED 触发了?" → AI 读 risk_event_log + threshold context → 解释 + 建议 approve/reject | `POST /api/agent/chat?context=risk_event/{id}` |
| **FactorEvaluation** | "为什么 dv_ttm 在 warning?" → AI 读 factor_ic_history + lifecycle → IC 衰减原因 + 替代候选 | `POST /api/agent/chat?context=factor/{name}` |
| **Execution** | "撤掉 601398 的所有 order" → AI 解析 → tool_call cancelOrder | `POST /api/agent/chat` w/ tool schema |
| **BacktestResults** | "为什么 12yr Sharpe 0.36 但 WF 0.87?" → AI 分析 OOS heterogeneity + selection bias 风险 | `POST /api/agent/chat?context=backtest/{id}` |
| **MiningTaskCenter** | "推荐 3 个新因子方向" → AI 读 research-kb failed + active → propose 3 candidate | `POST /api/agent/chat?context=mining` |
| **StrategyWorkspace** | "这个新组合 vs CORE3+dv_ttm 哪个更稳?" → AI 跑 quick-sim → 报告 | `POST /api/agent/chat?context=strategy` |
| **PipelineConsole** | "本月 LLM cost 花了多少? 接近 $50 上限吗?" → AI 查 llm_cost_daily → MTD + 趋势 | `POST /api/agent/chat?context=llm_cost` |
| **News Stream** (新加) | "今天哪些新闻可能影响持仓?" → AI 读 news_classified + 持仓 → 关联分析 | `POST /api/agent/chat?context=news` |

### §2.3 AI Boundary (CRIT ops NEVER LLM-triggered)
- ❌ AI 不能直接触发: `execute_phase` / `env_flip` / `emergency_close_all_positions` / `pause_trading` global
- ⚠️ AI 可 compose 但 manual 三锁: L4 approve/reject / drift fix / threshold change
- ✅ AI 可直接执行: cancel single order / factor archive / generate report / explain only

### §2.4 实现组件

```typescript
// frontend/src/components/ai/AssistPanel.tsx (NEW)
interface AssistPanelProps {
  context: {
    page: string;      // 'dashboard' | 'risk' | 'factor' | ...
    entity_id?: string; // e.g. risk_event_id / factor_name
    data_snapshot?: object; // 当前页面数据
  };
  position: 'floating' | 'embedded' | 'page';
  onToolCall?: (tool: string, args: object) => void;
}
```

- 复用 PipelineConsole.tsx 已有 LLM 调用 infra
- 复用 NotificationSystem.tsx 已有 toast 模式
- 新 hook `useAssistantStream()` for SSE-based response streaming
- 复用 modals.tsx Confirm pattern for tool_call confirmations

---

## §3 Phase H REVISED — 业务-Driven Incremental Refactor (4-6 周)

### §3.1 Week 1: P0 业务必修
1. **Dashboard/index** + RiskManagement + Execution: add **always-visible env banner** (P0-23 audit, LL-183 prevention) — top-bar 5px 红/绿条
2. **Execution/modals**: add **三锁 ConfirmModal variant** for CRIT ops (execute trigger / env_flip / emergency_close) — P0-13/14
3. **RiskManagement**: wire `/api/risk/l4-approve/{id}` + L4 STAGED approve/reject buttons — P1-49
4. **PipelineConsole**: LLM cost MTD card + RAG status badge — F-S7-001/005 P0 visibility

### §3.2 Week 2-3: AI 辅助 Panel 集成
1. Build `AssistPanel.tsx` component (floating + embedded modes)
2. Backend: `POST /api/agent/chat` streaming + tool schema (filtered by risk tier)
3. Integrate to PipelineConsole + Dashboard + FactorEvaluation + RiskManagement (4 entry points)
4. Cmd+J global shortcut to summon floating panel

### §3.3 Week 4: 业务 gap 修补
1. Portfolio: add **trade_audit + recon diff view** (current QMT vs DB)
2. FactorEvaluation: add **dv_ttm warning 显眼提示** + factor_lifecycle status badge
3. BacktestResults: add **OOS heterogeneity warning** (5yr 0.61 / 12yr 0.36 / WF 0.87 2.4× spread alert)
4. SystemSettings: wire Servy restart buttons + schtask toggle UI

### §3.4 Week 5-6: 清理 + Polish
1. Drop `DashboardForex.tsx` + `TradeExecution.tsx` legacy (DEV_FOREX deferred + Execution superseded)
2. Replace Recharts usage → ECharts (drop dual chart libs, ~250KB savings)
3. Drop `socket.io-client` (no server) → native EventSource for SSE
4. Move admin token from localStorage → httpOnly cookie (P0-22 audit)

### §3.5 NOT in Scope (deferred to Phase H+1)
- Audit Trail / LL/ADR browser (user explicitly said NOT business-relevant)
- L5 Reflector Reports page (could be in ReportCenter sub-tab if needed)
- System Health full dashboard (current SystemSettings sufficient)
- News Stream new page (could be in Dashboard sub-tab if user wants)

---

## §4 现有 35 Pages 改造统计

| 优先级 | 数量 | 重点页面 |
|---|---|---|
| **P0** (Week 1, business+safety critical) | 4 | Dashboard/index, RiskManagement, Execution/index, PipelineConsole |
| **P1** (Week 2-4, business gap fill) | 8 | Portfolio, AlertsPanel, AIPipelinePanel, FactorEvaluation, PTGraduation, SystemSettings, AgentConfig, modals.tsx |
| **P2** (Week 4-5, business enhance) | 14 | StrategyWorkspace, BacktestResults, FactorLibrary, FactorLab, MiningTaskCenter, etc. |
| **P3** (Week 6, polish or defer) | 7 | MarketData, MonthlyHeatmap, HoldingsTable, etc. |
| **删除** (cleanup) | 2 | DashboardForex, ComingSoon (评估), TradeExecution (评估归并) |

---

## §5 vs v1 (`V3_AUDIT_FRONTEND_DESIGN_PROPOSAL.md`) Delta

| Aspect | v1 (deprecated direction) | **v2 (canonical)** |
|---|---|---|
| Approach | 12 page from-scratch redesign | **现有 35 pages incremental refactor** |
| Focus | Control Center + audit/ADR/LL governance | **业务功能 (PT/Risk/Factor/Strategy/News)** |
| AI assist | Variant C standalone mockup | **集成到 PipelineConsole + Dashboard + 浮动 panel** |
| Effort | 11 weeks (full rewrite) | **4-6 weeks (incremental)** |
| Risk | High (35 pages re-implement) | Low (refactor in place) |
| User feedback | "偏离我的设计" | **"在之前的 web 基础上进行改造"** |

---

## §6 A/B/C HTML Mockup 处置

- **保留** 3 个 HTML 文件 (~132 KB total) 作探索性 artifact
- **Annotate** at top of each: "**EXPLORATORY ONLY** — not canonical direction per user feedback 2026-05-19"
- **C 的有用元素提取**: AI chat panel pattern + tool_call boundary + auto-explain panels — 沉淀到本 v2 doc §2.4 (`AssistPanel.tsx` design)
- **不删除**: 作为 "what NOT to do (full from-scratch redesign)" 教学 artifact

---

## §7 关联文档

- v1 deprecated direction: `V3_AUDIT_FRONTEND_DESIGN_PROPOSAL.md`
- Design Spec (claude.ai/design feedable): `V3_AUDIT_FRONTEND_DESIGN_SPEC.md` (also需要修正 — 业务焦点而非 Control Center)
- Section XI Backend Op → UI: `V3_AUDIT_S9_UX_CONTROL_PLANE.md` (仍然 valid — 32 ops 矩阵是 业务 ops, Section XI 不偏离, 只是不要新建 Control Center 单页, 改成在现有 Execution + SystemSettings 中加入这些 ops)
- A/B/C exploratory artifacts: `docs/audit/frontend_mockups/{A,B,C}.html`

---

**End Frontend Design REVISED v2.** 焦点 = 业务功能 incremental refactor of existing frontend/src/ + AI 辅助 panel 集成.
