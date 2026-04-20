"""MVP 2.1b Sub-commit 2 — QMTDataSource 单测.

Mock MiniQMTBroker + xtquant 模块 (monkeypatch sys.modules).
不依赖真 QMT / 真 xtquant 安装.
"""
from __future__ import annotations

import sys
from datetime import date
from types import ModuleType, SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from backend.platform.data.base_source import ContractViolation
from backend.platform.data.sources.qmt_source import (
    QMT_ASSETS_CONTRACT,
    QMT_POSITIONS_CONTRACT,
    QMT_TICKS_CONTRACT,
    QMTDataSource,
)

# ---------- Fake broker ----------


class _FakeBroker:
    def __init__(
        self,
        positions: list[dict] | None = None,
        asset: dict | None = None,
        positions_map: dict[str, int] | None = None,
        raise_on: str | None = None,
    ) -> None:
        self._positions = positions or []
        self._asset = asset or {
            "cash": 50000.0,
            "frozen_cash": 0.0,
            "market_value": 50000.0,
            "total_asset": 100000.0,
        }
        self._positions_map = positions_map or {}
        self._raise_on = raise_on  # method name to raise on

    def query_positions(self) -> list[dict]:
        if self._raise_on == "query_positions":
            raise ConnectionError("QMT 连接断开")
        return self._positions

    def query_asset(self) -> dict:
        if self._raise_on == "query_asset":
            raise ConnectionError("QMT 连接断开")
        return self._asset

    def get_positions(self) -> dict[str, int]:
        if self._raise_on == "get_positions":
            raise ConnectionError("QMT 连接断开")
        return self._positions_map


# ---------- Fake xtquant ----------


def _install_fake_xtquant(
    monkeypatch, ticks_map: dict[str, Any] | None = None, raise_err: bool = False
) -> None:
    """Inject fake xtquant package (xtquant + xtquant.xtdata) into sys.modules."""
    xtquant_mod = ModuleType("xtquant")
    xtdata_mod = ModuleType("xtquant.xtdata")

    if raise_err:
        def _raise(*_a, **_k):
            raise RuntimeError("xtdata network error")
        xtdata_mod.get_full_tick = _raise
    else:
        def _ret(codes):
            return {c: ticks_map.get(c) for c in codes} if ticks_map else {}
        xtdata_mod.get_full_tick = _ret

    xtquant_mod.xtdata = xtdata_mod
    monkeypatch.setitem(sys.modules, "xtquant", xtquant_mod)
    monkeypatch.setitem(sys.modules, "xtquant.xtdata", xtdata_mod)


# ============================================================
# Constructor
# ============================================================


def test_constructor_rejects_none_broker() -> None:
    with pytest.raises(ValueError, match=r"broker 不可为 None"):
        QMTDataSource(broker=None)


# ============================================================
# Contract dispatch
# ============================================================


def test_unsupported_contract_raises_value_error() -> None:
    src = QMTDataSource(broker=_FakeBroker())
    from backend.platform.data.interface import DataContract

    bogus = DataContract(
        name="unknown",
        version="v1",
        schema={},
        primary_key=(),
        source="qmt",
        unit_convention={},
    )
    with pytest.raises(ValueError, match=r"不支持 contract="):
        src._fetch_raw(bogus, since=date.today())


# ============================================================
# qmt_positions
# ============================================================


def test_fetch_positions_returns_schema_aligned() -> None:
    broker = _FakeBroker(
        positions=[
            {
                "stock_code": "600519.SH",
                "volume": 100,
                "can_use_volume": 100,
                "avg_price": 1600.0,
                "market_value": 160000.0,
            },
            {
                "stock_code": "000001.SZ",
                "volume": 500,
                "can_use_volume": 500,
                "avg_price": 10.5,
                "market_value": 5250.0,
            },
        ]
    )
    src = QMTDataSource(broker=broker)
    df = src.fetch(QMT_POSITIONS_CONTRACT, since=date.today())
    assert len(df) == 2
    assert set(df["code"]) == {"600519.SH", "000001.SZ"}
    assert set(df.columns) == {
        "code",
        "volume",
        "can_use_volume",
        "avg_price",
        "market_value",
    }


def test_fetch_positions_empty_list_returns_empty_df() -> None:
    src = QMTDataSource(broker=_FakeBroker(positions=[]))
    df = src.fetch(QMT_POSITIONS_CONTRACT, since=date.today())
    assert df.empty
    # 列仍需存在以对齐 schema (validate 通过)
    assert "code" in df.columns


def test_fetch_positions_broker_raises_propagates() -> None:
    broker = _FakeBroker(raise_on="query_positions")
    src = QMTDataSource(broker=broker)
    with pytest.raises(RuntimeError, match=r"broker.query_positions 失败"):
        src.fetch(QMT_POSITIONS_CONTRACT, since=date.today())


# ============================================================
# qmt_assets
# ============================================================


def test_fetch_assets_returns_single_row() -> None:
    broker = _FakeBroker(
        asset={
            "cash": 100000.0,
            "frozen_cash": 5000.0,
            "market_value": 400000.0,
            "total_asset": 500000.0,
        }
    )
    src = QMTDataSource(broker=broker)
    df = src.fetch(QMT_ASSETS_CONTRACT, since=date.today())
    assert len(df) == 1
    assert df.iloc[0]["total_asset"] == 500000.0
    assert df.iloc[0]["cash"] == 100000.0
    assert set(df.columns) == {
        "updated_at",
        "cash",
        "frozen_cash",
        "market_value",
        "total_asset",
    }


def test_fetch_assets_invalid_return_type_raises() -> None:
    class _BadBroker:
        def query_asset(self):
            return ["bad", "list", "not", "dict"]

    src = QMTDataSource(broker=_BadBroker())
    with pytest.raises(RuntimeError, match=r"返回类型异常"):
        src.fetch(QMT_ASSETS_CONTRACT, since=date.today())


# ============================================================
# qmt_ticks
# ============================================================


def test_fetch_ticks_with_explicit_codes(monkeypatch) -> None:
    _install_fake_xtquant(
        monkeypatch,
        ticks_map={
            # mock tick 对象仍含 high/low 属性 (真实 xtquant 返回), 但 fetcher (v2) 不再读
            "600519.SH": SimpleNamespace(lastPrice=1650.5, high=1660.0, low=1640.0, volume=12000),
            "000001.SZ": SimpleNamespace(lastPrice=10.5, high=10.8, low=10.3, volume=5000000),
        },
    )
    src = QMTDataSource(broker=_FakeBroker(), codes=["600519.SH", "000001.SZ"])
    df = src.fetch(QMT_TICKS_CONTRACT, since=date.today())
    assert len(df) == 2
    # v2: schema 删 high/low, 只剩 4 列 (详见 QMT_TICKS_CONTRACT 注释)
    assert set(df.columns) == {
        "code",
        "last_price",
        "volume",
        "updated_at",
    }
    assert set(df["code"]) == {"600519.SH", "000001.SZ"}


def test_fetch_ticks_passes_when_high_low_zero_session_18_live_regression(monkeypatch) -> None:
    """Regression for Session 18 2026-04-20 开盘事故.

    真实场景: 生产 19 只持仓股 lastPrice>0 但 tick.high=tick.low=0 (xtquant 未订阅
    盘中订阅时默认行为). v1 contract 强制 high/low>=0.01 → ContractViolation 每 60s
    raise, Redis market:latest:* 自 2026-04-03 MVP 2.1c 切换起 0 keys 至 2026-04-20
    开盘 2:30 min 事故发现. v2 删除 high/low 后该场景必须通过.
    """
    _install_fake_xtquant(
        monkeypatch,
        ticks_map={
            "600028.SH": SimpleNamespace(lastPrice=6.45, high=0.0, low=0.0, volume=100_000),
            "600900.SH": SimpleNamespace(lastPrice=28.30, high=0.0, low=0.0, volume=50_000),
        },
    )
    src = QMTDataSource(broker=_FakeBroker(), codes=["600028.SH", "600900.SH"])
    df = src.fetch(QMT_TICKS_CONTRACT, since=date.today())  # 不应 raise ContractViolation
    assert len(df) == 2
    assert set(df["code"]) == {"600028.SH", "600900.SH"}
    # v2 columns 无 high/low
    assert "high" not in df.columns
    assert "low" not in df.columns


def test_fetch_ticks_filters_halted_stocks(monkeypatch) -> None:
    """lastPrice ≤ 0 视为停牌, 应跳过."""
    _install_fake_xtquant(
        monkeypatch,
        ticks_map={
            "600519.SH": SimpleNamespace(lastPrice=1650.5, high=1660.0, low=1640.0, volume=1000),
            "000001.SZ": SimpleNamespace(lastPrice=0.0, high=0.0, low=0.0, volume=0),  # 停牌
            "000002.SZ": None,  # tick 未返回
        },
    )
    src = QMTDataSource(broker=_FakeBroker(), codes=["600519.SH", "000001.SZ", "000002.SZ"])
    df = src.fetch(QMT_TICKS_CONTRACT, since=date.today())
    assert len(df) == 1  # 只剩茅台
    assert df.iloc[0]["code"] == "600519.SH"


def test_fetch_ticks_falls_back_to_positions(monkeypatch) -> None:
    """无 codes 入参 → 回落 broker.get_positions keys."""
    _install_fake_xtquant(
        monkeypatch,
        ticks_map={
            "600519.SH": SimpleNamespace(lastPrice=1650.5, high=1660.0, low=1640.0, volume=1000),
        },
    )
    broker = _FakeBroker(positions_map={"600519.SH": 100})
    src = QMTDataSource(broker=broker)  # 无 codes
    df = src.fetch(QMT_TICKS_CONTRACT, since=date.today())
    assert len(df) == 1
    assert df.iloc[0]["code"] == "600519.SH"


def test_fetch_ticks_xtdata_raises_propagates(monkeypatch) -> None:
    _install_fake_xtquant(monkeypatch, raise_err=True)
    src = QMTDataSource(broker=_FakeBroker(), codes=["600519.SH"])
    with pytest.raises(RuntimeError, match=r"xtdata.get_full_tick 失败"):
        src.fetch(QMT_TICKS_CONTRACT, since=date.today())


# ============================================================
# _check_value_ranges
# ============================================================


def test_check_value_ranges_positions_negative_volume() -> None:
    src = QMTDataSource(broker=_FakeBroker())
    df = pd.DataFrame(
        {
            "code": ["600519.SH"],
            "volume": [-100],  # 负数
            "can_use_volume": [0],
            "avg_price": [1600.0],
            "market_value": [0.0],
        }
    )
    issues = src._check_value_ranges(df, QMT_POSITIONS_CONTRACT)
    assert any("volume" in msg and "< 0" in msg for msg in issues)


def test_check_value_ranges_ticks_last_price_below_min_tick() -> None:
    """v2: 仅 check last_price 最小跳价 0.01 (high/low 已从 schema 移除)."""
    src = QMTDataSource(broker=_FakeBroker())
    df = pd.DataFrame(
        {
            "code": ["600519.SH"],
            "last_price": [0.005],  # 低于 A 股最小跳价 0.01
            "volume": [100],
        }
    )
    issues = src._check_value_ranges(df, QMT_TICKS_CONTRACT)
    assert any("last_price" in msg and "0.01" in msg for msg in issues)


def test_check_value_ranges_ticks_valid_passes() -> None:
    """v2: last_price>=0.01 + volume>=0 (无 high/low) → 0 issues."""
    src = QMTDataSource(broker=_FakeBroker())
    df = pd.DataFrame(
        {
            "code": ["600028.SH"],
            "last_price": [6.45],
            "volume": [100_000],
        }
    )
    issues = src._check_value_ranges(df, QMT_TICKS_CONTRACT)
    assert issues == []


def test_check_value_ranges_assets_negative_total() -> None:
    src = QMTDataSource(broker=_FakeBroker())
    df = pd.DataFrame(
        {
            "cash": [-100.0],
            "frozen_cash": [0.0],
            "market_value": [0.0],
            "total_asset": [0.0],
        }
    )
    issues = src._check_value_ranges(df, QMT_ASSETS_CONTRACT)
    assert any("cash" in msg and "< 0" in msg for msg in issues)


# ============================================================
# Validate 端到端 — PK 重复 → ContractViolation
# ============================================================


def test_fetch_positions_duplicate_code_raises(monkeypatch) -> None:
    # 构造 2 条同 stock_code 的 position (QMT 不该返回, 但防御式测 PK 验证链路)
    broker = _FakeBroker(
        positions=[
            {"stock_code": "600519.SH", "volume": 100, "can_use_volume": 100, "avg_price": 1600.0, "market_value": 160000.0},
            {"stock_code": "600519.SH", "volume": 200, "can_use_volume": 200, "avg_price": 1610.0, "market_value": 322000.0},
        ]
    )
    src = QMTDataSource(broker=broker)
    with pytest.raises(ContractViolation) as exc_info:
        src.fetch(QMT_POSITIONS_CONTRACT, since=date.today())
    assert any("primary_key" in msg for msg in exc_info.value.issues)
