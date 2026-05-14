# V3 §17.1 CI Lint Verify Report — HC-3a (横切层 Gate D item 3)

> **本文件 = V3 横切层 Plan v0.3 §A HC-3a deliverable** — V3 §17.1 CI lint 5-component
> production-active verify-only report. HC-3a = **verify-only** (NOT 重建) — V3 §17.1
> CI lint 已 substantially closed in Tier A (ADR-020 + ADR-032); HC-3a confirms the 5
> components are production-active + `check_llm_imports.sh` 实跑 0 BLOCKED.
>
> **Status**: HC-3a sediment. **verify surfaced 1 Finding** — CRLF bug in 2/5
> components (§3), fixed in HC-3a (user 决议 A: HC-3a 内修, AskUserQuestion 1 round).
>
> **Date**: 2026-05-14 (Session 53+30)
>
> **关联**: Plan v0.3 §A HC-3a row / V3 §17.1 CI lint / ADR-020 (Claude 边界 + LiteLLM
> 路由 + CI lint) / ADR-031 (`check_anthropic_imports.py` → `check_llm_imports.sh` path
> 决议) / ADR-032 (S4 caller code _internal/ bypass scan) / Constitution §L10.1 item 7
> (path drift 真值修正) / ADR-075 reserved (HC-3 closure) / 铁律 36 (precondition 核) /
> 铁律 40 (测试债务 — governance test 8/10 RED on main `0165915` surfaced + fixed) /
> 铁律 45 (cite source fresh verify)

---

## §1 Context + Methodology

**Scope**: V3 §17.1 CI lint = "禁直接 import anthropic/openai, only path = LiteLLMRouter".
Per Plan v0.3 §A HC-3a, V3 §17.1 已 substantially closed in Tier A — HC-3a is
**verify-only** confirm 5 components production-active, NOT 重建.

**spec path drift 真值** (sustained Constitution §L10.1 item 7 + ADR-031 §6): V3 §17.1
spec cites `check_anthropic_imports.py` — pre-ADR-031 path drift. 真值 =
`scripts/check_llm_imports.sh` (renamed + scope-expanded to openai per ADR-020;
verified `scripts/` 0 `check_anthropic_imports.py`, 1 `check_llm_imports.sh`).

**Methodology** (铁律 36 precondition 核 + 铁律 45 fresh verify): each component
fresh-read + 实跑 verify (NOT static cite). `check_llm_imports.sh --full` 实跑;
governance test 实跑; `git config core.hooksPath` 实查; `git ls-files --eol` 实查
line-ending state.

---

## §2 5-Component Verify Matrix

| # | component | status | 实跑 verify 真值 |
|---|---|---|---|
| 1 | `scripts/check_llm_imports.sh` | ✅ production-active (CRLF fixed §3) | 2-round scan — S6 (`import anthropic/openai` block, ADR-020) + S4 (`from backend.qm_platform.llm._internal` caller bypass block, ADR-032). `--full` 实跑 exit 0: `0 unauthorized import 命中` + 1 transparent allowlist hit (`deepseek_client.py:222 # llm-import-allow:S2-deferred-PR-219`, stderr-logged 可审计). `--staged` / `--full` / invalid-mode (exit 2) 3 模式. |
| 2 | `config/hooks/pre-push` | ✅ production-active | integrates `sh scripts/check_llm_imports.sh --full` (line 62-70) + 铁律 X10 cutover-bias scan (line 11-57) + 铁律 10b smoke (line 82-92). `.gitattributes` `eol=lf` protected (pre-existing). |
| 3 | `config/hooks/pre-commit` | ✅ production-active (CRLF fixed §3) | integrates `sh scripts/check_llm_imports.sh --staged` (line 14-21) + staged `.md` 5-metric canonical verify (warning-only, 0 block). |
| 4 | `backend/tests/test_llm_import_block_governance.py` | ✅ GREEN (10/10 post-§3 fix; was 8/10 RED) | 7 test fns / 10 cases: clean-codebase-passes / 5× violator-without-marker-blocks (anthropic/openai × import/from) / allowlist-marker-passes / tests-subdir-excluded / deepseek-marker-preserved / invalid-mode. |
| 5 | `docs/LLM_IMPORT_POLICY.md` | ✅ production-active | 10 sections (§1 禁止 Pattern / §2 Scope / §3 触发时点 pre-commit+pre-push / §4 背景 V3 §5.5+ADR-020/022 / §5 合法 path / §6 紧急绕过 / §7 历史 / §8 Known Legacy Violator S2-deferred / §9 Allowlist Marker 规范 / §10 ...). |

**git hooks wired**: `git config core.hooksPath` = `config/hooks` ✅ (hooks 真生产激活, NOT 仅文件存在).

**`check_llm_imports.sh` 实跑 0 BLOCKED on current code** (Plan v0.3 §A HC-3a acceptance):
`bash scripts/check_llm_imports.sh --full` → exit 0, scope = `backend/` + `scripts/` (排除
`tests/`), 0 forbidden import, 1 legacy allowlist marker (transparent + auditable per
`LLM_IMPORT_POLICY.md` §9, monthly audit clears 过期 marker).

---

## §3 HC-3a Finding — CRLF bug in 2/5 components (verify surfaced, fixed in HC-3a)

**Finding [type (a) — verify-surfaced RED, 反 verify-only 假设]**: 2/5 components had
**CRLF line endings** in the working tree with no `.gitattributes` `eol=lf` protection:

| component | `git ls-files --eol` (pre-fix) | impact |
|---|---|---|
| `scripts/check_llm_imports.sh` | `i/lf w/crlf attr/` | governance test `subprocess.run(["bash", ...])` → `syntax error near unexpected token $'in\r'` (line 44 `case "$MODE" in\r`) |
| `config/hooks/pre-commit` | `i/lf w/crlf attr/` | latent — works via git's tolerant `sh` today, same fragility |

**Root cause**: `.gitattributes` was added (per its own comment) *specifically* to fix
CRLF-on-Windows-checkout — but only listed `config/hooks/pre-push text eol=lf`. It
**missed** `scripts/check_llm_imports.sh` + `config/hooks/pre-commit`.

**Why production "worked" but the test was RED**: git invokes hooks via `sh` (tolerant
of trailing `\r`); `test_llm_import_block_governance.py` invokes the script via strict
`bash` (`subprocess.run(["bash", ...])`) which fails on `case ... in\r`. → governance
test **8/10 FAILED on main `0165915`** (only `deepseek-marker-preserved` + `invalid-mode`
passed — the 2 not depending on the bash scan). This RED was NOT in the session prompt's
known-pre-existing-fail note (which only cited `test_dynamic_threshold_tasks.py`).

**Blast radius** (precondition 核 — `git ls-files --eol '*.sh' 'config/hooks/*'`): exactly
**2 files** `w/crlf` (the broken ones); other `.sh` (`install_crontab.sh` /
`install_git_hooks.sh` / `team_monitor.sh`) + `pre-push` are already `w/lf`.
`core.autocrlf` unset (local + global). 注: the `*.sh` glob in the fix also re-governs
those 3 already-LF `.sh` files (0 working-tree churn — intentional future-regression
guard, NOT scope creep).

**Fix** (HC-3a, user 决议 A — AskUserQuestion 1 round):
- `.gitattributes`: add `*.sh text eol=lf` (glob — 防 future `.sh` regression) +
  `config/hooks/pre-commit text eol=lf` (no extension, explicit).
- working-tree renormalize: `tr -d '\r'` the 2 files → LF (index was already `i/lf`,
  so 0 staged content diff — the **committed artifact = `.gitattributes`**, which
  forces LF on every future checkout/clone regardless of autocrlf).
- existing-clone note: a fresh clone is auto-correct via `eol=lf`; an *existing* clone
  with CRLF working-tree files would need a one-time `git add --renormalize .` — n=1
  for this single-person project, already fixed locally via the `tr` strip above.
- **Result**: governance test 8/10 RED → **10/10 GREEN**; `check_llm_imports.sh --full`
  still exit 0 via `bash`.

---

## §4 Cumulative cite footer

- **HC-3a deliverable**: 本 verify report + `.gitattributes` CRLF fix (verify-surfaced
  Finding §3 — user 决议 A HC-3a 内修)
- **HC-3 chunked 2 sub-PR**: HC-3a (本 — CI lint verify-only report + CRLF fix) →
  HC-3b (prompts/risk eval iteration ≥1 round on 5 YAML + V4-Flash→V4-Pro routing 决议
  + ADR-075 sediment)
- **关联**: Plan v0.3 §A HC-3a row / V3 §17.1 CI lint / ADR-020 (Claude 边界 + LiteLLM
  路由 + CI lint) / ADR-031 (`check_anthropic_imports.py` → `check_llm_imports.sh` path
  决议) / ADR-032 (S4 _internal/ bypass scan) / Constitution §L10.1 item 7 (path drift
  真值修正) / ADR-075 reserved (HC-3 closure) / 铁律 36 (precondition 核 — blast radius
  实查) / 铁律 40 (测试债务 — 8/10 RED surfaced + fixed) / 铁律 45 (cite fresh verify)
- **5/5 红线 sustained**: cash=￥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true /
  EXECUTION_MODE=paper / QMT_ACCOUNT_ID=81001102 — HC-3a = verify + `.gitattributes`
  config fix, 0 broker / 0 .env / 0 production yaml / 0 DB mutation
