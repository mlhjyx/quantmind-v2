"""订单级预交易验证器 — PreTradeValidator.

Sprint 1.10 Task 2: 在订单发送前执行5项安全检查，拦截超限订单。

设计原则:
- 纯计算，不修改任何状态
- 每项检查独立，返回完整的失败原因
- 返回 ValidationResult(passed, failed_checks, details)
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ValidationResult:
    """预交易验证结果。

    Attributes:
        passed: True=全部通过可以下单, False=至少一项检查失败。
        failed_checks: 失败的检查名称列表（通过时为空）。
        details: 各检查的详细信息 {check_name: message}。
    """
    passed: bool
    failed_checks: list[str]
    details: dict[str, str]


class PreTradeValidator:
    """订单级预交易验证器（5项检查）。

    检查列表:
        1. single_order_size  — 单笔订单金额 < 总资产 15%
        2. price_tolerance    — 买入价不超过前收盘 × 1.05（防追涨）
        3. industry_concentration — 单行业持仓(含本次订单) ≤ 25%
        4. daily_loss_limit   — 当日亏损 > 3% → 停止下单
        5. single_stock_limit — 单股持仓(含本次订单) < 总资产 10%

    用法:
        validator = PreTradeValidator(
            total_value=1_000_000,
            current_positions={code: weight},
            industry_map={code: industry},
            daily_return=-0.01,
        )
        result = validator.validate(
            code="600519",
            direction="buy",
            amount=100_000,
            price=1800.0,
            pre_close=1750.0,
            industry="白酒",
        )
        if not result.passed:
            logger.warning("订单拒绝: %s", result.failed_checks)
    """

    # 检查名称常量
    CHECK_SINGLE_ORDER_SIZE = "single_order_size"
    CHECK_PRICE_TOLERANCE = "price_tolerance"
    CHECK_INDUSTRY_CONCENTRATION = "industry_concentration"
    CHECK_DAILY_LOSS_LIMIT = "daily_loss_limit"
    CHECK_SINGLE_STOCK_LIMIT = "single_stock_limit"

    def __init__(
        self,
        total_value: float,
        current_positions: dict[str, float],
        industry_map: dict[str, str],
        daily_return: float,
        *,
        single_order_pct: float = 0.15,
        price_tolerance_ratio: float = 1.05,
        industry_cap: float = 0.25,
        daily_loss_threshold: float = -0.03,
        single_stock_cap: float = 0.10,
    ) -> None:
        """初始化验证器。

        Args:
            total_value: 组合总资产（含现金）。
            current_positions: 当前持仓权重 {code: weight}，权重加总≈1.0。
            industry_map: 股票行业映射 {code: industry_sw1}。
            daily_return: 当日收益率（负数=亏损）。
            single_order_pct: 单笔订单上限，默认15%。
            price_tolerance_ratio: 买入价上限倍数，默认1.05。
            industry_cap: 单行业持仓上限，默认25%。
            daily_loss_threshold: 日亏损熔断阈值，默认-3%。
            single_stock_cap: 单股持仓上限，默认10%。
        """
        if total_value <= 0:
            raise ValueError(f"total_value必须>0，当前={total_value}")

        self.total_value = total_value
        self.current_positions = current_positions
        self.industry_map = industry_map
        self.daily_return = daily_return

        self.single_order_pct = single_order_pct
        self.price_tolerance_ratio = price_tolerance_ratio
        self.industry_cap = industry_cap
        self.daily_loss_threshold = daily_loss_threshold
        self.single_stock_cap = single_stock_cap

    def validate(
        self,
        code: str,
        direction: str,
        amount: float,
        price: float,
        pre_close: float | None = None,
        industry: str | None = None,
    ) -> ValidationResult:
        """执行全部5项检查。

        Args:
            code: 股票代码。
            direction: 'buy' 或 'sell'。
            amount: 订单金额（元）。
            price: 委托价格。
            pre_close: 前收盘价（买入检查价格容差用）。
            industry: 所属行业（若未提供从 industry_map 查找）。

        Returns:
            ValidationResult — passed=True表示全部通过。
        """
        failed: list[str] = []
        details: dict[str, str] = {}

        # 1. 单笔订单大小检查
        result_1 = self._check_single_order_size(amount)
        details[self.CHECK_SINGLE_ORDER_SIZE] = result_1
        if not result_1.startswith("PASS"):
            failed.append(self.CHECK_SINGLE_ORDER_SIZE)

        # 2. 价格容差检查（仅买入）
        result_2 = self._check_price_tolerance(direction, price, pre_close)
        details[self.CHECK_PRICE_TOLERANCE] = result_2
        if not result_2.startswith("PASS"):
            failed.append(self.CHECK_PRICE_TOLERANCE)

        # 3. 行业集中度检查
        ind = industry if industry is not None else self.industry_map.get(code, "其他")
        result_3 = self._check_industry_concentration(code, amount, ind)
        details[self.CHECK_INDUSTRY_CONCENTRATION] = result_3
        if not result_3.startswith("PASS"):
            failed.append(self.CHECK_INDUSTRY_CONCENTRATION)

        # 4. 日亏损限制检查
        result_4 = self._check_daily_loss_limit()
        details[self.CHECK_DAILY_LOSS_LIMIT] = result_4
        if not result_4.startswith("PASS"):
            failed.append(self.CHECK_DAILY_LOSS_LIMIT)

        # 5. 单股持仓上限检查
        result_5 = self._check_single_stock_limit(code, amount)
        details[self.CHECK_SINGLE_STOCK_LIMIT] = result_5
        if not result_5.startswith("PASS"):
            failed.append(self.CHECK_SINGLE_STOCK_LIMIT)

        passed = len(failed) == 0
        if not passed:
            logger.warning(
                "[PreTrade] 订单拒绝 %s %s ¥%.0f: %s",
                code, direction, amount, failed,
            )

        return ValidationResult(
            passed=passed,
            failed_checks=failed,
            details=details,
        )

    # ── 内部检查函数 ──

    def _check_single_order_size(self, amount: float) -> str:
        """检查1: 单笔订单金额 < 总资产 × single_order_pct。"""
        limit = self.total_value * self.single_order_pct
        if amount < limit:
            return f"PASS: ¥{amount:.0f} < 限额¥{limit:.0f} ({self.single_order_pct:.0%}总资产)"
        return (
            f"FAIL: 单笔¥{amount:.0f} >= 限额¥{limit:.0f} "
            f"({self.single_order_pct:.0%}总资产¥{self.total_value:.0f})"
        )

    def _check_price_tolerance(
        self,
        direction: str,
        price: float,
        pre_close: float | None,
    ) -> str:
        """检查2: 买入价不超过前收盘 × price_tolerance_ratio。"""
        if direction != "buy":
            return "PASS: 非买入方向，跳过价格容差检查"
        if pre_close is None or pre_close <= 0:
            return "PASS: 无前收盘价数据，跳过价格容差检查"

        limit_price = pre_close * self.price_tolerance_ratio
        if price <= limit_price:
            return (
                f"PASS: 委托价{price:.2f} <= 上限{limit_price:.2f} "
                f"(前收{pre_close:.2f}×{self.price_tolerance_ratio})"
            )
        return (
            f"FAIL: 委托价{price:.2f} > 上限{limit_price:.2f} "
            f"(前收{pre_close:.2f}×{self.price_tolerance_ratio}，防追涨)"
        )

    def _check_industry_concentration(
        self,
        code: str,
        amount: float,
        industry: str,
    ) -> str:
        """检查3: 单行业持仓(含本次订单) ≤ industry_cap。"""
        # 计算现有行业持仓权重
        existing_weight = sum(
            w for c, w in self.current_positions.items()
            if self.industry_map.get(c, "其他") == industry
        )

        # 本次订单新增权重（不含已持仓该股）
        order_weight = amount / self.total_value
        # 若已持仓该股，新增的是净增量（这里保守计算：全部加上）
        new_total = existing_weight + order_weight

        if new_total <= self.industry_cap:
            return (
                f"PASS: {industry}行业{new_total:.1%} <= 上限{self.industry_cap:.0%} "
                f"(现有{existing_weight:.1%}+新增{order_weight:.1%})"
            )
        return (
            f"FAIL: {industry}行业将达{new_total:.1%} > 上限{self.industry_cap:.0%} "
            f"(现有{existing_weight:.1%}+新增{order_weight:.1%})"
        )

    def _check_daily_loss_limit(self) -> str:
        """检查4: 当日亏损 > |daily_loss_threshold| → 停止下单。"""
        if self.daily_return > self.daily_loss_threshold:
            return (
                f"PASS: 日收益{self.daily_return:.2%} > 阈值{self.daily_loss_threshold:.2%}"
            )
        return (
            f"FAIL: 日亏损{self.daily_return:.2%} <= 阈值{self.daily_loss_threshold:.2%}，"
            f"停止当日下单"
        )

    def _check_single_stock_limit(self, code: str, amount: float) -> str:
        """检查5: 单股持仓(含本次订单) < 总资产 × single_stock_cap。"""
        existing_weight = self.current_positions.get(code, 0.0)
        order_weight = amount / self.total_value
        new_weight = existing_weight + order_weight
        limit = self.single_stock_cap

        if new_weight < limit:
            return (
                f"PASS: {code}持仓将达{new_weight:.1%} < 上限{limit:.0%} "
                f"(现有{existing_weight:.1%}+新增{order_weight:.1%})"
            )
        return (
            f"FAIL: {code}持仓将达{new_weight:.1%} >= 上限{limit:.0%} "
            f"(现有{existing_weight:.1%}+新增{order_weight:.1%})"
        )
