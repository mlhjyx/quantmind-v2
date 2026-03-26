#!/usr/bin/env python3
"""钉钉Webhook连通性测试脚本。

用法:
    python scripts/test_dingtalk.py --test
    python scripts/test_dingtalk.py --test --message "自定义消息"

验证:
1. .env中DINGTALK_WEBHOOK_URL配置正确
2. DINGTALK_KEYWORD关键词匹配
3. 消息能成功发送到钉钉群
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.config import settings
from app.services.dispatchers.dingtalk import send_markdown_sync


def test_dingtalk(message: str | None = None) -> bool:
    """发送测试消息到钉钉群。

    Args:
        message: 自定义消息内容，None则用默认模板。

    Returns:
        是否发送成功。
    """
    webhook_url = settings.DINGTALK_WEBHOOK_URL
    keyword = settings.DINGTALK_KEYWORD
    secret = settings.DINGTALK_SECRET

    if not webhook_url:
        print("[FAIL] DINGTALK_WEBHOOK_URL 未配置（检查 .env）")
        return False

    print(f"[INFO] Webhook: {webhook_url[:60]}...")
    print(f"[INFO] Keyword: '{keyword}' | Secret: {'(已配置)' if secret else '(未配置)'}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if message:
        content = f"### QuantMind 测试消息\n\n{message}\n\n---\n*{now_str}*"
    else:
        content = (
            f"### QuantMind 钉钉连通性测试\n\n"
            f"**时间**: {now_str}\n\n"
            f"**状态**: 连接正常\n\n"
            f"**环境**: Paper Trading v1.1\n\n"
            f"---\n"
            f"此消息由 `test_dingtalk.py` 发送，确认钉钉通知链路正常。"
        )

    ok = send_markdown_sync(
        webhook_url=webhook_url,
        title="QuantMind 连通性测试",
        content=content,
        secret=secret,
        keyword=keyword,
    )

    if ok:
        print("[PASS] 钉钉消息发送成功，请检查群内是否收到。")
    else:
        print("[FAIL] 钉钉消息发送失败，请检查日志。")

    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="钉钉Webhook连通性测试")
    parser.add_argument("--test", action="store_true", required=True, help="执行测试")
    parser.add_argument("--message", type=str, default=None, help="自定义消息内容")
    args = parser.parse_args()

    ok = test_dingtalk(args.message)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
