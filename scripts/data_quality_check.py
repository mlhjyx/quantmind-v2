#!/usr/bin/env python3
"""数据质量自动巡检脚本。

每日由 Task Scheduler 触发 (默认 18:30, 见 scripts/setup_task_scheduler.ps1),
检查当日 klines_daily / daily_basic / moneyflow_daily 数据完整性。异常时通过
钉钉发送 P1 告警 + 写 notifications 表留底。

检查项:
  1. 行数一致性: klines_daily / daily_basic / moneyflow_daily 当日行数互相比对
  2. NULL 比例: 关键字段 NULL>5% 告警
  3. 最新日期: 各表最新 trade_date 是否 = 最近交易日（漏拉检测）
  4. 脏数据守护: MAX(trade_date) > today+7 视为未来日期脏数据 (P0)

铁律 33 fail-loud:
  - PG `statement_timeout=60s` (防 cold-cache COUNT 长挂, 4-22/4-23 hang 根因)
  - `connect_timeout=30s` (防 socket 建立慢)
  - main() top-level try/except → stderr + exit(2), schtask LastResult 非零可告警
  - logger FileHandler `delay=True` 防 Windows 文件锁竞争 (4-23 log 0 行根因)

用法:
    python scripts/data_quality_check.py              # 自动检测最近交易日
    python scripts/data_quality_check.py --date 2026-03-25  # 指定日期
    python scripts/data_quality_check.py --dry-run    # 只打印不发钉钉
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import sys
import traceback
from datetime import date, datetime, timedelta
from pathlib import Path

import psycopg2

# Fail-loud 早期探针 (logger 未初始化时的最后兜底 — 即使 logging FileHandler
# open 失败, schtask stderr 仍可捕获此行)
print(
    f"[data_quality_check] boot {datetime.now().isoformat()} pid={__import__('os').getpid()}",
    flush=True,
    file=sys.stderr,
)

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "backend"))

from app.config import settings  # noqa: E402
from app.services.dispatchers import dingtalk  # noqa: E402

# ── 日志 ──
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "data_quality_check.log"

# FileHandler delay=True: lazy open, 防 Windows 多 process zombie 文件锁
# (4-23 log 0 行事故根因 — 4-22 hang process 被 schtask 5min kill, 但 Windows
# 文件锁延迟释放, 4-23 冷启动 FileHandler open 失败 silent swallow).
_file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8", delay=True)
_stream_handler = logging.StreamHandler()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[_stream_handler, _file_handler],
)
logger = logging.getLogger(__name__)


# ── 配置 ──
ROW_TOLERANCE = 0.08  # 行数偏差容差 ±8%（moneyflow 天然少于 klines 约 5-6%）
NULL_THRESHOLD = 0.05  # NULL 比例告警阈值 5%
MAX_DATE_LAG = 1  # 最大允许滞后交易日数
FUTURE_DATE_GUARD_DAYS = 7  # MAX(trade_date) > today + N 天视为脏数据

# PG 连接硬超时 (铁律 33 fail-loud)
STATEMENT_TIMEOUT_MS = 60_000  # 单 SQL 60s (cold scan 17s × safety 3x)
CONNECT_TIMEOUT_S = 30  # socket 建立 30s

# 各表关键字段（用于 NULL 检查）
NULL_CHECK_FIELDS = {
    "klines_daily": ["close", "volume", "amount"],
    "daily_basic": ["total_mv", "turnover_rate", "pe_ttm"],
    "moneyflow_daily": ["buy_sm_amount", "sell_sm_amount", "net_mf_amount"],
}


def get_connection(
    statement_timeout_ms: int = STATEMENT_TIMEOUT_MS,
    connect_timeout_s: int = CONNECT_TIMEOUT_S,
) -> psycopg2.extensions.connection:
    """从 settings 解析连接参数，返回带 statement_timeout 的 psycopg2 同步连接。

    铁律 33: PG `statement_timeout` 硬超时, 防 cold-cache / table lock 无限
    等待. 超时后 PG raise QueryCanceled, Python 抛 exception, main() 捕获
    退出 exit_code=2.
    """
    url = settings.DATABASE_URL
    # 去掉 async driver 前缀
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(
        url,
        connect_timeout=connect_timeout_s,
        options=f"-c statement_timeout={statement_timeout_ms}",
    )


def get_latest_trading_day(
    cur: psycopg2.extensions.cursor, ref_date: date | None = None
) -> date:
    """获取 <= ref_date 的最近交易日."""
    if ref_date is None:
        ref_date = date.today()
    cur.execute(
        """SELECT trade_date FROM trading_calendar
           WHERE is_trading_day = true AND market = 'astock' AND trade_date <= %s
           ORDER BY trade_date DESC LIMIT 1""",
        (ref_date,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError(f"找不到 <= {ref_date} 的交易日，请检查 trading_calendar 表")
    return row[0]


def check_future_dates(
    cur: psycopg2.extensions.cursor, today: date
) -> list[str]:
    """检测任何表的 MAX(trade_date) > today+N 天 (脏数据/未来日期守护).

    背景: 2026-04-20 至今, klines_daily 有 1 row `TA010.SH @ 2099-04-30`
    (OHLC=10/vol=1000 测试 sentinel), 导致 check_latest_dates 的 MAX 返回
    2099 → `最新日期=2099-04-30 OK` 误报, 掩盖 4-20+ klines 真实滞后.
    """
    alerts: list[str] = []
    cutoff = today + timedelta(days=FUTURE_DATE_GUARD_DAYS)

    for table in ["klines_daily", "daily_basic", "moneyflow_daily"]:
        cur.execute(
            f"SELECT trade_date, COUNT(*) FROM {table} WHERE trade_date > %s "
            "GROUP BY trade_date ORDER BY trade_date",
            (cutoff,),
        )
        rows = cur.fetchall()
        if rows:
            detail = ", ".join(f"{d}×{n}" for d, n in rows)
            alerts.append(
                f"[P0] {table} 发现未来日期脏数据 (>today+{FUTURE_DATE_GUARD_DAYS}d): {detail}"
            )
            logger.error("%s 未来日期: %s", table, detail)
    return alerts


def check_row_counts(
    cur: psycopg2.extensions.cursor, trade_date: date
) -> list[str]:
    """检查各表当日行数一致性. 返回告警消息列表."""
    alerts: list[str] = []
    counts: dict[str, int] = {}

    for table in ["klines_daily", "daily_basic", "moneyflow_daily"]:
        logger.debug("count %s @ %s...", table, trade_date)
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE trade_date = %s",
            (trade_date,),
        )
        counts[table] = cur.fetchone()[0]

    logger.info(
        "行数统计 %s: klines=%d, daily_basic=%d, moneyflow=%d",
        trade_date,
        counts["klines_daily"],
        counts["daily_basic"],
        counts["moneyflow_daily"],
    )

    # 以 klines_daily 为基准
    base = counts["klines_daily"]
    if base == 0:
        alerts.append(f"klines_daily {trade_date} 行数=0，可能未拉取数据")
        return alerts

    for table in ["daily_basic", "moneyflow_daily"]:
        cnt = counts[table]
        if cnt == 0:
            alerts.append(f"{table} {trade_date} 行数=0，数据完全缺失")
            continue
        ratio = abs(cnt - base) / base
        if ratio > ROW_TOLERANCE:
            alerts.append(
                f"{table} {trade_date} 行数偏差过大: "
                f"{cnt} vs klines {base} (偏差{ratio:.1%}, 阈值{ROW_TOLERANCE:.0%})"
            )

    return alerts


def check_null_ratios(
    cur: psycopg2.extensions.cursor, trade_date: date
) -> list[str]:
    """检查关键字段 NULL 比例. 返回告警消息列表."""
    alerts: list[str] = []

    for table, fields in NULL_CHECK_FIELDS.items():
        cur.execute(
            f"SELECT COUNT(*) FROM {table} WHERE trade_date = %s",
            (trade_date,),
        )
        total = cur.fetchone()[0]
        if total == 0:
            continue  # 行数检查已覆盖

        for field in fields:
            cur.execute(
                f"SELECT COUNT(*) FROM {table} WHERE trade_date = %s AND {field} IS NULL",
                (trade_date,),
            )
            null_count = cur.fetchone()[0]
            null_ratio = null_count / total
            if null_ratio > NULL_THRESHOLD:
                alerts.append(
                    f"{table}.{field} {trade_date} NULL比例={null_ratio:.1%} "
                    f"({null_count}/{total}), 阈值{NULL_THRESHOLD:.0%}"
                )
            else:
                logger.debug(
                    "%s.%s NULL比例=%.2f%% (%d/%d) OK",
                    table,
                    field,
                    null_ratio * 100,
                    null_count,
                    total,
                )

    return alerts


def check_latest_dates(
    cur: psycopg2.extensions.cursor, expected_date: date, today: date
) -> list[str]:
    """检查各表最新日期是否为预期交易日.

    使用 effective_max (排除 > today+N 天的脏数据) 做滞后判断, 避免未来日期
    sentinel 掩盖真实滞后. 未来日期 alert 由 check_future_dates 单独负责.
    """
    alerts: list[str] = []
    cutoff = today + timedelta(days=FUTURE_DATE_GUARD_DAYS)

    for table in ["klines_daily", "daily_basic", "moneyflow_daily"]:
        # 只取"有效"范围的 MAX, 排除脏数据 sentinel
        cur.execute(
            f"SELECT MAX(trade_date) FROM {table} WHERE trade_date <= %s",
            (cutoff,),
        )
        max_date = cur.fetchone()[0]
        if max_date is None:
            alerts.append(f"{table} 表为空，无任何数据")
            continue

        if max_date < expected_date:
            # 计算滞后了几个交易日
            cur.execute(
                """SELECT COUNT(*) FROM trading_calendar
                   WHERE is_trading_day = true AND market = 'astock'
                   AND trade_date > %s AND trade_date <= %s""",
                (max_date, expected_date),
            )
            lag = cur.fetchone()[0]
            level = "P0" if lag > MAX_DATE_LAG else "P1"
            alerts.append(
                f"[{level}] {table} 最新日期={max_date}，"
                f"预期={expected_date}，滞后{lag}个交易日"
            )
        else:
            logger.info("%s 最新日期=%s OK", table, max_date)

    return alerts


def send_dingtalk_alert(
    alerts: list[str], trade_date: date, dry_run: bool = False
) -> None:
    """通过钉钉发送告警."""
    webhook_url = settings.DINGTALK_WEBHOOK_URL
    if not webhook_url:
        logger.warning("DINGTALK_WEBHOOK_URL 未配置，跳过钉钉通知")
        return

    title = f"[P1] 数据质量告警 {trade_date}"
    lines = [f"### 数据质量巡检告警 {trade_date}", ""]
    for i, alert in enumerate(alerts, 1):
        lines.append(f"{i}. {alert}")
    lines.append("")
    lines.append(f"---\n*巡检时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    content = "\n".join(lines)

    if dry_run:
        logger.info("[DRY-RUN] 钉钉消息:\n%s", content)
        return

    ok = dingtalk.send_markdown_sync(
        webhook_url=webhook_url,
        title=title,
        content=content,
        secret=settings.DINGTALK_SECRET or "",
        keyword=settings.DINGTALK_KEYWORD or "",
    )
    if ok:
        logger.info("钉钉告警发送成功")
    else:
        logger.error("钉钉告警发送失败")


def write_db_alert(
    conn: psycopg2.extensions.connection, alerts: list[str], trade_date: date
) -> None:
    """将告警写入 notifications 表. Script 级事务管理 (铁律 32 例外 — 非 service)."""
    try:
        cur = conn.cursor()
        content = "\n".join(f"- {a}" for a in alerts)
        cur.execute(
            """INSERT INTO notifications (level, category, market, title, content)
               VALUES (%s, %s, %s, %s, %s)""",
            ("P1", "pipeline", "astock", f"数据质量告警 {trade_date}", content),
        )
        conn.commit()
        logger.info("告警已写入 notifications 表")
    except Exception as e:
        logger.error("写入 notifications 失败: %s", e)
        conn.rollback()


def run_checks(args: argparse.Namespace) -> int:
    """主检查流程. 返回 exit_code (0=OK, 1=发现异常, 2=脚本异常)."""
    logger.info("=" * 60)
    logger.info("数据质量巡检开始 (statement_timeout=%ds)", STATEMENT_TIMEOUT_MS // 1000)

    conn = get_connection()
    cur = conn.cursor()
    today = date.today()

    try:
        # 确定检查日期
        check_date = (
            date.fromisoformat(args.date)
            if args.date
            else get_latest_trading_day(cur, today)
        )
        logger.info("检查日期: %s (today=%s)", check_date, today)

        # 执行所有检查 (每步独立 try, 单步失败不阻塞后续)
        all_alerts: list[str] = []

        for step_name, step_fn in (
            ("future_dates", lambda: check_future_dates(cur, today)),
            ("row_counts", lambda: check_row_counts(cur, check_date)),
            ("null_ratios", lambda: check_null_ratios(cur, check_date)),
            ("latest_dates", lambda: check_latest_dates(cur, check_date, today)),
        ):
            logger.info("→ %s 开始", step_name)
            try:
                step_alerts = step_fn()
                all_alerts.extend(step_alerts)
                logger.info(
                    "← %s 完成, %d 项告警", step_name, len(step_alerts)
                )
            except Exception as e:
                logger.error("✗ %s 异常: %s", step_name, e, exc_info=True)
                all_alerts.append(f"[P0] 检查步骤 {step_name} 异常: {e}")

        # 输出结果
        if all_alerts:
            logger.warning("发现 %d 项异常:", len(all_alerts))
            for alert in all_alerts:
                logger.warning("  - %s", alert)

            # 发送钉钉告警
            send_dingtalk_alert(all_alerts, check_date, dry_run=args.dry_run)

            # 写 DB
            if not args.dry_run:
                write_db_alert(conn, all_alerts, check_date)

            exit_code = 1
        else:
            logger.info("所有检查通过，数据质量正常")
            exit_code = 0

    finally:
        cur.close()
        conn.close()

    logger.info("数据质量巡检完成 exit_code=%d", exit_code)
    logger.info("=" * 60)
    return exit_code


def main() -> int:
    """CLI entrypoint. 铁律 33 fail-loud: 顶层 try/except → stderr + exit(2)."""
    parser = argparse.ArgumentParser(description="数据质量自动巡检")
    parser.add_argument(
        "--date", type=str, help="指定检查日期 YYYY-MM-DD（默认最近交易日）"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="试运行，不发钉钉不写 DB"
    )
    args = parser.parse_args()

    try:
        return run_checks(args)
    except Exception as e:
        # 最后兜底: logger 可能未初始化成功, stderr 必 print
        msg = f"[data_quality_check] FATAL: {type(e).__name__}: {e}"
        print(msg, flush=True, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # silent_ok: 最外层兜底, logger 可能未初始化成功, stderr 已打印
        with contextlib.suppress(Exception):
            logger.critical(msg, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
