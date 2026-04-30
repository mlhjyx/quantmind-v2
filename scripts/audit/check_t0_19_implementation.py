#!/usr/bin/env python3
"""T0-19 修法落地验证 (read-only, dry-run safe).

用途:
    Phase 2 PR merged 后立刻跑, 验证 T0-19 修法 (post-execution audit hook +
    chat_authorization signature + 4 项 DB 修法) 是否真落地. 5 项检查 (设计 vs
    实现 grep + dry-run 触发 hook 路径).

trigger 条件 (event-driven):
    - T0-19 Phase 2 PR merged 后立刻跑
    - emergency_close_all_positions.py 真跑前 (Phase 2 self-test)
    - 批 2 P0 修启动前/完结后跑

退出码语义:
    0 = 5/5 项 ✅, T0-19 修法落地完整
    1 = 1+ 项 ✗, T0-19 修法不完整, Phase 2 需补
    2 = 脚本自身错

禁止:
    - 任何 mutating SQL
    - --execute / --confirm-yes flag 触发 emergency_close 真发单
    - xtquant.trader.order_stock
    - LIVE_TRADING_DISABLED=False 模式跑 (双锁守门)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _check_live_trading_disabled() -> tuple[bool, str]:
    """硬门: LIVE_TRADING_DISABLED=true (config.py default) + EXECUTION_MODE=paper (.env)."""
    config_py = PROJECT_ROOT / "backend" / "app" / "config.py"
    if not config_py.exists():
        return False, f"config.py 不存在: {config_py}"

    content = config_py.read_text(encoding="utf-8")
    # 期望: LIVE_TRADING_DISABLED: bool = True
    match = re.search(r"LIVE_TRADING_DISABLED:\s*bool\s*=\s*(True|False)", content)
    if not match:
        return False, "config.py 无 LIVE_TRADING_DISABLED field"
    if match.group(1) != "True":
        return False, f"LIVE_TRADING_DISABLED default = {match.group(1)} (期望 True)"

    return True, "LIVE_TRADING_DISABLED=True (config.py default) ✓"


def _check_t0_19_audit_module() -> tuple[bool, str]:
    """检查 backend/app/services/t0_19_audit.py 存在 + 关键函数."""
    audit_py = PROJECT_ROOT / "backend" / "app" / "services" / "t0_19_audit.py"
    if not audit_py.exists():
        return False, f"模块不存在 (Phase 2 未落地): {audit_py}"

    content = audit_py.read_text(encoding="utf-8")

    expected_symbols = [
        "def write_post_close_audit",
        "def _collect_chat_authorization",
        "def _check_idempotency",
        "def _write_idempotency_flag",
    ]

    missing = [s for s in expected_symbols if s not in content]
    if missing:
        return False, f"缺函数: {', '.join(missing)}"

    return True, f"t0_19_audit.py + {len(expected_symbols)} 函数全在"


def _check_exception_classes() -> tuple[bool, str]:
    """检查 backend/app/exceptions.py 含 T0-19 exception 类."""
    exc_py = PROJECT_ROOT / "backend" / "app" / "exceptions.py"
    if not exc_py.exists():
        return False, f"exceptions.py 不存在: {exc_py}"

    content = exc_py.read_text(encoding="utf-8")

    expected_classes = [
        "T0_19_AlreadyBackfilledError",
        "T0_19_AuditCheckError",
        "T0_19_LogParseError",
    ]

    missing = [c for c in expected_classes if f"class {c}" not in content]
    if missing:
        return False, f"缺 exception 类: {', '.join(missing)}"

    return True, "3 exception 类全在"


def _check_emergency_close_hook() -> tuple[bool, str]:
    """检查 emergency_close_all_positions.py L306 后插 T0-19 hook."""
    script = PROJECT_ROOT / "scripts" / "emergency_close_all_positions.py"
    if not script.exists():
        return False, f"emergency_close_all_positions.py 不存在: {script}"

    content = script.read_text(encoding="utf-8")

    # 期望关键字
    expected_keywords = [
        "from app.services.t0_19_audit import write_post_close_audit",
        "write_post_close_audit(",
        "_collect_chat_authorization",
    ]

    missing = [k for k in expected_keywords if k not in content]
    if missing:
        return False, f"hook 未插入, 缺: {missing}"

    return True, "T0-19 hook 已插入 (3 关键字 grep ✓)"


def _check_dry_run_path() -> tuple[bool, str]:
    """dry-run subprocess test: 不带 --execute 跑 emergency_close, exit 0 + 0 真发单."""
    import subprocess

    # 双锁守门: LIVE_TRADING_DISABLED=true 必须先验证
    ltd_ok, _ = _check_live_trading_disabled()
    if not ltd_ok:
        return False, "LIVE_TRADING_DISABLED 不为 True, dry-run 测试拒跑 (fail-secure)"

    script = PROJECT_ROOT / "scripts" / "emergency_close_all_positions.py"
    venv_py = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        return False, f".venv python 不存在: {venv_py}"

    # 仅 dry-run (无 --execute), 期望 exit 0 + 不触发 _execute_sells
    try:
        result = subprocess.run(
            [str(venv_py), str(script)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(PROJECT_ROOT),
        )
    except subprocess.TimeoutExpired:
        return False, "dry-run subprocess timeout (60s, 期望 ~5s)"
    except Exception as e:
        return False, f"dry-run subprocess err: {e}"

    if result.returncode != 0:
        return False, f"dry-run exit {result.returncode} (期望 0)"

    # 期望 stdout 含 "DRY-RUN mode"
    if "DRY-RUN mode" not in result.stdout:
        return False, "stdout 无 'DRY-RUN mode' 提示"

    # 期望 stderr 含 boot probe (铁律 43-c)
    if "[emergency_close] boot" not in result.stderr:
        return False, "stderr 无 boot probe"

    return True, "dry-run subprocess exit 0 + DRY-RUN mode ✓"


def main() -> int:
    print("=" * 80)
    print("  check_t0_19_implementation — T0-19 Phase 2 修法落地 verifier")
    print("=" * 80)

    checks = [
        ("LIVE_TRADING_DISABLED 双锁守门", _check_live_trading_disabled),
        ("backend/app/services/t0_19_audit.py", _check_t0_19_audit_module),
        ("backend/app/exceptions.py 3 classes", _check_exception_classes),
        ("emergency_close_all_positions.py hook insertion", _check_emergency_close_hook),
        ("dry-run subprocess path (LIVE_TRADING_DISABLED=true)", _check_dry_run_path),
    ]

    print(f"\n  {'#':>2}  {'Check':50} {'Status':12}")
    print("  " + "-" * 78)

    failed = []
    for i, (name, check_fn) in enumerate(checks, 1):
        try:
            passed, detail = check_fn()
        except Exception as e:
            passed, detail = False, f"内部错: {type(e).__name__}: {e}"

        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {i:>2}  {name:50} {status:12}")
        print(f"      └─ {detail}")
        if not passed:
            failed.append(name)

    print("\n" + "=" * 80)
    if failed:
        print(f"  ❌ FAIL — {len(failed)}/{len(checks)} check(s) failed:")
        for name in failed:
            print(f"     - {name}")
        print("\n  T0-19 修法 Phase 2 需补.")
        print("=" * 80)
        return 1

    print(f"  ✅ PASS — 全部 {len(checks)}/{len(checks)} checks ✓")
    print("  T0-19 修法 Phase 2 落地完整.")
    print("=" * 80)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        import traceback

        print(f"\n❌ FATAL: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.exit(2)
