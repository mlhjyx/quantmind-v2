"""MVP 3.1 Risk Framework Sunset Gate 30 日监控 (ADR-010 addendum Follow-up #5).

监控 A+B+C 3 条件状态, 满足任一启动批 3b (inline 重审消铁律 31 例外 + 老代码 DROP).

## 条件 (Sunset Gate A+B+C, ADR-010 addendum + Session 30 定义)

| # | 条件 | 必/或 | 验证 |
|---|------|------|------|
| A | adapter live ≥ 30 日 + `risk_event_log.rule_id LIKE 'cb_%'` 真事件 ≥ 1 | 必 | DB query |
| B | 1 次 L4 审批完整跑通 (`approval_queue.status='approved'` + `cb_recover_l0` event) | 必 | DB query |
| C | Wave 4 Observability 启动 (`/risk` dashboard endpoint) | 或 | Feature flag / route grep |

**A+B+C 任一满足 → 启动批 3b**: inline 重审 `CircuitBreakerRule.evaluate` 消铁律 31 例外 +
DROP `circuit_breaker_state` / `circuit_breaker_log` 老表 + `scripts/approve_l4.py` + signal_phase 老触发.

## 调度 (Session 32 待 wire)

- **schtask `QuantMind_MVP31SunsetMonitor`**: 周日 04:00 (低峰 1/week)
- `schtask /create /tn QuantMind_MVP31SunsetMonitor /sc weekly /d SUN /st 04:00 ...`

## 输出

- **stderr boot probe** (铁律 43 c)
- **JSON report** `--json`: 结构化 report (conditions + recommendation)
- **Text human-readable** (default): 中文 summary + 进度条
- **钉钉告警**: 条件首次达成时发 (查 notifications 去重)
- **exit code**: 0=未到 sunset / 1=可启动 批 3b / 2=error (铁律 43 d)

## 关联铁律

- 铁律 33 fail-loud (b): 顶层 try/except → FATAL stderr + exit 2
- 铁律 42: scripts/** 必 PR (本 PR 走完整 9 步闭环)
- 铁律 43: schtask Python 脚本 4 项硬化标准 (statement_timeout / FileHandler delay=True /
  boot probe / 顶层 try/except)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import psycopg2

# ─── Constants ──────────────────────────────────────────────────────────────

# MVP 3.1 批 3 adapter live 首日 (PR #61 merged 2026-04-24T11:25:47Z)
ADAPTER_LIVE_DATE = date(2026, 4, 24)

# Sunset Gate 条件 A: live 天数门槛
CONDITION_A_DAYS_THRESHOLD = 30

# PG statement_timeout (铁律 43 a): weekly 批量不紧 60s, 本监控 30s
PG_STATEMENT_TIMEOUT_MS = 30_000

# notifications category (去重查询用)
DINGTALK_CATEGORY = "mvp_3_1_sunset_gate"

DB_DSN = os.environ.get(
    "MVP_3_1_SUNSET_DSN",
    "dbname=quantmind_v2 user=xin host=127.0.0.1",
)

# 钉钉 webhook (保留但 default None, 首期仅 log report 不主动告警)
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK")

# ─── Logger ─────────────────────────────────────────────────────────────────

LOG_DIR = Path(__file__).resolve().parents[1] / "logs"
LOG_FILE = LOG_DIR / "monitor_mvp_3_1_sunset.log"


def _setup_logger() -> logging.Logger:
    """Setup logger with FileHandler delay=True (铁律 43 b)."""
    logger = logging.getLogger("monitor_mvp_3_1_sunset")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    LOG_DIR.mkdir(exist_ok=True)
    # delay=True 防 Windows 进程 kill 后文件锁延迟冲突
    fh = logging.FileHandler(LOG_FILE, delay=True, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    # Also stderr for schtask capture
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(sh)
    return logger


# ─── Data Models ────────────────────────────────────────────────────────────


@dataclass
class ConditionResult:
    """单条件评估结果."""

    name: str  # "A" | "B" | "C"
    description: str
    satisfied: bool
    details: dict[str, Any] = field(default_factory=dict)
    """具体数字/日期 for debugging + 钉钉告警 + JSON report."""


@dataclass
class SunsetReport:
    """3 条件聚合 report."""

    generated_at: datetime
    adapter_live_date: date
    days_since_activation: int
    condition_a: ConditionResult
    condition_b: ConditionResult
    condition_c: ConditionResult

    @property
    def any_satisfied(self) -> bool:
        """A+B+C 任一满足 → 启动批 3b."""
        return (
            self.condition_a.satisfied
            or self.condition_b.satisfied
            or self.condition_c.satisfied
        )

    @property
    def recommendation(self) -> str:
        if self.any_satisfied:
            return "可启动批 3b (inline 重审消铁律 31 例外 + 老代码 DROP)"
        return f"继续观察 (无条件满足, live {self.days_since_activation} 日)"

    def to_dict(self) -> dict[str, Any]:
        """JSON 序列化 (date/datetime → ISO)."""
        d = asdict(self)
        d["generated_at"] = self.generated_at.isoformat()
        d["adapter_live_date"] = self.adapter_live_date.isoformat()
        d["any_satisfied"] = self.any_satisfied
        d["recommendation"] = self.recommendation
        return d


# ─── Condition checkers (铁律 33 fail-loud on DB errors) ────────────────────


def _connect_db(dsn: str = DB_DSN) -> psycopg2.extensions.connection:
    """Connect PG with statement_timeout (铁律 43 a, 参数化防注入)."""
    conn = psycopg2.connect(dsn)
    with conn.cursor() as cur:
        # parametrized 防 SQL 注入 (reviewer LL-068 沉淀)
        cur.execute("SET statement_timeout = %s", (PG_STATEMENT_TIMEOUT_MS,))
    conn.commit()
    return conn


def check_condition_a(
    conn: Any, today: date, adapter_live: date = ADAPTER_LIVE_DATE
) -> ConditionResult:
    """条件 A: adapter live ≥ 30 日 + risk_event_log.rule_id LIKE 'cb_%' 真事件 ≥ 1.

    "真事件" 定义: risk_event_log 所有 rule_id LIKE 'cb_%' 行均是真触发 (smoke subprocess
    不 write DB, 所以无需 filter test rows).

    Args:
        conn: psycopg2 conn
        today: 今日 date
        adapter_live: adapter 首次 live 日 (默认 PR #61 merge date)

    Returns:
        ConditionResult with days_elapsed, cb_events_count, satisfied
    """
    days_elapsed = (today - adapter_live).days
    days_satisfied = days_elapsed >= CONDITION_A_DAYS_THRESHOLD

    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*), max(created_at) FROM risk_event_log
               WHERE rule_id LIKE 'cb\\_%%' ESCAPE '\\'
                 AND created_at >= %s""",
            (datetime.combine(adapter_live, datetime.min.time(), tzinfo=UTC),),
        )
        row = cur.fetchone()
        events_count = int(row[0]) if row else 0
        latest_event = row[1] if row and row[1] else None

    events_satisfied = events_count >= 1
    satisfied = days_satisfied and events_satisfied

    return ConditionResult(
        name="A",
        description=(
            f"adapter live ≥ {CONDITION_A_DAYS_THRESHOLD} 日 + cb_* 真事件 ≥ 1"
        ),
        satisfied=satisfied,
        details={
            "days_elapsed": days_elapsed,
            "days_threshold": CONDITION_A_DAYS_THRESHOLD,
            "days_satisfied": days_satisfied,
            "cb_events_count": events_count,
            "events_satisfied": events_satisfied,
            "latest_event_at": latest_event.isoformat() if latest_event else None,
            "days_remaining": max(0, CONDITION_A_DAYS_THRESHOLD - days_elapsed),
        },
    )


def check_condition_b(conn: Any) -> ConditionResult:
    """条件 B: 1 次 L4 审批完整跑通 — approval_queue.status='approved' + cb_recover_l0 event.

    完整跑通 = (1) approve_l4.py CLI 更新 `approval_queue` 至 status='approved'
               + (2) 下一次 14:30 daily_risk_check_task 触发 cb_recover_l0 event
               写入 risk_event_log.

    Args:
        conn: psycopg2 conn

    Returns:
        ConditionResult with l4_approved_count, cb_recover_count, satisfied
    """
    with conn.cursor() as cur:
        # B.1: L4 审批通过数
        cur.execute(
            """SELECT count(*), max(reviewed_at) FROM approval_queue
               WHERE approval_type = 'circuit_breaker_l4_recovery'
                 AND status = 'approved'"""
        )
        row = cur.fetchone()
        l4_approved_count = int(row[0]) if row else 0
        latest_approval = row[1] if row and row[1] else None

        # B.2: cb_recover_l0 event count (任何 recovery 事件均计)
        cur.execute(
            """SELECT count(*), max(created_at) FROM risk_event_log
               WHERE rule_id = 'cb_recover_l0'"""
        )
        row = cur.fetchone()
        cb_recover_count = int(row[0]) if row else 0
        latest_recover = row[1] if row and row[1] else None

    # 完整跑通 = 2 者均 ≥ 1
    satisfied = l4_approved_count >= 1 and cb_recover_count >= 1

    return ConditionResult(
        name="B",
        description=(
            "1 次 L4 审批完整跑通 (approval_queue.approved + risk_event_log.cb_recover_l0)"
        ),
        satisfied=satisfied,
        details={
            "l4_approved_count": l4_approved_count,
            "cb_recover_count": cb_recover_count,
            "latest_approval_at": (
                latest_approval.isoformat() if latest_approval else None
            ),
            "latest_recover_at": (
                latest_recover.isoformat() if latest_recover else None
            ),
        },
    )


WAVE_4_FEATURE_FLAG = "wave_4_observability_started"


def check_condition_c(conn: Any) -> ConditionResult:
    """条件 C (或): Wave 4 Observability 启动 — feature_flags 表显式 flag.

    **Session 31 post-dry-run 修正**: 原启发式 `backend/app/api/risk.py` 路径存在检测
    过宽松 (Wave 3 前老 FastAPI risk 路由早就有), 默认 True 在条件 A/B 未满足时
    **false positive 误推批 3b**. 改为显式 feature flag:

    - `feature_flags.name = 'wave_4_observability_started'` AND `enabled = True` → satisfied
    - flag 不存在 / enabled=False → 未满足 (安全默认, 防启发式 false positive)

    Wave 4 MVP 4.x 真启动时通过 `scripts/registry/register_feature_flags.py --enable
    wave_4_observability_started` 手工置 True, 本条件即激活.

    Args:
        conn: psycopg2 conn (真需要, 查 feature_flags 表)

    Returns:
        ConditionResult with flag_enabled, satisfied
    """
    flag_enabled = False
    flag_exists = False
    with conn.cursor() as cur:
        cur.execute(
            "SELECT enabled FROM feature_flags WHERE name = %s",
            (WAVE_4_FEATURE_FLAG,),
        )
        row = cur.fetchone()
        if row is not None:
            flag_exists = True
            flag_enabled = bool(row[0])

    return ConditionResult(
        name="C",
        description=(
            f"Wave 4 Observability 启动 (feature_flag `{WAVE_4_FEATURE_FLAG}`)"
        ),
        satisfied=flag_enabled,
        details={
            "flag_name": WAVE_4_FEATURE_FLAG,
            "flag_exists": flag_exists,
            "flag_enabled": flag_enabled,
            "note": (
                f"Wave 4 MVP 4.x 启动时通过 scripts/registry/register_feature_flags.py"
                f" --enable {WAVE_4_FEATURE_FLAG} 置 True; 未 register 时本条件恒 False"
                " (安全默认, 防启发式 false positive)"
            ),
        },
    )


# ─── Reporting ──────────────────────────────────────────────────────────────


def build_report(conn: Any, today: date | None = None) -> SunsetReport:
    """聚合 3 条件 + 生成 report."""
    today = today or date.today()
    cond_a = check_condition_a(conn, today)
    cond_b = check_condition_b(conn)
    cond_c = check_condition_c(conn)
    return SunsetReport(
        generated_at=datetime.now(UTC),
        adapter_live_date=ADAPTER_LIVE_DATE,
        days_since_activation=(today - ADAPTER_LIVE_DATE).days,
        condition_a=cond_a,
        condition_b=cond_b,
        condition_c=cond_c,
    )


def format_text_report(report: SunsetReport) -> str:
    """human-readable 中文 report."""
    lines = [
        "=" * 60,
        "MVP 3.1 Risk Framework Sunset Gate 监控",
        "=" * 60,
        f"生成时间: {report.generated_at.isoformat()}",
        f"adapter live 首日: {report.adapter_live_date.isoformat()}",
        f"已 live: {report.days_since_activation} 日",
        "",
    ]
    for cond in (report.condition_a, report.condition_b, report.condition_c):
        status = "✅ 满足" if cond.satisfied else "⏳ 未达"
        lines.append(f"【条件 {cond.name}】{cond.description}")
        lines.append(f"  {status}")
        for k, v in cond.details.items():
            lines.append(f"    {k}: {v}")
        lines.append("")
    lines.append("-" * 60)
    lines.append(f"总体: {report.recommendation}")
    lines.append("=" * 60)
    return "\n".join(lines)


def should_send_dingtalk(
    conn: Any, report: SunsetReport, category: str = DINGTALK_CATEGORY
) -> bool:
    """去重: notifications 表已存在 "可启动批 3b" 消息则不重发."""
    if not report.any_satisfied:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM notifications
               WHERE category = %s AND title LIKE '%%可启动批 3b%%'""",
            (category,),
        )
        row = cur.fetchone()
        count = int(row[0]) if row else 0
    return count == 0


def record_dingtalk_alert(
    conn: Any,
    report: SunsetReport,
    title: str,
    content: str,
    category: str = DINGTALK_CATEGORY,
) -> None:
    """写 notifications 表 (钉钉发送单独处理, 这里仅 audit trail)."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO notifications
                   (level, category, market, title, content, is_read, is_acted)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            ("P1", category, "platform", title, content, False, False),
        )
    conn.commit()


# ─── Main ───────────────────────────────────────────────────────────────────


def main() -> int:
    """CLI entry — 铁律 43 (c) boot stderr probe + (d) 顶层 try/except."""
    # 铁律 43 (c) boot probe — stderr 优先 (schtask LastResult 捕获)
    print(
        f"[monitor_mvp_3_1_sunset] boot {datetime.now(UTC).isoformat()} "
        f"pid={os.getpid()}",
        flush=True,
        file=sys.stderr,
    )

    logger = _setup_logger()
    parser = argparse.ArgumentParser(
        description=(
            "MVP 3.1 Risk Framework Sunset Gate 监控 — A+B+C 任一满足启动批 3b."
        )
    )
    parser.add_argument(
        "--json", action="store_true", help="输出 JSON 格式 (stdout)"
    )
    parser.add_argument(
        "--no-dingtalk",
        action="store_true",
        help="不发钉钉 (dry-run 或 CI 用)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="verbose logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    logger.info("监控启动")

    try:
        conn = _connect_db()
        try:
            report = build_report(conn)
        finally:
            conn.close()

        if args.json:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(format_text_report(report))

        logger.info(
            "监控完成: any_satisfied=%s days_live=%d",
            report.any_satisfied,
            report.days_since_activation,
        )

        # 钉钉告警 (首次条件达成时)
        if not args.no_dingtalk and report.any_satisfied:
            with _connect_db() as conn:
                if should_send_dingtalk(conn, report):
                    title = f"MVP 3.1 Sunset Gate 可启动批 3b ({report.days_since_activation}日)"
                    content = format_text_report(report)
                    record_dingtalk_alert(conn, report, title, content)
                    logger.warning(
                        "告警已写 notifications 表 (钉钉 webhook 发送由下游 notifier 异步处理)"
                    )

        # exit code: 0=未到, 1=可启动批 3b, 2=error
        return 1 if report.any_satisfied else 0

    except Exception as exc:  # noqa: BLE001  # 顶层 fail-loud 铁律 43 d
        print(
            f"[monitor_mvp_3_1_sunset] FATAL: {type(exc).__name__}: {exc}",
            file=sys.stderr,
            flush=True,
        )
        traceback.print_exc(file=sys.stderr)
        with suppress(Exception):
            # silent_ok: logger 本身失败已 stderr 兜底
            logger.critical("FATAL: %s", exc, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
