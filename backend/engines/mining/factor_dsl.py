"""FactorDSL — 因子表达式语言（GP搜索空间定义）

设计来源: GP_CLOSED_LOOP_DESIGN.md §2
功能:
  1. 算子集定义（28个算子）：时序/截面/数学/数据终端
  2. 表达式树（AST）：ExprNode基类 + 求值 + 序列化
  3. 量纲约束（剪枝无意义表达式）
  4. 复杂度计算（节点数 + 深度加权）
  5. 逻辑/参数分离（R2研究: 参数槽位提取）
  6. Warm Start种子因子定义（v1.1的5个因子）

Sprint 1.16 alpha-miner
"""

from __future__ import annotations

import hashlib
import random
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 算子类型枚举
# ---------------------------------------------------------------------------


class OpType(Enum):
    """算子类型。"""
    UNARY = "unary"           # 单目: f(x) → y
    BINARY = "binary"         # 双目: f(x, y) → z
    TERNARY = "ternary"       # 三目: f(cond, x, y) → z  [NEW: FactorMiner ifelse]
    TS = "ts"                 # 时序: f(x, window) → y
    TS_BINARY = "ts_binary"   # 时序双目: f(x, y, window) → z
    CS = "cs"                 # 截面: f(x) → rank/zscore
    TERMINAL = "terminal"     # 终端: 数据字段或常数


class DimType(Enum):
    """量纲类型 — 用于过滤无经济意义的表达式 (AlphaZero量纲约束)。"""
    PRICE = "price"           # 元: open, high, low, close, vwap
    VOLUME = "volume"         # 手: volume
    AMOUNT = "amount"         # 元(成交额): amount, buy_lg_amount, ...
    RATIO = "ratio"           # 无量纲: returns, turnover_rate, pe_ttm, pb, ...
    MARKET_CAP = "market_cap" # 元(大数): total_mv, circ_mv
    UNKNOWN = "unknown"       # 经运算后无法追踪


# ---------------------------------------------------------------------------
# 算子注册表
# ---------------------------------------------------------------------------

# 时序算子 (必须指定窗口w)
TS_OPS: dict[str, dict[str, Any]] = {
    "ts_mean":  {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},
    "ts_std":   {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},
    "ts_max":   {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},
    "ts_min":   {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},
    "ts_sum":   {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},
    "ts_rank":  {"args": 1, "windows": [5, 10, 20],     "type": OpType.TS},
    "ts_skew":  {"args": 1, "windows": [20, 60],        "type": OpType.TS},
    "ts_kurt":  {"args": 1, "windows": [20, 60],        "type": OpType.TS},
    "delay":    {"args": 1, "windows": [1, 5, 10, 20],  "type": OpType.TS},
    "delta":    {"args": 1, "windows": [1, 5, 10, 20],  "type": OpType.TS},
    "ts_pct":   {"args": 1, "windows": [1, 5, 10, 20],  "type": OpType.TS},
    # NEW: AlphaZero/FactorMiner operators
    "ts_slope":         {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},   # 线性回归斜率
    "ts_rsquare":       {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},   # 线性回归R²
    "ts_decay_linear":  {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},   # 线性衰减加权mean
    "ts_argmax":        {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},   # 最大值位置/window
    "ts_argmin":        {"args": 1, "windows": [5, 10, 20, 60], "type": OpType.TS},   # 最小值位置/window
}

# 时序双目算子
TS_BINARY_OPS: dict[str, dict[str, Any]] = {
    "ts_corr":  {"args": 2, "windows": [10, 20, 60], "type": OpType.TS_BINARY},
    "ts_cov":   {"args": 2, "windows": [10, 20, 60], "type": OpType.TS_BINARY},
}

# 截面算子（不需要窗口参数）
CS_OPS: dict[str, dict[str, Any]] = {
    "cs_rank":   {"args": 1, "type": OpType.CS},
    "cs_zscore": {"args": 1, "type": OpType.CS},
    "cs_demean": {"args": 1, "type": OpType.CS},
}

# 单目数学算子
UNARY_OPS: dict[str, dict[str, Any]] = {
    "log":  {"args": 1, "type": OpType.UNARY},   # log(abs(x)+1e-10)
    "abs":  {"args": 1, "type": OpType.UNARY},
    "sign": {"args": 1, "type": OpType.UNARY},
    "neg":  {"args": 1, "type": OpType.UNARY},   # -x
    "inv":  {"args": 1, "type": OpType.UNARY},   # 1/x (安全除法)
    "sqrt": {"args": 1, "type": OpType.UNARY},   # sqrt(abs(x))
}

# 双目数学算子
BINARY_OPS: dict[str, dict[str, Any]] = {
    "add": {"args": 2, "type": OpType.BINARY},
    "sub": {"args": 2, "type": OpType.BINARY},
    "mul": {"args": 2, "type": OpType.BINARY},
    "div": {"args": 2, "type": OpType.BINARY},   # 安全除法
    "max": {"args": 2, "type": OpType.BINARY},
    "min": {"args": 2, "type": OpType.BINARY},
    # NEW: AlphaZero power operator
    "power": {"args": 2, "type": OpType.BINARY},  # x^n (n=child2, 常用0.5/2/3)
}

# 三目算子 (NEW: FactorMiner ifelse)
TERNARY_OPS: dict[str, dict[str, Any]] = {
    "ifelse": {"args": 3, "type": OpType.TERNARY},  # if(cond>0, x, y)
}

# 所有算子合并（便于查找）
ALL_OPS: dict[str, dict[str, Any]] = {
    **TS_OPS,
    **TS_BINARY_OPS,
    **CS_OPS,
    **UNARY_OPS,
    **BINARY_OPS,
    **TERNARY_OPS,
}

# 终端节点（数据字段）
TERMINALS: list[str] = [
    # 价量 (日频)
    "open", "high", "low", "close", "volume", "amount", "turnover_rate",
    # 估值 (日频)
    "pe_ttm", "pb", "ps_ttm", "total_mv", "circ_mv",
    # 资金流向 (日频)
    "buy_lg_amount", "sell_lg_amount", "net_lg_amount",
    "buy_md_amount", "sell_md_amount", "net_md_amount",
    # 派生 (预计算)
    "returns",     # close/delay(close,1) - 1
    "vwap",        # amount/volume
    "high_low",    # (high-low)/close
    "close_open",  # (close-open)/open
]

# 无量纲终端（可直接做截面比较）
DIMENSIONLESS_TERMINALS: frozenset[str] = frozenset(
    {
        "returns", "turnover_rate", "high_low", "close_open",
        "pe_ttm", "pb", "ps_ttm",  # 估值比率本身无量纲
    }
)

# 树结构约束
MAX_DEPTH: int = 4
MAX_NODES: int = 20

# 种子因子（v1.1的5个Active因子的DSL表达式）
SEED_FACTORS: dict[str, str] = {
    "turnover_mean_20": "ts_mean(turnover_rate, 20)",
    "volatility_20":    "ts_std(returns, 20)",
    "reversal_20":      "neg(ts_pct(close, 20))",
    "amihud_20":        "ts_mean(div(abs(returns), amount), 20)",
    "bp_ratio":         "inv(pb)",
}


# ---------------------------------------------------------------------------
# 量纲约束规则
# ---------------------------------------------------------------------------

DIMENSION_RULES: dict[str, Any] = {
    # 无量纲终端字段（可直接做截面排序）
    "dimensionless": DIMENSIONLESS_TERMINALS,
    # 禁止的算子-参数组合（无经济学意义）
    "forbidden_combos": [
        ("ts_corr", "volume", "pe_ttm"),
        ("div", "close", "volume"),
    ],
}

# ---------------------------------------------------------------------------
# 量纲类型映射 (AlphaZero 正则化进化核心机制)
# ---------------------------------------------------------------------------

TERMINAL_DIM: dict[str, DimType] = {
    # 价格类 (元/股)
    "open": DimType.PRICE, "high": DimType.PRICE,
    "low": DimType.PRICE, "close": DimType.PRICE, "vwap": DimType.PRICE,
    # 成交量 (手)
    "volume": DimType.VOLUME,
    # 成交额 (元)
    "amount": DimType.AMOUNT,
    "buy_lg_amount": DimType.AMOUNT, "sell_lg_amount": DimType.AMOUNT,
    "net_lg_amount": DimType.AMOUNT,
    "buy_md_amount": DimType.AMOUNT, "sell_md_amount": DimType.AMOUNT,
    "net_md_amount": DimType.AMOUNT,
    # 市值 (元, 大数)
    "total_mv": DimType.MARKET_CAP, "circ_mv": DimType.MARKET_CAP,
    # 无量纲比率
    "returns": DimType.RATIO, "turnover_rate": DimType.RATIO,
    "pe_ttm": DimType.RATIO, "pb": DimType.RATIO, "ps_ttm": DimType.RATIO,
    "high_low": DimType.RATIO, "close_open": DimType.RATIO,
}

# 同量纲终端分组 (用于关联变异的字段替换)
DIM_GROUPS: dict[DimType, list[str]] = {}
for _term, _dim in TERMINAL_DIM.items():
    DIM_GROUPS.setdefault(_dim, []).append(_term)


def infer_dimension(node: ExprNode) -> DimType:
    """推断表达式树的输出量纲。

    规则:
    - 终端: 查 TERMINAL_DIM
    - ts_*/delay/delta: 保持输入量纲
    - cs_rank/cs_zscore/cs_demean: → RATIO
    - ts_corr/ts_cov: → RATIO
    - log/sqrt: 仅接受 RATIO → RATIO
    - abs/neg/sign: 保持输入量纲
    - add/sub: 同量纲 → 同量纲, 否则 UNKNOWN
    - div: 同量纲 → RATIO, 否则 UNKNOWN
    - mul/power: → UNKNOWN (新量纲无法追踪)
    - ts_slope/ts_rsquare/ts_argmax/ts_argmin/ts_decay_linear: → RATIO
    - ifelse: 取 then-branch 量纲
    """
    op = node.op

    if op == "const":
        return DimType.RATIO

    if not node.children:
        return TERMINAL_DIM.get(op, DimType.UNKNOWN)

    child_dims = [infer_dimension(c) for c in node.children]

    # 截面算子 → RATIO
    if op in ("cs_rank", "cs_zscore", "cs_demean"):
        return DimType.RATIO

    # 时序相关/协方差 → RATIO
    if op in ("ts_corr", "ts_cov"):
        return DimType.RATIO

    # 回归/位置类 → RATIO
    if op in ("ts_slope", "ts_rsquare", "ts_argmax", "ts_argmin"):
        return DimType.RATIO

    # 时序单目: 保持输入量纲
    if op in ("ts_mean", "ts_std", "ts_max", "ts_min", "ts_sum",
              "ts_rank", "ts_skew", "ts_kurt", "ts_decay_linear",
              "delay", "delta", "ts_pct"):
        return child_dims[0]

    # abs/neg: 保持量纲
    if op in ("abs", "neg"):
        return child_dims[0]

    # sign → RATIO
    if op == "sign":
        return DimType.RATIO

    # log/sqrt: 仅RATIO有意义
    if op in ("log", "sqrt", "inv"):
        return DimType.RATIO

    # add/sub: 同量纲 → 同量纲
    if op in ("add", "sub"):
        if child_dims[0] == child_dims[1]:
            return child_dims[0]
        return DimType.UNKNOWN

    # div: 同量纲 → RATIO
    if op == "div":
        if child_dims[0] == child_dims[1]:
            return DimType.RATIO
        # 不同量纲的div也可能有意义 (如 amount/volume → price)
        return DimType.UNKNOWN

    # mul/power → UNKNOWN
    if op in ("mul", "power"):
        return DimType.UNKNOWN

    # ifelse: 取 then-branch 量纲
    if op == "ifelse" and len(child_dims) >= 2:
        return child_dims[1]

    return DimType.UNKNOWN


def check_dimensional_validity(node: ExprNode) -> tuple[bool, str]:
    """检查表达式的量纲合规性 (AlphaZero核心过滤机制)。

    Returns:
        (is_valid, reason)
    """
    for n in node.all_nodes():
        if not n.children:
            continue

        op = n.op
        child_dims = [infer_dimension(c) for c in n.children]

        # 规则1: add/sub 必须同量纲
        if op in ("add", "sub"):
            if len(child_dims) >= 2 and child_dims[0] != child_dims[1]:
                if child_dims[0] != DimType.UNKNOWN and child_dims[1] != DimType.UNKNOWN:
                    return False, (
                        f"{op}({child_dims[0].value}, {child_dims[1].value}): "
                        f"不同量纲相加减无意义"
                    )

        # 规则2: log/sqrt 仅接受 RATIO
        if op in ("log", "sqrt"):
            if child_dims[0] not in (DimType.RATIO, DimType.UNKNOWN):
                return False, (
                    f"{op}({child_dims[0].value}): "
                    f"对有量纲数据取log/sqrt无意义"
                )

        # 规则3: 同类型相乘无经济意义 (price*price / volume*volume)
        if op == "mul":
            if (len(child_dims) >= 2
                    and child_dims[0] == child_dims[1]
                    and child_dims[0] in (DimType.PRICE, DimType.VOLUME, DimType.MARKET_CAP)):
                return False, (
                    f"mul({child_dims[0].value}, {child_dims[1].value}): "
                    f"同类型相乘无经济意义"
                )

    return True, "OK"


# ---------------------------------------------------------------------------
# 表达式树节点
# ---------------------------------------------------------------------------


@dataclass
class ExprNode:
    """因子表达式树节点。

    支持算子节点（OpNode语义）、数据节点（终端字段）、常数节点。
    用单一dataclass表示，通过op字段区分类型：
      - op是算子名（如"ts_mean"）：算子节点，children非空
      - op是终端名（如"close"）：数据节点，children为空
      - op是"const"：常数节点，value字段有值
    """

    op: str
    children: list[ExprNode] = field(default_factory=list)
    window: int | None = None        # 时序算子窗口参数
    value: float | None = None       # const节点的值

    # ----------------------------------------------------------------
    # 序列化
    # ----------------------------------------------------------------

    def to_string(self) -> str:
        """序列化为可读字符串，例如 ts_mean(cs_rank(close), 20)。"""
        if self.op == "const":
            v = self.value if self.value is not None else 0.0
            return str(int(v)) if v == int(v) else f"{v:.4g}"

        if not self.children:
            # 终端节点
            return self.op

        op_info = ALL_OPS.get(self.op, {})
        op_type = op_info.get("type", OpType.UNARY)

        child_strs = [c.to_string() for c in self.children]

        if op_type == OpType.TS:
            w = self.window or 20
            return f"{self.op}({child_strs[0]}, {w})"
        elif op_type == OpType.TS_BINARY:
            w = self.window or 20
            return f"{self.op}({child_strs[0]}, {child_strs[1]}, {w})"
        elif op_type in (OpType.CS, OpType.UNARY):
            return f"{self.op}({child_strs[0]})"
        elif op_type == OpType.BINARY:
            return f"{self.op}({child_strs[0]}, {child_strs[1]})"
        elif op_type == OpType.TERNARY:
            return f"{self.op}({', '.join(child_strs)})"
        else:
            args_str = ", ".join(child_strs)
            return f"{self.op}({args_str})"

    def to_ast_hash(self) -> str:
        """结构哈希（窗口参数归一化后），用于AST去重。

        窗口参数归一化为占位符，使不同窗口的相同结构产生相同哈希前缀。
        """
        struct = self._structure_repr(normalize_window=True)
        return hashlib.sha256(struct.encode()).hexdigest()[:16]

    def _structure_repr(self, normalize_window: bool = False) -> str:
        """递归生成结构表示字符串。"""
        if self.op == "const":
            return "CONST"
        if not self.children:
            return self.op
        child_reprs = [c._structure_repr(normalize_window) for c in self.children]
        if normalize_window and self.window is not None:
            w_str = "W"
        else:
            w_str = str(self.window) if self.window is not None else ""
        parts = [self.op] + child_reprs
        if w_str:
            parts.append(w_str)
        return f"({','.join(parts)})"

    # ----------------------------------------------------------------
    # 求值
    # ----------------------------------------------------------------

    def evaluate(self, data: pd.DataFrame) -> pd.Series:
        """安全执行，返回截面因子值 Series（index = symbol_id）。

        Args:
            data: 宽表，行=symbol，列=字段名（close/volume等）。

        Returns:
            pd.Series: 因子值（index与data.index一致）。
        """
        return _eval_node(self, data)

    # ----------------------------------------------------------------
    # 复杂度
    # ----------------------------------------------------------------

    def node_count(self) -> int:
        """节点数（复杂度度量）。"""
        count = 1
        for child in self.children:
            count += child.node_count()
        return count

    def depth(self) -> int:
        """树深度（根节点深度=1）。"""
        if not self.children:
            return 1
        return 1 + max(c.depth() for c in self.children)

    def complexity_score(self) -> float:
        """复杂度分数 = node_count/MAX_NODES ∈ [0,1]。"""
        return min(1.0, self.node_count() / MAX_NODES)

    # ----------------------------------------------------------------
    # 工具方法
    # ----------------------------------------------------------------

    def clone(self) -> ExprNode:
        """深拷贝。"""
        return deepcopy(self)

    def is_terminal(self) -> bool:
        """是否为终端节点（叶节点）。"""
        return not self.children

    def all_nodes(self) -> list[ExprNode]:
        """返回所有节点（含自身）的列表（前序遍历）。"""
        result = [self]
        for child in self.children:
            result.extend(child.all_nodes())
        return result

    def __repr__(self) -> str:
        return f"ExprNode({self.to_string()!r})"


# ---------------------------------------------------------------------------
# 节点求值实现
# ---------------------------------------------------------------------------


def _eval_node(node: ExprNode, data: pd.DataFrame) -> pd.Series:
    """递归求值。异常时返回全NaN Series。"""
    try:
        return _eval_node_unsafe(node, data)
    except Exception as e:
        logger.debug("ExprNode求值异常: %s -> %s", node.to_string(), e)
        return pd.Series(np.nan, index=data.index, dtype=float)


def _eval_node_unsafe(node: ExprNode, data: pd.DataFrame) -> pd.Series:
    """递归求值（不捕获异常）。"""
    op = node.op

    # 常数节点
    if op == "const":
        v = node.value if node.value is not None else 0.0
        return pd.Series(float(v), index=data.index, dtype=float)

    # 终端节点（数据字段）
    if not node.children:
        if op in data.columns:
            return data[op].astype(float)
        # 字段不存在，返回NaN
        logger.warning("字段 '%s' 不在data.columns中", op)
        return pd.Series(np.nan, index=data.index, dtype=float)

    # 求子节点值
    child_vals = [_eval_node(c, data) for c in node.children]

    w = node.window or 20

    # 时序算子
    if op == "ts_mean":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).mean()
    if op == "ts_std":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).std()
    if op == "ts_max":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).max()
    if op == "ts_min":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).min()
    if op == "ts_sum":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).sum()
    if op == "ts_rank":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).rank(pct=True)
    if op == "ts_skew":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).skew()
    if op == "ts_kurt":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).kurt()
    if op == "delay":
        return child_vals[0].shift(w)
    if op == "delta":
        return child_vals[0] - child_vals[0].shift(w)
    if op == "ts_pct":
        return child_vals[0].pct_change(periods=w)

    # NEW: ts_slope — 线性回归斜率 (OLS, FactorMiner)
    if op == "ts_slope":
        def _slope(s):
            x = np.arange(len(s), dtype=float)
            mask = np.isfinite(s.values)
            if mask.sum() < max(3, w // 2):
                return np.nan
            xm = x[mask]
            ym = s.values[mask].astype(float)
            mx, my = xm.mean(), ym.mean()
            denom = ((xm - mx) ** 2).sum()
            if denom < 1e-15:
                return np.nan
            return ((xm - mx) * (ym - my)).sum() / denom
        return child_vals[0].rolling(w, min_periods=max(3, w // 2)).apply(_slope, raw=False)

    # NEW: ts_rsquare — 线性回归R² (FactorMiner)
    if op == "ts_rsquare":
        def _rsquare(s):
            x = np.arange(len(s), dtype=float)
            mask = np.isfinite(s.values)
            if mask.sum() < max(3, w // 2):
                return np.nan
            xm = x[mask]
            ym = s.values[mask].astype(float)
            mx, my = xm.mean(), ym.mean()
            ss_tot = ((ym - my) ** 2).sum()
            if ss_tot < 1e-15:
                return np.nan
            denom = ((xm - mx) ** 2).sum()
            if denom < 1e-15:
                return np.nan
            slope = ((xm - mx) * (ym - my)).sum() / denom
            intercept = my - slope * mx
            ss_res = ((ym - (slope * xm + intercept)) ** 2).sum()
            return 1.0 - ss_res / ss_tot
        return child_vals[0].rolling(w, min_periods=max(3, w // 2)).apply(_rsquare, raw=False)

    # NEW: ts_decay_linear — 线性衰减加权mean (AlphaZero)
    if op == "ts_decay_linear":
        def _decay(arr):
            n = len(arr)
            mask = np.isfinite(arr)
            if mask.sum() < max(1, n // 2):
                return np.nan
            wt = np.arange(1, n + 1, dtype=float)
            wt[~mask] = 0.0
            wt_sum = wt.sum()
            if wt_sum < 1e-15:
                return np.nan
            return np.nansum(np.where(mask, arr, 0.0) * wt) / wt_sum
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).apply(_decay, raw=True)

    # NEW: ts_argmax — 最大值位置/window (Alpha158, 归一化到[0,1])
    if op == "ts_argmax":
        def _argmax(s):
            vals = s.values
            mask = np.isfinite(vals)
            if mask.sum() < max(1, w // 2):
                return np.nan
            return float(np.nanargmax(vals)) / (len(vals) - 1) if len(vals) > 1 else 0.5
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).apply(_argmax, raw=False)

    # NEW: ts_argmin — 最小值位置/window (Alpha158, 归一化到[0,1])
    if op == "ts_argmin":
        def _argmin(s):
            vals = s.values
            mask = np.isfinite(vals)
            if mask.sum() < max(1, w // 2):
                return np.nan
            return float(np.nanargmin(vals)) / (len(vals) - 1) if len(vals) > 1 else 0.5
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).apply(_argmin, raw=False)

    # 时序双目算子
    if op == "ts_corr":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).corr(child_vals[1])
    if op == "ts_cov":
        return child_vals[0].rolling(w, min_periods=max(1, w // 2)).cov(child_vals[1])

    # 截面算子
    if op == "cs_rank":
        return child_vals[0].rank(pct=True)
    if op == "cs_zscore":
        mu = child_vals[0].mean()
        sigma = child_vals[0].std()
        if sigma == 0 or pd.isna(sigma):
            return pd.Series(0.0, index=data.index)
        return (child_vals[0] - mu) / sigma
    if op == "cs_demean":
        mu = child_vals[0].mean()
        return child_vals[0] - mu

    # 单目数学算子
    if op == "log":
        return np.log(child_vals[0].abs().clip(lower=1e-10))
    if op == "abs":
        return child_vals[0].abs()
    if op == "sign":
        return np.sign(child_vals[0])
    if op == "neg":
        return -child_vals[0]
    if op == "inv":
        return child_vals[0].replace(0, np.nan).rdiv(1.0)
    if op == "sqrt":
        return child_vals[0].abs().pow(0.5)

    # 双目数学算子
    if op == "add":
        return child_vals[0] + child_vals[1]
    if op == "sub":
        return child_vals[0] - child_vals[1]
    if op == "mul":
        return child_vals[0] * child_vals[1]
    if op == "div":
        denom = child_vals[1].replace(0, np.nan)
        return child_vals[0] / denom
    if op == "max":
        return pd.concat([child_vals[0], child_vals[1]], axis=1).max(axis=1)
    if op == "min":
        return pd.concat([child_vals[0], child_vals[1]], axis=1).min(axis=1)

    # NEW: power — x^n (AlphaZero)
    if op == "power":
        # child[1] 作为指数, 通常为常数(0.5/2/3)或另一个表达式
        base = child_vals[0].abs().clip(lower=1e-10)
        exp = child_vals[1].clip(-3, 3)  # 限制指数范围防止溢出
        return base.pow(exp)

    # NEW: ifelse — if(cond>0, x, y) (FactorMiner)
    if op == "ifelse":
        if len(child_vals) >= 3:
            cond = child_vals[0]
            return child_vals[1].where(cond > 0, child_vals[2])
        raise ValueError("ifelse需要3个参数")

    raise ValueError(f"未知算子: {op}")


# ---------------------------------------------------------------------------
# FactorDSL — 核心类
# ---------------------------------------------------------------------------


class FactorDSL:
    """因子表达式语言 — GP的搜索空间定义。

    使用方法:
        dsl = FactorDSL()
        tree = dsl.random_tree(max_depth=3)
        expr_str = tree.to_string()          # "ts_mean(cs_rank(close), 20)"
        tree2 = dsl.from_string(expr_str)    # 反序列化
        valid, msg = dsl.validate(tree)      # 量纲/深度/节点数检查
        template, params = dsl.extract_template(tree)  # 逻辑/参数分离
    """

    def __init__(
        self,
        max_depth: int = MAX_DEPTH,
        max_nodes: int = MAX_NODES,
        seed: int | None = None,
    ) -> None:
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self._rng = random.Random(seed)

    # ----------------------------------------------------------------
    # 随机树生成
    # ----------------------------------------------------------------

    def random_tree(self, max_depth: int | None = None, current_depth: int = 0) -> ExprNode:
        """随机生成合法表达式树（grow方法 + 量纲约束重试）。

        Args:
            max_depth: 最大深度，None使用实例配置。
            current_depth: 当前递归深度（内部使用）。

        Returns:
            ExprNode: 合法的表达式树。
        """
        # 顶层调用 (current_depth==0) 加量纲重试
        if current_depth == 0:
            for _ in range(10):
                tree = self._random_tree_once(max_depth, 0)
                dim_ok, _ = check_dimensional_validity(tree)
                if dim_ok:
                    return tree
            # 10次失败 → 返回安全的简单树
            return self._random_terminal()
        return self._random_tree_once(max_depth, current_depth)

    def _random_tree_once(self, max_depth: int | None = None, current_depth: int = 0) -> ExprNode:
        """单次随机树生成 (无量纲重试)。"""
        eff_depth = max_depth if max_depth is not None else self.max_depth

        # 强制叶节点的情况：已到最大深度
        if current_depth >= eff_depth - 1:
            return self._random_terminal()

        # 以一定概率选叶节点（grow方法，避免所有树都很深）
        terminal_prob = 0.3 + 0.2 * current_depth  # 越深越倾向于叶节点
        if self._rng.random() < terminal_prob:
            return self._random_terminal()

        # 随机选算子
        return self._random_op_node(eff_depth, current_depth)

    def _random_terminal(self) -> ExprNode:
        """随机生成终端节点（数据字段）。"""
        field_name = self._rng.choice(TERMINALS)
        return ExprNode(op=field_name)

    def _random_op_node(self, max_depth: int, current_depth: int) -> ExprNode:
        """随机选算子并生成子节点。"""
        # 权重分配：时序算子最常见
        op_pools = [
            (list(TS_OPS.keys()), 4),
            (list(TS_BINARY_OPS.keys()), 1),
            (list(CS_OPS.keys()), 2),
            (list(UNARY_OPS.keys()), 2),
            (list(BINARY_OPS.keys()), 2),
            (list(TERNARY_OPS.keys()), 1),  # ifelse低权重
        ]
        weighted_ops: list[str] = []
        for ops, weight in op_pools:
            weighted_ops.extend(ops * weight)

        op = self._rng.choice(weighted_ops)
        op_info = ALL_OPS[op]
        n_args = op_info["args"]
        op_type = op_info["type"]

        children = [
            self.random_tree(max_depth, current_depth + 1)
            for _ in range(n_args)
        ]

        window = None
        if op_type in (OpType.TS, OpType.TS_BINARY):
            windows = op_info.get("windows", [5, 10, 20])
            window = self._rng.choice(windows)

        return ExprNode(op=op, children=children, window=window)

    # ----------------------------------------------------------------
    # 从种子因子生成变体
    # ----------------------------------------------------------------

    def seed_to_variants(
        self,
        seed_name: str,
        seed_expr: str,
        n_variants: int = 8,
    ) -> list[ExprNode]:
        """从种子因子表达式生成多个变体。

        变体策略（GP_CLOSED_LOOP_DESIGN §3.3）:
          1. 原始种子不变
          2. 窗口变异: 改时序算子窗口
          3. 字段替换: 替换数据字段
          4. 外层算子包装: cs_rank/log/neg
          5. 随机子树替换

        Args:
            seed_name: 种子因子名称。
            seed_expr: 种子因子DSL表达式字符串。
            n_variants: 期望生成的变体数量。

        Returns:
            ExprNode列表（含原始种子）。
        """
        try:
            base = self.from_string(seed_expr)
        except ValueError:
            logger.warning("无法解析种子因子 %s: %s", seed_name, seed_expr)
            return [self.random_tree()]

        variants: list[ExprNode] = [base.clone()]

        # 策略2: 窗口变异
        window_variants = self._window_mutations(base)
        variants.extend(window_variants)

        # 策略3: 字段替换
        field_variants = self._field_substitutions(base)
        variants.extend(field_variants)

        # 策略4: 外层算子包装
        wrapper_variants = self._outer_wrappers(base)
        variants.extend(wrapper_variants)

        # 截断或补充
        if len(variants) > n_variants:
            variants = variants[:n_variants]
        while len(variants) < n_variants:
            # 随机子树替换填充
            v = base.clone()
            v = self._random_subtree_replace(v)
            variants.append(v)

        return variants

    def _window_mutations(self, node: ExprNode) -> list[ExprNode]:
        """改变时序算子的窗口参数。"""
        variants = []
        for alt_window in [5, 10, 40, 60]:
            v = node.clone()
            self._mutate_windows(v, alt_window)
            variants.append(v)
        return variants

    def _mutate_windows(self, node: ExprNode, new_window: int) -> None:
        """递归地将所有时序算子的窗口改为new_window。"""
        op_info = ALL_OPS.get(node.op, {})
        if op_info.get("type") in (OpType.TS, OpType.TS_BINARY) and node.window is not None:
            # 确保new_window在合法范围内
            valid_windows = op_info.get("windows", [5, 10, 20, 60])
            closest = min(valid_windows, key=lambda w: abs(w - new_window))
            node.window = closest
        for child in node.children:
            self._mutate_windows(child, new_window)

    def _field_substitutions(self, node: ExprNode) -> list[ExprNode]:
        """替换数据字段（如close→open/high/low/vwap）。"""
        variants = []
        substitutions = [
            ("close", ["open", "high", "low", "vwap"]),
            ("returns", ["close_open", "high_low"]),
            ("amount", ["volume"]),
        ]
        for src_field, tgt_fields in substitutions:
            for tgt in tgt_fields:
                v = node.clone()
                if self._replace_terminal(v, src_field, tgt):
                    variants.append(v)
        return variants

    def _replace_terminal(self, node: ExprNode, src: str, dst: str) -> bool:
        """递归替换终端节点，返回是否发生了替换。"""
        replaced = False
        if node.is_terminal() and node.op == src:
            node.op = dst
            return True
        for child in node.children:
            if self._replace_terminal(child, src, dst):
                replaced = True
                break  # 只替换第一个匹配
        return replaced

    def _outer_wrappers(self, node: ExprNode) -> list[ExprNode]:
        """在根节点外包裹算子。"""
        wrappers = [
            ("cs_rank", None),
            ("neg", None),
            ("ts_rank", 20),
        ]
        variants = []
        for wrapper_op, window in wrappers:
            if node.depth() < self.max_depth:
                v = ExprNode(op=wrapper_op, children=[node.clone()], window=window)
                variants.append(v)
        return variants

    def _random_subtree_replace(self, node: ExprNode) -> ExprNode:
        """随机替换一个内部子树为新的随机树。"""
        all_nodes = node.all_nodes()
        internal = [n for n in all_nodes if n.children]
        if not internal:
            return node

        target = self._rng.choice(internal)
        child_idx = self._rng.randrange(len(target.children))
        new_subtree = self.random_tree(max_depth=self.max_depth - target.depth())
        target.children[child_idx] = new_subtree
        return node

    # ----------------------------------------------------------------
    # 序列化 / 反序列化
    # ----------------------------------------------------------------

    def from_string(self, expr: str) -> ExprNode:
        """从字符串解析表达式树。

        支持格式:
          - "ts_mean(close, 20)"
          - "div(abs(returns), amount)"
          - "inv(pb)"
          - "neg(ts_pct(close, 20))"
          - "close" (终端)

        Args:
            expr: DSL表达式字符串。

        Returns:
            ExprNode: 解析结果。

        Raises:
            ValueError: 解析失败。
        """
        expr = expr.strip()
        if not expr:
            raise ValueError("空表达式")
        parser = _DSLParser(expr)
        return parser.parse()

    # ----------------------------------------------------------------
    # 验证
    # ----------------------------------------------------------------

    def validate(self, tree: ExprNode) -> tuple[bool, str]:
        """验证表达式合法性（量纲/深度/节点数）。

        Returns:
            (is_valid, reason): is_valid=False时reason说明原因。
        """
        # 深度检查
        d = tree.depth()
        if d > self.max_depth:
            return False, f"树深度={d}超过上限{self.max_depth}"

        # 节点数检查
        n = tree.node_count()
        if n > self.max_nodes:
            return False, f"节点数={n}超过上限{self.max_nodes}"

        # 量纲检查：终端字段+算子名必须合法（QA P2 bug修复）
        for node in tree.all_nodes():
            if node.is_terminal() and node.op not in TERMINALS and node.op != "const":
                return False, f"未知字段: {node.op}"
            if not node.is_terminal() and node.op not in ALL_OPS and node.op != "const":
                return False, f"未知算子: {node.op}"

        # 窗口参数检查
        for node in tree.all_nodes():
            if node.op in ALL_OPS:
                op_info = ALL_OPS[node.op]
                op_type = op_info.get("type")
                if op_type in (OpType.TS, OpType.TS_BINARY) and (node.window is None or node.window <= 0):
                    return False, f"时序算子 {node.op} 缺少有效窗口参数"

        # 量纲约束检查 (AlphaZero正则化进化)
        dim_ok, dim_reason = check_dimensional_validity(tree)
        if not dim_ok:
            return False, f"量纲违规: {dim_reason}"

        return True, "OK"

    # ----------------------------------------------------------------
    # 逻辑/参数分离（R2研究核心改进）
    # ----------------------------------------------------------------

    def extract_template(
        self,
        tree: ExprNode,
    ) -> tuple[ExprNode, dict[str, int]]:
        """提取结构模板 + 参数槽位（逻辑/参数分离）。

        输入: ts_mean(cs_rank(close), 20)
        输出: template=ts_mean(cs_rank(close), W0), params={W0: 20}

        Args:
            tree: 表达式树。

        Returns:
            (template, params): template是克隆树（窗口改为槽位索引），
                                params是 {slot_name: window_value} 映射。
        """
        template = tree.clone()
        params: dict[str, int] = {}
        slot_idx = [0]  # 用列表包装以便嵌套函数修改

        def _extract(node: ExprNode) -> None:
            if node.window is not None:
                slot_name = f"w{slot_idx[0]}"
                params[slot_name] = node.window
                node.window = slot_idx[0]  # 用槽位索引代替实际窗口值
                slot_idx[0] += 1
            for child in node.children:
                _extract(child)

        _extract(template)
        return template, params

    def apply_params(
        self,
        template: ExprNode,
        params: dict[str, int],
    ) -> ExprNode:
        """将参数应用到模板，生成完整表达式树。

        Args:
            template: 由extract_template返回的模板（窗口为槽位索引）。
            params: {slot_name: window_value} 映射，如 {"w0": 20, "w1": 10}。

        Returns:
            ExprNode: 窗口值已填入的完整树。
        """
        result = template.clone()
        slot_idx = [0]

        def _apply(node: ExprNode) -> None:
            if node.window is not None:
                slot_name = f"w{slot_idx[0]}"
                node.window = params.get(slot_name, node.window)
                slot_idx[0] += 1
            for child in node.children:
                _apply(child)

        _apply(result)
        return result

    def get_param_search_space(
        self,
        template: ExprNode,
        original_params: dict[str, int],
    ) -> dict[str, list[int]]:
        """返回模板的参数搜索空间（每个槽位的候选窗口列表）。

        用于Optuna参数优化的搜索范围定义。

        Args:
            template: 由extract_template返回的模板。
            original_params: 原始参数值 {slot_name: value}。

        Returns:
            {slot_name: [候选窗口列表]}
        """
        search_space: dict[str, list[int]] = {}

        def _collect(node: ExprNode) -> None:
            if node.window is not None:
                slot_name = f"w{node.window}"  # 此时window存的是槽位索引
                # 获取该算子的合法窗口列表
                op_info = ALL_OPS.get(node.op, {})
                valid_windows = op_info.get("windows", [5, 10, 20, 60])
                search_space[slot_name] = valid_windows
            for child in node.children:
                _collect(child)

        _collect(template)
        return search_space

    # ----------------------------------------------------------------
    # 遗传算子（供GP引擎调用）
    # ----------------------------------------------------------------

    def crossover(
        self,
        tree_a: ExprNode,
        tree_b: ExprNode,
    ) -> tuple[ExprNode, ExprNode]:
        """子树交叉（标准GP交叉算子 + 量纲约束重试）。

        随机选择两个树中的内部节点，交换对应子树。
        量纲不合规时最多重试5次。

        Returns:
            (child_a, child_b): 交叉后的两个后代（深拷贝）。
        """
        for _ in range(5):
            a = tree_a.clone()
            b = tree_b.clone()

            nodes_a = [n for n in a.all_nodes() if n.children]
            nodes_b = [n for n in b.all_nodes() if n.children]

            if not nodes_a or not nodes_b:
                return a, b

            na = self._rng.choice(nodes_a)
            nb = self._rng.choice(nodes_b)

            idx_a = self._rng.randrange(len(na.children))
            idx_b = self._rng.randrange(len(nb.children))

            subtree_a = na.children[idx_a]
            subtree_b = nb.children[idx_b]

            na.children[idx_a] = subtree_b
            nb.children[idx_b] = subtree_a

            # 验证深度
            if a.depth() > self.max_depth or b.depth() > self.max_depth:
                continue

            # 验证量纲
            dim_ok_a, _ = check_dimensional_validity(a)
            dim_ok_b, _ = check_dimensional_validity(b)
            if dim_ok_a and dim_ok_b:
                return a, b

        # 重试失败 → 返回原树clone
        return tree_a.clone(), tree_b.clone()

    def mutate(self, tree: ExprNode, mutation_rate: float = 0.3) -> ExprNode:
        """树变异（随机选一种变异策略）。

        变异策略（按概率选择）:
          40% — 窗口变异（改时序算子窗口）
          30% — 字段替换（改终端字段）
          20% — 子树替换（随机生成新子树）
          10% — 外层包装（添加新的外层算子）

        Args:
            tree: 输入树（不修改原树）。
            mutation_rate: 每个节点的变异概率（子树替换策略用）。

        Returns:
            ExprNode: 变异后的新树。
        """
        result = tree.clone()
        r = self._rng.random()

        if r < 0.40:
            # 窗口变异
            ts_nodes = [n for n in result.all_nodes() if n.op in TS_OPS or n.op in TS_BINARY_OPS]
            if ts_nodes:
                node = self._rng.choice(ts_nodes)
                op_info = ALL_OPS.get(node.op, {})
                valid_windows = op_info.get("windows", [5, 10, 20])
                node.window = self._rng.choice(valid_windows)
        elif r < 0.70:
            # 字段替换
            terminals = [n for n in result.all_nodes() if n.is_terminal() and n.op in TERMINALS]
            if terminals:
                node = self._rng.choice(terminals)
                node.op = self._rng.choice(TERMINALS)
        elif r < 0.90:
            # 子树替换
            result = self._random_subtree_replace(result)
        else:
            # 外层包装（仅在深度允许时）
            if result.depth() < self.max_depth:
                wrapper = self._rng.choice(["cs_rank", "neg", "abs"])
                result = ExprNode(op=wrapper, children=[result])

        # 确保变异后仍合法
        if result.depth() > self.max_depth or result.node_count() > self.max_nodes:
            return tree.clone()

        return result

    def correlated_mutate(self, tree: ExprNode, max_retries: int = 5) -> ExprNode:
        """关联变异 — 结构感知, 保持父代有效子树 (AlphaZero 10x效率)。

        策略:
          50% — 子树保留变异: 保留一侧子树, 只变异另一侧
          20% — 窗口邻域变异: window ±1 级 (5→10, 20→10或60)
          20% — 同量纲字段替换: 只在同DimType终端间替换
          10% — 外层包裹: 添加cs_rank/ts_rank外层

        含量纲检查: 变异结果不合规时重试, 最多max_retries次后回退原树。
        """
        for _attempt in range(max_retries):
            result = self._correlated_mutate_once(tree)
            dim_ok, _ = check_dimensional_validity(result)
            if dim_ok:
                return result
        # 所有重试失败, 返回原树clone
        return tree.clone()

    def _correlated_mutate_once(self, tree: ExprNode) -> ExprNode:
        """单次关联变异 (内部方法)。"""
        result = tree.clone()
        r = self._rng.random()

        if r < 0.50:
            # 子树保留变异: 选一个双目节点, 保留一侧, 另一侧随机重生
            binary_nodes = [
                n for n in result.all_nodes()
                if len(n.children) >= 2
            ]
            if binary_nodes:
                node = self._rng.choice(binary_nodes)
                # 随机选要替换的子树侧
                side = self._rng.randrange(len(node.children))
                remaining_depth = self.max_depth - node.depth()
                if remaining_depth > 0:
                    node.children[side] = self.random_tree(
                        max_depth=max(2, remaining_depth), current_depth=0
                    )
            else:
                # fallback: 普通子树替换
                result = self._random_subtree_replace(result)

        elif r < 0.70:
            # 窗口邻域变异: 只移动±1级, 非完全随机
            ts_nodes = [
                n for n in result.all_nodes()
                if n.op in TS_OPS or n.op in TS_BINARY_OPS
            ]
            if ts_nodes:
                node = self._rng.choice(ts_nodes)
                op_info = ALL_OPS.get(node.op, {})
                valid_windows = sorted(op_info.get("windows", [5, 10, 20]))
                if node.window in valid_windows:
                    idx = valid_windows.index(node.window)
                    # 邻域: ±1 步
                    neighbors = []
                    if idx > 0:
                        neighbors.append(valid_windows[idx - 1])
                    if idx < len(valid_windows) - 1:
                        neighbors.append(valid_windows[idx + 1])
                    if neighbors:
                        node.window = self._rng.choice(neighbors)

        elif r < 0.90:
            # 同量纲字段替换: 只在同DimType终端间替换
            terminals = [
                n for n in result.all_nodes()
                if n.is_terminal() and n.op in TERMINAL_DIM
            ]
            if terminals:
                node = self._rng.choice(terminals)
                dim = TERMINAL_DIM[node.op]
                candidates = [
                    t for t in DIM_GROUPS.get(dim, [])
                    if t != node.op
                ]
                if candidates:
                    node.op = self._rng.choice(candidates)

        else:
            # 外层包裹
            if result.depth() < self.max_depth:
                wrapper = self._rng.choice(["cs_rank", "neg", "ts_rank"])
                window = 20 if wrapper == "ts_rank" else None
                result = ExprNode(op=wrapper, children=[result], window=window)

        # 合法性检查
        if result.depth() > self.max_depth or result.node_count() > self.max_nodes:
            return tree.clone()

        return result


# ---------------------------------------------------------------------------
# DSL解析器
# ---------------------------------------------------------------------------


class _DSLParser:
    """简单递归下降解析器，解析DSL表达式字符串。

    支持的格式:
      - terminal: close / returns / pb
      - unary_op(arg): log(close), cs_rank(returns)
      - ts_op(arg, window): ts_mean(close, 20)
      - ts_binary_op(arg1, arg2, window): ts_corr(close, volume, 20)
      - binary_op(arg1, arg2): div(abs(returns), amount)
    """

    def __init__(self, expr: str) -> None:
        self.expr = expr.strip()
        self.pos = 0

    def parse(self) -> ExprNode:
        node = self._parse_expr()
        self._skip_whitespace()
        if self.pos < len(self.expr):
            raise ValueError(
                f"解析未完成，剩余: {self.expr[self.pos:]!r}"
            )
        return node

    def _parse_expr(self) -> ExprNode:
        self._skip_whitespace()
        name = self._parse_name()
        self._skip_whitespace()

        # 有括号 → 函数调用
        if self.pos < len(self.expr) and self.expr[self.pos] == "(":
            return self._parse_call(name)

        # 没有括号 → 终端节点或常数
        try:
            v = float(name)
            return ExprNode(op="const", value=v)
        except ValueError:
            pass

        if name in TERMINALS:
            return ExprNode(op=name)

        # 可能是未知字段（宽松处理，允许）
        logger.debug("未识别的终端名称: %s", name)
        return ExprNode(op=name)

    def _parse_call(self, op: str) -> ExprNode:
        """解析函数调用 op(arg1, arg2, ...)。"""
        self._expect("(")
        args: list[ExprNode | int | float] = []

        while True:
            self._skip_whitespace()
            if self.pos < len(self.expr) and self.expr[self.pos] == ")":
                break

            # 尝试解析数值参数（如窗口期 20）
            num = self._try_parse_number()
            if num is not None:
                args.append(num)
            else:
                args.append(self._parse_expr())

            self._skip_whitespace()
            if self.pos < len(self.expr) and self.expr[self.pos] == ",":
                self.pos += 1

        self._expect(")")

        # 提取窗口参数（最后一个数值参数）
        window: int | None = None
        expr_args: list[ExprNode] = []

        for a in args:
            if isinstance(a, (int, float)):
                window = int(a)
            elif isinstance(a, ExprNode):
                expr_args.append(a)

        return ExprNode(op=op, children=expr_args, window=window)

    def _parse_name(self) -> str:
        """解析标识符（字母/数字/下划线）。"""
        start = self.pos
        while self.pos < len(self.expr) and (
            self.expr[self.pos].isalnum() or self.expr[self.pos] in "_."
        ):
            self.pos += 1
        if self.pos == start:
            raise ValueError(f"期望标识符，位置{self.pos}: {self.expr[self.pos:self.pos+10]!r}")
        return self.expr[start:self.pos]

    def _try_parse_number(self) -> float | None:
        """尝试解析数值，失败返回None（不移动pos）。"""
        self._skip_whitespace()
        start = self.pos
        has_digit = False

        if self.pos < len(self.expr) and self.expr[self.pos] in "+-":
            self.pos += 1

        while self.pos < len(self.expr) and self.expr[self.pos].isdigit():
            has_digit = True
            self.pos += 1

        if self.pos < len(self.expr) and self.expr[self.pos] == ".":
            self.pos += 1
            while self.pos < len(self.expr) and self.expr[self.pos].isdigit():
                has_digit = True
                self.pos += 1

        if has_digit:
            return float(self.expr[start:self.pos])

        self.pos = start
        return None

    def _expect(self, char: str) -> None:
        """期望特定字符，不匹配则raise。"""
        self._skip_whitespace()
        if self.pos >= len(self.expr) or self.expr[self.pos] != char:
            ctx = self.expr[self.pos:self.pos+10] if self.pos < len(self.expr) else "<EOF>"
            raise ValueError(f"期望 {char!r}，得到 {ctx!r}，位置{self.pos}")
        self.pos += 1

    def _skip_whitespace(self) -> None:
        while self.pos < len(self.expr) and self.expr[self.pos] in " \t\n\r":
            self.pos += 1


# ---------------------------------------------------------------------------
# 便捷工具函数
# ---------------------------------------------------------------------------


def expr_to_string(tree: ExprNode) -> str:
    """ExprNode → 字符串（便捷封装）。"""
    return tree.to_string()


def string_to_expr(expr: str) -> ExprNode:
    """字符串 → ExprNode（便捷封装）。"""
    dsl = FactorDSL()
    return dsl.from_string(expr)


def get_seed_trees() -> dict[str, ExprNode]:
    """返回v1.1的5个种子因子的ExprNode字典。

    Returns:
        {factor_name: ExprNode}
    """
    dsl = FactorDSL()
    result: dict[str, ExprNode] = {}
    for name, expr in SEED_FACTORS.items():
        try:
            result[name] = dsl.from_string(expr)
        except ValueError as e:
            logger.error("种子因子 %s 解析失败: %s", name, e)
    return result
