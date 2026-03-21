"""钉钉Webhook发送器。

发送Markdown格式消息到钉钉群机器人。
支持HMAC-SHA256签名(如果secret非空)。
超时10秒，失败不抛异常只记日志。
"""

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

# 钉钉API超时(秒)
_TIMEOUT = 10.0


def _build_sign_url(webhook_url: str, secret: str) -> str:
    """构建带签名的钉钉Webhook URL。

    签名算法: base64(hmac_sha256(timestamp + '\\n' + secret, secret))

    Args:
        webhook_url: 原始Webhook地址。
        secret: 签名密钥。

    Returns:
        附带timestamp和sign参数的URL。
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


async def send_markdown(
    webhook_url: str,
    title: str,
    content: str,
    secret: str = "",
) -> bool:
    """发送Markdown消息到钉钉。

    Args:
        webhook_url: 钉钉Webhook地址。
        title: 消息标题(在通知栏显示)。
        content: Markdown格式内容。
        secret: HMAC签名密钥，为空则不签名。

    Returns:
        是否发送成功。失败不抛异常，仅记日志返回False。
    """
    if not webhook_url:
        logger.warning("[DingTalk] webhook_url未配置，跳过发送")
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
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            result = resp.json()

        if result.get("errcode") == 0:
            logger.info("[DingTalk] 发送成功: title='%s'", title)
            return True
        else:
            logger.error("[DingTalk] 返回错误: %s", result)
            return False

    except httpx.TimeoutException:
        logger.error("[DingTalk] 发送超时(%.0f秒): title='%s'", _TIMEOUT, title)
        return False
    except Exception as e:
        logger.error("[DingTalk] 发送异常: %s", e)
        return False


def send_markdown_sync(
    webhook_url: str,
    title: str,
    content: str,
    secret: str = "",
) -> bool:
    """同步版Markdown发送（给pipeline脚本用，避免async事件循环）。

    Args:
        webhook_url: 钉钉Webhook地址。
        title: 消息标题。
        content: Markdown格式内容。
        secret: HMAC签名密钥。

    Returns:
        是否发送成功。
    """
    if not webhook_url:
        logger.warning("[DingTalk] webhook_url未配置，跳过发送")
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
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            result = resp.json()

        if result.get("errcode") == 0:
            logger.info("[DingTalk] sync发送成功: title='%s'", title)
            return True
        else:
            logger.error("[DingTalk] sync返回错误: %s", result)
            return False

    except httpx.TimeoutException:
        logger.error("[DingTalk] sync发送超时(%.0f秒): title='%s'", _TIMEOUT, title)
        return False
    except Exception as e:
        logger.error("[DingTalk] sync发送异常: %s", e)
        return False


async def send_text(
    webhook_url: str,
    content: str,
    secret: str = "",
) -> bool:
    """发送纯文本消息到钉钉(备用)。

    Args:
        webhook_url: 钉钉Webhook地址。
        content: 纯文本内容。
        secret: HMAC签名密钥。

    Returns:
        是否发送成功。
    """
    if not webhook_url:
        return False

    url = _build_sign_url(webhook_url, secret) if secret else webhook_url
    payload = {
        "msgtype": "text",
        "text": {"content": content},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            result = resp.json()
        return result.get("errcode") == 0
    except Exception as e:
        logger.error("[DingTalk] 文本发送异常: %s", e)
        return False
