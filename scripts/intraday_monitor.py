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
from __future__ import annotations

import json
import os
import sys
from contextlib import closing
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT / "backend"))

# xtquant双层嵌套路径修复（append不insert，避免其旧numpy覆盖venv版本）
_venv = PROJECT_ROOT / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"
if _venv.exists() and str(_venv) not in sys.path:
    sys.path.append(str(_venv))

import structlog

# MVP 4.1 batch 3.8: AlertDispatchError 顶层 import (铁律 33 fail-loud).
from qm_platform.observability import AlertDispatchError

from app.config import settings

if TYPE_CHECKING:
    from qm_platform.observability import AlertRulesEngine

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
    """获取昨日收盘总市值(从performance_series).

    Session 21 P1-c 同类 bug fix: 加 `AND trade_date < %s` 过滤,
    防 15:40 DailyReconciliation 写当日行后本函数读到今日 self,
    被当成"昨收" → 日内 pnl_pct=0. 对齐 run_paper_trading.py:230 + daily_reconciliation.py:206.
    """
    import psycopg2
    try:
        conn = psycopg2.connect(
            dbname="quantmind_v2", user="xin",
            password="quantmind", host="localhost",
        )
        cur = conn.cursor()
        today = date.today()
        # 先尝试live模式，fallback到paper
        for mode in ["live", "paper"]:
            cur.execute(
                """SELECT nav FROM performance_series
                   WHERE strategy_id = %s AND execution_mode = %s
                     AND trade_date < %s
                   ORDER BY trade_date DESC LIMIT 1""",
                (settings.PAPER_STRATEGY_ID, mode, today),
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


@lru_cache(maxsize=1)
def _load_rules_engine_cached() -> AlertRulesEngine:
    """Inner cached loader: only success cached, raises on yaml load failure.

    P1.2 pattern (batch 3.6 + PR #141 P1.1 reviewer 沉淀): lru_cache 不缓存 exception,
    显式 return type. 失败下次 call 重试, 防 cold-start yaml 缺失永久 silent suppression.
    """
    from qm_platform.observability import AlertRulesEngine

    rules_path = PROJECT_ROOT / "configs" / "alert_rules.yaml"
    return AlertRulesEngine.from_yaml(str(rules_path))


def _get_rules_engine() -> AlertRulesEngine | None:
    """AlertRulesEngine 公共 accessor, 失败 None 不缓存."""
    try:
        return _load_rules_engine_cached()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Observability] AlertRulesEngine load failed: {e}, fallback")
        return None


def _send_alert_via_platform_sdk(
    level: str,
    title: str,
    content: str,
    kind: str = "generic",
    details_extra: dict | None = None,
) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine (MVP 4.1 batch 3.8).

    intraday_monitor 5 call sites with kind 区分:
      - kind="qmt_disconnect": QMT 断连 P0
      - kind="portfolio_drop": 组合 P0/P1 (cb_level 1/2/3 in details_extra)
      - kind="emergency_stock_batch": 单股急跌聚合 P1

    AlertDispatchError 必传播 (铁律 33). 调用方 (顶层 send_alert) try/except 包裹.

    设计: yaml match 只看 (severity, source), 不能区分 kind. intraday_monitor
    SDK 路径在代码端构造 dedup_key (kind-aware), yaml 仅提供 suppress_minutes,
    避免 portfolio rule cb_level template 对 qmt/emergency 缺 placeholder raise.
    """
    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    today_str = str(date.today())
    severity = Severity(level.lower()) if level.lower() in {"p0", "p1", "p2", "info"} else Severity.P1

    details: dict[str, str] = {
        "trade_date": today_str,
        "kind": kind,
        "content": content,
    }
    if details_extra:
        # 转 str 以兼容 dedup_key_template 占位符 (template format() 必字符串)
        for k, v in details_extra.items():
            details[k] = str(v) if not isinstance(v, str) else v

    alert = Alert(
        title=f"[{level}] {title}",
        severity=severity,
        source="intraday_monitor",
        details=details,
        trade_date=today_str,
        timestamp_utc=datetime.now(UTC).isoformat(),
    )

    router = get_alert_router()
    engine = _get_rules_engine()

    # batch 3.8 设计: dedup_key 在代码端按 kind 构造, 不调 rule.format_dedup_key
    # (yaml 模板 cb_l{cb_level} 对 qmt_disconnect / emergency_stock_batch 缺 placeholder
    # 会 raise AlertRuleError). yaml 仅提供 suppress_minutes.
    if kind == "emergency_stock_batch":
        dedup_key = f"intraday:emergency_stock_batch:{today_str}"
    elif kind == "emergency_stock":
        # per-code dedup (legacy 单股 kind, 历史保留兼容)
        code = details.get("code", "unknown")
        dedup_key = f"intraday:emergency_stock:{code}:{today_str}"
    elif kind == "portfolio_drop":
        cb_level = details.get("cb_level", "0")
        dedup_key = f"intraday:portfolio_drop:cb_l{cb_level}"
    elif kind == "qmt_disconnect":
        dedup_key = f"intraday:qmt_disconnect:{today_str}"
    else:
        dedup_key = f"intraday:{kind}:{today_str}"

    if engine is not None:
        rule = engine.match(alert)
        suppress_minutes = rule.suppress_minutes if rule else 5
    else:
        suppress_minutes = 5

    router.fire(alert, dedup_key=dedup_key, suppress_minutes=suppress_minutes)


def _send_alert_via_legacy_dingtalk(level: str, title: str, content: str) -> None:
    """legacy 直接 httpx.post (保留向后兼容路径)."""
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


def send_alert(
    level: str,
    title: str,
    content: str,
    kind: str = "generic",
    details_extra: dict | None = None,
) -> None:
    """发送钉钉告警 (MVP 4.1 batch 3.8 dispatch).

    settings.OBSERVABILITY_USE_PLATFORM_SDK 控制路径切换. AlertDispatchError 顶层
    catch (intraday_monitor 不阻塞 monitor 主流程, 下次 5min 重试).

    Args:
        level: P0/P1/P2/INFO (case-insensitive)
        title: 钉钉 markdown title
        content: markdown body
        kind: 告警类别 (qmt_disconnect/portfolio_drop/emergency_stock_batch/generic),
              SDK path 用于 dedup_key 区分; legacy path 忽略
        details_extra: 额外字段 (cb_level for portfolio_drop / code for emergency_stock),
                       SDK path 进 alert.details; legacy path 忽略
    """
    try:
        if settings.OBSERVABILITY_USE_PLATFORM_SDK:
            _send_alert_via_platform_sdk(level, title, content, kind, details_extra)
        else:
            _send_alert_via_legacy_dingtalk(level, title, content)
    except AlertDispatchError as e:
        # P0/P1 sink failed — log+continue (intraday_monitor 不阻塞 monitor 主流程)
        logger.error(
            f"[Observability] AlertDispatchError sink failed: {e} "
            f"(intraday_monitor 5min 重试, 不阻断主监控流程)"
        )
    except Exception as e:
        logger.error(f"告警发送失败: {e}")


# ── ADR-010 过渡期: 单股急跌检测 helpers ──

def _get_prev_closes_batch(codes: list[str]) -> dict[str, float]:
    """批量查 prev_close (1 query 替代 N): review P1 MEDIUM 优化.

    Returns:
        {code: prev_close} — 无数据的 code 不在返回里.
    """
    if not codes:
        return {}
    import psycopg2
    try:
        with closing(psycopg2.connect(
            dbname="quantmind_v2", user="xin",
            password="quantmind", host="localhost",
        )) as conn, conn.cursor() as cur:
            # 对每个 code 取最近 trade_date < today 的 close (DISTINCT ON PG 语法)
            cur.execute(
                """SELECT DISTINCT ON (code) code, close
                       FROM klines_daily
                       WHERE code = ANY(%s) AND trade_date < %s
                       ORDER BY code, trade_date DESC""",
                (codes, date.today()),
            )
            rows = cur.fetchall()
        return {row[0]: float(row[1]) for row in rows if row[1] is not None}
    except Exception as e:
        logger.warning(f"_get_prev_closes_batch failed: {e}")
        return {}


def _get_prev_close(code: str) -> float | None:
    """从 klines_daily 查单股前一交易日收盘价 (review P1 HIGH 修: try/finally close)."""
    import psycopg2
    try:
        with closing(psycopg2.connect(
            dbname="quantmind_v2", user="xin",
            password="quantmind", host="localhost",
        )) as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT close FROM klines_daily
                       WHERE code = %s AND trade_date < %s
                       ORDER BY trade_date DESC LIMIT 1""",
                (code, date.today()),
            )
            row = cur.fetchone()
        return float(row[0]) if row and row[0] else None
    except Exception as e:
        logger.warning(f"_get_prev_close failed for {code}: {e}")
        return None


def _get_current_price(code: str, r=None) -> float | None:
    """从 Redis market:latest:{code} 读当前价.

    Args:
        code: 股票 code
        r: 可选复用的 redis client (review P1 reuse 优化). None 则内部 new 一个.
    """
    try:
        if r is None:
            import redis
            r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        raw = r.get(f"market:latest:{code}")
        if not raw:
            return None
        data = json.loads(raw)
        # MVP 2.1c Sub3 contract v2 用 price, 旧格式兼容 last_price
        price_raw = data.get("price") if data.get("price") is not None else data.get("last_price")
        price = float(price_raw) if price_raw is not None else 0.0
        return price if price > 0 else None
    except Exception as e:
        logger.warning(f"_get_current_price failed for {code}: {e}")
        return None


def _compute_stock_daily_pnl(code: str, r=None, prev_close: float | None = None) -> float | None:
    """单股当日涨跌幅 = (current - prev_close) / prev_close. 任一数据缺失返 None.

    Args:
        code: 股票 code
        r: 可选复用的 redis client (review P1 reuse 优化)
        prev_close: 可选预先 batch 查好的前日 close (review P1 MEDIUM 优化, 避免 N 次 DB)
    """
    current = _get_current_price(code, r=r)
    if current is None:
        return None
    if prev_close is None:
        prev_close = _get_prev_close(code)
    if prev_close is None or prev_close <= 0:
        return None
    return (current - prev_close) / prev_close


def _emergency_dedup_key(code: str) -> str:
    """Redis key 用于同股同日 emergency 告警 dedup."""
    return f"intraday_alerted:emergency:{code}:{date.today().isoformat()}"


def _already_alerted_emergency(code: str, r=None) -> bool:
    """查 Redis 是否同股同日已告警 (24h TTL). fail-safe: 异常返 False (宁重复不漏报).

    Args:
        r: 可选复用的 redis client (review P1 reuse 优化)
    """
    try:
        if r is None:
            import redis
            r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        return r.exists(_emergency_dedup_key(code)) > 0
    except Exception:
        return False  # silent_ok: Redis 失败时允许告警, 保告警覆盖优先于去重


def _mark_alerted_emergency(code: str, r=None) -> None:
    """标记同股同日已告警 (TTL 86400s 自动清).

    Args:
        r: 可选复用的 redis client (review P1 reuse 优化)
    """
    try:
        if r is None:
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
        send_alert(
            "P0", f"QMT断连 {now.strftime('%H:%M')}",
            "盘中监控: miniQMT连接失败, 无法获取实时市值",
            kind="qmt_disconnect",
        )
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
        send_alert(
            "P0", f"组合暴跌 {now.strftime('%H:%M')}",
            f"市值={total_mv:,.0f}, 昨收={prev_mv:,.0f}\n{msg}",
            kind="portfolio_drop",
            details_extra={"cb_level": 3, "pnl_pct": f"{pnl_pct:.4f}"},
        )
    elif pnl_pct <= ALERT_P0_THRESHOLD:
        alert_level = "P0"
        msg = f"组合日内跌{pnl_pct:.2%}"
        alerts.append(msg)
        send_alert(
            "P0", f"组合大跌 {now.strftime('%H:%M')}",
            f"市值={total_mv:,.0f}, 昨收={prev_mv:,.0f}\n{msg}",
            kind="portfolio_drop",
            details_extra={"cb_level": 2, "pnl_pct": f"{pnl_pct:.4f}"},
        )
    elif pnl_pct <= ALERT_P1_THRESHOLD:
        alert_level = "P1"
        msg = f"组合日内跌{pnl_pct:.2%}"
        alerts.append(msg)
        send_alert(
            "P1", f"组合下跌 {now.strftime('%H:%M')}",
            f"市值={total_mv:,.0f}, 昨收={prev_mv:,.0f}\n{msg}",
            kind="portfolio_drop",
            details_extra={"cb_level": 1, "pnl_pct": f"{pnl_pct:.4f}"},
        )

    # 5. 单股急跌检测 (ADR-010 过渡期保险丝, 阈值 -8%, 每股每日限 1 次)
    # review P1 优化: 单 Redis client + 批量 prev_close, 避免 N×3 Redis + N DB
    emergency_stocks: list[dict] = []
    valid_codes = [p.get("stock_code", "") for p in positions if p.get("stock_code") and p.get("volume", 0) > 0]
    prev_closes = _get_prev_closes_batch(valid_codes)  # 1 DB query 替代 N
    try:
        import redis as _redis_mod
        redis_client = _redis_mod.Redis(host="localhost", port=6379, db=0, decode_responses=True)
    except Exception as e:
        logger.warning(f"Redis client init failed, fallback per-call: {e}")
        redis_client = None  # 降级: helpers 会自己 new (fail-safe)

    for pos in positions:
        code = pos.get("stock_code", "")
        if not code or pos.get("volume", 0) <= 0:
            continue
        stock_pnl = _compute_stock_daily_pnl(code, r=redis_client, prev_close=prev_closes.get(code))
        if stock_pnl is None or stock_pnl > ALERT_EMERGENCY_STOCK:
            continue
        if _already_alerted_emergency(code, r=redis_client):
            continue
        emergency_stocks.append({"code": code, "pnl_pct": stock_pnl})
        _mark_alerted_emergency(code, r=redis_client)

    if emergency_stocks:
        # 组合已 P0 保持 P0 不降级; 否则本规则升级到 P1
        if alert_level is None:
            alert_level = "P1"
        lines = [f"  {s['code']}: {s['pnl_pct']:+.2%}" for s in emergency_stocks]
        summary = f"单股急跌 {len(emergency_stocks)} 只 (阈值 {ALERT_EMERGENCY_STOCK:+.0%}):\n" + "\n".join(lines)
        alerts.append(summary)
        # batch 3.8: 单股急跌单次 alert 聚合 N 只 (Redis dedup 已在外层 loop 防同股
        # 多次 — 见 _already_alerted_emergency / _mark_alerted_emergency).
        # SDK path 用 emergency_stock_batch kind, summary dedup 防同 schtask cycle 多次发.
        codes_str = ",".join(s["code"] for s in emergency_stocks)
        send_alert(
            "P1",
            f"单股急跌 {now.strftime('%H:%M')}",
            f"ADR-010 过渡期保险丝触发:\n{summary}\n建议: 人工查证基本面, 必要时减仓",
            kind="emergency_stock_batch",
            details_extra={
                "stock_count": len(emergency_stocks),
                "codes": codes_str,
            },
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
