#!/usr/bin/env python3
"""盘中风控监控 — 每5分钟检查组合市值 + 单股急跌，日内告警。

通过miniQMT实时查询持仓市值，与昨日收盘市值比较计算日内涨跌幅。
告警规则:
  组合跌>3%: P1钉钉告警
  组合跌>5%: P0钉钉告警
  组合跌>8%: P0告警 + 日志标记"建议减仓"
  单股跌>8%: P1钉钉告警 (ADR-010 过渡期保护, 每股每日限1次)
  QMT断连: P0告警

调度: 交易日 09:35-15:00，每5分钟（Task Scheduler重复触发）。
非交易日/非交易时间自动跳过。

ADR-010 过渡期 (Risk Framework MVP 3.1 落地前):
  单股急跌规则是临时保险丝, 走 Redis market:latest + klines_daily 前日 close 自算
  pnl, 与 Risk Framework MVP 3.1 批 2 迁移后的 PortfolioDropXpct 规则合并.

用法:
    python scripts/intraday_monitor.py
    python scripts/intraday_monitor.py --force   # 忽略交易时间检查
"""

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

# xtquant双层嵌套路径修复（append不insert，避免其旧numpy覆盖venv版本）
_venv = Path(__file__).resolve().parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"
if _venv.exists() and str(_venv) not in sys.path:
    sys.path.append(str(_venv))

import structlog

from app.config import settings

logger = structlog.get_logger("intraday_monitor")

# ── 告警阈值 ──
ALERT_P1_THRESHOLD = -0.03   # 组合跌3%
ALERT_P0_THRESHOLD = -0.05   # 组合跌5%
ALERT_P0_REDUCE    = -0.08   # 组合跌8% 建议减仓
LIMIT_DOWN_PCT     = -0.095  # 单股接近跌停
ALERT_EMERGENCY_STOCK = -0.08  # 单股当日跌>8% P1 告警 (ADR-010 过渡期, Risk Framework MVP 3.1 前)


def is_trading_hours(now: datetime | None = None) -> bool:
    """检查当前是否在交易时间内(9:25-15:05)。"""
    now = now or datetime.now()
    t = now.time()
    from datetime import time as dt_time
    return dt_time(9, 25) <= t <= dt_time(15, 5)


def is_trading_day_today() -> bool:
    """从DB查询今天是否交易日。"""
    import psycopg2
    try:
        conn = psycopg2.connect(
            dbname="quantmind_v2", user="xin",
            password="quantmind", host="localhost",
        )
        cur = conn.cursor()
        cur.execute(
            """SELECT is_trading_day FROM trading_calendar
               WHERE market = 'astock' AND trade_date = %s""",
            (date.today(),),
        )
        row = cur.fetchone()
        conn.close()
        return bool(row and row[0])
    except Exception as e:
        logger.warning(f"交易日查询失败: {e}")
        return False


def get_prev_close_mv() -> float | None:
    """获取昨日收盘总市值(从performance_series)。"""
    import psycopg2
    try:
        conn = psycopg2.connect(
            dbname="quantmind_v2", user="xin",
            password="quantmind", host="localhost",
        )
        cur = conn.cursor()
        # 先尝试live模式，fallback到paper
        for mode in ["live", "paper"]:
            cur.execute(
                """SELECT nav FROM performance_series
                   WHERE strategy_id = %s AND execution_mode = %s
                   ORDER BY trade_date DESC LIMIT 1""",
                (settings.PAPER_STRATEGY_ID, mode),
            )
            row = cur.fetchone()
            if row and row[0]:
                conn.close()
                return float(row[0])
        conn.close()
        return None
    except Exception as e:
        logger.error(f"获取昨日市值失败: {e}")
        return None


def query_qmt_positions() -> tuple[float, list[dict]] | None:
    """通过QMT查询当前持仓总市值和个股明细。

    Returns:
        (total_mv, positions_list) 或 None(连接失败)。
    """
    try:
        qmt_path = settings.QMT_PATH
        account_id = settings.QMT_ACCOUNT_ID
        if not qmt_path or not account_id:
            logger.error("QMT_PATH或QMT_ACCOUNT_ID未配置")
            return None

        # 设置环境让qmt_manager识别live模式
        os.environ["EXECUTION_MODE"] = "live"

        from engines.broker_qmt import MiniQMTBroker

        broker = MiniQMTBroker(qmt_path, account_id)
        broker.connect()

        asset = broker.query_asset()
        total_mv = asset.get("total_asset", 0.0)

        positions = broker.query_positions()
        broker.disconnect()

        return total_mv, positions

    except Exception as e:
        logger.error(f"QMT查询失败: {e}")
        return None


def send_alert(level: str, title: str, content: str) -> None:
    """发送钉钉告警（直接HTTP调用，不依赖Service层）。"""
    import httpx
    webhook = settings.DINGTALK_WEBHOOK_URL
    if not webhook:
        logger.warning("DINGTALK_WEBHOOK_URL未配置，跳过告警")
        return
    try:
        text = f"[{level}] {title}\n{content}"
        resp = httpx.post(webhook, json={"msgtype": "text", "text": {"content": text}}, timeout=10)
        logger.info(f"[DingTalk] {level} 告警已发送: {resp.status_code}")
    except Exception as e:
        logger.error(f"告警发送失败: {e}")


# ── ADR-010 过渡期: 单股急跌检测 helpers ──

def _get_prev_close(code: str) -> float | None:
    """从 klines_daily 查单股前一交易日收盘价。"""
    import psycopg2
    try:
        conn = psycopg2.connect(
            dbname="quantmind_v2", user="xin",
            password="quantmind", host="localhost",
        )
        cur = conn.cursor()
        cur.execute(
            """SELECT close FROM klines_daily
               WHERE code = %s AND trade_date < %s
               ORDER BY trade_date DESC LIMIT 1""",
            (code, date.today()),
        )
        row = cur.fetchone()
        conn.close()
        return float(row[0]) if row and row[0] else None
    except Exception as e:
        logger.warning(f"_get_prev_close failed for {code}: {e}")
        return None


def _get_current_price(code: str) -> float | None:
    """从 Redis market:latest:{code} 读当前价。"""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        raw = r.get(f"market:latest:{code}")
        if not raw:
            return None
        data = json.loads(raw)
        # MVP 2.1c Sub3 contract v2 用 price, 旧格式兼容 last_price
        price = float(data.get("price") or data.get("last_price") or 0)
        return price if price > 0 else None
    except Exception as e:
        logger.warning(f"_get_current_price failed for {code}: {e}")
        return None


def _compute_stock_daily_pnl(code: str) -> float | None:
    """单股当日涨跌幅 = (current - prev_close) / prev_close. 任一数据缺失返 None."""
    current = _get_current_price(code)
    if current is None:
        return None
    prev_close = _get_prev_close(code)
    if prev_close is None or prev_close <= 0:
        return None
    return (current - prev_close) / prev_close


def _emergency_dedup_key(code: str) -> str:
    """Redis key 用于同股同日 emergency 告警 dedup."""
    return f"intraday_alerted:emergency:{code}:{date.today().isoformat()}"


def _already_alerted_emergency(code: str) -> bool:
    """查 Redis 是否同股同日已告警 (24h TTL). fail-safe: 异常返 False (宁重复不漏报)."""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        return r.exists(_emergency_dedup_key(code)) > 0
    except Exception:
        return False  # silent_ok: Redis 失败时允许告警, 保告警覆盖优先于去重


def _mark_alerted_emergency(code: str) -> None:
    """标记同股同日已告警 (TTL 86400s 自动清)."""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        r.setex(_emergency_dedup_key(code), 86400, "1")
    except Exception as e:
        logger.warning(f"_mark_alerted_emergency failed for {code}: {e}")


def save_monitor_log(
    total_mv: float | None,
    prev_mv: float | None,
    pnl_pct: float | None,
    alert_level: str | None,
    alerts: list[str],
) -> None:
    """写入intraday_monitor_log表。"""
    import psycopg2
    try:
        conn = psycopg2.connect(
            dbname="quantmind_v2", user="xin",
            password="quantmind", host="localhost",
        )
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO intraday_monitor_log
               (total_mv, prev_close_mv, daily_pnl_pct, alert_level, alerts_json)
               VALUES (%s, %s, %s, %s, %s)""",
            (total_mv, prev_mv, pnl_pct, alert_level, json.dumps(alerts, ensure_ascii=False)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"监控日志写入失败: {e}")


def run_monitor(force: bool = False) -> None:
    """执行一次盘中监控检查。"""
    now = datetime.now()

    # 1. 交易时间+交易日检查
    if not force:
        if not is_trading_hours(now):
            logger.info("非交易时间，跳过")
            return
        if not is_trading_day_today():
            logger.info("非交易日，跳过")
            return

    logger.info(f"[IntradayMonitor] 开始检查 {now.strftime('%H:%M:%S')}")

    alerts: list[str] = []
    alert_level: str | None = None

    # 2. 获取昨日收盘市值
    prev_mv = get_prev_close_mv()
    if prev_mv is None or prev_mv <= 0:
        logger.warning("无法获取昨日市值, 跳过")
        save_monitor_log(None, None, None, None, ["无昨日市值数据"])
        return

    # 3. 查询QMT当前市值
    result = query_qmt_positions()
    if result is None:
        alerts.append("QMT连接失败")
        alert_level = "P0"
        send_alert("P0", f"QMT断连 {now.strftime('%H:%M')}",
                    "盘中监控: miniQMT连接失败, 无法获取实时市值")
        save_monitor_log(None, prev_mv, None, alert_level, alerts)
        return

    total_mv, positions = result
    pnl_pct = (total_mv - prev_mv) / prev_mv if prev_mv > 0 else 0.0

    logger.info(
        f"[IntradayMonitor] 市值={total_mv:,.0f}, "
        f"昨收={prev_mv:,.0f}, 日内={pnl_pct:+.2%}"
    )

    # 4. 组合级告警
    if pnl_pct <= ALERT_P0_REDUCE:
        alert_level = "P0"
        msg = f"组合日内跌{pnl_pct:.2%}, 建议减仓50%"
        alerts.append(msg)
        send_alert("P0", f"组合暴跌 {now.strftime('%H:%M')}",
                    f"市值={total_mv:,.0f}, 昨收={prev_mv:,.0f}\n{msg}")
    elif pnl_pct <= ALERT_P0_THRESHOLD:
        alert_level = "P0"
        msg = f"组合日内跌{pnl_pct:.2%}"
        alerts.append(msg)
        send_alert("P0", f"组合大跌 {now.strftime('%H:%M')}",
                    f"市值={total_mv:,.0f}, 昨收={prev_mv:,.0f}\n{msg}")
    elif pnl_pct <= ALERT_P1_THRESHOLD:
        alert_level = "P1"
        msg = f"组合日内跌{pnl_pct:.2%}"
        alerts.append(msg)
        send_alert("P1", f"组合下跌 {now.strftime('%H:%M')}",
                    f"市值={total_mv:,.0f}, 昨收={prev_mv:,.0f}\n{msg}")

    # 5. 单股急跌检测 (ADR-010 过渡期保险丝, 阈值 -8%, 每股每日限 1 次)
    emergency_stocks = []
    for pos in positions:
        code = pos.get("stock_code", "")
        if not code or pos.get("volume", 0) <= 0:
            continue
        stock_pnl = _compute_stock_daily_pnl(code)
        if stock_pnl is None or stock_pnl > ALERT_EMERGENCY_STOCK:
            continue
        if _already_alerted_emergency(code):
            continue
        emergency_stocks.append({"code": code, "pnl_pct": stock_pnl})
        _mark_alerted_emergency(code)

    if emergency_stocks:
        # 组合已 P0 保持 P0 不降级; 否则本规则升级到 P1
        if alert_level is None:
            alert_level = "P1"
        lines = [f"  {s['code']}: {s['pnl_pct']:+.2%}" for s in emergency_stocks]
        summary = f"单股急跌 {len(emergency_stocks)} 只 (阈值 {ALERT_EMERGENCY_STOCK:+.0%}):\n" + "\n".join(lines)
        alerts.append(summary)
        send_alert(
            "P1",
            f"单股急跌 {now.strftime('%H:%M')}",
            f"ADR-010 过渡期保险丝触发:\n{summary}\n建议: 人工查证基本面, 必要时减仓",
        )

    # 6. 写入监控日志
    save_monitor_log(total_mv, prev_mv, pnl_pct, alert_level, alerts)
    logger.info(f"[IntradayMonitor] 完成, alert={alert_level or 'None'}")


def main() -> None:
    """CLI入口。"""
    import argparse
    parser = argparse.ArgumentParser(description="盘中风控监控")
    parser.add_argument("--force", action="store_true",
                        help="忽略交易时间检查(测试用)")
    args = parser.parse_args()
    run_monitor(force=args.force)


if __name__ == "__main__":
    main()
