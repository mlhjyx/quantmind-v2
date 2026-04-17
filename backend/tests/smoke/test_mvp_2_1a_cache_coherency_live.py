"""Smoke test — MVP 2.1a cache_coherency 真实 DB 路径端到端 (铁律 10b).

subprocess 启动 + live PG + 真查 factor_values MAX(trade_date), 验证:
  1. bootstrap_platform_deps 成功
  2. DB max_date 可查 (turnover_mean_20 factor_values 非空)
  3. MaxDateChecker 三场景正确 (cache 空 / fresh / 旧)
  4. check_stale 组合器返 "db_max_ahead"

BaseDataSource abstract 本次不 smoke (无 concrete), 待 MVP 2.1b 3 fetcher 落地时补.

失败意味:
  - factor_values 表缺失 / turnover_mean_20 数据被洗
  - MaxDateChecker / TTLGuard / check_stale 语义回归
  - CacheCoherencyPolicy dataclass 签名变化
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.smoke
def test_cache_coherency_live_max_date_checker() -> None:
    """bootstrap + MaxDateChecker + check_stale 对 live factor_values 真查."""
    code = (
        "from app.core.platform_bootstrap import bootstrap_platform_deps\n"
        "from app.logging_config import configure_logging\n"
        "configure_logging()\n"
        "ok = bootstrap_platform_deps()\n"
        "assert ok is True, 'bootstrap failed'\n"
        "from backend.platform.data.cache_coherency import (\n"
        "    CacheCoherencyPolicy, MaxDateChecker, check_stale,\n"
        ")\n"
        "from app.services.db import get_sync_conn\n"
        "from datetime import date, datetime, UTC, timedelta\n"
        "\n"
        "conn = get_sync_conn()\n"
        "try:\n"
        "    with conn.cursor() as cur:\n"
        "        cur.execute(\n"
        "            \"SELECT MAX(trade_date) FROM factor_values \"\n"
        "            \"WHERE factor_name='turnover_mean_20'\"\n"
        "        )\n"
        "        db_max = cur.fetchone()[0]\n"
        "finally:\n"
        "    conn.close()\n"
        "\n"
        "assert db_max is not None, 'factor_values turnover_mean_20 empty'\n"
        "assert isinstance(db_max, date), f'expected date, got {type(db_max)}'\n"
        "\n"
        "policy = CacheCoherencyPolicy(db_max_date_check=True, ttl_seconds=86400)\n"
        "checker = MaxDateChecker()\n"
        "\n"
        "# 3 scenarios\n"
        "assert checker.is_stale(db_max, None, policy) is True, 'empty cache should be stale'\n"
        "assert checker.is_stale(db_max, db_max, policy) is False, 'equal dates should be fresh'\n"
        "assert checker.is_stale(db_max, db_max - timedelta(days=1), policy) is True, "
        "'old cache should be stale'\n"
        "\n"
        "# check_stale combinator\n"
        "reason = check_stale(\n"
        "    db_max=db_max, cache_max=db_max - timedelta(days=1),\n"
        "    cache_written_at=datetime.now(UTC), policy=policy,\n"
        ")\n"
        "assert reason == 'db_max_ahead', f'expected db_max_ahead, got {reason!r}'\n"
        "\n"
        "print('OK 2.1a cache_coherency live, db_max=', db_max)"
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
            f"MVP 2.1a cache_coherency live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK 2.1a cache_coherency live" in result.stdout, result.stdout
