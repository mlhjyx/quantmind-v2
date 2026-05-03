"""LLM 路由公共类型 — 7 任务 enum + LLMResponse 数据类.

归属: Framework #LLM 平台 SDK 子模块 (V3 §5.5 LiteLLM 路由真预约).

7 任务来源 V3 §5.5 line 714-720 (S8 audit §4 mapping 表):
- L0.2 NewsClassifier (V4-Flash, 100-300 calls/天)
- L2.2 fundamental_context summarizer (V4-Flash, ~10/天)
- L2.3 Bull Agent (V4-Flash, 6/天)
- L2.3 Bear Agent (V4-Flash, 6/天)
- L2.3 Judge (V4-Pro, 3/天)
- L5 RiskReflector (V4-Pro, 周 1 + 月 1 + post-event)
- Embedding (V4-Flash, RAG ingest 1/事件)

Bull/Bear 拆 2 task (走不同 prompt + 不同输出格式), 沿用 user 决议 3 (a) 7 task.

关联:
- ADR-031 (S2 LiteLLMRouter implementation path 决议)
- V3 §5.5 / §11.1 / §16.2 / §20.1 #6
- docs/LLM_IMPORT_POLICY.md §10
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class RiskTaskType(StrEnum):
    """V3 §5.5 真预约 7 任务路由."""

    NEWS_CLASSIFY = "news_classify"                  # L0.2 V4-Flash
    FUNDAMENTAL_SUMMARIZE = "fundamental_summarize"  # L2.2 V4-Flash
    BULL_AGENT = "bull_agent"                        # L2.3 V4-Flash
    BEAR_AGENT = "bear_agent"                        # L2.3 V4-Flash
    JUDGE = "judge"                                  # L2.3 V4-Pro
    RISK_REFLECTOR = "risk_reflector"                # L5 V4-Pro
    EMBEDDING = "embedding"                          # RAG ingest V4-Flash


@dataclass(frozen=True)
class LLMMessage:
    """单条对话消息 (沿用 OpenAI Chat Completion 体例)."""

    role: str   # "system" | "user" | "assistant"
    content: str


@dataclass
class LLMResponse:
    """LiteLLMRouter 调用响应.

    跟 backend/engines/mining/deepseek_client.py LLMResponse 字段对齐 + 扩展:
    - cost_usd 改 Decimal (沿用决议 — 金融金额 Decimal, S2.3 持久化要求)
    - 新增 decision_id (caller traceable, S2.3 audit_trail 5 condition 真依赖)
    - 新增 is_fallback (是否走 qwen3-local fallback, S2.2 budget 状态判定)
    """

    content: str            # 原始响应文本
    model: str              # 实际路由后 model 名 (LiteLLM 真返)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    latency_ms: float = 0.0
    decision_id: str | None = None  # S2.3 audit trail 真依赖
    is_fallback: bool = False       # S2.2 budget 状态判定 + S2.3 audit cite


class UnknownTaskError(ValueError):
    """task_type 不在 RiskTaskType enum (反 silent fallback, 沿用铁律 33)."""


class RouterConfigError(RuntimeError):
    """config/litellm_router.yaml 加载或 schema 失败 (fail-loud, 铁律 33+34)."""
