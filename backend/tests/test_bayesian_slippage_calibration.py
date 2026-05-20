"""Unit tests for bayesian_slippage_calibration Plan v10 additions.

Covers the quarterly drift-alert + report-output wire — closes the Beat
`slippage-calibration-quarterly` design ("Compare vs current calibration;
alert if drift > 30% per coef. Output: docs/research/slippage_calibration_YYYYQ.md").

- _parse_env_file: parse k=v / skip comments / missing-file → {}
- _compute_coef_drift: > 30% flagged, within threshold empty
- _push_dingtalk_slippage: skip when webhook unset, plain post, signed URL,
  fail-soft on httpx error (铁律 33)

Mocks httpx.post — no network.

关联铁律: 18 (季度复核) / 33 (fail-soft)
关联: Plan v8 Master P0-10 / Beat slippage-calibration-quarterly design
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import bayesian_slippage_calibration as bsc  # noqa: E402

_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=testtoken"


# §1 _parse_env_file


def test_parse_env_file_missing_returns_empty(tmp_path: Path) -> None:
    """文件不存在 → 空 dict (fail-soft)."""
    assert bsc._parse_env_file(tmp_path / "nonexistent.env") == {}


def test_parse_env_file_parses_kv(tmp_path: Path) -> None:
    """解析 k=v, 跳过注释 + 空行, strip 空白."""
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nDINGTALK_WEBHOOK_URL=https://x\n\nFOO = bar \n", encoding="utf-8"
    )
    parsed = bsc._parse_env_file(env)
    assert parsed["DINGTALK_WEBHOOK_URL"] == "https://x"
    assert parsed["FOO"] == "bar"


# §2 _compute_coef_drift


def test_compute_coef_drift_flags_over_threshold() -> None:
    """系数 drift > 30% → 标记; <= 30% → 不标记."""
    params = {
        "base_bps": bsc.DEFAULT_PARAMS["base_bps"] * 1.5,  # +50% → flagged
        "y_small": bsc.DEFAULT_PARAMS["y_small"] * 1.1,  # +10% → not flagged
    }
    over = bsc._compute_coef_drift(params)
    assert "base_bps" in over
    assert abs(over["base_bps"] - 0.5) < 1e-9
    assert "y_small" not in over


def test_compute_coef_drift_empty_when_all_within() -> None:
    """所有系数 +5% drift → 全部在阈值内 → 空 dict."""
    params = {k: v * 1.05 for k, v in bsc.DEFAULT_PARAMS.items()}
    assert bsc._compute_coef_drift(params) == {}


# §3 _push_dingtalk_slippage


def test_push_dingtalk_slippage_skips_when_webhook_unset() -> None:
    """DINGTALK_WEBHOOK_URL 未配置 → 不调用 httpx.post."""
    with patch("httpx.post") as mock_post:
        bsc._push_dingtalk_slippage({}, "2026Q2", {"base_bps": 0.5})
    mock_post.assert_not_called()


def test_push_dingtalk_slippage_plain_post_when_no_secret() -> None:
    """webhook 有 / secret 无 → plain post; URL 无 sign; text 含系数名."""
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        bsc._push_dingtalk_slippage(
            {"DINGTALK_WEBHOOK_URL": _WEBHOOK}, "2026Q2", {"base_bps": 0.5}
        )
    mock_post.assert_called_once()
    url = mock_post.call_args.args[0]
    assert "sign=" not in url
    content = mock_post.call_args.kwargs["json"]["text"]["content"]
    assert "base_bps" in content


def test_push_dingtalk_slippage_signs_url_when_secret() -> None:
    """secret 有 → URL 附加 timestamp + sign (DingTalk 加签)."""
    env = {"DINGTALK_WEBHOOK_URL": _WEBHOOK, "DINGTALK_SECRET": "SECxyz"}
    with patch("httpx.post") as mock_post:
        mock_post.return_value = MagicMock(status_code=200)
        bsc._push_dingtalk_slippage(env, "2026Q2", {"y_small": 0.4})
    url = mock_post.call_args.args[0]
    assert "timestamp=" in url
    assert "sign=" in url


def test_push_dingtalk_slippage_fail_soft_on_error() -> None:
    """httpx.post 抛错 → fail-soft, 不向上抛 (铁律 33 — 校准结果不受影响)."""
    with patch("httpx.post", side_effect=RuntimeError("net down")):
        # 不应抛异常 —— 若抛, 本测试直接 error.
        bsc._push_dingtalk_slippage(
            {"DINGTALK_WEBHOOK_URL": _WEBHOOK}, "2026Q2", {"base_bps": 0.5}
        )
