"""Smoke test — MVP 1.2 DBFeatureFlag 真实 DB 路径端到端 (铁律 10b).

subprocess 启动 + live PG + 真调 DBFeatureFlag, 验证:
  1. bootstrap_platform_deps 成功
  2. is_enabled("use_db_direction") == True (生产 flag, MVP 1.3c 注册)
  3. list_all() 返非空 (≥ 1 行)
  4. FlagNotFound 对未注册 flag 正确 raise (铁律 33 fail-loud)

失败意味:
  - feature_flags 表缺失 / use_db_direction 被误 unregister / paramstyle 配错
  - FlagNotFound 被 silent 吞 (违反铁律 33 — MVP 1.2 硬门)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.smoke
def test_feature_flag_live_db_crud() -> None:
    """bootstrap + DBFeatureFlag live 读 use_db_direction + list + FlagNotFound."""
    code = (
        "from app.core.platform_bootstrap import bootstrap_platform_deps\n"
        "from app.logging_config import configure_logging\n"
        "configure_logging()\n"
        "ok = bootstrap_platform_deps()\n"
        "assert ok is True, 'bootstrap failed'\n"
        "from backend.qm_platform.config.feature_flag import DBFeatureFlag, FlagNotFound\n"
        "from app.services.db import get_sync_conn\n"
        "flag = DBFeatureFlag(conn_factory=get_sync_conn)\n"
        "assert flag.is_enabled('use_db_direction') is True, 'use_db_direction not enabled'\n"
        "rows = flag.list_all()\n"
        "assert len(rows) >= 1, f'expected >=1 flag, got {len(rows)}'\n"
        "assert any(r['name'] == 'use_db_direction' for r in rows), "
        "'use_db_direction missing in list_all'\n"
        "try:\n"
        "    flag.is_enabled('__nonexistent_flag_xyz__')\n"
        "    raise AssertionError('should have raised FlagNotFound')\n"
        "except FlagNotFound:\n"
        "    pass\n"
        "print('OK 1.2 feature_flag live', len(rows), 'flags')"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"MVP 1.2 feature_flag live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK 1.2 feature_flag live" in result.stdout, result.stdout
