# Git Hooks (`config/hooks/`)

铁律 10b 自动守门 — push 前强制 `pytest -m smoke` 全绿.

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
| `pre-push` | `git push` 之前 | 跑 `backend/tests/smoke/` 里 `@pytest.mark.smoke` 全套, 失败阻断 push |

## 前置条件

- **dev 环境 PG 必须 up** — smoke 套件依赖 live PostgreSQL (factor_values / feature_flags / factor_registry 等表)
- **Redis 必须 up** — 否则 `bootstrap_platform_deps` 某些初始化路径可能 warn (不致命)
- **`.venv` 推荐** — hook 自动探测 `.venv/Scripts/python.exe` (Windows) / `.venv/bin/python` (Unix), 无则 fall back 到 `python`

## 紧急绕过 (违反铁律, 慎用)

```bash
git push --no-verify
```

铁律 10b 强制要求: 绕过时 **commit message 必须声明原因**, e.g.:

```
fix(xxx): 紧急修复 prod xxx

铁律 10b 绕过: PG 维护窗口 live smoke 不可达, 已本地 mock 跑过.
Co-Authored-By: ...
```

## 故障排查

| 症状 | 原因 | 解决 |
|---|---|---|
| `./pre-push: Permission denied` (Linux/macOS) | 脚本无执行权限 | `chmod +x config/hooks/pre-push` + `git update-index --chmod=+x config/hooks/pre-push` |
| `bad interpreter: No such file or directory` | CRLF 换行 | `dos2unix config/hooks/pre-push` 或 `sed -i 's/\r$//' config/hooks/pre-push` |
| `ModuleNotFoundError: No module named 'app'` | 缺 `.venv/.../quantmind_v2_project_root.pth` | 手建 `.pth` 文件, 内容单行 `D:\quantmind-v2` (Windows) 或项目绝对路径 |
| `psycopg2.OperationalError: could not connect` | PG 未起 | `D:\pgsql\bin\pg_ctl.exe -D D:\pgdata16 start` (Windows 本机) |
| `FlagNotFound: use_db_direction` | feature_flags 表被 migrate 冲 | `python scripts/registry/register_feature_flags.py --apply` |

## 升级路径

本 hook 是**本地第一道防线**. 未来:
- `.githooks/pre-commit` 加 ruff + 快速单测子集
- GitHub Actions / 内部 CI 同步跑 smoke + 锚点回归 (铁律 10b 全链路 enforcement)
- `pyproject.toml` / `pre-commit` framework 统一管理 (本次留轻量 shell 脚本)

## 关联

- 铁律 10b: `CLAUDE.md` (§铁律 > 系统安全类)
- 模板来源: `backend/tests/smoke/test_mvp_1_3b_layer1_live.py`
- 统一 bootstrap: `backend/app/core/platform_bootstrap.py::bootstrap_platform_deps`
