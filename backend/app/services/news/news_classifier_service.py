"""NewsClassifierService — V3§3.2 NewsClassifier V4-Flash L0.2 实现 (sub-PR 7b.2).

scope (sub-PR 7b.2):
- yaml prompt load (prompts/risk/news_classifier_v1.yaml)
- LLM call 走 BudgetAwareRouter | LiteLLMRouter DI (sustained ADR-031 §6 + ADR-032)
- JSON parse + 4 profile + 4 category + 4 urgency + sentiment_score + confidence schema validate
- ClassificationResult dataclass 沿用 V3§3.2 line 365-376 + sub-PR 7b.1 v2 news_classified DDL
- persist hook stub = NotImplementedError (sub-PR 7b.3 真 wire conn_factory + DataPipeline)

V3§3.2 schema (line 365-376):
- sentiment_score: NUMERIC(5,4) [-1, 1]
- category: VARCHAR(20) ∈ {利好/利空/中性/事件驱动}
- urgency: VARCHAR(4) ∈ {P0/P1/P2/P3}
- confidence: NUMERIC(5,4) [0, 1]
- profile: VARCHAR(20) ∈ {ultra_short/short/medium/long}
- classifier_model: VARCHAR(50)
- classifier_prompt_version: VARCHAR(10) (本服务 = "v1")
- classifier_cost: NUMERIC(8,4) NULLABLE (NULL = Ollama fallback, ADR-031 §6 灾备)

LLM routing (ADR-031 §6 + ADR-035 §2):
- task = RiskTaskType.NEWS_CLASSIFY
- alias = "deepseek-v4-flash" (router.py:57 sediment, 0 智谱 alias)
- fallback = "qwen3-local" (Ollama qwen3.5:9b, ADR-034)

caller 真**唯一 sanctioned 入口** (沿用 ADR-032 + bootstrap.py docstring line 82):
    from backend.qm_platform.llm import get_llm_router
    from backend.app.services.news import NewsClassifierService

    router = get_llm_router(conn_factory=app_conn_factory)  # sub-PR 7b.3 真 wire
    service = NewsClassifierService(router=router)
    result = service.classify(news_item, decision_id="news-uuid-xxx")
    # result.persist(conn) — sub-PR 7b.3 真 wire (本 PR raise NotImplementedError)

关联铁律:
- 17 (DataPipeline 入库 — persist hook 留 sub-PR 7b.3 真 wire)
- 22 (文档跟随代码 — ADR-031 §6 patch sediment 同 PR)
- 25 (改什么读什么 — Phase 0/1 5 doc + V3 + ADR fresh verify sustained)
- 33 (fail-loud — JSON parse / schema validate / NotImplementedError)
- 34 (Config SSOT — yaml prompt path 走 module 级常量, 反 hardcode)
- 41 (timezone — NewsItem.timestamp tz-aware, sustained sub-PR 1-6 sediment)

关联文档:
- V3§3.2 line 359-393 (NewsClassifier V4-Flash 完整 schema sediment)
- V3 line 1223 (NewsClassifierService backend/app/services/news/ 真预约 path)
- V3 line 390 (prompts/risk/news_classifier_v1.yaml 真预约 yaml)
- ADR-031 §6 line 133 "Sprint 后续" (caller wire defer 真预约 sediment)
- ADR-035 §2 (V4 路由层 0 智谱 alias, NewsClassifier 走 deepseek-v4-flash)
- backend/migrations/2026_05_06_news_classified.sql (sub-PR 7b.1 v2 DDL sediment)
- backend/qm_platform/llm/types.py:31 (RiskTaskType.NEWS_CLASSIFY enum)
- backend/qm_platform/llm/_internal/router.py:57 (TASK_TO_MODEL_ALIAS sediment)
- backend/qm_platform/news/base.py (NewsItem schema, sub-PR 1 sediment)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from backend.qm_platform.llm import LLMMessage, LLMResponse, RiskTaskType

if TYPE_CHECKING:
    from backend.qm_platform.news.base import NewsItem

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 常量 (V3§3.2 line 365-376 + sub-PR 7b.1 v2 DDL CHECK 锁定)
# ─────────────────────────────────────────────────────────────

PROMPT_VERSION: str = "v1"
"""yaml prompt version (沿用 V3 line 390 真预约 prompts/risk/news_classifier_v1.yaml)."""

VALID_CATEGORIES: tuple[str, ...] = ("利好", "利空", "中性", "事件驱动")
"""V3§3.2 line 368 + news_classified.sql:49 CHECK 锁定 4 category."""

VALID_URGENCIES: tuple[str, ...] = ("P0", "P1", "P2", "P3")
"""V3§3.2 line 369 + news_classified.sql:51 CHECK 锁定 4 urgency."""

VALID_PROFILES: tuple[str, ...] = ("ultra_short", "short", "medium", "long")
"""V3§3.2 line 371 + 381-386 + news_classified.sql:55 CHECK 锁定 4 profile."""

DEFAULT_PROMPT_PATH: Path = (
    Path(__file__).resolve().parents[4] / "prompts" / "risk" / "news_classifier_v1.yaml"
)
"""默认 yaml prompt 路径 — repo_root/prompts/risk/news_classifier_v1.yaml.

resolve from __file__: backend/app/services/news/news_classifier_service.py
parents[0]=news, [1]=services, [2]=app, [3]=backend, [4]=repo_root.
"""

# ─────────────────────────────────────────────────────────────
# Errors (沿用铁律 33 fail-loud)
# ─────────────────────────────────────────────────────────────


class PromptLoadError(RuntimeError):
    """yaml prompt 加载或 schema 失败 (沿用铁律 33+34)."""


class ClassificationParseError(RuntimeError):
    """LLM 响应 JSON parse 或 schema validate 失败 (沿用铁律 33).

    caller 接住 → audit log + 走下一 NewsItem (反 silent skip + 反 入库 corrupt row).
    """

    def __init__(self, message: str, *, raw_content: str | None = None) -> None:
        super().__init__(message)
        self.raw_content = raw_content


# ─────────────────────────────────────────────────────────────
# Output schema (V3§3.2 line 365-376 + news_classified DDL 沿用)
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """V3§3.2 NewsClassifier output schema (line 365-376) + news_classified DDL 对齐.

    Fields align 1:1 to news_classified DDL columns (sub-PR 7b.1 v2 sediment):
    - news_id: BIGINT FK news_raw(news_id) — None 时表示 pre-persist (sub-PR 7b.3 真 wire 时填补)
    - sentiment_score: NUMERIC(5,4) [-1, 1]
    - category: VARCHAR(20) ∈ VALID_CATEGORIES
    - urgency: VARCHAR(4) ∈ VALID_URGENCIES
    - confidence: NUMERIC(5,4) [0, 1]
    - profile: VARCHAR(20) ∈ VALID_PROFILES
    - classifier_model: VARCHAR(50) (LLMResponse.model 真返)
    - classifier_prompt_version: VARCHAR(10) (本服务 PROMPT_VERSION)
    - classifier_cost: NUMERIC(8,4) NULLABLE (None = Ollama fallback, ADR-031 §6)

    NOTE: classified_at (TIMESTAMPTZ DEFAULT NOW()) 由 DB 真生成,
    本 dataclass 反携带 (DataPipeline 入库时填补, sub-PR 7b.3 真 wire).
    """

    sentiment_score: Decimal
    category: str
    urgency: str
    confidence: Decimal
    profile: str
    classifier_model: str
    classifier_prompt_version: str
    classifier_cost: Decimal | None
    news_id: int | None = None  # pre-persist None, sub-PR 7b.3 真 wire 时填补


# ─────────────────────────────────────────────────────────────
# Router protocol (DI 体例, BudgetAwareRouter | LiteLLMRouter 0 继承耦合)
# ─────────────────────────────────────────────────────────────


class _RouterProtocol(Protocol):
    """LiteLLMRouter | BudgetAwareRouter 共通 completion interface (沿用 duck typing)."""

    def completion(
        self,
        task: RiskTaskType,
        messages: list[LLMMessage] | list[dict[str, str]],
        *,
        decision_id: str | None = ...,
        **kwargs: Any,
    ) -> LLMResponse: ...


# ─────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────


class NewsClassifierService:
    """V3§3.2 NewsClassifier V4-Flash L0.2 服务 — yaml prompt + LLM call + JSON parse.

    DI 体例 (反 hidden coupling get_llm_router 内调):
        from backend.qm_platform.llm import get_llm_router
        from backend.app.services.news import NewsClassifierService

        router = get_llm_router(conn_factory=app_conn_factory)  # sub-PR 7b.3 真 wire
        service = NewsClassifierService(router=router)
        result = service.classify(news_item, decision_id="news-uuid-xxx")

    sub-PR 7b.2 scope = classify(NewsItem) → ClassificationResult.
    sub-PR 7b.3 scope = persist(result, conn) → DataPipeline 入库 news_classified.
    """

    def __init__(
        self,
        router: _RouterProtocol,
        *,
        prompt_path: Path | None = None,
    ) -> None:
        """Initialize NewsClassifierService.

        Args:
            router: BudgetAwareRouter | LiteLLMRouter (沿用 get_llm_router factory 真返).
            prompt_path: optional yaml prompt path 覆盖 (默认 DEFAULT_PROMPT_PATH).

        Raises:
            PromptLoadError: yaml file 不存在 / parse 失败 / schema 缺 required key.
        """
        self._router = router
        self._prompt = self._load_prompt(prompt_path or DEFAULT_PROMPT_PATH)

    @staticmethod
    def _load_prompt(path: Path) -> dict[str, Any]:
        """Load + validate yaml prompt schema.

        required keys: version (str) / system_prompt (str) / user_template (str).

        Raises:
            PromptLoadError: file IO / yaml parse / schema 不全 (沿用铁律 33).
        """
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError as e:
            raise PromptLoadError(f"yaml prompt file not found: {path}") from e
        except yaml.YAMLError as e:
            raise PromptLoadError(f"yaml prompt parse failed: {path} ({e})") from e

        if not isinstance(data, dict):
            raise PromptLoadError(
                f"yaml prompt root must be mapping, got {type(data).__name__}: {path}"
            )

        required = ("version", "system_prompt", "user_template")
        for key in required:
            if key not in data:
                raise PromptLoadError(
                    f"yaml prompt missing required key '{key}' at {path}"
                )
            if not isinstance(data[key], str):
                raise PromptLoadError(
                    f"yaml prompt key '{key}' must be str, got "
                    f"{type(data[key]).__name__}: {path}"
                )

        if data["version"] != PROMPT_VERSION:
            raise PromptLoadError(
                f"yaml prompt version mismatch: file={data['version']}, "
                f"expected={PROMPT_VERSION} at {path}"
            )

        return data

    def classify(
        self,
        item: NewsItem,
        *,
        decision_id: str | None = None,
    ) -> ClassificationResult:
        """Classify a NewsItem → ClassificationResult.

        Args:
            item: NewsItem (sub-PR 1-6 sediment, NewsFetcher 真返).
            decision_id: optional caller-traceable id (S2.3 audit trail 真依赖).

        Returns:
            ClassificationResult (V3§3.2 line 365-376 schema, news_id=None pre-persist).

        Raises:
            ClassificationParseError: LLM 响应非 JSON / schema validate 失败 / 范围越界
                                      (沿用铁律 33, caller 接住 → audit log + skip).
        """
        messages = self._build_messages(item)

        response = self._router.completion(
            task=RiskTaskType.NEWS_CLASSIFY,
            messages=messages,
            decision_id=decision_id,
        )

        return self._parse_response(response)

    def _build_messages(self, item: NewsItem) -> list[LLMMessage]:
        """Build LLM messages from NewsItem + yaml prompt template."""
        system_content = self._prompt["system_prompt"]
        user_content = self._prompt["user_template"].format(
            source=item.source,
            timestamp=item.timestamp.isoformat(),
            title=item.title,
            content=(item.content or ""),
            url=(item.url or ""),
            symbol_id=(item.symbol_id or ""),
            lang=item.lang,
        )
        return [
            LLMMessage(role="system", content=system_content),
            LLMMessage(role="user", content=user_content),
        ]

    def _parse_response(self, response: LLMResponse) -> ClassificationResult:
        """Parse LLM response → ClassificationResult + schema validate.

        Handles markdown code fence (```json ... ```) — V4-Flash 真生产经常 fence
        反 raw JSON.

        Raises:
            ClassificationParseError: 沿用铁律 33 fail-loud (caller 接住 audit + skip).
        """
        raw = response.content or ""
        json_text = _strip_code_fence(raw)

        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError as e:
            raise ClassificationParseError(
                f"LLM response not JSON: {e}", raw_content=raw
            ) from e

        if not isinstance(payload, dict):
            raise ClassificationParseError(
                f"LLM response must be JSON object, got {type(payload).__name__}",
                raw_content=raw,
            )

        # 6 required keys (V3§3.2 line 365-376)
        required = (
            "sentiment_score", "category", "urgency",
            "confidence", "profile",
        )
        missing = [k for k in required if k not in payload]
        if missing:
            raise ClassificationParseError(
                f"LLM response missing keys: {missing}", raw_content=raw
            )

        # Schema validate (沿用 news_classified.sql CHECK 锁定)
        sentiment = _to_decimal(payload["sentiment_score"], "sentiment_score", raw)
        if not (Decimal("-1") <= sentiment <= Decimal("1")):
            raise ClassificationParseError(
                f"sentiment_score 越界 [-1, 1]: {sentiment}", raw_content=raw
            )

        confidence = _to_decimal(payload["confidence"], "confidence", raw)
        if not (Decimal("0") <= confidence <= Decimal("1")):
            raise ClassificationParseError(
                f"confidence 越界 [0, 1]: {confidence}", raw_content=raw
            )

        category = str(payload["category"])
        if category not in VALID_CATEGORIES:
            raise ClassificationParseError(
                f"category 不在 {VALID_CATEGORIES}: {category!r}", raw_content=raw
            )

        urgency = str(payload["urgency"])
        if urgency not in VALID_URGENCIES:
            raise ClassificationParseError(
                f"urgency 不在 {VALID_URGENCIES}: {urgency!r}", raw_content=raw
            )

        profile = str(payload["profile"])
        if profile not in VALID_PROFILES:
            raise ClassificationParseError(
                f"profile 不在 {VALID_PROFILES}: {profile!r}", raw_content=raw
            )

        # cost: NULL = Ollama fallback (LLMResponse.is_fallback / cost_usd=0)
        cost: Decimal | None
        if response.is_fallback or response.cost_usd <= 0:
            cost = None  # NULL in news_classified.classifier_cost
        else:
            cost = response.cost_usd

        return ClassificationResult(
            sentiment_score=sentiment,
            category=category,
            urgency=urgency,
            confidence=confidence,
            profile=profile,
            classifier_model=response.model,
            classifier_prompt_version=PROMPT_VERSION,
            classifier_cost=cost,
            news_id=None,  # pre-persist, sub-PR 7b.3 真 wire 时填补
        )

    def persist(
        self,
        result: ClassificationResult,
        *,
        conn: Any,
        news_id: int | None = None,
    ) -> None:
        """Persist ClassificationResult → news_classified 表 (UPSERT, FK news_raw).

        sub-PR 7b.3 v2 sediment (#242) — 真 wire 沿用 sub-PR 7b.1 v2 #240 DDL FK CASCADE.

        Args:
            result: ClassificationResult (NewsClassifierService.classify 真返).
            conn: psycopg2 connection (caller 真**事务边界管理者**, 铁律 32 sustained).
            news_id: optional FK → news_raw(news_id). 默认走 result.news_id (pre-persist
                None 沿用 caller 真**先 INSERT news_raw 取 news_id 后** persist 体例,
                沿用 sub-PR 7c NewsIngestionService orchestrator 真预约 wire pattern).

        Raises:
            ValueError: news_id 真 None (反 silent skip pre-persist row corrupt, 铁律 33).

        Note (铁律 32 Service 不 commit sustained):
            本 service 走 conn 真 cursor + execute, **0 conn.commit() / 0 conn.rollback()**.
            caller (sub-PR 7c NewsIngestionService) 真**事务边界管理者** — 沿用 ADR-032
            line 36 真预约 conn_factory + 真生产 application bootstrap wire 体例.

        Note (idempotent UPSERT, 沿用 sub-PR 7b.1 v2 #240 DDL FK CASCADE):
            ON CONFLICT (news_id) DO UPDATE SET ... — 1:1 mapping (单 NewsItem → 单
            ClassificationResult). 反复 classify 同 news_id 真**最后一次 win**, classified_at
            刷 NOW() (DB clock 服务器时区, 铁律 41).
        """
        nid = news_id if news_id is not None else result.news_id
        if nid is None:
            raise ValueError(
                "news_id 真 None (反 silent skip pre-persist row corrupt, 铁律 33). "
                "caller 真**先 INSERT news_raw 取 news_id 后** persist 体例 "
                "(沿用 sub-PR 7c NewsIngestionService orchestrator 真预约 V3 line 1222)"
            )

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO news_classified (
                    news_id, sentiment_score, category, urgency, confidence,
                    profile, classifier_model, classifier_prompt_version,
                    classifier_cost
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (news_id) DO UPDATE SET
                    sentiment_score = EXCLUDED.sentiment_score,
                    category = EXCLUDED.category,
                    urgency = EXCLUDED.urgency,
                    confidence = EXCLUDED.confidence,
                    profile = EXCLUDED.profile,
                    classifier_model = EXCLUDED.classifier_model,
                    classifier_prompt_version = EXCLUDED.classifier_prompt_version,
                    classifier_cost = EXCLUDED.classifier_cost,
                    classified_at = NOW()
                """,
                (
                    nid,
                    result.sentiment_score,
                    result.category,
                    result.urgency,
                    result.confidence,
                    result.profile,
                    result.classifier_model,
                    result.classifier_prompt_version,
                    result.classifier_cost,
                ),
            )


# ─────────────────────────────────────────────────────────────
# 内部 helpers
# ─────────────────────────────────────────────────────────────

_CODE_FENCE_RE = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n(?P<body>.*?)\n```\s*$",
    re.DOTALL,
)


def _strip_code_fence(text: str) -> str:
    """Strip ```json ... ``` markdown fence — V4-Flash 真生产常见 wrap."""
    m = _CODE_FENCE_RE.match(text.strip())
    if m:
        return m.group("body").strip()
    return text.strip()


def _to_decimal(value: Any, field_name: str, raw: str) -> Decimal:
    """Coerce numeric value to Decimal (反 float precision drift)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except (ValueError, ArithmeticError) as e:
            raise ClassificationParseError(
                f"{field_name} 反 numeric: {value!r} ({e})", raw_content=raw
            ) from e
    raise ClassificationParseError(
        f"{field_name} type 不支持: {type(value).__name__}", raw_content=raw
    )
