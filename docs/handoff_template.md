# Handoff Template — sprint state SQL verify SOP

**Document ID**: handoff_template
**Status**: Phase 4.2 CC implementation, Layer 4 SOP Topic 1 B (handoff SQL verify 强制 template)
**Source**: protocol_v1.md §2 Topic 1 B + Topic 1 C 决议
**Created**: 2026-05-01

---

## §1 核哲学

**Handoff 目的**: cross-session continuity — **0 fabricated 数字** (anti-pattern v1 守门), **0 假设 path/file/function** (anti-pattern v2 守门), **0 信 user GUI cite without source** (anti-pattern v3 守门).

**核守门**: handoff 中**任一数字** **必 cite SQL query + result + timestamp** — **0 数字凭空**.

---

## §2 Schema (handoff entry 核 format)

```yaml
date: YYYY-MM-DD HH:MM (CC 实测 timestamp, 不假设)
session_id: Session N (CC 实测 verify, sprint state frontmatter cite)
sprint_phase: Layer N / Week N / Sprint N
branch: <git rev-parse --abbrev-ref HEAD>
main_head: <git log -1 --format=%h main>
work_done:
  - WI N: 描述
    - sql_verify:  # 任一数字必有
      - query: "<SQL query verbatim>"
      - result: <真值, 不假设>
      - timestamp: <CC 实测 query 时间>
work_next:
  - WI N+1: 描述
findings:
  - F-D78-N: 描述 (sustained source cite)
verdict: closed / sustained / blocked / STOP
```

---

## §3 核 cite SOP 强制 (Topic 1 B + Topic 1 C 同源)

handoff 中**任一数字** 必 cite 1 项:

| 数字类型 | **必 cite** source |
|---|---|
| factor count | `SELECT count(DISTINCT factor_name) FROM factor_ic_history;` + result + timestamp |
| Tier 0 数 | `wc -l docs/audit/TIER0_REGISTRY.md` OR `grep -c "T0-" TIER0_REGISTRY.md` + result + timestamp |
| LL 数 | `grep -c "^- LL-" LESSONS_LEARNED.md` + result + timestamp |
| D 决议 数 | `grep -c "^### D-" docs/DECISION_LOG.md` + result + timestamp |
| 测试 baseline | `pytest --collect-only -q | tail -1` + result + timestamp |
| 真账户 cash | `python scripts/_verify_account_oneshot.py` + result + timestamp |
| 真账户 nav | `SELECT trigger_metrics->'nav' FROM circuit_breaker_state WHERE execution_mode='live';` + result + timestamp |
| factor_ic MAX | `SELECT MAX(trade_date) FROM factor_ic_history WHERE factor_name='dv_ttm';` + result + timestamp |
| trade_log MAX | `SELECT MAX(trade_time) FROM trade_log;` + result + timestamp |
| schedule task last run | `SELECT MAX(created_at) FROM scheduler_task_log WHERE task_name='<task>';` + result + timestamp |

**核 SOP**: handoff 内**任一上述数字** 必 attach 1 row "sql_verify" entry per §2 schema.

---

## §4 Anti-pattern 守门

| anti-pattern | 守门 |
|---|---|
| v1 凭空数字 | 核 §3 cite source SOP enforce |
| v2 凭空 path | path cite **必 ls/find/glob verify** |
| v3 信 user GUI cite | user GUI cite **必 CC SQL/script/log cross-check** |
| v4 静态分析 = 真测 | **必 run command + output cite**, **0 grep/cat 推断** |
| v5 Claude 给具体 | **必 CC 实测决议**, **Claude 仅 verify direction** |

---

## §5 Example handoff entry (Phase 4.2 CC 起手 sediment)

```yaml
date: 2026-05-01 21:25 (CC 实测 timestamp)
session_id: Session 47 (sprint state frontmatter cite + handoff sustained)
sprint_phase: Layer 4 SOP align Phase 4.2 (Week 1 closed sustained PR #192 → Phase 4.2 起手)
branch: phase4_2/layer4_sop_align (CC 实测 git rev-parse --abbrev-ref HEAD)
main_head: 42f9663 (CC 实测 git log -1 --format=%h main, PR #192 merged sustained)
work_done:
  - WI 1: protocol_v1.md sediment to docs/audit/2026_05_audit/protocol_v1.md
    sql_verify: N/A (verbatim cite from user prev message)
  - WI 2: DECISION_LOG.md initial schema + D-72/D-78/D-79 sediment
    sql_verify: N/A (sediment file create)
  - WI 4: handoff_template.md create (本文件)
    sql_verify: N/A
  - WI 5: CLAUDE.md §489 数字 cite SOP update
    sql_verify: N/A
  - WI 6: alpha_continuous_log + cross_verify_log skeleton
    sql_verify: N/A
work_next:
  - WI 3: pre-commit hook minimal scope (CC 实测决议 5 metric verify)
  - WI 7: STATUS_REPORT + PR push
findings:
  - D-79 sediment: Layer 4 SOP align Phase 4.2 (sustained Topic 1-4 决议 closed)
  - D-73~D-77 placeholder sustained:  0 individual content sustained, 留 Layer 2 sprint Week 2-3 backfill
verdict: sustained (in progress)
```

---

**Document end**.
