"""MVP 4.1 batch 1 unit tests — PostgresAlertRouter + DingTalkChannel + dedup logic.

Mock-based 单测, 不连真 PG (smoke test_mvp_4_1_batch_1_live.py 走真 DB).
覆盖:
  - 合约: AlertRouter ABC 实现, FireResult 枚举语义
  - dedup: 命中 + 失误 + count++ 行为
  - validation: dedup_key 空/超长 + suppress_minutes 越界
  - dispatch: 单 channel 成功/失败, 多 channel 任一成功视 sent
  - fail-loud: 全 channel 失败 raise AlertDispatchError + dedup row 仍 persist
  - alert(severity, payload) Blueprint 签名
  - get_history filter
  - severity enum 映射 + 默认 suppress_minutes
  - timezone (铁律 41 UTC)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from qm_platform._types import Severity
from qm_platform.observability import (
    Alert,
    AlertDispatchError,
    DingTalkChannel,
    PostgresAlertRouter,
    reset_alert_router,
)
from qm_platform.observability.alert import (
    _DEDUP_KEY_MAX_LEN,
    _DEFAULT_SUPPRESS_MINUTES,
    _MAX_SUPPRESS_MINUTES,
)

# ─────────────────────────── fixtures ───────────────────────────


@pytest.fixture(autouse=True)
def _clear_singleton():
    reset_alert_router()
    yield
    reset_alert_router()


@pytest.fixture
def fixed_now() -> datetime:
    return datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def alert_p1() -> Alert:
    return Alert(
        title="dv_ttm IC 衰减",
        severity=Severity.P1,
        source="factor_lifecycle_monitor",
        details={"ratio": 0.517, "factor": "dv_ttm"},
        trade_date="2026-04-28",
        timestamp_utc="2026-04-28T19:00:00+00:00",
    )


def _mock_conn() -> tuple[MagicMock, MagicMock]:
    """构造 psycopg2 mock conn + cursor 默认返回空 row."""
    cursor = MagicMock()
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=None)
    cursor.fetchone = MagicMock(return_value=None)  # 默认 dedup miss
    cursor.fetchall = MagicMock(return_value=[])
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=cursor)
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=None)
    conn.close = MagicMock()
    return conn, cursor


def _make_router(
    *,
    channels=None,
    conn=None,
    now: datetime | None = None,
):
    if conn is None:
        conn, _ = _mock_conn()
    if channels is None:
        channels = [_make_channel(send_returns=True)]
    return PostgresAlertRouter(
        channels=channels,
        conn_factory=lambda: conn,
        now_fn=lambda: now or datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC),
    )


def _make_channel(name: str = "dingtalk_mock", send_returns: bool | Exception = True):
    ch = MagicMock()
    ch.name = name
    if isinstance(send_returns, Exception):
        ch.send = MagicMock(side_effect=send_returns)
    else:
        ch.send = MagicMock(return_value=send_returns)
    return ch


# ─────────────────────────── 合约 / 基础 ───────────────────────────


def test_fire_returns_sent_on_dedup_miss(alert_p1):
    conn, cur = _mock_conn()
    ch = _make_channel(send_returns=True)
    router = _make_router(channels=[ch], conn=conn)

    result = router.fire(alert_p1, dedup_key="lifecycle:dv_ttm:warning")

    assert result == "sent"
    ch.send.assert_called_once_with(alert_p1)
    conn.close.assert_called_once()


def test_fire_validates_empty_dedup_key(alert_p1):
    router = _make_router()
    with pytest.raises(ValueError, match="dedup_key 必须非空"):
        router.fire(alert_p1, dedup_key="")
    with pytest.raises(ValueError, match="dedup_key 必须非空"):
        router.fire(alert_p1, dedup_key="   ")


def test_fire_validates_too_long_dedup_key(alert_p1):
    router = _make_router()
    overlong = "x" * (_DEDUP_KEY_MAX_LEN + 1)
    with pytest.raises(ValueError, match="超长"):
        router.fire(alert_p1, dedup_key=overlong)


def test_fire_validates_suppress_minutes_lower_bound(alert_p1):
    router = _make_router()
    with pytest.raises(ValueError, match="必须正整数"):
        router.fire(alert_p1, dedup_key="k", suppress_minutes=0)
    with pytest.raises(ValueError, match="必须正整数"):
        router.fire(alert_p1, dedup_key="k", suppress_minutes=-1)


def test_fire_validates_suppress_minutes_upper_bound(alert_p1):
    router = _make_router()
    over_limit = _MAX_SUPPRESS_MINUTES + 1
    with pytest.raises(ValueError, match="超过 7d 上限"):
        router.fire(alert_p1, dedup_key="k", suppress_minutes=over_limit)


def test_default_suppress_minutes_per_severity(alert_p1):
    """severity 驱动默认窗口 (P0=5/P1=30/P2=60/INFO=60)."""
    assert _DEFAULT_SUPPRESS_MINUTES[Severity.P0] == 5
    assert _DEFAULT_SUPPRESS_MINUTES[Severity.P1] == 30
    assert _DEFAULT_SUPPRESS_MINUTES[Severity.P2] == 60
    assert _DEFAULT_SUPPRESS_MINUTES[Severity.INFO] == 60


# ─────────────────────────── dedup 行为 ───────────────────────────


def test_fire_returns_deduped_within_suppress_window(alert_p1, fixed_now):
    conn, cur = _mock_conn()
    # SELECT FOR UPDATE 命中 — suppress_until 在 now 之后
    cur.fetchone.return_value = (fixed_now + timedelta(minutes=10),)
    ch = _make_channel(send_returns=True)
    router = _make_router(channels=[ch], conn=conn, now=fixed_now)

    result = router.fire(alert_p1, dedup_key="k")

    assert result == "deduped"
    # channel 不应被调用
    ch.send.assert_not_called()
    # UPDATE fire_count++ SQL 应被调
    update_calls = [
        call for call in cur.execute.call_args_list
        if "UPDATE alert_dedup" in call.args[0] and "fire_count + 1" in call.args[0]
    ]
    assert len(update_calls) == 1


def test_fire_after_suppress_window_sends_again(alert_p1, fixed_now):
    conn, cur = _mock_conn()
    # suppress_until 在 now 之前 → 已过期, 视为 dedup miss
    cur.fetchone.return_value = (fixed_now - timedelta(minutes=1),)
    ch = _make_channel(send_returns=True)
    router = _make_router(channels=[ch], conn=conn, now=fixed_now)

    result = router.fire(alert_p1, dedup_key="k")

    assert result == "sent"
    ch.send.assert_called_once()


def test_dedup_naive_datetime_treated_as_expired(alert_p1, fixed_now):
    """tz-naive suppress_until 视为已过期 (铁律 41 防御编程, 不允许 naive 干扰)."""
    conn, cur = _mock_conn()
    naive = datetime(2099, 1, 1)  # naive future, 仍视为过期
    cur.fetchone.return_value = (naive,)
    ch = _make_channel(send_returns=True)
    router = _make_router(channels=[ch], conn=conn, now=fixed_now)

    assert router.fire(alert_p1, dedup_key="k") == "sent"


# ─────────────────────────── dispatch / fail-loud ───────────────────────────


def test_all_channels_failed_raises_dispatch_error(alert_p1, fixed_now):
    """sink_failed: row persist (审计 fire_count) 但 suppress_until=now (零窗, P0 真金可重试)."""
    conn, cur = _mock_conn()
    ch1 = _make_channel(name="dingtalk_a", send_returns=False)
    ch2 = _make_channel(name="dingtalk_b", send_returns=False)
    router = _make_router(channels=[ch1, ch2], conn=conn, now=fixed_now)

    with pytest.raises(AlertDispatchError, match="All channels failed"):
        router.fire(alert_p1, dedup_key="k")

    # row 仍 persist (UPSERT 调用过, fire_count++ 反映尝试) — 审计用
    upsert_calls = [
        call for call in cur.execute.call_args_list
        if "INSERT INTO alert_dedup" in call.args[0] and "ON CONFLICT" in call.args[0]
    ]
    assert len(upsert_calls) == 1
    # reviewer MEDIUM#2 升 P1 采纳: sink_failed → suppress_until = now (零窗, 不抑制重试)
    last_fired_at = upsert_calls[0].args[1][3]
    suppress_until = upsert_calls[0].args[1][4]
    assert last_fired_at == fixed_now
    assert suppress_until == fixed_now, (
        "sink_failed 不抑制下次重试 (P0 真金可用性 > storm 防御)"
    )


def test_sink_failed_does_not_suppress_next_retry(alert_p1, fixed_now):
    """sink_failed 后下次同 dedup_key fire (mock 模拟过期 row) 必能再 dispatch."""
    conn, cur = _mock_conn()
    # mock _is_deduped 第二次时 row exists 但 suppress_until == now (已到期)
    cur.fetchone.return_value = (fixed_now,)  # suppress_until == now → expired
    ch_ok = _make_channel(send_returns=True)
    router = _make_router(channels=[ch_ok], conn=conn, now=fixed_now)

    result = router.fire(alert_p1, dedup_key="k")

    assert result == "sent", "suppress_until == now 应被视为已过期, 允许重试"
    ch_ok.send.assert_called_once()


def test_one_channel_success_returns_sent(alert_p1):
    """多 channel 任一成功即视为 sent."""
    conn, cur = _mock_conn()
    ch_fail = _make_channel(name="ch_fail", send_returns=False)
    ch_ok = _make_channel(name="ch_ok", send_returns=True)
    router = _make_router(channels=[ch_fail, ch_ok], conn=conn)

    result = router.fire(alert_p1, dedup_key="k")

    assert result == "sent"
    ch_fail.send.assert_called_once()
    ch_ok.send.assert_called_once()


def test_channel_raise_treated_as_failure(alert_p1):
    """channel send() 抛异常视为该 channel failed, 不打断其他 channel."""
    conn, cur = _mock_conn()
    boom = _make_channel(name="boom", send_returns=RuntimeError("network down"))
    ok = _make_channel(name="ok", send_returns=True)
    router = _make_router(channels=[boom, ok], conn=conn)

    result = router.fire(alert_p1, dedup_key="k")

    assert result == "sent"
    # 两个 channel 都被调
    boom.send.assert_called_once()
    ok.send.assert_called_once()


def test_empty_channels_rejected_at_init():
    with pytest.raises(ValueError, match="至少需要 1 个 Channel"):
        PostgresAlertRouter(channels=[], conn_factory=lambda: _mock_conn()[0])


# ─────────────────────────── DingTalkChannel ───────────────────────────


def test_dingtalk_channel_requires_webhook():
    with pytest.raises(ValueError, match="webhook_url 未配置"):
        DingTalkChannel(webhook_url="")


def test_dingtalk_channel_send_uses_injected_sender(alert_p1):
    sender = MagicMock(return_value=True)
    ch = DingTalkChannel(
        webhook_url="https://oapi.test/webhook",
        secret="s",
        keyword="QM",
        sender=sender,
    )
    assert ch.send(alert_p1) is True
    sender.assert_called_once()
    kwargs = sender.call_args.kwargs
    assert kwargs["webhook_url"] == "https://oapi.test/webhook"
    assert kwargs["secret"] == "s"
    assert kwargs["keyword"] == "QM"
    # title 含 severity uppercase
    assert "[P1]" in kwargs["title"]
    # body markdown 含 source / trade_date / details
    assert "factor_lifecycle_monitor" in kwargs["content"]
    assert "2026-04-28" in kwargs["content"]
    assert "ratio" in kwargs["content"]


# ─────────────────────────── alert(severity, payload) Blueprint sig ───────────────────────────


def test_alert_payload_signature_happy(fixed_now):
    conn, cur = _mock_conn()
    ch = _make_channel(send_returns=True)
    router = _make_router(channels=[ch], conn=conn, now=fixed_now)

    result = router.alert(
        Severity.P0,
        {
            "title": "intraday drop > 8%",
            "source": "intraday_monitor",
            "dedup_key": "intraday:drop8",
            "details": {"nav": 920000.0, "drop": -0.087},
            "trade_date": "2026-04-28",
        },
    )
    assert result == "sent"
    sent_alert = ch.send.call_args.args[0]
    assert sent_alert.severity == Severity.P0
    assert sent_alert.title == "intraday drop > 8%"
    assert sent_alert.trade_date == "2026-04-28"
    assert sent_alert.timestamp_utc.startswith("2026-04-28T12:00:00")


def test_alert_payload_missing_keys_rejected():
    router = _make_router()
    with pytest.raises(ValueError, match="必须含 keys"):
        router.alert(Severity.P1, {"title": "x"})  # missing source / dedup_key


def test_alert_payload_passes_suppress_minutes_through(fixed_now):
    conn, cur = _mock_conn()
    ch = _make_channel(send_returns=True)
    router = _make_router(channels=[ch], conn=conn, now=fixed_now)
    router.alert(
        Severity.P2,
        {
            "title": "info",
            "source": "x",
            "dedup_key": "k",
            "suppress_minutes": 7,
        },
    )
    # UPSERT 用了 7min suppress 窗 (now+7min)
    upsert_call = next(
        c for c in cur.execute.call_args_list
        if "INSERT INTO alert_dedup" in c.args[0]
    )
    suppress_until = upsert_call.args[1][4]  # 第 5 个参数
    assert suppress_until == fixed_now + timedelta(minutes=7)


# ─────────────────────────── get_history ───────────────────────────


def test_get_history_no_filter(fixed_now):
    conn, cur = _mock_conn()
    cur.fetchall.return_value = [
        ("k1", "p1", "src1", fixed_now, "title1"),
        ("k2", "p2", "src2", fixed_now - timedelta(minutes=5), "title2"),
    ]
    router = _make_router(conn=conn, now=fixed_now)

    rows = router.get_history(limit=10)

    assert len(rows) == 2
    assert rows[0].severity == Severity.P1
    assert rows[1].severity == Severity.P2


def test_get_history_with_severity_filter(fixed_now):
    conn, cur = _mock_conn()
    cur.fetchall.return_value = [("k1", "p0", "src", fixed_now, "t")]
    router = _make_router(conn=conn, now=fixed_now)

    rows = router.get_history(severity=Severity.P0, limit=5)

    assert len(rows) == 1
    assert rows[0].severity == Severity.P0
    # SQL 含 WHERE severity = %s
    sql_text = cur.execute.call_args.args[0]
    assert "WHERE severity =" in sql_text
    assert cur.execute.call_args.args[1] == ("p0", 5)


def test_get_history_validates_limit(fixed_now):
    router = _make_router(now=fixed_now)
    with pytest.raises(ValueError, match="1..10000"):
        router.get_history(limit=0)
    with pytest.raises(ValueError, match="1..10000"):
        router.get_history(limit=10_001)


def test_get_history_skips_unknown_severity_row(fixed_now):
    """旧 row 含未来扩展的 severity 应 silent skip + log warn (不阻断)."""
    conn, cur = _mock_conn()
    cur.fetchall.return_value = [
        ("k1", "fatal", "src", fixed_now, "t"),  # 不存在的 severity
        ("k2", "p1", "src", fixed_now, "t"),
    ]
    router = _make_router(conn=conn, now=fixed_now)

    rows = router.get_history()
    # 只应保留 1 行 (skipping unknown)
    assert len(rows) == 1
    assert rows[0].severity == Severity.P1


# ─────────────────────────── 时区 / 防御 ───────────────────────────


def test_dedup_key_whitespace_stripped(alert_p1, fixed_now):
    """reviewer P3.A 采纳: ' abc ' / 'abc' 必视为同 dedup_key (避免独立 row)."""
    conn, cur = _mock_conn()
    ch = _make_channel(send_returns=True)
    router = _make_router(channels=[ch], conn=conn, now=fixed_now)

    router.fire(alert_p1, dedup_key="  factor:dv:warn  ")

    upsert_call = next(
        c for c in cur.execute.call_args_list
        if "INSERT INTO alert_dedup" in c.args[0]
    )
    persisted_key = upsert_call.args[1][0]
    assert persisted_key == "factor:dv:warn", "dedup_key 应被 strip 后入库"


def test_suppress_minutes_bool_rejected(alert_p1):
    """reviewer LOW#2 采纳: bool 是 int 子类, fire(suppress_minutes=True) 必 reject."""
    router = _make_router()
    with pytest.raises(ValueError, match="必须正整数"):
        router.fire(alert_p1, dedup_key="k", suppress_minutes=True)
    with pytest.raises(ValueError, match="必须正整数"):
        router.fire(alert_p1, dedup_key="k", suppress_minutes=False)


def test_default_suppress_minutes_completeness():
    """reviewer MEDIUM#3 采纳: _DEFAULT_SUPPRESS_MINUTES 必齐全 Severity enum."""
    assert set(_DEFAULT_SUPPRESS_MINUTES.keys()) == set(Severity), (
        "新增 Severity 必同步 _DEFAULT_SUPPRESS_MINUTES, 否则 module load assert 触发"
    )


def test_now_uses_utc_tzaware(alert_p1):
    """fire() 使用 UTC tz-aware datetime 写库 (铁律 41)."""
    conn, cur = _mock_conn()
    fixed = datetime(2026, 4, 28, 12, 0, 0, tzinfo=UTC)
    router = _make_router(conn=conn, now=fixed)

    router.fire(alert_p1, dedup_key="k", suppress_minutes=10)

    upsert_call = next(
        c for c in cur.execute.call_args_list
        if "INSERT INTO alert_dedup" in c.args[0]
    )
    last_fired_at = upsert_call.args[1][3]
    suppress_until = upsert_call.args[1][4]
    assert last_fired_at == fixed
    assert last_fired_at.tzinfo == UTC
    assert suppress_until == fixed + timedelta(minutes=10)
    assert suppress_until.tzinfo == UTC
