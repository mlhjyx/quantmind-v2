"""tests for NewsClassifierService — V3§3.2 V4-Flash L0.2 (sub-PR 7b.2 sediment).

scope (mock-only sustained, e2e live + bootstrap wire defer sub-PR 7b.3):
- TestConstructor (5): router DI + prompt path validation + yaml load failures
- TestPromptLoad (4): yaml file missing / non-mapping / missing key / version mismatch
- TestClassifyHappyPath (3): 4 category x 4 profile boundary + cost / fallback
- TestParseResponse (5): JSON parse / schema validate / range / category / fence strip
- TestParseInvalid (5): non-JSON / non-object / missing key / out-of-range / invalid enum
- TestPersist (1): NotImplementedError raise (sub-PR 7b.3 真 wire 留)
- TestStripCodeFence (5): json/plain/uppercase fence + no-fence passthrough + whitespace

沿用 sub-PR 1-6 + 7a + 7b.1 v2 体例 — mock LiteLLM router + yaml load + JSON parse.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from backend.app.services.news.news_classifier_service import (
    DEFAULT_PROMPT_PATH,
    PROMPT_VERSION,
    VALID_CATEGORIES,
    VALID_PROFILES,
    VALID_URGENCIES,
    ClassificationParseError,
    ClassificationResult,
    NewsClassifierService,
    PromptLoadError,
    _strip_code_fence,
)
from backend.qm_platform.llm import LLMResponse, RiskTaskType
from backend.qm_platform.news.base import NewsItem

# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture
def sample_news_item() -> NewsItem:
    """V3§3.1 NewsItem sample (沿用 sub-PR 1-6 schema)."""
    return NewsItem(
        source="zhipu",
        timestamp=datetime(2026, 5, 6, 14, 30, 0, tzinfo=UTC),
        title="贵州茅台业绩超预期",
        content="2026 Q1 净利润同比 +35%, 远超市场预期",
        url="https://example.com/news/1",
        lang="zh",
        symbol_id="600519.SH",
        fetch_cost_usd=Decimal("0.0001"),
        fetch_latency_ms=500,
    )


@pytest.fixture
def mock_router() -> MagicMock:
    """Mock router 沿用 BudgetAwareRouter | LiteLLMRouter completion duck typing."""
    router = MagicMock()
    router.completion.return_value = LLMResponse(
        content='{"sentiment_score": 0.7, "category": "利好", "urgency": "P1", '
        '"confidence": 0.85, "profile": "short"}',
        model="deepseek-v4-flash",
        tokens_in=100,
        tokens_out=50,
        cost_usd=Decimal("0.0015"),
        latency_ms=420.0,
        decision_id="news-uuid-test",
        is_fallback=False,
    )
    return router


@pytest.fixture
def valid_yaml_data() -> dict[str, str]:
    return {
        "version": "v1",
        "system_prompt": "你是金融新闻分类助手...",
        "user_template": "请分析以下新闻: {title}\n{content}\n{source}\n"
        "{timestamp}\n{url}\n{symbol_id}\n{lang}",
    }


@pytest.fixture
def tmp_yaml_prompt(tmp_path: Path, valid_yaml_data: dict[str, str]) -> Path:
    p = tmp_path / "test_prompt.yaml"
    p.write_text(yaml.safe_dump(valid_yaml_data, allow_unicode=True), encoding="utf-8")
    return p


@pytest.fixture
def service(mock_router: MagicMock, tmp_yaml_prompt: Path) -> NewsClassifierService:
    return NewsClassifierService(router=mock_router, prompt_path=tmp_yaml_prompt)


# ─────────────────────────────────────────────────────────────
# TestConstructor
# ─────────────────────────────────────────────────────────────


class TestConstructor:
    def test_loads_default_prompt_path(self, mock_router: MagicMock) -> None:
        # 默认 yaml prompt 路径真存在 — 反需 explicit path 覆盖
        assert DEFAULT_PROMPT_PATH.exists(), (
            f"DEFAULT_PROMPT_PATH 真路径反存在: {DEFAULT_PROMPT_PATH}"
        )
        service = NewsClassifierService(router=mock_router)
        assert service is not None

    def test_accepts_custom_prompt_path(
        self, mock_router: MagicMock, tmp_yaml_prompt: Path
    ) -> None:
        service = NewsClassifierService(router=mock_router, prompt_path=tmp_yaml_prompt)
        assert service is not None

    def test_default_path_is_under_repo_root(self) -> None:
        """resolve from __file__ 真 repo_root/prompts/risk/news_classifier_v1.yaml."""
        assert DEFAULT_PROMPT_PATH.name == "news_classifier_v1.yaml"
        assert DEFAULT_PROMPT_PATH.parent.name == "risk"
        assert DEFAULT_PROMPT_PATH.parent.parent.name == "prompts"

    def test_constants_match_v3_spec(self) -> None:
        """V3§3.2 line 367-371 + news_classified.sql CHECK 锁定 verify."""
        assert PROMPT_VERSION == "v1"
        assert VALID_CATEGORIES == ("利好", "利空", "中性", "事件驱动")
        assert VALID_URGENCIES == ("P0", "P1", "P2", "P3")
        assert VALID_PROFILES == ("ultra_short", "short", "medium", "long")

    def test_router_stored_for_classify(
        self, mock_router: MagicMock, tmp_yaml_prompt: Path
    ) -> None:
        """router DI 真存 — classify 时透传."""
        service = NewsClassifierService(router=mock_router, prompt_path=tmp_yaml_prompt)
        assert service._router is mock_router


# ─────────────────────────────────────────────────────────────
# TestPromptLoad
# ─────────────────────────────────────────────────────────────


class TestPromptLoad:
    def test_missing_file(self, mock_router: MagicMock, tmp_path: Path) -> None:
        bad = tmp_path / "nope.yaml"
        with pytest.raises(PromptLoadError, match="not found"):
            NewsClassifierService(router=mock_router, prompt_path=bad)

    def test_non_mapping_root(self, mock_router: MagicMock, tmp_path: Path) -> None:
        p = tmp_path / "list.yaml"
        p.write_text("- foo\n- bar\n", encoding="utf-8")
        with pytest.raises(PromptLoadError, match="root must be mapping"):
            NewsClassifierService(router=mock_router, prompt_path=p)

    def test_missing_required_key(
        self, mock_router: MagicMock, tmp_path: Path, valid_yaml_data: dict[str, str]
    ) -> None:
        partial = {k: v for k, v in valid_yaml_data.items() if k != "user_template"}
        p = tmp_path / "partial.yaml"
        p.write_text(yaml.safe_dump(partial, allow_unicode=True), encoding="utf-8")
        with pytest.raises(PromptLoadError, match="missing required key 'user_template'"):
            NewsClassifierService(router=mock_router, prompt_path=p)

    def test_version_mismatch(
        self, mock_router: MagicMock, tmp_path: Path, valid_yaml_data: dict[str, str]
    ) -> None:
        valid_yaml_data["version"] = "v999"
        p = tmp_path / "wrong_version.yaml"
        p.write_text(yaml.safe_dump(valid_yaml_data, allow_unicode=True), encoding="utf-8")
        with pytest.raises(PromptLoadError, match="version mismatch"):
            NewsClassifierService(router=mock_router, prompt_path=p)


# ─────────────────────────────────────────────────────────────
# TestClassifyHappyPath
# ─────────────────────────────────────────────────────────────


class TestClassifyHappyPath:
    def test_happy_path_returns_result(
        self, service: NewsClassifierService, sample_news_item: NewsItem
    ) -> None:
        result = service.classify(sample_news_item, decision_id="news-uuid-1")
        assert isinstance(result, ClassificationResult)
        assert result.sentiment_score == Decimal("0.7")
        assert result.category == "利好"
        assert result.urgency == "P1"
        assert result.confidence == Decimal("0.85")
        assert result.profile == "short"
        assert result.classifier_model == "deepseek-v4-flash"
        assert result.classifier_prompt_version == "v1"
        assert result.classifier_cost == Decimal("0.0015")
        assert result.news_id is None  # pre-persist sustained sub-PR 7b.3 真 wire

    def test_router_called_with_news_classify_task(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        service.classify(sample_news_item, decision_id="d-1")
        mock_router.completion.assert_called_once()
        kwargs = mock_router.completion.call_args.kwargs
        assert kwargs["task"] is RiskTaskType.NEWS_CLASSIFY
        assert kwargs["decision_id"] == "d-1"
        messages = kwargs["messages"]
        assert len(messages) == 2
        assert messages[0].role == "system"
        assert messages[1].role == "user"
        assert "贵州茅台" in messages[1].content

    def test_fallback_response_yields_null_cost(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        """Ollama qwen3.5:9b fallback (ADR-031 §6) → classifier_cost = NULL."""
        mock_router.completion.return_value = LLMResponse(
            content='{"sentiment_score": 0.0, "category": "中性", "urgency": "P3", '
            '"confidence": 0.6, "profile": "long"}',
            model="qwen3-local",
            cost_usd=Decimal("0"),
            is_fallback=True,
        )
        result = service.classify(sample_news_item)
        assert result.classifier_cost is None
        assert result.classifier_model == "qwen3-local"


# ─────────────────────────────────────────────────────────────
# TestParseResponse — 4 category × 4 profile boundary
# ─────────────────────────────────────────────────────────────


class TestParseResponse:
    @pytest.mark.parametrize("category", list(VALID_CATEGORIES))
    def test_each_category_accepted(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
        category: str,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": 0.0, "category": "' + category + '", '
                '"urgency": "P2", "confidence": 0.7, "profile": "medium"}'
            ),
            model="deepseek-v4-flash",
            cost_usd=Decimal("0.001"),
            is_fallback=False,
        )
        result = service.classify(sample_news_item)
        assert result.category == category

    @pytest.mark.parametrize("profile", list(VALID_PROFILES))
    def test_each_profile_accepted(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
        profile: str,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": 0.0, "category": "中性", '
                '"urgency": "P2", "confidence": 0.7, "profile": "' + profile + '"}'
            ),
            model="deepseek-v4-flash",
            cost_usd=Decimal("0.001"),
            is_fallback=False,
        )
        result = service.classify(sample_news_item)
        assert result.profile == profile

    @pytest.mark.parametrize("urgency", list(VALID_URGENCIES))
    def test_each_urgency_accepted(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
        urgency: str,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": 0.0, "category": "中性", '
                '"urgency": "' + urgency + '", "confidence": 0.7, "profile": "medium"}'
            ),
            model="deepseek-v4-flash",
            cost_usd=Decimal("0.001"),
            is_fallback=False,
        )
        result = service.classify(sample_news_item)
        assert result.urgency == urgency

    @pytest.mark.parametrize(
        "confidence", ["0", "0.0", "0.5", "1", "1.0"]
    )
    def test_confidence_boundary_accepted(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
        confidence: str,
    ) -> None:
        """confidence [0, 1] edge-inclusive accepted-case (沿用 sentiment 体例 verify)."""
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": 0.0, "category": "中性", '
                '"urgency": "P2", "confidence": ' + confidence + ', "profile": "medium"}'
            ),
            model="deepseek-v4-flash",
            cost_usd=Decimal("0.001"),
            is_fallback=False,
        )
        result = service.classify(sample_news_item)
        assert Decimal("0") <= result.confidence <= Decimal("1")

    @pytest.mark.parametrize(
        "sentiment", ["-1", "-1.0", "0", "0.5", "1", "1.0"]
    )
    def test_sentiment_boundary_accepted(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
        sentiment: str,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": ' + sentiment + ', "category": "中性", '
                '"urgency": "P2", "confidence": 0.7, "profile": "medium"}'
            ),
            model="deepseek-v4-flash",
            cost_usd=Decimal("0.001"),
            is_fallback=False,
        )
        result = service.classify(sample_news_item)
        assert Decimal("-1") <= result.sentiment_score <= Decimal("1")

    def test_response_with_markdown_fence_parsed(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        """V4-Flash 真生产经常 wrap ```json ... ``` markdown fence."""
        mock_router.completion.return_value = LLMResponse(
            content=(
                '```json\n'
                '{"sentiment_score": -0.5, "category": "利空", '
                '"urgency": "P1", "confidence": 0.9, "profile": "ultra_short"}\n'
                '```'
            ),
            model="deepseek-v4-flash",
            cost_usd=Decimal("0.002"),
            is_fallback=False,
        )
        result = service.classify(sample_news_item)
        assert result.category == "利空"
        assert result.urgency == "P1"


# ─────────────────────────────────────────────────────────────
# TestParseInvalid — 沿用铁律 33 fail-loud
# ─────────────────────────────────────────────────────────────


class TestParseInvalid:
    def test_non_json_response_raises(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content="不是 JSON 是纯文本", model="deepseek-v4-flash"
        )
        with pytest.raises(ClassificationParseError, match="not JSON"):
            service.classify(sample_news_item)

    def test_json_array_root_raises(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content='["not", "object"]', model="deepseek-v4-flash"
        )
        with pytest.raises(ClassificationParseError, match="must be JSON object"):
            service.classify(sample_news_item)

    def test_missing_required_key_raises(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content='{"sentiment_score": 0.5, "category": "利好", "urgency": "P1"}',
            model="deepseek-v4-flash",
        )
        with pytest.raises(ClassificationParseError, match="missing keys"):
            service.classify(sample_news_item)

    @pytest.mark.parametrize(
        "sentiment,err_match",
        [
            ("1.5", "sentiment_score 越界"),
            ("-1.5", "sentiment_score 越界"),
            ("2", "sentiment_score 越界"),
        ],
    )
    def test_sentiment_out_of_range_raises(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
        sentiment: str,
        err_match: str,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": ' + sentiment + ', "category": "中性", '
                '"urgency": "P2", "confidence": 0.7, "profile": "medium"}'
            ),
            model="deepseek-v4-flash",
        )
        with pytest.raises(ClassificationParseError, match=err_match):
            service.classify(sample_news_item)

    def test_invalid_category_raises(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": 0.0, "category": "无效类别", '
                '"urgency": "P2", "confidence": 0.7, "profile": "medium"}'
            ),
            model="deepseek-v4-flash",
        )
        with pytest.raises(ClassificationParseError, match="category 不在"):
            service.classify(sample_news_item)

    def test_invalid_urgency_raises(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": 0.0, "category": "中性", '
                '"urgency": "P9", "confidence": 0.7, "profile": "medium"}'
            ),
            model="deepseek-v4-flash",
        )
        with pytest.raises(ClassificationParseError, match="urgency 不在"):
            service.classify(sample_news_item)

    def test_invalid_profile_raises(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": 0.0, "category": "中性", '
                '"urgency": "P2", "confidence": 0.7, "profile": "forever"}'
            ),
            model="deepseek-v4-flash",
        )
        with pytest.raises(ClassificationParseError, match="profile 不在"):
            service.classify(sample_news_item)

    def test_confidence_out_of_range_raises(
        self,
        service: NewsClassifierService,
        sample_news_item: NewsItem,
        mock_router: MagicMock,
    ) -> None:
        mock_router.completion.return_value = LLMResponse(
            content=(
                '{"sentiment_score": 0.0, "category": "中性", '
                '"urgency": "P2", "confidence": 1.5, "profile": "medium"}'
            ),
            model="deepseek-v4-flash",
        )
        with pytest.raises(ClassificationParseError, match="confidence 越界"):
            service.classify(sample_news_item)


# ─────────────────────────────────────────────────────────────
# TestPersist — sub-PR 7b.3 真 wire 留 NotImplementedError
# ─────────────────────────────────────────────────────────────


class TestPersist:
    """sub-PR 7b.3 v2 (#242) 真 wire — INSERT INTO news_classified ON CONFLICT DO UPDATE."""

    def _make_result(self) -> ClassificationResult:
        return ClassificationResult(
            sentiment_score=Decimal("0.5"),
            category="利好",
            urgency="P1",
            confidence=Decimal("0.8"),
            profile="short",
            classifier_model="deepseek-v4-flash",
            classifier_prompt_version="v1",
            classifier_cost=Decimal("0.0015"),
            news_id=None,
        )

    def test_persist_raises_when_news_id_missing(
        self, service: NewsClassifierService
    ) -> None:
        """news_id=None pre-persist 真 fail-loud (反 silent skip row corrupt 铁律 33)."""
        result = self._make_result()
        mock_conn = MagicMock()
        with pytest.raises(ValueError, match="news_id 真 None"):
            service.persist(result, conn=mock_conn)
        mock_conn.cursor.assert_not_called()  # 反 SQL 已 emit

    def test_persist_uses_explicit_news_id_kwarg(
        self, service: NewsClassifierService
    ) -> None:
        """news_id 真 kwarg → 走 INSERT ... VALUES (news_id=given, ...)."""
        result = self._make_result()
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        service.persist(result, conn=mock_conn, news_id=12345)

        mock_conn.cursor.assert_called_once()
        mock_cursor.execute.assert_called_once()
        sql, params = mock_cursor.execute.call_args.args
        assert "INSERT INTO news_classified" in sql
        assert "ON CONFLICT (news_id) DO UPDATE" in sql
        assert "classified_at = NOW()" in sql
        assert params[0] == 12345  # news_id 真 first column
        assert params[1] == Decimal("0.5")  # sentiment_score
        assert params[2] == "利好"  # category
        assert params[3] == "P1"  # urgency
        assert params[4] == Decimal("0.8")  # confidence
        assert params[5] == "short"  # profile
        assert params[6] == "deepseek-v4-flash"  # classifier_model
        assert params[7] == "v1"  # classifier_prompt_version
        assert params[8] == Decimal("0.0015")  # classifier_cost

    def test_persist_falls_back_to_result_news_id(
        self, service: NewsClassifierService
    ) -> None:
        """news_id kwarg 真 None → 走 result.news_id (caller pre-填 news_id 真模式)."""
        result = ClassificationResult(
            sentiment_score=Decimal("0"),
            category="中性",
            urgency="P3",
            confidence=Decimal("0.5"),
            profile="long",
            classifier_model="qwen3-local",
            classifier_prompt_version="v1",
            classifier_cost=None,  # Ollama fallback
            news_id=99999,
        )
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        service.persist(result, conn=mock_conn)

        params = mock_cursor.execute.call_args.args[1]
        assert params[0] == 99999
        assert params[8] is None  # classifier_cost NULL = Ollama fallback

    def test_persist_does_not_commit(
        self, service: NewsClassifierService
    ) -> None:
        """铁律 32 Service 不 commit — caller 真事务边界管理者."""
        result = self._make_result()
        mock_cursor = MagicMock()
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

        service.persist(result, conn=mock_conn, news_id=1)

        mock_conn.commit.assert_not_called()
        mock_conn.rollback.assert_not_called()


# ─────────────────────────────────────────────────────────────
# TestBootstrap (sub-PR 7b.3 v2 #242 — get_news_classifier factory)
# ─────────────────────────────────────────────────────────────


class TestBootstrap:
    """get_news_classifier + reset_news_classifier 体例 (沿用 alert.py:528-554)."""

    def test_factory_returns_singleton(self, mock_router: MagicMock) -> None:
        from backend.app.services.news import (
            get_news_classifier,
            reset_news_classifier,
        )
        reset_news_classifier()
        try:
            c1 = get_news_classifier(router=mock_router)
            c2 = get_news_classifier(router=mock_router)
            assert c1 is c2  # process-level singleton sustained
        finally:
            reset_news_classifier()

    def test_factory_accepts_pre_built_router(
        self, mock_router: MagicMock
    ) -> None:
        from backend.app.services.news import (
            NewsClassifierService,
            get_news_classifier,
            reset_news_classifier,
        )
        reset_news_classifier()
        try:
            classifier = get_news_classifier(router=mock_router)
            assert isinstance(classifier, NewsClassifierService)
            assert classifier._router is mock_router
        finally:
            reset_news_classifier()

    def test_reset_clears_singleton(self, mock_router: MagicMock) -> None:
        from backend.app.services.news import (
            get_news_classifier,
            reset_news_classifier,
        )
        reset_news_classifier()
        c1 = get_news_classifier(router=mock_router)
        reset_news_classifier()
        c2 = get_news_classifier(router=mock_router)
        assert c1 is not c2  # 反 singleton 真 reset
        reset_news_classifier()


# ─────────────────────────────────────────────────────────────
# TestE2ELive — V4-Flash 真生产 API call (requires_litellm_e2e marker)
# ─────────────────────────────────────────────────────────────

import os  # noqa: E402 — pytest marker block


@pytest.mark.requires_litellm_e2e
@pytest.mark.skipif(
    not os.getenv("DEEPSEEK_API_KEY"),
    reason="DEEPSEEK_API_KEY env missing (沿用 sub-PR 1-6 + 7a + 7b.2 marker auto-skip 体例)",
)
class TestE2ELive:
    """V4-Flash 真生产 + DB UPSERT (mock conn capture SQL, 反 quota burn minimal payload).

    红线 sustained: LIVE_TRADING_DISABLED=true / EXECUTION_MODE=paper / minimal payload.
    """

    def test_e2e_classify_real_v4_flash_minimal_payload(
        self, sample_news_item: NewsItem
    ) -> None:
        """real DeepSeek V4-Flash API call → ClassificationResult (反 quota burn)."""
        from backend.app.services.news import get_news_classifier, reset_news_classifier
        from backend.qm_platform.llm import reset_llm_router

        reset_llm_router()
        reset_news_classifier()
        try:
            classifier = get_news_classifier()  # conn_factory=None 走降级 mode
            result = classifier.classify(
                sample_news_item, decision_id="e2e-live-7b.3-v2-test"
            )

            assert isinstance(result, ClassificationResult)
            assert result.category in VALID_CATEGORIES
            assert result.urgency in VALID_URGENCIES
            assert result.profile in VALID_PROFILES
            assert Decimal("-1") <= result.sentiment_score <= Decimal("1")
            assert Decimal("0") <= result.confidence <= Decimal("1")
            assert result.classifier_prompt_version == "v1"
            # V4-Flash 真生产 → cost > 0 OR Ollama fallback (cost=NULL)
            if not result.classifier_model.startswith("qwen3"):
                assert result.classifier_cost is None or result.classifier_cost >= 0
        finally:
            reset_llm_router()
            reset_news_classifier()

    def test_e2e_classify_then_persist_full_path(
        self, sample_news_item: NewsItem
    ) -> None:
        """real V4-Flash → ClassificationResult → persist UPSERT SQL emit (mock conn).

        反 真 DB 接触 (test infrastructure decoupling sustained sub-PR 1-6 体例),
        但 SQL emit verify 真**news_classified DDL 沿用 sub-PR 7b.1 v2 #240** sustained.
        """
        from backend.app.services.news import get_news_classifier, reset_news_classifier
        from backend.qm_platform.llm import reset_llm_router

        reset_llm_router()
        reset_news_classifier()
        try:
            classifier = get_news_classifier()
            result = classifier.classify(
                sample_news_item, decision_id="e2e-live-7b.3-v2-persist-test"
            )

            mock_cursor = MagicMock()
            mock_conn = MagicMock()
            mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

            classifier.persist(result, conn=mock_conn, news_id=42)

            sql = mock_cursor.execute.call_args.args[0]
            params = mock_cursor.execute.call_args.args[1]
            assert "INSERT INTO news_classified" in sql
            assert "ON CONFLICT (news_id) DO UPDATE" in sql
            assert params[0] == 42
            mock_conn.commit.assert_not_called()  # 铁律 32 sustained
        finally:
            reset_llm_router()
            reset_news_classifier()


# ─────────────────────────────────────────────────────────────
# TestStripCodeFence (内部 helper)
# ─────────────────────────────────────────────────────────────


class TestStripCodeFence:
    def test_strip_json_fence(self) -> None:
        raw = '```json\n{"a": 1}\n```'
        assert _strip_code_fence(raw) == '{"a": 1}'

    def test_strip_plain_fence(self) -> None:
        raw = '```\n{"b": 2}\n```'
        assert _strip_code_fence(raw) == '{"b": 2}'

    def test_no_fence_passthrough(self) -> None:
        raw = '{"c": 3}'
        assert _strip_code_fence(raw) == '{"c": 3}'

    def test_uppercase_fence(self) -> None:
        raw = '```JSON\n{"d": 4}\n```'
        assert _strip_code_fence(raw) == '{"d": 4}'

    def test_whitespace_around_fence(self) -> None:
        raw = '   \n```json\n{"e": 5}\n```\n   '
        assert _strip_code_fence(raw) == '{"e": 5}'
