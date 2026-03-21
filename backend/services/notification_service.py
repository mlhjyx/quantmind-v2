"""[DEPRECATED] 旧版通知服务 — 已迁移到 app.services.notification_service。

请使用:
    from app.services.notification_service import send_alert, send_daily_report

本文件保留仅为向后兼容，后续版本将删除。
"""

import warnings as _warnings
_warnings.warn(
    "services.notification_service 已废弃，请使用 app.services.notification_service",
    DeprecationWarning,
    stacklevel=2,
)

import base64
import hashlib
import hmac
import json
import logging
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _build_sign_url(webhook_url: str, secret: str) -> str:
    """构建DingTalk签名URL。

    签名算法: base64(hmac_sha256(timestamp + '\\n' + secret, secret))
    """
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    return f"{webhook_url}&timestamp={timestamp}&sign={sign}"


def send_dingtalk(
    webhook_url: str,
    content: str,
    secret: str = "",
    title: str = "QuantMind",
) -> bool:
    """发送DingTalk消息。

    Args:
        webhook_url: Webhook地址
        content: Markdown内容
        secret: 签名密钥（可选）
        title: 消息标题

    Returns:
        是否发送成功
    """
    if not webhook_url:
        logger.warning("[Notify] DingTalk webhook未配置，跳过")
        return False

    url = _build_sign_url(webhook_url, secret) if secret else webhook_url

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": content,
        },
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("errcode") == 0:
                logger.info("[Notify] DingTalk发送成功")
                return True
            else:
                logger.error(f"[Notify] DingTalk返回错误: {result}")
                return False
    except Exception as e:
        logger.error(f"[Notify] DingTalk发送异常: {e}")
        return False


def save_notification(
    conn,
    level: str,
    category: str,
    title: str,
    content: str,
    market: str = "astock",
) -> None:
    """写入notifications表。"""
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO notifications
               (level, category, market, title, content)
               VALUES (%s, %s, %s, %s, %s)""",
            (level, category, market, title, content),
        )
        conn.commit()
    except Exception as e:
        logger.warning(f"[Notify] 写入DB失败: {e}")
        conn.rollback()


def send_daily_report(
    trade_date: date,
    nav: float,
    daily_return: float,
    cum_return: float,
    position_count: int,
    is_rebalance: bool,
    beta: float,
    buys: list[str],
    sells: list[str],
    rejected: list[str],
    initial_capital: float,
    webhook_url: str = "",
    secret: str = "",
    conn=None,
) -> bool:
    """发送每日Paper Trading报告。

    同时写入DB notifications表 + 发送DingTalk。

    Returns:
        DingTalk是否发送成功（DB写入独立）
    """
    # 构建报告内容
    rebal_text = "**是（月度调仓）**" if is_rebalance else "否"
    ret_emoji = "📈" if daily_return >= 0 else "📉"

    lines = [
        f"### {ret_emoji} Paper Trading {trade_date}",
        "",
        f"| 指标 | 数值 |",
        f"|------|------|",
        f"| 调仓 | {rebal_text} |",
        f"| 持仓 | {position_count}只 |",
        f"| NAV | ¥{nav:,.0f} |",
        f"| 日收益 | {daily_return:+.2%} |",
        f"| 累计收益 | {cum_return:+.2%} |",
        f"| Beta | {beta:.3f} |",
    ]

    if buys:
        buy_str = ", ".join(buys[:8])
        if len(buys) > 8:
            buy_str += f" +{len(buys)-8}"
        lines.append(f"\n**买入({len(buys)})**: {buy_str}")

    if sells:
        sell_str = ", ".join(sells[:8])
        if len(sells) > 8:
            sell_str += f" +{len(sells)-8}"
        lines.append(f"\n**卖出({len(sells)})**: {sell_str}")

    if rejected:
        lines.append(f"\n⚠️ **受限({len(rejected)})**: {', '.join(rejected[:5])}")

    content = "\n".join(lines)

    # 写入DB
    if conn:
        save_notification(
            conn,
            level="info",
            category="paper_daily",
            title=f"Paper Trading {trade_date}",
            content=content,
        )

    # 发送DingTalk
    return send_dingtalk(
        webhook_url, content, secret,
        title=f"Paper {trade_date} {daily_return:+.2%}",
    )


def send_alert(
    level: str,
    title: str,
    content: str,
    webhook_url: str = "",
    secret: str = "",
    conn=None,
) -> bool:
    """发送告警通知。

    Args:
        level: 'P0'/'P1'/'P2'
        title: 告警标题
        content: 详细内容
    """
    emoji = {"P0": "🔴", "P1": "🟡", "P2": "🔵"}.get(level, "⚪")
    md = f"### {emoji} [{level}] {title}\n\n{content}"

    if conn:
        save_notification(conn, level=level, category="alert", title=title, content=content)

    return send_dingtalk(webhook_url, md, secret, title=f"[{level}] {title}")
