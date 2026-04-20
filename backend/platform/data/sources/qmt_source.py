"""MVP 2.1b Sub-commit 2 — QMTDataSource: miniQMT 实时交易数据 Platform fetcher.

继承 `BaseDataSource` (MVP 2.1a) Template method, 实现 `_fetch_raw` + contract.name dispatch.

3 种 Contract:
  - `qmt_positions`: 当前持仓 (query_positions)
  - `qmt_assets`: 账户资产 (query_asset, 单行)
  - `qmt_ticks`: 实时 tick (xtdata.get_full_tick)

特殊性 (vs Baostock/Tushare): QMT 数据目标是 **Redis 不是 PG**.
  - 本类只负责 **拉取 + validate** (纯 DataSource 契约)
  - 调用方 (`scripts/qmt_data_service.py` daemon) 拿 validated DataFrame 后自行写 Redis
  - **不走 DataPipeline.ingest** (与铁律 17 不冲突 — 铁律 17 约束 PG 入库, Redis 是独立 sink)

与老 `scripts/qmt_data_service.py` dual-write (MVP 2.1c 后迁移):
  - 本类: fetch_raw + validate
  - 老脚本: Servy daemon 生命周期 + Redis 写 + xtquant path 管理 + 重连退避

Usage:
    from engines.broker_qmt import MiniQMTBroker
    broker = MiniQMTBroker(qmt_path, account_id); broker.connect()
    source = QMTDataSource(broker=broker, codes=["600519.SH"])

    positions_df = source.fetch(QMT_POSITIONS_CONTRACT, since=date.today())
    assets_df = source.fetch(QMT_ASSETS_CONTRACT, since=date.today())
    ticks_df = source.fetch(QMT_TICKS_CONTRACT, since=date.today())
"""
from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

import pandas as pd

from ..base_source import BaseDataSource
from ..interface import DataContract

logger = logging.getLogger(__name__)


# ---------- DataContract 实例 (MVP 2.1b 临时; 正式注册留 MVP 2.1c) ----------

QMT_POSITIONS_CONTRACT = DataContract(
    name="qmt_positions",
    version="v1",
    schema={
        "code": "str",
        "volume": "int64 股",
        "can_use_volume": "int64 股",
        "avg_price": "float64 元",
        "market_value": "float64 元",
    },
    primary_key=("code",),
    source="qmt",
    unit_convention={
        "volume": "股",
        "can_use_volume": "股",
        "avg_price": "元",
        "market_value": "元",
    },
)

QMT_ASSETS_CONTRACT = DataContract(
    name="qmt_assets",
    version="v1",
    schema={
        "updated_at": "datetime",
        "cash": "float64 元",
        "frozen_cash": "float64 元",
        "market_value": "float64 元",
        "total_asset": "float64 元",
    },
    primary_key=("updated_at",),  # 账户资产无天然 PK, 用快照时戳
    source="qmt",
    unit_convention={
        "cash": "元",
        "frozen_cash": "元",
        "market_value": "元",
        "total_asset": "元",
    },
)

QMT_TICKS_CONTRACT = DataContract(
    name="qmt_ticks",
    # v2 (2026-04-20 Session 18): 盘中 live 事故修复 — 从 schema 移除 high/low.
    #
    # 根因 (user 2026-04-20 提供 QMT 官方文档 dict.thinktrader.net 修正诊断):
    #   xtquant.xtdata.get_full_tick() 返回的 tick dict 按官方文档 high/low 本应是
    #   "Day's highest/lowest price" (日级 OHLC, 非 tick 级). 但盘中实测 19 只持仓
    #   lastPrice>0 而 high=low=0 — 推断为未调用 xtdata.subscribe_whole_quote 订阅
    #   行情时 xtquant 只填充基础字段 (lastPrice/volume/askPrice/bidPrice),
    #   high/low/open 依赖订阅 push 更新, snapshot 调用可能返 0.
    #
    # MVP 2.1b contract v1 (e537c8a 2026-04-18) 强制 high/low>=0.01 range 校验,
    # 盘中 lastPrice>0 but high=low=0 合法场景 → ContractViolation 每 60s raise,
    # Redis market:latest:* 自 2026-04-03 MVP 2.1c Sub3.4 切换起 0 keys 至 2026-04-20
    # 开盘 09:20 stderr 刷屏才暴露 (非盘/停牌 lastPrice<=0 被 L251 filter 绕过).
    #
    # 下游消费者分析 (grep 全项目 "market:latest"):
    #   qmt_client.get_price/get_prices L66-93 只读 `price` 字段. 0 消费者用 high/low.
    #   即 high/low 是僵尸字段 — 17 天 0 keys 生产无人察觉, 证明业务不依赖.
    #
    # 修复: 从 schema 移除 (非放宽阈值掩盖). 未来若需日 OHLC, 应走独立 contract
    # + xtdata.subscribe_whole_quote 订阅 push 或改用 xtdata.get_market_data 日 K API,
    # 与 tick snapshot 解耦 (本 contract 定位是活跃行情实时 price snapshot).
    version="v2",
    schema={
        "code": "str",
        "last_price": "float64 元",
        "volume": "int64 股",
        "updated_at": "datetime",
    },
    primary_key=("code",),
    source="qmt",
    unit_convention={
        "last_price": "元",
        "volume": "股",
    },
)

_CONTRACT_NAMES = {"qmt_positions", "qmt_assets", "qmt_ticks"}


# ---------- DataSource ----------


class QMTDataSource(BaseDataSource):
    """miniQMT 实时数据 DataSource (MVP 2.1b).

    Args:
      broker: MiniQMTBroker 已 connect 实例 (或 test mock with get_positions/query_asset/query_positions).
      codes: qmt_ticks 查询用带后缀代码列表 (e.g. ["600519.SH"]); 空则用 positions keys.
      nan_ratio_threshold: 默认 0.0 — QMT 数据应全字段非空, 有空即异常.
    """

    def __init__(
        self,
        broker: Any,
        codes: list[str] | None = None,
        nan_ratio_threshold: float = 0.0,
    ) -> None:
        super().__init__(nan_ratio_threshold=nan_ratio_threshold)
        if broker is None:
            raise ValueError("broker 不可为 None — QMTDataSource 需已 connect 的 MiniQMTBroker")
        self._broker = broker
        self._codes = list(codes) if codes else None

    # ---------- Template method override ----------

    def _fetch_raw(self, contract: DataContract, since: date) -> pd.DataFrame:
        """按 contract.name dispatch 到 3 路子 fetcher.

        Raises:
          ValueError: contract.name 不属于 QMT 支持的 3 个 contract.
          RuntimeError: broker 调用失败 (铁律 33 fail-loud, 不吞异常).
        """
        del since  # QMT 是实时快照, 不用 since (PT 调度每 60s 触发)

        name = contract.name
        if name not in _CONTRACT_NAMES:
            raise ValueError(
                f"QMTDataSource 不支持 contract={name!r}, "
                f"支持: {sorted(_CONTRACT_NAMES)}"
            )

        if name == "qmt_positions":
            return self._fetch_positions()
        if name == "qmt_assets":
            return self._fetch_assets()
        # qmt_ticks
        return self._fetch_ticks()

    # ---------- 子 fetcher ----------

    def _fetch_positions(self) -> pd.DataFrame:
        """查询持仓 → DataFrame. MiniQMTBroker.query_positions 返 list[dict].

        Raises:
          RuntimeError: broker 抛异常 (铁律 33, 不吞).
        """
        try:
            positions = self._broker.query_positions()
        except Exception as e:
            raise RuntimeError(f"broker.query_positions 失败: {e}") from e

        cols = ["code", "volume", "can_use_volume", "avg_price", "market_value"]
        if not positions:
            return pd.DataFrame(columns=cols)

        rows: list[dict] = []
        for p in positions:
            rows.append(
                {
                    "code": p.get("stock_code") or p.get("code"),
                    "volume": int(p.get("volume", 0) or 0),
                    "can_use_volume": int(p.get("can_use_volume", 0) or 0),
                    "avg_price": float(p.get("avg_price", 0.0) or 0.0),
                    "market_value": float(p.get("market_value", 0.0) or 0.0),
                }
            )
        df = pd.DataFrame(rows)
        return df[[c for c in cols if c in df.columns]]

    def _fetch_assets(self) -> pd.DataFrame:
        """查询资产 → 单行 DataFrame (快照时戳作 PK).

        Raises:
          RuntimeError: broker 抛异常.
        """
        try:
            asset = self._broker.query_asset()
        except Exception as e:
            raise RuntimeError(f"broker.query_asset 失败: {e}") from e

        if not isinstance(asset, dict):
            raise RuntimeError(f"broker.query_asset 返回类型异常: {type(asset).__name__}")

        updated_at = datetime.now(UTC)
        row = {
            "updated_at": updated_at,
            "cash": float(asset.get("cash", 0.0) or 0.0),
            "frozen_cash": float(asset.get("frozen_cash", 0.0) or 0.0),
            "market_value": float(asset.get("market_value", 0.0) or 0.0),
            "total_asset": float(asset.get("total_asset", 0.0) or 0.0),
        }
        return pd.DataFrame([row])

    def _fetch_ticks(self) -> pd.DataFrame:
        """批量实时 tick → DataFrame.

        codes 来源: self._codes (__init__) 或 broker.get_positions() keys.

        Raises:
          RuntimeError: xtquant 不可用 / 网络异常 / tick 返回类型异常.
        """
        codes = self._codes
        if not codes:
            try:
                pos_map = self._broker.get_positions()
            except Exception as e:
                raise RuntimeError(f"broker.get_positions 失败: {e}") from e
            codes = list(pos_map.keys()) if pos_map else []

        # v2: schema 删 high/low (详见 QMT_TICKS_CONTRACT 注释)
        cols = ["code", "last_price", "volume", "updated_at"]
        if not codes:
            return pd.DataFrame(columns=cols)

        try:
            from xtquant import xtdata  # lazy, 测试 monkeypatch sys.modules["xtquant"]
        except ImportError as e:
            raise RuntimeError(f"xtquant 不可用: {e}") from e

        try:
            ticks = xtdata.get_full_tick(codes)
        except Exception as e:
            raise RuntimeError(f"xtdata.get_full_tick 失败: {e}") from e

        if not isinstance(ticks, dict):
            raise RuntimeError(f"xtdata.get_full_tick 返回类型异常: {type(ticks).__name__}")

        updated_at = datetime.now(UTC)
        rows: list[dict] = []
        for code, tick in ticks.items():
            if tick is None:
                continue
            last = _tick_attr(tick, "lastPrice", 0.0)
            if last is None or last <= 0:
                continue  # 停牌 / 空 tick 跳过 (下游需仅关心活跃行情)
            rows.append(
                {
                    "code": code,
                    "last_price": float(last),
                    "volume": int(_tick_attr(tick, "volume", 0) or 0),
                    "updated_at": updated_at,
                }
            )
        if not rows:
            return pd.DataFrame(columns=cols)

        df = pd.DataFrame(rows)
        return df[[c for c in cols if c in df.columns]]

    # ---------- _check_value_ranges override ----------

    def _check_value_ranges(
        self, df: pd.DataFrame, contract: DataContract
    ) -> list[str]:
        """业务约束: QMT 实盘价格必须 ≥ 0.01 元, volume ≥ 0, 现金/总资产 ≥ 0."""
        issues: list[str] = []
        if df.empty:
            return issues

        name = contract.name
        if name == "qmt_positions":
            for col in ("volume", "can_use_volume"):
                if col in df.columns:
                    bad = df[col].notna() & (df[col] < 0)
                    n = int(bad.sum())
                    if n > 0:
                        issues.append(f"[range] {col} 列 {n} 行 < 0 (持仓数不可负)")
            for col in ("avg_price", "market_value"):
                if col in df.columns:
                    bad = df[col].notna() & (df[col] < 0)
                    n = int(bad.sum())
                    if n > 0:
                        issues.append(f"[range] {col} 列 {n} 行 < 0")
        elif name == "qmt_assets":
            for col in ("cash", "frozen_cash", "market_value", "total_asset"):
                if col in df.columns:
                    bad = df[col].notna() & (df[col] < 0)
                    n = int(bad.sum())
                    if n > 0:
                        issues.append(f"[range] {col} 列 {n} 行 < 0 (资产不可负)")
        elif name == "qmt_ticks":
            # v2: 只 check last_price (tick 层活跃行情必须 >=0.01 A 股最小跳价) + volume >=0
            # high/low 字段已从 contract 移除 (未订阅时 snapshot 返 0, 详见 QMT_TICKS_CONTRACT 注释)
            if "last_price" in df.columns:
                bad = df["last_price"].notna() & (df["last_price"] < 0.01)
                n = int(bad.sum())
                if n > 0:
                    issues.append(f"[range] last_price 列 {n} 行 < 0.01 (A 股最小跳价 0.01)")
            if "volume" in df.columns:
                bad = df["volume"].notna() & (df["volume"] < 0)
                n = int(bad.sum())
                if n > 0:
                    issues.append(f"[range] volume 列 {n} 行 < 0")
        return issues


def _tick_attr(tick: Any, name: str, default):
    """统一从 tick 对象/dict 取属性, mock 测试友好."""
    if tick is None:
        return default
    if isinstance(tick, dict):
        return tick.get(name, default)
    return getattr(tick, name, default)


__all__ = [
    "QMTDataSource",
    "QMT_POSITIONS_CONTRACT",
    "QMT_ASSETS_CONTRACT",
    "QMT_TICKS_CONTRACT",
]
