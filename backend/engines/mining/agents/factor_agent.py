"""FactorAgent — LLM驱动的因子代码生成智能体

设计来源:
  - docs/research/R7_ai_model_selection.md §4.1 (DeepSeek-V3/Qwen3为Factor Agent)
  - docs/GP_CLOSED_LOOP_DESIGN.md (Step 3 LLM集成)

功能:
  1. 接收FactorHypothesis(来自IdeaAgent) → 输出pandas/numpy计算代码
  2. 代码必须是纯函数: def compute_factor(df: pd.DataFrame) -> pd.Series
  3. 输入df包含: open/high/low/close/volume/amount/turnover_rate/total_mv
  4. 安全沙箱验证: 生成的代码通过factor_sandbox.py静态检查
  5. 自动重试: 代码无效时重新生成(最多3次)

Sprint 1.18 ml-engineer (D5补全)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import structlog

from ..deepseek_client import (
    DeepSeekClient,
    LLMMessage,
    ModelRouter,
    TaskType,
    get_default_client,
)
from .idea_agent import FactorHypothesis

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class GeneratedFactorCode:
    """FactorAgent的输出 — 因子计算代码。"""
    hypothesis_name: str
    expression: str           # 原始DSL表达式
    code: str                 # Python代码字符串
    function_name: str        # 函数名（默认compute_factor）
    imports: list[str] = field(default_factory=list)
    is_valid: bool = False    # 语法+安全检查通过
    validation_error: str = ""
    retry_count: int = 0


# ---------------------------------------------------------------------------
# Prompt模板
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """你是一个量化因子代码生成专家。
你的任务是将因子假设转换为可执行的Python代码。

规则:
1. 代码必须是纯函数: def compute_factor(df: pd.DataFrame) -> pd.Series
2. 输入df的列: code, trade_date, open, high, low, close, volume, amount, turnover_rate, total_mv
3. 只使用 pandas, numpy (已导入为 pd, np)
4. 返回值必须是pd.Series，index与df一致
5. 处理NaN: 使用fillna或dropna，不能有无穷值
6. 不能使用eval/exec/import/open/os/sys等不安全操作
7. 代码应简洁高效，避免逐行循环

只输出Python代码块，不要解释。"""

_USER_TEMPLATE = """将以下因子假设转换为compute_factor函数:

因子名: {name}
DSL表达式: {expression}
经济学假设: {hypothesis}
预期IC方向: {direction}
类别: {category}

请生成 def compute_factor(df: pd.DataFrame) -> pd.Series 函数。"""


# ---------------------------------------------------------------------------
# FactorAgent
# ---------------------------------------------------------------------------


class FactorAgent:
    """因子代码生成Agent — 将假设转为可执行代码。

    用法:
        agent = FactorAgent()
        result = agent.generate_code(hypothesis)
        if result.is_valid:
            exec(result.code)  # 在沙箱中执行
    """

    def __init__(
        self,
        client: DeepSeekClient | None = None,
        max_retries: int = 3,
    ) -> None:
        self._client = client
        self._max_retries = max_retries
        self._router = ModelRouter()

    @property
    def client(self) -> DeepSeekClient:
        if self._client is None:
            self._client = get_default_client()
        return self._client

    def generate_code(
        self,
        hypothesis: FactorHypothesis,
    ) -> GeneratedFactorCode:
        """从因子假设生成计算代码。

        Args:
            hypothesis: IdeaAgent产出的因子假设。

        Returns:
            GeneratedFactorCode，含代码和验证结果。
        """
        result = GeneratedFactorCode(
            hypothesis_name=hypothesis.name,
            expression=hypothesis.expression,
            code="",
            function_name="compute_factor",
        )

        for attempt in range(self._max_retries):
            result.retry_count = attempt

            try:
                messages = [
                    LLMMessage(role="system", content=_SYSTEM_PROMPT),
                    LLMMessage(role="user", content=_USER_TEMPLATE.format(
                        name=hypothesis.name,
                        expression=hypothesis.expression,
                        hypothesis=hypothesis.hypothesis,
                        direction=hypothesis.expected_ic_direction,
                        category=hypothesis.category,
                    )),
                ]

                model_id, base_url = self._router.route(TaskType.FACTOR)
                response = self.client.chat(
                    messages=messages,
                    model=model_id,
                    base_url=base_url,
                )

                code = self._extract_code(response.content)
                if not code:
                    result.validation_error = "无法从LLM响应中提取代码块"
                    continue

                result.code = code
                result.imports = ["import pandas as pd", "import numpy as np"]

                # 验证代码
                valid, error = self._validate_code(code)
                if valid:
                    result.is_valid = True
                    result.validation_error = ""
                    logger.info(
                        "[FactorAgent] %s: 代码生成成功 (attempt %d)",
                        hypothesis.name, attempt + 1,
                    )
                    return result
                else:
                    result.validation_error = error
                    logger.warning(
                        "[FactorAgent] %s: 代码验证失败 (attempt %d): %s",
                        hypothesis.name, attempt + 1, error,
                    )

            except Exception as exc:
                result.validation_error = f"LLM调用失败: {exc}"
                logger.warning(
                    "[FactorAgent] %s: 异常 (attempt %d): %s",
                    hypothesis.name, attempt + 1, exc,
                )

        logger.error(
            "[FactorAgent] %s: %d次尝试后仍失败",
            hypothesis.name, self._max_retries,
        )
        return result

    @staticmethod
    def _extract_code(response_text: str) -> str:
        """从LLM响应中提取Python代码块。"""
        # 尝试 ```python ... ``` 格式
        pattern = r"```(?:python)?\s*\n(.*?)```"
        matches = re.findall(pattern, response_text, re.DOTALL)
        if matches:
            return matches[0].strip()

        # 尝试整个响应就是代码
        if "def compute_factor" in response_text:
            return response_text.strip()

        return ""

    @staticmethod
    def _validate_code(code: str) -> tuple[bool, str]:
        """验证生成的代码安全性和正确性。

        Returns:
            (is_valid, error_message)
        """
        # 1. 语法检查
        try:
            compile(code, "<factor_agent>", "exec")
        except SyntaxError as e:
            return False, f"语法错误: {e}"

        # 2. 必须包含compute_factor函数
        if "def compute_factor" not in code:
            return False, "缺少 def compute_factor 函数定义"

        # 3. 安全检查 — 禁止危险操作
        forbidden = [
            "import os", "import sys", "import subprocess",
            "eval(", "exec(", "__import__",
            "open(", "os.system", "os.popen",
        ]
        for f in forbidden:
            if f in code:
                return False, f"禁止操作: {f}"

        return True, ""
