# Design Doc Smoke Test — 2026-05-19 16:42 UTC

> **Plan v8 §VIII #27 closure** (Living Documentation, sediment-then-implement).
> Auto-verify doc claims against filesystem + .env truth sources.
> 反 LL-188 sediment drift (doc claim vs .env truth mismatch).

## §1 Summary

- **Claims checked**: 3
- **Aligned**: 2 ✅
- **Drift detected**: 1 ❌

## §2 Truth Facts (Canonical SSOT 5-20)

| Fact | Value | Source |
|---|---|---|
| `adr_count` | `71` | fs: docs/adr/ADR-*.md |
| `ll_unique_ids` | `169` | grep: LESSONS_LEARNED.md '^## LL-' |
| `audit_doc_count` | `145` | fs: docs/audit/*.md |
| `mvp_doc_count` | `23` | fs: docs/mvp/MVP_*.md |
| `research_kb_failed` | `8` | fs: docs/research-kb/failed/*.md |
| `research_kb_findings` | `25` | fs: docs/research-kb/findings/*.md |
| `research_kb_decisions` | `5` | fs: docs/research-kb/decisions/*.md |
| `env_execution_mode` | `paper` | .env |
| `env_live_trading_disabled` | `true` | .env |
| `env_qmt_account_id` | `81001102` | .env |
| `env_dingtalk_enabled` | `true` | .env |
| `env_pt_top_n` | `5` | .env |
| `env_pt_size_neutral_beta` | `0.50` | .env |

## §3 Drift Findings

| Severity | Fact | Claim | Truth | Note |
|---|---|---|---|---|
| ✅ ALIGNED | `adr_count` | `71` | `71` | Claim matches truth |
| ❌ DRIFT | `env_pt_top_n` | `20` | `5` | Claim '20' ≠ truth '5' |
| ✅ ALIGNED | `env_pt_size_neutral_beta` | `0.50` | `0.50` | Claim matches truth |

## §4 5/5 红线 Field Verification

| Field | Truth | Expected (Phase B-1) | Verdict |
|---|---|---|---|
| EXECUTION_MODE | `paper` | `paper` | ✅ |
| LIVE_TRADING_DISABLED | `true` | `true` | ✅ |
| QMT_ACCOUNT_ID | `81001102` | `81001102` | ✅ |
| DINGTALK_ALERTS_ENABLED | `true` | `true` | ✅ |

---

**Auto-regenerate**: `python scripts/audit_design_doc_smoke.py`
**Source of truth**: filesystem counts + grep + backend/.env
**Plan v8 §VIII #27 closure**: 2026-05-19 sediment

## §5 Future Enhancement

- Expand claim extraction to DEV_*.md (factor counts, schtask counts, service counts)
- Integrate w/ pre-commit canonical metrics (factor_count, ll_unique_ids, etc)
- DB query truth sources (factor_ic_history.factors, trade_log rows)
- Schtask LastResult via Get-ScheduledTaskInfo (Windows-only)