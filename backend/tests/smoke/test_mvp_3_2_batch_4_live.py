"""Smoke: MVP 3.2 批 4 多策略 wiring 生产入口真启动验证 (铁律 10b).

验证链路 (subprocess 隔离, 避母进程 import 污染):
  1. `app.services.strategy_bootstrap` 可 import — fail-safe fallback helper
  2. `get_live_strategies_for_risk_check` 函数签名 + 返 list[Strategy]
  3. `daily_pipeline.risk_daily_check_task` + `intraday_risk_check_task` 已注册 + import 新 helper
  4. fallback 行为真跑一次 (force DB error → 必返 [S1MonthlyRanking()])

铁律 10b 意图: subprocess 从生产启动路径真启动, 捕 import-time / top-level 执行错误.
本 smoke 额外验 fallback path 能真跑 (不是理论上 fallback, 是 runtime 实际可达).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.smoke
def test_mvp_3_2_batch_4_multi_strategy_wiring_imports() -> None:
    """Platform strategy + bootstrap + daily_pipeline 链路 subprocess import 不炸.

    断言:
      - strategy_bootstrap 可 import
      - get_live_strategies_for_risk_check 签名正确 (零参, 返 list)
      - daily_pipeline risk_daily_check_task / intraday_risk_check_task 注册
      - fallback runtime 可达: force DB fail → 返 [S1MonthlyRanking()] (非空)
      - S1.strategy_id == 当前 PT UUID (28fc37e5-...) 保 Monday 行为
    """
    project_root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                # MVP 1.1b LL-052 shadow 修复: 预热 stdlib platform
                "import platform as _stdlib_platform; "
                "_stdlib_platform.python_implementation(); "
                "import sys; "
                f"sys.path.insert(0, r'{project_root / 'backend'}'); "
                f"sys.path.insert(0, r'{project_root}'); "
                # 1. strategy_bootstrap 模块可 import
                "from app.services.strategy_bootstrap import "
                "get_live_strategies_for_risk_check; "
                # 2. 签名验证
                "import inspect; "
                "sig = inspect.signature(get_live_strategies_for_risk_check); "
                "assert len(sig.parameters) == 0, "
                "f'get_live_strategies_for_risk_check 应零参, 实测 {sig.parameters}'; "
                # 3. daily_pipeline task 注册
                "from app.tasks.daily_pipeline import "
                "risk_daily_check_task, intraday_risk_check_task; "
                "assert risk_daily_check_task.name == 'daily_pipeline.risk_check'; "
                "assert intraday_risk_check_task.name == 'daily_pipeline.intraday_risk_check'; "
                # 4. S1 strategy 可 import + UUID 稳定
                "from backend.engines.strategies.s1_monthly_ranking import S1MonthlyRanking; "
                "assert S1MonthlyRanking.strategy_id == '28fc37e5-2d32-4ada-92e0-41c11a5103d0', "
                "f'S1 UUID drifted: {S1MonthlyRanking.strategy_id}'; "
                # 5. Fallback runtime 可达: force get_sync_conn 抛 ConnectionError.
                # `-c` 单行无法用 `with` 复合语句, 改 patch.start()/stop() 手动管理.
                "from unittest.mock import patch; "
                "p = patch('app.services.strategy_bootstrap.get_sync_conn', "
                "          side_effect=ConnectionError('smoke-force-fallback')); "
                "p.start(); "
                "result = get_live_strategies_for_risk_check(); "
                "p.stop(); "
                "assert len(result) == 1, f'fallback 必返 [S1], 实测 {len(result)} items'; "
                "assert isinstance(result[0], S1MonthlyRanking), "
                "    f'fallback 必是 S1MonthlyRanking, 实测 {type(result[0])}'; "
                "print('OK')"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(project_root),
    )
    assert result.returncode == 0, (
        f"MVP 3.2 批 4 multi-strategy wiring smoke failed:\n"
        f"STDOUT: {result.stdout}\n"
        f"STDERR: {result.stderr}"
    )
    assert "OK" in result.stdout, f"Assertion(s) missing: {result.stdout}"
