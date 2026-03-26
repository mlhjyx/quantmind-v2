"""PT心跳watchdog — 检测Paper Trading是否今日已运行。

独立于PT主流程，由Task Scheduler每日20:00触发。
如果最近交易日的心跳缺失 → P0钉钉告警。

Sprint 1.11 Task 5。
"""
import json
import logging
import sys
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


def get_latest_trading_day() -> date:
    """获取最近交易日（从trading_calendar表查询）。"""
    from app.services.db import get_sync_conn

    conn = get_sync_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT MAX(cal_date) FROM trading_calendar
               WHERE is_open = TRUE AND cal_date <= CURRENT_DATE"""
        )
        row = cur.fetchone()
        if row and row[0]:
            return row[0] if isinstance(row[0], date) else date.fromisoformat(str(row[0]))
    finally:
        conn.close()
    return date.today()


def send_p0_alert(title: str, content: str) -> None:
    """发送P0钉钉告警。"""
    try:
        from app.services.notification_service import NotificationService
        from app.services.db import get_sync_conn

        conn = get_sync_conn()
        try:
            svc = NotificationService()
            svc.send_sync(conn, "P0", "watchdog", title, content)
            conn.commit()
        finally:
            conn.close()
        logger.info("P0告警已发送: %s", title)
    except Exception as e:
        logger.error("P0告警发送失败: %s (原始告警: %s — %s)", e, title, content)


def check_heartbeat() -> bool:
    """检查PT心跳是否正常。

    Returns:
        True=正常, False=异常（已发告警）。
    """
    if not HEARTBEAT_FILE.exists():
        logger.error("心跳文件不存在: %s", HEARTBEAT_FILE)
        send_p0_alert("PT心跳缺失", f"心跳文件不存在: {HEARTBEAT_FILE}")
        return False

    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.error("心跳文件读取失败: %s", e)
        send_p0_alert("PT心跳文件损坏", str(e))
        return False

    last_date = date.fromisoformat(data["trade_date"])
    latest_td = get_latest_trading_day()

    if last_date < latest_td:
        msg = f"最后心跳: {last_date}, 最近交易日: {latest_td}"
        logger.error("PT今天没跑! %s", msg)
        send_p0_alert("PT今天没跑", msg)
        return False

    logger.info(
        "心跳正常: trade_date=%s, status=%s, completed=%s",
        data.get("trade_date"),
        data.get("status"),
        data.get("completed_at"),
    )
    return True


if __name__ == "__main__":
    ok = check_heartbeat()
    sys.exit(0 if ok else 1)
