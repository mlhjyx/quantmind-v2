#!/usr/bin/env python3
"""SHUTDOWN_NOTICE_2026_04_30 §9 PT 重启 gate prerequisite verifier (read-only).

用途:
    PT 重启 gate prerequisite 7 项 (SHUTDOWN_NOTICE §9 v3 修订后) 逐一 grep /
    psql query, 输出 7 项 status table. 任 1 项 ✗ 阻止 PT 重启.

trigger 条件 (event-driven):
    - 批 2 P0 修启动前 (baseline)
    - 批 2 P0 修完结后 (verify)
    - PT 重启决议时 (final gate check)
    - 任何 SHUTDOWN_NOTICE.md 修订后 verify gate 仍 cover

退出码语义:
    0 = 7/7 项 ✅, PT 重启 gate cleared, user 可决议重启
    1 = 1+ 项 ✗, PT 重启 gate 阻塞
    2 = 脚本自身错

禁止:
    - 任何 mutating SQL
    - 启 PT / Servy start QuantMind-Paper-Trading
    - 改 .env 任何字段
    - 改 cb_state live 真值
    - DELETE position_snapshot 4-28 stale 19 行
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 期望 cash 4-30 14:54 实测 ground truth (D3-C E6 沿用)
EXPECTED_CASH_4_30 = 993520.16
CASH_TOLERANCE = 100.0  # ±100 元 (cash 利息 / 等微漂移)


def _connect_db():
    import psycopg2

    pwd = os.environ.get("PGPASSWORD") or "quantmind"
    return psycopg2.connect(
        host="localhost", user="xin", password=pwd, dbname="quantmind_v2"
    )


def _check_t0_15_ll081_v2() -> tuple[bool, str]:
    """T0-15: LL-081 v2 加 'QMTClient fallback / 持仓查询失败 N 次 → guard'."""
    # grep backend/qm_platform/risk/rules/ + backend/app/services/risk_wiring.py
    risk_dir = PROJECT_ROOT / "backend" / "qm_platform" / "risk" / "rules"
    if not risk_dir.exists():
        return False, f"risk rules dir 不存在: {risk_dir}"

    found = False
    for py_file in risk_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8", errors="ignore")
        if "fallback" in content.lower() and "qmt" in content.lower():
            found = True
            break

    if found:
        return True, "LL-081 v2 fallback / qmt guard 找到"
    return False, "LL-081 v2 fallback / qmt cover 未找到 (T0-15 仍 P0)"


def _check_t0_16_qmt_data_service_fail_loud() -> tuple[bool, str]:
    """T0-16: qmt_data_service.py 改 fail-loud (连续 N min 失败 raise + audit)."""
    qmt_svc = PROJECT_ROOT / "scripts" / "qmt_data_service.py"
    if not qmt_svc.exists():
        return False, f"qmt_data_service.py 不存在: {qmt_svc}"

    content = qmt_svc.read_text(encoding="utf-8")

    # 期望 fail-loud 关键字
    has_fail_loud = (
        "raise" in content
        and "risk_event_log" in content.lower()
        and "consecutive" in content.lower()
    )
    if has_fail_loud:
        return True, "qmt_data_service fail-loud + risk_event_log 找到"

    # 当前 silent skip 模式 (D3-A Step 4 实测)
    return False, "fail-loud + risk_event_log 未找到 (T0-16 仍 P0, 26 天 silent skip 未修)"


def _check_t0_18_beat_schedule_ops_checklist() -> tuple[bool, str]:
    """T0-18: 候选铁律 X9 - schedule 类 PR 必含 post-merge ops checklist."""
    # grep CLAUDE.md 加铁律 X9
    claude_md = PROJECT_ROOT / "CLAUDE.md"
    if not claude_md.exists():
        return False, "CLAUDE.md 不存在"

    content = claude_md.read_text(encoding="utf-8")

    # 期望铁律 43+ 加 schedule restart 强制
    has_x9 = (
        re.search(r"^4[3-9]\.\s.*[Bb]eat.*restart", content, re.MULTILINE) is not None
        or re.search(r"X9.*schedule.*restart", content, re.MULTILINE) is not None
    )
    if has_x9:
        return True, "铁律 X9 schedule restart 强制找到"

    return False, "铁律 X9 (schedule 注释后必 restart) 未入 CLAUDE.md (T0-18 P1)"


def _check_t0_19_emergency_close_hook() -> tuple[bool, str]:
    """T0-19: emergency_close hook + audit chain (沿用 check_t0_19_implementation.py)."""
    audit_py = PROJECT_ROOT / "backend" / "app" / "services" / "t0_19_audit.py"
    if not audit_py.exists():
        return False, "backend/app/services/t0_19_audit.py 不存在 (T0-19 P1)"

    script = PROJECT_ROOT / "scripts" / "emergency_close_all_positions.py"
    content = script.read_text(encoding="utf-8")
    if "write_post_close_audit" not in content:
        return False, "emergency_close hook 未插入 (T0-19 P1)"

    return True, "T0-19 hook + audit module 全在"


def _check_f_d3a_1_migrations() -> tuple[bool, str]:
    """F-D3A-1: 3 missing migrations apply (alert_dedup / platform_metrics / strategy_evaluations)."""
    expected = ["alert_dedup", "platform_metrics", "strategy_evaluations"]

    try:
        conn = _connect_db()
        cur = conn.cursor()
    except Exception as e:
        return False, f"DB connect 失败: {e}"

    missing = []
    for table in expected:
        cur.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=%s)",
            (table,),
        )
        if not cur.fetchone()[0]:
            missing.append(table)

    cur.close()
    conn.close()

    if missing:
        return False, f"missing tables: {', '.join(missing)} (F-D3A-1 P0)"
    return True, "3 expected tables 全 applied"


def _check_db_4_28_stale_cleared() -> tuple[bool, str]:
    """DB 4-28 19 股 stale snapshot 清理 (position_snapshot)."""
    try:
        conn = _connect_db()
        cur = conn.cursor()
    except Exception as e:
        return False, f"DB connect 失败: {e}"

    cur.execute(
        """
        SELECT COUNT(*) FROM position_snapshot
        WHERE trade_date = '2026-04-28'
          AND execution_mode = 'live'
        """
    )
    count = cur.fetchone()[0]
    cur.close()
    conn.close()

    if count == 0:
        return True, "DB 4-28 19 股 stale snapshot 已清"
    return False, f"DB 4-28 仍有 {count} 行 stale (期望 0, gate 阻塞)"


def _check_cb_state_live_reset() -> tuple[bool, str]:
    """cb_state live reset to ¥993,520 (实测真账户值, ±100 容差)."""
    try:
        conn = _connect_db()
        cur = conn.cursor()
    except Exception as e:
        return False, f"DB connect 失败: {e}"

    cur.execute(
        """
        SELECT trigger_metrics
        FROM circuit_breaker_state
        WHERE execution_mode = 'live'
        ORDER BY updated_at DESC LIMIT 1
        """
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    if row is None:
        return False, "circuit_breaker_state 无 live row"

    metrics = row[0] or {}
    nav = metrics.get("nav") if isinstance(metrics, dict) else None

    if nav is None:
        return False, "trigger_metrics.nav 为 None"

    nav = float(nav)
    diff = abs(nav - EXPECTED_CASH_4_30)
    if diff > CASH_TOLERANCE:
        return False, (
            f"cb_state.nav={nav:,.2f} ≠ 真账户 ¥{EXPECTED_CASH_4_30:,.2f} "
            f"(diff={diff:,.2f}, 容差 ±{CASH_TOLERANCE:.0f}). gate 阻塞 (DB stale)."
        )
    return True, f"cb_state.nav={nav:,.2f} 与真账户 ground truth 一致 (diff {diff:,.2f})"


def main() -> int:
    print("=" * 80)
    print("  check_pt_restart_gate — SHUTDOWN_NOTICE_2026_04_30 §9 v3 verifier")
    print("=" * 80)

    checks = [
        ("T0-15 LL-081 v2 (QMT 断连/fallback cover)", _check_t0_15_ll081_v2),
        ("T0-16 qmt_data_service fail-loud", _check_t0_16_qmt_data_service_fail_loud),
        ("T0-18 铁律 X9 (schedule 注释后必 restart)", _check_t0_18_beat_schedule_ops_checklist),
        ("T0-19 emergency_close audit hook", _check_t0_19_emergency_close_hook),
        ("F-D3A-1 3 missing migrations apply", _check_f_d3a_1_migrations),
        ("DB 4-28 19 股 stale snapshot 清理", _check_db_4_28_stale_cleared),
        ("cb_state live reset ¥993,520 (实测真账户)", _check_cb_state_live_reset),
    ]

    print(f"\n  {'#':>2}  {'Check':52} {'Status':12}")
    print("  " + "-" * 78)

    failed = []
    for i, (name, check_fn) in enumerate(checks, 1):
        try:
            passed, detail = check_fn()
        except Exception as e:
            passed, detail = False, f"内部错: {type(e).__name__}: {e}"

        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {i:>2}  {name:52} {status:12}")
        print(f"      └─ {detail}")
        if not passed:
            failed.append(name)

    print("\n" + "=" * 80)
    if failed:
        print(f"  ❌ GATE BLOCKED — {len(failed)}/{len(checks)} prerequisite(s) failed:")
        for name in failed:
            print(f"     - {name}")
        print("\n  PT 重启**禁止** — user 必先修上列项目.")
        print("  ℹ️  另 2 项 (paper-mode 5d dry-run + .env paper→live 显式授权) 是手工 user 决议项, 不在本脚本.")
        print("=" * 80)
        return 1

    print(f"  ✅ GATE CLEARED — 全部 {len(checks)}/{len(checks)} prerequisites ✓")
    print("  PT 重启可决议 (user 仍需手工: paper-mode 5d dry-run + .env paper→live 授权).")
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
