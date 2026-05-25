"""Unit tests for llm_cost_monthly_audit._push_dingtalk — Plan v10 DingTalk wire.

Closes the script's pre-existing TODO (DingTalk push when status != OK). The
monthly audit computed WARN / CAP_EXCEEDED status but never alerted anyone —
this wires the downstream alert per the Beat `llm-cost-monthly-audit` design.

Coverage:
- webhook missing → skip (no httpx.post, no exception)
- webhook present, no secret → plain post; text content carries status
- webhook + secret present → URL gains timestamp + sign (DingTalk 加签)
- httpx.post raises → fail-soft, no exception propagates (铁律 33)

Mocks httpx.post — no real network.

关联铁律: 33 (fail-soft)
关联: Plan v8 Master P0-16 / Plan v9 matrix §3.3 / Beat llm-cost-monthly-audit
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import llm_cost_monthly_audit as lcma  # noqa: E402

_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=testtoken"


def test_push_dingtalk_skips_when_webhook_unset() -> None:
    """DINGTALK_WEBHOOK_URL 未配置 → 不调用 httpx.post, 不抛错."""
    with patch("httpx.post") as mock_post:
        lcma._push_dingtalk({}, "WARN", 42.0, 50.0, 0.84, 12.3)
    mock_post.assert_not_called()


def test_push_dingtalk_plain_post_when_no_secret() -> None:
    """webhook 有 / secret 无 → plain post; URL 无 sign; text 含 status.

    iter 80 fix: `_push_dingtalk = send_alert` (MVP 4.1 batch 3.9 alias) — send_alert
    routes via OBSERVABILITY_USE_PLATFORM_SDK switch. Test targets LEGACY httpx path
    specifically, so call `_send_alert_via_legacy_dingtalk` directly (immune to
    settings drift; verifies legacy httpx contract unchanged).
    """
    env = {"DINGTALK_WEBHOOK_URL": _WEBHOOK}
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        lcma._send_alert_via_legacy_dingtalk(env, "CAP_EXCEEDED", 55.0, 50.0, 1.1, 80.0)

    mock_post.assert_called_once()
    url = mock_post.call_args.args[0]
    assert "sign=" not in url
    content = mock_post.call_args.kwargs["json"]["text"]["content"]
    assert "CAP_EXCEEDED" in content


def test_push_dingtalk_signs_url_when_secret_present() -> None:
    """secret 有 → URL 附加 timestamp + sign (DingTalk 加签).

    iter 80 fix: 同 test_push_dingtalk_plain_post — call legacy path directly.
    """
    env = {"DINGTALK_WEBHOOK_URL": _WEBHOOK, "DINGTALK_SECRET": "SECabc123"}
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        lcma._send_alert_via_legacy_dingtalk(env, "WARN", 42.0, 50.0, 0.84, None)

    url = mock_post.call_args.args[0]
    assert "timestamp=" in url
    assert "sign=" in url


def test_push_dingtalk_fail_soft_on_post_error() -> None:
    """httpx.post 抛错 → fail-soft, 不向上抛 (铁律 33 — 审计结果不受影响)."""
    env = {"DINGTALK_WEBHOOK_URL": _WEBHOOK}
    with patch("httpx.post", side_effect=RuntimeError("network down")):
        # 不应抛异常 —— 若抛, 本测试直接 error.
        lcma._push_dingtalk(env, "WARN", 42.0, 50.0, 0.84, 5.0)
