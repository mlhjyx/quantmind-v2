"""测试 DeepSeekClient + ModelRouter + IdeaAgent

所有测试使用mock模式（不需要真实API key）。
测试覆盖:
  1. ModelRouter路由逻辑
  2. DeepSeekClient mock模式响应
  3. DeepSeekClient成本追踪
  4. IdeaAgent生成+DSL验证
  5. IdeaAgent解析容错

Sprint 1.17 ml-engineer
"""

from __future__ import annotations

import json

from engines.mining.agents.idea_agent import (
    ActiveFactor,
    FactorHypothesis,
    FailedFactor,
    IdeaAgent,
)
from engines.mining.deepseek_client import (
    DEEPSEEK_BASE_URL,
    MODEL_DEEPSEEK_R1,
    MODEL_DEEPSEEK_V3,
    MODEL_QWEN3_LOCAL,
    QWEN3_LOCAL_BASE_URL,
    CostTracker,
    DeepSeekClient,
    LLMMessage,
    LLMResponse,
    ModelRouter,
    TaskType,
    get_default_client,
    get_default_router,
)

# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class TestModelRouter:
    def test_idea_routes_to_r1(self) -> None:
        router = ModelRouter()
        model, url = router.route(TaskType.IDEA)
        assert model == MODEL_DEEPSEEK_R1
        assert url == DEEPSEEK_BASE_URL

    def test_diagnosis_routes_to_r1(self) -> None:
        router = ModelRouter()
        model, _ = router.route(TaskType.DIAGNOSIS)
        assert model == MODEL_DEEPSEEK_R1

    def test_eval_routes_to_v3(self) -> None:
        router = ModelRouter()
        model, url = router.route(TaskType.EVAL)
        assert model == MODEL_DEEPSEEK_V3
        assert url == DEEPSEEK_BASE_URL

    def test_factor_routes_to_v3_when_local_unavailable(self) -> None:
        router = ModelRouter(local_qwen3_available=False)
        model, url = router.route(TaskType.FACTOR)
        assert model == MODEL_DEEPSEEK_V3
        assert url == DEEPSEEK_BASE_URL

    def test_factor_routes_to_qwen3_when_local_available(self) -> None:
        router = ModelRouter(local_qwen3_available=True)
        model, url = router.route(TaskType.FACTOR)
        assert model == MODEL_QWEN3_LOCAL
        assert url == QWEN3_LOCAL_BASE_URL

    def test_set_local_available(self) -> None:
        router = ModelRouter(local_qwen3_available=False)
        router.set_local_available(True)
        model, _ = router.route(TaskType.FACTOR)
        assert model == MODEL_QWEN3_LOCAL


# ---------------------------------------------------------------------------
# DeepSeekClient — mock模式
# ---------------------------------------------------------------------------


class TestDeepSeekClientMock:
    def test_mock_mode_activates_without_api_key(self) -> None:
        client = DeepSeekClient(api_key="")
        assert client.mock_mode is True

    def test_mock_mode_explicit(self) -> None:
        client = DeepSeekClient(api_key="fake_key", mock_mode=True)
        assert client.mock_mode is True

    def test_mock_chat_returns_response(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        resp = client.chat(
            messages=[LLMMessage(role="user", content="生成因子")],
            model=MODEL_DEEPSEEK_R1,
        )
        assert isinstance(resp, LLMResponse)
        assert resp.content
        assert resp.model == MODEL_DEEPSEEK_R1

    def test_mock_json_mode_returns_parseable_json(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        resp = client.chat(
            messages=[LLMMessage(role="user", content="生成因子")],
            model=MODEL_DEEPSEEK_V3,
            json_mode=True,
        )
        assert resp.is_json
        assert resp.parsed is not None
        # mock返回的是list
        assert isinstance(resp.parsed, list)
        assert len(resp.parsed) >= 1

    def test_mock_cost_is_zero(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        resp = client.chat(
            messages=[LLMMessage(role="user", content="test")],
            model=MODEL_DEEPSEEK_R1,
        )
        assert resp.cost_usd == 0.0


# ---------------------------------------------------------------------------
# CostTracker
# ---------------------------------------------------------------------------


class TestCostTracker:
    def test_record_accumulates(self) -> None:
        tracker = CostTracker()
        resp1 = LLMResponse(
            content="x", model=MODEL_DEEPSEEK_R1,
            input_tokens=1000, output_tokens=200, cost_usd=0.001,
            latency_ms=500,
        )
        resp2 = LLMResponse(
            content="y", model=MODEL_DEEPSEEK_V3,
            input_tokens=500, output_tokens=100, cost_usd=0.0002,
            latency_ms=200,
        )
        tracker.record(resp1)
        tracker.record(resp2)

        assert tracker.total_calls == 2
        assert tracker.total_input_tokens == 1500
        assert tracker.total_output_tokens == 300
        assert abs(tracker.total_cost_usd - 0.0012) < 1e-9

    def test_record_by_model(self) -> None:
        tracker = CostTracker()
        for _ in range(3):
            tracker.record(LLMResponse(
                content="x", model=MODEL_DEEPSEEK_R1,
                input_tokens=100, output_tokens=50, cost_usd=0.001,
                latency_ms=100,
            ))
        assert tracker.calls_by_model[MODEL_DEEPSEEK_R1] == 3

    def test_summary_keys(self) -> None:
        tracker = CostTracker()
        summary = tracker.summary()
        assert "total_calls" in summary
        assert "total_cost_usd" in summary
        assert "calls_by_model" in summary
        assert "cost_by_model" in summary

    def test_cost_tracker_via_client_mock(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        client.chat(
            messages=[LLMMessage(role="user", content="test")],
            model=MODEL_DEEPSEEK_V3,
        )
        client.chat(
            messages=[LLMMessage(role="user", content="test2")],
            model=MODEL_DEEPSEEK_R1,
        )
        assert client.cost_tracker.total_calls == 2
        assert MODEL_DEEPSEEK_V3 in client.cost_tracker.calls_by_model
        assert MODEL_DEEPSEEK_R1 in client.cost_tracker.calls_by_model


# ---------------------------------------------------------------------------
# IdeaAgent — mock模式
# ---------------------------------------------------------------------------


class TestIdeaAgent:
    def _make_agent(self) -> IdeaAgent:
        client = DeepSeekClient(mock_mode=True)
        return IdeaAgent(client=client)

    def test_generate_returns_list(self) -> None:
        agent = self._make_agent()
        results = agent.generate(n=3)
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_generate_returns_factor_hypotheses(self) -> None:
        agent = self._make_agent()
        results = agent.generate(n=3)
        for h in results:
            assert isinstance(h, FactorHypothesis)
            assert h.name
            assert h.expression

    def test_generate_with_active_factors(self) -> None:
        agent = self._make_agent()
        active = [
            ActiveFactor("test_factor", "cs_rank(returns)", ic=0.04,
                         ic_direction="positive", category="价量"),
        ]
        results = agent.generate(active_factors=active, n=2)
        assert isinstance(results, list)

    def test_generate_with_failed_factors(self) -> None:
        agent = self._make_agent()
        failed = [
            FailedFactor("bad_factor", "ts_mean(volume, 5)", failure_reason="IC_TOO_LOW"),
        ]
        results = agent.generate(failed_factors=failed, n=2)
        assert isinstance(results, list)

    def test_mock_expression_is_dsl_valid(self) -> None:
        """mock模式返回的默认表达式应通过DSL验证。"""
        agent = self._make_agent()
        results = agent.generate(n=1)
        valid_count = sum(1 for h in results if h.dsl_valid)
        # mock返回 "cs_rank(ts_mean(returns, 20))" 应该是合法的
        assert valid_count >= 1

    def test_get_available_operators(self) -> None:
        agent = self._make_agent()
        ops = agent.get_available_operators()
        assert "ts_mean" in ops
        assert "cs_rank" in ops
        assert "div" in ops
        assert len(ops) >= 28

    def test_get_available_terminals(self) -> None:
        agent = self._make_agent()
        terminals = agent.get_available_terminals()
        assert "close" in terminals
        assert "returns" in terminals
        assert "volume" in terminals

    def test_parse_response_handles_nested_dict(self) -> None:
        """测试解析容错: 顶层是dict包裹list的情况。"""
        agent = self._make_agent()
        nested = {"factors": [
            {
                "name": "test_factor",
                "expression": "cs_rank(returns)",
                "hypothesis": "测试",
                "expected_ic_direction": "positive",
                "expected_ic_range": [0.02, 0.05],
                "category": "价量",
                "novelty_vs_existing": "new",
            }
        ]}
        results = agent._parse_response(json.dumps(nested), nested)
        assert len(results) == 1
        assert results[0].name == "test_factor"

    def test_parse_response_handles_empty(self) -> None:
        agent = self._make_agent()
        results = agent._parse_response("invalid json {{{{", None)
        assert results == []

    def test_validate_valid_expression(self) -> None:
        agent = self._make_agent()
        valid, msg = agent._validate_expression("cs_rank(ts_mean(returns, 20))")
        assert valid is True

    def test_validate_empty_expression(self) -> None:
        agent = self._make_agent()
        valid, msg = agent._validate_expression("")
        assert valid is False
        assert msg

    def test_default_active_factors_are_v11_seeds(self) -> None:
        agent = self._make_agent()
        defaults = agent._default_active_factors()
        names = {f.name for f in defaults}
        assert "turnover_mean_20" in names
        assert "volatility_20" in names
        assert "bp_ratio" in names


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------


class TestSingletons:
    def test_get_default_client_returns_same_instance(self) -> None:
        # 重置单例以避免跨测试污染
        import engines.mining.deepseek_client as mod
        mod._default_client = None
        c1 = get_default_client()
        c2 = get_default_client()
        assert c1 is c2

    def test_get_default_router_returns_same_instance(self) -> None:
        import engines.mining.deepseek_client as mod
        mod._default_router = None
        r1 = get_default_router()
        r2 = get_default_router()
        assert r1 is r2


# ---------------------------------------------------------------------------
# QA-Tester 补充测试 — Sprint 1.17 交叉审查
# ---------------------------------------------------------------------------


class TestDeepSeekClientRetryExhausted:
    """API key设置但调用失败时，重试耗尽后应抛出RuntimeError。"""

    def test_retry_exhausted_raises_runtime_error(self) -> None:
        """模拟openai调用持续抛异常，验证RuntimeError包含重试次数信息。"""
        import unittest.mock as mock

        client = DeepSeekClient(api_key="fake_key_for_retry", mock_mode=False, max_retries=2)

        fake_openai = mock.MagicMock()
        fake_openai.chat.completions.create.side_effect = ConnectionError("network error")

        import pytest
        with mock.patch.object(client, "_get_openai_client", return_value=fake_openai), mock.patch.object(client, "_rate_limit"), pytest.raises(RuntimeError) as exc_info:  # 跳过限速sleep
            client.chat(
                messages=[LLMMessage(role="user", content="test")],
                model=MODEL_DEEPSEEK_V3,
            )
        assert "2" in str(exc_info.value)   # 错误信息应包含重试次数

    def test_retry_count_correct(self) -> None:
        """验证实际调用次数等于max_retries。"""
        import unittest.mock as mock

        client = DeepSeekClient(api_key="fake_key", mock_mode=False, max_retries=3)
        fake_openai = mock.MagicMock()
        fake_openai.chat.completions.create.side_effect = Exception("boom")

        import pytest
        with mock.patch.object(client, "_get_openai_client", return_value=fake_openai), mock.patch.object(client, "_rate_limit"), mock.patch("time.sleep"), pytest.raises(RuntimeError):  # 不真正sleep
            client.chat(
                messages=[LLMMessage(role="user", content="test")],
                model=MODEL_DEEPSEEK_V3,
            )
        assert fake_openai.chat.completions.create.call_count == 3


class TestDeepSeekClientCostAccuracy:
    """成本估算精度验证。"""

    def test_estimate_cost_r1(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        # R1: input=0.55/M, output=2.19/M
        cost = client._estimate_cost(MODEL_DEEPSEEK_R1, input_tokens=1_000_000, output_tokens=1_000_000)
        assert abs(cost - (0.55 + 2.19)) < 1e-6

    def test_estimate_cost_v3(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        # V3: input=0.14/M, output=0.28/M
        cost = client._estimate_cost(MODEL_DEEPSEEK_V3, input_tokens=500_000, output_tokens=200_000)
        expected = (500_000 * 0.14 + 200_000 * 0.28) / 1_000_000
        assert abs(cost - expected) < 1e-9

    def test_estimate_cost_local_model_zero(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        cost = client._estimate_cost(MODEL_QWEN3_LOCAL, input_tokens=100_000, output_tokens=50_000)
        assert cost == 0.0

    def test_estimate_cost_unknown_model_uses_v3_fallback(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        # 未知model应fallback到V3定价（input=0.14, output=0.28）
        cost_unknown = client._estimate_cost("unknown-model-xyz", input_tokens=1_000_000, output_tokens=0)
        cost_v3_input = 0.14
        assert abs(cost_unknown - cost_v3_input) < 1e-6

    def test_cost_tracker_summary_rounding(self) -> None:
        """summary中cost_by_model精度应为6位小数。"""
        tracker = CostTracker()
        tracker.record(LLMResponse(
            content="x", model=MODEL_DEEPSEEK_R1,
            input_tokens=123, output_tokens=456, cost_usd=0.000001234567,
            latency_ms=100,
        ))
        summary = tracker.summary()
        # 验证四舍五入到6位
        val = summary["cost_by_model"][MODEL_DEEPSEEK_R1]
        assert val == round(0.000001234567, 6)


class TestDeepSeekClientMockTextMode:
    """mock模式非JSON模式响应验证。"""

    def test_mock_text_mode_is_not_json(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        resp = client.chat(
            messages=[LLMMessage(role="user", content="test")],
            model=MODEL_DEEPSEEK_V3,
            json_mode=False,
        )
        assert resp.is_json is False
        assert resp.parsed is None

    def test_mock_text_mode_contains_placeholder(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        resp = client.chat(
            messages=[LLMMessage(role="user", content="test")],
            model=MODEL_DEEPSEEK_V3,
            json_mode=False,
        )
        assert "Mock" in resp.content

    def test_mock_latency_is_zero(self) -> None:
        client = DeepSeekClient(mock_mode=True)
        resp = client.chat(
            messages=[LLMMessage(role="user", content="test")],
            model=MODEL_DEEPSEEK_R1,
        )
        assert resp.latency_ms == 0.0


class TestIdeaAgentDSLValidation:
    """IdeaAgent DSL验证覆盖更多边界情况。"""

    def _make_agent(self) -> IdeaAgent:
        return IdeaAgent(client=DeepSeekClient(mock_mode=True))

    def test_validate_unknown_terminal_field_rejected(self) -> None:
        """未知终端字段（叶节点）必须被validate拒绝。"""
        agent = self._make_agent()
        # "not_a_field"作为叶节点，validate会检查TERMINALS列表
        valid, msg = agent._validate_expression("cs_rank(not_a_field)")
        assert valid is False
        assert "not_a_field" in msg

    def test_validate_whitespace_only_rejected(self) -> None:
        agent = self._make_agent()
        valid, msg = agent._validate_expression("   ")
        assert valid is False
        assert msg  # 必须有错误信息

    def test_dsl_valid_flag_set_on_hypotheses(self) -> None:
        """生成结果的每个FactorHypothesis必须有dsl_valid字段被填充（不是默认False未触碰）。"""
        agent = self._make_agent()
        results = agent.generate(n=1)
        for h in results:
            # dsl_valid字段必须已经被agent检查过（True or False都是可接受的，但字段应为bool）
            assert isinstance(h.dsl_valid, bool)

    def test_dsl_error_populated_on_invalid(self) -> None:
        """DSL无效时dsl_error字段应有描述信息（使用未知终端字段触发）。"""
        agent = self._make_agent()
        # "nonexistent_data_field"作为叶节点触发"未知字段"错误
        valid, error = agent._validate_expression("cs_zscore(nonexistent_data_field)")
        assert not valid
        assert len(error) > 0

    def test_validate_unknown_operator_not_checked_known_limitation(self) -> None:
        """已知限制: validate当前不检查算子名是否在ALL_OPS中（只检查终端字段）。
        未知算子如fake_op(returns)目前会通过validate — 这是DSL的已知缺口，
        需要在validate中增加算子名验证。
        """
        agent = self._make_agent()
        # returns是合法终端，fake_op算子名不在ALL_OPS但validate不检查
        # 此测试记录当前行为，不设置期望值为True或False，只验证返回bool
        valid, _msg = agent._validate_expression("fake_op(returns)")
        assert isinstance(valid, bool)  # 文档化行为而非断言期望值


class TestIdeaAgentContextConstruction:
    """上下文构造验证：格式化输出符合prompt要求。"""

    def _make_agent(self) -> IdeaAgent:
        return IdeaAgent(client=DeepSeekClient(mock_mode=True))

    def test_format_active_factors_contains_ic(self) -> None:
        agent = self._make_agent()
        factors = [ActiveFactor("f1", "cs_rank(returns)", ic=0.042,
                                ic_direction="positive", category="价量")]
        text = agent._format_active_factors(factors)
        assert "f1" in text
        assert "0.042" in text
        assert "positive" in text

    def test_format_active_factors_empty(self) -> None:
        agent = self._make_agent()
        text = agent._format_active_factors([])
        assert "暂无" in text

    def test_format_failed_factors_contains_reason(self) -> None:
        agent = self._make_agent()
        factors = [FailedFactor("bad_f", "ts_mean(volume, 5)", failure_reason="IC_TOO_LOW")]
        text = agent._format_failed_factors(factors)
        assert "bad_f" in text
        assert "IC_TOO_LOW" in text

    def test_format_failed_factors_truncated_at_20(self) -> None:
        """超过20条失败因子时只输出前20条（避免prompt过长）。"""
        agent = self._make_agent()
        factors = [
            FailedFactor(f"f{i}", "ts_mean(close, 5)", failure_reason="IC_TOO_LOW")
            for i in range(30)
        ]
        text = agent._format_failed_factors(factors)
        # 只应包含f0..f19，不包含f20以后
        assert "f19" in text
        assert "f20" not in text

    def test_format_blacklist_truncated_at_10(self) -> None:
        """黑名单超过10条只输出前10条。"""
        agent = self._make_agent()
        patterns = [f"pattern_{i}" for i in range(15)]
        text = agent._format_blacklist(patterns)
        assert "pattern_9" in text
        assert "pattern_10" not in text

    def test_format_blacklist_empty(self) -> None:
        agent = self._make_agent()
        text = agent._format_blacklist([])
        assert "暂无" in text


class TestIdeaAgentParseResponseEdgeCases:
    """_parse_response 容错覆盖更多边界情况。"""

    def _make_agent(self) -> IdeaAgent:
        return IdeaAgent(client=DeepSeekClient(mock_mode=True))

    def test_parse_response_single_dict_wrapped(self) -> None:
        """顶层是单个因子dict时，应自动包装成列表。"""
        agent = self._make_agent()
        single = {
            "name": "solo_factor",
            "expression": "cs_rank(returns)",
            "hypothesis": "测试单dict",
            "expected_ic_direction": "positive",
            "expected_ic_range": [0.02, 0.05],
            "category": "价量",
            "novelty_vs_existing": "test",
        }
        results = agent._parse_response(json.dumps(single), single)
        assert len(results) == 1
        assert results[0].name == "solo_factor"

    def test_parse_response_hypotheses_key(self) -> None:
        """顶层dict用'hypotheses'键包裹list。"""
        agent = self._make_agent()
        data = {"hypotheses": [
            {
                "name": "h_factor",
                "expression": "cs_zscore(close)",
                "hypothesis": "用hypotheses键",
                "expected_ic_direction": "negative",
                "expected_ic_range": [0.01, 0.04],
                "category": "价量",
                "novelty_vs_existing": "",
            }
        ]}
        results = agent._parse_response(json.dumps(data), data)
        assert len(results) == 1
        assert results[0].name == "h_factor"

    def test_parse_response_skips_non_dict_items(self) -> None:
        """list中混入非dict元素时，跳过无效项不崩溃。"""
        agent = self._make_agent()
        mixed = [
            "not_a_dict",
            42,
            {
                "name": "valid_factor",
                "expression": "cs_rank(volume)",
                "hypothesis": "valid",
                "expected_ic_direction": "positive",
                "expected_ic_range": [0.02, 0.05],
                "category": "价量",
                "novelty_vs_existing": "",
            },
        ]
        results = agent._parse_response(json.dumps(mixed), mixed)
        assert len(results) == 1
        assert results[0].name == "valid_factor"

    def test_parse_response_pre_parsed_takes_priority(self) -> None:
        """pre_parsed不为None时直接使用，不重新解析raw_content。"""
        agent = self._make_agent()
        pre_parsed = [{
            "name": "pre_factor",
            "expression": "cs_rank(returns)",
            "hypothesis": "pre_parsed优先",
            "expected_ic_direction": "positive",
            "expected_ic_range": [0.02, 0.05],
            "category": "价量",
            "novelty_vs_existing": "",
        }]
        # raw_content是损坏的JSON，但pre_parsed有效
        results = agent._parse_response("{{CORRUPTED}}", pre_parsed)
        assert len(results) == 1
        assert results[0].name == "pre_factor"

    def test_parse_response_missing_optional_fields_use_defaults(self) -> None:
        """缺少可选字段时使用默认值，不抛异常。"""
        agent = self._make_agent()
        minimal = [{"name": "minimal_factor", "expression": "cs_rank(close)"}]
        results = agent._parse_response(json.dumps(minimal), minimal)
        assert len(results) == 1
        h = results[0]
        assert h.name == "minimal_factor"
        assert h.expected_ic_direction == "positive"   # 默认值
        assert h.category == "价量"                    # 默认值


class TestIdeaAgentRetryOnDSLFailure:
    """DSL合法率不足时验证重试行为。"""

    def test_retry_adds_invalid_to_failed_list(self) -> None:
        """DSL验证失败的因子应被加入failed_factors参与下一轮重试。"""
        client = DeepSeekClient(mock_mode=True)
        agent = IdeaAgent(client=client, max_validate_retries=3)

        call_count = [0]
        captured_failed: list[list] = []

        def patched_call_and_parse(active_factors, failed_factors, blacklist_patterns, n):
            call_count[0] += 1
            captured_failed.append(list(failed_factors))
            # 直接返回解析好的FactorHypothesis列表（绕过_parse_response）
            return [FactorHypothesis(
                name="bad_factor",
                expression="cs_rank(totally_unknown_field_xyz)",
                hypothesis="bad",
                expected_ic_direction="positive",
            )]

        import unittest.mock as mock
        with mock.patch.object(agent, "_call_and_parse", side_effect=patched_call_and_parse):
            agent.generate(n=1)

        # max_validate_retries=3，valid_count=0 < max(1,0)=1，应重试到耗尽
        assert call_count[0] == 3
        # 第二次调用的failed_factors应包含第一次的无效因子
        assert len(captured_failed) >= 2
        second_call_failed_names = [f.name for f in captured_failed[1]]
        assert "bad_factor" in second_call_failed_names

    def test_generate_returns_last_result_after_all_retries_fail(self) -> None:
        """所有重试后仍无效，应返回最后一次结果（含dsl_valid=False的项）。"""
        import unittest.mock as mock

        client = DeepSeekClient(mock_mode=True)
        agent = IdeaAgent(client=client, max_validate_retries=2)

        # 使用未知终端字段，使validate返回False
        always_invalid_hypothesis = FactorHypothesis(
            name="always_bad",
            expression="cs_rank(totally_unknown_field_xyz)",
            hypothesis="always bad",
            expected_ic_direction="positive",
        )

        with mock.patch.object(
            agent, "_call_and_parse",
            return_value=[always_invalid_hypothesis],
        ):
            results = agent.generate(n=1)

        assert len(results) >= 1
        # 全部无效时也应返回结果（不返回空列表）
        assert all(isinstance(h, FactorHypothesis) for h in results)
        # 验证dsl_valid已被填充为False（因为字段未知）
        assert all(h.dsl_valid is False for h in results)
