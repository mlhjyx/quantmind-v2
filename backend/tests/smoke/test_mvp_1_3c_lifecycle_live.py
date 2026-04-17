"""Smoke test — MVP 1.3c PlatformLifecycleMonitor 真实 DB 路径端到端 (铁律 10b).

subprocess 启动 + live PG + 真调 DBFactorRegistry + PlatformLifecycleMonitor, 验证:
  1. bootstrap_platform_deps 成功
  2. registry.get_active() 返 ≥ 4 factors (4 CORE: turnover_mean_20 / volatility_20 /
     bp_ratio / dv_ttm — CLAUDE.md 硬锁定)
  3. monitor.evaluate_all() 不 crash, 返 list (可为空, 可含 TransitionDecision)
  4. ic_reader live 查 factor_ic_history 不 crash

失败意味:
  - factor_registry 表数据被洗 / pool 字段 NULL / status 非法枚举
  - factor_ic_history 表 schema 变化 / ic_ma20/ic_ma60 列缺失
  - PlatformLifecycleMonitor.evaluate_all 链路有 import-time or runtime 错
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.smoke
def test_lifecycle_live_evaluate_all() -> None:
    """bootstrap + registry.get_active + monitor.evaluate_all 完整链路."""
    code = (
        "from app.core.platform_bootstrap import bootstrap_platform_deps\n"
        "from app.logging_config import configure_logging\n"
        "configure_logging()\n"
        "ok = bootstrap_platform_deps()\n"
        "assert ok is True, 'bootstrap failed'\n"
        "from backend.platform.factor.registry import DBFactorRegistry\n"
        "from backend.platform.factor.lifecycle import PlatformLifecycleMonitor\n"
        "from backend.platform.data.access_layer import PlatformDataAccessLayer\n"
        "from app.services.db import get_sync_conn\n"
        "\n"
        "def ic_reader(factor_name, lookback):\n"
        "    conn = get_sync_conn()\n"
        "    try:\n"
        "        with conn.cursor() as cur:\n"
        "            cur.execute(\n"
        "                'SELECT trade_date, ic_ma20, ic_ma60 FROM factor_ic_history '\n"
        "                'WHERE factor_name=%s ORDER BY trade_date DESC LIMIT %s',\n"
        "                (factor_name, lookback),\n"
        "            )\n"
        "            rows = cur.fetchall()\n"
        "        return [{'trade_date': r[0], 'ic_ma20': r[1], 'ic_ma60': r[2]}\n"
        "                for r in reversed(rows)]\n"
        "    finally:\n"
        "        conn.close()\n"
        "\n"
        "dal = PlatformDataAccessLayer(conn_factory=get_sync_conn)\n"
        "registry = DBFactorRegistry(dal=dal, conn_factory=get_sync_conn)\n"
        "monitor = PlatformLifecycleMonitor(registry=registry, ic_reader=ic_reader)\n"
        "\n"
        "active = registry.get_active()\n"
        "assert len(active) >= 4, f'expected >=4 active CORE factors, got {len(active)}'\n"
        "core_names = {m.name for m in active}\n"
        "expected_core = {'turnover_mean_20', 'volatility_20', 'bp_ratio', 'dv_ttm'}\n"
        "missing = expected_core - core_names\n"
        "assert not missing, f'missing CORE factors in active set: {missing}'\n"
        "\n"
        "decisions = monitor.evaluate_all()\n"
        "assert isinstance(decisions, list), f'expected list, got {type(decisions)}'\n"
        "print(f'OK 1.3c lifecycle live, {len(active)} active, {len(decisions)} decisions')"
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
            f"MVP 1.3c lifecycle live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK 1.3c lifecycle live" in result.stdout, result.stdout
