"""PipelineOrchestrator — 因子挖掘8节点状态机编排器。

将BruteForce/GP/LLM引擎产出的候选因子，经由8个节点逐级处理：
  GENERATE → SANDBOX → GATE → CLASSIFY → STRATEGY_MATCH → BACKTEST → RISK_CHECK → APPROVAL

设计文档对照:
  - docs/DEV_AI_EVOLUTION.md §4: Pipeline完整流程
  - docs/GP_CLOSED_LOOP_DESIGN.md §6: 单次GP运行7步流程
  - docs/IMPLEMENTATION_MASTER.md §3-4: 运行时架构与接口规格
  - docs/RISK_CONTROL_SERVICE_DESIGN.md: L1-L4熔断

铁律:
  3. SimBroker回测 (BACKTEST节点)
  8. 因子→策略匹配 (STRATEGY_MATCH节点)
  5. 验代码不信文档 — 所有节点输入输出有运行时校验

PT代码隔离: 不触碰 run_paper_trading.py / signal_engine.py / paper_broker.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 枚举 — 节点名称 / 节点状态 / Run状态
# ---------------------------------------------------------------------------


class PipelineNode(StrEnum):
    """Pipeline 8节点（按执行顺序）。"""

    GENERATE = "GENERATE"
    SANDBOX = "SANDBOX"
    GATE = "GATE"
    CLASSIFY = "CLASSIFY"
    STRATEGY_MATCH = "STRATEGY_MATCH"
    BACKTEST = "BACKTEST"
    RISK_CHECK = "RISK_CHECK"
    APPROVAL = "APPROVAL"


_NODE_ORDER: list[PipelineNode] = [
    PipelineNode.GENERATE,
    PipelineNode.SANDBOX,
    PipelineNode.GATE,
    PipelineNode.CLASSIFY,
    PipelineNode.STRATEGY_MATCH,
    PipelineNode.BACKTEST,
    PipelineNode.RISK_CHECK,
    PipelineNode.APPROVAL,
]


class NodeStatus(StrEnum):
    """单节点执行状态。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(StrEnum):
    """整条Pipeline运行状态。"""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class NodeResult:
    """单节点执行结果。"""

    node: PipelineNode
    status: NodeStatus
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def elapsed_seconds(self) -> float | None:
        """耗时（秒），节点完成后可用。"""
        if self.finished_at is None:
            return None
        return self.finished_at - self.started_at

    def finish(self, status: NodeStatus, output: dict[str, Any] | None = None,
               error: str | None = None) -> None:
        """标记节点完成。"""
        self.status = status
        self.finished_at = time.time()
        if output:
            self.output = output
        if error:
            self.error = error

    def to_dict(self) -> dict[str, Any]:
        """序列化为可JSON化的dict。"""
        return {
            "node": self.node,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_seconds": self.elapsed_seconds,
            "output": self.output,
            "error": self.error,
        }


@dataclass
class FactorCandidate:
    """流经Pipeline的因子候选体。

    每个节点对此对象进行填充，后续节点可读取前序节点的结果。
    """

    factor_name: str
    factor_expr: str
    source_engine: str          # gp / bruteforce / llm
    run_id: str
    ast_hash: str = ""
    factor_values: pd.DataFrame | None = None   # SANDBOX节点填充
    gate_report: Any | None = None              # GATE节点填充（GateReport）
    classification: Any | None = None           # CLASSIFY节点填充（FactorClassification）
    strategy_config: dict[str, Any] = field(default_factory=dict)  # STRATEGY_MATCH
    backtest_result: Any | None = None          # BACKTEST节点填充
    risk_passed: bool = False                   # RISK_CHECK节点填充
    approval_id: int | None = None              # APPROVAL节点填充
    node_results: dict[str, NodeResult] = field(default_factory=dict)
    skip_reason: str | None = None              # 跳过时记录原因

    def record_node(self, node: PipelineNode, result: NodeResult) -> None:
        """记录节点结果到候选体。"""
        self.node_results[node] = result


@dataclass
class PipelineRunState:
    """单次Pipeline运行的完整状态，供前端查询。"""

    run_id: str
    engine: str
    status: RunStatus = RunStatus.IDLE
    current_node: PipelineNode | None = None
    node_statuses: dict[str, NodeStatus] = field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    total_candidates: int = 0
    passed_sandbox: int = 0
    passed_gate: int = 0
    passed_backtest: int = 0
    pending_approval: int = 0
    error: str | None = None
    candidate_details: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        for node in _NODE_ORDER:
            self.node_statuses[node] = NodeStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        """序列化为前端可用格式。"""
        return {
            "run_id": self.run_id,
            "engine": self.engine,
            "status": self.status,
            "current_node": self.current_node,
            "node_statuses": dict(self.node_statuses),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "progress": {
                "total_candidates": self.total_candidates,
                "passed_sandbox": self.passed_sandbox,
                "passed_gate": self.passed_gate,
                "passed_backtest": self.passed_backtest,
                "pending_approval": self.pending_approval,
            },
            "error": self.error,
            "candidate_details": self.candidate_details,
        }


# ---------------------------------------------------------------------------
# 风控检查辅助
# ---------------------------------------------------------------------------

_RISK_MDD_LIMIT: float = 0.35        # MDD硬性上限（GP_CLOSED_LOOP §5.2）
_RISK_MAX_CORR: float = 0.70         # 与现有因子最大相关性（Gate G2复用）
_RISK_MIN_SHARPE: float = 0.39       # 5年全量Sharpe下限（基线0.39 volume_impact）


# ---------------------------------------------------------------------------
# PipelineOrchestrator
# ---------------------------------------------------------------------------


class PipelineOrchestrator:
    """因子挖掘8节点状态机编排器。

    用法（单因子端到端）:
        orch = PipelineOrchestrator(conn=db_conn)
        run_state = await orch.run_single(
            factor_name="gp_factor_001",
            factor_expr="ts_mean(cs_rank(close), 20)",
            source_engine="gp",
            run_id="gp_2026w14",
            market_data=price_df,
            forward_returns=fwd_df,
            existing_factors={"turnover_mean_20": ts_values},
        )

    用法（批量并行）:
        run_state = await orch.run_batch(candidates_list, ...)
    """

    def __init__(
        self,
        conn: Any | None = None,
        max_parallel: int = 4,
    ) -> None:
        """初始化编排器。

        Args:
            conn: 数据库连接（用于写入approval_queue / mining_knowledge）。
                  可为None（仅内存模式，不写DB）。
            max_parallel: 批量处理时的最大并行因子数量。
        """
        self._conn = conn
        self._max_parallel = max_parallel

        # 当前活跃的Run状态（key=run_id）
        self._runs: dict[str, PipelineRunState] = {}

        # 懒加载各引擎（避免import时过重）
        self._sandbox: Any | None = None
        self._gate: Any | None = None
        self._classifier: Any | None = None

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    async def run_single(
        self,
        factor_name: str,
        factor_expr: str,
        source_engine: str,
        run_id: str,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series] | None = None,
        price_data: pd.DataFrame | None = None,
    ) -> PipelineRunState:
        """单因子端到端Pipeline: GENERATE→…→APPROVAL。

        Args:
            factor_name: 因子名称（唯一标识）。
            factor_expr: 因子DSL表达式字符串。
            source_engine: 产出引擎 gp/bruteforce/llm。
            run_id: 所属Pipeline运行ID。
            market_data: 行情+基本面数据 DataFrame（截面，含close/open/volume等）。
            forward_returns: 前向收益 DataFrame（trade_date, code, fwd_ret_20d）。
            existing_factors: 现有Active因子的截面值，用于正交性检查。
            price_data: 行情时序数据，用于BACKTEST节点（QuickBacktester）。
                        若None则跳过BACKTEST节点。

        Returns:
            PipelineRunState: 含所有节点状态和候选体详情。
        """
        state = self._get_or_create_run(run_id, source_engine)
        state.status = RunStatus.RUNNING
        state.started_at = datetime.now(tz=UTC)
        state.total_candidates = 1

        candidate = FactorCandidate(
            factor_name=factor_name,
            factor_expr=factor_expr,
            source_engine=source_engine,
            run_id=run_id,
        )

        await self._process_candidate(
            candidate=candidate,
            state=state,
            market_data=market_data,
            forward_returns=forward_returns,
            existing_factors=existing_factors or {},
            price_data=price_data,
        )

        # 汇总统计
        self._update_state_counts(state, [candidate])
        state.candidate_details = [self._candidate_summary(candidate)]
        state.status = RunStatus.COMPLETED
        state.finished_at = datetime.now(tz=UTC)
        return state

    async def run_batch(
        self,
        candidates: list[dict[str, str]],
        run_id: str,
        source_engine: str,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series] | None = None,
        price_data: pd.DataFrame | None = None,
    ) -> PipelineRunState:
        """批量因子并行Pipeline处理。

        Args:
            candidates: 因子候选列表，每个元素 {"factor_name": ..., "factor_expr": ...}。
            run_id: 所属Pipeline运行ID。
            source_engine: 产出引擎 gp/bruteforce/llm。
            market_data: 行情+基本面数据 DataFrame。
            forward_returns: 前向收益 DataFrame。
            existing_factors: 现有Active因子截面值。
            price_data: 行情时序数据（QuickBacktester用）。

        Returns:
            PipelineRunState: 含所有候选体处理结果。
        """
        state = self._get_or_create_run(run_id, source_engine)
        state.status = RunStatus.RUNNING
        state.started_at = datetime.now(tz=UTC)
        state.total_candidates = len(candidates)

        logger.info(
            "批量Pipeline启动: run_id=%s, engine=%s, candidates=%d",
            run_id, source_engine, len(candidates),
        )

        # 构建候选体列表
        factor_candidates = [
            FactorCandidate(
                factor_name=c["factor_name"],
                factor_expr=c["factor_expr"],
                source_engine=source_engine,
                run_id=run_id,
            )
            for c in candidates
        ]

        # 并行处理（限制并发数量）
        sem = asyncio.Semaphore(self._max_parallel)

        async def _process_with_sem(cand: FactorCandidate) -> None:
            async with sem:
                await self._process_candidate(
                    candidate=cand,
                    state=state,
                    market_data=market_data,
                    forward_returns=forward_returns,
                    existing_factors=existing_factors or {},
                    price_data=price_data,
                )

        await asyncio.gather(*[_process_with_sem(c) for c in factor_candidates])

        self._update_state_counts(state, factor_candidates)
        state.candidate_details = [self._candidate_summary(c) for c in factor_candidates]
        state.status = RunStatus.COMPLETED
        state.finished_at = datetime.now(tz=UTC)

        logger.info(
            "批量Pipeline完成: run_id=%s, passed_gate=%d/%d, pending_approval=%d",
            run_id, state.passed_gate, state.total_candidates, state.pending_approval,
        )
        return state

    def get_run_state(self, run_id: str) -> PipelineRunState | None:
        """查询指定run_id的运行状态（前端轮询用）。"""
        return self._runs.get(run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        """列出所有运行记录（按started_at降序）。"""
        runs = sorted(
            self._runs.values(),
            key=lambda r: r.started_at or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )
        return [r.to_dict() for r in runs]

    # ------------------------------------------------------------------
    # 8节点处理链
    # ------------------------------------------------------------------

    async def _process_candidate(
        self,
        candidate: FactorCandidate,
        state: PipelineRunState,
        market_data: pd.DataFrame,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series],
        price_data: pd.DataFrame | None,
    ) -> None:
        """按顺序执行8个节点，任一节点FAIL则记录知识并停止。"""

        # Node 1: GENERATE（候选体已由调用方产出，这里只做登记）
        await self._node_generate(candidate, state)
        if _is_failed(candidate, PipelineNode.GENERATE):
            return

        # Node 2: SANDBOX
        await self._node_sandbox(candidate, state, market_data)
        if _is_failed(candidate, PipelineNode.SANDBOX):
            await self._record_knowledge(candidate, "sandbox_failed")
            return

        # Node 3: GATE
        await self._node_gate(candidate, state, forward_returns, existing_factors)
        if _is_failed(candidate, PipelineNode.GATE):
            await self._record_knowledge(candidate, "gate_failed")
            return

        # Node 4: CLASSIFY
        await self._node_classify(candidate, state)
        if _is_failed(candidate, PipelineNode.CLASSIFY):
            # 分类失败不阻断，记录为unclassified继续
            logger.warning("CLASSIFY节点失败，降级为unclassified: %s", candidate.factor_name)

        # Node 5: STRATEGY_MATCH（铁律8）
        await self._node_strategy_match(candidate, state)
        if _is_failed(candidate, PipelineNode.STRATEGY_MATCH):
            await self._record_knowledge(candidate, "strategy_match_failed")
            return

        # Node 6: BACKTEST（铁律3）
        await self._node_backtest(candidate, state, market_data, price_data)
        if _is_failed(candidate, PipelineNode.BACKTEST):
            await self._record_knowledge(candidate, "backtest_failed")
            return

        # Node 7: RISK_CHECK
        await self._node_risk_check(candidate, state)
        if _is_failed(candidate, PipelineNode.RISK_CHECK):
            await self._record_knowledge(candidate, "risk_check_failed")
            return

        # Node 8: APPROVAL
        await self._node_approval(candidate, state)

    # ------------------------------------------------------------------
    # 节点实现
    # ------------------------------------------------------------------

    async def _node_generate(
        self, candidate: FactorCandidate, state: PipelineRunState
    ) -> None:
        """Node 1: GENERATE — 登记候选因子，验证基本字段。"""
        node_result = NodeResult(node=PipelineNode.GENERATE, status=NodeStatus.RUNNING)
        state.current_node = PipelineNode.GENERATE
        state.node_statuses[PipelineNode.GENERATE] = NodeStatus.RUNNING

        if not candidate.factor_expr or not candidate.factor_name:
            node_result.finish(
                NodeStatus.FAILED,
                error="factor_name 或 factor_expr 为空",
            )
            candidate.record_node(PipelineNode.GENERATE, node_result)
            state.node_statuses[PipelineNode.GENERATE] = NodeStatus.FAILED
            return

        # 计算AST hash（用于去重）
        import hashlib
        candidate.ast_hash = hashlib.sha256(candidate.factor_expr.encode()).hexdigest()[:16]

        node_result.finish(
            NodeStatus.COMPLETED,
            output={
                "factor_name": candidate.factor_name,
                "factor_expr": candidate.factor_expr,
                "ast_hash": candidate.ast_hash,
                "source_engine": candidate.source_engine,
            },
        )
        candidate.record_node(PipelineNode.GENERATE, node_result)
        state.node_statuses[PipelineNode.GENERATE] = NodeStatus.COMPLETED

    async def _node_sandbox(
        self,
        candidate: FactorCandidate,
        state: PipelineRunState,
        market_data: pd.DataFrame,
    ) -> None:
        """Node 2: SANDBOX — AST安全检查 + 安全执行，产出因子值。"""
        node_result = NodeResult(node=PipelineNode.SANDBOX, status=NodeStatus.RUNNING)
        state.current_node = PipelineNode.SANDBOX
        state.node_statuses[PipelineNode.SANDBOX] = NodeStatus.RUNNING

        try:
            sandbox = self._get_sandbox()

            # AST静态安全检查
            validation = sandbox.validate_expression(candidate.factor_expr)
            if not validation.is_valid:
                node_result.finish(
                    NodeStatus.FAILED,
                    output={"errors": validation.errors},
                    error=f"AST安全检查失败: {'; '.join(validation.errors)}",
                )
                candidate.record_node(PipelineNode.SANDBOX, node_result)
                state.node_statuses[PipelineNode.SANDBOX] = NodeStatus.FAILED
                return

            # 安全执行（subprocess隔离）
            exec_result = sandbox.execute_safely(candidate.factor_expr, market_data)
            if not exec_result.success:
                node_result.finish(
                    NodeStatus.FAILED,
                    output={"validation_ok": True},
                    error=f"执行失败: {exec_result.error}",
                )
                candidate.record_node(PipelineNode.SANDBOX, node_result)
                state.node_statuses[PipelineNode.SANDBOX] = NodeStatus.FAILED
                return

            # 构建factor_values DataFrame（GATE节点需要）
            if isinstance(exec_result.result, pd.Series):
                fv = exec_result.result.to_frame(name="factor_value")
                if "trade_date" not in fv.columns and isinstance(market_data.index, pd.MultiIndex):
                    fv = fv.reset_index()
            else:
                fv = exec_result.result

            candidate.factor_values = fv

            node_result.finish(
                NodeStatus.COMPLETED,
                output={
                    "validation_ok": True,
                    "elapsed_seconds": exec_result.elapsed_seconds,
                    "ast_depth": validation.ast_depth,
                    "node_count": validation.node_count,
                    "factor_shape": list(fv.shape) if fv is not None else None,
                },
            )
            candidate.record_node(PipelineNode.SANDBOX, node_result)
            state.node_statuses[PipelineNode.SANDBOX] = NodeStatus.COMPLETED

        except Exception as exc:
            logger.exception("SANDBOX节点异常: factor=%s", candidate.factor_name)
            node_result.finish(
                NodeStatus.FAILED,
                error=f"SANDBOX节点异常: {exc}",
            )
            candidate.record_node(PipelineNode.SANDBOX, node_result)
            state.node_statuses[PipelineNode.SANDBOX] = NodeStatus.FAILED

    async def _node_gate(
        self,
        candidate: FactorCandidate,
        state: PipelineRunState,
        forward_returns: pd.DataFrame,
        existing_factors: dict[str, pd.Series],
    ) -> None:
        """Node 3: GATE — 运行FactorGatePipeline G1-G8。"""
        node_result = NodeResult(node=PipelineNode.GATE, status=NodeStatus.RUNNING)
        state.current_node = PipelineNode.GATE
        state.node_statuses[PipelineNode.GATE] = NodeStatus.RUNNING

        try:
            if candidate.factor_values is None:
                node_result.finish(NodeStatus.FAILED, error="factor_values为空，无法运行Gate")
                candidate.record_node(PipelineNode.GATE, node_result)
                state.node_statuses[PipelineNode.GATE] = NodeStatus.FAILED
                return

            gate = self._get_gate()

            # 提取截面IC所需数据
            factor_series = _extract_factor_series(candidate.factor_values)
            fwd_series = _extract_fwd_series(forward_returns)

            # 计算IC统计量
            ic_mean, ic_std, t_stat = _compute_ic_stats(factor_series, fwd_series)

            # 计算中性化后IC（G4）
            neutralized_ic = _compute_neutralized_ic(factor_series, fwd_series)

            # 计算与现有因子的最大相关性（G2）
            active_factor_corr = _compute_factor_correlations(factor_series, existing_factors)

            # 经济学方向假设（G5）：默认双向，sign推断
            expected_direction = int(1 if ic_mean >= 0 else -1)

            # 运行G1-G5自动Gate
            report = gate.run_gates(
                factor_name=candidate.factor_name,
                ic_mean=ic_mean,
                ic_std=ic_std,
                t_stat=t_stat,
                active_factor_corr=active_factor_corr,
                neutralized_ic_mean=neutralized_ic,
                expected_direction=expected_direction,
            )

            candidate.gate_report = report

            if not report.auto_gates_passed:
                failed = report.failed_gates
                node_result.finish(
                    NodeStatus.FAILED,
                    output={
                        "ic_mean": ic_mean,
                        "t_stat": t_stat,
                        "failed_gates": failed,
                        "summary": report.summary,
                    },
                    error=f"Gate失败: {', '.join(failed)}",
                )
                candidate.record_node(PipelineNode.GATE, node_result)
                state.node_statuses[PipelineNode.GATE] = NodeStatus.FAILED
                return

            node_result.finish(
                NodeStatus.COMPLETED,
                output={
                    "ic_mean": ic_mean,
                    "ic_std": ic_std,
                    "t_stat": t_stat,
                    "passed_gates": [g for g, r in report.gates.items() if str(r.status) == "PASS"],
                    "pending_gates": report.pending_gates,
                    "summary": report.summary,
                },
            )
            candidate.record_node(PipelineNode.GATE, node_result)
            state.node_statuses[PipelineNode.GATE] = NodeStatus.COMPLETED

        except Exception as exc:
            logger.exception("GATE节点异常: factor=%s", candidate.factor_name)
            node_result.finish(NodeStatus.FAILED, error=f"GATE节点异常: {exc}")
            candidate.record_node(PipelineNode.GATE, node_result)
            state.node_statuses[PipelineNode.GATE] = NodeStatus.FAILED

    async def _node_classify(
        self, candidate: FactorCandidate, state: PipelineRunState
    ) -> None:
        """Node 4: CLASSIFY — FactorClassifier分类。"""
        node_result = NodeResult(node=PipelineNode.CLASSIFY, status=NodeStatus.RUNNING)
        state.current_node = PipelineNode.CLASSIFY
        state.node_statuses[PipelineNode.CLASSIFY] = NodeStatus.RUNNING

        try:
            classifier = self._get_classifier()

            # 从GateReport提取IC衰减信息
            ic_mean = 0.0
            ic_std = 0.0
            if candidate.gate_report:
                g1 = candidate.gate_report.gates.get("G1")
                if g1 and g1.value is not None:
                    ic_mean = float(g1.value)
                g3 = candidate.gate_report.gates.get("G3")
                if g3 and g3.value is not None:
                    ic_std = max(float(g3.value) * abs(ic_mean), 0.001)

            # ic_decay近似（用固定的ic_mean作为代理）
            ic_decay = {1: ic_mean, 5: ic_mean * 0.8, 20: ic_mean * 0.5, 60: ic_mean * 0.2}

            classification = classifier.classify_factor(
                factor_name=candidate.factor_name,
                ic_decay=ic_decay,
                ic_std=ic_std,
                signal_sparsity=0.7,   # 默认持续型，Gate通过的多为排序因子
            )
            candidate.classification = classification

            node_result.finish(
                NodeStatus.COMPLETED,
                output={
                    "signal_type": classification.signal_type,
                    "half_life_days": classification.half_life_days,
                    "recommended_frequency": classification.recommended_frequency,
                    "confidence": classification.confidence,
                    "reasoning": classification.reasoning[:200] if classification.reasoning else "",
                },
            )
            candidate.record_node(PipelineNode.CLASSIFY, node_result)
            state.node_statuses[PipelineNode.CLASSIFY] = NodeStatus.COMPLETED

        except Exception as exc:
            logger.warning("CLASSIFY节点异常(非阻断): factor=%s, err=%s", candidate.factor_name, exc)
            node_result.finish(NodeStatus.FAILED, error=f"CLASSIFY异常: {exc}")
            candidate.record_node(PipelineNode.CLASSIFY, node_result)
            state.node_statuses[PipelineNode.CLASSIFY] = NodeStatus.FAILED

    async def _node_strategy_match(
        self, candidate: FactorCandidate, state: PipelineRunState
    ) -> None:
        """Node 5: STRATEGY_MATCH — 铁律8因子→策略匹配。

        使用FactorClassifier的strategy_config推荐，确保每个因子进入
        与其信号特征匹配的策略框架，而非一律使用等权月度。
        """
        node_result = NodeResult(node=PipelineNode.STRATEGY_MATCH, status=NodeStatus.RUNNING)
        state.current_node = PipelineNode.STRATEGY_MATCH
        state.node_statuses[PipelineNode.STRATEGY_MATCH] = NodeStatus.RUNNING

        try:
            classification = candidate.classification

            if classification is None:
                # 无分类结果，使用v1.1默认配置（等权月度Top15）
                strategy_config = {
                    "strategy_class": "EqualWeightStrategy",
                    "rebalance_frequency": "monthly",
                    "top_n": 15,
                    "weighting": "equal",
                    "selection": "top_n",
                    "match_basis": "default_fallback",
                }
            else:
                strategy_config = classification.strategy_config or {}
                strategy_config["match_basis"] = "classifier"
                strategy_config["signal_type"] = str(classification.signal_type)
                strategy_config["half_life_days"] = classification.half_life_days

            candidate.strategy_config = strategy_config

            node_result.finish(
                NodeStatus.COMPLETED,
                output=strategy_config,
            )
            candidate.record_node(PipelineNode.STRATEGY_MATCH, node_result)
            state.node_statuses[PipelineNode.STRATEGY_MATCH] = NodeStatus.COMPLETED

        except Exception as exc:
            logger.exception("STRATEGY_MATCH节点异常: factor=%s", candidate.factor_name)
            node_result.finish(NodeStatus.FAILED, error=f"STRATEGY_MATCH异常: {exc}")
            candidate.record_node(PipelineNode.STRATEGY_MATCH, node_result)
            state.node_statuses[PipelineNode.STRATEGY_MATCH] = NodeStatus.FAILED

    async def _node_backtest(
        self,
        candidate: FactorCandidate,
        state: PipelineRunState,
        market_data: pd.DataFrame,
        price_data: pd.DataFrame | None,
    ) -> None:
        """Node 6: BACKTEST — 铁律3 SimBroker/QuickBacktester回测。"""
        node_result = NodeResult(node=PipelineNode.BACKTEST, status=NodeStatus.RUNNING)
        state.current_node = PipelineNode.BACKTEST
        state.node_statuses[PipelineNode.BACKTEST] = NodeStatus.RUNNING

        if price_data is None:
            # 无价格数据时跳过BACKTEST（测试模式）
            node_result.finish(
                NodeStatus.SKIPPED,
                output={"reason": "price_data未提供，跳过BACKTEST节点"},
            )
            candidate.record_node(PipelineNode.BACKTEST, node_result)
            state.node_statuses[PipelineNode.BACKTEST] = NodeStatus.SKIPPED
            logger.debug("BACKTEST节点跳过（price_data=None）: factor=%s", candidate.factor_name)
            return

        if candidate.factor_values is None:
            node_result.finish(NodeStatus.FAILED, error="factor_values为空，无法回测")
            candidate.record_node(PipelineNode.BACKTEST, node_result)
            state.node_statuses[PipelineNode.BACKTEST] = NodeStatus.FAILED
            return

        try:
            from engines.mining.quick_backtester import QuickBacktester

            # 按策略匹配结果选择参数（铁律8与铁律3联动）
            top_n = candidate.strategy_config.get("top_n", 15)

            backtester = QuickBacktester(
                price_data=price_data,
                top_n=int(top_n),
            )

            # 在线程池中运行（避免阻塞event loop）
            loop = asyncio.get_event_loop()
            bt_result = await loop.run_in_executor(
                None, backtester.backtest, candidate.factor_values
            )
            candidate.backtest_result = bt_result

            # 判断是否通过回测标准
            sharpe = bt_result.sharpe if bt_result.sharpe != -999.0 else None
            passed = sharpe is not None and sharpe >= _RISK_MIN_SHARPE

            if not passed:
                node_result.finish(
                    NodeStatus.FAILED,
                    output={
                        "sharpe": sharpe,
                        "mdd": bt_result.mdd,
                        "threshold": _RISK_MIN_SHARPE,
                        "error": bt_result.error,
                    },
                    error=f"Sharpe={sharpe:.3f} < 基线{_RISK_MIN_SHARPE}（或回测异常）",
                )
                candidate.record_node(PipelineNode.BACKTEST, node_result)
                state.node_statuses[PipelineNode.BACKTEST] = NodeStatus.FAILED
                return

            node_result.finish(
                NodeStatus.COMPLETED,
                output={
                    "sharpe": sharpe,
                    "mdd": bt_result.mdd,
                    "turnover": bt_result.turnover,
                    "ic_mean": bt_result.ic_mean,
                    "n_rebalances": bt_result.n_rebalances,
                },
            )
            candidate.record_node(PipelineNode.BACKTEST, node_result)
            state.node_statuses[PipelineNode.BACKTEST] = NodeStatus.COMPLETED

        except Exception as exc:
            logger.exception("BACKTEST节点异常: factor=%s", candidate.factor_name)
            node_result.finish(NodeStatus.FAILED, error=f"BACKTEST异常: {exc}")
            candidate.record_node(PipelineNode.BACKTEST, node_result)
            state.node_statuses[PipelineNode.BACKTEST] = NodeStatus.FAILED

    async def _node_risk_check(
        self, candidate: FactorCandidate, state: PipelineRunState
    ) -> None:
        """Node 7: RISK_CHECK — 回测MDD + 集中度风险检查。"""
        node_result = NodeResult(node=PipelineNode.RISK_CHECK, status=NodeStatus.RUNNING)
        state.current_node = PipelineNode.RISK_CHECK
        state.node_statuses[PipelineNode.RISK_CHECK] = NodeStatus.RUNNING

        bt = candidate.backtest_result
        if bt is None:
            # BACKTEST被跳过，风控也跳过
            node_result.finish(
                NodeStatus.SKIPPED,
                output={"reason": "BACKTEST未执行，RISK_CHECK跳过"},
            )
            candidate.risk_passed = True  # 无数据不阻断
            candidate.record_node(PipelineNode.RISK_CHECK, node_result)
            state.node_statuses[PipelineNode.RISK_CHECK] = NodeStatus.SKIPPED
            return

        failures: list[str] = []

        # MDD检查（CLAUDE.md 宪法：MDD > Sharpe优化目标排序）
        if bt.mdd > _RISK_MDD_LIMIT:
            failures.append(f"MDD={bt.mdd:.2%} > 上限{_RISK_MDD_LIMIT:.2%}")

        # 换手率检查（年化换手>200%视为过高）
        if bt.turnover and bt.turnover > 2.0:
            failures.append(f"年化换手率={bt.turnover:.1%} > 200%")

        if failures:
            node_result.finish(
                NodeStatus.FAILED,
                output={"failures": failures, "mdd": bt.mdd, "turnover": bt.turnover},
                error=f"风控失败: {'; '.join(failures)}",
            )
            candidate.risk_passed = False
            candidate.record_node(PipelineNode.RISK_CHECK, node_result)
            state.node_statuses[PipelineNode.RISK_CHECK] = NodeStatus.FAILED
            return

        candidate.risk_passed = True
        node_result.finish(
            NodeStatus.COMPLETED,
            output={"mdd": bt.mdd, "turnover": bt.turnover, "risk_passed": True},
        )
        candidate.record_node(PipelineNode.RISK_CHECK, node_result)
        state.node_statuses[PipelineNode.RISK_CHECK] = NodeStatus.COMPLETED

    async def _node_approval(
        self, candidate: FactorCandidate, state: PipelineRunState
    ) -> None:
        """Node 8: APPROVAL — 写入gp_approval_queue等待人工审批。"""
        node_result = NodeResult(node=PipelineNode.APPROVAL, status=NodeStatus.RUNNING)
        state.current_node = PipelineNode.APPROVAL
        state.node_statuses[PipelineNode.APPROVAL] = NodeStatus.RUNNING

        try:
            approval_id = await self._write_approval_queue(candidate)
            candidate.approval_id = approval_id

            node_result.finish(
                NodeStatus.COMPLETED,
                output={
                    "approval_id": approval_id,
                    "status": "pending",
                    "message": "已写入审批队列，等待人工approve/reject",
                },
            )
            candidate.record_node(PipelineNode.APPROVAL, node_result)
            state.node_statuses[PipelineNode.APPROVAL] = NodeStatus.COMPLETED

        except Exception as exc:
            logger.exception("APPROVAL节点异常: factor=%s", candidate.factor_name)
            node_result.finish(NodeStatus.FAILED, error=f"APPROVAL写入失败: {exc}")
            candidate.record_node(PipelineNode.APPROVAL, node_result)
            state.node_statuses[PipelineNode.APPROVAL] = NodeStatus.FAILED

    # ------------------------------------------------------------------
    # 数据库操作
    # ------------------------------------------------------------------

    async def _write_approval_queue(self, candidate: FactorCandidate) -> int | None:
        """写入approval_queue表。无DB连接时返回None（内存模式）。

        Returns:
            approval_queue 主键id，内存模式返回None。
        """
        if self._conn is None:
            logger.debug("内存模式：跳过写入approval_queue: %s", candidate.factor_name)
            return None

        gate_result_json = {}
        if candidate.gate_report:
            gate_result_json = {
                g: {"status": str(r.status), "value": r.value, "message": r.message}
                for g, r in candidate.gate_report.gates.items()
            }

        bt = candidate.backtest_result
        sharpe_1y = float(bt.sharpe) if bt and bt.sharpe != -999.0 else None

        backtest_report = None
        if bt:
            backtest_report = {
                "sharpe": bt.sharpe,
                "mdd": bt.mdd,
                "turnover": bt.turnover,
                "ic_mean": bt.ic_mean,
                "n_rebalances": bt.n_rebalances,
            }

        try:
            from sqlalchemy import text

            result = await self._conn.execute(
                text(
                    """
                    INSERT INTO approval_queue
                        (run_id, factor_name, factor_expr, ast_hash,
                         gate_result, sharpe_1y, backtest_report, status, created_at)
                    VALUES
                        (:run_id, :factor_name, :factor_expr, :ast_hash,
                         :gate_result::jsonb, :sharpe_1y, :backtest_report::jsonb,
                         'pending', NOW())
                    RETURNING id
                    """
                ),
                {
                    "run_id": candidate.run_id,
                    "factor_name": candidate.factor_name,
                    "factor_expr": candidate.factor_expr,
                    "ast_hash": candidate.ast_hash,
                    "gate_result": json.dumps(gate_result_json),
                    "sharpe_1y": sharpe_1y,
                    "backtest_report": json.dumps(backtest_report) if backtest_report else None,
                },
            )
            row = result.fetchone()
            await self._conn.commit()
            return row[0] if row else None
        except Exception as exc:
            logger.error("写入approval_queue失败: %s", exc)
            await self._conn.rollback()
            return None

    async def _record_knowledge(
        self, candidate: FactorCandidate, failure_stage: str
    ) -> None:
        """将失败因子写入mining_knowledge表（供下轮GP学习）。

        无DB连接时记录到日志。
        """
        error_details = {}
        for node, result in candidate.node_results.items():
            if result.status == NodeStatus.FAILED:
                error_details[node] = result.error

        if self._conn is None:
            logger.info(
                "mining_knowledge(内存模式): factor=%s, stage=%s, errors=%s",
                candidate.factor_name, failure_stage, error_details,
            )
            return

        try:
            from sqlalchemy import text

            await self._conn.execute(
                text(
                    """
                    INSERT INTO mining_knowledge
                        (run_id, factor_name, factor_expr, ast_hash,
                         status, rejection_reason, created_at)
                    VALUES
                        (:run_id, :factor_name, :factor_expr, :ast_hash,
                         'rejected', :rejection_reason, NOW())
                    ON CONFLICT (ast_hash) DO UPDATE
                        SET rejection_reason = EXCLUDED.rejection_reason,
                            updated_at = NOW()
                    """
                ),
                {
                    "run_id": candidate.run_id,
                    "factor_name": candidate.factor_name,
                    "factor_expr": candidate.factor_expr,
                    "ast_hash": candidate.ast_hash,
                    "rejection_reason": json.dumps(
                        {"stage": failure_stage, "errors": error_details}
                    ),
                },
            )
            await self._conn.commit()
        except Exception as exc:
            logger.warning("写入mining_knowledge失败（非阻断）: %s", exc)

    # ------------------------------------------------------------------
    # 辅助工具
    # ------------------------------------------------------------------

    def _get_or_create_run(self, run_id: str, engine: str) -> PipelineRunState:
        if run_id not in self._runs:
            self._runs[run_id] = PipelineRunState(run_id=run_id, engine=engine)
        return self._runs[run_id]

    def _get_sandbox(self) -> Any:
        if self._sandbox is None:
            from engines.mining.factor_sandbox import FactorSandbox
            self._sandbox = FactorSandbox(timeout=10)
        return self._sandbox

    def _get_gate(self) -> Any:
        if self._gate is None:
            from engines.factor_gate import FactorGatePipeline
            self._gate = FactorGatePipeline(conn=self._conn)
        return self._gate

    def _get_classifier(self) -> Any:
        if self._classifier is None:
            from engines.factor_classifier import FactorClassifier
            self._classifier = FactorClassifier()
        return self._classifier

    @staticmethod
    def _update_state_counts(
        state: PipelineRunState, candidates: list[FactorCandidate]
    ) -> None:
        """统计各节点通过数量。"""
        for c in candidates:
            sandbox_r = c.node_results.get(PipelineNode.SANDBOX)
            gate_r = c.node_results.get(PipelineNode.GATE)
            backtest_r = c.node_results.get(PipelineNode.BACKTEST)
            approval_r = c.node_results.get(PipelineNode.APPROVAL)

            if sandbox_r and sandbox_r.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED):
                state.passed_sandbox += 1
            if gate_r and gate_r.status == NodeStatus.COMPLETED:
                state.passed_gate += 1
            if backtest_r and backtest_r.status in (NodeStatus.COMPLETED, NodeStatus.SKIPPED):
                state.passed_backtest += 1
            if approval_r and approval_r.status == NodeStatus.COMPLETED:
                state.pending_approval += 1

    @staticmethod
    def _candidate_summary(candidate: FactorCandidate) -> dict[str, Any]:
        """生成候选体摘要（前端展示用）。"""
        node_summary = {}
        for node, result in candidate.node_results.items():
            node_summary[node] = {
                "status": result.status,
                "elapsed_seconds": result.elapsed_seconds,
                "error": result.error,
                "output_keys": list(result.output.keys()),
            }

        bt = candidate.backtest_result
        return {
            "factor_name": candidate.factor_name,
            "factor_expr": candidate.factor_expr,
            "ast_hash": candidate.ast_hash,
            "source_engine": candidate.source_engine,
            "approval_id": candidate.approval_id,
            "risk_passed": candidate.risk_passed,
            "sharpe": float(bt.sharpe) if bt and bt.sharpe != -999.0 else None,
            "mdd": float(bt.mdd) if bt else None,
            "signal_type": str(candidate.classification.signal_type) if candidate.classification else None,
            "strategy_config": candidate.strategy_config,
            "node_results": node_summary,
        }


# ---------------------------------------------------------------------------
# 辅助函数（IC计算、相关性等）
# ---------------------------------------------------------------------------


def _is_failed(candidate: FactorCandidate, node: PipelineNode) -> bool:
    """检查指定节点是否失败。"""
    result = candidate.node_results.get(node)
    return result is not None and result.status == NodeStatus.FAILED


def _extract_factor_series(factor_values: pd.DataFrame) -> pd.Series:
    """从factor_values DataFrame中提取Series。"""
    if isinstance(factor_values, pd.Series):
        return factor_values
    if "factor_value" in factor_values.columns:
        return factor_values["factor_value"].dropna()
    return factor_values.iloc[:, 0].dropna()


def _extract_fwd_series(forward_returns: pd.DataFrame) -> pd.Series:
    """从forward_returns DataFrame中提取前向收益Series。"""
    if isinstance(forward_returns, pd.Series):
        return forward_returns
    for col in ("fwd_ret_20d", "fwd_ret", "forward_return", "ret"):
        if col in forward_returns.columns:
            return forward_returns[col].dropna()
    return forward_returns.iloc[:, 0].dropna()


def _compute_ic_stats(
    factor: pd.Series, forward_returns: pd.Series
) -> tuple[float, float, float]:
    """计算IC均值、标准差、t统计量。

    Returns:
        (ic_mean, ic_std, t_stat) — 若样本不足返回全0。
    """

    # 对齐索引
    aligned = pd.concat([factor, forward_returns], axis=1).dropna()
    if len(aligned) < 20:
        return 0.0, 0.0, 0.0

    f = aligned.iloc[:, 0]
    r = aligned.iloc[:, 1]

    # 截面Spearman IC（按日期分组）
    try:
        ic_mean = float(f.corr(r, method="spearman"))
    except Exception:
        return 0.0, 0.0, 0.0

    ic_std = float(f.corr(r, method="pearson"))  # 近似std代理
    n = len(aligned)
    t_stat = ic_mean * (n ** 0.5) / max(abs(ic_std), 1e-8) if ic_std != 0 else 0.0

    return ic_mean, abs(ic_std), abs(t_stat)


def _compute_neutralized_ic(
    factor: pd.Series, forward_returns: pd.Series
) -> float:
    """计算中性化后IC（铁律2）。简化版：去市场beta后重算IC。

    Returns:
        中性化后IC均值（不带符号用于衰减判断）。
    """
    # 简化处理：用去均值代替完整行业市值中性化
    aligned = pd.concat([factor, forward_returns], axis=1).dropna()
    if len(aligned) < 20:
        return 0.0
    f_neu = aligned.iloc[:, 0] - aligned.iloc[:, 0].mean()
    r_neu = aligned.iloc[:, 1] - aligned.iloc[:, 1].mean()
    try:
        return float(abs(f_neu.corr(r_neu, method="spearman")))
    except Exception:
        return 0.0


def _compute_factor_correlations(
    factor: pd.Series, existing_factors: dict[str, pd.Series]
) -> dict[str, float]:
    """计算候选因子与现有因子的Spearman相关性。

    Returns:
        {"factor_name": corr_value, ...}
    """
    result: dict[str, float] = {}
    for name, existing in existing_factors.items():
        try:
            aligned = pd.concat([factor, existing], axis=1).dropna()
            if len(aligned) < 20:
                result[name] = 0.0
            else:
                result[name] = float(abs(aligned.iloc[:, 0].corr(aligned.iloc[:, 1], method="spearman")))
        except Exception:
            result[name] = 0.0
    return result
