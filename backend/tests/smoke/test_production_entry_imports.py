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

import os
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
    # Session 27 Task A: 铁律 43 硬化后加入 smoke (main() 返 int + argparse --help OK)
    "scripts/pull_moneyflow.py",
]

# Daemon 脚本 (无 --help) — 走 ast.parse 仅验证语法 + import-free parse
DAEMON_SCRIPTS = [
    "scripts/qmt_data_service.py",
    "scripts/pt_watchdog.py",
]

# One-shot bootstrap 脚本 (无 argparse, 立即跑 main()) — subprocess exec pre-main
# 只验证 imports + 常量 (不触发业务逻辑). MVP 2.3 Sub2 迁 Platform SDK 后新增覆盖面.
ONESHOT_SCRIPTS = [
    "scripts/build_12yr_baseline.py",
    "scripts/yearly_breakdown_backtest.py",
    "scripts/wf_equal_weight_oos.py",
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

    # Reviewer P2 采纳 (PR #52): pull_moneyflow module-top `pro = ts.pro_api(TOKEN)`
    # 依赖 TUSHARE_TOKEN. pydantic-settings 从 backend/.env OR env var 加载,
    # 任一存在即可. CI 无 .env + 无 env 时 skip (避免 subprocess returncode=1
    # 误当 shadow bug). 对齐 live_tushare marker 精神.
    if script == "scripts/pull_moneyflow.py":
        has_env = bool(os.environ.get("TUSHARE_TOKEN"))
        has_dotenv = (PROJECT_ROOT / "backend" / ".env").exists()
        if not (has_env or has_dotenv):
            pytest.skip("pull_moneyflow smoke 需要 TUSHARE_TOKEN (env 或 backend/.env), 均缺失时 skip")

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


@pytest.mark.smoke
@pytest.mark.parametrize("script", ONESHOT_SCRIPTS)
def test_oneshot_script_pre_main_imports(script: str) -> None:
    """One-shot bootstrap 脚本 — subprocess exec pre-main imports (MVP 2.3 Sub2).

    这些脚本无 argparse --help (立即跑 main() 触发 12 年回测, 太慢).
    本测试只 exec 文件的 pre-`def main` 部分 (imports + 常量 + helper 函数定义),
    验证 Platform SDK 迁移后 top-level imports 能成功解析.
    """
    script_path = PROJECT_ROOT / script
    assert script_path.exists()

    # review P2-A (两 reviewer 共识): 用 re.split `^def main\b` (MULTILINE) 防未来 script
    # 含 `def main_helper` / 注释里 `# def main` 导致误分割, 范式更健壮.
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import pathlib, re; "
            f"src = pathlib.Path(r'{script_path}').read_text(encoding='utf-8'); "
            f"head = re.split(r'^def main\\b', src, maxsplit=1, flags=re.MULTILINE)[0]; "
            f"exec(compile(head, r'{script_path}', 'exec'), "
            f"{{'__name__': '__test__', '__file__': r'{script_path}'}}); "
            f"print('pre-main OK')",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or "pre-main OK" not in result.stdout:
        pytest.fail(
            f"{script} pre-main exec failed:\n"
            f"stderr[:1500]:\n{result.stderr[:1500]}"
        )

    # Shadow check (铁律 10b)
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
