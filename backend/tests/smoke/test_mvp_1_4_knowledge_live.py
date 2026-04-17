"""Smoke test — MVP 1.4 Knowledge Registry 真实 DB 路径端到端 (铁律 10b).

subprocess 启动 + live PG + 真调 3 concrete Knowledge Registries, 验证:
  1. bootstrap_platform_deps 成功
  2. DBADRRegistry.get_by_id('ADR-001') 返 ADRRecord (migrate_adrs.py 入库的 5 ADR)
  3. DBFailedDirectionDB.list_all() 返 >= 1 (migrate_research_kb.py 入库 ~39 条)
  4. DBExperimentRegistry.search_similar(任意字符串) 不 crash 返 list

失败意味:
  - adr_records / failed_directions / platform_experiments 表 drop / migrate 丢数据
  - Knowledge Registry paramstyle 配错 (MVP 1.4 sqlite/PG 双路径兼容)
  - ADR-001 (Platform 包名决策) 被意外 delete / supersede

关闭 Wave 1 Knowledge Framework 生产真启动最后一个盲区 (1.1/1.2/1.3b/1.3c/1.4/2.1a 全覆盖).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.smoke
def test_knowledge_registry_live_read_path() -> None:
    """bootstrap + 3 Knowledge read APIs 对 live PG."""
    code = (
        "from app.core.platform_bootstrap import bootstrap_platform_deps\n"
        "from app.logging_config import configure_logging\n"
        "configure_logging()\n"
        "ok = bootstrap_platform_deps()\n"
        "assert ok is True, 'bootstrap failed'\n"
        "from backend.platform.knowledge.registry import (\n"
        "    DBExperimentRegistry, DBFailedDirectionDB, DBADRRegistry, ADRNotFound,\n"
        ")\n"
        "from app.services.db import get_sync_conn\n"
        "\n"
        "adr_reg = DBADRRegistry(conn_factory=get_sync_conn)\n"
        "fd_db = DBFailedDirectionDB(conn_factory=get_sync_conn)\n"
        "exp_reg = DBExperimentRegistry(conn_factory=get_sync_conn)\n"
        "\n"
        "# ADR-001 (Platform 包名决策, MVP 1.4 入库)\n"
        "adr = adr_reg.get_by_id('ADR-001')\n"
        "assert adr.adr_id == 'ADR-001', f'expected ADR-001, got {adr.adr_id}'\n"
        "assert adr.status is not None, 'ADR-001 status 为空'\n"
        "\n"
        "# ADRNotFound raise (铁律 33 fail-loud)\n"
        "try:\n"
        "    adr_reg.get_by_id('ADR-999-nonexistent')\n"
        "    raise AssertionError('should have raised ADRNotFound')\n"
        "except ADRNotFound:\n"
        "    pass\n"
        "\n"
        "# FailedDirectionDB list — CLAUDE.md L474 表格 + docs/research-kb/ 迁入 ~39 条\n"
        "fails = fd_db.list_all()\n"
        "assert isinstance(fails, list), f'expected list, got {type(fails)}'\n"
        "assert len(fails) >= 1, f'expected >=1 failed direction, got {len(fails)}'\n"
        "\n"
        "# ExperimentRegistry search (read path, 允许返空 list)\n"
        "hits = exp_reg.search_similar('size neutral', k=3)\n"
        "assert isinstance(hits, list), f'expected list, got {type(hits)}'\n"
        "\n"
        "print(f'OK 1.4 knowledge live, ADR-001 status={adr.status}, '\n"
        "      f'{len(fails)} failed directions, {len(hits)} similar experiments')"
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
            f"MVP 1.4 knowledge live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK 1.4 knowledge live" in result.stdout, result.stdout
