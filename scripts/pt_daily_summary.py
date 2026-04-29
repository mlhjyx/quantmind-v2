"""PT 每日执行总结 — NAV/PnL/持仓变化 → DingTalk。

Phase 3 自动化 (2026-04-16): 每日 17:35 由 Task Scheduler 触发。
汇总当天 PT 信号生成 + 执行 + NAV + 持仓变化, 推送到 DingTalk。

用法:
    python scripts/pt_daily_summary.py                    # 今天
    python scripts/pt_daily_summary.py --date 2026-04-15  # 指定日期
    python scripts/pt_daily_summary.py --dry-run           # 不发 DingTalk
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
from datetime import date, datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# .venv/.pth 已把 backend 加入 sys.path. 不用 insert(0) 避免与 stdlib `platform`
# 冲突 (铁律 10b shadow fix: backend/platform/ 会 shadow stdlib platform
# 当 sqlalchemy/pandas 通过 import platform → 命中 backend/platform 循环导入
# AttributeError: partially initialized module 'platform' has no attribute
# 'python_implementation'). 本脚本 17:35 schtask 自 Session 32 前每日 LastResult=1
# 根因即此 shadow bug, fix 对齐 compute_ic_rolling.py/compute_daily_ic.py 模式.
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402
from qm_platform.observability import AlertDispatchError  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
_handlers = [logging.FileHandler(LOG_DIR / "pt_daily_summary.log", encoding="utf-8")]
import contextlib

with contextlib.suppress(Exception):
    _handlers.insert(0, logging.StreamHandler(sys.stderr))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=_handlers,
    force=True,
)
logger = logging.getLogger("pt_daily_summary")


def _get_conn():
    """获取 psycopg2 连接。"""
    from app.services.db import get_sync_conn

    return get_sync_conn()


def _is_trading_day(conn, trade_date: date) -> bool:
    """检查是否为交易日。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT is_trading_day FROM trading_calendar
           WHERE trade_date = %s AND market = 'astock'""",
        (trade_date,),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def _get_nav_info(conn, trade_date: date) -> dict | None:
    """获取当日 NAV 和收益数据。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT nav, daily_return, cumulative_return, drawdown, position_count
           FROM performance_series
           WHERE trade_date = %s AND execution_mode = 'live'
           LIMIT 1""",
        (trade_date,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "nav": float(row[0]),
        "daily_return": float(row[1]),
        "cumulative_return": float(row[2]),
        "drawdown": float(row[3]),
        "position_count": int(row[4]),
    }


def _get_trades(conn, trade_date: date) -> list[dict]:
    """获取当日成交记录。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT code, direction, quantity, fill_price
           FROM trade_log
           WHERE trade_date = %s AND execution_mode = 'live'
           ORDER BY created_at""",
        (trade_date,),
    )
    return [
        {"code": r[0], "direction": r[1], "quantity": int(r[2]), "price": float(r[3])}
        for r in cur.fetchall()
    ]


def _get_signal_status(conn, trade_date: date) -> dict:
    """获取信号生成状态。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT status, error_message
           FROM scheduler_task_log
           WHERE task_name = 'signal_phase'
             AND schedule_time::date = %s
           ORDER BY end_time DESC LIMIT 1""",
        (trade_date,),
    )
    row = cur.fetchone()
    if not row:
        return {"signal_status": "not_found", "signal_error": None}
    return {"signal_status": row[0], "signal_error": row[1]}


def _get_pms_triggers(conn, trade_date: date) -> list[dict]:
    """获取 PMS 触发记录。"""
    cur = conn.cursor()
    cur.execute(
        """SELECT symbol, pms_level_triggered, unrealized_pnl_pct, drawdown_from_peak_pct
           FROM position_monitor
           WHERE trigger_date = %s AND pms_level_triggered IS NOT NULL""",
        (trade_date,),
    )
    return [
        {
            "code": r[0],
            "level": f"L{r[1]}" if r[1] else "L?",
            "gain": float(r[2]) if r[2] else 0,
            "dd": float(r[3]) if r[3] else 0,
        }
        for r in cur.fetchall()
    ]


def _get_circuit_breaker(conn) -> dict:
    """获取熔断状态。

    P2.2 batch 3.4 reviewer 顺修: 原 hardcoded execution_mode='paper' 在 Session 20
    cutover 后 silent 永远返 cb_level=0 (live 模式 row 不查). 改读 settings.EXECUTION_MODE
    动态适配 paper/live, 与 _get_latest_perf_date 模式一致.
    """
    from app.config import settings

    cur = conn.cursor()
    cur.execute(
        """SELECT current_level, trigger_reason
           FROM circuit_breaker_state
           WHERE strategy_id = %s AND execution_mode = %s""",
        (settings.PAPER_STRATEGY_ID, settings.EXECUTION_MODE),
    )
    row = cur.fetchone()
    if not row:
        return {"cb_level": 0, "cb_reason": "N/A"}
    return {"cb_level": int(row[0]), "cb_reason": row[1] or ""}


def _format_report(trade_date: date, data: dict) -> str:
    """格式化 DingTalk Markdown 报告。"""
    nav = data.get("nav_info")
    trades = data.get("trades", [])
    signal = data.get("signal")
    pms = data.get("pms_triggers", [])
    cb = data.get("circuit_breaker", {})

    # 标题 emoji
    if nav and nav["daily_return"] >= 0:
        emoji = "📈"
    elif nav:
        emoji = "📉"
    else:
        emoji = "⚠️"

    lines = [f"### {emoji} PT 日报 {trade_date}"]
    lines.append("")

    # NAV 信息
    if nav:
        lines.append("| 指标 | 数值 |")
        lines.append("|------|------|")
        lines.append(f"| NAV | ¥{nav['nav']:,.0f} |")
        lines.append(f"| 日收益 | {nav['daily_return']:+.2%} |")
        lines.append(f"| 累计收益 | {nav['cumulative_return']:+.2%} |")
        lines.append(f"| 回撤 | {nav['drawdown']:.2%} |")
        lines.append(f"| 持仓 | {nav['position_count']}只 |")
    else:
        lines.append("⚠️ 无 NAV 数据 (可能非交易日或执行未完成)")

    # 信号状态
    lines.append("")
    sig_status = signal.get("signal_status", "unknown")
    sig_emoji = "✅" if sig_status == "success" else "❌"
    lines.append(f"**信号生成**: {sig_emoji} {sig_status}")
    if signal.get("signal_error"):
        lines.append(f"  错误: {signal['signal_error'][:100]}")

    # 成交
    if trades:
        buys = [t for t in trades if t["direction"] == "buy"]
        sells = [t for t in trades if t["direction"] == "sell"]
        lines.append("")
        if buys:
            buy_codes = ", ".join(t["code"] for t in buys[:8])
            lines.append(f"**买入({len(buys)})**: {buy_codes}")
        if sells:
            sell_codes = ", ".join(t["code"] for t in sells[:8])
            lines.append(f"**卖出({len(sells)})**: {sell_codes}")
    else:
        lines.append("")
        lines.append("**成交**: 无 (hold)")

    # PMS 触发
    if pms:
        lines.append("")
        lines.append(f"🛡️ **PMS 触发({len(pms)})**:")
        for p in pms[:5]:
            lines.append(f"  - {p['code']} {p['level']} (浮盈{p['gain']:.1%}, 回撤{p['dd']:.1%})")

    # 熔断
    cb_level = cb.get("cb_level", 0)
    if cb_level > 0:
        lines.append("")
        lines.append(f"🚨 **熔断 L{cb_level}**: {cb.get('cb_reason', '')}")

    return "\n".join(lines)


@functools.lru_cache(maxsize=1)
def _get_rules_engine():
    """Cached AlertRulesEngine load (batch 3.x pattern)."""
    from qm_platform.observability import AlertRulesEngine

    try:
        return AlertRulesEngine.from_yaml(PROJECT_ROOT / "configs" / "alert_rules.yaml")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Observability] AlertRulesEngine load failed: %s, fallback", e)
        return None


def _send_alert_via_platform_sdk(title: str, content: str, trade_date: date) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.4)."""
    from datetime import UTC

    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    trade_date_str = str(trade_date)
    alert = Alert(
        title=f"[P1] {title}",
        severity=Severity.P1,  # PT 日报固定 P1 (信息播报, 非紧急)
        source="pt_daily_summary",
        details={
            "trade_date": trade_date_str,
            "content": content,
        },
        trade_date=trade_date_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    engine = _get_rules_engine()
    rule = engine.match(alert) if engine else None
    if rule:
        dedup_key = rule.format_dedup_key(alert)
        suppress_minutes = rule.suppress_minutes
    else:
        dedup_key = f"pt_daily_summary:{trade_date_str}"
        suppress_minutes = None

    router = get_alert_router()
    try:
        result = router.fire(
            alert,
            dedup_key=dedup_key,
            suppress_minutes=suppress_minutes,
        )
        logger.info(
            "[Observability] AlertRouter.fire result=%s key=%s", result, dedup_key
        )
    except AlertDispatchError as e:
        logger.error("[Observability] AlertRouter sink_failed: %s", e)
        raise


def _send_alert_via_legacy_dingtalk(title: str, content: str) -> bool:
    """旧 path: dingtalk dispatcher 直调 (fallback, settings flag=False 时走)."""
    try:
        from app.config import settings
        from app.services.dispatchers.dingtalk import send_markdown_sync

        webhook = settings.DINGTALK_WEBHOOK_URL
        secret = settings.DINGTALK_SECRET
        if not webhook:
            logger.warning("[DingTalk] webhook 未配置, 跳过")
            return False
        keyword = getattr(settings, "DINGTALK_KEYWORD", "")
        return send_markdown_sync(
            webhook_url=webhook,
            title=title,
            content=content,
            secret=secret,
            keyword=keyword,
        )
    except Exception as e:
        logger.error("[DingTalk] 发送失败 (legacy): %s", e)
        return False


def _send_dingtalk(title: str, content: str, trade_date: date | None = None) -> bool:
    """发送 DingTalk (MVP 4.1 batch 3.4 dispatch).

    默认走 PlatformAlertRouter, 旧 dingtalk 直调路径保留作 fallback.
    AlertDispatchError 必传播 (caller catch).
    """
    from app.config import settings

    if settings.OBSERVABILITY_USE_PLATFORM_SDK:
        td = trade_date or date.today()
        _send_alert_via_platform_sdk(title, content, td)
        return True
    return _send_alert_via_legacy_dingtalk(title, content)


def run_daily_summary(trade_date: date, dry_run: bool = False) -> dict:
    """执行每日 PT 总结。"""
    logger.info("=" * 60)
    logger.info("[PT Daily Summary] %s", trade_date)

    conn = _get_conn()

    try:
        if not _is_trading_day(conn, trade_date):
            logger.info("%s 非交易日, 跳过", trade_date)
            return {"status": "skipped", "reason": "non_trading_day"}

        data = {
            "nav_info": _get_nav_info(conn, trade_date),
            "trades": _get_trades(conn, trade_date),
            "signal": _get_signal_status(conn, trade_date),
            "pms_triggers": _get_pms_triggers(conn, trade_date),
            "circuit_breaker": _get_circuit_breaker(conn),
        }

        report = _format_report(trade_date, data)
        logger.info("报告内容:\n%s", report)

        if not dry_run:
            nav = data["nav_info"]
            ret_str = f"{nav['daily_return']:+.2%}" if nav else "N/A"
            # batch 3.4 (P1.1 模式): AlertDispatchError 单 catch
            try:
                _send_dingtalk(f"PT日报 {trade_date} {ret_str}", report, trade_date)
                logger.info("[DingTalk] 日报已发送")
            except AlertDispatchError as e:
                logger.error(
                    "[Observability] AlertDispatchError — 日报未送达, 主流程继续: %s", e
                )
        else:
            logger.info("[DRY-RUN] 不发送 DingTalk")

        return {"status": "success", "data": data}

    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="PT 每日执行总结 → DingTalk")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="不发 DingTalk")
    args = parser.parse_args()

    if args.date:
        trade_date = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        trade_date = date.today()

    run_daily_summary(trade_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
