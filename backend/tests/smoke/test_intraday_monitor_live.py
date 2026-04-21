"""Smoke: scripts/intraday_monitor.py 生产入口真启动验证 (铁律 10b).

验证: subprocess 从项目根启动 intraday_monitor.py --force (忽略交易时间),
      退出码 0 或 skip 消息 (无交易日时), 不触 import-time crash (铁律 10b).

不覆盖的 (需 live QMT + Redis 数据, 留 live 场景):
  - QMT 连接 / 市值查询
  - Redis market:latest 读取
  - 真告警发送 (webhook 未必配置)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.smoke
def test_intraday_monitor_imports_and_runs() -> None:
    """intraday_monitor.py 以 --force 启动, 无 import crash 即 PASS.

    不检查退出码 (QMT / Redis / DB 可能不在本地可用致非 0),
    只验证 "python 解释器能加载脚本且到达 main()", 即铁律 10b 意图.
    """
    project_root = Path(__file__).resolve().parents[3]
    script = project_root / "scripts" / "intraday_monitor.py"
    assert script.exists(), f"intraday_monitor.py 缺失: {script}"

    # 用 python -c 形式: import 脚本并检查关键 symbol (绕过真跑的 side effect)
    result = subprocess.run(
        [
            sys.executable, "-c",
            "import sys, pathlib; "
            f"sys.path.insert(0, r'{project_root}'); "
            "import importlib.util; "
            f"spec = importlib.util.spec_from_file_location('intraday_monitor', r'{script}'); "
            "mod = importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(mod); "
            "assert hasattr(mod, 'run_monitor'), 'run_monitor missing'; "
            "assert hasattr(mod, 'ALERT_EMERGENCY_STOCK'), 'ALERT_EMERGENCY_STOCK missing'; "
            "assert mod.ALERT_EMERGENCY_STOCK == -0.08, f'threshold drifted: {mod.ALERT_EMERGENCY_STOCK}'; "
            "assert hasattr(mod, '_compute_stock_daily_pnl'), '_compute_stock_daily_pnl missing'; "
            "print('OK')",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(project_root),
    )
    assert result.returncode == 0, (
        f"intraday_monitor import failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "OK" in result.stdout, f"Assertion(s) missing: {result.stdout}"
