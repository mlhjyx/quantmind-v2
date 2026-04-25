"""MVP 2.3 Sub1 PR B · DBBacktestRegistry 单测 (mock pipeline + conn, 不依赖 DB).

覆盖:
  - log_run: Platform 概念 → 老表列字段映射 (ADR-007)
  - log_run: 调 DataPipeline.ingest(BACKTEST_RUN, lineage=...) 返 lineage_id
  - log_run: upserted_rows=0 → RuntimeError (fail-loud 铁律 33)
  - _perf_to_columns: PerformanceReport → 16 独立 DECIMAL 列
  - get_by_hash: SELECT SQL + 返 BacktestResult 反序列化
  - get_by_hash: 无记录返 None
  - list_recent: ORDER BY + LIMIT
  - _row_to_result: tuple → BacktestResult 结构正确

铁律: 17 (DataPipeline 入库) / 33 (fail-loud) / 25 / 38.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from backend.qm_platform._types import BacktestMode
from backend.qm_platform.backtest.interface import BacktestConfig, BacktestResult
from backend.qm_platform.backtest.registry import DBBacktestRegistry

# ─── Fixtures ──────────────────────────────────────────────


def _make_config(**overrides) -> BacktestConfig:
    base = {
        "start": date(2020, 1, 1),
        "end": date(2025, 12, 31),
        "universe": "csi300",
        "factor_pool": ("bp_ratio", "dv_ttm"),
        "rebalance_freq": "monthly",
        "top_n": 20,
        "industry_cap": 1.0,
        "size_neutral_beta": 0.5,
        "cost_model": "full",
        "capital": "1000000.0",
        "benchmark": "csi300",
        "extra": {},
    }
    base.update(overrides)
    return BacktestConfig(**base)


def _make_result(**overrides) -> BacktestResult:
    base = {
        "run_id": uuid4(),
        "config_hash": "h" * 64,
        "git_commit": "abc1234",
        "sharpe": 1.2,
        "annual_return": 0.15,
        "max_drawdown": -0.08,
        "total_return": 0.92,
        "trades_count": 123,
        "metrics": {},
    }
    base.update(overrides)
    return BacktestResult(**base)


def _fake_perf():
    """Fake PerformanceReport, 覆盖 _perf_to_columns 全字段."""
    return SimpleNamespace(
        sharpe_ratio=1.2,
        annual_return=0.15,
        max_drawdown=-0.08,
        calmar_ratio=1.875,
        sortino_ratio=1.5,
        information_ratio=0.5,
        beta=0.9,
        win_rate=0.55,
        profit_loss_ratio=1.3,
        annual_turnover=3.5,
        total_trades=123,
        max_consecutive_loss_days=7,
        bootstrap_sharpe_ci=(1.2, 0.9, 1.5),
        avg_open_gap=0.002,
        mean_position_deviation=0.01,
    )


def _make_ingest_result(upserted_rows: int = 1, lineage_id: UUID | None = None) -> SimpleNamespace:
    """Fake IngestResult."""
    return SimpleNamespace(
        upserted_rows=upserted_rows,
        rejected_rows=0,
        reject_reasons={},
        lineage_id=lineage_id or uuid4(),
    )


# ─── log_run: 字段映射 (3 tests) ────────────────────────────


def test_log_run_maps_fields_to_legacy_columns():
    """ADR-007 字段映射: config_hash→config_yaml_hash / factor_pool→factor_list / config→config_json."""
    pipeline = MagicMock()
    expected_lineage_id = uuid4()
    pipeline.ingest.return_value = _make_ingest_result(lineage_id=expected_lineage_id)

    registry = DBBacktestRegistry(pipeline=pipeline)
    cfg = _make_config()
    result = _make_result(config_hash="myconfighash", git_commit="commit_sha")

    returned = registry.log_run(
        config=cfg,
        result=result,
        artifact_paths={},
        mode=BacktestMode.FULL_5Y,
        elapsed_sec=30,
        lineage=None,
        perf=_fake_perf(),
        start_date=date(2020, 1, 1),
        end_date=date(2025, 12, 31),
    )

    # PR B P1-D fix: lineage=None → log_run 返 None (不走 write_lineage 路径)
    assert returned is None

    # 检查 ingest 被调用 + df 内容
    pipeline.ingest.assert_called_once()
    df_arg, contract_arg = pipeline.ingest.call_args.args
    row = df_arg.iloc[0].to_dict()
    assert row["config_yaml_hash"] == "myconfighash"  # ← config_hash 映射
    assert row["factor_list"] == list(cfg.factor_pool)  # ← factor_pool 映射
    # config_json 是 JSON-safe 转换后的 dict (date → ISO str), 走 json.loads(json.dumps(default=str))
    # 不等于原 asdict(cfg) (date 字段类型不同). 验证 universe/top_n 字段保留即可.
    assert row["config_json"]["universe"] == cfg.universe
    assert row["config_json"]["top_n"] == cfg.top_n
    assert row["config_json"]["start"] == cfg.start.isoformat()  # date → ISO str
    assert row["git_commit"] == "commit_sha"
    assert row["mode"] == "full_5y"  # BacktestMode.FULL_5Y.value
    assert row["status"] == "success"
    assert row["elapsed_sec"] == 30
    assert row["lineage_id"] is None  # 本 test 没传 lineage, 应 None


def test_log_run_writes_enriched_lineage_and_not_via_pipeline():
    """PR B P1-B fix: 走 app.data_fetcher.pipeline.write_lineage_with_outputs 追加 backtest_run 输出,
    pipeline.ingest(lineage=None) 避双写.

    验证:
      - write_lineage_with_outputs 被调 1 次, 传入原 lineage + output_refs 含 backtest_run.run_id
      - pipeline.ingest 被调时 lineage kwarg = None (避免 _record_lineage 双写 + drop enriched 版)
      - log_run 返回 write_lineage_with_outputs 的 UUID
    """
    from unittest.mock import patch

    from backend.qm_platform.data.lineage import CodeRef, Lineage, LineageRef

    pipeline = MagicMock()
    pipeline.ingest.return_value = _make_ingest_result(lineage_id=None)
    pipeline.conn = MagicMock()
    registry = DBBacktestRegistry(pipeline=pipeline, conn=pipeline.conn)

    real_lineage = Lineage(
        inputs=[LineageRef(table="factor_values", pk_values={"f": "bp_ratio"})],
        code=CodeRef(git_commit="abc", module="test"),
        params={"mode": "quick_1y"},
    )
    result = _make_result()
    expected_lineage_id = real_lineage.lineage_id

    # Mock registry module 内 import 的 write_lineage_with_outputs
    with patch(
        "backend.qm_platform.backtest.registry.write_lineage_with_outputs",
        return_value=expected_lineage_id,
    ) as mock_gw:
        returned = registry.log_run(
            config=_make_config(),
            result=result,
            artifact_paths={},
            mode=BacktestMode.QUICK_1Y,
            lineage=real_lineage,
            perf=_fake_perf(),
        )

    # 1. write_lineage_with_outputs 调 1 次, 传原 lineage + backtest_run output ref
    mock_gw.assert_called_once()
    args = mock_gw.call_args.args
    assert args[0] is real_lineage  # 原 lineage 直传 (helper 内部 replace 追加 outputs)
    output_refs = args[1]
    assert len(output_refs) == 1
    # output_refs[0] 由 make_lineage_ref(table='backtest_run', run_id=...) 构造
    bt_ref = output_refs[0]
    assert bt_ref.table == "backtest_run"
    assert bt_ref.pk_values["run_id"] == str(result.run_id)

    # 2. pipeline.ingest 调时 lineage=None (避双写)
    kwargs = pipeline.ingest.call_args.kwargs
    assert kwargs["lineage"] is None, "pipeline.ingest must not trigger _record_lineage"

    # 3. log_run 返 helper 返回的 lineage_id
    assert returned == expected_lineage_id


def test_log_run_without_lineage_returns_none():
    """lineage=None 时 log_run 返 None (P1-D: return 类型 UUID | None)."""
    pipeline = MagicMock()
    pipeline.ingest.return_value = _make_ingest_result()
    registry = DBBacktestRegistry(pipeline=pipeline)

    returned = registry.log_run(
        config=_make_config(),
        result=_make_result(),
        artifact_paths={},
        mode=BacktestMode.QUICK_1Y,
        lineage=None,
        perf=_fake_perf(),
    )
    assert returned is None


def test_log_run_pipeline_conn_identity_assert():
    """P1-A: 若 pipeline+conn 都显式设置, 必同一 conn 对象 (否则 assert fail)."""
    from unittest.mock import patch

    from backend.qm_platform.data.lineage import CodeRef, Lineage

    pipeline = MagicMock()
    pipeline.ingest.return_value = _make_ingest_result()
    pipeline.conn = MagicMock()  # 对象 A
    conn_b = MagicMock()  # 对象 B (不同)
    registry = DBBacktestRegistry(pipeline=pipeline, conn=conn_b)

    lineage = Lineage(
        inputs=[],
        code=CodeRef(git_commit="x", module="test"),
        params={},
    )
    with (
        patch("backend.qm_platform.backtest.registry.write_lineage_with_outputs"),
        pytest.raises(AssertionError, match="same object"),
    ):
        registry.log_run(
            config=_make_config(),
            result=_make_result(),
            artifact_paths={},
            mode=BacktestMode.QUICK_1Y,
            lineage=lineage,
            perf=_fake_perf(),
        )


def test_log_run_zero_upserted_raises_fail_loud():
    """0 rows upserted → RuntimeError (铁律 33 fail-loud)."""
    pipeline = MagicMock()
    pipeline.ingest.return_value = _make_ingest_result(upserted_rows=0)
    pipeline.ingest.return_value.rejected_rows = 1
    pipeline.ingest.return_value.reject_reasons = {"invalid_jsonb_config_json": 1}

    registry = DBBacktestRegistry(pipeline=pipeline)
    with pytest.raises(RuntimeError, match="0 rows upserted"):
        registry.log_run(
            config=_make_config(),
            result=_make_result(),
            artifact_paths={},
            mode=BacktestMode.QUICK_1Y,
            perf=_fake_perf(),
        )


# ─── _perf_to_columns (2 tests) ────────────────────────────


def test_perf_to_columns_full_mapping():
    """PerformanceReport 字段映射到 backtest_run 独立 DECIMAL 列."""
    perf = _fake_perf()
    cols = DBBacktestRegistry._perf_to_columns(perf)
    assert cols["annual_return"] == 0.15
    assert cols["sharpe_ratio"] == 1.2
    assert cols["max_drawdown"] == -0.08
    assert cols["calmar_ratio"] == 1.875
    assert cols["total_trades"] == 123
    assert cols["max_consecutive_loss_days"] == 7
    assert cols["sharpe_ci_lower"] == 0.9
    assert cols["sharpe_ci_upper"] == 1.5
    assert cols["avg_overnight_gap"] == 0.002  # ← avg_open_gap 映射
    assert cols["position_deviation"] == 0.01  # ← mean_position_deviation 映射


def test_perf_to_columns_handles_missing_ci():
    """bootstrap_sharpe_ci 缺失 → sharpe_ci_lower/upper 为 None."""
    perf = SimpleNamespace(
        sharpe_ratio=1.0,
        annual_return=0.1,
        max_drawdown=-0.05,
        calmar_ratio=2.0,
        sortino_ratio=1.2,
        information_ratio=0.3,
        beta=0.8,
        win_rate=0.5,
        profit_loss_ratio=1.1,
        annual_turnover=2.0,
        total_trades=50,
        max_consecutive_loss_days=5,
        bootstrap_sharpe_ci=(),  # 空元组
        avg_open_gap=0.0,
        mean_position_deviation=0.0,
    )
    cols = DBBacktestRegistry._perf_to_columns(perf)
    assert cols["sharpe_ci_lower"] is None
    assert cols["sharpe_ci_upper"] is None


# ─── get_by_hash (3 tests) ─────────────────────────────────


def test_get_by_hash_returns_none_when_not_found():
    """无匹配 row → 返 None."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn.cursor.return_value.__enter__.return_value = cur

    registry = DBBacktestRegistry(pipeline=MagicMock(), conn=conn)
    assert registry.get_by_hash("nohash") is None


def test_get_by_hash_returns_backtest_result():
    """命中 row → 反序列化 BacktestResult."""
    run_id = uuid4()
    lineage_id = uuid4()
    row = (
        run_id,  # run_id
        "mycfghash",  # config_yaml_hash
        "commit_sha",  # git_commit
        1.2,  # sharpe_ratio
        0.15,  # annual_return
        -0.08,  # max_drawdown
        123,  # total_trades
        1.875,
        1.5,
        0.5,  # calmar / sortino / IR
        0.9,
        0.55,
        1.3,
        3.5,  # beta / win_rate / P&L / turnover
        7,  # max_consecutive_loss_days
        0.9,
        1.5,  # sharpe_ci_lower / upper
        0.002,
        0.01,  # gap / position_dev
        0.05,  # excess_return
        lineage_id,  # lineage_id
    )
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = row
    conn.cursor.return_value.__enter__.return_value = cur

    registry = DBBacktestRegistry(pipeline=MagicMock(), conn=conn)
    result = registry.get_by_hash("mycfghash")

    assert result is not None
    assert result.run_id == run_id
    assert result.config_hash == "mycfghash"
    assert result.git_commit == "commit_sha"
    assert result.sharpe == 1.2
    assert result.trades_count == 123
    assert result.lineage_id == lineage_id


def test_get_by_hash_sql_uses_config_yaml_hash_column():
    """SQL 走 config_yaml_hash (ADR-007 老表列名) 不是 config_hash."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = None
    conn.cursor.return_value.__enter__.return_value = cur

    registry = DBBacktestRegistry(pipeline=MagicMock(), conn=conn)
    registry.get_by_hash("somehash")

    sql_executed = cur.execute.call_args.args[0]
    assert "config_yaml_hash" in sql_executed
    assert "ORDER BY created_at DESC" in sql_executed
    assert "LIMIT 1" in sql_executed


# ─── list_recent (1 test) ──────────────────────────────────


def test_list_recent_orders_desc_and_limits():
    """list_recent SQL 走 ORDER BY created_at DESC + LIMIT."""
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = []
    conn.cursor.return_value.__enter__.return_value = cur

    registry = DBBacktestRegistry(pipeline=MagicMock(), conn=conn)
    result = registry.list_recent(limit=5)

    assert result == []
    sql = cur.execute.call_args.args[0]
    assert "ORDER BY created_at DESC" in sql
    assert "LIMIT" in sql
    # limit 作为 param 传, 不是硬编码
    assert cur.execute.call_args.args[1] == (5,)


# ─── _row_to_result None-handling (1 test) ─────────────────


def test_row_to_result_handles_nulls():
    """DB 列为 NULL → 反序列化不 raise, 默认 0.0/0/None."""
    run_id = uuid4()
    row = (
        run_id,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,  # lineage_id
    )
    result = DBBacktestRegistry._row_to_result(row)
    assert result.run_id == run_id
    assert result.config_hash == ""
    assert result.git_commit == ""
    assert result.sharpe == 0.0
    assert result.trades_count == 0
    assert result.lineage_id is None
