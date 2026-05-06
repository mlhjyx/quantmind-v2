# Audit Week 2 Batch — sub-PR 8a-followup-B 全 series 9 P2/P3 finding sediment (2026-05-07)

> **scope**: sub-PR 8a-followup-pre / -A / -B-yaml / -B-audit reviewer 全 4 PR cycle defer P2/P3 finding 真**单 source 锁定** + audit Week 2 batch governance plan.
> **真意义**: 反**散落 stale gh PR comment** 沿用 ADR-022 反 silent overwrite + sub-PR 8a-followup STATUS_REPORT 体例 sustained.
> **关联文档**: ADR-DRAFT.md row 6-10 sediment (本 PR chunk A 加) + 沿用 sub-PR 8a-followup STATUS_REPORT memory chain (5-07 4 file sustained).

---

## 真累计 9 P2/P3 finding (sub-PR 8a-followup-B 全 4 PR reviewer defer audit Week 2 batch)

### sub-PR 8a-followup-pre (PR #245) — security-reviewer 8 finding (2 P0 + 4 P1 全 adopt + 4 P2/P3 defer)

| # | severity | finding | file:line | 真预约 修 |
|---|---|---|---|---|
| F-pre-P2-1 | P2 | `git push\b` pattern fail 多空格 bypass (e.g. `git  push  --force`) | .claude/hooks/block_dangerous_git.py:54-67 | audit Week 2 batch — 加 `\s+` between git+push patterns |
| F-pre-P2-2 | P2 | hook 真**raw substring search** false positive (commit msg 含 "reset --hard" 触发 hook self-trip) | .claude/hooks/block_dangerous_git.py:42-50 | audit Week 2 batch — command-boundary 体例 / heredoc body skip 体例 sediment (沿用 P3-1 partial 修) |
| F-pre-P2-3 | P2 | DANGEROUS_PATTERNS 真**0 word boundary** before "git" — 极 unlikely false positive | .claude/hooks/block_dangerous_git.py:42-50 | audit Week 2 batch — 加 `\b` before "git" sustained PUSH_DANGEROUS_PATTERNS 体例 |
| F-pre-P2-4 | P2 | fail-soft on JSON parse error 真**document trade-off** 沿用 docstring | .claude/hooks/block_dangerous_git.py:74-76 | audit Week 2 batch — 加 docstring trade-off cite (反 silent disable 风险) |

### sub-PR 8a-followup-A (PR #246) — python-reviewer 7 finding (2 P1 全 adopt + 5 P2/P3 defer)

| # | severity | finding | file:line | 真预约 修 |
|---|---|---|---|---|
| F-A-P2-1 | P2 | whitespace-only `actual_model` (e.g. `"   "`) 真**fail-loud raise FallbackDetectionError** 真**未 cover** | router.py:_is_fallback | audit Week 2 batch — 加 strip 体例 + 显式 case unit test |
| F-A-P2-2 | P2 | _build_response line 301 "or primary_alias" fallback 真 interaction with Case 1 short-circuit 真**undocumented** | router.py:301 | audit Week 2 batch — 加 docstring 体例注 |
| F-A-P2-3 | P2 | docstring 30-line 真**signal-to-noise ratio** 真低 — Case 1/2/3 narrative 真**buried** | router.py:_is_fallback docstring | audit Week 2 batch — 沿用 Args/Returns/Raises 体例 refactor |
| F-A-P3-1 | P3 | inline comment line 386-388 真**redundant** vs docstring | router.py:386-388 | audit Week 2 batch — shorten 1 line cite |
| F-A-P3-2 | P3 | test local import 真**inconsistent** module-level import 体例 (反 _patch_router_completion sustained) | test_litellm_router_core.py | audit Week 2 batch — module-level import 体例 sustained |

### sub-PR 8a-followup-B-yaml (PR #247) — python-reviewer 7 finding (2 P1 全 adopt + 5 P2/P3 defer)

| # | severity | finding | file:line | 真预约 修 |
|---|---|---|---|---|
| F-B-yaml-P2-1 | P2 | litellm_settings yaml block 真**dead config** (S2.1 runtime 未 apply, S2.2/S2.3 deferred) | config/litellm_router.yaml:litellm_settings | audit Week 2 batch — 加 yaml 体例注 + S2.2/S2.3 起手时 wire bootstrap |
| F-B-yaml-P2-2 | P2 | caller-override extra_body merge semantics 真**未 unit-test cover** (LiteLLM Router internal merge behavior 真**未 documented**) | router.py:completion + yaml | audit Week 2 batch — 真测 LiteLLM Router internal merge + 加 unit test |
| F-B-yaml-P2-3 | P2 | test_yaml_no_legacy_deepseek_chat_or_reasoner_underlying 真**KeyError defensive** access | test_litellm_router_core.py:486-499 | audit Week 2 batch — 加 .get() defensive |
| F-B-yaml-P3-1 | P3 | next() StopIteration 真**opacity** 反 AssertionError clear message | test_litellm_router_core.py:460-463/476-479 | audit Week 2 batch — 加 default + assert 体例 |
| F-B-yaml-P3-2 | P3 | BULL/BEAR_AGENT routing test 真**stale mock string** (反此 PR cover) | router.py:59-60 + test_response_dataclass_fields_complete | audit Week 2 batch — 沿用 V4 underlying mock string |

### sub-PR 8a-followup-B-audit (PR #248) — python-reviewer 7 finding (1 P1 + 1 P3 adopt + 5 P2/P3 defer)

| # | severity | finding | file:line | 真预约 修 |
|---|---|---|---|---|
| F-B-audit-P1-1 | P1 (defer) | DDL VARCHAR(40) error_class column comment/semantics drift (sentinel string 沿用 fits 但 contract 反 documented) | migrations/2026_05_03_llm_call_log.sql:72 | audit Week 2 batch — 加 migration widen + comment update |
| F-B-audit-P2-3 | P2 | _audit_log_failure compute_prompt_hash silent except (asymmetric vs success path) | budget.py:464-465 | audit Week 2 batch — 加 logger.warning 沿用 success path 体例 |
| F-B-audit-P2-4 | P2 | llm_cost_daily.call_count 反 increment exception path → analytic undercount | budget.py:_audit_log_failure | audit Week 2 batch — 加 record_cost 0 cost call sustained 沿用 + docstring 体例注 |
| F-B-audit-P2-5 | P2 | sentinel string literals → StrEnum 沿用 BudgetState 体例 (typo prevention) | budget.py:413 | audit Week 2 batch — 加 AuditErrorClass StrEnum |
| F-B-audit-P3-7 | P3 | "llm_audit_failure_record_build_failed" warning path 真**0 test** | budget.py:313 | audit Week 2 batch — 加 test cover defensive code |

---

## 累计统计 (4 PR cycle reviewer defer audit Week 2 batch)

| PR | reviewer total | adopt | defer audit Week 2 |
|---|---|---|---|
| PR #245 followup-pre | 8 | 6 (2 P0 + 4 P1) | 4 (P2/P3) |
| PR #246 followup-A | 7 | 2 (P1) | 5 (P2/P3) |
| PR #247 followup-B-yaml | 7 | 2 (P1) | 5 (P2/P3) |
| PR #248 followup-B-audit | 7 | 2 (P1+P3) | 5 (P1+P2/P3) |
| **总** | **29** | **12** | **19 finding** (含 P1-F-B-audit-1 DDL drift 沿用部分 closed) |

**真讽刺 sediment**: 19 P2/P3 finding 真**累计 sediment scope** 真**audit Week 2 batch governance** 真生产规模, 反 sub-PR 推进速度. 真**反 anti-pattern** sustained — sub-PR closing 时**同步**写 audit Week 2 batch row (反 累 sub-PR 后单 batch governance 体例) — 沿用 ADR-022 反 silent overwrite 体例 sustained (audit Week 2 batch governance 真**单走 PR** sediment 真讽刺案例 #15 candidate).

---

## audit Week 2 batch governance plan (chunk A 起手 → chunk B sequence-based)

**chunk A (本 PR sub-PR audit-week-2-A)**: ADR-DRAFT row 6-10 sediment + 9 P2/P3 finding sediment (本 file).

**chunk B (sub-PR audit-week-2-B sequence-based)**: 真讽刺 #9-#14 LL sediment (LESSONS_LEARNED.md) + ADR-037 §Context 第 7 漂移类型 sediment 加深.

**chunk C deferred** (sub-PR 8b 完成后): Sprint 1 PR #222 retrospective audit (其他 8 PR 类似 part drift catch).

**真**真生效**: chunk A + B 闭环后 → next-prompt Sprint 2 完整 e2e re-run + sub-PR 8b 起手 (RSSHub wire + Anspire/Marketaux endpoint 修 + cadence 决议) — 沿用 user 决议精神 #2 "做完一个推进下一个" + #4 "反留尾巴" sustained.

---

## 真生产 evidence (red line 5/5 sustained, 反 mutation outside scope)

- main HEAD: `9bff84d` post-PR #244 merge (Sprint 2 ingestion 完整闭环)
- xtquant 真账户: cash=¥993,520.66 / 0 持仓 / drift 0.0001% sustained 5-07 sub-PR 8a-followup verify
- .env: LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 sustained
- 0 broker call / 0 真发单 / 0 .env mutation / 0 schtask / 0 force push / 0 push to main / 0 mass delete

---

## 关联文档 (audit chain sediment)

- [docs/adr/ADR-DRAFT.md](../adr/ADR-DRAFT.md) row 6-10 (本 PR chunk A 加)
- [memory/sprint_2_sub_pr_8a_caller_wire_2026_05_07.md](../../memory/sprint_2_sub_pr_8a_caller_wire_2026_05_07.md) (sub-PR 8a STATUS_REPORT)
- [memory/sprint_2_sub_pr_8a_followup_diagnose_2026_05_07.md](../../memory/sprint_2_sub_pr_8a_followup_diagnose_2026_05_07.md) (sub-PR 8a-followup STATUS_REPORT)
- [memory/sprint_2_cumulative_verify_2026_05_07.md](../../memory/sprint_2_cumulative_verify_2026_05_07.md) (Sprint 1+2+Risk v2 cumulative verify)
- [LESSONS_LEARNED.md](../../LESSONS_LEARNED.md) (chunk B 沉淀目标)

---

**LL-100 chunked SOP**: 本 file ~150 line < 400 阈值, single chunk 真生效, 0 拆.

**0 mutation outside scope**: 本 PR scope = ADR-DRAFT row 6-10 append + 本 audit doc create (~250 line total cumulative chunk A).
