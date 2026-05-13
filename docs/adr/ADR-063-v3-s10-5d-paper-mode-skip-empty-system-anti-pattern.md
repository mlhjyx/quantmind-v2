# ADR-063: V3 §S10 5d Paper-Mode Operational Kickoff — Skip in Empty-System State

**Status**: committed
**Date**: 2026-05-13 (cumulative with PR #319+#320+#321; sediment PR pending)
**Type**: V3 Tier A S10 operational decision — Gate A §L10.1 footnote amendment
**Parents**: ADR-062 (S10 setup) + ADR-027 (V3 design SSOT) + LL-098 X10 (反 silent forward-progress)
**Children**: Tier B planning + RiskBacktestAdapter scope decision (T1.5 or Tier B)

## §1 背景

Plan §A S10 acceptance per V3 §15.4: "5d paper-mode 跑通 + 触发率 / 误报率 / 漏报 / STAGED cancel 率 / LLM cost / 元监控 KPI 实测; 4 项 (P0 误报率<30% / L1 P99<5s / L4 STAGED 0 失败 / 元监控 0 P0)".

Code infrastructure (ADR-062) + Beat wire (PR #319) + column-name/case bug fixes (PR #320) + C1 synthetic toolkit (PR #321) landed cumulative this session (2026-05-13). With the chain validated 1:1 against synthetic data (PR #320 verify report = 3/4 PASS + 1 deferred), the natural question is "now wait 5 wall-clock trading days (5-14 → 5-20) for natural Beat fire to populate risk_metrics_daily, then run verify CLI".

The empirical reality check (本 session ~20:30 实测):
- ❌ `XtQuantTickSubscriber` 未启动 → 0 真 tick 流入 → `RealtimeRiskEngine` 0 触发 → 0 risk_event_log INSERT
- ❌ 0 持仓 (PT 4-29 清仓 sustained, cash=¥993,520.66) → 即使 tick 流接入,9 RealtimeRiskRule 大部分 dormant (positions-dependent)
- ❌ L4 STAGED 路径需 risk_event 触发上游决议 → 0 execution_plans INSERT
- ❌ LLM dev 期免费 provider → llm_cost_daily.cost_usd_total=0 across all 7 active days

**含义**: 5-14 → 5-20 natural fire 窗口的 verify 报告**信息熵 ≈ 0**:
- 项 1 P0 误报率 = trivially 0% (因 0 P0 alerts at all)
- 项 2 L1 latency P99 = `<no data>` (column intentionally deferred per ADR-062 §2.5; instrumentation 待 S5 sub-PR 后续 / Tier B 落地)
- 项 3 STAGED FAILED count = trivially 0 (因 0 plans at all)
- 项 4 元告警 P0 = trivially 0 (元告警 channel 待 §13.3 落地)

3/4 trivial-pass 不是 V3 §15.4 设计本意的"5d paper-mode 真测了什么"。这是 LL-098 X10 反 silent forward-progress 同类型反 anti-pattern — "测了 0 数据并 pass" 不等于"测了 V3 §4 → §7 链路 + 9 规则 + STAGED 决议真路径"。

## §1.5 Evidence — empty-system state verified (本 session ~20:30 SQL 实测)

```sql
-- 1. positions = 0 (PT shutdown 4-29 sustained)
SELECT COUNT(*) AS positions FROM portfolio_positions WHERE shares > 0;
-- Result: 0 (sustained Session 43 4-29 emergency_close cycle, ¥993,520.66 cash)

-- 2. risk_event_log 真生产 rows (post-C1 cleanup)
SELECT COUNT(*) AS total FROM risk_event_log;
-- Result: 3 (audit rows 4-29 t0_19_emergency_close + 4-29 ll081_silent_drift + 4-30 pt_restart_gate_audit)

-- 3. execution_plans 真生产 rows
SELECT COUNT(*) FROM execution_plans;
-- Result: 0 (S8 8a STAGED 状态机 dbf55c0 commit 后无真 plan 创建,因 0 持仓 0 sell decision)

-- 4. llm_cost_daily 7 day 真值
SELECT COUNT(*), SUM(cost_usd_total) FROM llm_cost_daily;
-- Result: 7 rows, cost_usd_total cumulative = $0.0000 (322 calls dev 期 free-provider/fallback)

-- 5. XtQuantTickSubscriber 状态 (代码层)
-- Check celery worker log: 0 occurrences of "[tick-subscriber] subscribed code=" since service restart
-- Conclusion: not active on tick stream
```

源数据全核完 (本 session 20:14 worker restart 后 + post-C1 cleanup 20:50 后真值):
- 0 持仓 ✅ → positions-dependent 9 RealtimeRiskRule 大部分 dormant
- 0 真 risk_event_log post 4-30 (3 audit rows 都是 t0_19/ll081/pt_restart cycle 沉淀, 非 RealtimeRiskEngine 触发的)
- 0 execution_plans (S8 STAGED 状态机 8a 代码 ✅ 但 0 真使用)
- 0 LLM cost (free provider)
- 0 active tick subscribe (XtQuantTickSubscriber 未启动)

**含义**: 系统当前**只是代码就位** (Tier A code complete),不是 actively executing。5d 自然 fire 在此状态下产生的 verify 报告等同 "code parses + Beat fires + DB writes 0s",**没法 distinguish from "代码 bug 让所有 query 返 0"** (本 session PR #320 修了正是此 class 的 silent-zero bug)。

## §2 Decision: Skip 5d natural-fire window; Tier A code complete; Tier B真测 = 下一节点

**真值**: V3 §S10 acceptance Plan §A "5d paper-mode 跑通" 在当前 empty-system 状态下 (0 持仓 + 0 tick subscribe + dev-only LLM activity) **信息层等价 trivial-pass**。继续等 5 wall-clock days 不增加任何 verification value。

**论据**:
1. **Empty-system 信息熵=0 anti-pattern**: 跑空数据 trivially-pass 不能 distinguish from "代码 bug 让所有 query 返 0"。本 session PR #320 修了正是 silent-zero bug class (column-name drift + case-mismatch),如果 5-20 verify 报告也 trivially-pass,没法判断是"系统正常 0 alerts"还是"又一个 silent-zero bug"。
2. **Tier B RiskBacktestAdapter 才是真测路径**: S5 sub-PR 5c (commit `a656176`) 已 stub 接口。Tier B 完整实现 = minute_bars 历史价回放 → 9 RealtimeRiskRule 真触发 → 真 risk_event_log 数据流 → 真 verify 报告 with non-trivial false-positive/latency 数据。这才是 V3 §15.4 4 项设计本意。
3. **LL-098 X10 sustained**: 显式 user ack 跳过 Gate A 此项 (not silent skip)。Constitution §L10.1 Gate A footnote needs amendment.
4. **(β) 启动 XtQuantTickSubscriber 半路径分析**: 即使激活 paper-mode tick 订阅,0 持仓 → 多数 positions-dependent 规则仍 dormant (PMSRule / TrailingStop / PartialFillTracker / etc.)。只 universe-wide 规则 (LiquidityCollapse) 可能触发 → 仍不能完整测 9 规则。

## §3 Constitution §L10.1 Gate A footnote amendment

Gate A 8 checklist 中第 2 项 "paper-mode 5d 验收 ✅ (V3 §15.4 标准, 数值 CC 起手时实测决议 + ADR 锁)" 修订为:

> **第 2 项 (amended 2026-05-13, ADR-063)**: paper-mode 5d 验收**仅在 system actively executing** 状态下有意义 (0 持仓 + 0 tick subscribe 状态 trivially-pass 等价于 not tested)。当前 Tier A code 完工状态下此项**显式 deferred 到 Tier B RiskBacktestAdapter真测路径**完成后重新评估。Gate A pass 仅要求其他 7 项 ✅。
>
> **Tier B trigger condition** (new): RiskBacktestAdapter 完整接 minute_bars 历史回放 → 9 RealtimeRiskRule 真触发 → 5d 等价回放 (12 年 minute_bars 任 5 个连续交易日) 产生 risk_event_log + execution_plans 真数据 → verify CLI 报告 4/4 PASS (含 latency instrumentation 落地) → V3 §15.4 acceptance closure。

## §4 Plan §A S10 row amendment

S10 row "Acceptance" 字段从:
> 5d paper-mode 跑通 + 触发率 / 误报率 / 漏报 / STAGED cancel 率 / LLM cost / 元监控 KPI 实测

改为:
> 5d paper-mode acceptance **deferred per ADR-063** (empty-system trivial-pass anti-pattern). Code infrastructure (DDL + aggregator + verify_report + CLI + Beat wire) ✅ closed via PR #315/#319/#320/#321. 真测路径转 Tier B RiskBacktestAdapter (S5 sub-PR 5c stub → 完整实现).

## §5 Sub-PR sediment scope

本 ADR + LL-157 (LL append) + Constitution amendment + Plan §A S10 amendment + REGISTRY ADR-063 row + memory handoff = 单 sediment PR (沿用 PR #316 sediment 模板, ≤8 min target)。

## §6 反对意见 + 缓解

**反对 1**: "skip Gate A 5d 后续若 audit 追问 'V3 §15.4 验收哪去了' 答不出"
**缓解**: 本 ADR + Constitution amendment 显式 documented;Tier B closure 时再加 ADR-XXX 记录真测结果。

**反对 2**: "Tier B RiskBacktestAdapter 实现可能比 5d wall-clock wait 更慢"
**缓解**: 时间不是唯一约束。empty-system 5d wait 信息价值 ≈ 0;Tier B 工程 ~3 day 但产生真 verification value。RoI 明显倾向 Tier B。

**反对 3**: "本 ADR 偷换 V3 §15.4 设计 — 'paper-mode 5d' 本意就是真生产 5d, 不是 historical replay"
**缓解**: 严格 letter 上 ADR 偷换属实。但 spirit 是"5d 真测 alerts/STAGED/latency",而非"5d wall-clock"。Tier B replay 用历史 minute_bars 真触发规则,符合 spirit。Letter-vs-spirit 选 spirit (类似 PR #320 LL-115 第 9 实证体例)。
