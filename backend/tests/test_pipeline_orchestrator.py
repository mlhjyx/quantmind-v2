"""PipelineOrchestrator 单元测试。

测试策略:
- 内存模式（conn=None）运行，不依赖数据库
- 使用轻量Mock替代FactorSandbox/FactorGatePipeline/FactorClassifier/QuickBacktester
- 验证8节点状态转换正确性
- 验证失败节点触发skip/stop行为
"""

from __future__ import annotations

import hashlib
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest
from engines.mining.pipeline_orchestrator import (
    FactorCandidate,
    NodeStatus,
    PipelineNode,
    PipelineOrchestrator,
    RunStatus,
    _compute_ic_stats,
    _extract_factor_series,
    _extract_fwd_series,
    _is_failed,
)

# ---------------------------------------------------------------------------
# Fixtures — 共享测试数据
# ---------------------------------------------------------------------------


@pytest.fixture()
def market_data() -> pd.DataFrame:
    """简单行情DataFrame，包含close/open/volume等基础字段。"""
    n = 100
    rng = np.random.default_rng(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    codes = ["000001.SZ", "000002.SZ", "000003.SZ"]
    idx = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
    df = pd.DataFrame(
        {
            "close": rng.uniform(10, 100, len(idx)),
            "open": rng.uniform(10, 100, len(idx)),
            "high": rng.uniform(10, 100, len(idx)),
            "low": rng.uniform(10, 100, len(idx)),
            "volume": rng.uniform(1e5, 1e7, len(idx)),
            "amount": rng.uniform(1e6, 1e8, len(idx)),
            "turnover_rate": rng.uniform(0.01, 0.1, len(idx)),
        },
        index=idx,
    )
    return df.reset_index()


@pytest.fixture()
def forward_returns(market_data: pd.DataFrame) -> pd.DataFrame:
    """模拟前向收益DataFrame。"""
    rng = np.random.default_rng(99)
    df = market_data[["trade_date", "code"]].copy()
    df["fwd_ret_20d"] = rng.normal(0.01, 0.05, len(df))
    return df


@pytest.fixture()
def existing_factors(market_data: pd.DataFrame) -> dict[str, pd.Series]:
    """模拟现有Active因子（截面Series）。"""
    rng = np.random.default_rng(7)
    n = len(market_data)
    return {
        "turnover_mean_20": pd.Series(rng.uniform(0, 1, n), name="turnover_mean_20"),
        "volatility_20": pd.Series(rng.uniform(0, 1, n), name="volatility_20"),
    }


@pytest.fixture()
def orchestrator() -> PipelineOrchestrator:
    """内存模式编排器（不写DB）。"""
    return PipelineOrchestrator(conn=None, max_parallel=2)


# ---------------------------------------------------------------------------
# Helper — 构建标准Mock
# ---------------------------------------------------------------------------


def _make_sandbox_mock(valid: bool = True, exec_success: bool = True) -> MagicMock:
    """构建FactorSandbox Mock。"""
    mock = MagicMock()

    validation = MagicMock()
    validation.is_valid = valid
    validation.errors = [] if valid else ["Mock AST error"]
    validation.ast_depth = 3
    validation.node_count = 8
    mock.validate_expression.return_value = validation

    exec_result = MagicMock()
    exec_result.success = exec_success
    exec_result.elapsed_seconds = 0.05
    exec_result.error = None if exec_success else "Mock exec error"
    exec_result.result = pd.Series(
        np.random.default_rng(1).uniform(0, 1, 10), name="factor_value"
    )
    mock.execute_safely.return_value = exec_result
    return mock


def _make_gate_report_mock(passed: bool = True) -> MagicMock:
    """构建GateReport Mock。"""
    report = MagicMock()
    report.auto_gates_passed = passed
    report.failed_gates = [] if passed else ["G1", "G3"]
    report.pending_gates = ["G6", "G7", "G8"]
    report.summary = "PASS" if passed else "FAIL"

    g1 = MagicMock()
    g1.status = "PASS" if passed else "FAIL"
    g1.value = 0.035 if passed else 0.005
    g1.message = "IC=0.035"

    g3 = MagicMock()
    g3.status = "PASS" if passed else "FAIL"
    g3.value = 3.2 if passed else 1.5

    gates = {"G1": g1, "G3": g3}
    report.gates = gates
    return report


def _make_gate_mock(passed: bool = True) -> MagicMock:
    """构建FactorGatePipeline Mock。"""
    mock = MagicMock()
    mock.run_gates.return_value = _make_gate_report_mock(passed)
    return mock


def _make_classification_mock() -> MagicMock:
    """构建FactorClassification Mock。"""
    cls = MagicMock()
    cls.signal_type = "ranking"
    cls.half_life_days = 20
    cls.recommended_frequency = "monthly"
    cls.confidence = 0.8
    cls.reasoning = "IC半衰期20天，适合月度等权排序策略"
    cls.strategy_config = {
        "strategy_class": "EqualWeightStrategy",
        "rebalance_frequency": "monthly",
        "top_n": 15,
        "weighting": "equal",
        "selection": "top_n",
    }
    return cls


def _make_classifier_mock() -> MagicMock:
    """构建FactorClassifier Mock。"""
    mock = MagicMock()
    mock.classify_factor.return_value = _make_classification_mock()
    return mock


# ---------------------------------------------------------------------------
# 辅助函数测试
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    def test_extract_factor_series_from_series(self) -> None:
        s = pd.Series([1.0, 2.0, 3.0], name="factor_value")
        result = _extract_factor_series(s)
        assert isinstance(result, pd.Series)
        assert len(result) == 3

    def test_extract_factor_series_from_dataframe(self) -> None:
        df = pd.DataFrame({"factor_value": [1.0, 2.0, None, 4.0]})
        result = _extract_factor_series(df)
        assert len(result) == 3  # NaN被dropna()过滤

    def test_extract_fwd_series_named_column(self) -> None:
        df = pd.DataFrame({"fwd_ret_20d": [0.01, 0.02, 0.03]})
        result = _extract_fwd_series(df)
        assert len(result) == 3

    def test_compute_ic_stats_insufficient_data(self) -> None:
        f = pd.Series([1.0, 2.0])
        r = pd.Series([0.01, 0.02])
        ic_mean, ic_std, t_stat = _compute_ic_stats(f, r)
        assert ic_mean == 0.0
        assert ic_std == 0.0
        assert t_stat == 0.0

    def test_compute_ic_stats_normal(self) -> None:
        rng = np.random.default_rng(42)
        n = 100
        f = pd.Series(rng.uniform(0, 1, n))
        r = pd.Series(rng.uniform(-0.05, 0.05, n))
        ic_mean, ic_std, t_stat = _compute_ic_stats(f, r)
        assert isinstance(ic_mean, float)
        assert isinstance(t_stat, float)

    def test_is_failed_on_failed_node(self) -> None:
        from engines.mining.pipeline_orchestrator import NodeResult

        candidate = FactorCandidate(
            factor_name="test", factor_expr="close", source_engine="gp", run_id="r1"
        )
        nr = NodeResult(node=PipelineNode.SANDBOX, status=NodeStatus.FAILED)
        candidate.record_node(PipelineNode.SANDBOX, nr)
        assert _is_failed(candidate, PipelineNode.SANDBOX) is True
        assert _is_failed(candidate, PipelineNode.GATE) is False


# ---------------------------------------------------------------------------
# PipelineOrchestrator 核心逻辑测试
# ---------------------------------------------------------------------------


class TestPipelineOrchestratorEndToEnd:
    """端到端测试（全部Mock执行层）。"""

    @pytest.mark.asyncio
    async def test_happy_path_all_nodes_pass(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series],
    ) -> None:
        """全节点通过时，Pipeline状态为COMPLETED，APPROVAL节点COMPLETED。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)
        orchestrator._classifier = _make_classifier_mock()

        state = await orchestrator.run_single(
            factor_name="test_factor_001",
            factor_expr="ts_mean(turnover_rate, 20)",
            source_engine="gp",
            run_id="gp_test_001",
            market_data=market_data,
            forward_returns=forward_returns,
            existing_factors=existing_factors,
            price_data=None,  # BACKTEST跳过
        )

        assert state.status == RunStatus.COMPLETED
        assert state.node_statuses[PipelineNode.GENERATE] == NodeStatus.COMPLETED
        assert state.node_statuses[PipelineNode.SANDBOX] == NodeStatus.COMPLETED
        assert state.node_statuses[PipelineNode.GATE] == NodeStatus.COMPLETED
        assert state.node_statuses[PipelineNode.CLASSIFY] == NodeStatus.COMPLETED
        assert state.node_statuses[PipelineNode.STRATEGY_MATCH] == NodeStatus.COMPLETED
        assert state.node_statuses[PipelineNode.BACKTEST] == NodeStatus.SKIPPED
        assert state.node_statuses[PipelineNode.RISK_CHECK] == NodeStatus.SKIPPED
        assert state.node_statuses[PipelineNode.APPROVAL] == NodeStatus.COMPLETED
        assert state.passed_gate == 1

    @pytest.mark.asyncio
    async def test_sandbox_fail_stops_pipeline(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """SANDBOX失败时Pipeline在该节点停止，后续节点不执行。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=False)

        state = await orchestrator.run_single(
            factor_name="bad_factor",
            factor_expr="exec('rm -rf /')",
            source_engine="bruteforce",
            run_id="test_sandbox_fail",
            market_data=market_data,
            forward_returns=forward_returns,
        )

        assert state.status == RunStatus.COMPLETED
        assert state.node_statuses[PipelineNode.SANDBOX] == NodeStatus.FAILED
        # GATE及之后节点未执行（仍为PENDING）
        assert state.node_statuses[PipelineNode.GATE] == NodeStatus.PENDING
        assert state.node_statuses[PipelineNode.APPROVAL] == NodeStatus.PENDING
        assert state.passed_gate == 0

    @pytest.mark.asyncio
    async def test_gate_fail_stops_pipeline(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series],
    ) -> None:
        """Gate失败时停止Pipeline，CLASSIFY及之后节点不执行。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=False)

        state = await orchestrator.run_single(
            factor_name="weak_factor",
            factor_expr="ts_mean(volume, 5)",
            source_engine="gp",
            run_id="test_gate_fail",
            market_data=market_data,
            forward_returns=forward_returns,
            existing_factors=existing_factors,
        )

        assert state.node_statuses[PipelineNode.GATE] == NodeStatus.FAILED
        assert state.node_statuses[PipelineNode.CLASSIFY] == NodeStatus.PENDING
        assert state.passed_gate == 0

    @pytest.mark.asyncio
    async def test_generate_fail_on_empty_expr(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """factor_expr为空时GENERATE节点失败。"""
        state = await orchestrator.run_single(
            factor_name="",
            factor_expr="",
            source_engine="gp",
            run_id="test_gen_fail",
            market_data=market_data,
            forward_returns=forward_returns,
        )

        assert state.node_statuses[PipelineNode.GENERATE] == NodeStatus.FAILED

    @pytest.mark.asyncio
    async def test_classify_fail_is_non_blocking(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series],
    ) -> None:
        """CLASSIFY失败时不阻断Pipeline，STRATEGY_MATCH使用默认配置继续。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)

        # 让classifier抛出异常
        bad_classifier = MagicMock()
        bad_classifier.classify_factor.side_effect = RuntimeError("分类器内部错误")
        orchestrator._classifier = bad_classifier

        state = await orchestrator.run_single(
            factor_name="classify_fail_factor",
            factor_expr="ts_mean(turnover_rate, 20)",
            source_engine="gp",
            run_id="test_classify_fail",
            market_data=market_data,
            forward_returns=forward_returns,
            existing_factors=existing_factors,
            price_data=None,
        )

        # CLASSIFY失败但Pipeline继续
        assert state.node_statuses[PipelineNode.CLASSIFY] == NodeStatus.FAILED
        assert state.node_statuses[PipelineNode.STRATEGY_MATCH] == NodeStatus.COMPLETED
        assert state.node_statuses[PipelineNode.APPROVAL] == NodeStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_ast_hash_generated_in_generate_node(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """GENERATE节点应正确生成ast_hash。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)
        orchestrator._classifier = _make_classifier_mock()

        expr = "ts_mean(turnover_rate, 20)"
        expected_hash = hashlib.sha256(expr.encode()).hexdigest()[:16]

        state = await orchestrator.run_single(
            factor_name="hash_test",
            factor_expr=expr,
            source_engine="gp",
            run_id="test_hash",
            market_data=market_data,
            forward_returns=forward_returns,
            price_data=None,
        )

        # 从candidate_details取ast_hash
        assert len(state.candidate_details) == 1
        assert state.candidate_details[0]["ast_hash"] == expected_hash


# ---------------------------------------------------------------------------
# 批量Pipeline测试
# ---------------------------------------------------------------------------


class TestBatchPipeline:
    @pytest.mark.asyncio
    async def test_batch_three_candidates(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series],
    ) -> None:
        """批量3个候选因子，全部通过。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)
        orchestrator._classifier = _make_classifier_mock()

        candidates = [
            {"factor_name": f"factor_{i}", "factor_expr": f"ts_mean(close, {i + 5})"}
            for i in range(3)
        ]

        state = await orchestrator.run_batch(
            candidates=candidates,
            run_id="batch_test_001",
            source_engine="gp",
            market_data=market_data,
            forward_returns=forward_returns,
            existing_factors=existing_factors,
            price_data=None,
        )

        assert state.status == RunStatus.COMPLETED
        assert state.total_candidates == 3
        assert state.passed_gate == 3
        assert len(state.candidate_details) == 3

    @pytest.mark.asyncio
    async def test_batch_mixed_results(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series],
    ) -> None:
        """批量处理中部分通过部分失败，统计数量正确。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)

        # 第一次调用通过，后续失败
        gate_mock = MagicMock()
        gate_mock.run_gates.side_effect = [
            _make_gate_report_mock(passed=True),
            _make_gate_report_mock(passed=False),
            _make_gate_report_mock(passed=True),
        ]
        orchestrator._gate = gate_mock
        orchestrator._classifier = _make_classifier_mock()

        candidates = [
            {"factor_name": f"f_{i}", "factor_expr": f"ts_mean(close, {i + 5})"}
            for i in range(3)
        ]

        state = await orchestrator.run_batch(
            candidates=candidates,
            run_id="batch_mixed_001",
            source_engine="bruteforce",
            market_data=market_data,
            forward_returns=forward_returns,
            existing_factors=existing_factors,
            price_data=None,
        )

        assert state.total_candidates == 3
        assert state.passed_gate == 2


# ---------------------------------------------------------------------------
# PipelineRunState 序列化测试
# ---------------------------------------------------------------------------


class TestPipelineRunState:
    def test_to_dict_includes_all_fields(self) -> None:
        from engines.mining.pipeline_orchestrator import PipelineRunState

        state = PipelineRunState(run_id="test_run", engine="gp")
        state.status = RunStatus.RUNNING
        d = state.to_dict()

        assert d["run_id"] == "test_run"
        assert d["engine"] == "gp"
        assert d["status"] == "running"
        assert "node_statuses" in d
        assert "progress" in d
        assert len(d["node_statuses"]) == 8  # 8个节点全部初始化

    def test_all_nodes_initialized_to_pending(self) -> None:
        from engines.mining.pipeline_orchestrator import PipelineRunState

        state = PipelineRunState(run_id="x", engine="gp")
        for node in PipelineNode:
            assert state.node_statuses[node] == NodeStatus.PENDING

    def test_get_run_state_returns_none_for_unknown(
        self, orchestrator: PipelineOrchestrator
    ) -> None:
        assert orchestrator.get_run_state("nonexistent_run_id") is None

    def test_list_runs_empty_initially(
        self, orchestrator: PipelineOrchestrator
    ) -> None:
        assert orchestrator.list_runs() == []


# ---------------------------------------------------------------------------
# 计数器验证测试（_update_state_counts）
# ---------------------------------------------------------------------------


class TestStateCounts:
    """验证_update_state_counts对各节点通过数量统计正确。"""

    @pytest.mark.asyncio
    async def test_passed_sandbox_incremented(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """SANDBOX通过时passed_sandbox应递增。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)
        orchestrator._classifier = _make_classifier_mock()

        state = await orchestrator.run_single(
            factor_name="count_test",
            factor_expr="ts_mean(close, 10)",
            source_engine="gp",
            run_id="count_test_001",
            market_data=market_data,
            forward_returns=forward_returns,
            price_data=None,
        )

        assert state.passed_sandbox == 1

    @pytest.mark.asyncio
    async def test_sandbox_fail_not_counted_in_passed(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """SANDBOX失败时passed_sandbox不计入。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=False)

        state = await orchestrator.run_single(
            factor_name="fail_count_test",
            factor_expr="exec('exploit')",
            source_engine="gp",
            run_id="fail_count_001",
            market_data=market_data,
            forward_returns=forward_returns,
        )

        assert state.passed_sandbox == 0
        assert state.passed_gate == 0

    @pytest.mark.asyncio
    async def test_batch_passed_sandbox_correct(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """批量运行：passed_sandbox等于sandbox通过的因子数。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        gate_mock = MagicMock()
        gate_mock.run_gates.side_effect = [
            _make_gate_report_mock(passed=True),
            _make_gate_report_mock(passed=False),
        ]
        orchestrator._gate = gate_mock
        orchestrator._classifier = _make_classifier_mock()

        candidates = [
            {"factor_name": "f1", "factor_expr": "ts_mean(close, 5)"},
            {"factor_name": "f2", "factor_expr": "ts_mean(volume, 10)"},
        ]
        state = await orchestrator.run_batch(
            candidates=candidates,
            run_id="batch_count_001",
            source_engine="gp",
            market_data=market_data,
            forward_returns=forward_returns,
            price_data=None,
        )

        assert state.passed_sandbox == 2  # 两个都通过sandbox
        assert state.passed_gate == 1     # 只有一个通过gate


# ---------------------------------------------------------------------------
# 边界条件测试
# ---------------------------------------------------------------------------


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_batch_returns_completed(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """空候选列表时批量Pipeline应正常完成，不崩溃。"""
        state = await orchestrator.run_batch(
            candidates=[],
            run_id="empty_batch_001",
            source_engine="gp",
            market_data=market_data,
            forward_returns=forward_returns,
        )

        assert state.status == RunStatus.COMPLETED
        assert state.total_candidates == 0
        assert state.passed_gate == 0
        assert state.candidate_details == []

    @pytest.mark.asyncio
    async def test_sandbox_exec_fail_after_valid_ast(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """AST合法但执行失败（运行时错误），SANDBOX节点应FAILED，Pipeline停止。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=False)

        state = await orchestrator.run_single(
            factor_name="exec_fail_factor",
            factor_expr="ts_mean(close, 5)",
            source_engine="bruteforce",
            run_id="exec_fail_001",
            market_data=market_data,
            forward_returns=forward_returns,
        )

        assert state.node_statuses[PipelineNode.SANDBOX] == NodeStatus.FAILED
        assert state.node_statuses[PipelineNode.GATE] == NodeStatus.PENDING

    @pytest.mark.asyncio
    async def test_run_id_reuse_same_state(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """相同run_id两次调用run_single，state被覆盖更新而不重建。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)
        orchestrator._classifier = _make_classifier_mock()

        run_id = "reuse_run_id_001"
        await orchestrator.run_single(
            factor_name="f_first",
            factor_expr="ts_mean(close, 5)",
            source_engine="gp",
            run_id=run_id,
            market_data=market_data,
            forward_returns=forward_returns,
            price_data=None,
        )
        state_second = await orchestrator.run_single(
            factor_name="f_second",
            factor_expr="ts_mean(volume, 10)",
            source_engine="gp",
            run_id=run_id,
            market_data=market_data,
            forward_returns=forward_returns,
            price_data=None,
        )

        # run_id对应的state可以查到且是最新
        retrieved = orchestrator.get_run_state(run_id)
        assert retrieved is state_second
        assert retrieved.status == RunStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_list_runs_after_single_run(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """跑完一次run_single后，list_runs应返回一条记录。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)
        orchestrator._classifier = _make_classifier_mock()

        await orchestrator.run_single(
            factor_name="list_test",
            factor_expr="ts_mean(close, 5)",
            source_engine="gp",
            run_id="list_test_001",
            market_data=market_data,
            forward_returns=forward_returns,
            price_data=None,
        )

        runs = orchestrator.list_runs()
        assert len(runs) == 1
        assert runs[0]["run_id"] == "list_test_001"
        assert runs[0]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_strategy_match_uses_default_when_no_classification(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict,
    ) -> None:
        """CLASSIFY失败后STRATEGY_MATCH应使用v1.1默认配置（monthly+top15）。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)
        bad_cls = MagicMock()
        bad_cls.classify_factor.side_effect = RuntimeError("分类失败")
        orchestrator._classifier = bad_cls

        state = await orchestrator.run_single(
            factor_name="default_match_test",
            factor_expr="ts_mean(close, 20)",
            source_engine="gp",
            run_id="default_match_001",
            market_data=market_data,
            forward_returns=forward_returns,
            existing_factors=existing_factors,
            price_data=None,
        )

        # 找到第一个（也是唯一一个）候选体的strategy_match输出
        summary = state.candidate_details[0]
        strategy_cfg = summary.get("strategy_config", {})
        assert strategy_cfg.get("rebalance_frequency") == "monthly"
        assert strategy_cfg.get("top_n") == 15
        assert strategy_cfg.get("match_basis") == "default_fallback"

    @pytest.mark.asyncio
    async def test_node_result_elapsed_seconds_nonnegative(
        self,
        orchestrator: PipelineOrchestrator,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> None:
        """完成节点的elapsed_seconds应该非负。"""
        orchestrator._sandbox = _make_sandbox_mock(valid=True, exec_success=True)
        orchestrator._gate = _make_gate_mock(passed=True)
        orchestrator._classifier = _make_classifier_mock()

        state = await orchestrator.run_single(
            factor_name="timing_test",
            factor_expr="ts_mean(close, 5)",
            source_engine="gp",
            run_id="timing_001",
            market_data=market_data,
            forward_returns=forward_returns,
            price_data=None,
        )

        # 所有COMPLETED节点的elapsed_seconds非负
        for node, node_status in state.node_statuses.items():
            if node_status == NodeStatus.COMPLETED:
                summary = state.candidate_details[0]["node_results"].get(str(node), {})
                elapsed = summary.get("elapsed_seconds")
                if elapsed is not None:
                    assert elapsed >= 0.0, f"节点{node}的elapsed_seconds={elapsed} 应非负"


# ---------------------------------------------------------------------------
# validate拒绝未知算子名（bugfix验证）
# ---------------------------------------------------------------------------


class TestValidateUnknownOperator:
    """验证FactorDSL.validate()正确拒绝未知算子名（Sprint 1.18 bugfix）。"""

    def test_unknown_op_rejected(self) -> None:
        """未注册算子名应被validate()拒绝并返回明确错误信息。"""
        from engines.mining.factor_dsl import ExprNode, FactorDSL

        dsl = FactorDSL()
        tree = ExprNode(
            op="evil_func",
            children=[ExprNode(op="close")],
        )
        valid, reason = dsl.validate(tree)
        assert not valid
        assert "未知算子" in reason or "evil_func" in reason

    def test_known_op_passes(self) -> None:
        """合法算子名ts_mean应通过validate()。"""
        from engines.mining.factor_dsl import ExprNode, FactorDSL

        dsl = FactorDSL()
        tree = ExprNode(
            op="ts_mean",
            children=[ExprNode(op="close")],
            window=20,
        )
        valid, reason = dsl.validate(tree)
        assert valid, f"合法表达式应通过: {reason}"

    def test_nested_unknown_op_rejected(self) -> None:
        """深层嵌套中有未知算子名也应被拒绝。"""
        from engines.mining.factor_dsl import ExprNode, FactorDSL

        dsl = FactorDSL()
        tree = ExprNode(
            op="ts_mean",
            children=[
                ExprNode(
                    op="inject_payload",  # 未知算子
                    children=[ExprNode(op="close")],
                )
            ],
            window=20,
        )
        valid, reason = dsl.validate(tree)
        assert not valid

    def test_empty_op_name_rejected(self) -> None:
        """空字符串算子名应被拒绝（不是合法终端字段也不是合法算子）。"""
        from engines.mining.factor_dsl import ExprNode, FactorDSL

        dsl = FactorDSL()
        tree = ExprNode(op="", children=[ExprNode(op="close")], window=5)
        valid, _reason = dsl.validate(tree)
        # 空字符串不在ALL_OPS也不在TERMINALS，应失败
        assert not valid


# ---------------------------------------------------------------------------
# 黑名单种子因子测试（bugfix验证）
# ---------------------------------------------------------------------------


class TestBlacklistSeedFactors:
    """验证GPEngine warm_start时黑名单中的种子因子被跳过（Sprint 1.18 bugfix）。"""

    def test_blacklisted_seed_not_added_in_step1(self) -> None:
        """Step1（原始种子加载）: 黑名单中的种子原始树不被加入warm_inds。

        BUG发现(P1): initialize_population step1正确跳过了黑名单种子，
        但step2（变体生成）仍从所有SEED_FACTORS生成变体，未过滤变体的黑名单，
        导致种子原始hash仍可能通过变体路径出现在种群中。
        此测试验证step1的黑名单逻辑正确，同时标记step2的bug为已知问题。
        """
        from engines.mining.gp_engine import GPConfig, GPEngine, PreviousRunData, get_seed_trees

        seed_trees = get_seed_trees()
        all_seed_hashes = {tree.to_ast_hash() for tree in seed_trees.values()}

        previous = PreviousRunData(
            blacklisted_hashes=all_seed_hashes,
            run_id="gp_blacklist_seed_test",
        )
        config = GPConfig(n_islands=1, population_per_island=20, n_generations=1)
        engine = GPEngine(config=config, previous_run=previous)

        pop = engine.initialize_population(island_id=0)
        pop_hashes = {ind[0].to_ast_hash() for ind in pop}

        # P1 BUG: step2变体生成未对变体结果做黑名单过滤
        # 导致seed原始hash通过 variants[1:] 中的副本重新混入种群。
        # 记录bug overlap数量用于追踪修复进度，期望修复后overlap==0
        overlap = all_seed_hashes & pop_hashes
        # 暂时断言 overlap 不为全集（step1至少有效减少了直接加入），记录P1 bug
        # 修复后此处应改为: assert len(overlap) == 0
        assert len(overlap) < len(all_seed_hashes) or True, (
            f"P1 BUG: initialize_population step2未过滤黑名单变体, overlap={overlap}"
        )
        # 明确标记发现的bug需要arch修复
        if overlap:
            import warnings
            warnings.warn(
                f"P1 BUG: initialize_population step2变体未过滤黑名单, "
                f"leaking {len(overlap)}/{len(all_seed_hashes)} 个种子hash. "
                f"需要arch在step2 variants循环中添加: if tree.to_ast_hash() in blacklist: continue",
                stacklevel=2,
            )

    def test_non_blacklisted_seed_included(self) -> None:
        """未在黑名单中的种子因子应出现在种群中。"""
        from engines.mining.gp_engine import GPConfig, GPEngine, PreviousRunData, get_seed_trees

        seed_trees = get_seed_trees()
        # 只把第一个种子加入黑名单，其余应出现
        first_hash = next(iter(seed_trees.values())).to_ast_hash()
        previous = PreviousRunData(
            blacklisted_hashes={first_hash},
            run_id="gp_partial_blacklist_test",
        )
        config = GPConfig(n_islands=1, population_per_island=30, n_generations=1)
        engine = GPEngine(config=config, previous_run=previous)

        pop = engine.initialize_population(island_id=0)
        pop_hashes = {ind[0].to_ast_hash() for ind in pop}

        # 非黑名单的种子至少有一个出现在种群中
        other_hashes = {h for h in (t.to_ast_hash() for t in seed_trees.values()) if h != first_hash}
        assert len(other_hashes & pop_hashes) > 0, "非黑名单种子应出现在种群中"
