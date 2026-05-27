# Codex Governance Hook Audit — 2026-05-27

## Scope

本次只治理 Codex 当前层 `.codex/`，不迁移、不删除 `.claude/` 历史体系。0 `.env` / broker / DB row / Servy / Task Scheduler / production YAML mutation。

## Inventory

Codex hook 配置源为 `.codex/hooks.json`。本轮前 wire 10 个 hook，未 wire 3 个 `.py`：

| Hook | 本轮决议 | 理由 |
|---|---|---|
| `block_dangerous_git.py` | 接入 `PreToolUse` command 类 hook | 通用危险 git 命令 guardrail，和 `redline_pretool_block.py` 互补 |
| `doc_drift_check.py` | 删除 Codex 拷贝 | standalone drift checker，不应作为 Codex hook 残留 |
| `handoff_sessionend.py` | 删除 Codex 拷贝 | Codex 当前未 wire `SessionEnd`，本轮 Codex-first 不迁移 Claude SessionEnd 体系 |

## Fixes

- `session_context_inject.py`: runtime audit log 改写到 `.codex/hooks/audit.log`；JSON 输出改为 ASCII-safe，避免 Windows GBK stdout `UnicodeEncodeError`。
- `post_edit_lint.py`: `ruff` subprocess 显式 `encoding="utf-8", errors="replace"`，并防御 stdout/stderr 为 `None`，避免 PostToolUse hook 因解码失败 traceback。
- `.gitignore`: 忽略 `.codex/hooks/audit.log` 与 `.codex/hooks/__pycache__/`，保留 `.codex` 配置、hook、agent 文件可入库。
- `config/hooks/README.md`: 同步实际 `pre-commit` / `pre-push` 行为。
- `AGENTS.md`: 将旧 `.Codex/skills` 路径最小更正为 `.agents/skills`。
- `.codex/hooks/post-task.md`: 将旧 `CLAUDE.md` 铁律入口引用最小更正为 `AGENTS.md` / `IRONLAWS.md`。
- `.codex/agents/*.toml` 与 hook 提示文本：将旧 `.Codex/...` / `CLAUDE.md` 引用归一到当前 `.codex/`、`.agents/skills/`、`AGENTS.md` / `IRONLAWS.md`。

## Verification

- Static inventory: `.codex/hooks.json` references 11 hook files; all referenced files exist; `.codex/hooks/*.py` has 0 unwired residual hooks after deleting standalone copies.
- Hook smoke: all wired hooks passed minimal JSON smoke. Normal samples exited 0; `.env` write sample exited 2; `git reset --hard` sample exited 2; no traceback.
- Runtime noise: `git status --short --untracked-files=all` no longer reports `.codex/hooks/audit.log` or `.codex/hooks/__pycache__/`.
- Backend collect: `python -m pytest --collect-only -q backend/tests/test_pipeline_status_contract.py backend/tests/test_risk_events_endpoint.py backend/tests/test_trailing_stop.py` collected 38 tests.
- Frontend build: `npm run build -- --mode development` passed. Vite reported the existing large `vendor-echarts` chunk warning.
- Git hook empty staged: `C:\Program Files\Git\bin\bash.exe config/hooks/pre-commit` exited 0 with staged LLM scan skipped because there were 0 target files.
