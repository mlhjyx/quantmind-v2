"""D5 LLM 3-Agent + D6 Thompson Sampling 测试。

D5测试:
- FactorAgent: 代码提取、安全验证、缺失函数检测
- EvalAgent: IC计算、推荐等级、数据不足处理

D6测试:
- Thompson Sampling: 选择、更新、收敛、持久化、确定性
"""

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engines.mining.agents.eval_agent import (
    EvalAgent,
    EvalResult,
    IC_THRESHOLD_ACCEPT,
    IC_THRESHOLD_REVIEW,
    MIN_DATES,
)
from engines.mining.agents.factor_agent import (
    FactorAgent,
    GeneratedFactorCode,
)
from engines.mining.agents.idea_agent import FactorHypothesis
from engines.mining.engine_selector import (
    ALL_ENGINES,
    ENGINE_BRUTEFORCE,
    ENGINE_GP,
    ENGINE_LLM,
    EngineStats,
    ThompsonSamplingSelector,
)


# ═══════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════

def _make_hypothesis() -> FactorHypothesis:
    return FactorHypothesis(
        name="test_factor",
        expression="cs_rank(ts_mean(close, 20))",
        hypothesis="20日均价截面排序",
        expected_ic_direction="negative",
        category="价量",
    )


def _make_price_data(n_dates: int = 30, n_stocks: int = 50) -> pd.DataFrame:
    """合成行情数据。"""
    rng = np.random.RandomState(42)
    rows = []
    start = date(2024, 1, 2)
    for i in range(n_dates):
        td = start + timedelta(days=i)
        if td.weekday() >= 5:
            continue
        for j in range(n_stocks):
            code = f"{j:06d}.SZ"
            close = rng.uniform(10, 50)
            rows.append({
                "code": code,
                "trade_date": td,
                "open": round(close * 0.99, 2),
                "high": round(close * 1.02, 2),
                "low": round(close * 0.98, 2),
                "close": round(close, 2),
                "volume": int(rng.uniform(50000, 500000)),
                "amount": round(close * rng.uniform(1e4, 1e6), 2),
                "turnover_rate": round(rng.uniform(1, 10), 2),
                "total_mv": round(rng.uniform(1e5, 1e7), 2),
            })
    return pd.DataFrame(rows)


def _make_forward_returns(price_data: pd.DataFrame) -> pd.DataFrame:
    """合成前瞻收益（与IC有关联的）。"""
    rng = np.random.RandomState(42)
    rows = []
    for td in price_data["trade_date"].unique():
        day = price_data[price_data["trade_date"] == td]
        for _, row in day.iterrows():
            # 与close负相关（模拟反转因子）
            fwd_ret = -0.001 * row["close"] / 30 + rng.normal(0, 0.02)
            rows.append({
                "code": row["code"],
                "trade_date": td,
                "fwd_ret_5d": fwd_ret,
            })
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════
# D5: FactorAgent
# ═══════════════════════════════════════════════════

class TestFactorAgentCodeExtraction:
    """FactorAgent._extract_code() 代码提取。"""

    def test_extract_from_markdown_block(self):
        """从```python...```块提取。"""
        response = '```python\ndef compute_factor(df):\n    return df["close"]\n```'
        code = FactorAgent._extract_code(response)
        assert "def compute_factor" in code

    def test_extract_plain_code(self):
        """纯代码响应（无markdown标记）。"""
        response = 'def compute_factor(df):\n    return df["close"]'
        code = FactorAgent._extract_code(response)
        assert "def compute_factor" in code

    def test_extract_empty_response(self):
        """空响应返回空字符串。"""
        assert FactorAgent._extract_code("no code here") == ""


class TestFactorAgentValidation:
    """FactorAgent._validate_code() 安全验证。"""

    def test_valid_code_passes(self):
        """正常代码通过验证。"""
        code = 'def compute_factor(df):\n    return df["close"].rolling(20).mean()'
        valid, error = FactorAgent._validate_code(code)
        assert valid is True
        assert error == ""

    def test_missing_function_fails(self):
        """缺少compute_factor函数。"""
        code = 'def other_func(df):\n    return df["close"]'
        valid, error = FactorAgent._validate_code(code)
        assert valid is False
        assert "compute_factor" in error

    def test_forbidden_import_os(self):
        """禁止import os。"""
        code = 'import os\ndef compute_factor(df):\n    return df["close"]'
        valid, error = FactorAgent._validate_code(code)
        assert valid is False
        assert "禁止" in error

    def test_forbidden_eval(self):
        """禁止eval()。"""
        code = 'def compute_factor(df):\n    return eval("df.close")'
        valid, error = FactorAgent._validate_code(code)
        assert valid is False

    def test_syntax_error(self):
        """语法错误。"""
        code = 'def compute_factor(df)\n    return df'
        valid, error = FactorAgent._validate_code(code)
        assert valid is False
        assert "语法" in error


# ═══════════════════════════════════════════════════
# D5: EvalAgent
# ═══════════════════════════════════════════════════

class TestEvalAgentExecution:
    """EvalAgent 代码执行和IC计算。"""

    def test_valid_factor_code_evaluates(self):
        """有效因子代码能执行并产出IC。"""
        code = """
def compute_factor(df):
    import pandas as pd
    return df["close"].rank(ascending=False)
"""
        price_data = _make_price_data(n_dates=40, n_stocks=50)
        fwd_returns = _make_forward_returns(price_data)

        agent = EvalAgent()
        result = agent.evaluate(code, price_data, fwd_returns, "test")

        assert result.is_valid
        assert result.n_dates >= MIN_DATES
        assert result.ic_mean != 0.0
        assert len(result.ic_series) > 0
        assert result.recommendation in ("accept", "review", "reject")

    def test_invalid_code_returns_error(self):
        """无效代码返回错误。"""
        code = "def wrong_func(df): pass"  # 无compute_factor
        price_data = _make_price_data()
        fwd_returns = _make_forward_returns(price_data)

        agent = EvalAgent()
        result = agent.evaluate(code, price_data, fwd_returns, "bad_factor")

        assert result.is_valid is False
        assert result.recommendation == "reject"
        assert result.execution_error != ""

    def test_forbidden_code_blocked(self):
        """危险代码被阻止。"""
        code = 'import os\ndef compute_factor(df): return df["close"]'
        price_data = _make_price_data()
        fwd_returns = _make_forward_returns(price_data)

        agent = EvalAgent()
        result = agent.evaluate(code, price_data, fwd_returns, "danger")

        assert result.is_valid is False
        assert "禁止" in result.execution_error

    def test_insufficient_dates_rejected(self):
        """截面日数不足。"""
        code = 'def compute_factor(df):\n    return df["close"]'
        price_data = _make_price_data(n_dates=5, n_stocks=50)
        fwd_returns = _make_forward_returns(price_data)

        agent = EvalAgent()
        result = agent.evaluate(code, price_data, fwd_returns, "short")

        assert result.is_valid is False


class TestEvalAgentRecommendation:
    """EvalAgent推荐等级。"""

    def test_high_ic_accepted(self):
        """高IC因子推荐accept。"""
        result = EvalResult(factor_name="strong", is_valid=True)
        result.ic_mean = 0.05
        result.t_stat = 3.0
        EvalAgent._evaluate_recommendation(result)
        assert result.recommendation == "accept"

    def test_medium_ic_review(self):
        """中IC因子推荐review。"""
        result = EvalResult(factor_name="medium", is_valid=True)
        result.ic_mean = 0.025
        result.t_stat = 1.5
        EvalAgent._evaluate_recommendation(result)
        assert result.recommendation == "review"

    def test_low_ic_rejected(self):
        """低IC因子推荐reject。"""
        result = EvalResult(factor_name="weak", is_valid=True)
        result.ic_mean = 0.005
        result.t_stat = 0.5
        EvalAgent._evaluate_recommendation(result)
        assert result.recommendation == "reject"


# ═══════════════════════════════════════════════════
# D6: Thompson Sampling
# ═══════════════════════════════════════════════════

class TestThompsonSamplingBasic:
    """Thompson Sampling基本功能。"""

    def test_select_returns_valid_engine(self):
        """选择结果是有效引擎。"""
        selector = ThompsonSamplingSelector(seed=42)
        result = selector.select()
        assert result.selected_engine in ALL_ENGINES
        assert len(result.sampled_scores) == 3

    def test_deterministic_with_seed(self):
        """固定种子确保确定性。"""
        s1 = ThompsonSamplingSelector(seed=42)
        s2 = ThompsonSamplingSelector(seed=42)
        r1 = s1.select()
        r2 = s2.select()
        assert r1.selected_engine == r2.selected_engine
        assert r1.sampled_scores == r2.sampled_scores

    def test_update_success(self):
        """成功更新增加alpha。"""
        selector = ThompsonSamplingSelector(seed=42)
        selector.update(ENGINE_GP, success=True)
        stats = selector.get_stats()
        assert stats[ENGINE_GP]["alpha"] == 2.0  # 1.0 + 1
        assert stats[ENGINE_GP]["beta"] == 1.0
        assert stats[ENGINE_GP]["total_runs"] == 1
        assert stats[ENGINE_GP]["total_successes"] == 1

    def test_update_failure(self):
        """失败更新增加beta。"""
        selector = ThompsonSamplingSelector(seed=42)
        selector.update(ENGINE_LLM, success=False)
        stats = selector.get_stats()
        assert stats[ENGINE_LLM]["alpha"] == 1.0
        assert stats[ENGINE_LLM]["beta"] == 2.0  # 1.0 + 1
        assert stats[ENGINE_LLM]["total_runs"] == 1
        assert stats[ENGINE_LLM]["total_successes"] == 0


class TestThompsonSamplingConvergence:
    """Thompson Sampling收敛行为。"""

    def test_converges_to_best_engine(self):
        """大量更新后倾向选择成功率最高的引擎。"""
        selector = ThompsonSamplingSelector(seed=42)

        # GP成功30次，失败5次 → 成功率86%
        for _ in range(30):
            selector.update(ENGINE_GP, success=True)
        for _ in range(5):
            selector.update(ENGINE_GP, success=False)

        # BruteForce成功10次，失败20次 → 成功率33%
        for _ in range(10):
            selector.update(ENGINE_BRUTEFORCE, success=True)
        for _ in range(20):
            selector.update(ENGINE_BRUTEFORCE, success=False)

        # LLM成功2次，失败8次 → 成功率20%
        for _ in range(2):
            selector.update(ENGINE_LLM, success=True)
        for _ in range(8):
            selector.update(ENGINE_LLM, success=False)

        # 100次选择中GP应占多数
        counts = {e: 0 for e in ALL_ENGINES}
        for _ in range(100):
            r = selector.select()
            counts[r.selected_engine] += 1

        assert counts[ENGINE_GP] > counts[ENGINE_BRUTEFORCE]
        assert counts[ENGINE_GP] > counts[ENGINE_LLM]
        assert counts[ENGINE_GP] > 60  # GP应被选60+次

    def test_uniform_prior_explores_all(self):
        """无更新时（均匀先验），三个引擎都有机会被选。"""
        counts = {e: 0 for e in ALL_ENGINES}
        for i in range(300):
            selector = ThompsonSamplingSelector(seed=i)
            r = selector.select()
            counts[r.selected_engine] += 1

        # 每个引擎至少被选30次（300次中）
        for engine in ALL_ENGINES:
            assert counts[engine] > 30, f"{engine}被选次数过少: {counts[engine]}"


class TestThompsonSamplingPersistence:
    """Thompson Sampling持久化。"""

    def test_save_and_load(self):
        """保存→加载后状态一致。"""
        selector = ThompsonSamplingSelector(seed=42)
        selector.update(ENGINE_GP, success=True)
        selector.update(ENGINE_GP, success=True)
        selector.update(ENGINE_LLM, success=False)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "selector_state.json"
            selector.save(path)

            assert path.exists()
            data = json.loads(path.read_text())
            assert ENGINE_GP in data

            # 加载到新实例
            selector2 = ThompsonSamplingSelector(seed=42)
            selector2.load(path)

            stats1 = selector.get_stats()
            stats2 = selector2.get_stats()
            assert stats1 == stats2

    def test_load_nonexistent_uses_prior(self):
        """加载不存在的文件使用默认先验。"""
        selector = ThompsonSamplingSelector(seed=42)
        selector.load("/nonexistent/path.json")

        stats = selector.get_stats()
        for engine in ALL_ENGINES:
            assert stats[engine]["alpha"] == 1.0
            assert stats[engine]["beta"] == 1.0


class TestEngineStats:
    """EngineStats数据类。"""

    def test_success_rate_zero_runs(self):
        """无运行时成功率=0。"""
        s = EngineStats(name="test")
        assert s.success_rate == 0.0

    def test_mean_prior(self):
        """先验Beta(1,1)均值=0.5。"""
        s = EngineStats(name="test")
        assert s.mean == pytest.approx(0.5)

    def test_roundtrip_dict(self):
        """to_dict/from_dict往返一致。"""
        s = EngineStats(name="gp", alpha=5.0, beta=3.0, total_runs=7, total_successes=4)
        d = s.to_dict()
        s2 = EngineStats.from_dict(d)
        assert s2.name == s.name
        assert s2.alpha == s.alpha
        assert s2.beta == s.beta
