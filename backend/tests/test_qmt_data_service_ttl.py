"""qmt_data_service TTL semantics tests — PR-X1 (LL-081 真修复).

Background: 4-27 Monday 真生产首日 zombie 4h17m. Root cause:
    `qmt_data_service.py` SET CACHE_QMT_STATUS 无 TTL + 无 sync_loop heartbeat refresh
    → service hang 后 key 永久卡 "connected" → qmt_client.is_connected() 永久 True
    → Risk Framework QMTDisconnectRule 0 触发 (intraday 13 次本应 P0 alert)

Fix (PR-X1):
    1. SET → SETEX (TTL=180s = 3x sync_loop 60s)
    2. _sync_positions 成功末加 setex(CACHE_QMT_STATUS, 180, "connected") heartbeat
    3. _sync_positions 失败时 setex(CACHE_QMT_STATUS, 180, "disconnected")

测试覆盖 (6 tests):
    - test_constants_match_ll081_spec: TTL 常量配置正确 + 上下界 (reviewer code P3-2 采纳)
    - test_connect_qmt_success_uses_setex: _connect_qmt 成功 → setex (非 set)
    - test_connect_qmt_failure_uses_setex_disconnected: _connect_qmt 失败 → setex disconnected
    - test_sync_positions_success_refreshes_status_and_nav: 同步成功 dual setex (NAV + heartbeat)
    - test_sync_positions_failure_marks_disconnected: 同步失败 standalone setex disconnected
    - test_sync_positions_failure_silent_ok_on_redis_error: Redis 也挂时不 cascade fail
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# scripts/ 不是 Python package, 用 sys.path hack 跟现有 backend.tests 风格对齐
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))


@pytest.fixture
def qmt_module():
    """Import qmt_data_service module 一次, 跨测试共享."""
    import qmt_data_service  # noqa: PLC0415

    return qmt_data_service


@pytest.fixture
def service(qmt_module):
    """构造 QMTDataService 实例 with mocked _redis + _broker + _bus.

    reviewer python-reviewer P2 采纳: spec=redis.Redis 让 mock 强壮 — 测试 set vs setex
    的 assert_not_called 在 spec 下结构性确保 (typo .ssetex 等会立即 AttributeError).
    """
    import redis  # noqa: PLC0415

    svc = qmt_module.QMTDataService()
    svc._redis = MagicMock(spec=redis.Redis)  # bypass _get_redis lazy init + spec strict
    svc._broker = MagicMock()
    svc._bus = MagicMock()
    # mock pipeline as context-managerless (本测试不验证 pipeline 内部)
    pipe_mock = MagicMock()
    svc._redis.pipeline.return_value = pipe_mock
    pipe_mock.execute.return_value = None
    return svc


# ─────────────────────────────────────────────────────────
# 1. Constants & spec
# ─────────────────────────────────────────────────────────


class TestConstants:
    def test_constants_match_ll081_spec(self, qmt_module) -> None:
        """LL-081 教训: TTL = 3x SYNC_INTERVAL, 防 zombie key 永不过期."""
        assert qmt_module.SYNC_INTERVAL_SEC == 60
        assert qmt_module.QMT_STATUS_TTL_SEC == 180
        assert qmt_module.NAV_TTL_SEC == 180
        assert qmt_module.PORTFOLIO_CURRENT_TTL_SEC == 180
        # 下界: TTL > 1 个 sync interval, 否则 sync_loop heartbeat 来不及 refresh
        assert qmt_module.QMT_STATUS_TTL_SEC > qmt_module.SYNC_INTERVAL_SEC
        assert qmt_module.NAV_TTL_SEC > qmt_module.SYNC_INTERVAL_SEC
        # reviewer code-reviewer P3-2 采纳: 上界 — TTL <= 6x SYNC_INTERVAL (= 360s) 防误配过宽
        # zombie 持续 6 min 是合理监控延迟上限, 配 1h 太宽风险高
        assert qmt_module.QMT_STATUS_TTL_SEC <= 6 * qmt_module.SYNC_INTERVAL_SEC
        assert qmt_module.NAV_TTL_SEC <= 6 * qmt_module.SYNC_INTERVAL_SEC


# ─────────────────────────────────────────────────────────
# 2. _connect_qmt — SET → SETEX 防 zombie
# ─────────────────────────────────────────────────────────


class TestConnectQmtTtl:
    def test_connect_qmt_success_uses_setex(self, qmt_module, service) -> None:
        """成功连接 → setex(QMT_STATUS, 180, "connected"), 非裸 set."""
        # mock MiniQMTBroker import + connect
        with patch.object(qmt_module, "ensure_xtquant_path", lambda: None), patch(
            "engines.broker_qmt.MiniQMTBroker"
        ) as mock_broker_cls:
            mock_broker_cls.return_value.connect.return_value = None
            with patch.object(
                qmt_module.settings, "QMT_PATH", "C:/fake/path", create=True
            ), patch.object(
                qmt_module.settings, "QMT_ACCOUNT_ID", "fake-acct", create=True
            ):
                ok = service._connect_qmt()

        assert ok is True
        # 验证 setex (不是 set)
        service._redis.setex.assert_called_once_with(
            qmt_module.CACHE_QMT_STATUS,
            qmt_module.QMT_STATUS_TTL_SEC,
            "connected",
        )
        service._redis.set.assert_not_called()

    def test_connect_qmt_failure_uses_setex_disconnected(
        self, qmt_module, service
    ) -> None:
        """连接失败 (broker.connect raise) → setex(QMT_STATUS, 180, "disconnected")."""
        with patch.object(qmt_module, "ensure_xtquant_path", lambda: None), patch(
            "engines.broker_qmt.MiniQMTBroker"
        ) as mock_broker_cls:
            mock_broker_cls.return_value.connect.side_effect = RuntimeError("xtquant 断")
            with patch.object(
                qmt_module.settings, "QMT_PATH", "C:/fake", create=True
            ), patch.object(
                qmt_module.settings, "QMT_ACCOUNT_ID", "fake", create=True
            ):
                ok = service._connect_qmt()

        assert ok is False
        service._redis.setex.assert_called_once_with(
            qmt_module.CACHE_QMT_STATUS,
            qmt_module.QMT_STATUS_TTL_SEC,
            "disconnected",
        )
        service._redis.set.assert_not_called()


# ─────────────────────────────────────────────────────────
# 3. _sync_positions heartbeat — 核心 LL-081 fix
# ─────────────────────────────────────────────────────────


class TestSyncPositionsHeartbeat:
    def test_sync_positions_success_refreshes_status_and_nav(
        self, qmt_module, service
    ) -> None:
        """sync 成功 → setex(NAV, 180, json) + setex(QMT_STATUS, 180, "connected") heartbeat.

        关键: heartbeat 让 zombie 后 key 自然 expire, qmt_client.is_connected 自动 fail-loud.
        """
        service._broker.get_positions.return_value = {"600519.SH": 100}
        service._broker.query_asset.return_value = {"cash": 50000.0, "total_asset": 100000.0}

        result = service._sync_positions()

        assert result == {"600519.SH": "100"}
        # 验证 setex 调用清单
        setex_calls = service._redis.setex.call_args_list
        # 必含: CACHE_PORTFOLIO_NAV (TTL=180) + CACHE_QMT_STATUS heartbeat (TTL=180, "connected")
        nav_call_seen = False
        status_heartbeat_seen = False
        for call in setex_calls:
            args = call.args
            if args[0] == qmt_module.CACHE_PORTFOLIO_NAV:
                assert args[1] == qmt_module.NAV_TTL_SEC
                nav_data = json.loads(args[2])
                assert nav_data["cash"] == 50000.0
                assert nav_data["total_value"] == 100000.0
                nav_call_seen = True
            elif args[0] == qmt_module.CACHE_QMT_STATUS:
                assert args[1] == qmt_module.QMT_STATUS_TTL_SEC
                assert args[2] == "connected"
                status_heartbeat_seen = True

        assert nav_call_seen, "CACHE_PORTFOLIO_NAV setex 未调用 (LL-081 NAV TTL)"
        assert status_heartbeat_seen, (
            "CACHE_QMT_STATUS heartbeat setex 未调用 (LL-081 关键修复, "
            "防 zombie 永久 stale 'connected')"
        )

    def test_sync_positions_failure_marks_disconnected(
        self, qmt_module, service
    ) -> None:
        """sync 失败 (broker raise) → setex(QMT_STATUS, 180, "disconnected").

        这是 zombie 模式的唯一兜底: 即使 sync_loop 持续失败, status key 会被
        主动标 disconnected (而非依赖 connect 边沿 SET 之后无后续覆盖).
        """
        service._broker.get_positions.side_effect = RuntimeError("QMT 数据通道断")

        result = service._sync_positions()

        assert result is None  # 失败返 None (老语义保留)
        # 验证 disconnected setex
        disconnected_called = False
        for call in service._redis.setex.call_args_list:
            args = call.args
            if (
                args[0] == qmt_module.CACHE_QMT_STATUS
                and args[2] == "disconnected"
                and args[1] == qmt_module.QMT_STATUS_TTL_SEC
            ):
                disconnected_called = True
                break
        assert disconnected_called, (
            "sync 失败必须 setex(QMT_STATUS, 180, 'disconnected') 主动标 (LL-081 zombie 兜底)"
        )

    def test_sync_positions_failure_silent_ok_on_redis_error(
        self, qmt_module, service
    ) -> None:
        """sync 失败 + setex 也失败 (Redis 挂) → 不 crash 主 loop (silent_ok 注释).

        铁律 33 silent_ok: Redis 也挂时主 logger.warning 已 record, 不重复 raise.
        主 sync_loop 必须能进下一周期重试.
        """
        service._broker.get_positions.side_effect = RuntimeError("QMT 断")
        # setex 第一次成功 (其他 try block 内), 第二次 (except 块) 失败
        # 简化: 全 setex 都 raise
        service._redis.setex.side_effect = ConnectionError("Redis 也挂了")

        # 不应 raise (铁律 33 silent_ok)
        result = service._sync_positions()
        assert result is None
