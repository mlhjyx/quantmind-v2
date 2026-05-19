# Runbook — Retroactive Code Review (铁律 42 procedural补救)

> **Purpose**: 当 backend/* 改动绕过 PR + reviewer (铁律 42 violation) 已累积 → 走本 SOP 触发 reviewer agent 补救, 不允许 silent rot.
> **First applied**: Session 57+1 (commit `0e26ac8` round-1, commit `5a58ef0` round-2) — 30 commits / 15,433 lines main 直推 (audit `RETROACTIVE_REVIEW_FINDINGS_2026_05_19.md`).
> **Trigger philosophy**: 越早 retroactive 越便宜 — 单次 1-2h 工作量 cap 5-7 P1, 拖到 1 month 累积可至 30+ P1 + technical debt 复利.

---

## 1. 触发条件 (任一命中即 trigger)

### 1.1 自动 trigger (CC 主动检测)
- **(a) batch size**: 单一 main session 累计 backend/* 改动 > **10 files** OR **> 500 lines diff** vs last PR-reviewed base
- **(b) commit count**: > **5 commits** direct-main 后 no PR review (cumulative since last reviewed base)
- **(c) high-risk path**: 任一 commit 触碰 `backend/app/api/auth*` / `backend/app/core/auth*` / `backend/qm_platform/llm/*` / `scripts/run_paper_trading*.py` / `backend/.env` → 单 commit 即 trigger

### 1.2 时间 trigger (cadence-based)
- **(d) 周末 cadence**: 每周日 evening session, 若本周 backend/* 改动 > 0, 走 mini retroactive
- **(e) sprint closure**: 沉淀 STATUS_REPORT 前必走

### 1.3 显式 trigger (user OR CC 主动)
- **(f) user 提示**: user 截图 / 反馈累计 diff 大 / 怀疑 procedural violation
- **(g) CC 自审**: CC 末 N commit 觉得自己飘了 (sustained "感觉应该 review 但没 spawn")
- **(h) pre-cutover**: PT live-fire / env_flip / Tier A→B gate 前必走

---

## 2. SOP — 8 步走 (步 0 NEW Session 58 round-1 LL-188 sediment)

### 步 0. Cold-Start Env Reality Check (LL-188 sediment, 反 sediment drift 3+ weeks)

**Why**: Sediment claim ("EXECUTION_MODE=paper sustained" etc) 可与 .env 真值漂移. Session 57+1 6 rounds 全程未真核, 3+ weeks drift unnoticed until Session 58 cold-start. 反 silent rot at sediment layer (LL-188).

**1-minute check**:
```bash
# Env reality check (反 sediment claim 直接核)
grep -E "^(EXECUTION_MODE|LIVE_TRADING_DISABLED|COOKIE_SECURE_FLAG|API_HOST|DINGTALK_ALERTS_ENABLED)" backend/.env

# Backup chain timeline (paper→live cutover trace)
ls -la logs/.env-backup-*.bak backend/.env.bak.* 2>/dev/null | sort -k 6,7

# DB真值 reverse-verify (trade_log + position_snapshot)
python -c "
import re, psycopg2, urllib.parse as up
url = re.search(r'^DATABASE_URL=(.+)$', open('backend/.env').read(), re.MULTILINE).group(1).strip().strip('\"\\'').replace('postgresql+asyncpg://','postgresql://')
p = up.urlparse(url)
conn = psycopg2.connect(host=p.hostname, port=p.port or 5432, dbname=p.path.lstrip('/'), user=p.username, password=p.password)
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*), MIN(executed_at), MAX(executed_at) FROM trade_log WHERE executed_at > NOW() - INTERVAL '30 days';\")
print('trade_log last 30d:', cur.fetchone())
cur.execute(\"SELECT COUNT(DISTINCT trade_date) FROM position_snapshot;\")
print('position_snapshot trade_dates:', cur.fetchone()[0])
conn.close()
"
```

**Expected output check**:
- `EXECUTION_MODE`: paper OR live (whatever operator decided)
- `LIVE_TRADING_DISABLED`: true (broker disabled) OR false (broker enabled — extra caution)
- Backup chain: 最近 backup 应 reflect 任 cutover events (naming convention `pre-{event}-{date}.bak`)
- trade_log: 最近 N 天活动反 sediment claim "0 broker call sustained"

**Red-line claim format SHOULD match reality**:
- ✅ "0 broker call sustained" + trade_log 真 0 rows = consistent
- ❌ "EXECUTION_MODE=paper sustained" + .env actual `live` = **drift, STOP, surface to user**
- ⚠️ "持仓 0" + position_snapshot 0 rows = consistent (清仓 confirmed)

**Action on drift detected**:
1. **STOP**: do NOT proceed with retroactive review under false sediment assumption
2. **Surface**: 给 user 完整 forensic chain (file mtime / backup chain / DB真值 / git log) + corrected red-line claim format
3. **Sediment**: LL candidate (类 LL-188 pattern) — sediment 漂移 layer recurrence prevention
4. **Defuse**: 任 sediment-dependent guards (like round-2 startup guard) 反向 audit + relax/refine

---

## 3. SOP — 7 步 (retroactive review main flow)

### 步 1. Inventory (scope 确定)
```bash
git log --oneline <last-reviewed-base>..HEAD     # 列改动 commit
git diff --stat <last-reviewed-base>..HEAD       # 列 diff 量
```
- 取**未被 prior PR review 覆盖**的 commits 列表
- 区分 `docs/` (直推 OK per 铁律 42) vs `backend/` `frontend/` `scripts/` (需 review)

### 步 2. Classification (风险分层)
按 risk 分 group:
- **HIGH**: auth / security / 红线 enforcement / 配置 / 风险 engine 改动
- **MED**: new components / new endpoints / new scripts
- **LOW**: dead code cleanup / 单纯文档同步 / typo

每 group 估 line 数 + 文件数.

### 步 3. Reviewer Agent Spawn (parallel 并发)
**3 个 reviewer 一次性 spawn** (反 serial — 阻塞 CC 时间高):

| Agent | 适用 | Tools |
|---|---|---|
| `everything-claude-code:typescript-reviewer` | frontend ts/tsx | Read / Grep / Glob / Bash |
| `everything-claude-code:python-reviewer` | backend python / scripts | Read / Grep / Glob / Bash |
| `everything-claude-code:security-reviewer` | cross-cut (auth / 红线 / cookie / SQL inj / prompt inj) | Read / Grep / Glob / Bash |

Optionally:
- `oh-my-claudecode:architect` — strategic / SSOT violation / layering
- `oh-my-claudecode:critic` — multi-perspective challenge

### 步 4. Prompt Template (per agent)
```
Retroactive code review for QuantMind-V2 [LANG] changes pushed direct-to-main
without PR review (N commits, Session XX). User invoked 铁律 42 procedural
violation acknowledgment. You're filling the missing reviewer gate.

**Scope (~XXX lines NEW)** — read ALL files in full:
1. [absolute path 1]
2. [absolute path 2]
... (max 10 files)

**Project context**:
- Stack: FastAPI + sync psycopg2 + PostgreSQL 16.8 + React 18 + TS
- 红线 5/5 sustained: cash ¥XXX / 0 持仓 / LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper
- 铁律 [relevant subset, e.g. 33/34/35/41/42]
- [specific known constraint, e.g. AssistContext entity_id 需 sanitize]

**Review lens**:
[8-10 specific checks per reviewer type]

**Output format**:
- Total findings count by severity (P0/P1/P2/P3)
- Per finding: `[P0/P1/P2/P3] file:line — issue + 1-sentence fix [+ 铁律 tag]`
- Cap at top 20 findings total
- End with 1-paragraph overall impression (合格率 / ship-blocker / cleanup needed)

Be concise. Under 800 words. Do NOT write code fixes — only describe with line numbers.
```

### 步 5. Aggregate (CC main process)
- 3 reviewer return → CC 列总表 (P0=N / P1=N / P2=N / P3=N)
- 去重 (同一 file:line 不同 reviewer 触发) — pick highest severity
- 分组按 file 域 (backend / frontend / scripts) 便于 batch 修

### 步 6. Fix (按 P0 → P1 batch close, P2/P3 backlog)
- **P0**: 立即 fix, ship-blocker
- **P1**: 本轮 close (all 12 P1 ≤ 2h target)
- **P2**: select top 30-50% close 本轮, 余下 backlog
- **P3**: 全部 backlog (next session)

每 file 域 batch 一个 commit. 反 一 commit 改 50 files (review 不可读).

### 步 7. Sediment (反 retroactive review 也飘)
- 写 `docs/audit/RETROACTIVE_REVIEW_FINDINGS_<date>.md` — full findings + fix mapping + backlog
- LL candidate 沉淀 (是否 patterns repeat? e.g. "credential fallback default in 2+ scripts" → LL)
- Memory sprint state prepend handoff
- Commit msg 中含 "Retroactive review pass on N commits/X lines" 字样

---

## 3. Reviewer Lens 简表 (per agent)

### 3.1 typescript-reviewer
1. `any` / `unknown` cast 不合理
2. 缺 null guard (LL-035 `?.`)
3. Zustand race / async setState
4. XSS via `dangerouslySetInnerHTML` / innerHTML
5. Token leak in console.log / localStorage
6. Confirmation flow correctness (tier escalation / type-to-confirm)
7. Async missing await / unhandled rejection / cleanup on unmount
8. A11y: keyboard nav / focus trap / ESC / role / aria
9. Silent catch blocks (铁律 33)
10. API contract: axios call shape / withCredentials

### 3.2 python-reviewer
1. Auth gate on state-mutating endpoint (`Depends(verify_admin_token)`)
2. Transaction boundary (`conn.commit()` 仅 Router/Celery 层)
3. SQL injection (`%s` 参数 vs f-string)
4. Connection leak (try/finally OR context manager)
5. Bare `except: pass` (铁律 33)
6. Configuration SSOT (`settings.xxx` 反 `os.environ`)
7. Hardcoded secrets / fallback defaults (铁律 35)
8. Decimal precision for financial amounts
9. Magic numbers (named constants)
10. Idempotency for re-run scripts

### 3.3 security-reviewer (cross-cut)
1. admin_token path end-to-end (cookie + header + localStorage XSS)
2. AI assist attack surface (prompt injection / model-output-as-command)
3. Safety guardrail bypass (Confirm dialog client-only OR server re-enforce?)
4. RBAC on tool invocation
5. Cost gate (LLM unauthenticated cost sink)
6. CSRF on state-mutating endpoints (SameSite + Origin)
7. Script attack surface (privileged ops / dynamic table names)
8. Production safety property (LIVE_TRADING_DISABLED 双锁 / EXECUTION_MODE / 红线 5/5)
9. Logged credentials in DSN / error messages
10. RED FLAG: ship-blocker condition / 红线 erosion

---

## 4. False Positive 处理

Reviewer findings 不全是真问题. Common FPs:
- "AssistPanel `key={index}`" — message list immutable append, 不会 reorder, index key OK
- "import inside function body" — 有时是真延迟加载 (LLM router) 反 cold-start cost, 不应移到 module-level
- "magic number range(30)" — 若已带 named constant + 注释, FP

**SOP**: 走过 reviewer 验证后, 标 `[FP]` 在 audit doc 中, 反 dilute real findings.

---

## 5. Forward-Looking Patterns (反复出现的)

历史 sediment lessons (Session 57+1 round-1+round-2 真值):
1. **Credential fallback default `""` in scripts** — 5-19 2 scripts 同 pattern. Forward: 新 script 走 `scripts/_lib/db.py` shared `_load_dsn()` helper (反 copy-paste twin).
2. **`os.environ` direct in middle-layer** — middle layer 应走 `settings.xxx` SSOT. Forward: ruff custom rule OR pre-commit grep for `os.environ.get` in `backend/app/api/*`.
3. **Silent catch `// keep defaults`** — 频繁 React useEffect pattern. Forward: ESLint rule for empty catch / log-only catch in `frontend/src/pages/*`.
4. **AssistPanel keydown stale closure** — useEffect dep array + closure 典型陷阱. Forward: typescript-reviewer 每 NEW component 必 spawn.
5. **TOCTOU race in 2-connection workflow** — open A / close A / open B 间隙. Forward: single-conn / single-txn 应是 default pattern for any audit-trail-sensitive ops.

---

## 6. 实操 Quick Reference

### 完整 trigger → sediment one-liner
```
1. inventory: git log/diff vs last reviewed base
2. spawn 3 reviewer agents (typescript / python / security) 并行
3. aggregate findings, dedupe, classify by severity
4. fix P0/P1 (batch by file domain) → ruff + tsc verify
5. write docs/audit/RETROACTIVE_REVIEW_FINDINGS_<date>.md
6. memory sprint state prepend
7. commit with "Retroactive review pass on N commits/X lines" prefix
```

### Run cost
- elapsed: 1.5-2.5h (3 agents parallel + CC fix + verify + sediment)
- token: ~100K (3 agents × 30K + CC main 10K)
- finding 容量: ~30-50 across 3 reviewers

---

## 7. 关联

- **铁律 42** (T1): PR + reviewer 制 (backend/* required)
- **ADR-022** append-only sediment 体例
- **`docs/audit/RETROACTIVE_REVIEW_FINDINGS_2026_05_19.md`** — first applied case study
- **LL-187 → LL-188 (TBD)** sediment chain: large-batch direct-push silent rot

---

**End of runbook.**
