"""PT心跳watchdog — 检测Paper Trading链路是否正常运行。

独立于PT主流程，由Task Scheduler每日20:00触发。
检查3个维度:
  1. 心跳文件 — PT脚本运行后写入的状态文件
  2. performance_series — DB中是否有当日NAV记录
  3. signals表 — 信号是否按时生成（调仓日检查）

任一异常 → P0钉钉告警 + 退出码1。

Sprint 1.11 Task 5 → Sprint 1.25 重写（修复SQL列名+增加DB检查）。
"""

import contextlib
import functools
import json
import logging
import os
import sys
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

# 添加项目路径
sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

# Platform SDK 顶层 import (batch 3.x pattern, 防 import-in-try NameError).
from qm_platform.observability import AlertDispatchError  # noqa: E402

# Session 26 LL-068 defense-in-depth: FileHandler delay=True 防 Windows zombie 文件锁.
LOG_DIR = Path("D:/quantmind-v2/logs")
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "pt_watchdog.log", encoding="utf-8", delay=True),
    ],
)
logger = logging.getLogger(__name__)

HEARTBEAT_FILE = LOG_DIR / "pt_heartbeat.json"

# PG 连接硬超时 (铁律 33 fail-loud, LL-068 pattern 扩散)
STATEMENT_TIMEOUT_MS = 60_000


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
    """获取同步数据库连接, 注入 session-level statement_timeout (LL-068).

    防 cold-cache / table lock 无限等待, 超时后 PG raise QueryCanceled,
    main() 顶层 try/except 捕获 exit(2) 触发 schtask 钉钉告警链.
    """
    from app.services.db import get_sync_conn

    conn = get_sync_conn()
    # reviewer python-P1: parametrize %s 而非 f-string (bandit B608 未来兼容).
    # psycopg2 autocommit=False 默认, SET 在当前 transaction 中, 后续 queries 共享
    # 同 transaction 所以 timeout 实际生效 (session GUC 机制).
    with conn.cursor() as cur:
        cur.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
    return conn


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
           WHERE execution_mode IN ('paper', 'live')"""
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row and row[0] else None


def get_latest_signal_date(conn) -> date | None:
    """查询signals表最新日期。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT MAX(trade_date) FROM signals
           WHERE execution_mode IN ('paper', 'live')"""
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row and row[0] else None


def get_perf_gap_days(conn) -> int:
    """计算performance_series最新日期距今的交易日天数。

    F21 修 (2026-04-20 Session 20→21): 原 `WHERE execution_mode = 'paper'` 与
    ``get_latest_perf_date`` (L100-101) 的 ``IN ('paper', 'live')`` 读取不对称,
    paper namespace 0 行时 fallback 至 '2020-01-01' 致 gap=1524 假警, 20:00
    钉钉误报 "PT链路异常" (Session 10 P0-β 第 3 残留).

    Note (caller precondition): 调用方 ``check_performance_series`` (L201-204)
    先调 ``get_latest_perf_date`` 并在返 None 时 ``report.fail`` 早 return,
    本函数只在 perf_series 非空时调用. 若独立调用 0 行 DB, COALESCE fallback
    '2020-01-01' 仍产生 gap≈1524 假警 — 未来新调用方必须先验证 perf_series
    非空 (铁律 33 fail-loud).
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT COUNT(*) FROM trading_calendar
           WHERE market = 'astock' AND is_trading_day = TRUE
             AND trade_date > (
                SELECT COALESCE(MAX(trade_date), '2020-01-01')
                FROM performance_series WHERE execution_mode IN ('paper', 'live')
             )
             AND trade_date <= CURRENT_DATE"""
    )
    row = cur.fetchone()
    cur.close()
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# 告警发送
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _get_rules_engine():
    """Cached AlertRulesEngine load (batch 3.x pattern)."""
    from qm_platform.observability import AlertRulesEngine

    project_root = Path(__file__).resolve().parent.parent
    try:
        return AlertRulesEngine.from_yaml(project_root / "configs" / "alert_rules.yaml")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Observability] AlertRulesEngine load failed: %s, fallback", e)
        return None


def _send_alert_via_platform_sdk(title: str, content: str) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.4)."""
    from datetime import UTC, datetime

    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router
    # AlertDispatchError 已 module-level top-import (line 29), 不重复 (P2.1 reviewer)

    today_str = str(date.today())
    full_content = f"## ⚠️ {title}\n\n{content}\n\n> 来源: pt_watchdog"
    alert = Alert(
        title=f"[P0] {title}",
        severity=Severity.P0,  # pt_watchdog 全 P0 (PT 链路异常 = 真金风险)
        source="pt_watchdog",
        details={
            "trade_date": today_str,
            "check": title,
            "content": full_content,
        },
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    engine = _get_rules_engine()
    rule = engine.match(alert) if engine else None
    if rule:
        dedup_key = rule.format_dedup_key(alert)
        suppress_minutes = rule.suppress_minutes
    else:
        dedup_key = f"pt_watchdog:summary:{today_str}"
        suppress_minutes = None

    router = get_alert_router()
    try:
        result = router.fire(
            alert,
            dedup_key=dedup_key,
            suppress_minutes=suppress_minutes,
        )
        logger.info(
            "[Observability] AlertRouter.fire result=%s key=%s title=%s",
            result,
            dedup_key,
            title,
        )
    except AlertDispatchError as e:
        logger.error("[Observability] AlertRouter sink_failed: %s", e)
        raise


def _send_alert_via_legacy_dingtalk(title: str, content: str) -> None:
    """旧 path: dingtalk dispatcher 直调 (fallback, settings flag=False 时走)."""
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
            logger.info("钉钉告警已发送: %s (legacy)", title)
        else:
            logger.warning("钉钉发送返回失败 (legacy, webhook 可能未配置)")
    except Exception as e:
        logger.error("钉钉告警发送异常 (legacy): %s (原始: %s — %s)", e, title, content)


def send_alert(title: str, content: str) -> None:
    """通过钉钉发送 P0 告警 (MVP 4.1 batch 3.4 dispatch).

    默认走 PlatformAlertRouter, 旧 dingtalk 直调路径保留作 fallback.
    AlertDispatchError 必传播 (caller catch).
    """
    from app.config import settings

    if settings.OBSERVABILITY_USE_PLATFORM_SDK:
        _send_alert_via_platform_sdk(title, content)
    else:
        _send_alert_via_legacy_dingtalk(title, content)


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


def _run() -> int:
    """实际执行流程 (主 logic). 顶层 try/except 由 main() 包裹."""
    logger.info("=" * 60)
    logger.info("PT Watchdog 启动 (statement_timeout=%ds)", STATEMENT_TIMEOUT_MS // 1000)
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
        # batch 3.4 (P1.1 batch 3.1 模式): AlertDispatchError 单 catch.
        # PT 链路异常本身就是 P0 真金风险, sink 失败不应 swallow exit_code=1 信号.
        try:
            send_alert("PT链路异常", alert_content)
        except AlertDispatchError as e:
            logger.error(
                "[Observability] AlertDispatchError — 告警未送达, exit_code=1 仍反映 PT 异常: %s",
                e,
            )
        logger.error("PT Watchdog: FAILED")
        return 1

    if report.warnings:
        logger.warning("PT Watchdog: PASSED with %d warnings", len(report.warnings))
    else:
        logger.info("PT Watchdog: ALL PASSED")
    return 0


def main() -> int:
    """CLI entrypoint. 铁律 33 fail-loud (LL-068 扩散):
    - boot stderr probe (schtask 最早启动证据, 即使 logger 失败)
    - 顶层 try/except → stderr FATAL + exit(2) 触发 schtask 钉钉告警
    """
    # Fail-loud boot 探针 (reviewer python-P2: os 已 module-top import 替原 __import__)
    print(
        f"[pt_watchdog] boot {datetime.now().isoformat()} pid={os.getpid()}",
        flush=True,
        file=sys.stderr,
    )
    try:
        return _run()
    except Exception as e:
        msg = f"[pt_watchdog] FATAL: {type(e).__name__}: {e}"
        print(msg, flush=True, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # silent_ok: 最外层兜底, logger 可能未初始化成功
        with contextlib.suppress(Exception):
            logger.critical(msg, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
