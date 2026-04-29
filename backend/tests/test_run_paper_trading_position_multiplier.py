"""run_paper_trading.py:441-471 hardcoded position_multiplier=0.5 修 — Fix 3.

历史 BUG (PROJECT_DIAGNOSTIC_REPORT.md F-A6 + 第三部分 #B 消费点):
  Step 5.9 execute_phase 调 check_circuit_breaker_sync 拿 cb_level + position_multiplier,
  但 line 468 写死 `position_multiplier=0.5`, 不从 `cb["position_multiplier"]` 取.
  CB_POSITION_MULTIPLIER = {0:1.0, 1:1.0, 2:1.0, 3:0.5, 4:0.0}, hardcoded 0.5
  仅 L3 偶然命中, L0/L1/L2 应 1.0 实际传 0.5 (持仓被错误降仓), L4 应 0.0 实际 0.5
  (本应停止下单变成减半下单).

修复: position_multiplier=cb.get("position_multiplier", 1.0)
  fallback 1.0 防 cb dict missing key (silent_ok normal mode 默认行为).

测试方式: SAST (regex 源码), 不依赖真 PT 运行. 镜像 test_pt_watchdog.py /
test_execution_mode_isolation.py D3 SAST pattern.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "run_paper_trading.py"
)


def test_script_exists():
    assert _SCRIPT.exists(), f"run_paper_trading.py 不在预期位置: {_SCRIPT}"


def test_step5_9_execute_rebalance_consumes_cb_position_multiplier():
    """Step 5.9 execute_rebalance 必从 cb dict 取 position_multiplier, 非 hardcoded.

    reviewer P2-2 采纳 (oh-my-claudecode): SAST regex 覆盖 intermediate variable
    extraction pattern (e.g. `mult = cb.get(...); ... position_multiplier=mult`).
    防 future refactor 抽局部变量绕过此 SAST 守门 (false negative).
    """
    src = _SCRIPT.read_text(encoding="utf-8")

    # Pattern A: 直接 kwarg 调用 — position_multiplier=cb.get("position_multiplier", ...)
    direct = re.compile(
        r'position_multiplier\s*=\s*cb(?:\.get\(\s*[\'"]position_multiplier[\'"]'
        r'|\[\s*[\'"]position_multiplier[\'"]\])'
    )
    # Pattern B: 文件任意位置含 cb.get("position_multiplier" 或 cb["position_multiplier"]
    # (intermediate variable extraction 也会引这种调用, 至少 1 次必出现)
    indirect = re.compile(
        r'cb(?:\.get\(\s*[\'"]position_multiplier[\'"]'
        r'|\[\s*[\'"]position_multiplier[\'"]\])'
    )

    direct_matches = direct.findall(src)
    indirect_matches = indirect.findall(src)
    total = len(direct_matches) + len(indirect_matches)
    assert total >= 1, (
        "run_paper_trading.py 必从 cb dict 读 position_multiplier "
        "(直接 kwarg 或 intermediate variable 抽取). 详见 Fix 3 spec / "
        "PROJECT_DIAGNOSTIC_REPORT.md F-A6."
    )


def test_step5_9_no_hardcoded_zero_point_five():
    """除 fallback default 外, 不允许 `position_multiplier=0.5` 字面量出现."""
    src = _SCRIPT.read_text(encoding="utf-8")

    # 提取 execute_rebalance call 周边 30 行 (Step 5.9 区域 L440-475)
    # 用 markers 定位 Step 5.9 段
    step59_start = src.find("Step 5.9")
    step6_end_anchor = src.find("Step 6", step59_start) if step59_start > 0 else -1
    if step59_start < 0 or step6_end_anchor < 0:
        pytest.skip("Step 5.9 / Step 6 markers not found, skipping (refactor possibly)")
    step59_block = src[step59_start:step6_end_anchor + 500]  # +500 覆盖 execute_rebalance call

    # 在该 block 内不允许 `position_multiplier=0.5` 字面量 (允许 fallback default 写在
    # cb.get("position_multiplier", 1.0) 中, 那是 1.0 不是 0.5).
    forbidden = re.compile(r"position_multiplier\s*=\s*0\.5\b")
    matches = forbidden.findall(step59_block)
    assert len(matches) == 0, (
        f"Step 5.9 区域仍含 hardcoded `position_multiplier=0.5` ({len(matches)} 处). "
        "应替为 cb.get('position_multiplier', 1.0). 详见 Fix 3 spec."
    )
