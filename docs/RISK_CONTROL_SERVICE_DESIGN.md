# RISK_CONTROL_SERVICE_DESIGN — RETIRED 2026-05-25 (iter 119)

> **STATUS**: ⛔ **PHYSICALLY ARCHIVED** to [`docs/archive/RISK_CONTROL_SERVICE_DESIGN_2026_05_25_archived.md`](archive/RISK_CONTROL_SERVICE_DESIGN_2026_05_25_archived.md).
>
> **REPLACED BY** (V3 SSOT, in-force):
> - **Authoritative design**: [`docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md`](QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md)
> - **L4 STAGED + 反向决策权 + 跌停 fallback**: [`docs/adr/ADR-027-l4-staged-default-reverse-decision-rights.md`](adr/ADR-027-l4-staged-default-reverse-decision-rights.md)
> - **AUTO mode + V4-Pro X 阈值 + RAG + backtest replay**: [`docs/adr/ADR-028-l4-auto-mode-rag-backtest-replay.md`](adr/ADR-028-l4-auto-mode-rag-backtest-replay.md)
>
> **Retirement audit**: [`docs/audit/V3_SSOT_RISK_CONTROL_RETIRE_2026_05_25.md`](audit/V3_SSOT_RISK_CONTROL_RETIRE_2026_05_25.md) (iter 100 audit, §4 FULL RETIRE recommendation; iter 119 execution).
>
> **Archive rationale** (audit §4):
> 1. V3 SSOT 100% covers all 8 sections (semantic重命名 from L0-L3 → PMSRule L1/L3 + DynamicThreshold 3-level; L4_STOPPED redefined by ADR-027)
> 2. schema modernization: `circuit_breaker_state/log` → `risk_event_log` + `execution_plans` + `dynamic_threshold_adjustments` (V3 §10 TimescaleDB hypertable + JSONB)
> 3. 7+ weeks of DEPRECATION header sediment (5-19 → 5-25) — maintenance cost > historical value
>
> **For cross-doc cite**: grep `RISK_CONTROL_SERVICE_DESIGN.md` future hits land at this stub → V3 SSOT redirect. 0 information loss; archived file remains git-history accessible + readable at the archive path above.

---

## See also (V3 risk framework cross-doc cite)

- `CLAUDE.md` §文档查阅索引 (iter 119 updated to reflect archive path)
- `docs/V3_IMPLEMENTATION_CONSTITUTION.md` §L1.1 8-doc fresh-read SSOT
- `docs/V3_SKILL_HOOK_AGENT_INVOCATION_MAP.md` skill/hook/agent invocation map

**END stub.** Stop reading here for current state — see V3 SSOT links above.
