# Backtest Review — 正确性 + 复现性 + sim-to-real

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / backtest/01
**Type**: 评判性 + 复现性 (CC 扩 M2) + 过拟合 detection (CC 扩 M3)

---

## §1 铁律 15 sustained verify (regression max_diff=0)

实测真值:
- CLAUDE.md sustained "回测可复现 (regression max_diff=0 硬门)" sustained sustained
- 真 last-run regression test timestamp + 真 max_diff 值 — **本审查 0 跑实测**
- F-D78-24 (sustained) sustained: 待 verify

**finding**:
- F-D78-24 (复) [P3] regression_test max_diff=0 sustained 假设, 真 last-run + 真 max_diff 未 verify in 本审查
- **F-D78-84 [P2]** regression test 真 last-run timestamp 0 sustained sustained (CLAUDE.md / sprint state 0 sync update last-run, 沿用 sprint period sustained "5yr+12yr max_diff=0" sustained sustained 但真 last-run 时间漂移 candidate)

---

## §2 sim-to-real gap (CC 扩 M3 candidate)

实测 sprint period sustained:
- Phase 2.1 Layer 2 NO-GO: "E2E 可微 Sharpe Portfolio 优化 sim-to-real gap 282%" sustained
- CORE3+dv_ttm WF OOS Sharpe=0.8659 (2026-04-12 PASS) vs 真期间 PT NAV ~-0.65% (3-25 → 4-29 60 day) — **sim-to-real gap 真测 candidate**

**finding**:
- **F-D78-85 [P1]** sim-to-real gap 真测 candidate. WF OOS Sharpe=0.8659 (2026-04-12 sustained) vs 真期间 PT NAV ~-0.65% / Sharpe ~0 (60 day): gap 候选明显. 真 root cause: 4-29 -29% 跌停事件 candidate (单事件 vs 长期 alpha) + WF 期间不含 4-29 类事件 + L0 风控空缺 (沿用 risk/01 5 Why)

---

## §3 与生产路径一致性 (sustained framework §3.5)

实测真值:
- 同 SignalComposer / 同成本模型 / 同 universe sustained sprint period sustained sustained (sprint period MVP 3.3 Stage 3.0 真切换 PR #116, signal_service 内部走 PlatformSignalPipeline)
- 但 4-29 PT 暂停后真生产路径 0 active (沿用 risk/02 §1 risk_event_log 仅 audit log)
- 候选 verify: 回测 vs 生产 SignalComposer 真同 commit hash + 同 config 路径

候选 finding:
- F-D78-86 [P2] 回测 vs 生产 SignalComposer 真同一性 实测 verify candidate (sprint period sustained PR #116 sustained sustained 但本审查未深查)

---

## §4 历史 bug 防复发 (regression test 覆盖度)

(沿用 testing/01 §6, 多 regression bug 候选 grep verify)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-24 (复) | P3 | regression_test max_diff=0 sustained 假设, 真 last-run + 真 max_diff 未 verify |
| F-D78-84 | P2 | regression test 真 last-run timestamp 0 sustained sustained (sustained 沉淀但 sync update 漂移) |
| **F-D78-85** | **P1** | sim-to-real gap 真测 candidate. WF OOS Sharpe=0.8659 vs 真期间 PT NAV ~-0.65% / Sharpe ~0 (60 day), 4-29 跌停事件 + L0 空缺 (沿用 risk/01 5 Why) |
| F-D78-86 | P2 | 回测 vs 生产 SignalComposer 真同一性实测 verify candidate (sprint period PR #116 sustained 但本审查未深查) |

---

**文档结束**.
