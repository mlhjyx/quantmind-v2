"""Data Contract定义 — 每张核心表的schema、单位、值域。

所有数据入库前必须通过Contract验证。
单位在入库时从Tushare原始单位转换为DB存储单位(元)。

DDL权威来源: docs/QUANTMIND_V2_DDL_FINAL.sql
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SourceUnit(Enum):
    """Tushare API返回的原始单位。"""

    QIAN_YUAN = "千元"  # klines_daily.amount, index_daily.amount
    WAN_YUAN = "万元"  # daily_basic.total_mv/circ_mv, moneyflow金额, northbound.hold_mv
    YUAN = "元"  # 价格列(open/high/low/close等)
    SHOU = "手"  # 1手=100股
    GU = "股"  # northbound.hold_vol
    WAN_GU = "万股"  # daily_basic.total_share/float_share/free_share
    PCT_X100 = "%×100"  # pct_change: 5.06 = 涨5.06%
    PCT = "%"  # turnover_rate
    DIMENSIONLESS = "无量纲"  # z-score, 比率


class DBUnit(Enum):
    """DB统一存储单位。"""

    YUAN = "元"
    SHOU = "手"  # volume保留手(全系统一致)
    GU = "股"
    WAN_GU = "万股"  # share列保留万股(与Tushare一致)
    PCT_X100 = "%×100"
    PCT = "%"
    DIMENSIONLESS = "无量纲"


# 单位转换乘数: source_unit → db_unit
UNIT_CONVERSIONS: dict[tuple[SourceUnit, DBUnit], float] = {
    (SourceUnit.QIAN_YUAN, DBUnit.YUAN): 1000.0,
    (SourceUnit.WAN_YUAN, DBUnit.YUAN): 10000.0,
}


@dataclass(frozen=True)
class ColumnSpec:
    """单列schema定义。"""

    dtype: str  # "float", "int", "str", "bool", "date"
    nullable: bool = True
    source_unit: SourceUnit | None = None  # Tushare原始单位
    db_unit: DBUnit | None = None  # DB存储单位
    min_val: float | None = None
    max_val: float | None = None

    @property
    def conversion_factor(self) -> float | None:
        """计算单位转换乘数。None=不需要转换。"""
        if self.source_unit is None or self.db_unit is None:
            return None
        key = (self.source_unit, self.db_unit)
        return UNIT_CONVERSIONS.get(key)


@dataclass(frozen=True)
class TableContract:
    """表级Contract定义。"""

    table_name: str
    pk_columns: tuple[str, ...]
    columns: dict[str, ColumnSpec]
    rename_map: dict[str, str] = field(default_factory=dict)
    fk_filter_col: str | None = "code"  # FK过滤列(None=不过滤)
    skip_unit_conversion: bool = False  # factor_values等计算产出跳过


# ════════════════════════════════════════════════════════════
# Contract实例
# ════════════════════════════════════════════════════════════

# --- helpers ---
_price_col = ColumnSpec("float", nullable=True, source_unit=SourceUnit.YUAN, db_unit=DBUnit.YUAN, min_val=0)


KLINES_DAILY = TableContract(
    table_name="klines_daily",
    pk_columns=("code", "trade_date"),
    columns={
        "code": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "open": _price_col,
        "high": _price_col,
        "low": _price_col,
        "close": _price_col,
        "pre_close": _price_col,
        "change": ColumnSpec("float"),
        "pct_change": ColumnSpec("float", source_unit=SourceUnit.PCT_X100, db_unit=DBUnit.PCT_X100, min_val=-30, max_val=30),
        "volume": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU, min_val=0),
        "amount": ColumnSpec("float", source_unit=SourceUnit.QIAN_YUAN, db_unit=DBUnit.YUAN, min_val=0),
        "turnover_rate": ColumnSpec("float", source_unit=SourceUnit.PCT, db_unit=DBUnit.PCT),
        "adj_factor": ColumnSpec("float", min_val=0),
        "is_suspended": ColumnSpec("bool"),
        "is_st": ColumnSpec("bool"),
        "up_limit": _price_col,
        "down_limit": _price_col,
    },
    rename_map={"ts_code": "code", "vol": "volume", "pct_chg": "pct_change"},
)

DAILY_BASIC = TableContract(
    table_name="daily_basic",
    pk_columns=("code", "trade_date"),
    columns={
        "code": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "close": _price_col,
        "turnover_rate": ColumnSpec("float", source_unit=SourceUnit.PCT, db_unit=DBUnit.PCT),
        "turnover_rate_f": ColumnSpec("float", source_unit=SourceUnit.PCT, db_unit=DBUnit.PCT),
        "volume_ratio": ColumnSpec("float", min_val=0),
        "pe": ColumnSpec("float"),
        "pe_ttm": ColumnSpec("float"),
        "pb": ColumnSpec("float"),
        "ps": ColumnSpec("float"),
        "ps_ttm": ColumnSpec("float"),
        "dv_ratio": ColumnSpec("float", source_unit=SourceUnit.PCT, db_unit=DBUnit.PCT),
        "dv_ttm": ColumnSpec("float", source_unit=SourceUnit.PCT, db_unit=DBUnit.PCT),
        "total_share": ColumnSpec("float", source_unit=SourceUnit.WAN_GU, db_unit=DBUnit.WAN_GU),
        "float_share": ColumnSpec("float", source_unit=SourceUnit.WAN_GU, db_unit=DBUnit.WAN_GU),
        "free_share": ColumnSpec("float", source_unit=SourceUnit.WAN_GU, db_unit=DBUnit.WAN_GU),
        "total_mv": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN, min_val=0),
        "circ_mv": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN, min_val=0),
    },
    rename_map={"ts_code": "code"},
)

MONEYFLOW_DAILY = TableContract(
    table_name="moneyflow_daily",
    pk_columns=("code", "trade_date"),
    columns={
        "code": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "buy_sm_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "buy_sm_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "sell_sm_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "sell_sm_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "buy_md_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "buy_md_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "sell_md_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "sell_md_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "buy_lg_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "buy_lg_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "sell_lg_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "sell_lg_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "buy_elg_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "buy_elg_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "sell_elg_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "sell_elg_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "net_mf_vol": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU),
        "net_mf_amount": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
    },
    rename_map={"ts_code": "code"},
)

INDEX_DAILY = TableContract(
    table_name="index_daily",
    pk_columns=("index_code", "trade_date"),
    columns={
        "index_code": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "open": _price_col,
        "high": _price_col,
        "low": _price_col,
        "close": _price_col,
        "pre_close": _price_col,
        "pct_change": ColumnSpec("float", source_unit=SourceUnit.PCT_X100, db_unit=DBUnit.PCT_X100),
        "volume": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU, min_val=0),
        "amount": ColumnSpec("float", source_unit=SourceUnit.QIAN_YUAN, db_unit=DBUnit.YUAN, min_val=0),
    },
    rename_map={"ts_code": "index_code", "vol": "volume", "pct_chg": "pct_change"},
    fk_filter_col=None,  # index codes不在symbols表
)

FACTOR_VALUES = TableContract(
    table_name="factor_values",
    pk_columns=("code", "trade_date", "factor_name"),
    columns={
        "code": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "factor_name": ColumnSpec("str", nullable=False),
        "raw_value": ColumnSpec("float"),
        "neutral_value": ColumnSpec("float"),
        "zscore": ColumnSpec("float", source_unit=SourceUnit.DIMENSIONLESS, db_unit=DBUnit.DIMENSIONLESS),
    },
    fk_filter_col=None,
    skip_unit_conversion=True,  # z-score无量纲，跳过单位转换
)

NORTHBOUND_HOLDINGS = TableContract(
    table_name="northbound_holdings",
    pk_columns=("code", "trade_date"),
    columns={
        "code": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "hold_vol": ColumnSpec("int", source_unit=SourceUnit.GU, db_unit=DBUnit.GU, min_val=0),
        "hold_ratio": ColumnSpec("float", source_unit=SourceUnit.PCT, db_unit=DBUnit.PCT),
        "hold_mv": ColumnSpec("float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN),
        "net_buy_vol": ColumnSpec("int", source_unit=SourceUnit.GU, db_unit=DBUnit.GU),
    },
    rename_map={"ts_code": "code"},
)

SYMBOLS = TableContract(
    table_name="symbols",
    pk_columns=("code",),
    columns={
        "code": ColumnSpec("str", nullable=False),
        "ts_code": ColumnSpec("str"),
        "name": ColumnSpec("str", nullable=False),
        "market": ColumnSpec("str"),
        "board": ColumnSpec("str"),
        "exchange": ColumnSpec("str"),
        "industry_sw1": ColumnSpec("str"),
        "list_date": ColumnSpec("date"),
        "delist_date": ColumnSpec("date"),
        "list_status": ColumnSpec("str"),
        "is_hs": ColumnSpec("str"),
        "is_st": ColumnSpec("bool"),
    },
    fk_filter_col=None,  # symbols自身是被引用的表
    skip_unit_conversion=True,
)

EARNINGS_ANNOUNCEMENTS = TableContract(
    table_name="earnings_announcements",
    pk_columns=("id",),
    columns={
        "ts_code": ColumnSpec("str", nullable=False),
        "end_date": ColumnSpec("date"),
        "ann_date": ColumnSpec("date"),
        "f_ann_date": ColumnSpec("date"),
        "trade_date": ColumnSpec("date"),
        "basic_eps": ColumnSpec("float"),
        "eps_q4_ago": ColumnSpec("float"),
        "eps_surprise": ColumnSpec("float"),
        "eps_surprise_pct": ColumnSpec("float"),
        "report_type": ColumnSpec("str"),
        "source": ColumnSpec("str"),
    },
    fk_filter_col=None,
    skip_unit_conversion=True,
)


# ════════════════════════════════════════════════════════════
# Contract注册表 — 按table_name查找
# ════════════════════════════════════════════════════════════

CONTRACT_REGISTRY: dict[str, TableContract] = {
    c.table_name: c
    for c in [
        KLINES_DAILY,
        DAILY_BASIC,
        MONEYFLOW_DAILY,
        INDEX_DAILY,
        FACTOR_VALUES,
        NORTHBOUND_HOLDINGS,
        SYMBOLS,
        EARNINGS_ANNOUNCEMENTS,
    ]
}


def get_contract(table_name: str) -> TableContract:
    """按表名获取Contract。未注册的表raise KeyError。"""
    if table_name not in CONTRACT_REGISTRY:
        raise KeyError(f"No contract registered for table '{table_name}'. "
                       f"Available: {list(CONTRACT_REGISTRY.keys())}")
    return CONTRACT_REGISTRY[table_name]
