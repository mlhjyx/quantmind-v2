"""MVP 2.3 Sub1 PR B · DBBacktestRegistry live PG 端到端 (铁律 10b).

subprocess 启动 + 真 PG → 测试核心 Platform 层 round-trip:
  1. DBBacktestRegistry.log_run 走 DataPipeline.ingest(BACKTEST_RUN, lineage=...)
  2. 验证真 PG 写入 (UUID / TEXT[] factor_list / NUMERIC[] extra_decimals / JSONB config / DECIMAL 指标)
  3. lineage_id 非空 + data_lineage FK 真建立 (MVP 2.2 U3 集成)
  4. get_by_hash 按 config_yaml_hash 回查, 反序列化 BacktestResult 结构正确
  5. 清理测试 run (保 7 行历史 + 4 FK 依赖表不污染)

不在本 smoke 范围 (走 unit):
  - PlatformBacktestRunner.run 端到端 (需真 engine, 太重)
  - cache hit / mode dispatch / lineage 构造

失败意味: BACKTEST_RUN TableContract 字段不对齐 / PG 类型 adapter 边界 / lineage FK 断链 / config_yaml_hash 查重失效.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]

_SMOKE_CODE = """
from dataclasses import asdict
from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pandas as pd

from app.data_fetcher.contracts import BACKTEST_RUN
from app.data_fetcher.pipeline import DataPipeline
from app.services.db import get_sync_conn
from backend.qm_platform._types import BacktestMode
from backend.qm_platform.backtest.interface import BacktestConfig, BacktestResult
from backend.qm_platform.backtest.registry import DBBacktestRegistry
from backend.qm_platform.data.lineage import CodeRef, Lineage, LineageRef

# 远古 hash 前缀避免碰撞老 7 行 + 未来真 run
SMOKE_HASH = "_smoke_mvp_2_3_pr_b_" + uuid4().hex[:16]

conn = get_sync_conn()
try:
    # 清理可能的残留
    with conn.cursor() as cur:
        cur.execute("DELETE FROM backtest_run WHERE config_yaml_hash LIKE %s",
                    ("_smoke_mvp_2_3_pr_b_%",))
    conn.commit()

    # ─── 1. 构造 BacktestConfig + BacktestResult + PerformanceReport mock ──
    cfg = BacktestConfig(
        start=date(2020, 1, 1),
        end=date(2025, 12, 31),
        universe="csi300",
        factor_pool=("bp_ratio", "dv_ttm"),
        rebalance_freq="monthly",
        top_n=20,
        industry_cap=1.0,
        size_neutral_beta=0.50,
        cost_model="full",
        capital="1000000.0",
        benchmark="csi300",
        extra={},
    )
    run_id = uuid4()
    result = BacktestResult(
        run_id=run_id,
        config_hash=SMOKE_HASH,
        git_commit="smoke_commit",
        sharpe=1.2,
        annual_return=0.15,
        max_drawdown=-0.08,
        total_return=0.92,
        trades_count=123,
        metrics={},
    )
    perf = SimpleNamespace(
        sharpe_ratio=1.2, annual_return=0.15, max_drawdown=-0.08,
        calmar_ratio=1.875, sortino_ratio=1.5, information_ratio=0.5,
        beta=0.9, win_rate=0.55, profit_loss_ratio=1.3, annual_turnover=3.5,
        total_trades=123, max_consecutive_loss_days=7,
        bootstrap_sharpe_ci=(1.2, 0.9, 1.5),
        avg_open_gap=0.002, mean_position_deviation=0.01,
    )
    # Lineage 构造 (MVP 2.2 U3)
    lineage = Lineage(
        inputs=[
            LineageRef(table="factor_values", pk_values={"factor": "bp_ratio"}),
            LineageRef(table="klines_daily", pk_values={"range": "2020-2025"}),
        ],
        code=CodeRef(git_commit="smoke_commit", module="smoke.test_mvp_2_3"),
        params={"mode": "quick_1y", "smoke": True},
    )

    # ─── 2. DBBacktestRegistry.log_run: 真 PG 写入 ──────────
    pipeline = DataPipeline(conn)
    registry = DBBacktestRegistry(pipeline=pipeline, conn=conn)
    lineage_id = registry.log_run(
        config=cfg,
        result=result,
        artifact_paths={},
        mode=BacktestMode.QUICK_1Y,
        elapsed_sec=30,
        lineage=lineage,
        perf=perf,
        start_date=cfg.start,
        end_date=cfg.end,
    )
    assert lineage_id is not None, "log_run must return lineage_id"

    # ─── 3. 验证真 PG 写入 + 类型 adapter ─────────────────────
    with conn.cursor() as cur:
        cur.execute(
            "SELECT run_id, config_yaml_hash, factor_list, config_json, "
            "sharpe_ratio, mode, lineage_id "
            "FROM backtest_run WHERE config_yaml_hash = %s",
            (SMOKE_HASH,),
        )
        row = cur.fetchone()
    assert row is not None, "backtest_run 应有 1 行真写入"
    db_run_id, db_hash, db_factor_list, db_config_json, db_sharpe, db_mode, db_lineage_id = row

    # UUID round-trip
    assert str(db_run_id) == str(run_id), f"run_id mismatch: {db_run_id} vs {run_id}"
    # config_yaml_hash
    assert db_hash == SMOKE_HASH
    # TEXT[] round-trip: Python list → PG TEXT[] → Python list
    assert db_factor_list == ["bp_ratio", "dv_ttm"], f"factor_list TEXT[] adapter fail: {db_factor_list}"
    # JSONB round-trip
    assert isinstance(db_config_json, dict), f"config_json JSONB adapter fail: {type(db_config_json)}"
    assert db_config_json["universe"] == "csi300"
    # DECIMAL 指标
    assert float(db_sharpe) == 1.2
    # mode (PR A ALTER 新列)
    assert db_mode == "quick_1y"
    # lineage_id FK 真建立 (MVP 2.2 U3)
    assert db_lineage_id is not None, "lineage_id FK 必须非空"
    assert str(db_lineage_id) == str(lineage_id), "lineage_id 回填不一致"

    # ─── 4. data_lineage 表真写入 (FK 验证) ──────────────────
    with conn.cursor() as cur:
        cur.execute("SELECT lineage_id FROM data_lineage WHERE lineage_id = %s", (lineage_id,))
        lrow = cur.fetchone()
    assert lrow is not None, "data_lineage 表应含新写入的 lineage_id (MVP 2.2 集成)"

    # ─── 5. get_by_hash 回读 + 反序列化 ──────────────────────
    retrieved = registry.get_by_hash(SMOKE_HASH)
    assert retrieved is not None, "get_by_hash 必返 BacktestResult"
    assert retrieved.run_id == run_id
    assert retrieved.config_hash == SMOKE_HASH
    assert abs(retrieved.sharpe - 1.2) < 1e-6
    assert retrieved.trades_count == 123
    assert retrieved.lineage_id == lineage_id

    # ─── 6. list_recent 含本 run ─────────────────────────────
    recent = registry.list_recent(limit=20)
    assert any(r.config_hash == SMOKE_HASH for r in recent), "list_recent 应含本 smoke run"

    print("SMOKE PASS: log_run + DB round-trip + lineage FK + get_by_hash + list_recent all OK")
finally:
    # 清理测试 run (保 7 行历史 + data_lineage 随之 orphan 也清理)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM backtest_run WHERE config_yaml_hash LIKE %s",
                ("_smoke_mvp_2_3_pr_b_%",),
            )
            # data_lineage orphan cleanup (no cascade from backtest_run, 手动)
            cur.execute(
                "DELETE FROM data_lineage WHERE lineage_id NOT IN "
                "(SELECT DISTINCT lineage_id FROM factor_values WHERE lineage_id IS NOT NULL) "
                "AND lineage_id NOT IN "
                "(SELECT DISTINCT lineage_id FROM backtest_run WHERE lineage_id IS NOT NULL) "
                "AND created_at >= NOW() - INTERVAL '1 hour'"
            )
        conn.commit()
    finally:
        conn.close()
"""


@pytest.mark.smoke
def test_mvp_2_3_backtest_live_log_run_and_round_trip() -> None:
    """subprocess 生产入口真启动 (铁律 10b), 验证 DBBacktestRegistry 全 round-trip."""
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
            f"MVP 2.3 backtest live smoke failed (exit={result.returncode}):\n"
            f"stderr[:2000]:\n{result.stderr[:2000]}\n"
            f"stdout[:1000]:\n{result.stdout[:1000]}"
        )
    assert "SMOKE PASS" in result.stdout, f"stdout: {result.stdout[:500]}"
