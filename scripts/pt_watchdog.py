"""PT心跳watchdog — 检测Paper Trading链路是否正常运行。

独立于PT主流程，由Task Scheduler每日20:00触发。
检查3个维度:
  1. 心跳文件 — PT脚本运行后写入的状态文件
  2. performance_series — DB中是否有当日NAV记录
  3. signals表 — 信号是否按时生成（调仓日检查）

任一异常 → P0钉钉告警 + 退出码1。

Sprint 1.11 Task 5 → Sprint 1.25 重写（修复SQL列名+增加DB检查）。
"""

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HEARTBEAT_FILE = Path("D:/quantmind-v2/logs/pt_heartbeat.json")


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class HealthReport:
    """综合健康报告。"""

    checks_passed: int = 0
    checks_failed: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.checks_failed == 0

    def fail(self, msg: str) -> None:
        self.errors.append(msg)
        self.checks_failed += 1
        logger.error("FAIL: %s", msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)
        logger.warning("WARN: %s", msg)

    def passed(self, msg: str) -> None:
        self.checks_passed += 1
        logger.info("OK: %s", msg)


# ---------------------------------------------------------------------------
# 数据库查询
# ---------------------------------------------------------------------------


def _get_conn():
    """获取同步数据库连接。"""
    from app.services.db import get_sync_conn

    return get_sync_conn()


def get_latest_trading_day(conn) -> date | None:
    """获取最近交易日（从trading_calendar表查询）。

    DDL列名: trade_date, is_trading_day (非cal_date/is_open)。
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT MAX(trade_date) FROM trading_calendar
           WHERE is_trading_day = TRUE AND trade_date <= CURRENT_DATE
             AND market = 'astock'"""
    )
    row = cur.fetchone()
    cur.close()
    if row and row[0]:
        return row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
    return None


def get_latest_perf_date(conn) -> date | None:
    """查询performance_series最新日期。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT MAX(trade_date) FROM performance_series
           WHERE execution_mode = 'paper'"""
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row and row[0] else None


def get_latest_signal_date(conn) -> date | None:
    """查询signals表最新日期。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT MAX(trade_date) FROM signals
           WHERE execution_mode = 'paper'"""
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row and row[0] else None


def get_perf_gap_days(conn) -> int:
    """计算performance_series最新日期距今的交易日天数。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date > (
                SELECT COALESCE(MAX(trade_date), '2020-01-01')
                FROM performance_series WHERE execution_mode = 'paper'
             )
             AND trade_date <= CURRENT_DATE"""
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# 告警发送
# ---------------------------------------------------------------------------


def send_alert(title: str, content: str) -> None:
    """通过钉钉发送P0告警（直接调用sync发送器，不依赖NotificationService）。"""
    try:
        from app.config import settings
        from app.services.dispatchers.dingtalk import send_markdown_sync

        ok = send_markdown_sync(
            webhook_url=settings.DINGTALK_WEBHOOK_URL,
            title=f"[P0] {title}",
            content=f"## ⚠️ {title}\n\n{content}\n\n> 来源: pt_watchdog",
            secret=settings.DINGTALK_SECRET,
            keyword=settings.DINGTALK_KEYWORD,
        )
        if ok:
            logger.info("钉钉告警已发送: %s", title)
        else:
            logger.warning("钉钉发送返回失败（webhook可能未配置）")
    except Exception as e:
        logger.error("钉钉告警发送异常: %s (原始: %s — %s)", e, title, content)


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


def check_heartbeat_file(report: HealthReport, latest_td: date) -> None:
    """检查1: 心跳文件。"""
    if not HEARTBEAT_FILE.exists():
        report.warn(f"心跳文件不存在: {HEARTBEAT_FILE}（如PT用DB心跳则可忽略）")
        return

    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        report.fail(f"心跳文件损坏: {e}")
        return

    last_date_str = data.get("trade_date", "")
    if not last_date_str:
        report.fail("心跳文件缺少trade_date字段")
        return

    last_date = date.fromisoformat(last_date_str)
    if last_date < latest_td:
        report.fail(f"心跳文件过期: 最后={last_date}, 最近交易日={latest_td}")
    else:
        report.passed(f"心跳文件正常: {last_date}")
    report.details["heartbeat_date"] = str(last_date)


def check_performance_series(report: HealthReport, conn, latest_td: date) -> None:
    """检查2: performance_series是否有最新数据。"""
    perf_date = get_latest_perf_date(conn)
    if perf_date is None:
        report.fail("performance_series表无数据")
        return

    report.details["perf_latest_date"] = str(perf_date)
    gap = get_perf_gap_days(conn)
    report.details["perf_gap_trading_days"] = gap

    if gap == 0:
        report.passed(f"绩效数据正常: 最新={perf_date}")
    elif gap == 1:
        report.warn(f"绩效数据滞后1个交易日: 最新={perf_date}, 今日={latest_td}")
    else:
        report.fail(f"绩效数据缺失{gap}个交易日! 最新={perf_date}, 最近交易日={latest_td}")


def check_signals(report: HealthReport, conn, latest_td: date) -> None:
    """检查3: signals表是否有最新数据。"""
    sig_date = get_latest_signal_date(conn)
    if sig_date is None:
        report.warn("signals表无数据（可能尚未到调仓日）")
        return

    report.details["signal_latest_date"] = str(sig_date)

    # signals不是每日生成（月度调仓），所以只在gap>30天时告警
    diff = (latest_td - sig_date).days
    if diff <= 35:
        report.passed(f"信号数据正常: 最新={sig_date}（距今{diff}天）")
    else:
        report.fail(f"信号数据超过35天未更新: 最新={sig_date}, 距今{diff}天")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def run_watchdog() -> HealthReport:
    """运行全部健康检查。"""
    report = HealthReport()

    conn = _get_conn()
    try:
        latest_td = get_latest_trading_day(conn)
        if latest_td is None:
            report.fail("无法获取最近交易日（trading_calendar表为空或异常）")
            return report

        report.details["latest_trading_day"] = str(latest_td)
        report.details["check_time"] = str(date.today())
        logger.info("最近交易日: %s, 今日: %s", latest_td, date.today())

        check_heartbeat_file(report, latest_td)
        check_performance_series(report, conn, latest_td)
        check_signals(report, conn, latest_td)
    finally:
        conn.close()

    return report


def main() -> int:
    """入口。返回退出码: 0=正常, 1=异常。"""
    logger.info("=" * 60)
    logger.info("PT Watchdog 启动")
    logger.info("=" * 60)

    report = run_watchdog()

    logger.info("-" * 60)
    logger.info(
        "结果: passed=%d, failed=%d, warnings=%d",
        report.checks_passed,
        report.checks_failed,
        len(report.warnings),
    )

    if not report.ok:
        # 发送告警
        error_text = "\n".join(f"- {e}" for e in report.errors)
        warn_text = "\n".join(f"- {w}" for w in report.warnings) if report.warnings else "无"
        detail_text = "\n".join(f"- {k}: {v}" for k, v in report.details.items())

        alert_content = (
            f"**失败项({report.checks_failed}):**\n{error_text}\n\n"
            f"**警告({len(report.warnings)}):**\n{warn_text}\n\n"
            f"**详情:**\n{detail_text}"
        )
        send_alert("PT链路异常", alert_content)
        logger.error("PT Watchdog: FAILED")
        return 1

    if report.warnings:
        logger.warning("PT Watchdog: PASSED with %d warnings", len(report.warnings))
    else:
        logger.info("PT Watchdog: ALL PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
