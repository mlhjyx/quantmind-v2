#!/usr/bin/env python3
"""数据质量自动巡检脚本。

每日17:00由Task Scheduler触发，检查当日数据完整性。
异常时通过钉钉发送P1告警。

检查项:
  1. 行数一致性: klines_daily / daily_basic / moneyflow_daily 当日行数互相比对
  2. NULL比例: 关键字段NULL>5%告警
  3. 最新日期: 各表最新trade_date是否=最近交易日（漏拉检测）

用法:
    python scripts/data_quality_check.py              # 自动检测最近交易日
    python scripts/data_quality_check.py --date 2026-03-25  # 指定日期
    python scripts/data_quality_check.py --dry-run    # 只打印不发钉钉
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

import psycopg2

# ── 项目路径 ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.config import settings
from app.services.dispatchers import dingtalk

# ── 日志 ──
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "data_quality_check.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── 配置 ──
ROW_TOLERANCE = 0.08  # 行数偏差容差 ±8%（moneyflow天然少于klines约5-6%）
NULL_THRESHOLD = 0.05  # NULL比例告警阈值 5%
MAX_DATE_LAG = 1  # 最大允许滞后交易日数

# 各表关键字段（用于NULL检查）
NULL_CHECK_FIELDS = {
    "klines_daily": ["close", "volume", "amount"],
    "daily_basic": ["total_mv", "turnover_rate", "pe_ttm"],
    "moneyflow_daily": ["buy_sm_amount", "sell_sm_amount", "net_mf_amount"],
}


def get_connection() -> psycopg2.extensions.connection:
    """从settings解析连接参数，返回psycopg2同步连接。"""
    # DATABASE_URL格式: postgresql+asyncpg://user:pass@host:port/db
    url = settings.DATABASE_URL
    # 去掉driver部分
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    return psycopg2.connect(url)


def get_latest_trading_day(
    cur: psycopg2.extensions.cursor, ref_date: date | None = None
) -> date:
    """获取<=ref_date的最近交易日。"""
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
        raise RuntimeError(f"找不到 <= {ref_date} 的交易日，请检查trading_calendar表")
    return row[0]


def check_row_counts(
    cur: psycopg2.extensions.cursor, trade_date: date
) -> list[str]:
    """检查各表当日行数一致性。返回告警消息列表。"""
    alerts: list[str] = []
    counts: dict[str, int] = {}

    for table in ["klines_daily", "daily_basic", "moneyflow_daily"]:
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

    # 以klines_daily为基准
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
    """检查关键字段NULL比例。返回告警消息列表。"""
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
    cur: psycopg2.extensions.cursor, expected_date: date
) -> list[str]:
    """检查各表最新日期是否为预期交易日。返回告警消息列表。"""
    alerts: list[str] = []

    for table in ["klines_daily", "daily_basic", "moneyflow_daily"]:
        cur.execute(f"SELECT MAX(trade_date) FROM {table}")
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


def send_dingtalk_alert(alerts: list[str], trade_date: date, dry_run: bool = False) -> None:
    """通过钉钉发送告警。"""
    webhook_url = settings.DINGTALK_WEBHOOK_URL
    if not webhook_url:
        logger.warning("DINGTALK_WEBHOOK_URL未配置，跳过钉钉通知")
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


def write_db_alert(conn: psycopg2.extensions.connection, alerts: list[str], trade_date: date) -> None:
    """将告警写入notifications表。"""
    try:
        cur = conn.cursor()
        content = "\n".join(f"- {a}" for a in alerts)
        cur.execute(
            """INSERT INTO notifications (level, category, market, title, content)
               VALUES (%s, %s, %s, %s, %s)""",
            ("P1", "pipeline", "astock", f"数据质量告警 {trade_date}", content),
        )
        conn.commit()
        logger.info("告警已写入notifications表")
    except Exception as e:
        logger.error("写入notifications失败: %s", e)
        conn.rollback()


def main() -> None:
    parser = argparse.ArgumentParser(description="数据质量自动巡检")
    parser.add_argument("--date", type=str, help="指定检查日期 YYYY-MM-DD（默认最近交易日）")
    parser.add_argument("--dry-run", action="store_true", help="试运行，不发钉钉")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("数据质量巡检开始")

    conn = get_connection()
    cur = conn.cursor()

    try:
        # 确定检查日期
        check_date = date.fromisoformat(args.date) if args.date else get_latest_trading_day(cur)
        logger.info("检查日期: %s", check_date)

        # 执行所有检查
        all_alerts: list[str] = []
        all_alerts.extend(check_row_counts(cur, check_date))
        all_alerts.extend(check_null_ratios(cur, check_date))
        all_alerts.extend(check_latest_dates(cur, check_date))

        # 输出结果
        if all_alerts:
            logger.warning("发现 %d 项异常:", len(all_alerts))
            for alert in all_alerts:
                logger.warning("  - %s", alert)

            # 发送钉钉告警
            send_dingtalk_alert(all_alerts, check_date, dry_run=args.dry_run)

            # 写DB
            if not args.dry_run:
                write_db_alert(conn, all_alerts, check_date)
        else:
            logger.info("所有检查通过，数据质量正常")

    finally:
        cur.close()
        conn.close()

    logger.info("数据质量巡检完成")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
