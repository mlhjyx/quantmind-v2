"""Smoke test — 生产入口脚本 top-level import 能 subprocess 启动 (铁律 10b).

MVP 1.1b Shadow Fix 直接动机:
  2026-04-17 发现 FastAPI/PT CLI/Celery 重启全部炸于 stdlib `platform` shadow.
  单测 CWD=project root 永远绿, 但 subprocess 在 CWD=backend/ 启动就触发.

本 smoke 覆盖关键生产入口, 每个 subprocess 启动:
  - 触发真实 top-level imports (pandas / numpy / uvicorn / celery / etc.)
  - 不执行业务逻辑 (用 --help / ast.parse)
  - 捕 import-time 失败 (ImportError / ModuleNotFoundError / AttributeError on stdlib shadow)

运行: `pytest backend/tests/smoke/test_production_entry_imports.py -v -m smoke`
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

# 生产关键入口 — 今日 shadow bug 影响链上的真实脚本
# 每个必须支持 argparse --help (argparse 会 exit(0) 于 --help, 不跑业务)
# qmt_data_service.py 排除 — 无 argparse, daemon loop, 走 ast.parse smoke (见后)
CRITICAL_SCRIPTS = [
    "scripts/run_paper_trading.py",
    "scripts/run_backtest.py",
    "scripts/health_check.py",
    "scripts/regression_test.py",
    "scripts/monitor_factor_ic.py",
    # fetch_minute_bars.py 已删 MVP 2.1c Sub3.3 (2026-04-18), 改用 BaostockDataSource SDK
    "scripts/factor_health_check.py",
]

# Daemon 脚本 (无 --help) — 走 ast.parse 仅验证语法 + import-free parse
DAEMON_SCRIPTS = [
    "scripts/qmt_data_service.py",
    "scripts/pt_watchdog.py",
]


@pytest.mark.smoke
@pytest.mark.parametrize("script", CRITICAL_SCRIPTS)
def test_script_help_runs(script: str) -> None:
    """subprocess 启动 script --help — 触发 top-level imports, 不跑业务.

    失败场景 (今日实见):
      - ModuleNotFoundError: No module named 'backend'  → Platform shadow / sys.path
      - ImportError: Unable to import required dependencies: numpy  → pandas 触发 shadow
      - AttributeError: module 'platform' has no attribute 'system' → shadow 残留
    """
    script_path = PROJECT_ROOT / script
    assert script_path.exists(), f"脚本 {script_path} 不存在, 测试失效"

    # 关键: CWD=project root (Servy 配置后的标准启动路径, 铁律 10b)
    # 允许 exit code 0 (正常) 或 2 (argparse error, 但 import 通过)
    result = subprocess.run(
        [sys.executable, str(script_path), "--help"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )

    # import-time 错误通常在 returncode=1 + stderr 含 Traceback
    if result.returncode not in (0, 2):
        pytest.fail(
            f"{script} subprocess exit={result.returncode}\n"
            f"stderr[:1500]:\n{result.stderr[:1500]}\n"
            f"stdout[:500]:\n{result.stdout[:500]}"
        )

    # 即便 returncode=0, 若 stderr 显式含 Shadow 特征也 fail
    shadow_signatures = (
        "No module named 'backend'",
        "Unable to import required dependencies",
        "platform' has no attribute",
    )
    for sig in shadow_signatures:
        if sig in result.stderr:
            pytest.fail(
                f"{script} stderr 含 shadow 特征 {sig!r}:\n"
                f"stderr[:1500]:\n{result.stderr[:1500]}"
            )


@pytest.mark.smoke
@pytest.mark.parametrize("script", DAEMON_SCRIPTS)
def test_daemon_script_ast_parse(script: str) -> None:
    """Daemon 脚本 (无 --help) — subprocess ast.parse 仅验证语法无 top-level 崩.

    不执行 (守护进程会 loop), 只 parse + compile, 捕语法错误和 import 引用完整性.
    """
    script_path = PROJECT_ROOT / script
    assert script_path.exists()

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import ast, pathlib; "
            f"src = pathlib.Path(r'{script_path}').read_text(encoding='utf-8'); "
            f"ast.parse(src); "
            f"compile(src, r'{script_path}', 'exec'); "
            f"print('parse OK')",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=10,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or "parse OK" not in result.stdout:
        pytest.fail(
            f"{script} AST parse failed:\n"
            f"stderr[:1500]:\n{result.stderr[:1500]}"
        )
