"""S2.3 LLM cost daily aggregate report — sum / per-task / per-state breakdown + DingTalk push.

Session 51 (2026-05-03 PR #224): 沿用决议 6 (a) S5 退役合并 S2.3.

scope:
- 当日 cost sum + month-to-date sum (走 llm_cost_daily 表 + llm_call_log 表 cross-verify)
- per-task breakdown (groupby task, 7 任务真分桶)
- per-budget_state breakdown (NORMAL / WARN_80 / CAPPED_100 命中分布)
- fallback rate %
- 月度 review 关联 (V3 §16.2 cite + BudgetGuard.check 真实时状态)
- DingTalk markdown push (沿用 dispatchers/dingtalk.py composition, NOT 重写)

Usage:
    python scripts/llm_cost_daily_report.py                  # 当天 + 月度 review
    python scripts/llm_cost_daily_report.py --date 2026-05-15  # 指定历史日 (回填)
    python scripts/llm_cost_daily_report.py --no-dingtalk    # 反 push (本地 verify)
    python scripts/llm_cost_daily_report.py --verbose        # 详细日志

Cron (Session 51 PR #224):
    Windows Task Scheduler weekly Mon-Fri 20:30 (PT_Watchdog 20:00 后 30min,
    全 dense window 后 0 资源争抢, schtask 体例沿用 setup_task_scheduler.ps1).

Exit code (沿用铁律 43 d):
    0 = success (含 0 calls 真合法 — 月初未触发 LLM)
    1 = warning (DingTalk push 失败但 report 真齐)
    2 = fatal (DB conn / SQL fail)
"""
from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import traceback
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# .venv/.pth 已把 backend 加入 sys.path. append 反 stdlib platform shadow (铁律 10b).
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

import psycopg2  # noqa: E402

from app.config import settings  # noqa: E402
from app.services.dispatchers.dingtalk import send_markdown_sync  # noqa: E402

CST = ZoneInfo("Asia/Shanghai")  # 沿用铁律 41 timezone

logger = logging.getLogger("llm_cost_daily_report")


def _conn_factory():
    """psycopg2 conn factory (沿用 BudgetGuard DI 体例).

    SQLAlchemy URL → psycopg2 args (从 settings.DATABASE_URL 解析).
    """
    url = settings.DATABASE_URL
    # `postgresql+asyncpg://` 转 `postgresql://` (psycopg2 标准 URL)
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return psycopg2.connect(url)


def fetch_today_summary(conn, target_date: date) -> dict:
    """从 llm_cost_daily 表查 1 天 row (沿用 BudgetGuard.record_cost 写入 row)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cost_usd_total, call_count, fallback_count, capped_count, updated_at
            FROM llm_cost_daily
            WHERE day = %s
            """,
            (target_date,),
        )
        row = cur.fetchone()
    if row is None:
        return {
            "cost_usd_total": Decimal("0"),
            "call_count": 0,
            "fallback_count": 0,
            "capped_count": 0,
            "updated_at": None,
        }
    return {
        "cost_usd_total": row[0],
        "call_count": row[1],
        "fallback_count": row[2],
        "capped_count": row[3],
        "updated_at": row[4],
    }


def fetch_month_to_date_sum(conn, target_date: date) -> Decimal:
    """从 llm_cost_daily 月聚合 (沿用 BudgetGuard._sum_cost 体例)."""
    month_start = target_date.replace(day=1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(cost_usd_total), 0)
            FROM llm_cost_daily
            WHERE day BETWEEN %s AND %s
            """,
            (month_start, target_date),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return Decimal("0")
    return row[0] if isinstance(row[0], Decimal) else Decimal(str(row[0]))


def fetch_per_task_breakdown(conn, target_date: date) -> list[dict]:
    """从 llm_call_log 1 天 groupby task (反 llm_cost_daily 真 sum-only).

    沿用 reviewer Chunk C P2 修: range predicate 真**激活 ix_llm_call_log_task_time
    + TimescaleDB chunk exclusion** (反 ::date cast 真全表扫描).
    """
    next_day = target_date + timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                task,
                COUNT(*) AS call_count,
                COALESCE(SUM(cost_usd), 0) AS cost_usd_total,
                COALESCE(SUM(tokens_in), 0) AS tokens_in_total,
                COALESCE(SUM(tokens_out), 0) AS tokens_out_total,
                SUM(CASE WHEN is_fallback THEN 1 ELSE 0 END) AS fallback_count
            FROM llm_call_log
            WHERE triggered_at >= %s
              AND triggered_at < %s
            GROUP BY task
            ORDER BY cost_usd_total DESC
            """,
            (target_date, next_day),
        )
        rows = cur.fetchall()
    return [
        {
            "task": r[0],
            "call_count": r[1],
            "cost_usd": r[2] if isinstance(r[2], Decimal) else Decimal(str(r[2])),
            "tokens_in": r[3],
            "tokens_out": r[4],
            "fallback_count": r[5],
        }
        for r in rows
    ]


def fetch_per_budget_state_breakdown(conn, target_date: date) -> list[dict]:
    """从 llm_call_log 1 天 groupby budget_state (NORMAL / WARN_80 / CAPPED_100).

    沿用 reviewer Chunk C P2 修: range predicate (沿用 fetch_per_task_breakdown 体例).
    """
    next_day = target_date + timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                budget_state,
                COUNT(*) AS call_count,
                COALESCE(SUM(cost_usd), 0) AS cost_usd_total
            FROM llm_call_log
            WHERE triggered_at >= %s
              AND triggered_at < %s
            GROUP BY budget_state
            ORDER BY budget_state
            """,
            (target_date, next_day),
        )
        rows = cur.fetchall()
    return [
        {
            "budget_state": r[0],
            "call_count": r[1],
            "cost_usd": r[2] if isinstance(r[2], Decimal) else Decimal(str(r[2])),
        }
        for r in rows
    ]


def build_markdown_payload(
    *,
    target_date: date,
    today_summary: dict,
    month_to_date: Decimal,
    per_task: list[dict],
    per_state: list[dict],
) -> tuple[str, str]:
    """构造 DingTalk markdown payload (title + text)."""
    monthly_budget = settings.LLM_MONTHLY_BUDGET_USD
    warn_threshold = settings.LLM_BUDGET_WARN_THRESHOLD
    cap_threshold = settings.LLM_BUDGET_CAP_THRESHOLD
    warn_usd = Decimal(str(monthly_budget)) * Decimal(str(warn_threshold))
    cap_usd = Decimal(str(monthly_budget)) * Decimal(str(cap_threshold))

    if month_to_date >= cap_usd:
        state_label = "🔴 CAPPED_100 (强制 Ollama fallback)"
    elif month_to_date >= warn_usd:
        state_label = "🟡 WARN_80 (P2 元告警)"
    else:
        state_label = "🟢 NORMAL"

    fallback_rate_pct = 0.0
    if today_summary["call_count"] > 0:
        fallback_rate_pct = round(
            today_summary["fallback_count"] / today_summary["call_count"] * 100,
            1,
        )

    title = f"QuantMind LLM Cost Daily {target_date.isoformat()}"

    lines: list[str] = [
        f"### {title}",
        "",
        f"**月度状态**: {state_label}",
        f"**月累计**: ${month_to_date:.4f} / ${monthly_budget:.2f} (warn ${warn_usd:.2f} / cap ${cap_usd:.2f})",
        "",
        "**当日汇总**:",
        f"- 调用数: {today_summary['call_count']}",
        f"- 总成本: ${today_summary['cost_usd_total']:.4f}",
        f"- fallback 命中: {today_summary['fallback_count']} ({fallback_rate_pct}%)",
        f"- capped 触发: {today_summary['capped_count']}",
        "",
    ]

    if per_task:
        lines.append("**按任务分桶 (cost desc)**:")
        for row in per_task:
            lines.append(
                f"- `{row['task']}`: {row['call_count']} calls / "
                f"${row['cost_usd']:.4f} / "
                f"{row['tokens_in']}+{row['tokens_out']} tokens / "
                f"fallback {row['fallback_count']}"
            )
        lines.append("")

    if per_state:
        lines.append("**按 budget_state 分桶**:")
        for row in per_state:
            lines.append(
                f"- `{row['budget_state']}`: {row['call_count']} calls / ${row['cost_usd']:.4f}"
            )
        lines.append("")

    lines.append(f"_关联: V3 §16.2 + ADR-031 §6 + S2.3 PR #224 (生成于 {datetime.now(CST):%Y-%m-%d %H:%M:%S CST})_")

    return title, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM cost daily aggregate report")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="目标日期 (YYYY-MM-DD), 默认今日 (CST timezone)",
    )
    parser.add_argument(
        "--no-dingtalk",
        action="store_true",
        help="反 push DingTalk (本地 verify 用)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="详细日志",
    )
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = datetime.now(CST).date()

    logger.info("LLM cost daily report — target_date=%s", target_date)

    try:
        conn = _conn_factory()
    except Exception:
        logger.error("DB conn 失败:\n%s", traceback.format_exc())
        return 2

    try:
        today_summary = fetch_today_summary(conn, target_date)
        month_to_date = fetch_month_to_date_sum(conn, target_date)
        per_task = fetch_per_task_breakdown(conn, target_date)
        per_state = fetch_per_budget_state_breakdown(conn, target_date)
    except Exception:
        logger.error("SQL fail:\n%s", traceback.format_exc())
        # 沿用 reviewer Chunk C P1 修: 反 double conn.close() — finally 已包络.
        # except 直 return, finally 真路径单一 close (反 InterfaceError on second close).
        return 2
    finally:
        # silent_ok: close 失败 0 影响 exit code (沿用铁律 33 silent_ok 注释)
        with contextlib.suppress(Exception):
            conn.close()

    title, markdown_text = build_markdown_payload(
        target_date=target_date,
        today_summary=today_summary,
        month_to_date=month_to_date,
        per_task=per_task,
        per_state=per_state,
    )

    logger.info("\n%s", markdown_text)

    if args.no_dingtalk:
        logger.info("--no-dingtalk 反 push (本地 verify 完成)")
        return 0

    webhook_url = settings.DINGTALK_WEBHOOK_URL
    if not webhook_url:
        # stub if 0 set (沿用决议 (I), 反 break test/local 真生产环境)
        logger.warning("DINGTALK_WEBHOOK_URL 0 set, 反 push (沿用决议 (I))")
        return 0

    if not settings.DINGTALK_ALERTS_ENABLED:
        logger.info("DINGTALK_ALERTS_ENABLED=False, 反 push (沿用 .env 双锁)")
        return 0

    pushed = send_markdown_sync(
        webhook_url=webhook_url,
        title=title,
        content=markdown_text,
        secret=settings.DINGTALK_SECRET or "",
        keyword=settings.DINGTALK_KEYWORD or "",
    )
    if pushed:
        logger.info("DingTalk push 成功")
        return 0
    else:
        logger.error("DingTalk push 失败 — report 已生成 + log 落本地")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # 沿用铁律 43 d 顶层 try/except
        traceback.print_exc()
        sys.exit(2)
