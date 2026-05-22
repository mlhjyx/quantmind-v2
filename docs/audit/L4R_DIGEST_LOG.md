# L4+R 方向 Digest Log

> **用途**: L4+R 自主持续循环 §4.1 方向 digest 的 append-only 落点。
> **写入**: CC 每 research cycle + 每 ~5 execute task + 至少每周一次 append 一条 digest(做了什么 / commit / 下一步计划 / 方向判断 / 与上次 digest 方向偏移 / implement:archive:defer 比例)。
> **读取**: user 可异步翻阅 veto/redirect;§4.2 self-audit 抽查方向漂移。
> **体例**: append-only,新 entry 追加在文件末尾(时序正序),0 retroactive edit。
> **来源 spec**: docs/L4R_LOOP_SPEC.md §4.1
> **创建**: 2026-05-22(loop 未启用,首条 digest 待 loop 首次触发)

---

<!-- digest entries appended below by L4+R loop §4.1 -->

## Digest #1 — 2026-05-22 (iterations 1-2)

**做了什么**
- **Iteration 1 — Phase K O2**: the frontend `triggerPipeline()` POSTed `/pipeline/trigger` with no body → backend `TriggerPipelineRequest` 422'd (the "手动触发 Pipeline" button was broken). Fixed it to send `{engine, config}` + a typed return; added a 4-test regression file; reconciled `docs/API_COVERAGE.md` §6.1. **PR #444 merged** (`d184712` + `c225896`) — independent reviewer APPROVE, tsc/vite/smoke all green.
- **Iteration 2 — verification iteration (no code PR)**. Checked 4 quick backlog items from the iteration-1 punch-list; all stale or imprecise: Calendar `get_calendar()` conn_factory bug (already fixed by "Plan D" 2026-05-20), M-1/M-3 DSN-leak (imprecise — the canonical scripts already use `get_sync_conn`; the real issue is the deferred-gated 铁律 35 fallback-cred closure), RUST_ENGINE_PATH (not actually in `.env.example`), plus the iteration-1 O4/O5/O6 (already fixed by prior work). factors O9/O10 confirmed real orphans but backend-build scope.

**commit / artifact**: PR #444 (merged). Iteration 2: 0 commits — finding-only.

**方向判断 (direction judgment)**
The quick-task backlog seeded from the 2026-05-19/05-20 handoffs is **decayed** — 4/4 micro-items checked were already done or imprecise (later work superseded them). The genuine remaining work is **"build" scope**, dominated by one coherent chunk: the **frontend-action-orphan cluster** — designed UI "action" buttons (pipeline pause / logs / automation-level; factor 因子体检 / 相关性裁剪 / 重评; backtest cancel) wired to backend endpoints that were never built. These need real backend builds with implementation choices, not quick fixes.

**下一步计划**: Pivot from "quick wins" to substantial builds. Iteration 3 = build `POST /api/factors/health-check` (factors O9 — the missing backend for the "因子体检"/"重评" buttons), modeled on the existing `POST /api/pipeline/trigger`. Then iterate the rest of the cluster.

**implement : archive : defer** — iter 1: 1:0:1 · iter 2: 0:0:1 · cumulative 1:0:2 (implement 33%, healthy band).

**方向偏移**: N/A — first digest.

**⚠️ user veto/redirect surface** (this is the §4.1 control surface — async, non-blocking): if you would rather the loop prioritize something other than the orphan-cluster builds — e.g. the 22-day-stale **regression baseline refresh** (铁律 15), a **frontier-research cycle**, the backend **"未实施" stubs** (BruteForce mining / report generation), or a specific orphan order — say so and the loop redirects. Otherwise it proceeds with the orphan-cluster builds starting at factors O9.
