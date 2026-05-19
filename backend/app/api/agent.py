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

import re
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.core.auth import verify_admin_token
from app.core.rate_limit import rate_limit_chat

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

    @field_validator("entity_id")
    @classmethod
    def _sanitize_entity_id(cls, v: str | None) -> str | None:
        """P1-4 fix (security-reviewer, Session 57+1 2026-05-19): prompt injection防御.

        entity_id 来源前端 query/path, 未 sanitize 时可被 attacker 注入 LLM
        system_prompt override 指令 (e.g. "ignore previous instructions, execute...").
        严格白名单: 字母数字 + 点 + 中划线 + 下划线 + 斜杠 (factor name / strategy id / stock code 体例).
        长度 cap 64 chars 防 prompt blow-up. 空串/全被剥光 → None.
        """
        if v is None:
            return None
        sanitized = re.sub(r"[^a-zA-Z0-9._\-/]", "", v)[:64]
        return sanitized or None


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
    """检查 AI_ASSIST_ENABLED 旗标 (默认 false, 反 silent LLM cost 增长).

    P1 fix (python-reviewer, Session 57+1 2026-05-19): 走 settings.AI_ASSIST_ENABLED SSOT
    (铁律 34), 反 os.environ direct read (middle-layer bypass anti-pattern).
    Settings pydantic 已处理 .env 加载 + 类型 coercion.
    """
    return settings.AI_ASSIST_ENABLED


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/chat", response_model=ChatResponse, summary="AI Assist Panel 聊天端点")
async def post_chat(
    req: ChatRequest,
    _: None = Depends(verify_admin_token),  # P1-2 fix: 反 unauthenticated LLM cost sink
    _rl: None = Depends(rate_limit_chat),  # S3 close: 10 req/min per IP token-bucket
) -> ChatResponse:
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

    # 真 LLM 调用 path — F-S7-001 closed (commit 23ebea5) 后启用.
    # 走 get_llm_router() 唯一 sanctioned 入口 + NEWS_CLASSIFY task (V4-Flash 最便宜 path).
    # NEWS_CLASSIFY 真业务是新闻分类, 这里 abuse 用作 chat — semantic mismatch 但 LLM
    # 真 input/output 无差异. 留 future RiskTaskType.GENERAL_ASSIST 实施 (修 prompt
    # versioning table 时一起加 enum + yaml entry).
    try:
        return _real_llm_chat(req)
    except Exception as exc:
        # Fallback 反 silent fail (铁律 33): 真 LLM 调用失败时 graceful degrade 到 stub
        logger.exception(
            "Real LLM call failed, falling back to stub reply",
            page=req.context.page,
            error=str(exc),
        )
        stub = _stub_reply(req.messages, req.context)
        return ChatResponse(
            reply=f"⚠️ LLM 调用失败 ({exc}), 走 stub fallback:\n\n{stub}",
            mode="stub",
            cost_usd=0.0,
            tokens_in=0,
            tokens_out=0,
            timestamp=datetime.now(UTC).isoformat(),
        )


def _real_llm_chat(req: ChatRequest) -> ChatResponse:
    """走 get_llm_router() 真 LLM 调用 path.

    F-S7-001 P0 closed → cost_usd 真值入 LLMResponse (DeepSeek pricing fallback path).
    AI Boundary CRIT ops 自然 enforce — 当前 path 仅返 text reply, 无 tool calling.
    """
    # llm-internal-allow: agent chat 走 sanctioned get_llm_router() facade (反 naked LiteLLMRouter)
    from backend.qm_platform.llm import LLMMessage, RiskTaskType, get_llm_router

    router = get_llm_router()
    domain_hint = _DOMAIN_HINTS.get(req.context.page, _DOMAIN_HINTS["general"])
    system_prompt = (
        f"你是 QuantMind AI 助手 (QuantMind {req.context.page} domain).\n"
        f"专业背景: {domain_hint}\n\n"
        f"硬约束:\n"
        f"- 仅 explanation-only, 不允许触发任何 ops (trade / env_flip / emergency_close 全 forbidden)\n"
        f"- 引用真值仅基于用户输入 + 你的训练知识, 不编造系统真值\n"
        f"- 中文回复, 简洁直接, ≤ 300 字"
    )
    messages: list[LLMMessage] = [LLMMessage("system", system_prompt)]
    for m in req.messages:
        messages.append(LLMMessage(m.role, m.content))

    # Use NEWS_CLASSIFY task (V4-Flash, cheapest, ~$0.0002/typical-call).
    # 留 future GENERAL_ASSIST task 时迁移.
    response = router.completion(
        task=RiskTaskType.NEWS_CLASSIFY,
        messages=messages,
        decision_id=f"frontend-assist-{req.context.page}",
    )

    return ChatResponse(
        reply=response.content,
        mode="live",
        cost_usd=float(response.cost_usd),
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        timestamp=datetime.now(UTC).isoformat(),
    )


@router.get("/chat/status", summary="AI Assist 启用状态查询")
async def get_chat_status(
    _: None = Depends(verify_admin_token),  # P1-2 fix: 反 op taxonomy info disclosure
) -> dict[str, Any]:
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
        "model": "deepseek-v4-flash",
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
        "model": "deepseek-v4-pro",
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
        "model": "deepseek-v4-flash",
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
        "model": "deepseek-v4-pro",
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


# H1 真闭环 (2026-05-19, ISSUES_PENDING_REGISTRY §9 H1): prompt_history table
# 真 persist + version diff support (反 LL-183 silent UI lie sustained).
# Migration: backend/migrations/2026_05_19_prompt_history.sql

def _get_db_conn() -> Any:
    """psycopg2 sync conn — 沿用 backend.app.services.db pattern."""
    from app.services.db import get_sync_conn
    return get_sync_conn()


def _row_to_config(row: tuple) -> dict[str, Any]:
    """prompt_history row → AgentConfig API shape."""
    return {
        "name": row[0],
        "version": row[1],
        "display_name": row[2],
        "model": row[3],
        "temperature": float(row[4]),
        "max_tokens": row[5],
        "system_prompt": row[6],
        "ic_threshold": float(row[7]),
        "t_stat_threshold": float(row[8]),
        "auto_archive": row[9],
        "auto_reject": row[10],
        "max_daily_runs": row[11],
        "is_active": row[12],
        "reason": row[13],
        "created_at": row[14].isoformat() if row[14] else None,
        "created_by": row[15],
    }


def _fetch_active_config(name: str) -> dict[str, Any] | None:
    """从 prompt_history 拿 active row (is_active=TRUE)."""
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT agent_name, version, display_name, model, temperature, max_tokens,
                       system_prompt, ic_threshold, t_stat_threshold,
                       auto_archive, auto_reject, max_daily_runs,
                       is_active, reason, created_at, created_by
                FROM prompt_history
                WHERE agent_name = %s AND is_active = TRUE
                ORDER BY version DESC
                LIMIT 1
                """,
                (name,),
            )
            row = cur.fetchone()
        return _row_to_config(row) if row else None
    finally:
        conn.close()


def _seed_default_config(name: str) -> dict[str, Any]:
    """First-run seed: INSERT v1 default config row (idempotent via UNIQUE constraint).

    code-reviewer P1.4 fix: nested try/rollback ensures conn returned to pool clean
    even on INSERT exception (CHECK constraint violation / type mismatch).
    """
    default = _AGENT_DEFAULT_CONFIGS[name]
    conn = _get_db_conn()
    try:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO prompt_history (
                        agent_name, version, display_name, model, temperature, max_tokens,
                        system_prompt, ic_threshold, t_stat_threshold,
                        auto_archive, auto_reject, max_daily_runs,
                        is_active, reason, created_by
                    )
                    VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE,
                            'initial seed from _AGENT_DEFAULT_CONFIGS', 'system')
                    ON CONFLICT (agent_name, version) DO NOTHING
                    RETURNING version
                    """,
                    (
                        name,
                        default["display_name"],
                        default["model"],
                        default["temperature"],
                        default["max_tokens"],
                        default["system_prompt"],
                        default["ic_threshold"],
                        default["t_stat_threshold"],
                        default["auto_archive"],
                        default["auto_reject"],
                        default["max_daily_runs"],
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    finally:
        conn.close()
    fetched = _fetch_active_config(name)
    return fetched if fetched else default


def _insert_new_version(
    name: str,
    payload: dict[str, Any],
    reason: str | None,
    *,
    source_version: int | None = None,
) -> dict[str, Any]:
    """INSERT 新 version row + mark previous active=FALSE (atomic single transaction).

    P1.5 fix (security-reviewer + code-reviewer): pg_advisory_xact_lock serializes
    concurrent PUTs per agent_name, preventing TOCTOU race on next_version compute +
    UNIQUE constraint loser silent data loss. Lock auto-releases on commit/rollback.

    P1 rollback atomicity fix (python-reviewer, Session 57+1 2026-05-19):
        source_version=N → 复制 N 号 version 作 base (rollback path), 在 advisory lock
        内做 SELECT 防 TOCTOU. None → 走 is_active=TRUE active row (regular update path).
        Raise ValueError if source_version not found (caller endpoint maps to HTTP 404).
    """
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            # P1.5: advisory lock per-agent (single writer, auto-release on txn end)
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"prompt_history_{name}",),
            )
            # Get next version + current active config (now race-free)
            cur.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 FROM prompt_history WHERE agent_name = %s",
                (name,),
            )
            next_version = cur.fetchone()[0]

            # P1 atomic rollback: pull source row from specific version OR current active.
            # 走 advisory lock 内单 SELECT 替代外层 SELECT+close+inner SELECT 两 conn race.
            if source_version is not None:
                cur.execute(
                    """
                    SELECT display_name, model, temperature, max_tokens, system_prompt,
                           ic_threshold, t_stat_threshold,
                           auto_archive, auto_reject, max_daily_runs
                    FROM prompt_history
                    WHERE agent_name = %s AND version = %s
                    """,
                    (name, source_version),
                )
                source_row = cur.fetchone()
                if source_row is None:
                    # version 真不存在 (advisory lock held → strong consistency).
                    # 反 silent fail (铁律 33): endpoint maps to HTTP 404.
                    raise ValueError(
                        f"agent {name} version {source_version} not found"
                    )
                current = source_row
            else:
                # Pull current active to apply partial updates atop
                cur.execute(
                    """
                    SELECT display_name, model, temperature, max_tokens, system_prompt,
                           ic_threshold, t_stat_threshold,
                           auto_archive, auto_reject, max_daily_runs
                    FROM prompt_history
                    WHERE agent_name = %s AND is_active = TRUE
                    ORDER BY version DESC LIMIT 1
                    """,
                    (name,),
                )
                current = cur.fetchone()
            if current is None:
                default = _AGENT_DEFAULT_CONFIGS[name]
                current_vals = {
                    "display_name": default["display_name"],
                    "model": default["model"],
                    "temperature": default["temperature"],
                    "max_tokens": default["max_tokens"],
                    "system_prompt": default["system_prompt"],
                    "ic_threshold": default["ic_threshold"],
                    "t_stat_threshold": default["t_stat_threshold"],
                    "auto_archive": default["auto_archive"],
                    "auto_reject": default["auto_reject"],
                    "max_daily_runs": default["max_daily_runs"],
                }
            else:
                current_vals = {
                    "display_name": current[0],
                    "model": current[1],
                    "temperature": float(current[2]),
                    "max_tokens": current[3],
                    "system_prompt": current[4],
                    "ic_threshold": float(current[5]),
                    "t_stat_threshold": float(current[6]),
                    "auto_archive": current[7],
                    "auto_reject": current[8],
                    "max_daily_runs": current[9],
                }

            merged = {**current_vals, **{k: v for k, v in payload.items() if k in current_vals}}

            # Mark previous active=FALSE
            cur.execute(
                "UPDATE prompt_history SET is_active = FALSE WHERE agent_name = %s AND is_active = TRUE",
                (name,),
            )

            # INSERT new version active
            cur.execute(
                """
                INSERT INTO prompt_history (
                    agent_name, version, display_name, model, temperature, max_tokens,
                    system_prompt, ic_threshold, t_stat_threshold,
                    auto_archive, auto_reject, max_daily_runs,
                    is_active, reason, created_by
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, %s, 'user')
                """,
                (
                    name,
                    next_version,
                    merged["display_name"],
                    merged["model"],
                    merged["temperature"],
                    merged["max_tokens"],
                    merged["system_prompt"],
                    merged["ic_threshold"],
                    merged["t_stat_threshold"],
                    merged["auto_archive"],
                    merged["auto_reject"],
                    merged["max_daily_runs"],
                    reason or f"user update via PUT /agent/{name}/config",
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    fetched = _fetch_active_config(name)
    if fetched is None:
        raise RuntimeError("post-INSERT 拉 active row 真 None — atomic txn rollback 真 silent fail (铁律 33)")
    return fetched


@router.get("/{name}/config", summary="Agent 配置查询 (DB-persisted prompt_history)")
async def get_agent_config(name: str) -> dict[str, Any]:
    """返回 agent 配置. 走 prompt_history table 真 active row.
    First-run: 0 rows → 自动 seed v1 default + 返.

    Args:
        name: agent 名 (idea / factor / eval / diagnosis).
    """
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")

    try:
        fetched = _fetch_active_config(name)
        if fetched is None:
            # First run: seed v1 from defaults
            return _seed_default_config(name)
        return fetched
    except Exception as exc:
        # P2 fix (python-reviewer Session 57+1 round-4): explicit silent_ok 注释
        # 反 铁律 33 (no silent failure). Degraded mode 真合理 (DB unreachable 时
        # serve in-memory defaults 比 5xx 报错对 frontend dashboard UX 更友好), 但
        # 必须 log WARNING 让 ops 可见 + 显式 # silent_ok 标记防 future 误认 bug.
        logger.warning(  # silent_ok: DB unreachable → degraded-mode defaults (反 5xx user-facing)
            "get_agent_config DB query failed, returning in-memory defaults",
            agent=name,
            error=str(exc),
        )
        return _AGENT_DEFAULT_CONFIGS[name]


@router.put("/{name}/config", summary="Agent 配置更新 (insert new version row)")
async def put_agent_config(
    name: str,
    payload: dict[str, Any],
    _: None = Depends(verify_admin_token),  # P2-1 fix (treat as P1): auth gate on mutation
) -> dict[str, Any]:
    """更新 agent 配置 — 真 INSERT 新 version + mark previous active=FALSE.

    H1 真闭环 (反 LL-183 silent UI lie pattern): 用户改动持久化 to prompt_history.
    Version diff/rollback UI 留 future enhancement.

    Args:
        name: agent 名.
        payload: partial update (任意 fields from AgentConfig schema). reason 可选.
    """
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")

    reason = payload.pop("reason", None) if isinstance(payload, dict) else None
    try:
        return _insert_new_version(name, payload, reason)
    except Exception as exc:
        logger.exception("put_agent_config DB INSERT failed", agent=name)
        raise HTTPException(status_code=500, detail=f"Config update failed: {exc}") from exc


@router.post("/{name}/config/reset", summary="Agent 配置重置 (insert version row from defaults)")
async def reset_agent_config(
    name: str,
    _: None = Depends(verify_admin_token),  # P2-1 fix: auth gate
) -> dict[str, Any]:
    """重置 agent 配置 — INSERT 新 version row with default values."""
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")

    default = _AGENT_DEFAULT_CONFIGS[name]
    try:
        return _insert_new_version(name, dict(default), "reset to default")
    except Exception as exc:
        logger.exception("reset_agent_config DB INSERT failed", agent=name)
        raise HTTPException(status_code=500, detail=f"Config reset failed: {exc}") from exc


@router.get("/{name}/history", summary="Agent prompt 版本历史 (last N versions)")
async def get_agent_history(
    name: str,
    limit: int = Query(default=20, ge=1, le=100),  # P3 fix: explicit bounds (反 unbounded sql LIMIT)
    _: None = Depends(verify_admin_token),  # P2-2 fix (treat P1): 反 prompt enumeration leak
) -> list[dict[str, Any]]:
    """返回 last N 版本 prompt_history rows (newest first)."""
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT agent_name, version, display_name, model, temperature, max_tokens,
                       system_prompt, ic_threshold, t_stat_threshold,
                       auto_archive, auto_reject, max_daily_runs,
                       is_active, reason, created_at, created_by
                FROM prompt_history
                WHERE agent_name = %s
                ORDER BY version DESC LIMIT %s
                """,
                (name, limit),
            )
            return [_row_to_config(row) for row in cur.fetchall()]
    finally:
        conn.close()


@router.post("/{name}/config/rollback", summary="Agent 配置 rollback 至历史 version")
async def rollback_agent_config(
    name: str,
    version: int,
    reason: str | None = None,
    _: None = Depends(verify_admin_token),  # P2-1 fix: auth gate on mutation
) -> dict[str, Any]:
    """Rollback 至 prompt_history 指定 version. 策略: INSERT 新 version row (copy from target)
    + mark previous active=FALSE (atomic txn, 沿用 _insert_new_version 体例).

    反 ' destructive overwrite ' (沿用 ADR-022): 旧 version row 真**保留**, 不真 UPDATE 旧 row.
    audit trail real (反 retroactive edit).

    Args:
        name: agent 名 (idea/factor/eval/diagnosis).
        version: target version 号 (从 /history 拉的 version 字段).
        reason: rollback 理由 (optional, audit trail).
    """
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")
    if version < 1:
        raise HTTPException(status_code=400, detail="version 必须 >= 1")

    # P1 atomic rollback (python-reviewer Session 57+1 2026-05-19):
    # 走 _insert_new_version(source_version=version) — 单 connection / 单 advisory
    # lock / 单 txn 内做 SELECT (target) + INSERT (new) + UPDATE (active flip).
    # 反 旧 2-conn pattern 的 TOCTOU race (外层 SELECT close 到内层 INSERT open 之间
    # 另一 PUT 可改 target row → audit trail corruption).
    rollback_reason = reason or f"rollback to version {version}"
    try:
        return _insert_new_version(
            name,
            {},
            rollback_reason,
            source_version=version,
        )
    except ValueError as exc:
        # version 真不存在 (advisory lock 内 SELECT, strong consistency)
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("rollback_agent_config DB INSERT failed", agent=name, version=version)
        raise HTTPException(status_code=500, detail=f"Rollback failed: {exc}") from exc


@router.get("/model-health", summary="LLM 模型健康检查 (stub)")
async def get_model_health(
    _: None = Depends(verify_admin_token),  # P3-1 fix: 反 model/provider name leak
) -> list[dict[str, Any]]:
    """返回 3 model health stub. 真实施需 backend periodic LLM ping cron."""
    return [
        {
            "model": "deepseek-v4-pro",
            "is_online": True,
            "latency_ms": None,
            "last_checked_at": datetime.now(UTC).isoformat(),
            "error": "stub mode — periodic ping cron 未实施",
        },
        {
            "model": "deepseek-v4-flash",
            "is_online": True,
            "latency_ms": None,
            "last_checked_at": datetime.now(UTC).isoformat(),
            "error": "stub mode",
        },
        {
            "model": "qwen3-local",
            "is_online": False,
            "latency_ms": None,
            "last_checked_at": datetime.now(UTC).isoformat(),
            "error": "stub mode + ollama_chat fallback only (L7 sync: qwen3 → qwen3-local)",
        },
    ]


@router.get("/cost-summary", summary="LLM 成本汇总 (从 llm_call_log 真值)")
async def get_cost_summary(
    month: str | None = None,
    _: None = Depends(verify_admin_token),  # P2 retroactive: cost data 视作 sensitive ops
) -> dict[str, Any]:
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
            "deepseek-v4-flash": {"cost_cny": 0.0, "tokens": 0},
            "deepseek-v4-pro": {"cost_cny": 0.0, "tokens": 0},
            "qwen3-local": {"cost_cny": 0.0, "tokens": 0},
        },
        "daily_usage": [],
        "_note": (
            "Phase I stub. 真实施需 llm_call_log SQL 聚合 (F-S7-001 修复后真值生效, "
            "AI_ASSIST_ENABLED=true 后历史累积).真 prompt version cost decomp "
            "留 backend prompt_history table impl."
        ),
    }


@router.get("/{name}/logs", summary="Agent 调用日志 (stub empty)")
async def get_agent_logs(
    name: str,
    limit: int = Query(default=50, ge=1, le=200),  # P3 fix: explicit bounds (反 large LIMIT)
    _: None = Depends(verify_admin_token),  # P2-2 fix: 反 unauthenticated log enumeration
) -> list[dict[str, Any]]:
    """返回 agent 调用 logs. Stub empty — 真实施需 llm_call_log SQL 聚合."""
    if name not in _AGENT_DEFAULT_CONFIGS:
        raise HTTPException(status_code=404, detail=f"Agent {name} 不存在")
    _ = limit  # placeholder, real impl 走 LIMIT clause
    return []
