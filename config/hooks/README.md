# Git Hooks (`config/hooks/`)

本目录是 Git 本地守门层，和 `.codex/hooks/` 的 Codex 工具调用守门层互补。

- `pre-commit`: staged 代码/文档的快速治理检查。
- `pre-push`: push 前生产入口 smoke + X10/LLM import 守门。

## 启用 (一次性, 每个 clone 手动)

```bash
git config core.hooksPath config/hooks
```

这是仓库 **local config** (`.git/config`), 不入 git. 每个新 clone 需手动执行.

## 禁用 (应急)

```bash
git config --unset core.hooksPath
```

恢复到默认 `.git/hooks/` (通常为空).

## 内容

| 文件 | 触发 | 作用 |
|---|---|---|
| `pre-commit` | `git commit` 之前 | staged LLM import block；frontend raw axios SSOT block；staged `.md` canonical 数字提示；LL-188 `.env` 状态漂移 warning-only |
| `pre-push` | `git push` 之前 | X10 cutover-bias scan；full LLM import block；`backend/tests/` 下 `smoke and not live_tushare` 全套，失败阻断 push |

## Pre-Commit

`pre-commit` 当前包含三类检查：

1. **S6 LLM import block**: 调 `scripts/check_llm_imports.sh --staged`，阻断非 allowlist LLM SDK import。
2. **Frontend API discipline block**: 调 `scripts/audit/check_frontend_api_discipline.py`，只识别真实 `axios` import/require/dynamic import；生产代码仅允许 `frontend/src/api/client.ts` 直接 import axios，测试目录和注释不会误报。
3. **staged `.md` canonical 提示**: 对 staged markdown 输出 6 类 canonical 参考值，包含 factor count、Tier0、LL、D 决议、测试 baseline、LL-188 `.env` claim drift。该部分是 warning-only，不阻断 commit。

紧急绕过:

```bash
git commit --no-verify
```

## Pre-Push

`pre-push` 当前包含三类阻断检查：

1. **铁律 X10 cutover-bias scan**: 扫 branch name + 最近 5 个 commit subject，命中 `/schedule agent`、`paper-mode 5d`、`paper-mode dry-run`、`paper→live`、`auto cutover`、`自动 cutover` 时阻断。
2. **S6 LLM import block**: 调 `scripts/check_llm_imports.sh --full`，覆盖 `backend/` + `scripts/` Python 文件。
3. **铁律 10b smoke**: 调 `python -m pytest backend/tests/ -m "smoke and not live_tushare" --tb=line -q --timeout=60`。

## 前置条件

- **dev 环境 PG 必须 up** — smoke / canonical 查询可能依赖本机 PostgreSQL。
- **Redis 建议 up** — 部分生产入口 smoke 可能初始化 Redis 相关路径。
- **`.venv` 推荐** — hook 自动探测 `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (Unix)，无则 fall back 到 `python`。
- **Git Bash / sh 可用** — hooks 是 POSIX shell 脚本，Windows 下通常由 Git for Windows 提供。

## 紧急绕过 (违反铁律, 慎用)

```bash
git push --no-verify
```

绕过时 **commit message 必须声明原因**, e.g.:

```
fix(xxx): 紧急修复 prod xxx

铁律 10b 绕过: PG 维护窗口 live smoke 不可达, 已本地 mock 跑过.
Co-Authored-By: ...
```

## 故障排查

| 症状 | 原因 | 解决 |
|---|---|---|
| `./pre-push: Permission denied` (Linux/macOS) | 脚本无执行权限 | `chmod +x config/hooks/pre-push config/hooks/pre-commit` + `git update-index --chmod=+x config/hooks/pre-push config/hooks/pre-commit` |
| `bad interpreter: No such file or directory` | CRLF 换行 | `dos2unix config/hooks/pre-push config/hooks/pre-commit` 或 `sed -i 's/\r$//' config/hooks/pre-push config/hooks/pre-commit` |
| `ModuleNotFoundError: No module named 'app'` | 缺 `.venv/.../quantmind_v2_project_root.pth` | 手建 `.pth` 文件, 内容单行 `D:\quantmind-v2` (Windows) 或项目绝对路径 |
| `psycopg2.OperationalError: could not connect` | PG 未起 | `D:\pgsql\bin\pg_ctl.exe -D D:\pgdata16 start` (Windows 本机) |
| `FlagNotFound: use_db_direction` | feature_flags 表被 migrate 冲 | `python scripts/registry/register_feature_flags.py --apply` |
| `scripts/check_llm_imports.sh` block | 新增了非 allowlist LLM SDK import | 改走 LiteLLM 路由或按 `docs/LLM_IMPORT_POLICY.md` 加明确 allowlist marker |
| `frontend-api-discipline` block | 生产前端代码直接 import/require axios | 改走 `frontend/src/api/client.ts` 的 `apiClient`；注释或测试 mock 不会触发 |

## 升级路径

本目录是本地第一道 Git 防线。未来可考虑：
- 将 warning-only markdown canonical check 升级为明确 mismatch block。
- GitHub Actions / 内部 CI 同步跑 smoke + 锚点回归。
- `pyproject.toml` / `pre-commit` framework 统一管理。

## 关联

- 铁律 10b / X10: `IRONLAWS.md`
- LLM import policy: `docs/LLM_IMPORT_POLICY.md`
- 统一 bootstrap: `backend/app/core/platform_bootstrap.py::bootstrap_platform_deps`
