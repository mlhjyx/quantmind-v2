"""scripts/daily_data_ingest.py 单元测试 — Step 12 BAU 入库失败告警 wire。"""

from __future__ import annotations

# scripts/ 可从 backend/ 测试上下文 import (mining_service.py 先例 + .pth)。
from qm_platform._types import Severity

from scripts.daily_data_ingest import _send_failure_alert


class _FakeRouter:
    """记录 fire() 调用的假 AlertRouter。"""

    def __init__(self) -> None:
        self.fired: list = []

    def fire(self, alert, dedup_key=None, **kwargs):  # noqa: ANN001, ANN003
        self.fired.append((alert, dedup_key))
        return "sent"


def test_send_failure_alert_fires_p1_alert(monkeypatch) -> None:
    """入库失败 → 经 AlertRouter 发一条 P1 告警, source=daily_data_ingest。"""
    fake = _FakeRouter()
    monkeypatch.setattr("qm_platform.observability.get_alert_router", lambda: fake)

    _send_failure_alert("postclose", "2026-05-22", "boom")

    assert len(fake.fired) == 1
    alert, dedup_key = fake.fired[0]
    assert alert.source == "daily_data_ingest"
    assert alert.severity == Severity("p1")
    assert "postclose" in dedup_key
    assert "2026-05-22" in dedup_key


def test_send_failure_alert_truncates_long_error(monkeypatch) -> None:
    """超长 error 文本截断到 500 字符 (details 不爆量)。"""
    fake = _FakeRouter()
    monkeypatch.setattr("qm_platform.observability.get_alert_router", lambda: fake)

    _send_failure_alert("intraday", "2026-05-22", "x" * 5000)

    alert, _ = fake.fired[0]
    assert len(alert.details["error"]) == 500


def test_send_failure_alert_swallows_router_error(monkeypatch) -> None:
    """best-effort: AlertRouter 抛异常时 _send_failure_alert 不得 raise (不掩盖入库失败)。"""

    def _boom():
        raise RuntimeError("router down")

    monkeypatch.setattr("qm_platform.observability.get_alert_router", _boom)

    # 不抛异常即通过 — _apply 仍可正常 return 1。
    _send_failure_alert("intraday", "2026-05-22", "ingest error")
