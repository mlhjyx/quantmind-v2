"""IdeaAgent — LLM驱动的因子假设生成智能体

设计来源:
  - docs/research/R7_ai_model_selection.md §4.1 (DeepSeek-R1为Idea Agent)
  - docs/research/T10_LLM_PROMPT_AND_DAG_PRUNING.md §4.1 (Prompt模板)
  - docs/GP_CLOSED_LOOP_DESIGN.md (Step 3 LLM集成)

功能:
  1. 接收上下文 (已有因子/失败历史/市场特征) → 输出因子假设列表
  2. 使用T10研究产出的Idea Agent Prompt模板
  3. 输出解析: JSON → list[FactorHypothesis]
  4. DSL验证: 生成的expression必须通过FactorDSL.validate()
  5. 自动重试: expression无效时重新生成(最多3次)

Sprint 1.17 ml-engineer
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from ..deepseek_client import (
    DEEPSEEK_BASE_URL,
    MODEL_DEEPSEEK_R1,
    DeepSeekClient,
    LLMMessage,
    get_default_client,
)
from ..factor_dsl import (
    ALL_OPS,
    SEED_FACTORS,
    TERMINALS,
    FactorDSL,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ActiveFactor:
    """当前Active因子信息（输入上下文）。"""
    name: str
    expression: str
    ic: float
    ic_direction: str   # "positive" | "negative"
    category: str


@dataclass
class FailedFactor:
    """历史失败因子信息（输入上下文）。"""
    name: str
    expression: str
    failure_reason: str   # Gate失败原因，如 "IC_TOO_LOW" / "CORR_TOO_HIGH"


@dataclass
class FactorHypothesis:
    """因子假设 — IdeaAgent的输出单元。"""
    name: str
    expression: str                          # FactorDSL格式表达式
    hypothesis: str                          # 经济学解释
    expected_ic_direction: str               # "positive" | "negative"
    expected_ic_range: list[float] = field(default_factory=lambda: [0.02, 0.05])
    category: str = "价量"                   # 价量/流动性/资金流/基本面/行为
    novelty_vs_existing: str = ""            # 与已有因子的区别
    dsl_valid: bool = False                  # DSL验证结果（填充by IdeaAgent）
    dsl_error: str = ""                      # DSL验证错误信息


# ---------------------------------------------------------------------------
# IdeaAgent
# ---------------------------------------------------------------------------


class IdeaAgent:
    """因子假设生成智能体。

    使用DeepSeek-R1（深度推理）生成有经济学逻辑的因子假设。
    生成后自动通过FactorDSL.validate()验证DSL合法性。

    使用示例:
        agent = IdeaAgent()
        hypotheses = agent.generate(
            active_factors=[...],
            failed_factors=[...],
            n=5,
        )
        for h in hypotheses:
            print(h.name, h.expression, h.dsl_valid)
    """

    # T10 §4.1 Idea Agent Prompt模板
    _SYSTEM_PROMPT = """你是A股量化因子研究专家。你的任务是生成有经济学逻辑的Alpha因子假设。

A股市场特征:
- 散户占比高(>60%)，存在明显的追涨杀跌行为
- T+1交易制度，涨跌停限制(10%/20%/5%/30%)
- 机构资金与散户资金的博弈产生可预测的定价偏差
- 月末/季末效应、节假日效应明显

因子DSL算子集（必须严格使用以下算子，不可自创）:
时序算子(需指定窗口): ts_mean(x,w) ts_std(x,w) ts_max(x,w) ts_min(x,w) ts_sum(x,w)
  ts_rank(x,w) ts_skew(x,w) ts_kurt(x,w) delay(x,w) delta(x,w) ts_pct(x,w)
  ts_corr(x,y,w) ts_cov(x,y,w)
截面算子: cs_rank(x) cs_zscore(x) cs_demean(x)
单目数学: log(x) abs(x) sign(x) neg(x) inv(x) sqrt(x)
双目数学: add(x,y) sub(x,y) mul(x,y) div(x,y) max(x,y) min(x,y)

可用数据字段(终端节点):
  open high low close volume amount turnover_rate
  pe_ttm pb ps_ttm total_mv circ_mv
  buy_lg_amount sell_lg_amount net_lg_amount
  buy_md_amount sell_md_amount net_md_amount
  returns vwap high_low close_open

窗口参数约束:
  ts_mean/ts_std/ts_max/ts_min/ts_sum: 窗口=[5,10,20,60]
  ts_rank/ts_skew/ts_kurt: 窗口=[20,60]
  delay/delta/ts_pct: 窗口=[1,5,10,20]
  ts_corr/ts_cov: 窗口=[10,20,60]

因子质量标准:
  - IC目标范围: 0.02~0.10（超过0.15往往是过拟合）
  - 与已有因子相关性 < 0.7
  - 有清晰的经济学解释（市场现象→投资者行为→定价偏差→可预测性）

输出格式: 严格JSON数组，每个元素包含所有字段。"""

    _USER_PROMPT_TEMPLATE = """基于以下上下文生成{n}个新因子假设：

**已有Active因子** (避免相关性>0.7):
{active_factors_text}

**历史失败因子** (避免类似模式):
{failed_factors_text}

**禁止的子树模式** (黑名单):
{blacklist_text}

请生成{n}个符合要求的因子假设，输出严格JSON数组:
[{{
  "name": "factor_name_snake_case",
  "expression": "cs_rank(ts_mean(returns, 20))",
  "hypothesis": "经济学解释：市场现象→投资者行为→定价偏差→可预测性",
  "expected_ic_direction": "positive",
  "expected_ic_range": [0.02, 0.05],
  "category": "价量",
  "novelty_vs_existing": "与xxx因子的本质区别..."
}}]

重要约束:
1. expression只能使用上述DSL算子，窗口参数必须在规定范围内
2. 每个因子必须有独特的经济学逻辑，不能是已有因子的简单变体
3. 生成的name必须是合法snake_case格式"""

    def __init__(
        self,
        client: DeepSeekClient | None = None,
        dsl: FactorDSL | None = None,
        model: str = MODEL_DEEPSEEK_R1,
        base_url: str = DEEPSEEK_BASE_URL,
        max_validate_retries: int = 3,
    ) -> None:
        self._client = client or get_default_client()
        self._dsl = dsl or FactorDSL()
        self._model = model
        self._base_url = base_url
        self._max_validate_retries = max_validate_retries

    def generate(
        self,
        active_factors: list[ActiveFactor] | None = None,
        failed_factors: list[FailedFactor] | None = None,
        blacklist_patterns: list[str] | None = None,
        n: int = 5,
    ) -> list[FactorHypothesis]:
        """生成因子假设列表。

        Args:
            active_factors: 当前Active因子（提供IC/方向信息）。
                            None时使用v1.1种子因子作为默认上下文。
            failed_factors: 历史失败因子（避免重复尝试）。
            blacklist_patterns: GP黑名单中的子树模式。
            n: 希望生成的因子数量。

        Returns:
            list[FactorHypothesis]: 通过DSL验证的因子假设列表。
                                    DSL无效的假设也会返回（dsl_valid=False），
                                    调用方可自行过滤。
        """
        active_factors = active_factors or self._default_active_factors()
        failed_factors = failed_factors or []
        blacklist_patterns = blacklist_patterns or []

        for attempt in range(self._max_validate_retries):
            hypotheses = self._call_and_parse(
                active_factors=active_factors,
                failed_factors=failed_factors,
                blacklist_patterns=blacklist_patterns,
                n=n,
            )

            # 验证DSL
            for h in hypotheses:
                h.dsl_valid, h.dsl_error = self._validate_expression(h.expression)

            valid_count = sum(1 for h in hypotheses if h.dsl_valid)
            logger.info(
                "IdeaAgent生成完成 attempt=%d/%d: %d/%d个DSL合法",
                attempt + 1, self._max_validate_retries, valid_count, len(hypotheses),
            )

            # 如果有足够的有效因子就返回
            if valid_count >= max(1, n // 2):
                return hypotheses

            # 无效过多，重试时增加约束提示
            logger.warning(
                "DSL合法率不足 (%d/%d)，重试 attempt %d/%d",
                valid_count, len(hypotheses), attempt + 1, self._max_validate_retries,
            )
            # 将无效因子的错误信息加入failed_factors，避免重复
            for h in hypotheses:
                if not h.dsl_valid:
                    failed_factors.append(FailedFactor(
                        name=h.name,
                        expression=h.expression,
                        failure_reason=f"DSL_INVALID: {h.dsl_error}",
                    ))

        return hypotheses  # 返回最后一次结果（含无效）

    def _call_and_parse(
        self,
        active_factors: list[ActiveFactor],
        failed_factors: list[FailedFactor],
        blacklist_patterns: list[str],
        n: int,
    ) -> list[FactorHypothesis]:
        """执行LLM调用并解析响应。"""
        active_text = self._format_active_factors(active_factors)
        failed_text = self._format_failed_factors(failed_factors)
        blacklist_text = self._format_blacklist(blacklist_patterns)

        user_content = self._USER_PROMPT_TEMPLATE.format(
            n=n,
            active_factors_text=active_text,
            failed_factors_text=failed_text,
            blacklist_text=blacklist_text,
        )

        messages = [
            LLMMessage(role="system", content=self._SYSTEM_PROMPT),
            LLMMessage(role="user", content=user_content),
        ]

        response = self._client.chat(
            messages=messages,
            model=self._model,
            base_url=self._base_url,
            json_mode=True,
            temperature=0.8,   # 略高温度增加多样性
            max_tokens=3000,
        )

        return self._parse_response(response.content, response.parsed)

    def _parse_response(
        self,
        raw_content: str,
        pre_parsed: Any,
    ) -> list[FactorHypothesis]:
        """将LLM响应解析为FactorHypothesis列表。"""
        data = pre_parsed

        # 如果pre_parsed为None，尝试手动解析
        if data is None:
            try:
                # 尝试提取JSON数组
                start = raw_content.find("[")
                end = raw_content.rfind("]") + 1
                if start >= 0 and end > start:
                    data = json.loads(raw_content[start:end])
                else:
                    data = json.loads(raw_content)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error("IdeaAgent响应JSON解析失败: %s", e)
                logger.debug("原始响应: %s", raw_content[:500])
                return []

        # 支持顶层是dict（含data字段）或直接是list
        if isinstance(data, dict):
            for key in ("factors", "hypotheses", "data", "results"):
                if key in data and isinstance(data[key], list):
                    data = data[key]
                    break
            else:
                # 如果是单个因子dict，包装成列表
                data = [data]

        if not isinstance(data, list):
            logger.error("IdeaAgent响应格式错误: 期望list，得到 %s", type(data))
            return []

        hypotheses = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                h = FactorHypothesis(
                    name=str(item.get("name", "unknown_factor")),
                    expression=str(item.get("expression", "")),
                    hypothesis=str(item.get("hypothesis", "")),
                    expected_ic_direction=str(item.get("expected_ic_direction", "positive")),
                    expected_ic_range=item.get("expected_ic_range", [0.02, 0.05]),
                    category=str(item.get("category", "价量")),
                    novelty_vs_existing=str(item.get("novelty_vs_existing", "")),
                )
                hypotheses.append(h)
            except Exception as e:
                logger.warning("解析单个因子假设失败: %s, item=%s", e, item)

        return hypotheses

    def _validate_expression(self, expression: str) -> tuple[bool, str]:
        """验证DSL表达式合法性。"""
        if not expression or not expression.strip():
            return False, "表达式为空"
        try:
            tree = self._dsl.from_string(expression)
            return self._dsl.validate(tree)
        except Exception as e:
            return False, f"解析失败: {e}"

    # ----------------------------------------------------------------
    # 上下文格式化
    # ----------------------------------------------------------------

    def _format_active_factors(self, factors: list[ActiveFactor]) -> str:
        if not factors:
            return "（暂无Active因子）"
        lines = []
        for f in factors:
            lines.append(
                f"  - {f.name}: {f.expression} | IC={f.ic:+.3f} ({f.ic_direction}) | {f.category}"
            )
        return "\n".join(lines)

    def _format_failed_factors(self, factors: list[FailedFactor]) -> str:
        if not factors:
            return "（暂无失败历史）"
        lines = []
        for f in factors[:20]:   # 限制最多20条，避免prompt过长
            lines.append(f"  - {f.name}: {f.expression} → 失败原因: {f.failure_reason}")
        return "\n".join(lines)

    def _format_blacklist(self, patterns: list[str]) -> str:
        if not patterns:
            return "（暂无黑名单模式）"
        return "\n".join(f"  - {p}" for p in patterns[:10])

    def _default_active_factors(self) -> list[ActiveFactor]:
        """使用v1.1种子因子作为默认Active因子上下文。"""
        defaults = [
            ActiveFactor("turnover_mean_20", SEED_FACTORS["turnover_mean_20"],
                         ic=-0.042, ic_direction="negative", category="流动性"),
            ActiveFactor("volatility_20",    SEED_FACTORS["volatility_20"],
                         ic=-0.038, ic_direction="negative", category="价量"),
            ActiveFactor("reversal_20",      SEED_FACTORS["reversal_20"],
                         ic=0.031,  ic_direction="positive", category="价量"),
            ActiveFactor("amihud_20",        SEED_FACTORS["amihud_20"],
                         ic=-0.035, ic_direction="negative", category="流动性"),
            ActiveFactor("bp_ratio",         SEED_FACTORS["bp_ratio"],
                         ic=0.028,  ic_direction="positive", category="基本面"),
        ]
        return defaults

    # ----------------------------------------------------------------
    # 便捷方法
    # ----------------------------------------------------------------

    def get_available_operators(self) -> list[str]:
        """返回FactorDSL可用算子列表（供prompt构造使用）。"""
        return list(ALL_OPS.keys())

    def get_available_terminals(self) -> list[str]:
        """返回FactorDSL可用数据字段列表。"""
        return list(TERMINALS)
