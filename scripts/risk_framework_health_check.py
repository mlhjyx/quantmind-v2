#!/usr/bin/env python3
"""Risk Framework Self-Health Monitor (Phase 0a, MVP 3.1b verification, Session 44).

为什么需要 (Session 44 真生产事件根因之一):
  Risk Framework 30 天 0 触发, 用户 4-29 才发现. 根因之一是**没有元层监控**:
  Beat / Celery worker / 整条 risk task 链如果 silent 挂掉 (network glitch /
  worker crash / Beat schedule 漂移), 用户**无任何告警通道得知**, 与"风控正常但
  当日确实没规则触发"无法区分.

  Phase 2 (PR #144) 加 scheduler_task_log audit 写入后, 本脚本作为 dead-man's-switch
  消费这数据源 — 期望存在的 row 缺失 → P0 钉钉. **本脚本走 schtask, 不走 Celery
  Beat** (要监控 Celery 自己挂的场景, 不能依赖被监控对象).

设计 (与 PR #144 audit 写入互补):
  - 输入: scheduler_task_log (Phase 2 PR #144 已写入)
  - 检查 (3 类 finding):
    1. **Missing** (P0): 交易日期望任务无 row → Beat / worker 挂
    2. **Errored** (P1): row 存在但 status in (error, retry) → 主流程异常
    3. **Stale** (P1): row 存在但 last_run > 期望窗口 → 部分跑了但停了
  - 输出: stdout 表格 + DingTalk P0/P1 (--no-alert dry-run)
  - 触发: schtask 15:30 daily (在 risk_daily_check 14:30 之后, 给足窗口)

铁律 43 4-项硬化 (schtask Python 脚本):
  - (a) PG statement_timeout=60s (默认 60_000ms)
  - (b) FileHandler delay=True (Windows 进程 zombie 锁)
  - (c) main() 首行 stderr boot probe
  - (d) main() top-level try/except → stderr + exit(2)

铁律: 22 / 24 / 25 / 31 / 33 / 41 / 43

用法:
    # Daily check (默认 24h 窗口, 真发钉钉)
    python scripts/risk_framework_health_check.py

    # Dry-run (不发钉钉, 仅 stdout)
    python scripts/risk_framework_health_check.py --no-alert

    # 自定义窗口
    python scripts/risk_framework_health_check.py --window-hours 12

    # 强制触发钉钉测试 (即使无 finding, 也发一条 INFO)
    python scripts/risk_framework_health_check.py --force-trigger
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "backend"))

# ── 日志 (铁律 43-b: delay=True 防 Windows zombie 锁) ──
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "risk_framework_health.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8", delay=True),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

# ── 期望 schedule 契约 (与 beat_schedule.py 对齐) ──
#
# P2 reviewer (PR #145): SSOT-TODO 铁律 34 — 此处 hardcoded 与 backend/app/tasks/
# beat_schedule.py 第二份 SSOT, 若 cron 变更 (e.g. 收盘时间 14:55→15:00) 需手工同步.
# 不直接 import beat_schedule (会拉 Celery app 初始化副作用 + scripts/ 不应依赖
# Celery 模块, 本 script 设计就是脱离 Celery 监控). 维护契约: beat_schedule.py
# 改动 PR 必更新本 EXPECTED_SCHEDULE + 同步 PR commit message 注明.
#
# 每条 (task_name, expected_count_per_trading_day, max_gap_minutes)
# - max_gap_minutes: 自上次 success 到 now 的最大允许 gap, 超过即 stale
# - earliest_check_utc_hour: 当日最早可检查时刻 (UTC), 防 schtask 在 Beat 首发前
#   误报 missing (e.g. intraday Beat 09:35 CST = 01:35 UTC, 检查不能早于 02:00 UTC)
EXPECTED_SCHEDULE = {
    "risk_daily_check": {
        "expected_per_day": 1,
        "max_gap_minutes": 60 * 24 + 60,  # 1 day + 1h tolerance (next day 14:30)
        "trigger_time": "14:30 CST",
        # 14:30 CST = 06:30 UTC, 检查器 schtask 设计 15:30 CST = 07:30 UTC
        "earliest_check_utc_hour": 6,  # 14:00 CST 后才检查
        "severity_on_missing": "P0",
    },
    "intraday_risk_check": {
        "expected_per_day": 72,  # 5min cron × 6h (09:00-14:55)
        "min_per_day": 60,  # 容忍 12 cycle gap (1h restart window)
        "max_gap_minutes": 30,  # 盘中 gap >30min 即 stale (5min cron 应高频)
        "trigger_time": "*/5 9-14 CST",
        # 09:00 CST = 01:00 UTC, 检查不能早于 ~10:00 CST = 02:00 UTC
        # (P2 reviewer 采纳: 防 Mon-am 09:30 检查时 0 cycle 误报 missing)
        "earliest_check_utc_hour": 2,
        "severity_on_missing": "P0",
    },
}


@dataclass
class Finding:
    """单条健康检查异常."""

    severity: str  # P0/P1/P2/INFO
    task_name: str
    kind: str  # 'missing' / 'errored' / 'stale'
    detail: str


def _arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Risk Framework dead-man's-switch (Phase 0a, Session 44)."
    )
    p.add_argument(
        "--window-hours", type=int, default=24,
        help="检查窗口 (h, 默认 24)",
    )
    p.add_argument(
        "--no-alert", action="store_true",
        help="dry-run: 只 stdout, 不发钉钉",
    )
    p.add_argument(
        "--force-trigger", action="store_true",
        help="强制发钉钉 (测试通道, 即使无 finding 也发 INFO)",
    )
    p.add_argument(
        "--statement-timeout-ms", type=int, default=60_000,
        help="PG statement_timeout (ms, 默认 60s, 铁律 43-a)",
    )
    return p


def _open_conn(statement_timeout_ms: int):
    """sync psycopg2 conn, 启用 statement_timeout (铁律 43-a)."""
    from app.services.db import get_sync_conn
    conn = get_sync_conn()
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = %s", (statement_timeout_ms,))
    return conn


def _is_trading_day(conn, today: date) -> tuple[bool, str]:
    """复用 TradingDayChecker (Layer 3 DB calendar)."""
    from engines.trading_day_checker import TradingDayChecker
    checker = TradingDayChecker(conn=conn)
    return checker.is_trading_day(today)


def _check_task(
    conn, task_name: str, spec: dict, now_utc: datetime, window_hours: int,
) -> list[Finding]:
    """对单 task_name 跑 3 类 check (missing / errored / stale)."""
    findings: list[Finding] = []
    cutoff = now_utc - timedelta(hours=window_hours)

    cur = conn.cursor()
    # 总数 + status 分布 + 最新 run
    cur.execute(
        """SELECT status, COUNT(*) FROM scheduler_task_log
            WHERE task_name = %s AND created_at >= %s
            GROUP BY status""",
        (task_name, cutoff),
    )
    status_counts = dict(cur.fetchall())
    total_runs = sum(status_counts.values())

    cur.execute(
        """SELECT MAX(end_time) FROM scheduler_task_log
            WHERE task_name = %s AND status IN ('success', 'skipped', 'disabled')""",
        (task_name,),
    )
    last_success_row = cur.fetchone()
    last_success: datetime | None = last_success_row[0] if last_success_row else None
    cur.close()

    # 1. Missing — 期望 N+ runs, 实测 0 (P0)
    # P2 reviewer 采纳 (PR #145): earliest_check_utc_hour guard 防 Beat 首发前误报
    # (e.g. Mon-am 09:30 CST = 01:30 UTC, intraday Beat 09:00 CST 才刚启, 检查器
    # 跑早了 → 0 row → 误报 P0). 跳过 missing 检查若当前 UTC 早于 earliest.
    earliest_hour = spec.get("earliest_check_utc_hour")
    too_early = (
        earliest_hour is not None and now_utc.hour < earliest_hour
    )

    expected_min = spec.get("min_per_day") or spec.get("expected_per_day", 1)
    if total_runs == 0 and not too_early:
        findings.append(Finding(
            severity=spec["severity_on_missing"],
            task_name=task_name,
            kind="missing",
            detail=(
                f"窗口 {window_hours}h 内 0 行 scheduler_task_log → "
                f"Beat / worker 挂? 期望 ≥{expected_min} runs (trigger={spec['trigger_time']})"
            ),
        ))

    # 2. Errored — status in (error, retry) (P1)
    error_count = status_counts.get("error", 0) + status_counts.get("retry", 0)
    if error_count > 0:
        findings.append(Finding(
            severity="P1",
            task_name=task_name,
            kind="errored",
            detail=(
                f"窗口 {window_hours}h 内 {error_count} 条 error/retry "
                f"(distribution={status_counts})"
            ),
        ))

    # 3. Stale — last success > max_gap_minutes (P1, 部分跑了但停了)
    max_gap = spec["max_gap_minutes"]
    if last_success:
        # last_success 是 timestamp with tz, ensure UTC compare
        if last_success.tzinfo is None:
            last_success = last_success.replace(tzinfo=UTC)
        gap_min = (now_utc - last_success).total_seconds() / 60
        if gap_min > max_gap and total_runs > 0:
            # 同时 missing=False (有 row) but stale → 中途停了
            findings.append(Finding(
                severity="P1",
                task_name=task_name,
                kind="stale",
                detail=(
                    f"上次 success={last_success.isoformat()}, "
                    f"gap={gap_min:.0f}min > 阈值 {max_gap}min → 中途挂 / Beat 漂移"
                ),
            ))

    # 4. Under-count — intraday 期望 72×/日, 但只跑 50× → P1
    # P2 reviewer 采纳: too_early 同样 skip under_count 防早跑误报
    min_runs = spec.get("min_per_day")
    if (
        min_runs and total_runs > 0
        and total_runs < min_runs and not too_early
    ):
        findings.append(Finding(
            severity="P1",
            task_name=task_name,
            kind="under_count",
            detail=(
                f"窗口内 {total_runs} runs < min_per_day={min_runs} "
                f"(期望 ~{spec.get('expected_per_day', '?')}×) → cycles 漏跑"
            ),
        ))

    return findings


def _print_summary(
    findings: list[Finding], today: date, is_td: bool, td_reason: str,
) -> None:
    """stdout 友好打印."""
    print("\n" + "=" * 80)
    print("  Risk Framework Self-Health Monitor (Phase 0a, Session 44)")
    print(f"  Date: {today}  Trading day: {is_td} ({td_reason})")
    print("=" * 80)

    if not findings:
        print("  ✅ 0 findings — Risk Framework heart-beat 全绿")
        print("=" * 80 + "\n")
        return

    by_sev: dict[str, list[Finding]] = {}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)

    for sev in ("P0", "P1", "P2", "INFO"):
        sev_findings = by_sev.get(sev, [])
        if sev_findings:
            print(f"\n  [{sev}] {len(sev_findings)} finding(s):")
            for f in sev_findings:
                print(f"    - task={f.task_name} kind={f.kind}")
                print(f"      detail: {f.detail}")
    print("=" * 80 + "\n")


def _send_dingtalk(
    findings: list[Finding], today: date, force: bool,
    statement_timeout_ms: int = 60_000,
) -> None:
    """钉钉 P0/P1 告警 (经 notification_service.send_sync).

    P1 reviewer 采纳 (PR #145 fix #2): 接受 statement_timeout_ms 参数 +
    apply 到 notification 连接, 不裸开 conn (铁律 43-a). 防 send_sync 内 INSERT
    notifications 卡死时无超时保护.
    """
    from app.services.notification_service import get_notification_service

    p0_count = sum(1 for f in findings if f.severity == "P0")
    p1_count = sum(1 for f in findings if f.severity == "P1")

    # P1 reviewer 采纳 (PR #145 fix #1): 重排条件 — 原 `if force: level=P0` 吃掉了
    # `elif force: level=P3` (永远 unreachable 死代码). 修: force+0 findings 先判,
    # 进 P3 测试通道 (不入库, 仅钉钉 INFO).
    if not findings and force:
        level = "P3"  # force 测试通道, 0 finding 不入库 (notifications 表只 P0/P1/P2)
    elif p0_count > 0:
        level = "P0"
    elif p1_count > 0:
        level = "P1"
    elif force:
        # force=True + has findings 路径: 已被 p0/p1 分支处理, 这里防御性兜底
        level = "P0"
    else:
        return  # no findings, no force → no send

    if not findings and force:
        title = f"[risk-health] {today} 强制测试 (0 findings)"
        content = "通道测试: scheduler_task_log 检查全绿."
    else:
        title = (
            f"[risk-health] {today} P0={p0_count} P1={p1_count} "
            f"({len(findings)} findings 总)"
        )
        content_lines = [
            f"## Risk Framework 自检异常 ({today})\n",
            "### Findings",
        ]
        for f in findings:
            content_lines.append(
                f"- **[{f.severity}]** task=`{f.task_name}` kind=`{f.kind}`"
            )
            content_lines.append(f"  - detail: {f.detail}")
        content_lines.append("\n### 处置建议")
        content_lines.append(
            "- P0 missing: 检查 Celery Beat / worker 是否运行 (servy-cli status)"
        )
        content_lines.append(
            "- P1 errored: 看最近 logs/celery-stderr.log 找异常根因"
        )
        content_lines.append(
            "- P1 stale: 检查最近一次 success time, 之间 cycle 哪挂了"
        )
        content = "\n".join(content_lines)

    # P1 reviewer 采纳 (PR #145 fix #2): 走 _open_conn 应用 statement_timeout (铁律 43-a)
    # 防 notifications INSERT 卡死时无超时. 主 conn 已关 (在 main() finally), 这里只能
    # 开新 conn — 用同 helper 保契约对齐.
    conn = _open_conn(statement_timeout_ms)
    try:
        svc = get_notification_service()
        svc.send_sync(
            conn=conn, level=level, category="risk",
            title=title, content=content, force=force,
        )
        conn.commit()  # script 是事务持有方, send_sync 内不 commit (铁律 32)
        logger.info("[risk-health] DingTalk %s sent: %s", level, title)
    finally:
        conn.close()


def main() -> int:
    # 铁律 43-c: stderr boot probe (即使 logger init 失败也有启动证据)
    print(
        f"[risk-health] boot {datetime.now(UTC).isoformat()} pid={os.getpid()}",
        flush=True, file=sys.stderr,
    )

    args = _arg_parser().parse_args()

    try:
        conn = _open_conn(args.statement_timeout_ms)
        try:
            today = date.today()
            now_utc = datetime.now(UTC)

            is_td, td_reason = _is_trading_day(conn, today)
            if not is_td:
                logger.info("[risk-health] 非交易日 (%s), 无需检查", td_reason)
                _print_summary([], today, is_td, td_reason)
                return 0

            all_findings: list[Finding] = []
            for task_name, spec in EXPECTED_SCHEDULE.items():
                findings = _check_task(
                    conn, task_name, spec, now_utc, args.window_hours,
                )
                all_findings.extend(findings)
        finally:
            conn.close()

        _print_summary(all_findings, today, is_td, td_reason)

        if not args.no_alert and (all_findings or args.force_trigger):
            try:
                _send_dingtalk(
                    all_findings, today, args.force_trigger,
                    statement_timeout_ms=args.statement_timeout_ms,
                )
            except Exception as e:  # noqa: BLE001
                # silent_ok: DingTalk 失败不阻 stdout report (CI 模式仍能消费)
                logger.error(
                    "[risk-health] DingTalk send failed (报警失败但 finding 已 stdout): %s: %s",
                    type(e).__name__, e, exc_info=True,
                )

        # exit code: 0 全绿, 1 有 finding (CI gate)
        if all_findings:
            return 1
        return 0

    except Exception as e:
        # 铁律 43-d: top-level except → stderr + exit(2) → schtask LastResult 非零
        print(
            f"[risk-health] FATAL: {type(e).__name__}: {e}",
            file=sys.stderr, flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        with suppress(Exception):
            logger.critical("[risk-health] FATAL: %s", e, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
