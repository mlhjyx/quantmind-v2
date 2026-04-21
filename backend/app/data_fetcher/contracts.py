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

    dtype: str  # "float" | "int" | "str" | "bool" | "date" | "uuid" | "jsonb" (MVP 2.2) | "text_array" | "decimal_array" (MVP 2.3)
    nullable: bool = True
    source_unit: SourceUnit | None = None  # Tushare原始单位
    db_unit: DBUnit | None = None  # DB存储单位
    min_val: float | None = None
    max_val: float | None = None
    # F22 (Session 21): NULL 率阈值 (0.0-1.0). None=不校验. 超阈值 DataPipeline
    # logger.error (fail-loud 铁律 33) + 写 IngestResult.null_ratio_warnings, 不 raise 不 drop.
    # 场景: Tushare API 端数据漂移 (e.g. daily_basic.dv_ttm 4-15 起从 0% → 31% → 100% NULL),
    # 下游 (data_quality_report / 钉钉) 按 warning 处置, DataPipeline 只负责暴露问题.
    null_ratio_max: float | None = None

    def __post_init__(self) -> None:
        """Domain validation (reviewer P3 采纳).

        null_ratio_max ∈ [0.0, 1.0] 或 None. 超界值 (如 1.5 或 -0.1) 在 import
        时即 raise, 避免 mis-configuration 拖到 ingest 运行时才爆.
        """
        if self.null_ratio_max is not None and not (0.0 <= self.null_ratio_max <= 1.0):
            raise ValueError(
                f"null_ratio_max must be in [0.0, 1.0], got {self.null_ratio_max}"
            )

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
_price_col = ColumnSpec(
    "float", nullable=True, source_unit=SourceUnit.YUAN, db_unit=DBUnit.YUAN, min_val=0
)


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
        "pct_change": ColumnSpec(
            "float",
            source_unit=SourceUnit.PCT_X100,
            db_unit=DBUnit.PCT_X100,
            min_val=-30,
            max_val=30,
        ),
        "volume": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU, min_val=0),
        "amount": ColumnSpec(
            "float", source_unit=SourceUnit.QIAN_YUAN, db_unit=DBUnit.YUAN, min_val=0
        ),
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
        # F22: pe_ttm null_ratio_max=0.05 — 历史 0% NULL, 4-15 drift 到 26.9% 是 Tushare API 端异常, 5% 阈值保留正常数据缺失容差
        "pe_ttm": ColumnSpec("float", null_ratio_max=0.05),
        "pb": ColumnSpec("float"),
        "ps": ColumnSpec("float"),
        "ps_ttm": ColumnSpec("float"),
        "dv_ratio": ColumnSpec("float", source_unit=SourceUnit.PCT, db_unit=DBUnit.PCT),
        # F22: dv_ttm null_ratio_max=0.05 — 历史 0% NULL, 4-15→4-20 drift 31.7%→100% 是 Tushare 端漂移
        "dv_ttm": ColumnSpec(
            "float", source_unit=SourceUnit.PCT, db_unit=DBUnit.PCT, null_ratio_max=0.05
        ),
        "total_share": ColumnSpec("float", source_unit=SourceUnit.WAN_GU, db_unit=DBUnit.WAN_GU),
        "float_share": ColumnSpec("float", source_unit=SourceUnit.WAN_GU, db_unit=DBUnit.WAN_GU),
        "free_share": ColumnSpec("float", source_unit=SourceUnit.WAN_GU, db_unit=DBUnit.WAN_GU),
        "total_mv": ColumnSpec(
            "float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN, min_val=0
        ),
        "circ_mv": ColumnSpec(
            "float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN, min_val=0
        ),
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
        "sell_elg_amount": ColumnSpec(
            "float", source_unit=SourceUnit.WAN_YUAN, db_unit=DBUnit.YUAN
        ),
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
        "amount": ColumnSpec(
            "float", source_unit=SourceUnit.QIAN_YUAN, db_unit=DBUnit.YUAN, min_val=0
        ),
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
        "zscore": ColumnSpec(
            "float", source_unit=SourceUnit.DIMENSIONLESS, db_unit=DBUnit.DIMENSIONLESS
        ),
    },
    fk_filter_col=None,
    skip_unit_conversion=True,  # z-score无量纲，跳过单位转换
)

# S2b (2026-04-15): 新增 FACTOR_IC_HISTORY Contract, 支持 factor_onboarding
# 走 DataPipeline 入库 (铁律 17). 所有 IC 数字必须由 ic_calculator 计算 (铁律 19).
# 多 horizon (1d/5d/10d/20d) + 派生 (abs/ma20/ma60/decay_level) schema 对齐
# 原 factor_onboarding.py _upsert_ic_history 写入的列.
FACTOR_IC_HISTORY = TableContract(
    table_name="factor_ic_history",
    pk_columns=("factor_name", "trade_date"),
    columns={
        "factor_name": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "ic_1d": ColumnSpec("float"),
        "ic_5d": ColumnSpec("float"),
        "ic_10d": ColumnSpec("float"),
        "ic_20d": ColumnSpec("float"),
        "ic_abs_1d": ColumnSpec("float"),
        "ic_abs_5d": ColumnSpec("float"),
        "ic_ma20": ColumnSpec("float"),
        "ic_ma60": ColumnSpec("float"),
        "decay_level": ColumnSpec("str"),
    },
    fk_filter_col=None,  # factor_name 是因子标识, 不是 symbols.code
    skip_unit_conversion=True,  # IC 是无量纲 Spearman 相关系数
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

MINUTE_BARS = TableContract(
    table_name="minute_bars",
    pk_columns=("code", "trade_time"),
    columns={
        "code": ColumnSpec("str", nullable=False),
        "trade_time": ColumnSpec("str", nullable=False),  # timestamp类型, 用str占位
        "trade_date": ColumnSpec("date", nullable=False),
        "open": _price_col,
        "high": _price_col,
        "low": _price_col,
        "close": _price_col,
        "volume": ColumnSpec("int", source_unit=SourceUnit.SHOU, db_unit=DBUnit.SHOU, min_val=0),
        "amount": ColumnSpec("float", source_unit=SourceUnit.YUAN, db_unit=DBUnit.YUAN, min_val=0),
        "adjustflag": ColumnSpec("str"),  # "1"=后复权 "2"=前复权 "3"=不复权
    },
    # Baostock原始code是 "sh.600519"/"sz.000001" 形式,
    # 由puller在DataFrame构造时转为带后缀的 "600519.SH"/"000001.SZ",
    # 此处不做rename (puller已经用'code'字段)。
    # Baostock不返回ts_code，不需要rename。
    rename_map={},
    fk_filter_col=None,  # Top-100 + A股补充, 不强制匹配symbols
    skip_unit_conversion=False,  # amount单位为元(Baostock原始)
)

STOCK_STATUS_DAILY = TableContract(
    table_name="stock_status_daily",
    pk_columns=("code", "trade_date"),
    columns={
        "code": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "is_st": ColumnSpec("bool", nullable=False),
        "is_suspended": ColumnSpec("bool", nullable=False),
        "is_new_stock": ColumnSpec("bool", nullable=False),
        "board": ColumnSpec("str"),
        "list_date": ColumnSpec("date"),
        "delist_date": ColumnSpec("date"),
    },
    fk_filter_col=None,  # 不过滤FK(回填时包含所有code)
    skip_unit_conversion=True,
)


# MVP 2.1c Sub2 (2026-04-18): shadow_portfolio 表 DataPipeline 迁移.
# 原 services/shadow_portfolio.py 逐行 INSERT ... ON CONFLICT, 改走 pipeline.ingest.
# PK 用 (strategy_name, trade_date, symbol_code) UNIQUE 约束 (id SERIAL 由 DB 自增).
# created_at 由 DB DEFAULT NOW() 管理, Contract 不列 (避 DataPipeline 无法传 NOW() 表达式).
SHADOW_PORTFOLIO = TableContract(
    table_name="shadow_portfolio",
    pk_columns=("strategy_name", "trade_date", "symbol_code"),
    columns={
        "strategy_name": ColumnSpec("str", nullable=False),
        "trade_date": ColumnSpec("date", nullable=False),
        "rebalance_date": ColumnSpec("date", nullable=False),
        "symbol_code": ColumnSpec("str", nullable=False),
        "predicted_score": ColumnSpec("float"),
        "weight": ColumnSpec("float", nullable=False, min_val=0.0, max_val=1.0),
        "rank_in_portfolio": ColumnSpec("int", min_val=1),
    },
    fk_filter_col=None,  # symbol_code 格式由调用方对齐, 不强制 FK
    skip_unit_conversion=True,
)


# MVP 2.3 Sub1 PR B (2026-04-18): backtest_run 表走 DataPipeline 迁移 (ADR-007 沿用老表策略).
# 老表 (docs/QUANTMIND_V2_DDL_FINAL.sql) 7 行历史 + 4 FK 依赖表 (backtest_daily_nav / backtest_holdings
# / backtest_trades / backtest_wf_windows) 保留. PR A (`a0e01db`) ALTER ADD 3 新列 (mode / lineage_id /
# extra_decimals) + CHECK + FK + partial index. 本 Contract 映射全 32 列 (不含 created_at —
# DB DEFAULT NOW() 管理, 遵循 SHADOW_PORTFOLIO pattern L345).
#
# 字段名映射 (ADR-007 tech debt, MVP 3.x Clean-up RENAME):
#   - Platform concept `config_hash` ↔ 老表列 `config_yaml_hash`
#   - Platform concept `factor_pool` ↔ 老表列 `factor_list` (走 text_array ColumnSpec)
#   - Platform concept `config` ↔ 老表列 `config_json`
#   - Platform concept `metrics.sharpe` ↔ 老表列 `sharpe_ratio` (独立 DECIMAL 列, 非 JSONB 聚合)
BACKTEST_RUN = TableContract(
    table_name="backtest_run",
    pk_columns=("run_id",),
    columns={
        # PK + metadata
        "run_id": ColumnSpec("uuid", nullable=False),
        "strategy_id": ColumnSpec("uuid"),  # FK → strategy(id), nullable (研究脚本无 strategy 绑定)
        "name": ColumnSpec("str"),
        "status": ColumnSpec("str"),  # pending / running / success / failed
        # 配置
        "config_json": ColumnSpec("jsonb", nullable=False),
        "factor_list": ColumnSpec("text_array", nullable=False),
        # 复现锚点 (铁律 15)
        "config_yaml_hash": ColumnSpec("str"),
        "git_commit": ColumnSpec("str"),
        # 核心指标 (engines/metrics.py PerformanceReport 映射, 非 JSONB 聚合)
        "annual_return": ColumnSpec("float"),
        "sharpe_ratio": ColumnSpec("float"),
        "max_drawdown": ColumnSpec("float"),
        "excess_return": ColumnSpec("float"),
        "calmar_ratio": ColumnSpec("float"),
        "sortino_ratio": ColumnSpec("float"),
        "information_ratio": ColumnSpec("float"),
        "beta": ColumnSpec("float"),
        "win_rate": ColumnSpec("float"),
        "profit_loss_ratio": ColumnSpec("float"),
        "annual_turnover": ColumnSpec("float"),
        "total_trades": ColumnSpec("int"),
        "max_consecutive_loss_days": ColumnSpec("int"),
        # 可信度指标 (Bootstrap CI)
        "sharpe_ci_lower": ColumnSpec("float"),
        "sharpe_ci_upper": ColumnSpec("float"),
        # 跳空 + 仓位偏差
        "avg_overnight_gap": ColumnSpec("float"),
        "position_deviation": ColumnSpec("float"),
        # JSONB 扩展
        "cost_sensitivity_json": ColumnSpec("jsonb"),
        "annual_breakdown_json": ColumnSpec("jsonb"),
        "market_state_json": ColumnSpec("jsonb"),
        # 运行元数据
        "start_date": ColumnSpec("date"),
        "end_date": ColumnSpec("date"),
        "elapsed_sec": ColumnSpec("int"),
        "error_message": ColumnSpec("str"),
        # PR A ALTER ADD 3 新列 (MVP 2.3)
        "mode": ColumnSpec("str"),  # BacktestMode enum value (chk_backtest_run_mode CHECK 容忍 NULL)
        "lineage_id": ColumnSpec("uuid"),  # FK → data_lineage(lineage_id), MVP 2.2 U3 追溯
        "extra_decimals": ColumnSpec("decimal_array"),  # 未来 metric 扩展预留 (decimal_array 直通)
    },
    fk_filter_col=None,  # run_id 客户端 uuid4 生成, 不走 symbols FK
    skip_unit_conversion=True,  # 配置 / 指标 / 血缘无单位转换
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
        FACTOR_IC_HISTORY,
        NORTHBOUND_HOLDINGS,
        SYMBOLS,
        EARNINGS_ANNOUNCEMENTS,
        STOCK_STATUS_DAILY,
        MINUTE_BARS,
        SHADOW_PORTFOLIO,
        BACKTEST_RUN,
    ]
}


def get_contract(table_name: str) -> TableContract:
    """按表名获取Contract。未注册的表raise KeyError。"""
    if table_name not in CONTRACT_REGISTRY:
        raise KeyError(
            f"No contract registered for table '{table_name}'. "
            f"Available: {list(CONTRACT_REGISTRY.keys())}"
        )
    return CONTRACT_REGISTRY[table_name]
