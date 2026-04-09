"""交易验证器链。"""

from __future__ import annotations

import pandas as pd


def _infer_price_limit(code: str) -> float:
    """从股票代码推断涨跌停幅度（纯计算，无IO）。

    板块规则:
    - 创业板(300/301开头): ±20%
    - 科创板(688开头): ±20%
    - 北交所(8/4开头): ±30%
    - ST股(代码无法判断，需symbols_info): 默认归入主板10%
    - 主板(其余): ±10%

    注意: ST股需要name字段判断，仅靠代码无法识别。
    当symbols_info可用时应优先使用其price_limit字段。
    """
    # code统一为带后缀格式(000001.SZ), startswith仍可正确匹配板块
    if code.startswith("68"):
        return 0.20  # 科创板
    if code.startswith("30"):
        return 0.20  # 创业板
    if code.startswith("8") or code.startswith("4") or code.endswith(".BJ"):
        return 0.30  # 北交所
    return 0.10  # 主板(含ST fallback — ST需symbols_info.price_limit覆盖)


# ============================================================
# ValidatorChain — 可组合的交易验证器 (Phase 3)
# ============================================================

class BaseValidator:
    """交易验证器基类。返回None=通过, 返回str=拒绝原因。"""

    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        raise NotImplementedError


class SuspensionValidator(BaseValidator):
    """停牌检测: volume=0。"""

    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        if row.get("volume", 0) == 0:
            return "停牌(volume=0)"
        return None


class DataCompletenessValidator(BaseValidator):
    """数据完整性: close/pre_close不为0。"""

    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        close = row.get("close", 0)
        pre_close = row.get("pre_close", 0)
        if close == 0 or pre_close == 0:
            return f"数据不完整(close={close}, pre_close={pre_close})"
        return None


class PriceLimitValidator(BaseValidator):
    """涨跌停封板检测。"""

    def validate(self, code: str, direction: str, row: pd.Series) -> str | None:
        close = row.get("close", 0)
        pre_close = row.get("pre_close", 0)
        if close == 0 or pre_close == 0:
            return None  # DataCompletenessValidator已处理

        up_limit = row.get("up_limit", None)
        down_limit = row.get("down_limit", None)
        if up_limit is None or down_limit is None:
            price_limit = _infer_price_limit(code)
            up_limit = round(pre_close * (1 + price_limit), 2)
            down_limit = round(pre_close * (1 - price_limit), 2)

        _t = row.get("turnover_rate")
        turnover = 999.0 if (_t is None or pd.isna(_t)) else float(_t)

        if direction == "buy" and abs(close - up_limit) < 0.015 and turnover < 1.0:
            return f"涨停封板(close={close}≈up_limit={up_limit}, turnover={turnover:.1f}%)"
        if direction == "sell" and abs(close - down_limit) < 0.015 and turnover < 1.0:
            return f"跌停封板(close={close}≈down_limit={down_limit}, turnover={turnover:.1f}%)"
        return None


class ValidatorChain:
    """可组合的验证器链。按顺序执行，第一个拒绝即停止。"""

    def __init__(self, validators: list[BaseValidator] | None = None):
        self.validators = validators or [
            SuspensionValidator(),
            DataCompletenessValidator(),
            PriceLimitValidator(),
        ]

    def can_trade(self, code: str, direction: str, row: pd.Series) -> tuple[bool, str | None]:
        """返回(can_trade, reject_reason)。"""
        for v in self.validators:
            reason = v.validate(code, direction, row)
            if reason:
                return False, reason
        return True, None

