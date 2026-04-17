"""Smoke test — MVP 1.3b Platform Layer 1 真实 DB 路径端到端 (铁律 10b).

subprocess 启动 + live PG + 真调 signal_engine._get_direction, 验证:
  1. bootstrap_platform_deps 成功 (DBFactorRegistry + DBFeatureFlag 注入)
  2. use_db_direction=True 命中 (feature_flags 表存在 + enabled)
  3. Layer 1 DB 取值与 pt_live.yaml / FACTOR_DIRECTION hardcoded 一致 (0 drift)

失败意味:
  - DB 不可达 / feature_flags 表缺失 / factor_registry CORE3+dv_ttm 缺失
  - direction 值与 hardcoded 不一致 → Phase 2.4 PT 配置已破坏, 需修 registry
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.smoke
def test_layer1_live_db_direction_matches_hardcoded() -> None:
    """bootstrap + live DB + _get_direction 4 CORE 因子对齐 hardcoded."""
    # 不做 sys.path.insert(0, backend) — 会触发 stdlib platform shadow (MVP 1.1b)
    # 依赖 .venv .pth 已加 project root + backend/
    code = (
        "from app.core.platform_bootstrap import bootstrap_platform_deps\n"
        "from app.logging_config import configure_logging\n"
        "configure_logging()\n"
        "ok = bootstrap_platform_deps()\n"
        "assert ok is True, 'bootstrap failed'\n"
        "from engines import signal_engine as se\n"
        "assert se._PLATFORM_REGISTRY is not None, '_PLATFORM_REGISTRY not injected'\n"
        "assert se._PLATFORM_FLAG_DB is not None, '_PLATFORM_FLAG_DB not injected'\n"
        "# CORE3+dv_ttm (WF OOS Sharpe=0.8659, pt_live.yaml 真相源)\n"
        "expected = {'turnover_mean_20': -1, 'volatility_20': -1, 'bp_ratio': 1, 'dv_ttm': 1}\n"
        "drift = []\n"
        "for f, exp in expected.items():\n"
        "    got = se._get_direction(f)\n"
        "    if got != exp:\n"
        "        drift.append(f'{f}: got {got}, expected {exp}')\n"
        "assert not drift, f'direction drift: {drift}'\n"
        "print('OK', len(expected), 'factors Layer 1 aligned')"
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
            f"Layer 1 live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK 4 factors Layer 1 aligned" in result.stdout, result.stdout
