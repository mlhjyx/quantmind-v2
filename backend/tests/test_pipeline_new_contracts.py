"""MVP 2.1c Sub-commit 2: SHADOW_PORTFOLIO + STOCK_STATUS_DAILY 新 TableContract 结构 + SQL 生成.

DataPipeline.ingest 的完整端到端 (真 execute_values) 留 live smoke (test_mvp_2_1c_c_level_live).
本单测覆盖:
  - Contract 属性 (columns / pk / fk_filter_col / skip_unit_conversion)
  - CONTRACT_REGISTRY 注册正确
  - DataPipeline._build_upsert_sql 生成 SQL 格式 (PG 语法验证, 不真跑)
  - records DataFrame 构造 (shadow_portfolio 迁移后字段对齐)
"""
from __future__ import annotations

import pandas as pd

from app.data_fetcher.contracts import (
    CONTRACT_REGISTRY,
    SHADOW_PORTFOLIO,
    STOCK_STATUS_DAILY,
)
from app.data_fetcher.pipeline import DataPipeline

# ============================================================
# Contract 结构 (4 tests)
# ============================================================


def test_shadow_portfolio_contract_structure():
    """SHADOW_PORTFOLIO Contract 字段对齐生产 DDL."""
    assert SHADOW_PORTFOLIO.table_name == "shadow_portfolio"
    assert SHADOW_PORTFOLIO.pk_columns == (
        "strategy_name", "trade_date", "symbol_code",
    )
    expected_cols = {
        "strategy_name", "trade_date", "rebalance_date", "symbol_code",
        "predicted_score", "weight", "rank_in_portfolio",
    }
    assert set(SHADOW_PORTFOLIO.columns.keys()) == expected_cols
    assert SHADOW_PORTFOLIO.fk_filter_col is None
    assert SHADOW_PORTFOLIO.skip_unit_conversion is True
    # 值域约束
    assert SHADOW_PORTFOLIO.columns["weight"].min_val == 0.0
    assert SHADOW_PORTFOLIO.columns["weight"].max_val == 1.0
    assert SHADOW_PORTFOLIO.columns["rank_in_portfolio"].min_val == 1
    # 非空约束
    assert SHADOW_PORTFOLIO.columns["strategy_name"].nullable is False
    assert SHADOW_PORTFOLIO.columns["weight"].nullable is False
    assert SHADOW_PORTFOLIO.columns["predicted_score"].nullable is True


def test_stock_status_daily_contract_structure():
    """STOCK_STATUS_DAILY Contract (MVP 1.1 已存) 字段对齐 DDL."""
    assert STOCK_STATUS_DAILY.table_name == "stock_status_daily"
    assert STOCK_STATUS_DAILY.pk_columns == ("code", "trade_date")
    expected_cols = {
        "code", "trade_date", "is_st", "is_suspended", "is_new_stock",
        "board", "list_date", "delist_date",
    }
    assert set(STOCK_STATUS_DAILY.columns.keys()) == expected_cols
    assert STOCK_STATUS_DAILY.fk_filter_col is None
    assert STOCK_STATUS_DAILY.skip_unit_conversion is True
    # PK + is_st/is_suspended/is_new_stock 非空
    for c in ("code", "trade_date", "is_st", "is_suspended", "is_new_stock"):
        assert STOCK_STATUS_DAILY.columns[c].nullable is False, f"{c} should be non-null"


def test_both_contracts_registered():
    """2 Contract 在 CONTRACT_REGISTRY 可查."""
    assert CONTRACT_REGISTRY["shadow_portfolio"] is SHADOW_PORTFOLIO
    assert CONTRACT_REGISTRY["stock_status_daily"] is STOCK_STATUS_DAILY


def test_shadow_portfolio_contract_no_unit_conversion():
    """SHADOW_PORTFOLIO 无单位 (score/weight/rank 均无量纲)."""
    for col_name, spec in SHADOW_PORTFOLIO.columns.items():
        # 应无 source_unit/db_unit 单位标注 (跳过转换)
        assert spec.source_unit is None, f"{col_name} source_unit should be None"
        assert spec.db_unit is None, f"{col_name} db_unit should be None"


# ============================================================
# _build_upsert_sql SQL 生成格式 (3 tests)
# ============================================================


def test_shadow_portfolio_upsert_sql_format():
    """验证 DataPipeline._build_upsert_sql 为 SHADOW_PORTFOLIO 生成 PG 语法."""
    pipeline = DataPipeline(conn=None)  # conn lazy, 不 touch DB
    columns = list(SHADOW_PORTFOLIO.columns.keys())
    sql = pipeline._build_upsert_sql(SHADOW_PORTFOLIO, columns)
    # INSERT + conflict target + UPDATE EXCLUDED
    assert sql.startswith("INSERT INTO shadow_portfolio (")
    assert "VALUES %s" in sql
    assert "ON CONFLICT (strategy_name, trade_date, symbol_code) DO UPDATE SET" in sql
    # non-PK 列全部在 UPDATE SET
    for non_pk in ("rebalance_date", "predicted_score", "weight", "rank_in_portfolio"):
        assert f"{non_pk} = EXCLUDED.{non_pk}" in sql, f"missing {non_pk} update"


def test_stock_status_daily_upsert_sql_format():
    """验证 STOCK_STATUS_DAILY 生成 SQL."""
    pipeline = DataPipeline(conn=None)
    columns = list(STOCK_STATUS_DAILY.columns.keys())
    sql = pipeline._build_upsert_sql(STOCK_STATUS_DAILY, columns)
    assert sql.startswith("INSERT INTO stock_status_daily (")
    assert "ON CONFLICT (code, trade_date) DO UPDATE SET" in sql
    # PK 不在 UPDATE
    assert "code = EXCLUDED.code" not in sql
    assert "trade_date = EXCLUDED.trade_date" not in sql
    # 非 PK 在 UPDATE
    for non_pk in ("is_st", "is_suspended", "is_new_stock", "board", "list_date", "delist_date"):
        assert f"{non_pk} = EXCLUDED.{non_pk}" in sql


def test_upsert_sql_all_pk_no_update():
    """全列都是 PK 时应生成 DO NOTHING (而非 DO UPDATE)."""
    pipeline = DataPipeline(conn=None)
    # 模拟: columns 只含 pk
    columns = list(SHADOW_PORTFOLIO.pk_columns)
    sql = pipeline._build_upsert_sql(SHADOW_PORTFOLIO, columns)
    assert "DO NOTHING" in sql
    assert "DO UPDATE" not in sql


# ============================================================
# records DataFrame 构造 + 单位转换行为 (2 tests)
# ============================================================


def test_shadow_portfolio_record_construction():
    """shadow_portfolio.py 迁移后 DataFrame 字段对齐 Contract."""
    df_top_mock = pd.DataFrame({
        "code": ["600519.SH", "000001.SZ"],
        "predicted_score": [0.15, 0.08],
        "weight": [0.5, 0.5],
        "rank_in_portfolio": [1, 2],
    })
    from datetime import date
    records = pd.DataFrame({
        "strategy_name": "lgbm_test",
        "trade_date": date(2026, 4, 15),
        "rebalance_date": date(2026, 4, 16),
        "symbol_code": df_top_mock["code"].astype(str),
        "predicted_score": df_top_mock["predicted_score"].astype(float),
        "weight": df_top_mock["weight"].astype(float),
        "rank_in_portfolio": df_top_mock["rank_in_portfolio"].astype(int),
    })
    # 所有 Contract 列在 records
    for col in SHADOW_PORTFOLIO.columns:
        assert col in records.columns, f"missing {col}"
    # 字段类型
    assert records["weight"].dtype.kind == "f"
    assert records["rank_in_portfolio"].dtype.kind == "i"


def test_stock_status_daily_record_construction():
    """pt_data_service._ingest_stock_status records → DataFrame 字段对齐 Contract."""
    from datetime import date
    records_tuples = [
        ("600519.SH", date(2026, 4, 15), False, False, False, "main",
         date(2001, 8, 27), None),
        ("300001.SZ", date(2026, 4, 15), True, False, False, "gem",
         date(2009, 1, 1), None),
    ]
    df = pd.DataFrame(
        records_tuples,
        columns=[
            "code", "trade_date", "is_st", "is_suspended", "is_new_stock",
            "board", "list_date", "delist_date",
        ],
    )
    for col in STOCK_STATUS_DAILY.columns:
        assert col in df.columns, f"missing {col}"
    # 类型: bool 列
    assert df["is_st"].dtype == bool
    assert df["is_suspended"].dtype == bool
