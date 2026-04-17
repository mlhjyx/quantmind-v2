# Servy Service Configs

生产 4 Servy-managed 服务配置导出, 入 git 为审计/回滚/可重建基线.

## 服务列表

| 名称 | CWD (StartupDirectory) | 启动命令 |
|---|---|---|
| `QuantMind-FastAPI` | `D:\quantmind-v2` | `python -m uvicorn app.main:app --host=0.0.0.0 --port=8000 --workers=2` |
| `QuantMind-Celery` | `D:\quantmind-v2` | `python -m celery -A app.tasks.celery_app worker --pool=solo --concurrency=1` |
| `QuantMind-CeleryBeat` | `D:\quantmind-v2` | `python -m celery -A app.tasks.celery_app beat --loglevel=info` |
| `QuantMind-QMTData` | `D:\quantmind-v2\backend` | `python scripts/qmt_data_service.py` (QMTData 不 import Platform, CWD 可保留 backend) |

## 关键约束

**CWD 必须是项目根**, 不能是 `backend/` — 避免 stdlib `platform` 被 `backend/platform/` shadow
(MVP 1.1b Shadow Fix 2026-04-17 教训). QMTData 是例外因其不 import numpy/pandas/uvicorn, 但为
一致性未来也应改为项目根.

## .pth 协同

启动时需 `.venv/Lib/site-packages/quantmind_v2_project_root.pth` 文件, 内容单行:
```
D:\quantmind-v2
```
该文件让 `backend` 作为 namespace package 可解析, `from backend.platform.X` 可用.
**新环境需手动创建** (或未来 pyproject.toml 后处理钩子自动建).

## 重新导入 (改完配置)

```powershell
D:/tools/Servy/servy-cli.exe import --path=D:/quantmind-v2/config/servy/QuantMind-FastAPI.json --config=json
D:/tools/Servy/servy-cli.exe restart --name=QuantMind-FastAPI
```

## 导出 (记录当前生产状态)

```powershell
D:/tools/Servy/servy-cli.exe export --name=QuantMind-FastAPI --config=json --path=D:/quantmind-v2/config/servy/QuantMind-FastAPI.json
```
