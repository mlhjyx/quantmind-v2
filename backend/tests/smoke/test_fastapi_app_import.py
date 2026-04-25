"""Smoke test — FastAPI app 模块能从项目根 CWD subprocess 导入 (铁律 10b).

不 spawn uvicorn 服务器 (太重), 但以与生产相同的方式 (`CWD=project root, python -c
'import app.main'`) 触发完整 import 链, 包括 uvicorn.main 的 stdlib `platform` 导入.

历史炸点 (Session 7 MVP 1.1b 期间, 此 smoke 加入触发因): uvicorn.main:6 `import platform`
命中当时的 `backend/platform/` shadow → numpy partial-init AttributeError. PR-E1
(Session 36 2026-04-25) 把 `backend/platform/` 重命名为 `backend/qm_platform/` 永久消
除 shadow 根因, 本 smoke 现作为 regression guard.

运行: `pytest backend/tests/smoke/test_fastapi_app_import.py -v -m smoke`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.smoke
def test_fastapi_app_imports_from_project_root() -> None:
    """subprocess 从 project root 启动 `import app.main` — 必须零异常."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.main; print('FastAPI app imported:', app.main.app.title)",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )

    if result.returncode != 0:
        pytest.fail(
            f"`import app.main` failed (exit={result.returncode}):\n"
            f"stderr[:1500]:\n{result.stderr[:1500]}\n"
            f"stdout[:500]:\n{result.stdout[:500]}"
        )
    assert "FastAPI app imported" in result.stdout, result.stdout


@pytest.mark.smoke
def test_stdlib_platform_wins_over_backend_platform() -> None:
    """subprocess 验证 stdlib `platform.system()` 可用, 不被任何子目录 shadow.

    历史核心症状 (PR-E1 Session 36 修复前): `import platform; platform.system()` →
    AttributeError 因 `backend/platform/` 包名与 stdlib 冲突. 现 regression guard.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import platform; print('stdlib platform.system():', platform.system())",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, f"stdlib platform 不可用: {result.stderr}"
    assert "stdlib platform.system()" in result.stdout
    # stdlib.system() 在 Windows 返 Windows / Linux 返 Linux
    assert any(os in result.stdout for os in ("Windows", "Linux", "Darwin"))


@pytest.mark.smoke
def test_backend_platform_namespace_package_accessible() -> None:
    """subprocess 验证 `from backend.qm_platform.X import Y` 可解析 (项目根在 sys.path)."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from backend.qm_platform.config.feature_flag import DBFeatureFlag; "
            "print('DBFeatureFlag:', DBFeatureFlag.__name__)",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"`from backend.qm_platform.X import Y` failed:\n"
            f"stderr[:1500]:\n{result.stderr[:1500]}"
        )
    assert "DBFeatureFlag: DBFeatureFlag" in result.stdout
