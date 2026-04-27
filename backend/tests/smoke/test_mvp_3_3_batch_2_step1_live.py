"""MVP 3.3 batch 2 Step 1 PlatformOrderRouter live smoke (铁律 10b).

subprocess 真启动验证 module-top imports + SDK 实例化 + 基础 route 路径不破.
对齐 batch 1 smoke pattern: LL-052 platform shadow + sys.path 注入.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _build_smoke_code() -> str:
    """LL-052 shadow 修复 + sys.path 注入 + import 链 + smoke route + cancel_stale stub."""
    backend_path_str = str(PROJECT_ROOT / "backend")
    project_root_str = str(PROJECT_ROOT)
    # 多行 Python 脚本 — \n 分隔 (subprocess -c 接受任意内容).
    return "\n".join(
        [
            "import platform as _stdlib_platform",
            "_stdlib_platform.python_implementation()",
            "import sys",
            f"sys.path.insert(0, r'{backend_path_str}')",
            f"sys.path.insert(0, r'{project_root_str}')",
            "from datetime import date",
            "from decimal import Decimal",
            "from backend.qm_platform.signal.router import (",
            "    PlatformOrderRouter, IdempotencyViolation,",
            "    InsufficientCapital, TurnoverCapExceeded, DEFAULT_LOT_SIZE,",
            ")",
            "from backend.qm_platform.signal import PlatformOrderRouter as POR_root",
            "from backend.qm_platform._types import Signal",
            "assert PlatformOrderRouter is POR_root, 'export 不一致 router'",
            "assert DEFAULT_LOT_SIZE == 100, 'lot_size 漂移'",
            "router = PlatformOrderRouter()",
            "assert router.lot_size == 100, 'default lot_size'",
            "assert callable(router.route), 'route 未实现'",
            "assert callable(router.cancel_stale), 'cancel_stale 未实现'",
            # smoke route: 1 signal → 1 order
            "sig = Signal(",
            "    strategy_id='s1', code='600519.SH', target_weight=0.10,",
            "    score=1.0, trade_date=date(2026, 4, 27),",
            "    metadata={'price': 100.0},",
            ")",
            "orders = router.route(",
            "    signals=[sig], current_positions={},",
            "    capital_allocation={'s1': Decimal('1000000')},",
            ")",
            "assert len(orders) == 1, f'expected 1 order, got {len(orders)}'",
            "assert orders[0].side == 'BUY', f'expected BUY, got {orders[0].side}'",
            "assert orders[0].quantity == 1000, f'expected 1000, got {orders[0].quantity}'",
            "assert len(orders[0].order_id) == 16, 'order_id 长度漂移'",
            # cancel_stale stub raise
            "try:",
            "    router.cancel_stale()",
            "    raise AssertionError('cancel_stale 应 raise NotImplementedError')",
            "except NotImplementedError:",
            "    pass",
            "print('OK order router boot')",
        ]
    )


@pytest.mark.smoke
def test_order_router_imports_and_route():
    """subprocess Python 真启动: import + 实例化 + route 1 signal smoke."""
    result = subprocess.run(
        [sys.executable, "-c", _build_smoke_code()],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"smoke failed (exit={result.returncode}): stderr={result.stderr}"
    )
    assert "OK order router boot" in result.stdout, (
        f"missing OK marker: stdout={result.stdout}"
    )
