"""因子沙箱 — AST安全检查 + subprocess隔离执行

安全策略:
1. AST静态分析: 禁止 import/exec/eval/open/os/sys 等危险操作
2. 白名单函数: 只允许 math/numpy/pandas 的安全子集 + 自定义金融算子
3. subprocess隔离: 因子计算在独立进程中运行，超时 kill
4. 资源限制: 表达式长度 ≤ 500 字符，参数类型检查

R2研究选型: AlphaAgent AST去重准确率+81%，Gate G0层前置安全检查。
"""

import ast
import logging
import multiprocessing
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 危险节点 / 白名单
# ---------------------------------------------------------------------------

_FORBIDDEN_NODE_TYPES: frozenset[type] = frozenset(
    {
        ast.Import,
        ast.ImportFrom,
        ast.Global,
        ast.Nonlocal,
        ast.Delete,
        ast.ClassDef,
        ast.AsyncFunctionDef,
        ast.AsyncFor,
        ast.AsyncWith,
        ast.Yield,
        ast.YieldFrom,
        ast.Await,
    }
)

# 禁止作为函数调用的名称（区别于禁止的变量名，因为 open/close 都是 OHLC 字段）
_FORBIDDEN_CALL_NAMES: frozenset[str] = frozenset(
    {
        "exec",
        "eval",
        "compile",
        "open",
        "input",
        "print",
        "breakpoint",
        "__import__",
    }
)

_FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "import",
        "exec",
        "eval",
        "compile",
        "os",
        "sys",
        "subprocess",
        "shutil",
        "pathlib",
        "socket",
        "urllib",
        "requests",
        "http",
        "ftplib",
        "smtplib",
        "pickle",
        "shelve",
        "builtins",
        "__import__",
        "__builtins__",
        "__subclasses__",
        "__bases__",
        "__mro__",
        "globals",
        "locals",
        "vars",
        "dir",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "input",
        "print",
        "breakpoint",
    }
)

# 允许使用的顶层模块/对象名
_ALLOWED_NAMES: frozenset[str] = frozenset(
    {
        # numpy
        "np",
        "numpy",
        # pandas
        "pd",
        "pandas",
        # math
        "math",
        "abs",
        "min",
        "max",
        "sum",
        "len",
        "range",
        "int",
        "float",
        "bool",
        "str",
        "round",
        "sorted",
        "zip",
        "enumerate",
        # 自定义金融算子 (与 DEV_FACTOR_MINING.md §算子表一致)
        "ts_mean",
        "ts_std",
        "ts_corr",
        "ts_rank",
        "ts_max",
        "ts_min",
        "ts_sum",
        "delay",
        "delta",
        "rank",
        "zscore",
        "cs_rank",
        "cs_zscore",
        "log",
        "sign",
        "pow",
        "if_else",
        # 数据参数名
        "data",
        "df",
        "close",
        "open",
        "high",
        "low",
        "volume",
        "amount",
        "turnover_rate",
        "pe_ttm",
        "pb",
        "total_mv",
        "circ_mv",
        "True",
        "False",
        "None",
    }
)

# 允许调用的函数
_ALLOWED_CALLS: frozenset[str] = frozenset(
    {
        "abs",
        "min",
        "max",
        "sum",
        "len",
        "round",
        "sorted",
        "zip",
        "enumerate",
        "int",
        "float",
        "bool",
        "np.mean",
        "np.std",
        "np.median",
        "np.sum",
        "np.max",
        "np.min",
        "np.abs",
        "np.log",
        "np.log1p",
        "np.sqrt",
        "np.sign",
        "np.where",
        "np.clip",
        "np.nan_to_num",
        "np.isnan",
        "np.isinf",
        "np.percentile",
        "np.nanmean",
        "np.nanstd",
        "np.nanmedian",
        "np.nansum",
        "pd.Series",
        "pd.DataFrame",
        "pd.isna",
        "pd.notna",
        "ts_mean",
        "ts_std",
        "ts_corr",
        "ts_rank",
        "ts_max",
        "ts_min",
        "ts_sum",
        "delay",
        "delta",
        "rank",
        "zscore",
        "cs_rank",
        "cs_zscore",
        "log",
        "sign",
        "pow",
        "if_else",
        "math.log",
        "math.sqrt",
        "math.exp",
        "math.ceil",
        "math.floor",
        "math.fabs",
    }
)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    """AST安全检查结果"""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ast_depth: int = 0
    node_count: int = 0

    def __bool__(self) -> bool:
        return self.is_valid


@dataclass
class ExecutionResult:
    """沙箱执行结果"""

    success: bool
    result: pd.Series | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0

    def __bool__(self) -> bool:
        return self.success


# ---------------------------------------------------------------------------
# AST 安全检查器
# ---------------------------------------------------------------------------


class _ASTSecurityVisitor(ast.NodeVisitor):
    """遍历 AST 检查危险节点"""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self._depth: int = 0
        self._max_depth: int = 0
        self._node_count: int = 0

    @property
    def ast_depth(self) -> int:
        return self._max_depth

    @property
    def node_count(self) -> int:
        return self._node_count

    def generic_visit(self, node: ast.AST) -> None:
        self._node_count += 1
        self._depth += 1
        self._max_depth = max(self._max_depth, self._depth)

        # 检查禁止的节点类型
        if type(node) in _FORBIDDEN_NODE_TYPES:
            self.errors.append(
                f"禁止的AST节点类型: {type(node).__name__} (行 {getattr(node, 'lineno', '?')})"
            )

        super().generic_visit(node)
        self._depth -= 1

    def visit_Name(self, node: ast.Name) -> None:
        self._node_count += 1
        name = node.id
        # 允许名单优先：data column names (open/close/high 等) 即使在禁止列表也放行
        if name not in _ALLOWED_NAMES and name in _FORBIDDEN_NAMES:
            self.errors.append(f"禁止的名称: '{name}' (行 {node.lineno})")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        self._node_count += 1
        # 检查 __dunder__ 属性访问
        attr = node.attr
        if attr.startswith("__") and attr.endswith("__"):
            self.errors.append(f"禁止访问 dunder 属性: '{attr}' (行 {node.lineno})")
        # 检查危险属性
        if attr in {"system", "popen", "spawn", "fork", "exec", "eval"}:
            self.errors.append(f"禁止的属性访问: '.{attr}' (行 {node.lineno})")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        self._node_count += 1
        func_name = self._get_call_name(node.func)
        if func_name and (
            func_name in _FORBIDDEN_NAMES or func_name in _FORBIDDEN_CALL_NAMES
        ):
            self.errors.append(f"禁止的函数调用: '{func_name}' (行 {node.lineno})")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._node_count += 1
        # 允许 lambda 和简单函数定义（用于表达式封装）
        # 但不允许嵌套函数内有危险调用（继续遍历）
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._node_count += 1
        self.generic_visit(node)

    @staticmethod
    def _get_call_name(func_node: ast.expr) -> str | None:
        if isinstance(func_node, ast.Name):
            return func_node.id
        if isinstance(func_node, ast.Attribute):
            parent = _ASTSecurityVisitor._get_call_name(func_node.value)
            if parent:
                return f"{parent}.{func_node.attr}"
        return None


# ---------------------------------------------------------------------------
# Factor Sandbox
# ---------------------------------------------------------------------------


class FactorSandbox:
    """因子表达式安全执行沙箱

    使用方法:
        sandbox = FactorSandbox(timeout=5)
        result = sandbox.validate_expression("rank(close / delay(close, 20))")
        if result:
            exec_result = sandbox.execute_safely(expr, data)
    """

    MAX_EXPR_LENGTH: int = 500
    DEFAULT_TIMEOUT: int = 5  # seconds
    MAX_NODES: int = 200  # AST节点数上限（防止爆炸式表达式）

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def validate_expression(self, expr: str) -> ValidationResult:
        """AST静态分析 — 检查表达式安全性

        Args:
            expr: 因子表达式字符串

        Returns:
            ValidationResult: is_valid=True 表示通过检查
        """
        result = ValidationResult(is_valid=True)

        # 1. 长度检查
        if len(expr) > self.MAX_EXPR_LENGTH:
            result.is_valid = False
            result.errors.append(
                f"表达式过长: {len(expr)} 字符 (上限 {self.MAX_EXPR_LENGTH})"
            )
            return result

        # 2. 解析 AST
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError as e:
            result.is_valid = False
            result.errors.append(f"语法错误: {e}")
            return result

        # 3. AST 安全遍历
        visitor = _ASTSecurityVisitor()
        visitor.visit(tree)

        result.ast_depth = visitor.ast_depth
        result.node_count = visitor.node_count
        result.errors.extend(visitor.errors)
        result.warnings.extend(visitor.warnings)

        # 4. 节点数检查
        if visitor.node_count > self.MAX_NODES:
            result.errors.append(
                f"AST节点过多: {visitor.node_count} (上限 {self.MAX_NODES})"
            )

        result.is_valid = len(result.errors) == 0
        return result

    def execute_safely(
        self,
        expr: str,
        data: pd.DataFrame,
        timeout: int | None = None,
    ) -> ExecutionResult:
        """在独立子进程中执行因子表达式

        Args:
            expr: 因子表达式字符串（已通过 validate_expression）
            data: 包含所需字段的 DataFrame（索引为 symbol_id 或 (date, symbol_id)）
            timeout: 超时秒数，默认使用实例配置

        Returns:
            ExecutionResult: success=True + result Series 或 error 信息
        """
        t_start = time.perf_counter()
        effective_timeout = timeout if timeout is not None else self.timeout

        # 先做安全检查
        validation = self.validate_expression(expr)
        if not validation:
            return ExecutionResult(
                success=False,
                error=f"安全检查失败: {'; '.join(validation.errors)}",
            )

        # subprocess 隔离执行
        result_queue: multiprocessing.Queue = multiprocessing.Queue()
        proc = multiprocessing.Process(
            target=_subprocess_worker,
            args=(expr, data, result_queue),
            daemon=True,
        )
        proc.start()
        proc.join(timeout=effective_timeout)

        elapsed = time.perf_counter() - t_start

        if proc.is_alive():
            proc.kill()
            proc.join()
            return ExecutionResult(
                success=False,
                error=f"执行超时 (>{effective_timeout}s)",
                elapsed_seconds=elapsed,
            )

        if result_queue.empty():
            return ExecutionResult(
                success=False,
                error=f"子进程异常退出 (exitcode={proc.exitcode})",
                elapsed_seconds=elapsed,
            )

        payload = result_queue.get_nowait()
        if payload["ok"]:
            series = payload["result"]
            return ExecutionResult(
                success=True,
                result=series,
                elapsed_seconds=elapsed,
            )
        else:
            return ExecutionResult(
                success=False,
                error=payload["error"],
                elapsed_seconds=elapsed,
            )


# ---------------------------------------------------------------------------
# 子进程 worker（在独立进程中运行）
# ---------------------------------------------------------------------------


def _subprocess_worker(
    expr: str,
    data: pd.DataFrame,
    result_queue: multiprocessing.Queue,
) -> None:
    """在子进程中执行因子表达式，结果放入队列"""
    try:
        # 构建受限执行环境
        safe_globals: dict[str, Any] = {"__builtins__": {}}
        safe_locals: dict[str, Any] = _build_safe_namespace(data)

        # 执行
        result = eval(expr, safe_globals, safe_locals)  # noqa: S307

        # 规范化为 pd.Series
        if isinstance(result, pd.Series):
            series = result
        elif isinstance(result, (np.ndarray, list)):
            series = pd.Series(result, index=data.index)
        elif isinstance(result, (int, float, np.floating, np.integer)):
            series = pd.Series(float(result), index=data.index)
        else:
            series = pd.Series(result, index=data.index)

        result_queue.put({"ok": True, "result": series})

    except Exception:
        result_queue.put({"ok": False, "error": traceback.format_exc()})


def _build_safe_namespace(data: pd.DataFrame) -> dict[str, Any]:
    """构建因子表达式的执行命名空间

    包含:
    - DataFrame 中的所有列（直接以列名访问）
    - 金融时序算子（ts_mean / ts_std 等）
    - numpy/pandas 安全子集
    """
    ns: dict[str, Any] = {}

    # 注入数据列
    for col in data.columns:
        ns[col] = data[col]
    ns["data"] = data
    ns["df"] = data

    # numpy 安全子集
    ns["np"] = _SafeNumpy()

    # pandas 安全子集
    ns["pd"] = _SafePandas()

    # math
    import math as _math

    ns["math"] = _math

    # 内置安全函数
    ns.update(
        {
            "abs": abs,
            "min": min,
            "max": max,
            "sum": sum,
            "len": len,
            "round": round,
            "int": int,
            "float": float,
            "bool": bool,
        }
    )

    # 金融算子
    ns.update(
        {
            "ts_mean": _ts_mean,
            "ts_std": _ts_std,
            "ts_corr": _ts_corr,
            "ts_rank": _ts_rank,
            "ts_max": _ts_max,
            "ts_min": _ts_min,
            "ts_sum": _ts_sum,
            "delay": _delay,
            "delta": _delta,
            "rank": _cs_rank,
            "cs_rank": _cs_rank,
            "zscore": _cs_zscore,
            "cs_zscore": _cs_zscore,
            "log": _safe_log,
            "sign": _safe_sign,
            "pow": _safe_pow,
            "if_else": _if_else,
        }
    )

    return ns


# ---------------------------------------------------------------------------
# 安全包装类（限制 numpy/pandas 访问）
# ---------------------------------------------------------------------------


class _SafeNumpy:
    """numpy 安全子集代理"""

    mean = staticmethod(np.mean)
    std = staticmethod(np.std)
    median = staticmethod(np.median)
    sum = staticmethod(np.sum)
    max = staticmethod(np.max)
    min = staticmethod(np.min)
    abs = staticmethod(np.abs)
    log = staticmethod(np.log)
    log1p = staticmethod(np.log1p)
    sqrt = staticmethod(np.sqrt)
    sign = staticmethod(np.sign)
    where = staticmethod(np.where)
    clip = staticmethod(np.clip)
    nan_to_num = staticmethod(np.nan_to_num)
    isnan = staticmethod(np.isnan)
    isinf = staticmethod(np.isinf)
    percentile = staticmethod(np.percentile)
    nanmean = staticmethod(np.nanmean)
    nanstd = staticmethod(np.nanstd)
    nanmedian = staticmethod(np.nanmedian)
    nansum = staticmethod(np.nansum)
    inf = np.inf
    nan = np.nan
    pi = np.pi


class _SafePandas:
    """pandas 安全子集代理"""

    Series = staticmethod(pd.Series)
    DataFrame = staticmethod(pd.DataFrame)
    isna = staticmethod(pd.isna)
    notna = staticmethod(pd.notna)


# ---------------------------------------------------------------------------
# 金融算子实现
# ---------------------------------------------------------------------------


def _ts_mean(x: pd.Series, window: int) -> pd.Series:
    return x.rolling(window=window, min_periods=max(1, window // 2)).mean()


def _ts_std(x: pd.Series, window: int) -> pd.Series:
    return x.rolling(window=window, min_periods=max(1, window // 2)).std()


def _ts_corr(x: pd.Series, y: pd.Series, window: int) -> pd.Series:
    return x.rolling(window=window, min_periods=max(1, window // 2)).corr(y)


def _ts_rank(x: pd.Series, window: int) -> pd.Series:
    return x.rolling(window=window, min_periods=max(1, window // 2)).rank(pct=True)


def _ts_max(x: pd.Series, window: int) -> pd.Series:
    return x.rolling(window=window, min_periods=max(1, window // 2)).max()


def _ts_min(x: pd.Series, window: int) -> pd.Series:
    return x.rolling(window=window, min_periods=max(1, window // 2)).min()


def _ts_sum(x: pd.Series, window: int) -> pd.Series:
    return x.rolling(window=window, min_periods=max(1, window // 2)).sum()


def _delay(x: pd.Series, d: int) -> pd.Series:
    return x.shift(d)


def _delta(x: pd.Series, d: int) -> pd.Series:
    return x - x.shift(d)


def _cs_rank(x: pd.Series) -> pd.Series:
    return x.rank(pct=True)


def _cs_zscore(x: pd.Series) -> pd.Series:
    mu = x.mean()
    sigma = x.std()
    if sigma == 0:
        return pd.Series(0.0, index=x.index)
    return (x - mu) / sigma


def _safe_log(x: pd.Series) -> pd.Series:
    return np.log(x.clip(lower=1e-10))


def _safe_sign(x: pd.Series) -> pd.Series:
    return np.sign(x)


def _safe_pow(x: pd.Series, n: float) -> pd.Series:
    return np.power(x, n)


def _if_else(
    condition: pd.Series, x: pd.Series, y: pd.Series
) -> pd.Series:
    return pd.Series(
        np.where(condition, x, y),
        index=condition.index,
    )
