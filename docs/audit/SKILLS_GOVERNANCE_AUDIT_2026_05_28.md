# Skills Governance Audit — 2026-05-28

## Summary

This audit closes the `.agents/skills` policy gap from `FULL_PROJECT_CLOSURE_AND_GOVERNANCE_AUDIT_2026_05_27.md` and `docs/runbook/full_project_remediation_batch_2026_05_27.md`.

Decision: `.agents/skills` is the active Codex project skill layer and must be versioned. `.claude/skills` remains tracked historical state and is not deleted or migrated in this batch.

## Inventory

Fresh inventory from Git Bash on 2026-05-28:

- Active skill directories in `.agents/skills`: 26
- Already tracked before this batch: 7 skill files
- Untracked before this batch: 19 skill directories
- Runtime noise: empty `nul` file at repo root

## Policy

| Area | Decision |
|---|---|
| `.agents/skills` | Track active project skills in Git. |
| `.claude/skills` | Historical Claude layer; keep intact. |
| `.codex/agents` | Codex agent configs; already tracked by Codex governance package. |
| `nul` | Empty generated noise; remove from worktree. |

## Tracked Skill Groups

| Group | Directories | Decision |
|---|---:|---|
| Existing QuantMind domain skills | 7 | Keep tracked. |
| V3 governance skills | 13 | Track; required by AGENTS/V3 SOP references. |
| Matt Pocock workflow skills | 6 | Track selected project copies; upstream clone remains historical/reference only. |

## Verification

- `git ls-files .agents/skills` showed only 7 tracked files before this batch.
- `git status --short .agents/skills` showed 19 untracked skill directories before this batch.
- `find .agents/skills -maxdepth 1 -mindepth 1 -type d` listed 26 active skill directories.
- `nul` was an empty untracked root file and is removed as runtime noise.
