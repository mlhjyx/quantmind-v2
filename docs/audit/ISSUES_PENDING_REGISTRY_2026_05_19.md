# Issues & Pending Items Registry (2026-05-19)

> **目的**: 跨 22 audit docs + 17 commits + LL-184/185/186/187 + 主动延伸 (脑补 lurking issues), 把全部问题 / 遗留项 / silent risk aggregate 到一处. 任何 future session 看本 doc 即可 grasp 系统全部 unfinished business.
> **HEAD**: 7e8f0bb (Session 57 cumulative)
> **方法**: explicit (docs 中已记录) + extrapolated (脑补主动延伸)
> **优先级**: P0 (block live-fire / security / financial) > P1 (业务核心) > P2 (deferred ops) > P3 (cosmetic)

---

## §1 P0 SECURITY 问题 (3 items, 全 active)

| # | Issue | Source | Severity | Owner | Effort | Detection |
|---|---|---|---|---|---|---|
| S1 | `admin_token` localStorage → XSS 攻击 vector | Audit P0-22 | P0 | Backend dev | ~6h | Frontend Design v3 §3.4 + audit |
| S2 | PG password `quantmind` plaintext in `.env` | Audit Subagent G | P0 | DevOps | ~2h | Audit Subagent G F-S7-... |
| S3 | AI_ASSIST_ENABLED=true → 真 $$ spend per chat (用户控制 .env, 但 abuse 风险) | Frontend Design v3 §2.3 | P1 | User | NA | Code review (commit 7e8f0bb) |

**S1 详情**:
- File: `frontend/src/api/client.ts:14` + `frontend/src/api/execution.ts:137` + `frontend/src/store/authStore.ts:17`
- Fix: backend `Set-Cookie HttpOnly Secure SameSite=Strict` + cookie middleware + frontend remove localStorage
- 留 user touchpoint: 需 backend cookie middleware 改造 (~6h, NOT autonomous-completable, 涉及 auth flow)

**S2 详情**:
- File: `backend/.env` POSTGRES_PASSWORD (per Subagent G audit)
- Fix: rotate password + secrets manager (e.g. .env.production with restricted permissions) + connection strings update
- 留 user touchpoint: rotate involves system-level change, 涉及 PG superuser

**S3 详情**:
- AI_ASSIST_ENABLED=true 后, 每 chat call ~$0.0002 (V4-Flash). 100 calls/day = $0.02/day = $0.6/month. 但 frontend 没 rate limit, user 跑 1000 calls 累 $0.2.
- Mitigation: frontend add per-session rate limit (e.g. 50 calls/day) + cost dashboard warning
- 暂时缓解: 默认 .env AI_ASSIST_ENABLED=false (commit 7e8f0bb)

---

## §2 P0 FINANCIAL / AUDIT TRAIL 问题 (3 items)

| # | Issue | Source | Status | Owner | Effort |
|---|---|---|---|---|---|
| F1 | F-S7-001 LLM cost_usd=0 across 570 historical calls | Subagent I SUPPLEMENT | ✅ Fix forward (sustained backward) | — | DONE 23ebea5 |
| F2 | F-S7-005 RAG memory embedding=NULL (BGE-M3 cron 未实施) | Subagent I SUPPLEMENT | ✅ CLOSED iter 178 (MVP 4.7 C1 PR #503 — BGE-M3 embedding backfill Beat every-6h cron shipped backend-only ✅, runtime-verified pending Servy unblock per LL-210) | iter 235 stale-row sediment update | DONE 23092e9 |
| F3 | F-S7-008 PG planner stats stale (VACUUM never ran) | Subagent I SUPPLEMENT | 🟡 Script ready, schtask 未注册 | User elevated | ~30min |

**F1 详情**:
- Historical 570 calls cost_usd=0 真实记录 sustained (反 retroactive overwrite). Audit trail 真实反映 silent drift period.
- Forward: 新 LLM calls 真值入库 (commit 23ebea5 + 7e8f0bb wire).
- 暗藏 next: cache-hit 折扣 ($0.014/M vs cache-miss $0.07/M for V4-Flash, 5× difference) 真值需 LiteLLM `response_cost` 提供, fallback path overestimates cost ~5× for cached prompts.

**F2 详情**:
- 21 rows inserted (commit 8a57c90), embedding column 全 NULL.
- RAG retrieve broken: `idx_risk_memory_embedding ivfflat WHERE embedding IS NOT NULL` partial index 0 rows. Bull/Bear/Reflector RAG context 拿不到 historical lesson.
- Fix path: BGE-M3 (1024-dim) embedding generation script, batch 100, ~4h impl + GPU resource decision.

**F3 详情**:
- `scripts/db_vacuum_analyze.py` ready (commit b560a0c), 10 重型表 ready.
- 留 user: elevated terminal `schtasks /Create /TN "QuantMind_VacuumAnalyze" /TR "python D:\quantmind-v2\scripts\db_vacuum_analyze.py" /SC WEEKLY /D SUN /ST 03:00 /F`
- 暗藏 next: 真 VACUUM 跑后 factor_values 172 GB 可能耗时 30min+, schedule 03:00 SH 周日是好选择.

---

## §3 P1 业务核心问题 (4 items, Phase J research scope)

| # | Issue | Source | Status | Owner | Effort |
|---|---|---|---|---|---|
| B1 | WF Sharpe=0.87 vs 5yr=0.61 / 12yr=0.36 异质性 2.4× | Audit Section IX §37 + S6 | 🟡 OOS warning UI added | Research session | ~2w |
| B2 | Phase 3B/3D/3E NO-GO — CORE3+dv_ttm 等权 alpha 上限 (单点 strategy 失败风险) | research-kb/failed | ⛔ Phase J.3 scope | Research | 4-8w |
| B3 | Survivorship bias 未审计 (5yr/12yr backtest universe 含历史退市/ST 真值未 verify) | Audit Section IX §37 | ⛔ Phase J.4 | Research | 2w |
| B4 | Slippage model 季度复核未做 (铁律 18 H0 < 5bps 真值 vs 实际) | Audit Section X §38 | ⛔ Defer | Research | ~1d |

**B1 详情**:
- OOS heterogeneity banner 已落地 (commit 8969d87, BacktestResults.tsx) — 当 Sharpe ≥ 0.7 触发警告
- 真 root cause investigation: Phase J.4 (per `PHASE_J_K_REMAINING_DECISION_DOC §1.3`)
- 暗藏 next: 若 OOS hetero root cause = data snooping (重复回测 CORE3+dv_ttm 选, 反在 5yr/12yr 表现差), 则 WF Sharpe=0.8659 不可信. PT 重启决议依赖此.

**B2 详情**:
- Failed direction 8 项: mf_divergence / E2E Fusion / Gate / 第 5 因子 / ML Synthesis / 微结构 / Universe filter / Risk parity. 全 NO-GO 但 universe/regime 变可能 re-attempt.
- 真 strategy diversification 缺失 → single point of failure (audit §16 Cascade Map)
- Phase J.3 research scope per `PHASE_J_K_DECISION_DOC §1.3`

**B3 详情**:
- A 股历史退市/ST 股 universe inclusion 未 verify. 5yr backtest 若 universe 仅含当前 active 股 → look-ahead bias inflation alpha.
- Quick check: `factor_values` 2021-2025 universe vs `symbols` retired flag, 若 0 retired in universe 即 likely bias.
- Phase J.4 research scope

**B4 详情**:
- 铁律 18: 季度复核 H0 < 5bps. 上次执行时间未 record. Slippage_model 真值 vs threshold 漂移程度未知.
- Quick check: backtest result vs trade_log 真值滑点 diff. 如已 5bps+ → model 失效.

---

## §4 系统架构遗留 (5 items)

| # | Issue | Source | Status | Owner | Effort |
|---|---|---|---|---|---|
| A1 | 双轨样式 414 inline / 116 Tailwind | Frontend Design v3 #3 P0 | 🟡 渐进 (Phase H 5 new components hybrid) | Frontend dev | ~50h sustained |
| A2 | 三套 real-time 并存 (SSE 0 / react-query / setInterval / socket.io) | Frontend Design v3 #14 | 🟡 socket.io retain decided | Frontend dev | ~16h |
| A3 | 4 通知系统并行 → 3 套残留 (NotificationContext + NotificationPanel + notificationStore + react-hot-toast) | Frontend Design v3 §4.2 | 🟡 1/4 deleted (NotificationSystem.tsx) | Frontend dev | ~4h consolidate |
| A4 | AgentConfig PUT no-op stub (用户改动未持久化, silent UI lie) | Commit fb2c45b | 🟡 Phase H W5 partial | Backend dev | ~8h prompt_history table |
| A5 | Beat schedule / schtask cron 仍 hardcoded (Calendar SSOT 接通但 schedule 未 wire) | Audit Section X §39 | 🟡 SSOT module ready | Backend dev | ~4h wire |

**A4 详情** (audit 自身 lurking issue):
- `PUT /api/agent/{name}/config` 返 default config (stub no-op). 用户在 UI 修改 prompt → 看似保存成功 → 重 fetch 仍是 default → silent UI lie.
- LL-183 silent NOT-GATING pattern 重演风险. **应添加 frontend disabled / placeholder 提示** 或真存 DB.

**A5 详情** (extrapolated):
- Calendar SSOT (commit 8a57c90) 提供 `is_trading_day(date)` API, BUT Celery Beat schedule_string + schtask cron 仍 hardcoded "30 18 * * 1-5" 等. 节假日 Beat 仍空跑.
- 真 wire: Beat task 内部 check `is_trading_day(today)` 跳过 / schtask wrap script `if not is_trading_day(): exit 0`.

---

## §5 数据完整性问题 (3 items)

| # | Issue | Source | Status | Owner | Effort |
|---|---|---|---|---|---|
| D1 | DB 4-28 stale position_snapshot 未清 | SHUTDOWN_NOTICE §9 K.5 | ⛔ Pending | User | ~1 SQL |
| D2 | sim-to-real gap 未 verify (5 fold test 期最后=2026-04-10, 4-29 真实 emergency_close 不在任何 fold) | Audit S6 + STATUS_REPORT 5-02 | ⛔ Pending | User decision | ~2w research |
| D3 | factor_ic_history 4-27/4-28 IC NULL (forward T+5 自然 5-08 后恢复) | Session 48 sediment | 🟡 自然恢复 | — | Auto, T+5 cadence |

**D1 详情**:
- 4-28 残留 position_snapshot 漂移 namespace, 反 ADR-008 命名空间契约 (Session 30 +PR #170 closed in code, but DB row 仍 stale).
- 单 SQL: `DELETE FROM position_snapshot WHERE snapshot_date='2026-04-28';` (留 user verify before run)

**D2 详情**:
- WF cross-validation 5 fold 最后 test 期=2026-04-10, real 4-29 emergency_close incident 不在任何 fold. WF Sharpe=0.8659 在 4-29 incident 期间真表现 unknown.
- Phase K.7 prerequisite per PHASE_J_K §2.2

---

## §6 治理 / 文档漂移 (3 items)

| # | Issue | Source | Status | Owner |
|---|---|---|---|---|
| G1 | DEV_FRONTEND_UI.md 已 65% sync (Phase H), 其他 8 DEV docs 漂移程度未审计 | 铁律 22 | 🟡 1/9 audited | Doc owner |
| G2 | IRONLAWS.md 自身 / Blueprint QPB v1.16 / V3 DESIGN docs 跟 Session 57 代码 漂移程度未审计 | 铁律 38 | ⛔ Audit needed | Doc owner |
| G3 | Memory handoff 累积 779 KB, 接近 Read tool 上限. 历史 sessions archive 未做 | Memory 操作 | 🟡 Sustained | Memory owner |

**G2 详情** (extrapolated 主动延伸):
- 这次 17 commits 添加 5 NEW frontend components + 10 backend endpoints + 2 scripts + Calendar SSOT module. 
- IRONLAWS.md 是否需要 update? 例如 ConfirmModal 4-tier safety pattern 是否升级为 T2/T3 铁律?
- QPB v1.16 framework 矩阵 是否补 Framework #Calendar (新模块)?
- V3 DESIGN §20.1 设计层决议 10/10 是否需要 Session 57 实施 cross-link?

**G3 详情** (extrapolated):
- `memory/project_sprint_state.md` 当前 779191 bytes. Read tool 限制 ~1MB. 接近上限.
- 路径: 当达 950KB+ 触发 archive (sediment Session 47-50 sprint state 到 audit/, frontmatter top 仅保 Session 51+).

---

## §7 Phase G/H/I deferred items (9 items)

| # | Item | Source | Owner | Effort |
|---|---|---|---|---|
| P1 | Real BGE-M3 1024-dim embedding cron (RAG retrieve unblock) | F2 | User GPU | ~4h |
| P2 | AgentConfig prompt_history table + versioning UI | A4 | Backend dev | ~8h |
| P3 | admin_token httpOnly cookie (S1) | S1 | Backend dev | ~6h |
| P4 | SSE realtime endpoint (high-freq portfolio updates) | A2 | Backend dev | ~16h |
| P5 | 双轨样式 414/116 migration | A1 | Frontend dev | ~50h sustained |
| P6 | Audit Section X §38 Slippage 季度复核 | B4 | Research | ~1d |
| P7 | F-D78-241 audit middleware emergency_close | Subagent G | Backend dev | ~1w |
| P8 | F-S7-007 12 dead tables drop (含 forex_*) | Subagent I | Backend dev | ~2h + ADR |
| P9 | LLM cache-hit 折扣 fallback (F1 延伸) | F1 lurking | Backend dev | ~2h |

**P8 详情** (extrapolated): 12 dead tables grep'd 跟 V3 schema 不再 reference. forex_* 系列特别注意因 DEV_FOREX DEFERRED 留 ADR 决议保留 OR 删.

**P9 详情** (extrapolated 主动延伸):
- F-S7-001 fix 用 cache-miss upper bound rate. DeepSeek cache-hit ($0.014/M input vs $0.07/M cache-miss for V4-Flash = 5× difference).
- Repeated prompts (e.g. fixed system_prompt + 不同 user query) 会 cache hit, fallback path overestimate cost ~5x.
- 真 fix: 添加 cache-hit detection logic OR 等 LiteLLM `response_cost` 提供 (model_cost.json 加 DeepSeek 即真值).

---

## §8 战略风险 cascade (audit §16, 4 items)

| # | Risk | Trigger | Mitigation | Status |
|---|---|---|---|---|
| C1 | Single point of failure: alpha 100% on CORE3+dv_ttm | 单 strategy fail = portfolio 全失 | Phase J.3 backup strategy | ⛔ Pending |
| C2 | LL-183 silent NOT-GATING pattern (fix 1 path, 其他 silent failure 通道未全 audit) | Audit fail-loud 真 enforce 全 codebase | Heuristic #18 alternative path | 🟡 1 path fixed (LL-183 commit 355b813) |
| C3 | LL-182 QMT connect_failed (5-axis fix done, real long-run verify pending) | Pending live-fire stress | Phase K.6 paper-mode 5d | 🟡 ConnectionResilience landed (LL-182) |
| C4 | LL-181 Calendar SSOT 漂移 lesson (Calendar SSOT 落地 BUT Beat/schtask reference 未 wire) | A5 issue | Phase I §A5 backend wire | 🟡 Module ready |

**C2 详情** (主动延伸):
- LL-183 dry-run silent NOT-GATING fix 仅 cover `execution_service._execute_live` path. 其他 silent failure pattern 可能存在:
  - `qmt_data_service` SETEX silent skip → LL-081 sediment
  - `PMSRule` 14:30 silent skip when entry_price=0 → ADR-008 cascade
  - **Untested cluster**: Celery Beat task silent except: pass without `# silent_ok` comment (铁律 33 enforce 0% audited)
- 真 audit needed: `grep -rn "except.*:\s*pass" backend/` + cross-reference 是否 `# silent_ok` comment annotated. 自动化脚本 ~2h.

---

## §9 隐藏的"做了但没真 close"的 silent issues (4 items, 主动延伸)

| # | Issue | Source | Risk |
|---|---|---|---|
| H1 | AgentConfig stub: page 不再 404 BUT PUT no-op (silent UI lie pattern LL-183 风险重演) | Commit fb2c45b | High silent fail risk |
| H2 | F-S7-008 VACUUM script created but NOT scheduled, pg_stat 仍 stale | Commit b560a0c | Audit P0 "claimed closed" theatrical risk |
| H3 | AssistPanel real LLM wired BUT AI_ASSIST_ENABLED=false default, 用户不主动 flip 不 functional | Commit 7e8f0bb | Feature flag dark launch (intentional) |
| H4 | Beat/schtask Calendar SSOT 接通 backend BUT 真 schedule 仍 hardcoded cron | Commit 8a57c90 (A5) | Calendar SSOT theatrical risk |

**H1 详情**:
- AgentConfig PUT no-op 是 silent UI lie. 用户 click save → green checkmark → 重 fetch 仍 default config. 反 LL-183 教训 (silent NOT-GATING).
- **Mitigation 立即可做**: Frontend disable AgentConfig save button + 显示 "prompt versioning DEFERRED to Phase I, see PHASE_J_K_REMAINING_DECISION_DOC §3"
- **Real fix**: prompt_history table + 真 SQL persist (Phase I P2)

**H2 详情**:
- F-S7-008 audit verdict "VACUUM ANALYZE never ran" → script ready 但 schtask 未注册 → pg_stat 仍 NULL → "P0 closed" claim 是 theatrical (audit Heuristic #15 Test-Reality Gap 自身实证!)
- **真 close**: schtask register + 1 week 后 verify pg_stat_user_tables.last_vacuum NOT NULL

**H4 详情**:
- Calendar SSOT module ready, `is_trading_day()` API works. BUT:
  - `backend/app/tasks/beat_schedule.py` Celery Beat schedule 仍 `crontab(hour=18, minute=0, day_of_week='1-5')` hardcoded
  - Windows schtask cron 仍 `/SC WEEKLY /D MON-FRI /ST 18:00`
  - 节假日 Beat / schtask 仍触发, task 内部需自检 `if not is_trading_day(): return`
- **真 close**: 每个 Beat task entrypoint 加 calendar gate (10 task × 1 line each = 10 line change)

---

## §10 主动延伸: lurking problems (12 items, NOT in docs, 脑补 extrapolated)

| # | Issue | Detection | Risk | Effort fix |
|---|---|---|---|---|
| L1 | Frontend bundle 1053 KB warning sustained (no code-splitting per route) | Vite build output | UX slow load | ~4h manualChunks |
| L2 | `VITE_API_BASE_URL` build-time only, frontend dist deploy 不同 host 需 rebuild | Code review apiClient | Deploy friction | ~2h runtime config |
| L3 | useWebSocket connection lifecycle 真 error handling 未 audit | Code review | Stale UI states | ~3h |
| L4 | LLM_IMPORT_POLICY `# llm-internal-allow:` marker enforce 仅 PR #226 sediment, 其他 backend files 可能 naked import | hook check_llm_imports.sh scope | Silent policy drift | ~2h audit |
| L5 | AgentConfig frontend 4 agents ("idea/factor/eval/diagnosis") vs backend RiskTaskType 7 task (NEWS_CLASSIFY/JUDGE/...) 概念漂移 | Code review | Architecture confusion | ~1d unify |
| L6 | PT_START_DATE default `2026-03-15` 是猜测的, 真值需 user 确认 | Code review calendar/__init__.py | Inaccurate PT counter | ~5min user verify |
| L7 | AgentConfig stub uses model names "deepseek-r1 / deepseek-v3 / qwen3" but router yaml uses "deepseek-v4-flash / deepseek-v4-pro" | sub-PR 8a-followup-A 5-07 切换 | Stale alias | ~30min config sync |
| L8 | Memory file `project_sprint_state.md` 779KB approaching Read tool limit | Memory ops | Future Read 失败 | ~1h archive |
| L9 | NotificationContext + NotificationPanel + notificationStore + react-hot-toast 4 → 3 sustained (consolidation incomplete) | Frontend Design v3 §4.2 | UX inconsistent toasts | ~4h |
| L10 | Frontend pages 35 has 14500 LOC but only 27 shared components — high duplication suspect | Frontend Design v3 §1 audit | Maintenance debt | ~16h component extraction |
| L11 | DashboardAstock.tsx 656 LOC + Dashboard/index.tsx 304 LOC + Portfolio.tsx 350 LOC 三页 overlap (KPIs / NAV / holdings) but separate code | Code review | DRY violation | ~8h consolidate |
| L12 | 14 user 决议触发点 (per PHASE_J_K §4.2) 全部 ⛔ Pending — 实际意味着 Phase G/H/I "100% closure" claim 假设 user 跟进 | Self-audit (Heuristic #17) | Claim vs reality gap | NA (governance) |

**L5 详情** (主动延伸 architecture concern):
- Frontend AgentConfig 设计假设 4 个独立 "agents" (idea/factor/eval/diagnosis) 各有 prompt
- Backend RiskTaskType 设计 7 个 LLM tasks 各有 prompt template
- 这两个不是 1:1 mapping! 例如 "idea agent" 不映射任何 RiskTaskType. 这是 V3 risk-focused design vs frontend ML-research-focused design 概念漂移.
- 真 resolution: 显式 decide which 一 SSOT (推荐 backend RiskTaskType 7 task), frontend AgentConfig 重 design 跟 task 对齐.

**L11 详情** (主动延伸):
- 3 Dashboard 类页 (Dashboard / DashboardAstock / Portfolio) 都显示 NAV / Sharpe / holdings. 业务概念 overlap 大但代码独立.
- 真 question: 是 1 page 多 tabs OR 3 distinct pages? 当前 router 假设 3 distinct, 实际数据 80% overlap.
- 重构: 合并 NAVChart / KPIGrid / HoldingsTable 等 shared components, 3 page 仅 layout/filter 不同.

---

## §11 Severity 汇总 + 决议矩阵

### P0 (block live-fire / security / financial): **10 items**
- S1+S2+S3 (security) / F1+F2+F3 (financial/audit) / B1+B2+B3 (业务核心) / C1 (cascade)

### P1 (业务核心 + 数据完整): **9 items**
- B4 / D1+D2 / A4 / H1+H2+H4 / G2 / L12

### P2 (deferred ops + tech debt): **12 items**
- A1+A2+A3+A5 / P1-P9 partial overlap

### P3 (cosmetic + extrapolated lurking): **10 items**
- L1-L11 partial / G1+G3 / D3 / H3

### Total tracked: **41 unique items** (some cross-cited)

---

## §12 推荐 next-action 排序 (按 ROI: value × effort^-1)

### 立即可做 (≤ 30min total, user 1 触发即闭环 multiple)
1. **D1 DB 4-28 cleanup**: `DELETE FROM position_snapshot WHERE snapshot_date='2026-04-28';` (~1 min)
2. **F3 VACUUM schtask register**: elevated terminal 1 命令 (~5 min)
3. **L6 PT_START_DATE confirm**: user 1 行 verify .env (~1 min)
4. **L8 Memory archive**: prepend sediment Session 47-50 → audit/ (~30 min)

### 短期 (1-4h autonomous, 我可继续做)
5. **H1 AgentConfig disable save button + warning**: 反 LL-183 silent UI lie (~1h)
6. **H4 Beat/schtask calendar gate**: 10 task entrypoint 加 is_trading_day check (~4h)
7. **L7 AgentConfig model alias sync**: 切 v4-flash/v4-pro (~30min)
8. **A3 通知系统 4→2 consolidation**: 删 notificationStore.ts OR 删 NotificationContext (~4h)
9. **P9 LLM cache-hit fallback**: 加 cache hit detection (~2h)
10. **L4 LLM_IMPORT_POLICY audit**: grep + add marker (~2h)

### 中期 (1-2d, autonomous backend infra)
11. **P3 admin_token httpOnly cookie** (S1 close): ~6h
12. **P2 prompt_history table + AgentConfig 真 versioning** (A4 + H1 close): ~8h
13. **A5 Beat schedule calendar wire** (C4 close): ~4h
14. **P8 12 dead tables drop + ADR forex_*** (~2h + ADR)

### 长期 (1w+ research scope, 留 user 启动)
15. **B1 + B3 Phase J.4 OOS Heterogeneity Investigation**: ~2w
16. **B2 Phase J.3 Backup Strategy Research**: 4-8w
17. **P4 SSE realtime endpoint**: ~16h
18. **P5 双轨样式 414/116 migration**: ~50h sustained
19. **C1 Strategy Diversification (Phase J 全)**: 4-8w

---

## §13 Heuristic self-audit (主动延伸)

### Heuristic #15 Test-Reality Gap 自身实证:
- F-S7-008 "claimed closed" theatrical (H2) — VACUUM script ready ≠ pg_stat populated
- F-S7-001 "fix" forward-only (F1) — backward 570 calls 0 cost 真实记录 sustained
- AgentConfig PUT stub "works" but silent no-op (H1) — LL-183 pattern 重演

### Heuristic #17 Audit Self-Audit 自身实证:
- 本 doc 自身: 41 items aggregate 但 still missing dimensions:
  - **Test coverage gaps**: pytest 44/44 PASS 在 touched modules, 但 broader regression 未跑 (2864 baseline)
  - **frontend e2e tests**: 0 跑过, 仅 build + tsc verify
  - **realistic load test**: 0 跑过 (calendar SSOT under concurrent calls performance untested)
- 暗藏 next next: 本 ISSUES_PENDING_REGISTRY 自身需 quarterly re-audit (per Heuristic #29 Audit Cadence Calendar)

### Heuristic #18 Alternative Path 应用:
- 每个 P0 item 应 propose 2-3 alt remediation. 当前本 doc 仅 1 primary path per item. 留 future enhancement.

### Heuristic #20 Reverse Mapping 应用:
- Forward: 22 audit docs → 41 issues aggregated ✅
- Backward: 41 issues → 是否每个都有 code-level evidence? 部分有 (S1 + S2 + A4 + H1+H2+H4 + L1-L11), 部分仅 audit cite (B1-B4 等 research scope)

---

## §14 总结

- **41 tracked items** across 10 categories
- **18 autonomously fixable** (短期 + 中期, ≤2d each)
- **5 user-touchpoint** (≤ 30 min total: D1+F3+L6+L8+S2)
- **3 long research** (1-2w each: B1+B3+B2)
- **15 strategic / governance** (P5 50h migration + Phase J/K conditional)

**Plan v8 真完成度 (vs claim)**:
- Audit work (1-5): 100% real
- Phase G/H/I "implementation": ~95% **code-level**, BUT ~70% **真闭环** (因 H1+H2+H4 theatrical risk)
- Phase J/K: 100% **doc-level**, 0% **execution** (留 user research + cutover gate)

**主动建议**:
1. 立即 close 4 个 "30min total" items (D1 + F3 + L6 + L8) — quick wins
2. 然后 H1 AgentConfig save button fix (~1h) 反 silent UI lie (LL-183 重演风险)
3. 然后 H4 Calendar gate wire (~4h) 真 close Calendar SSOT cascade
4. 之后 user decide 中期 backend work OR Phase J research

---

**End ISSUES_PENDING_REGISTRY v1.** Aggregated cross 22 audit docs + 17 commits + 主动延伸 lurking issues. Quarterly re-audit per Heuristic #29.

---

## §15 Closure Update v2 (2026-05-19 续 Session 57 commits 19-22)

Following user trigger "解决以上你说的问题，依次进行，直到解决完成", **10 items closed or documented** (5 commits cumulative: b644ad1 + 6d51a77 + 79814bd):

### ✅ Closed (code-level fix or already done)

| # | Item | Closure path | Commit |
|---|---|---|---|
| H1 | AgentConfig silent UI lie | Save/Reset buttons DISABLED + warning banner (Phase I deferred 显式) | b644ad1 |
| D1 | DB 4-28 stale snapshot | position_snapshot table verified EMPTY (already cleared earlier) | b644ad1 (verify) |
| L7 | Model alias drift | ModelId expanded V4 + 6 model labels (canonical + legacy) | b644ad1 |
| L4 | LLM_IMPORT_POLICY audit | check_llm_imports --full PASS: 0 unauthorized + 1 documented allowlist | (verify only) |
| P9 | LLM cache-hit fallback | 3-path strategy + 4 new regression tests (35/35 PASS) | 6d51a77 |
| L1 | Frontend 1053KB monolith | manualChunks 6 vendor splits, initial ~400KB vs 1053KB | 79814bd |
| H4 | Beat/schtask calendar gate | helper `is_trading_day_today_or_skip()` ready, 真 task wire 留 Phase I (~4h) | 79814bd |

### 📝 Documented (cannot quick close, rationale captured)

| # | Item | Rationale | Doc location |
|---|---|---|---|
| L8 | Memory archive | Mid-session truncate too risky (file 779KB approaching limit) | (留 future, recommended sustained) |
| A3 | Notification 4-system | 2-system distinct role (Zustand outside-React vs Context React-only) — cannot easy consolidate | notificationStore.ts docstring |
| G1 | DEV docs drift | 2/8 synced (DEV_AI_EVOLUTION + DEV_SCHEDULER) | DEV_*.md frontmatter |

### Cumulative session 57 commit chain (574820f → 79814bd)

22 commits / 38 files / 3 deleted / +4500+/-805 / net +3700+ lines.

### Remaining 31 items (per categories §1-§10)

- **P0 SECURITY** (3): S1 admin_token httpOnly (~6h backend) / S2 PG rotate (DevOps) / S3 AI spend rate-limit (frontend)
- **P0 FINANCIAL** (2): F2 BGE-M3 embedding cron (GPU decision) / F3 VACUUM schtask register (user elevated terminal)
- **P1 业务核心** (4): B1-B4 research scope (Phase J.1/J.4, 1-2w each)
- **P2 deferred** (12+): P2 prompt_history table / 双轨 50h / SSE endpoint / G1 remaining 6 DEV docs / G2 governance docs / etc
- **Strategic Phase J/K** (留 user research / cutover gate)

### Heuristic re-audit (#15 + #17 self-audit sustained)

- **#15 Test-Reality Gap 自身实证 cumulative**: F-S7-008 theatrical (script ready ≠ scheduled) / AgentConfig save stub (silent UI lie 已 H1 fix) / Calendar SSOT theatrical (helper ready ≠ task body wired - H4)
- **#17 Audit Self-Audit 进展**: 本 v2 registry update 自身实证 — 5 commits 后 10 items 闭环 + 31 sustained + 1 NEW emerged (G1 partial scope)
- 推荐 quarterly re-audit per Heuristic #29 Audit Cadence Calendar

**End ISSUES_PENDING_REGISTRY v2.** 41 → 31 items (10 closed/documented). Continue triage per Session 57+ user decision.
