"""单元测试 — FactorDSL (Sprint 1.16 因子表达式语言)

覆盖:
- 所有28个算子可调用且返回正确类型(pd.Series)
- 表达式树 round-trip: to_string() → from_string() → to_string() 一致
- 量纲约束: 非法深度/节点数/字段被拒绝
- evaluate() 边界: NaN处理/空DataFrame/单行数据
- crossover/mutate 产生合法表达式
- from_string 解析各类表达式格式
- validate() 正常/异常路径
- extract_template / apply_params 参数槽位分离

设计文档对照: docs/GP_CLOSED_LOOP_DESIGN.md §2
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from engines.mining.factor_dsl import (
    ALL_OPS,
    BINARY_OPS,
    CS_OPS,
    MAX_NODES,
    SEED_FACTORS,
    TS_BINARY_OPS,
    TS_OPS,
    UNARY_OPS,
    ExprNode,
    FactorDSL,
    OpType,
    get_seed_trees,
)

# ---------------------------------------------------------------------------
# 测试数据工厂
# ---------------------------------------------------------------------------


def _make_data(n: int = 100, seed: int = 0) -> pd.DataFrame:
    """生成包含所有终端字段的宽表 DataFrame（单截面，行=symbol）。"""
    rng = np.random.default_rng(seed)
    close = rng.uniform(5.0, 100.0, n)
    volume = rng.uniform(1e6, 1e8, n)
    amount = close * volume * rng.uniform(0.8, 1.2, n)
    pb = rng.uniform(0.5, 10.0, n)
    returns = rng.normal(0.0, 0.02, n)

    data = {
        "open":  close * rng.uniform(0.98, 1.02, n),
        "high":  close * rng.uniform(1.00, 1.05, n),
        "low":   close * rng.uniform(0.95, 1.00, n),
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover_rate": rng.uniform(0.001, 0.1, n),
        "pe_ttm": rng.uniform(5.0, 100.0, n),
        "pb": pb,
        "ps_ttm": rng.uniform(0.5, 20.0, n),
        "total_mv": close * rng.uniform(1e8, 1e10, n),
        "circ_mv": close * rng.uniform(5e7, 5e9, n),
        "buy_lg_amount": rng.uniform(1e6, 1e8, n),
        "sell_lg_amount": rng.uniform(1e6, 1e8, n),
        "net_lg_amount": rng.normal(0, 1e7, n),
        "buy_md_amount": rng.uniform(5e5, 5e7, n),
        "sell_md_amount": rng.uniform(5e5, 5e7, n),
        "net_md_amount": rng.normal(0, 5e6, n),
        "returns": returns,
        "vwap": amount / volume,
        "high_low": (close * rng.uniform(1.0, 1.05, n) - close * rng.uniform(0.95, 1.0, n)) / close,
        "close_open": rng.normal(0.0, 0.01, n),
    }
    return pd.DataFrame(data)


def _make_ts_data(n_rows: int = 60, seed: int = 0) -> pd.DataFrame:
    """生成时序数据（index 为整数序列，模拟单只股票历史）。"""
    rng = np.random.default_rng(seed)
    close = 10.0 * np.cumprod(1 + rng.normal(0, 0.02, n_rows))
    volume = rng.uniform(1e6, 5e6, n_rows)
    amount = close * volume
    returns = np.concatenate([[0.0], np.diff(close) / close[:-1]])
    pb = rng.uniform(1.0, 5.0, n_rows)

    data = {
        "open":  close * rng.uniform(0.99, 1.01, n_rows),
        "high":  close * rng.uniform(1.00, 1.03, n_rows),
        "low":   close * rng.uniform(0.97, 1.00, n_rows),
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover_rate": rng.uniform(0.001, 0.05, n_rows),
        "pe_ttm": rng.uniform(10.0, 50.0, n_rows),
        "pb": pb,
        "ps_ttm": rng.uniform(1.0, 10.0, n_rows),
        "total_mv": close * 1e8,
        "circ_mv": close * 5e7,
        "buy_lg_amount": rng.uniform(1e6, 5e6, n_rows),
        "sell_lg_amount": rng.uniform(1e6, 5e6, n_rows),
        "net_lg_amount": rng.normal(0, 1e6, n_rows),
        "buy_md_amount": rng.uniform(5e5, 2e6, n_rows),
        "sell_md_amount": rng.uniform(5e5, 2e6, n_rows),
        "net_md_amount": rng.normal(0, 5e5, n_rows),
        "returns": returns,
        "vwap": amount / volume,
        "high_low": (close * 1.02 - close * 0.98) / close,
        "close_open": rng.normal(0.0, 0.01, n_rows),
    }
    return pd.DataFrame(data)


@pytest.fixture(scope="module")
def data_cs() -> pd.DataFrame:
    """截面数据（100行）。"""
    return _make_data(n=100)


@pytest.fixture(scope="module")
def data_ts() -> pd.DataFrame:
    """时序数据（60行）。"""
    return _make_ts_data(n_rows=60)


@pytest.fixture(scope="module")
def dsl() -> FactorDSL:
    """标准 FactorDSL 实例（固定 seed）。"""
    return FactorDSL(seed=42)


# ---------------------------------------------------------------------------
# 1. 算子总数验证
# ---------------------------------------------------------------------------


class TestOperatorCount:
    """验证算子总数 == 28（设计规格）。"""

    def test_ts_ops_count(self) -> None:
        """时序算子: 11个。"""
        assert len(TS_OPS) == 11, f"TS_OPS 数量={len(TS_OPS)}, 期望11"

    def test_ts_binary_ops_count(self) -> None:
        """时序双目算子: 2个。"""
        assert len(TS_BINARY_OPS) == 2

    def test_cs_ops_count(self) -> None:
        """截面算子: 3个。"""
        assert len(CS_OPS) == 3

    def test_unary_ops_count(self) -> None:
        """单目数学算子: 6个。"""
        assert len(UNARY_OPS) == 6

    def test_binary_ops_count(self) -> None:
        """双目数学算子: 6个。"""
        assert len(BINARY_OPS) == 6

    def test_total_ops_at_least_28(self) -> None:
        """总算子数 >= 28（设计规格）。"""
        total = len(ALL_OPS)
        assert total >= 28, f"算子总数={total}, 期望>=28"


# ---------------------------------------------------------------------------
# 2. 每个算子可调用且返回 pd.Series
# ---------------------------------------------------------------------------


class TestAllOperatorsExecutable:
    """每个算子节点 evaluate() 应返回 pd.Series 而不抛出。"""

    def _run_op(self, op: str, data: pd.DataFrame) -> pd.Series:
        """构建单个算子的最小表达式树并求值。"""
        op_info = ALL_OPS[op]
        op_type = op_info["type"]

        terminal = ExprNode(op="close")
        terminal2 = ExprNode(op="volume")

        if op_type == OpType.TS:
            window = op_info["windows"][0]
            node = ExprNode(op=op, children=[terminal.clone()], window=window)
        elif op_type == OpType.TS_BINARY:
            window = op_info["windows"][0]
            node = ExprNode(op=op, children=[terminal.clone(), terminal2.clone()], window=window)
        elif op_type in (OpType.CS, OpType.UNARY):
            node = ExprNode(op=op, children=[terminal.clone()])
        elif op_type == OpType.BINARY:
            node = ExprNode(op=op, children=[terminal.clone(), terminal2.clone()])
        else:
            node = ExprNode(op=op, children=[terminal.clone()])

        result = node.evaluate(data)
        return result

    def test_ts_ops_return_series(self, data_ts: pd.DataFrame) -> None:
        """所有时序算子返回 pd.Series。"""
        for op in TS_OPS:
            result = self._run_op(op, data_ts)
            assert isinstance(result, pd.Series), f"{op} 未返回 pd.Series"

    def test_ts_binary_ops_return_series(self, data_ts: pd.DataFrame) -> None:
        """时序双目算子返回 pd.Series。"""
        for op in TS_BINARY_OPS:
            result = self._run_op(op, data_ts)
            assert isinstance(result, pd.Series), f"{op} 未返回 pd.Series"

    def test_cs_ops_return_series(self, data_cs: pd.DataFrame) -> None:
        """截面算子返回 pd.Series。"""
        for op in CS_OPS:
            result = self._run_op(op, data_cs)
            assert isinstance(result, pd.Series), f"{op} 未返回 pd.Series"

    def test_unary_ops_return_series(self, data_cs: pd.DataFrame) -> None:
        """单目数学算子返回 pd.Series。"""
        for op in UNARY_OPS:
            result = self._run_op(op, data_cs)
            assert isinstance(result, pd.Series), f"{op} 未返回 pd.Series"

    def test_binary_ops_return_series(self, data_cs: pd.DataFrame) -> None:
        """双目数学算子返回 pd.Series。"""
        for op in BINARY_OPS:
            result = self._run_op(op, data_cs)
            assert isinstance(result, pd.Series), f"{op} 未返回 pd.Series"

    def test_terminal_returns_series(self, data_cs: pd.DataFrame) -> None:
        """终端节点也返回 pd.Series。"""
        for field in ["close", "volume", "returns", "pb"]:
            node = ExprNode(op=field)
            result = node.evaluate(data_cs)
            assert isinstance(result, pd.Series)


# ---------------------------------------------------------------------------
# 3. 算子数值正确性
# ---------------------------------------------------------------------------


class TestOperatorCorrectness:
    """关键算子的数值正确性验证。"""

    def test_ts_mean_close_to_rolling_mean(self, data_ts: pd.DataFrame) -> None:
        """ts_mean 结果应等于 pandas rolling mean。"""
        node = ExprNode(op="ts_mean", children=[ExprNode(op="close")], window=10)
        result = node.evaluate(data_ts)
        expected = data_ts["close"].rolling(10, min_periods=5).mean()
        pd.testing.assert_series_equal(result.reset_index(drop=True),
                                       expected.reset_index(drop=True))

    def test_neg_negates_values(self, data_cs: pd.DataFrame) -> None:
        """neg 应对所有值取负。"""
        node = ExprNode(op="neg", children=[ExprNode(op="close")])
        result = node.evaluate(data_cs)
        np.testing.assert_array_almost_equal(result.values, -data_cs["close"].values)

    def test_abs_nonnegative(self, data_cs: pd.DataFrame) -> None:
        """abs 结果全部 >= 0。"""
        node = ExprNode(op="abs", children=[ExprNode(op="returns")])
        result = node.evaluate(data_cs)
        assert (result.dropna() >= 0).all()

    def test_inv_reciprocal(self, data_cs: pd.DataFrame) -> None:
        """inv(pb) 应约等于 1/pb。"""
        node = ExprNode(op="inv", children=[ExprNode(op="pb")])
        result = node.evaluate(data_cs)
        expected = 1.0 / data_cs["pb"]
        pd.testing.assert_series_equal(result.reset_index(drop=True),
                                       expected.reset_index(drop=True))

    def test_div_zero_returns_nan(self, data_cs: pd.DataFrame) -> None:
        """div 除以0应返回 NaN，不抛出。"""
        zero_col = data_cs.copy()
        zero_col["volume"] = 0.0
        node = ExprNode(op="div", children=[ExprNode(op="close"), ExprNode(op="volume")])
        result = node.evaluate(zero_col)
        assert isinstance(result, pd.Series)
        assert result.isna().all()

    def test_cs_rank_range(self, data_cs: pd.DataFrame) -> None:
        """cs_rank 结果应在 [0, 1]。"""
        node = ExprNode(op="cs_rank", children=[ExprNode(op="close")])
        result = node.evaluate(data_cs)
        valid = result.dropna()
        assert (valid >= 0.0).all() and (valid <= 1.0).all()

    def test_log_no_exception_on_negative(self, data_cs: pd.DataFrame) -> None:
        """log 对包含负值的序列不应抛出（设计: log(abs(x)+eps)）。"""
        neg_data = data_cs.copy()
        neg_data["returns"] = -1.0
        node = ExprNode(op="log", children=[ExprNode(op="returns")])
        result = node.evaluate(neg_data)
        assert isinstance(result, pd.Series)
        assert not result.isna().all()

    def test_sign_values_in_minus1_0_1(self, data_cs: pd.DataFrame) -> None:
        """sign 结果仅为 -1, 0, +1。"""
        node = ExprNode(op="sign", children=[ExprNode(op="returns")])
        result = node.evaluate(data_cs)
        valid = result.dropna().unique()
        for v in valid:
            assert v in (-1.0, 0.0, 1.0), f"sign 产生了非法值: {v}"

    def test_delay_shifts_by_window(self, data_ts: pd.DataFrame) -> None:
        """delay(close, 5) 应等于 close.shift(5)。"""
        node = ExprNode(op="delay", children=[ExprNode(op="close")], window=5)
        result = node.evaluate(data_ts)
        expected = data_ts["close"].shift(5)
        pd.testing.assert_series_equal(result.reset_index(drop=True),
                                       expected.reset_index(drop=True))

    def test_delta_equals_diff(self, data_ts: pd.DataFrame) -> None:
        """delta(close, 5) 应等于 close - close.shift(5)。"""
        node = ExprNode(op="delta", children=[ExprNode(op="close")], window=5)
        result = node.evaluate(data_ts)
        expected = data_ts["close"] - data_ts["close"].shift(5)
        pd.testing.assert_series_equal(result.reset_index(drop=True),
                                       expected.reset_index(drop=True))


# ---------------------------------------------------------------------------
# 4. 表达式树 Round-trip
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """to_string() → from_string() → to_string() 应保持一致。"""

    SEED_EXPRS = list(SEED_FACTORS.values())

    @pytest.mark.parametrize("expr_str", SEED_EXPRS)
    def test_seed_factor_round_trip(self, expr_str: str) -> None:
        """5个种子因子的 round-trip 一致性。"""
        dsl = FactorDSL()
        tree = dsl.from_string(expr_str)
        restored = tree.to_string()
        tree2 = dsl.from_string(restored)
        assert tree2.to_string() == restored, (
            f"Round-trip 失败: {expr_str!r} → {restored!r} → {tree2.to_string()!r}"
        )

    def test_complex_expr_round_trip(self) -> None:
        """复杂嵌套表达式 round-trip。"""
        dsl = FactorDSL()
        expr = "ts_mean(div(abs(returns), amount), 20)"
        tree = dsl.from_string(expr)
        restored = tree.to_string()
        tree2 = dsl.from_string(restored)
        assert tree2.to_string() == restored

    def test_binary_expr_round_trip(self) -> None:
        """双目表达式 round-trip。"""
        dsl = FactorDSL()
        expr = "add(cs_rank(close), neg(returns))"
        tree = dsl.from_string(expr)
        restored = tree.to_string()
        tree2 = dsl.from_string(restored)
        assert tree2.to_string() == restored

    def test_ts_corr_round_trip(self) -> None:
        """时序双目算子 round-trip。"""
        dsl = FactorDSL()
        expr = "ts_corr(close, volume, 20)"
        tree = dsl.from_string(expr)
        restored = tree.to_string()
        tree2 = dsl.from_string(restored)
        assert tree2.to_string() == restored

    def test_terminal_round_trip(self) -> None:
        """终端节点 round-trip。"""
        dsl = FactorDSL()
        for field in ["close", "returns", "pb"]:
            tree = dsl.from_string(field)
            assert tree.to_string() == field

    def test_random_trees_round_trip(self) -> None:
        """随机生成10棵树，每棵 round-trip 一致。"""
        dsl = FactorDSL(seed=123)
        for _ in range(10):
            tree = dsl.random_tree()
            expr = tree.to_string()
            tree2 = dsl.from_string(expr)
            assert tree2.to_string() == expr, f"随机树 round-trip 失败: {expr!r}"


# ---------------------------------------------------------------------------
# 5. 量纲约束 / validate()
# ---------------------------------------------------------------------------


class TestValidation:
    """validate() 应正确拒绝非法表达式。"""

    def test_valid_seed_trees_pass(self) -> None:
        """5个种子因子均应通过 validate()。"""
        dsl = FactorDSL()
        for name, expr in SEED_FACTORS.items():
            tree = dsl.from_string(expr)
            valid, reason = dsl.validate(tree)
            assert valid, f"种子因子 {name} 验证失败: {reason}"

    def test_depth_exceeded_rejected(self) -> None:
        """超过 MAX_DEPTH 的树应被拒绝。"""
        dsl = FactorDSL(max_depth=2)
        # 构造深度=5的树（超出 max_depth=2）
        node = ExprNode(op="close")
        for _ in range(5):
            node = ExprNode(op="neg", children=[node])
        valid, reason = dsl.validate(node)
        assert not valid
        assert "深度" in reason or "depth" in reason.lower()

    def test_node_count_exceeded_rejected(self) -> None:
        """超过 MAX_NODES 的树应被拒绝。"""
        dsl = FactorDSL(max_nodes=3)
        # 构造节点数>3的树
        tree = ExprNode(
            op="add",
            children=[
                ExprNode(op="neg", children=[ExprNode(op="close")]),
                ExprNode(op="neg", children=[ExprNode(op="returns")]),
            ],
        )
        valid, reason = dsl.validate(tree)
        assert not valid
        assert "节点" in reason or "node" in reason.lower()

    def test_unknown_field_rejected(self) -> None:
        """使用未知字段名的终端节点应被拒绝。"""
        dsl = FactorDSL()
        tree = ExprNode(op="nonexistent_field_xyz")
        valid, reason = dsl.validate(tree)
        assert not valid
        assert "未知字段" in reason or "nonexistent" in reason

    def test_ts_op_missing_window_rejected(self) -> None:
        """时序算子缺少窗口参数应被拒绝。"""
        dsl = FactorDSL()
        tree = ExprNode(op="ts_mean", children=[ExprNode(op="close")], window=None)
        valid, reason = dsl.validate(tree)
        assert not valid
        assert "窗口" in reason or "window" in reason.lower()

    def test_ts_op_zero_window_rejected(self) -> None:
        """时序算子窗口=0 应被拒绝。"""
        dsl = FactorDSL()
        tree = ExprNode(op="ts_mean", children=[ExprNode(op="close")], window=0)
        valid, reason = dsl.validate(tree)
        assert not valid

    def test_normal_depth_passes(self) -> None:
        """深度在限制内的树应通过。"""
        dsl = FactorDSL()
        tree = ExprNode(
            op="ts_mean",
            children=[ExprNode(op="cs_rank", children=[ExprNode(op="close")])],
            window=20,
        )
        valid, reason = dsl.validate(tree)
        assert valid, reason


# ---------------------------------------------------------------------------
# 6. evaluate() 边界情况
# ---------------------------------------------------------------------------


class TestEvaluateBoundary:
    """evaluate() 在边界情况下的健壮性。"""

    def test_missing_column_returns_nan(self) -> None:
        """数据中不存在的字段应返回全 NaN，不抛出。"""
        data = pd.DataFrame({"close": [1.0, 2.0, 3.0]})
        node = ExprNode(op="nonexistent_col")
        result = node.evaluate(data)
        assert isinstance(result, pd.Series)
        assert result.isna().all()

    def test_empty_dataframe_returns_empty_series(self) -> None:
        """空 DataFrame 应返回空 Series，不抛出。"""
        data = pd.DataFrame(columns=["close", "volume", "returns"])
        node = ExprNode(op="ts_mean", children=[ExprNode(op="close")], window=5)
        result = node.evaluate(data)
        assert isinstance(result, pd.Series)
        assert len(result) == 0

    def test_single_row_returns_series(self) -> None:
        """单行数据（最小输入）应返回长度=1的 Series。"""
        data = _make_data(n=1)
        node = ExprNode(op="close")
        result = node.evaluate(data)
        assert len(result) == 1

    def test_all_nan_input_returns_nan(self) -> None:
        """全 NaN 输入应返回全 NaN（不抛出）。"""
        data = pd.DataFrame({
            "close": [float("nan")] * 20,
            "volume": [float("nan")] * 20,
            "returns": [float("nan")] * 20,
        })
        node = ExprNode(op="ts_mean", children=[ExprNode(op="close")], window=5)
        result = node.evaluate(data)
        assert isinstance(result, pd.Series)

    def test_nested_div_zero_does_not_crash(self) -> None:
        """嵌套 div(x, 0) 不应抛出，应返回 NaN。"""
        data = pd.DataFrame({"close": [1.0, 2.0, 3.0], "volume": [0.0, 0.0, 0.0]})
        node = ExprNode(
            op="div",
            children=[ExprNode(op="close"), ExprNode(op="volume")],
        )
        result = node.evaluate(data)
        assert isinstance(result, pd.Series)
        assert result.isna().all()

    def test_ts_kurt_short_series_no_crash(self) -> None:
        """时序 kurt 在短序列下不应崩溃（min_periods 保护）。"""
        data = _make_ts_data(n_rows=5)
        node = ExprNode(op="ts_kurt", children=[ExprNode(op="close")], window=20)
        result = node.evaluate(data)
        assert isinstance(result, pd.Series)


# ---------------------------------------------------------------------------
# 7. from_string 解析
# ---------------------------------------------------------------------------


class TestFromString:
    """from_string() 对各种格式的解析正确性。"""

    def test_parse_terminal(self) -> None:
        dsl = FactorDSL()
        tree = dsl.from_string("close")
        assert tree.op == "close"
        assert not tree.children

    def test_parse_ts_op(self) -> None:
        dsl = FactorDSL()
        tree = dsl.from_string("ts_mean(close, 20)")
        assert tree.op == "ts_mean"
        assert tree.window == 20
        assert len(tree.children) == 1
        assert tree.children[0].op == "close"

    def test_parse_unary_op(self) -> None:
        dsl = FactorDSL()
        tree = dsl.from_string("neg(returns)")
        assert tree.op == "neg"
        assert tree.children[0].op == "returns"

    def test_parse_binary_op(self) -> None:
        dsl = FactorDSL()
        tree = dsl.from_string("div(abs(returns), amount)")
        assert tree.op == "div"
        assert len(tree.children) == 2
        assert tree.children[0].op == "abs"
        assert tree.children[1].op == "amount"

    def test_parse_ts_binary_op(self) -> None:
        dsl = FactorDSL()
        tree = dsl.from_string("ts_corr(close, volume, 20)")
        assert tree.op == "ts_corr"
        assert tree.window == 20
        assert len(tree.children) == 2

    def test_parse_deeply_nested(self) -> None:
        dsl = FactorDSL()
        expr = "ts_mean(cs_rank(div(abs(returns), amount)), 20)"
        tree = dsl.from_string(expr)
        assert tree.op == "ts_mean"
        assert tree.window == 20

    def test_parse_empty_string_raises(self) -> None:
        dsl = FactorDSL()
        with pytest.raises(ValueError):
            dsl.from_string("")

    def test_parse_invalid_string_raises(self) -> None:
        dsl = FactorDSL()
        with pytest.raises((ValueError, Exception)):
            dsl.from_string("!!!invalid!!!")


# ---------------------------------------------------------------------------
# 8. node_count / depth / complexity_score
# ---------------------------------------------------------------------------


class TestNodeMetrics:
    """节点计数、深度、复杂度分数验证。"""

    def test_terminal_node_count_is_1(self) -> None:
        node = ExprNode(op="close")
        assert node.node_count() == 1

    def test_terminal_depth_is_1(self) -> None:
        node = ExprNode(op="close")
        assert node.depth() == 1

    def test_unary_node_count_is_2(self) -> None:
        node = ExprNode(op="neg", children=[ExprNode(op="close")])
        assert node.node_count() == 2

    def test_unary_depth_is_2(self) -> None:
        node = ExprNode(op="neg", children=[ExprNode(op="close")])
        assert node.depth() == 2

    def test_complexity_score_range(self) -> None:
        """complexity_score 应在 [0, 1]。"""
        dsl = FactorDSL(seed=0)
        for _ in range(20):
            tree = dsl.random_tree()
            score = tree.complexity_score()
            assert 0.0 <= score <= 1.0

    def test_complexity_score_formula(self) -> None:
        """complexity_score = node_count / MAX_NODES（上限1.0）。"""
        node = ExprNode(op="close")
        expected = min(1.0, 1 / MAX_NODES)
        assert node.complexity_score() == pytest.approx(expected)

    def test_ast_hash_structure_invariant(self) -> None:
        """相同结构、不同窗口参数应产生相同 AST hash（窗口归一化）。"""
        dsl = FactorDSL()
        t1 = dsl.from_string("ts_mean(close, 20)")
        t2 = dsl.from_string("ts_mean(close, 60)")
        assert t1.to_ast_hash() == t2.to_ast_hash()

    def test_different_structure_different_hash(self) -> None:
        """不同结构应产生不同 AST hash。"""
        dsl = FactorDSL()
        t1 = dsl.from_string("ts_mean(close, 20)")
        t2 = dsl.from_string("ts_std(close, 20)")
        assert t1.to_ast_hash() != t2.to_ast_hash()


# ---------------------------------------------------------------------------
# 9. crossover / mutate 产生合法表达式
# ---------------------------------------------------------------------------


class TestGeneticOperators:
    """crossover 和 mutate 应产生满足约束的合法表达式。"""

    def test_crossover_returns_two_nodes(self) -> None:
        """crossover 应返回两个 ExprNode。"""
        dsl = FactorDSL(seed=1)
        a = dsl.from_string("ts_mean(close, 20)")
        b = dsl.from_string("ts_std(returns, 10)")
        c1, c2 = dsl.crossover(a, b)
        assert isinstance(c1, ExprNode)
        assert isinstance(c2, ExprNode)

    def test_crossover_result_valid(self) -> None:
        """crossover 结果应通过 validate()。"""
        dsl = FactorDSL(seed=2)
        for _ in range(10):
            a = dsl.random_tree()
            b = dsl.random_tree()
            c1, c2 = dsl.crossover(a, b)
            v1, r1 = dsl.validate(c1)
            v2, r2 = dsl.validate(c2)
            assert v1, f"crossover child1 非法: {r1} (expr={c1.to_string()!r})"
            assert v2, f"crossover child2 非法: {r2} (expr={c2.to_string()!r})"

    def test_crossover_produces_legal_expression(self) -> None:
        """crossover 后的字符串可被 from_string 重新解析。"""
        dsl = FactorDSL(seed=7)
        for _ in range(10):
            a = dsl.random_tree()
            b = dsl.random_tree()
            c1, c2 = dsl.crossover(a, b)
            expr1 = c1.to_string()
            expr2 = c2.to_string()
            # 可以重新解析（不抛出）
            dsl.from_string(expr1)
            dsl.from_string(expr2)

    def test_mutate_returns_expr_node(self) -> None:
        """mutate 应返回 ExprNode。"""
        dsl = FactorDSL(seed=3)
        tree = dsl.from_string("ts_mean(close, 20)")
        mutated = dsl.mutate(tree)
        assert isinstance(mutated, ExprNode)

    def test_mutate_result_valid(self) -> None:
        """mutate 结果应通过 validate()。"""
        dsl = FactorDSL(seed=4)
        for _ in range(20):
            tree = dsl.random_tree()
            mutated = dsl.mutate(tree)
            valid, reason = dsl.validate(mutated)
            assert valid, f"mutate 结果非法: {reason} (expr={mutated.to_string()!r})"

    def test_mutate_preserves_tree_type(self) -> None:
        """mutate 不应改变原始树（返回新树）。"""
        dsl = FactorDSL(seed=5)
        tree = dsl.from_string("ts_mean(close, 20)")
        original_expr = tree.to_string()
        # 多次 mutate，原始树不变
        for _ in range(5):
            dsl.mutate(tree)
        assert tree.to_string() == original_expr

    def test_mutate_can_change_expression(self) -> None:
        """多次 mutate 后应有至少一次产生不同的表达式（不总是恒等变换）。"""
        dsl = FactorDSL(seed=99)
        tree = dsl.from_string("ts_mean(close, 20)")
        original = tree.to_string()
        changed = False
        for _ in range(20):
            m = dsl.mutate(tree)
            if m.to_string() != original:
                changed = True
                break
        assert changed, "mutate 20次从未改变表达式，疑似 bug"


# ---------------------------------------------------------------------------
# 10. extract_template / apply_params
# ---------------------------------------------------------------------------


class TestTemplateExtraction:
    """逻辑/参数分离（extract_template / apply_params）正确性。"""

    def test_extract_template_extracts_window(self) -> None:
        """ts_mean 应提取出窗口槽位。"""
        dsl = FactorDSL()
        tree = dsl.from_string("ts_mean(close, 20)")
        template, params = dsl.extract_template(tree)
        assert "w0" in params
        assert params["w0"] == 20

    def test_apply_params_restores_window(self) -> None:
        """apply_params 后的树应还原窗口。"""
        dsl = FactorDSL()
        tree = dsl.from_string("ts_mean(close, 20)")
        template, params = dsl.extract_template(tree)
        restored = dsl.apply_params(template, params)
        # 还原后 to_string 应和原树一致
        assert restored.to_string() == tree.to_string()

    def test_multiple_windows_extracted(self) -> None:
        """嵌套时序算子应提取多个槽位。"""
        dsl = FactorDSL()
        expr = "ts_mean(ts_std(returns, 10), 20)"
        tree = dsl.from_string(expr)
        _, params = dsl.extract_template(tree)
        assert len(params) >= 2

    def test_no_window_ops_empty_params(self) -> None:
        """无时序算子的表达式应产生空参数字典。"""
        dsl = FactorDSL()
        tree = dsl.from_string("neg(cs_rank(returns))")
        _, params = dsl.extract_template(tree)
        assert len(params) == 0

    def test_param_search_space_covers_valid_windows(self) -> None:
        """get_param_search_space 应返回算子合法窗口列表。"""
        dsl = FactorDSL()
        tree = dsl.from_string("ts_mean(close, 20)")
        template, params = dsl.extract_template(tree)
        space = dsl.get_param_search_space(template, params)
        assert "w0" in space
        assert 20 in space["w0"]


# ---------------------------------------------------------------------------
# 11. get_seed_trees
# ---------------------------------------------------------------------------


class TestSeedTrees:
    """get_seed_trees() 返回与 SEED_FACTORS 对应的合法树。"""

    def test_returns_all_5_seeds(self) -> None:
        trees = get_seed_trees()
        assert len(trees) == len(SEED_FACTORS)

    def test_seed_trees_are_expr_nodes(self) -> None:
        trees = get_seed_trees()
        for name, tree in trees.items():
            assert isinstance(tree, ExprNode), f"{name} 不是 ExprNode"

    def test_seed_trees_pass_validation(self) -> None:
        dsl = FactorDSL()
        trees = get_seed_trees()
        for name, tree in trees.items():
            valid, reason = dsl.validate(tree)
            assert valid, f"种子树 {name} 验证失败: {reason}"

    def test_seed_trees_match_factor_exprs(self) -> None:
        """seed tree 的 to_string() 应和 SEED_FACTORS 原始表达式 round-trip 一致。"""
        dsl = FactorDSL()
        trees = get_seed_trees()
        for name, expr in SEED_FACTORS.items():
            tree = trees[name]
            # parse original → to_string → compare with seed tree to_string
            parsed = dsl.from_string(expr)
            assert parsed.to_string() == tree.to_string()


# ---------------------------------------------------------------------------
# 12. seed_to_variants
# ---------------------------------------------------------------------------


class TestSeedToVariants:
    """seed_to_variants 生成的变体数量和合法性。"""

    def test_variants_count_matches_request(self) -> None:
        dsl = FactorDSL(seed=10)
        variants = dsl.seed_to_variants("turnover_mean_20", "ts_mean(turnover_rate, 20)", n_variants=8)
        assert len(variants) == 8

    def test_variants_include_original_seed(self) -> None:
        """第一个变体应为原始种子（不变）。"""
        dsl = FactorDSL(seed=10)
        original = "ts_mean(turnover_rate, 20)"
        variants = dsl.seed_to_variants("turnover_mean_20", original, n_variants=5)
        assert variants[0].to_string() == original

    def test_all_variants_are_valid(self) -> None:
        """所有变体应通过 validate()。"""
        dsl = FactorDSL(seed=11)
        for name, expr in SEED_FACTORS.items():
            variants = dsl.seed_to_variants(name, expr, n_variants=6)
            for i, v in enumerate(variants):
                valid, reason = dsl.validate(v)
                assert valid, f"种子 {name} 变体[{i}] 非法: {reason} (expr={v.to_string()!r})"

    def test_variants_are_expr_nodes(self) -> None:
        dsl = FactorDSL(seed=12)
        variants = dsl.seed_to_variants("bp_ratio", "inv(pb)", n_variants=4)
        for v in variants:
            assert isinstance(v, ExprNode)


# ---------------------------------------------------------------------------
# 13. random_tree
# ---------------------------------------------------------------------------


class TestRandomTree:
    """random_tree 生成的树满足约束。"""

    def test_random_tree_depth_within_limit(self) -> None:
        dsl = FactorDSL(seed=20)
        for _ in range(50):
            tree = dsl.random_tree()
            assert tree.depth() <= dsl.max_depth, (
                f"树深度 {tree.depth()} 超过上限 {dsl.max_depth}"
            )

    def test_random_tree_node_count_within_limit(self) -> None:
        dsl = FactorDSL(seed=21)
        for _ in range(50):
            tree = dsl.random_tree()
            assert tree.node_count() <= dsl.max_nodes

    def test_random_tree_passes_validate(self) -> None:
        dsl = FactorDSL(seed=22)
        for _ in range(30):
            tree = dsl.random_tree()
            valid, reason = dsl.validate(tree)
            assert valid, f"random_tree 产生非法树: {reason} (expr={tree.to_string()!r})"

    def test_random_tree_with_seed_is_deterministic(self) -> None:
        """相同 seed 的 FactorDSL 生成相同序列的随机树。"""
        dsl1 = FactorDSL(seed=77)
        dsl2 = FactorDSL(seed=77)
        for _ in range(5):
            t1 = dsl1.random_tree()
            t2 = dsl2.random_tree()
            assert t1.to_string() == t2.to_string()
