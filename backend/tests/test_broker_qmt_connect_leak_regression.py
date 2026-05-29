"""Regression: broker_qmt.connect() 失败路径必 stop() 释放 xtquant 资源.

防 PID 11008 真生产事故复现 (2026-05-27):
- 38 小时 × ~5min 重试 = ~450 次失败 connect()
- 每次失败漏 ~40 MB / ~4 threads / ~2 bound sockets
- 累计: 8.4 GB / 874 threads / 438 bound sockets (90% RAM 占用)

根因: broker_qmt.py connect() 在 `if result != 0` 失败分支只
`self._trader = None` 丢 Python 引用, 不调 `stop()` —— xtquant.XtQuantTrader.start()
已经 spawn 的内部 thread pool / TCP socket / asyncio loop **GC 不会回收 C 层资源**,
唯一安全释放手段是显式 stop().

修复: try/except 包住 start() 之后所有路径, 失败必 stop() 后再 raise (沿用铁律 33
fail-safe cleanup).
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


def _install_fake_xtquant(connect_return_code: int) -> tuple[MagicMock, dict]:
    """注入 fake xtquant 模块, 返回 (mock_trader_instance, modules_dict).

    Args:
        connect_return_code: XtQuantTrader.connect() 返回值. 0 = 成功, !=0 = 失败.
    """
    mock_trader_instance = MagicMock(name="XtQuantTrader_instance")
    mock_trader_instance.connect.return_value = connect_return_code
    mock_trader_instance.subscribe.return_value = 0
    mock_trader_instance.start.return_value = None
    mock_trader_instance.stop.return_value = None

    fake_xttrader = MagicMock()
    fake_xttrader.XtQuantTrader = MagicMock(return_value=mock_trader_instance)
    # XtQuantTraderCallback 必须是真实 class (broker_qmt 内 _Callback 继承它)
    fake_xttrader.XtQuantTraderCallback = type("XtQuantTraderCallback", (), {})

    fake_xttype = MagicMock()
    fake_xttype.StockAccount = MagicMock()

    modules = {
        "xtquant": MagicMock(),
        "xtquant.xttrader": fake_xttrader,
        "xtquant.xttype": fake_xttype,
    }
    return mock_trader_instance, modules


def test_connect_failure_calls_stop_to_release_xtquant_resources(tmp_path):
    """REGRESSION (PID 11008 / 8.4 GB leak): connect() 返回 -1 时, stop() 必被调用.

    这是阻止 38h 累积 8.4 GB 泄漏的关键守护. 修复前 `self._trader = None` 只丢 Python
    引用, xtquant C 层 thread/socket 持续累积. 修复后 try/except 兜底显式 stop().
    """
    mock_trader_instance, fake_modules = _install_fake_xtquant(connect_return_code=-1)

    with patch.dict(sys.modules, fake_modules):
        from engines.broker_qmt import MiniQMTBroker

        broker = MiniQMTBroker(
            qmt_path=str(tmp_path),
            account_id="test_acct",
            session_id=12345,
        )

        with pytest.raises(RuntimeError, match="miniQMT连接失败.*返回码: -1"):
            broker.connect()

    # ⭐ 核心 regression assertion: stop() 必被调用 (反 8.4 GB 真生产事故)
    mock_trader_instance.stop.assert_called_once()
    # Python 引用清空 (避免后续 disconnect 误调被 stop 过的 trader)
    assert broker._trader is None
    # _connected 状态未被错误置 True
    assert broker._connected is False


def test_connect_success_does_not_call_stop(tmp_path):
    """对照: connect() 成功路径不应调 stop() (回归保护防过度修复)."""
    mock_trader_instance, fake_modules = _install_fake_xtquant(connect_return_code=0)

    with patch.dict(sys.modules, fake_modules):
        from engines.broker_qmt import MiniQMTBroker

        broker = MiniQMTBroker(
            qmt_path=str(tmp_path),
            account_id="test_acct",
            session_id=12345,
        )
        broker.connect()  # 不应 raise

    mock_trader_instance.stop.assert_not_called()
    assert broker._trader is mock_trader_instance
    assert broker._connected is True
