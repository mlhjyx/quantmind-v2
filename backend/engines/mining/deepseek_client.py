"""DeepSeek API客户端 — AI闭环LLM调用层

设计来源: docs/research/R7_ai_model_selection.md §4.1 混合模型架构
功能:
  1. DeepSeekClient: chat completions封装，支持JSON模式和纯文本模式
  2. ModelRouter: 根据任务类型路由到最佳模型
     - idea      → deepseek-reasoner (R1, 深度推理)
     - factor    → Qwen3本地 fallback → deepseek-chat (V3, 快速)
     - eval      → deepseek-chat (V3.2/V3, 统计分析)
     - diagnosis → deepseek-reasoner (R1, 根因分析)
  3. 重试+超时+限速: 指数退避3次, 单次60秒, QPM限制
  4. 成本追踪: 每次调用记录token数和估算费用

Sprint 1.17 ml-engineer
"""

from __future__ import annotations

import json
import structlog
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 模型常量 (R7 §4.1 推荐)
# ---------------------------------------------------------------------------

# DeepSeek API兼容OpenAI格式
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 模型ID (2026年3月)
MODEL_DEEPSEEK_R1 = "deepseek-reasoner"          # Idea Agent / Diagnosis Agent
MODEL_DEEPSEEK_V3 = "deepseek-chat"              # Factor Agent (fallback) / Eval Agent

# 本地Qwen3 (Ollama/LM Studio兼容OpenAI格式)
QWEN3_LOCAL_BASE_URL = "http://localhost:11434/v1"
MODEL_QWEN3_LOCAL = "qwen3:30b-a3b"              # Qwen3-30B-A3B (MoE, fits 12GB VRAM)

# 定价 ($/M tokens, 2026-03-28)
_PRICING: dict[str, dict[str, float]] = {
    MODEL_DEEPSEEK_R1: {"input": 0.55, "output": 2.19},
    MODEL_DEEPSEEK_V3: {"input": 0.14, "output": 0.28},
    MODEL_QWEN3_LOCAL: {"input": 0.0,  "output": 0.0},   # 本地零成本
}

# QPM限制 (requests per minute)
_QPM_LIMITS: dict[str, int] = {
    MODEL_DEEPSEEK_R1: 30,
    MODEL_DEEPSEEK_V3: 60,
    MODEL_QWEN3_LOCAL: 120,
}


# ---------------------------------------------------------------------------
# 任务类型枚举 (对应R7 §1.1 Agent角色)
# ---------------------------------------------------------------------------


class TaskType(StrEnum):
    """AI闭环任务类型，决定模型路由。"""
    IDEA      = "idea"       # Idea Agent: 因子假设生成
    FACTOR    = "factor"     # Factor Agent: 代码生成
    EVAL      = "eval"       # Eval Agent: 统计评估
    DIAGNOSIS = "diagnosis"  # Diagnosis Agent: 根因分析


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class LLMMessage:
    """单条对话消息。"""
    role: str     # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    """LLM调用响应。"""
    content: str                         # 原始响应文本
    model: str                           # 实际使用的模型
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    is_json: bool = False                # 是否为JSON模式响应
    parsed: Any = None                   # JSON模式解析结果


@dataclass
class CostTracker:
    """累计成本追踪器。"""
    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    calls_by_model: dict[str, int] = field(default_factory=dict)
    cost_by_model: dict[str, float] = field(default_factory=dict)

    def record(self, response: LLMResponse) -> None:
        """记录一次调用。"""
        self.total_calls += 1
        self.total_input_tokens += response.input_tokens
        self.total_output_tokens += response.output_tokens
        self.total_cost_usd += response.cost_usd
        self.calls_by_model[response.model] = self.calls_by_model.get(response.model, 0) + 1
        self.cost_by_model[response.model] = self.cost_by_model.get(response.model, 0.0) + response.cost_usd

    def summary(self) -> dict[str, Any]:
        """返回成本摘要字典。"""
        return {
            "total_calls": self.total_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "calls_by_model": dict(self.calls_by_model),
            "cost_by_model": {k: round(v, 6) for k, v in self.cost_by_model.items()},
        }


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """根据任务类型路由到最佳模型 (R7 §4.1)。

    路由策略:
        IDEA      → deepseek-reasoner (R1深度推理, 中文金融知识最强)
        FACTOR    → qwen3本地 (零成本代码生成); 本地不可用 → deepseek-chat
        EVAL      → deepseek-chat (V3成本低, 统计分析够用)
        DIAGNOSIS → deepseek-reasoner (R1根因分析, 长上下文推理)
    """

    def __init__(self, local_qwen3_available: bool = False) -> None:
        self._local_available = local_qwen3_available

    def route(self, task_type: TaskType) -> tuple[str, str]:
        """返回 (model_id, base_url)。"""
        if task_type in (TaskType.IDEA, TaskType.DIAGNOSIS):
            return MODEL_DEEPSEEK_R1, DEEPSEEK_BASE_URL

        if task_type == TaskType.FACTOR:
            if self._local_available:
                return MODEL_QWEN3_LOCAL, QWEN3_LOCAL_BASE_URL
            return MODEL_DEEPSEEK_V3, DEEPSEEK_BASE_URL

        # EVAL
        return MODEL_DEEPSEEK_V3, DEEPSEEK_BASE_URL

    def set_local_available(self, available: bool) -> None:
        self._local_available = available


# ---------------------------------------------------------------------------
# DeepSeekClient
# ---------------------------------------------------------------------------


class DeepSeekClient:
    """DeepSeek / OpenAI兼容API客户端。

    支持:
      - DeepSeek-R1 (deepseek-reasoner)
      - DeepSeek-V3 (deepseek-chat)
      - Qwen3本地 (Ollama/LM Studio, OpenAI格式)

    API key从环境变量 DEEPSEEK_API_KEY 读取。
    未设置时自动进入mock模式（graceful fallback）。

    使用示例:
        client = DeepSeekClient()
        resp = client.chat(
            messages=[LLMMessage("user", "生成一个因子")],
            model=MODEL_DEEPSEEK_R1,
            json_mode=True,
        )
        print(resp.content)
        print(client.cost_tracker.summary())
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = DEEPSEEK_BASE_URL,
        timeout: float = 60.0,
        max_retries: int = 3,
        mock_mode: bool = False,
    ) -> None:
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.base_url = base_url
        self.timeout = timeout
        self.max_retries = max_retries
        self.cost_tracker = CostTracker()

        # mock模式: API key未设置时自动启用
        self.mock_mode = mock_mode or not self.api_key
        if self.mock_mode and not mock_mode:
            logger.warning(
                "DEEPSEEK_API_KEY未设置，DeepSeekClient进入mock模式。"
                "生产环境请设置环境变量。"
            )

        # 限速状态 (简单令牌桶)
        self._last_call_time: dict[str, float] = {}

        # 延迟导入openai，避免未安装时报错
        self._openai_client: Any = None

    def _get_openai_client(self, base_url: str) -> Any:
        """懒加载并缓存OpenAI客户端。"""
        try:
            from openai import OpenAI  # type: ignore[import-untyped]
        except ImportError as e:
            raise ImportError(
                "需要安装openai包: pip install openai>=1.0"
            ) from e

        # 本地模型不需要api_key
        key = self.api_key if self.api_key else "local"
        return OpenAI(api_key=key, base_url=base_url, timeout=self.timeout)

    def _rate_limit(self, model: str) -> None:
        """简单QPM限速: 确保同一模型调用间隔 >= 60/QPM 秒。"""
        qpm = _QPM_LIMITS.get(model, 30)
        min_interval = 60.0 / qpm
        last = self._last_call_time.get(model, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self._last_call_time[model] = time.monotonic()

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """估算调用成本（USD）。"""
        pricing = _PRICING.get(model, {"input": 0.14, "output": 0.28})
        return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000

    def _mock_response(
        self,
        messages: list[LLMMessage],
        model: str,
        json_mode: bool,
    ) -> LLMResponse:
        """Mock模式响应，用于测试和API key未配置时的graceful fallback。"""
        if json_mode:
            content = json.dumps([{
                "name": "mock_factor_001",
                "expression": "cs_rank(ts_mean(returns, 20))",
                "hypothesis": "Mock因子假设（API key未配置）",
                "expected_ic_direction": "positive",
                "expected_ic_range": [0.02, 0.05],
                "category": "价量",
                "novelty_vs_existing": "Mock模式，无实际内容",
            }])
        else:
            content = "[Mock模式] DeepSeek API key未配置，返回占位响应。"

        return LLMResponse(
            content=content,
            model=model,
            input_tokens=100,
            output_tokens=50,
            cost_usd=0.0,
            latency_ms=0.0,
            is_json=json_mode,
            parsed=json.loads(content) if json_mode else None,
        )

    def chat(
        self,
        messages: list[LLMMessage],
        model: str = MODEL_DEEPSEEK_V3,
        base_url: str | None = None,
        json_mode: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        """执行chat completions调用。

        Args:
            messages: 对话消息列表。
            model: 模型ID，默认deepseek-chat (V3)。
            base_url: 覆盖默认base_url（用于本地模型）。
            json_mode: True时强制JSON格式输出并解析。
            temperature: 采样温度，0=确定性，1=最随机。
            max_tokens: 最大输出token数。

        Returns:
            LLMResponse: 包含内容、token计数和成本。

        Raises:
            RuntimeError: 重试耗尽后仍失败。
        """
        if self.mock_mode:
            resp = self._mock_response(messages, model, json_mode)
            self.cost_tracker.record(resp)
            return resp

        effective_base_url = base_url or self.base_url
        oai_messages = [{"role": m.role, "content": m.content} for m in messages]

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                self._rate_limit(model)
                client = self._get_openai_client(effective_base_url)

                kwargs: dict[str, Any] = {
                    "model": model,
                    "messages": oai_messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if json_mode:
                    kwargs["response_format"] = {"type": "json_object"}

                t0 = time.monotonic()
                completion = client.chat.completions.create(**kwargs)
                latency_ms = (time.monotonic() - t0) * 1000

                raw_content = completion.choices[0].message.content or ""
                input_tokens = getattr(completion.usage, "prompt_tokens", 0)
                output_tokens = getattr(completion.usage, "completion_tokens", 0)
                cost = self._estimate_cost(model, input_tokens, output_tokens)

                parsed = None
                if json_mode:
                    try:
                        parsed = json.loads(raw_content)
                    except json.JSONDecodeError:
                        logger.warning("JSON解析失败，原始内容: %s...", raw_content[:200])

                resp = LLMResponse(
                    content=raw_content,
                    model=model,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                    latency_ms=latency_ms,
                    is_json=json_mode,
                    parsed=parsed,
                )
                self.cost_tracker.record(resp)
                logger.debug(
                    "LLM调用成功: model=%s tokens=%d+%d cost=$%.6f latency=%.0fms",
                    model, input_tokens, output_tokens, cost, latency_ms,
                )
                return resp

            except Exception as e:
                last_error = e
                wait = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                logger.warning(
                    "LLM调用失败 (attempt %d/%d): %s，%.1fs后重试",
                    attempt + 1, self.max_retries, e, wait,
                )
                if attempt < self.max_retries - 1:
                    time.sleep(wait)

        raise RuntimeError(
            f"DeepSeek API调用失败，已重试{self.max_retries}次。"
            f"最后一次错误: {last_error}"
        )


# ---------------------------------------------------------------------------
# 全局单例（便于模块间共享成本追踪）
# ---------------------------------------------------------------------------

_default_client: DeepSeekClient | None = None
_default_router: ModelRouter | None = None


def get_default_client() -> DeepSeekClient:
    """获取全局DeepSeekClient单例。"""
    global _default_client
    if _default_client is None:
        _default_client = DeepSeekClient()
    return _default_client


def get_default_router() -> ModelRouter:
    """获取全局ModelRouter单例。"""
    global _default_router
    if _default_router is None:
        _default_router = ModelRouter()
    return _default_router
