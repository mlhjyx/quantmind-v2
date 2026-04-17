"""Smoke test — MVP 2.1c Sub2 C 级 DataPipeline.ingest live PG 端到端 (铁律 10b).

subprocess 启动 + live PG + 真跑 ingest 2 新 Contract (SHADOW_PORTFOLIO + STOCK_STATUS_DAILY),
验证:
  1. DataPipeline 从 SHADOW_PORTFOLIO Contract 生成正确 upsert SQL
  2. 真插 2 行 shadow_portfolio (strategy_name='_smoke_test_mvp_2_1c'), upserted_rows=2
  3. 重复 ingest 触发 ON CONFLICT UPDATE (更新 weight/rank), upserted_rows=2 依然
  4. 真插 1 行 stock_status_daily (code='SMOKE_TEST', trade_date='1900-01-01'),
     upserted_rows=1 + ON CONFLICT UPDATE 二次 ingest=1
  5. 清理测试数据 (DELETE by strategy_name / code+trade_date) 确保无污染生产表

失败意味: DataPipeline.ingest 破坏语义 / Contract 字段不对齐 DB schema / ON CONFLICT 触发异常.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SMOKE_CODE = """
from datetime import date

import pandas as pd

from app.data_fetcher.contracts import SHADOW_PORTFOLIO, STOCK_STATUS_DAILY
from app.data_fetcher.pipeline import DataPipeline
from app.services.db import get_sync_conn

SMOKE_STRATEGY = '_smoke_test_mvp_2_1c'
SMOKE_CODE = 'SMOKE_TEST'
SMOKE_DATE = date(1900, 1, 1)  # 远古日期避免碰撞生产数据

conn = get_sync_conn()
try:
    # 清理可能的残留 (前 run 失败时留下)
    cur = conn.cursor()
    cur.execute('DELETE FROM shadow_portfolio WHERE strategy_name = %s',
                (SMOKE_STRATEGY,))
    cur.execute(
        'DELETE FROM stock_status_daily WHERE code = %s AND trade_date = %s',
        (SMOKE_CODE, SMOKE_DATE),
    )
    conn.commit()
    cur.close()

    # ─── 1. SHADOW_PORTFOLIO ingest ────────────────────────────
    pipeline = DataPipeline(conn)
    df_shadow = pd.DataFrame({
        'strategy_name': SMOKE_STRATEGY,
        'trade_date': SMOKE_DATE,
        'rebalance_date': SMOKE_DATE,
        'symbol_code': ['TEST.SH', 'TEST.SZ'],
        'predicted_score': [0.5, 0.3],
        'weight': [0.6, 0.4],
        'rank_in_portfolio': [1, 2],
    })
    result = pipeline.ingest(df_shadow, SHADOW_PORTFOLIO)
    assert result.upserted_rows == 2, f'SHADOW_PORTFOLIO ingest {result.upserted_rows}'
    assert result.rejected_rows == 0, f'rejected: {result.reject_reasons}'

    # 2nd ingest: 改 weight 触发 ON CONFLICT UPDATE
    df_shadow['weight'] = [0.7, 0.3]
    result2 = pipeline.ingest(df_shadow, SHADOW_PORTFOLIO)
    assert result2.upserted_rows == 2, f'SHADOW_PORTFOLIO update {result2.upserted_rows}'

    # Verify UPDATE 生效
    cur = conn.cursor()
    cur.execute(
        'SELECT weight FROM shadow_portfolio '
        'WHERE strategy_name = %s AND symbol_code = %s',
        (SMOKE_STRATEGY, 'TEST.SH'),
    )
    row = cur.fetchone()
    assert row is not None and abs(row[0] - 0.7) < 1e-6, f'weight not updated: {row}'
    cur.close()

    # ─── 2. STOCK_STATUS_DAILY ingest ────────────────────────
    df_status = pd.DataFrame({
        'code': [SMOKE_CODE],
        'trade_date': [SMOKE_DATE],
        'is_st': [False],
        'is_suspended': [False],
        'is_new_stock': [False],
        'board': ['main'],
        'list_date': [SMOKE_DATE],
        'delist_date': [None],
    })
    result3 = pipeline.ingest(df_status, STOCK_STATUS_DAILY)
    assert result3.upserted_rows == 1, f'STOCK_STATUS_DAILY ingest {result3.upserted_rows}'

    # 2nd ingest: 改 is_st=True 触发 UPDATE
    df_status['is_st'] = [True]
    result4 = pipeline.ingest(df_status, STOCK_STATUS_DAILY)
    assert result4.upserted_rows == 1, f'STOCK_STATUS_DAILY update {result4.upserted_rows}'

    cur = conn.cursor()
    cur.execute(
        'SELECT is_st FROM stock_status_daily WHERE code = %s AND trade_date = %s',
        (SMOKE_CODE, SMOKE_DATE),
    )
    row = cur.fetchone()
    assert row is not None and row[0] is True, f'is_st not updated: {row}'
    cur.close()

    print('OK 2.1c c_level live: shadow=2+2 upd, status=1+1 upd')
finally:
    # 清理
    cur = conn.cursor()
    cur.execute('DELETE FROM shadow_portfolio WHERE strategy_name = %s',
                (SMOKE_STRATEGY,))
    cur.execute(
        'DELETE FROM stock_status_daily WHERE code = %s AND trade_date = %s',
        (SMOKE_CODE, SMOKE_DATE),
    )
    conn.commit()
    cur.close()
    conn.close()
"""


@pytest.mark.smoke
def test_c_level_ingest_live_both_contracts() -> None:
    """SHADOW_PORTFOLIO + STOCK_STATUS_DAILY live PG ingest + ON CONFLICT (铁律 10b)."""
    result = subprocess.run(
        [sys.executable, "-c", _SMOKE_CODE],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        pytest.fail(
            f"MVP 2.1c C level live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "OK 2.1c c_level live" in result.stdout, result.stdout
