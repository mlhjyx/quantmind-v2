---
adr_id: ADR-002
title: 第 2 策略选型 — PEAD Event-driven (非 Minute Intraday)
status: accepted
related_ironlaws: [38]
recorded_at: 2026-04-17
---

## Context

Wave 3 引入第 2 策略 (S2) 与主策略 S1 (MonthlyRanking) 并跑验证 Strategy Framework. 需在两类候选中选一:

1. **PEAD Event-driven** — 基于公告日触发, 低频, 依赖财报数据 (已在 klines/daily_basic/announcements)
2. **Minute Intraday** — 分钟级日内回归/动量, 高频, 依赖 `minute_bars` (21 GB, 190M 行 5 年数据)

两者在 Platform 角度差异明显: 事件驱动 vs 时间驱动, 信号频率差 2 数量级, 回测基础设施需求不同.

Phase 3E-II 已验证 10 个微结构因子 (minute_bars 派生) 全 ROBUST 但 WF 0/6 PASS — 分钟级因子 alpha 存在, 但 **等权框架无法利用**. 若走 Minute Intraday 需同时做 non-equal-weight portfolio optimization, 工程复杂度翻倍.

## Decision

选 **PEAD Event-driven** 作为 S2. 前置 MVP 3.0a (3 周) 准备 announcements 数据接入 + 事件触发基础设施. Minute Intraday 留 Wave 4+ 作 S3 候选.

## Alternatives Considered

| 选项 | 预期耗时 | 基础设施就绪度 | Alpha 证据 | 为何不选 |
|---|---|---|---|---|
| **PEAD Event-driven** ⭐ | 3 周前置 + 3-4 周 Strategy Framework | announcements/PEAD_Q1 已入库 (factor_values 含 pead_q1), direction=+1 验证过 | Sprint 1.8 confirmed | — (选此) |
| Minute Intraday | 6-8 周 (含 portfolio 层改造) | minute_bars 21 GB 齐 + 10 微结构因子 ROBUST 但 WF FAIL | 需 non-equal-weight 才能释放 | 工程复杂度 2x + 同时验证 Strategy Framework 与 portfolio 层 2 变量, 违反"一次一变量" |

## Consequences

**正面**:
- PEAD 基础设施已 70% 就绪, S2 开发聚焦在 Strategy Framework + Event Hook 预埋 (MVP 3.2)
- 事件驱动 vs 月度 Ranking 在信号语义正交, 两策略独立性强, Strategy Isolation test 有用
- PEAD 低频减 QMT 下单压力, 生产风险低

**负面**:
- Minute-level alpha 延后开发, 10 微结构因子暂时搁置
- PEAD 依赖 announcements 数据实时性, 需 Wave 4 前验证 Tushare announcements coverage

## References

- `memory/project_platform_decisions.md` §Q2
- `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Part 4 MVP 3.0a + MVP 3.1
- Phase 3E-II 验证报告 (sprint_state "Phase 3E-II 微结构因子 WF 0/6 FAIL")
- factor_values `pead_q1` direction=+1 数据 (`backend/engines/factor_engine/_constants.py::PEAD_FACTOR_DIRECTION`)
