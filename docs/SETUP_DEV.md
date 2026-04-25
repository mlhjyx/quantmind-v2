# SETUP_DEV — 新环境 bootstrap 清单

新机器 / 新 clone 启动 QuantMind V2 所需的**非显而易见步骤**. 显而易见的 (pip install, 建库建表) 不赘述.

铁律 10b 自动门禁 + Platform stdlib shadow 根治后, 若缺以下任一步骤, 首次跑 `pytest` / 启 Servy 会炸.

---

## 必做步骤 (缺一不可)

### 1. `.venv/.../quantmind_v2_project_root.pth` (手建, 非 git)

MVP 1.1b Shadow Fix 依赖此文件让 `from backend.qm_platform.X` 作为 namespace package 可解析.
**Session 12 (2026-04-19) 修正**: 必须**两行** — 项目根 + `backend/` — 因代码双 import 风格并存
(`from app / engines / ...` 无前缀 + `from backend.qm_platform / backend.app.X` 带前缀).

**Windows (两行)**:
```powershell
# .venv 建好后 (python -m venv .venv + pip install -e ".[dev]")
@"
D:\quantmind-v2
D:\quantmind-v2\backend
"@ | Out-File -FilePath .venv\Lib\site-packages\quantmind_v2_project_root.pth -Encoding ASCII
```

**验证**:
```bash
.venv/Scripts/python.exe -c "
import app; import backend.qm_platform._types
import alembic; assert 'site-packages' in alembic.__file__, f'alembic shadow! {alembic.__file__}'
print('pth OK (alembic resolve:', alembic.__file__, ')')
"
# 期望: "pth OK (alembic resolve: ...\\site-packages\\alembic\\__init__.py )"
# alembic 必须 resolve 到 pip site-packages 而非 backend/alembic/ (migration 目录, 无 __init__.py).
# pip alembic (regular package) 优先级 > backend/alembic/ (namespace), 正常无 shadow.
# 若未来有人给 backend/alembic/ 加 __init__.py, 此校验炸, 需立即 rename migration 目录.
```

**没有此文件 (或只单行) → 炸点**:
- `ModuleNotFoundError: No module named 'app'` (smoke `test_fastapi_app_import` 炸)
- `ModuleNotFoundError: No module named 'backend'` (smoke `test_production_entry_imports` 炸)

---

### 2. `git config core.hooksPath config/hooks` (一次性 local config)

启用铁律 10b 自动门禁 — push 前 `pytest -m smoke` 必全绿.

```bash
git config core.hooksPath config/hooks
```

详见 `config/hooks/README.md`. 禁用: `git config --unset core.hooksPath`.

**不启用 → 炸点**: 账面铁律 10b 生效, 实际不 enforce, 历史教训复发 (MVP 1.1-2.1a 账面绿 7/7 但生产 shadow 潜伏 1 周).

---

### 3. Servy 服务 `StartupDirectory` = 项目根 (非 `backend/`)

MVP 1.1b Shadow Fix 要求. 配置已入 git: `config/servy/QuantMind-{FastAPI,Celery,CeleryBeat,QMTData}.json`.

**导入**:
```powershell
D:\tools\Servy\servy-cli.exe import --path=D:\quantmind-v2\config\servy\QuantMind-FastAPI.json --config=json
D:\tools\Servy\servy-cli.exe import --path=D:\quantmind-v2\config\servy\QuantMind-Celery.json --config=json
D:\tools\Servy\servy-cli.exe import --path=D:\quantmind-v2\config\servy\QuantMind-CeleryBeat.json --config=json
D:\tools\Servy\servy-cli.exe import --path=D:\quantmind-v2\config\servy\QuantMind-QMTData.json --config=json
```

**CWD 注意 (历史 shadow 风险已根除 Session 36 PR-E1)**: 原 `backend/platform/` 命名 shadow stdlib `platform`, 在 multiprocessing.spawn 子进程触发 numpy import 失败. PR-E1 (Session 36 2026-04-25) 重命名为 `backend/qm_platform/` 永久消除根因. CWD 不再是炸点, 但建议仍按上面 servy json 配置项目根 CWD 以保 \`from backend.qm_platform.X\` namespace 解析稳定.

---

### 4. PostgreSQL + TimescaleDB + Redis 基础设施

- PG 16.8 + TimescaleDB 2.26.0 + `D:\pgsql\bin\pg_ctl.exe -D D:\pgdata16 start` (详见 CLAUDE.md 硬件章节)
- Redis 5.0.14.1
- 建库/建表: `docs/QUANTMIND_V2_DDL_FINAL.sql` + `backend/migrations/*.sql` (幂等)
- `.env`: 不入 git, 从上一环境拷贝 (DATABASE_URL / REDIS_URL / API keys / PT_* / PMS_* / SN_*)

---

### 4b. xtquant SDK (非 pip, miniQMT 私有)

xtquant 是国金证券 miniQMT 的 Python SDK, **不在 PyPI**. 必须从 miniQMT 安装目录手动复制.

**标准位置** (按 `backend/app/core/xtquant_path.py:24` 契约):
```
.venv/Lib/site-packages/Lib/site-packages/xtquant/
```

**为何双层嵌套**: miniQMT SDK 原始发布结构如此, `ensure_xtquant_path()` 用 `append`
(不是 `insert`) 加入 sys.path, 避免 xtquant 旧 numpy 覆盖项目 numpy.

**获取方式**:
- miniQMT 客户端默认装在 `D:/国金证券QMT交易端/bin.x64/...` 附近, 找 `xtquant/` 子目录
- 或从 Servy 正在运行的 QMTData 服务 `tasklist /v` 查进程 path 反推

**缺失 → 炸点**:
- `ModuleNotFoundError: No module named 'xtquant'` 仅影响 `scripts/qmt_data_service.py`
  (QMTData 服务启动). smoke / regression / 其他 scripts 不依赖.
- **Servy QMTData 服务下次重启前必须就位**, 否则 fail-loud.

---

### 5. 迁移脚本 (一次性, 按顺序)

```bash
# Platform Registry (铁律 31 / 34)
.venv/Scripts/python.exe scripts/registry/backfill_factor_registry.py --apply
.venv/Scripts/python.exe scripts/registry/register_feature_flags.py --apply

# Knowledge Registry (MVP 1.4, 铁律 38)
.venv/Scripts/python.exe scripts/knowledge/migrate_research_kb.py --apply
.venv/Scripts/python.exe scripts/knowledge/register_adrs.py --apply
```

---

## 验证 (完成后跑一次)

```bash
# 1. Python 路径 OK
.venv/Scripts/python.exe -c "from backend.qm_platform.data.access_layer import PlatformDataAccessLayer; print('import ok')"

# 2. 全 smoke 套件 (铁律 10b)
.venv/Scripts/python.exe -m pytest backend/tests/smoke/ -m smoke -v
# 期望: 20 PASS (MVP 1.1-2.1a retrospective 全覆盖)

# 3. 锚点回归 (铁律 15)
.venv/Scripts/python.exe scripts/regression_test.py --years 5
# 期望: max_diff=0.0, Sharpe=0.6095

# 4. Servy 服务健康
D:\tools\Servy\servy-cli.exe status
# 期望: 4 服务 Running
```

---

## 故障排查

| 症状 | 根因 | 解决 |
|---|---|---|
| `No module named 'backend'` | 缺 `.pth` 文件 | 见步骤 1 |
| `No module named 'app'` | pytest CWD 不是项目根 | `cd D:\quantmind-v2` 后重跑, 或 `.pth` 缺失 |
| `AttributeError: module 'platform' has no attribute 'system'` | Servy StartupDirectory=`backend/` + `sys.path.insert(0, backend)` shadow | 见步骤 3 (重新 import Servy config) |
| `bash: config/hooks/pre-push: bad interpreter` | CRLF 换行 (Windows autocrlf=true) | `.gitattributes` 已强制 `eol=lf`, 重 clone 或 `git add --renormalize config/hooks/pre-push` |
| `pytest collection` 崩 `collections.Callable` | pyreadline 2.1 + py3.11 不兼容 | `pip uninstall pyreadline` (dill 不受影响) |

---

## 关联文档

- `config/hooks/README.md` — pre-push hook 启用/禁用/故障排查
- `config/servy/README.md` — Servy 服务管理 + CWD 约束
- `CLAUDE.md` §铁律 10b — 生产入口真启动验证制度化
- `CLAUDE.md` §部署规则 — Servy 服务清单 + 启动顺序
- `backend/migrations/` — 数据库 migration 全集 (幂等)
