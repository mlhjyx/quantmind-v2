# QuantMind Project Skills

This directory is the versioned Codex project skill layer for QuantMind V2.

Policy:
- Track active project skills in Git so a fresh clone gets the same governance behavior.
- Keep `.claude/skills` as the historical Claude mirror; do not delete or migrate it in Codex-only governance batches.
- Prefer updating an existing project skill over adding a duplicate skill with overlapping triggers.
- Generated caches and runtime artifacts do not belong here.

Current groups:
- `quantmind-*`: project domain skills for DB safety, factor research, experiments, performance, and research KB.
- `quantmind-v3-*`: V3 governance skills referenced by `AGENTS.md` and the V3 invocation map.
- `mattpocock-*`: selected third-party workflow skills adapted into the project layer.
- `omc-reference`: local OMC/team reference skill.
