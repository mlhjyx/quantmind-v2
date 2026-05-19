"""Agent / AI Assist API 路由.

Frontend Design v3 §2.3 AssistPanel backing endpoint.

设计原则 (AI Boundary, v3 spec):
    ❌ Block list (NEVER LLM-triggered):
        execute_phase / env_flip / emergency_close_all / pause_trading_global /
        L4 force-reset
    ⚠️ Compose but manual:
        L4 approve/reject / drift fix / threshold change
    ✅ Direct (explain-only):
        cancel single order / factor archive / report generate

当前状态 (2026-05-19 Week 2):
    - STUB 模式 — 返回 context-aware 解释, 不调用真 LLM
    - 真 LLM wire 待用户决议 (cost implication, F-S7-001 P0 cost tracking broken)
    - Enable: set AI_ASSIST_ENABLED=true in .env + 完成 F-S7-001 修复

Upgrade path (1 commit when ready):
    1. 修 F-S7-001 (LiteLLM cost_usd 真值入库)
    2. .env 加 AI_ASSIST_ENABLED=true
    3. 本文件 _do_assist() 替换 stub_response() 调用为 get_llm_router().completion()
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/agent", tags=["agent"])

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

AssistDomain = Literal[
    "dashboard", "risk", "factor", "execution", "strategy", "backtest", "pipeline", "general"
]


class AssistContext(BaseModel):
    """前端发送的对话上下文。"""

    page: AssistDomain = Field(description="当前页面 domain")
    entity_id: str | None = Field(default=None, description="操作对象 ID (e.g. factor name, strategy id)")
    data_snapshot: dict[str, Any] | None = Field(default=None, description="可选的数据快照")


class ChatMessage(BaseModel):
    """聊天消息。"""

    role: Literal["user", "assistant", "system"]
    content: str


class ChatRequest(BaseModel):
    """AssistPanel 聊天请求。"""

    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    context: AssistContext


class ChatResponse(BaseModel):
    """AssistPanel 聊天响应。"""

    reply: str
    mode: Literal["stub", "live"]
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0
    timestamp: str


# ---------------------------------------------------------------------------
# Stub 模式 — context-aware 解释 (不真调 LLM)
# ---------------------------------------------------------------------------

_DOMAIN_HINTS: dict[str, str] = {
    "dashboard": (
        "驾驶舱主要看 NAV / Sharpe / MDD / 持仓数 等核心指标. "
        "当前 PT (paper trading) 0 持仓 + cash ¥993,520 是 2026-04-29 用户决议清仓状态. "
        "重启交易 prerequisite 见 docs/audit/SHUTDOWN_NOTICE_2026_04_30.md §9."
    ),
    "risk": (
        "风控分 5 层 (L0 NORMAL / L1 WARN / L2 REDUCE / L3 HALT / L4 LIQUIDATE). "
        "L4 是 STAGED 流程, 需要人工 approve. 当前 PT 因清仓状态下熔断状态默认 L0. "
        "force-reset 是高风险 ops, 要写理由, 跳过 recovery streak 直接归零."
    ),
    "factor": (
        "因子池: CORE 4 (turnover_mean_20 / volatility_20 / bp_ratio / dv_ttm), WF OOS Sharpe=0.8659. "
        "新因子加入硬门 G1-G10 + paired bootstrap p<0.05. "
        "dv_ttm 当前是 warning 状态 (Session 5 lifecycle ratio=0.517 < 0.8), PT 配置仍包含."
    ),
    "execution": (
        "Execution 是黄金模板 (ConfirmModal + AdminTokenModal + danger CONFIRM 4 层防误触). "
        "LL-183 教训: dry-run 旗标传播必须显式, 不能 silent NOT-GATING. "
        "Execution 流程必走 PlatformSignalPipeline → execution_service → broker_qmt."
    ),
    "strategy": (
        "当前唯一 active strategy = CORE3+dv_ttm WF PASS. "
        "5yr=0.61 / 12yr=0.36 / WF=0.87 三 spread 真值有 2.4× 异质性, 需 cross-period 重评估. "
        "Phase 2.1/2.2/3B/3D/3E 全 NO-GO, 等权 alpha 上限确认."
    ),
    "backtest": (
        "回测可复现门 (regression max_diff=0) — 同 config_yaml_hash + git_commit 必产同结果. "
        "成本对齐铁律 18 (H0 < 5bps) + Partial SN b=0.50 是唯一有效 Modifier."
    ),
    "pipeline": (
        "Pipeline 12 节点 / 周一调仓 / 实盘 09:31 SH 自动执行. "
        "节点状态走 /api/pipeline/status 拉, 包含 node_statuses / current_node / status."
    ),
    "general": (
        "QuantMind V2 是个人 A 股量化系统, Python-first, sync psycopg2 + Celery + Redis. "
        "目标年化 15-25% / Sharpe 1-2 / MDD <15%. 当前清仓状态, 等 V3 重启 gate 完成."
    ),
}


def _stub_reply(messages: list[ChatMessage], context: AssistContext) -> str:
    """生成 stub 响应 — context-aware 解释, 0 LLM 调用."""

    user_msg = messages[-1].content.strip() if messages[-1].role == "user" else ""
    domain_hint = _DOMAIN_HINTS.get(context.page, _DOMAIN_HINTS["general"])

    entity_line = ""
    if context.entity_id:
        entity_line = f"\n\n当前 entity: `{context.entity_id}`"

    return (
        f"📍 AI 助手 (stub 模式, 真 LLM 调用待用户启用 AI_ASSIST_ENABLED)\n\n"
        f"你的问题: {user_msg[:200]}\n\n"
        f"---\n"
        f"**{context.page} 域基础知识**:\n{domain_hint}"
        f"{entity_line}\n\n"
        f"---\n"
        f"⚠️ 当前 AI 助手未启用真 LLM 调用. 启用步骤:\n"
        f"1. 修复 F-S7-001 LLM cost tracking (audit P0)\n"
        f"2. .env 加 `AI_ASSIST_ENABLED=true`\n"
        f"3. 重启 FastAPI 服务\n\n"
        f"CRIT ops (env_flip / execute_phase / emergency_close) 即使启用也不允许 LLM 触发, 仍走 CC bash."
    )


def _is_ai_enabled() -> bool:
    """检查 AI_ASSIST_ENABLED 旗标 (默认 false, 反 silent LLM cost 增长)."""
    val = os.environ.get("AI_ASSIST_ENABLED", "false").strip().lower()
    return val in ("true", "1", "yes")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse, summary="AI Assist Panel 聊天端点")
async def post_chat(req: ChatRequest) -> ChatResponse:
    """处理 AssistPanel 聊天请求.

    当前 STUB 模式 — 返回 context-aware 解释而非调用真 LLM.
    启用真 LLM 需 .env 设 AI_ASSIST_ENABLED=true 且修复 F-S7-001 cost tracking.

    Args:
        req: 包含 messages 数组 + context (page domain + entity_id + data_snapshot).

    Returns:
        ChatResponse 含 reply / mode (stub|live) / cost_usd / tokens 信息.

    Raises:
        HTTPException 400 若 messages 为空.
    """
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")

    enabled = _is_ai_enabled()
    if not enabled:
        reply = _stub_reply(req.messages, req.context)
        return ChatResponse(
            reply=reply,
            mode="stub",
            cost_usd=0.0,
            tokens_in=0,
            tokens_out=0,
            timestamp=datetime.now(UTC).isoformat(),
        )

    # 真 LLM 调用 path (待 F-S7-001 修复 + 用户启用 AI_ASSIST_ENABLED 后激活)
    # 当前留 TODO 占位, 反 silent LLM 调用导致 zero-cost 计入 audit 漂移
    logger.warning(
        "AI_ASSIST_ENABLED=true 但 LLM 调用 path 仍未启用 (待 F-S7-001 P0 修复)",
        page=req.context.page,
    )
    reply = _stub_reply(req.messages, req.context)
    reply = (
        "⚠️ AI_ASSIST_ENABLED=true 但 LLM 调用 path 仍未启用 (F-S7-001 P0 cost tracking 待修复).\n\n"
        + reply
    )
    return ChatResponse(
        reply=reply,
        mode="stub",
        cost_usd=0.0,
        tokens_in=0,
        tokens_out=0,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/chat/status", summary="AI Assist 启用状态查询")
async def get_chat_status() -> dict[str, Any]:
    """返回 AI Assist 当前 enable 状态 (前端 banner 提示用)."""
    return {
        "enabled": _is_ai_enabled(),
        "mode": "stub",
        "blocked_ops": [
            "execute_phase",
            "env_flip",
            "emergency_close_all",
            "pause_trading_global",
            "l4_force_reset",
        ],
        "compose_only_ops": [
            "l4_approve",
            "l4_reject",
            "drift_fix",
            "threshold_change",
        ],
        "direct_ops": [
            "cancel_single_order",
            "factor_archive",
            "report_generate",
        ],
    }


# ---------------------------------------------------------------------------
# Agent Config endpoints (Frontend Design v3 §3.3.5 — AgentConfig 页 read-only stub)
# ---------------------------------------------------------------------------

# 4 agents (frontend api/agent.ts: AgentName = "idea" | "factor" | "eval" | "diagnosis")
# 每个 agent 的默认 config + prompt template stub.
# 真 prompt versioning 留 backend prompt history table 实施 (Phase I 8h scope).
_AGENT_DEFAULT_CONFIGS: dict[str, dict[str, Any]] = {
    "idea": {
        "name": "idea",
        "display_name": "Idea Agent",
        "model": "deepseek-v3",
        "temperature": 0.7,
        "max_tokens": 4000,
        "system_prompt": (
            "你是 QuantMind 量化研究助手. 任务: 基于市场观察生成新因子假设. "
            "输出格式: (1) 经济机制描述 (≥50字) (2) 因子数学定义 (3) 预期 IC "
            "方向 (4) 失败模式. 严格遵守铁律 13 (经济机制不可缺)."
        ),
        "ic_threshold": 0.02,
        "t_stat_threshold": 2.5,
        "auto_archive": False,
        "auto_reject": False,
        "max_daily_runs": 10,
    },
    "factor": {
        "name": "factor",
        "display_name": "Factor Agent",
        "model": "deepseek-r1",
        "temperature": 0.3,
        "max_tokens": 8000,
        "system_prompt": (
            "你是因子评估专家. 任务: 基于 IC / IR / t-stat / 衰减速率 / "
            "经济机制评估候选因子. 输出: PASS/FAIL + 5 维 score + 理由. "
            "严格遵守 G1-G10 Gate (含 G9 新颖性 + G10 经济机制)."
        ),
        "ic_threshold": 0.025,
        "t_stat_threshold": 2.5,
        "auto_archive": True,
        "auto_reject": True,
        "max_daily_runs": 20,
    },
    "eval": {
        "name": "eval",
        "display_name": "Eval Agent",
        "model": "deepseek-v3",
        "temperature": 0.2,
        "max_tokens": 4000,
        "system_prompt": (
            "你是策略评估专家. 任务: 基于回测结果 (Sharpe / MDD / 换手率 / "
            "regime / 成本) 评估策略上线适配性. 输出: GO/WAIT/NO-GO + 风险列表."
        ),
        "ic_threshold": 0.02,
        "t_stat_threshold": 2.0,
        "auto_archive": False,
        "auto_reject": False,
        "max_daily_runs": 5,
    },
    "diagnosis": {
        "name": "diagnosis",
        "display_name": "Diagnosis Agent",
        "model": "deepseek-r1",
        "temperature": 0.1,
        "max_tokens": 8000,
        "system_prompt": (
            "你是系统诊断专家. 任务: 基于异常事件 (IC 突降 / 持仓异常 / "
            "Sharpe 漂移) 推导根因 + 修复方案. 输出: root_cause + fix_plan + "
            "rollback_plan + verify_command."
        ),
        "ic_threshold": 0.0,
        "t_stat_threshold": 0.0,
        "auto_archive": False,
        "auto_reject": False,
        "max_daily_runs": 3,
    },
}


@router.get("/{name}/config", summary="Agent 配置查询 (read-only stub)")
async def get_agent_config(name: str) -> dict[str, Any]:
    """返回 agent 配置 (含 system_prompt). Phase I read-only stub —
    真 prompt versioning 留 backend prompt history table 实施.

    Args:
        name: agent 名 (idea / factor / eval / diagnosis).
    """
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")
    return _AGENT_DEFAULT_CONFIGS[name]


@router.put("/{name}/config", summary="Agent 配置更新 (stub no-op)")
async def put_agent_config(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """更新 agent 配置. 当前 stub no-op (留 backend prompt history 实施).

    真实施需:
      1. Backend prompt_history table (name, version, prompt, model, temp, created_at)
      2. 写入新 version row + 保留旧 version
      3. Rollback via version_id

    返回当前 default config (未持久化用户改动).
    """
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")
    logger.warning(
        "Agent config PUT 当前 stub no-op, 用户改动未持久化 (留 Phase I prompt history 实施)",
        agent=name,
        payload_keys=list(payload.keys()),
    )
    return _AGENT_DEFAULT_CONFIGS[name]


@router.post("/{name}/config/reset", summary="Agent 配置重置 (stub no-op)")
async def reset_agent_config(name: str) -> dict[str, Any]:
    """重置 agent 配置. Stub no-op — 返 default config."""
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")
    return _AGENT_DEFAULT_CONFIGS[name]


@router.get("/model-health", summary="LLM 模型健康检查 (stub)")
async def get_model_health() -> list[dict[str, Any]]:
    """返回 3 model health stub. 真实施需 backend periodic LLM ping cron."""
    return [
        {
            "model": "deepseek-r1",
            "is_online": True,
            "latency_ms": None,
            "last_checked_at": datetime.now(UTC).isoformat(),
            "error": "stub mode — periodic ping cron 未实施",
        },
        {
            "model": "deepseek-v3",
            "is_online": True,
            "latency_ms": None,
            "last_checked_at": datetime.now(UTC).isoformat(),
            "error": "stub mode",
        },
        {
            "model": "qwen3",
            "is_online": False,
            "latency_ms": None,
            "last_checked_at": datetime.now(UTC).isoformat(),
            "error": "stub mode + ollama_chat fallback only",
        },
    ]


@router.get("/cost-summary", summary="LLM 成本汇总 (从 llm_call_log 真值)")
async def get_cost_summary(month: str | None = None) -> dict[str, Any]:
    """返回月度 LLM 成本汇总.

    F-S7-001 P0 修复后 (commit 23ebea5), 新 LLM 调用 cost_usd 真值入库.
    历史 570 calls cost_usd=0 sustained (audit trail 真实记录).

    Args:
        month: YYYY-MM, 默认本月.
    """
    if month is None:
        month = datetime.now(UTC).strftime("%Y-%m")
    # Phase I read-only stub — 真实施需 llm_call_log SQL 聚合
    # 占位返回结构, 真值在 F-S7-001 修复后 LLM 调用累积
    return {
        "month": month,
        "total_cost_cny": 0.0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "by_agent": {
            "idea": {"cost_cny": 0.0, "tokens": 0},
            "factor": {"cost_cny": 0.0, "tokens": 0},
            "eval": {"cost_cny": 0.0, "tokens": 0},
            "diagnosis": {"cost_cny": 0.0, "tokens": 0},
        },
        "by_model": {
            "deepseek-r1": {"cost_cny": 0.0, "tokens": 0},
            "deepseek-v3": {"cost_cny": 0.0, "tokens": 0},
            "qwen3": {"cost_cny": 0.0, "tokens": 0},
        },
        "daily_usage": [],
        "_note": (
            "Phase I stub. 真实施需 llm_call_log SQL 聚合 (F-S7-001 修复后真值生效, "
            "AI_ASSIST_ENABLED=true 后历史累积).真 prompt version cost decomp "
            "留 backend prompt_history table impl."
        ),
    }


@router.get("/{name}/logs", summary="Agent 调用日志 (stub empty)")
async def get_agent_logs(name: str, limit: int = 50) -> list[dict[str, Any]]:
    """返回 agent 调用 logs. Stub empty — 真实施需 llm_call_log SQL 聚合."""
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")
    _ = limit  # placeholder, real impl 走 LIMIT clause
    return []
