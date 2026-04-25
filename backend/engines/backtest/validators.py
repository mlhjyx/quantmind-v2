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

    注意: ST股需要 symbols_info[code, 'price_limit'] 覆盖, 仅靠代码无法识别. 调用方
    应优先用 ``_get_price_limit(code, symbols_info)`` 而非直接调本函数.
    """
    # code统一为带后缀格式(000001.SZ), startswith仍可正确匹配板块
    if code.startswith("68"):
        return 0.20  # 科创板
    if code.startswith("30"):
        return 0.20  # 创业板
    if code.startswith("8") or code.startswith("4") or code.endswith(".BJ"):
        return 0.30  # 北交所
    return 0.10  # 主板(含ST fallback — ST需symbols_info.price_limit覆盖)


def _get_price_limit(code: str, symbols_info: pd.DataFrame | None = None) -> float:
    """获取涨跌停幅度, 优先使用 symbols_info[code, 'price_limit'] override.

    Session 36 PR fix (audit §3.3 REAL_BUG_DORMANT closure): production 之前
    `ValidatorChain.can_trade` 仅 3 参数, broker.py wrapper 接受 symbols_info
    但内部丢弃, ST 5% price_limit 永远 fallback _infer_price_limit 0.10 主板.
    本 helper + 新增 symbols_info 参数 contract 修复.

    Args:
        code: 股票代码 (e.g. "000001.SZ")
        symbols_info: 可选 DataFrame, index=code, column='price_limit' (decimal frac).
                      ST 股应在此 DataFrame 中显式给出 0.05.

    Returns:
        price_limit 小数比例 (e.g. 0.05 for ST, 0.10 for 主板). 优先级:
        1. symbols_info[code, 'price_limit'] (若 valid float > 0)
        2. _infer_price_limit(code) fallback
    """
    if symbols_info is not None and code in symbols_info.index:
        try:
            pl = float(symbols_info.loc[code, "price_limit"])
        except (KeyError, ValueError, TypeError):
            pl = 0.0
        if pl > 0:
            return pl
    return _infer_price_limit(code)


# ============================================================
# ValidatorChain — 可组合的交易验证器 (Phase 3)
# ============================================================

class BaseValidator:
    """交易验证器基类。返回None=通过, 返回str=拒绝原因。"""

    def validate(
        self,
        code: str,
        direction: str,
        row: pd.Series,
        symbols_info: pd.DataFrame | None = None,
    ) -> str | None:
        raise NotImplementedError


class SuspensionValidator(BaseValidator):
    """停牌检测: volume=0。"""

    def validate(
        self,
        code: str,
        direction: str,
        row: pd.Series,
        symbols_info: pd.DataFrame | None = None,
    ) -> str | None:
        if row.get("volume", 0) == 0:
            return "停牌(volume=0)"
        return None


class DataCompletenessValidator(BaseValidator):
    """数据完整性: close/pre_close不为0。"""

    def validate(
        self,
        code: str,
        direction: str,
        row: pd.Series,
        symbols_info: pd.DataFrame | None = None,
    ) -> str | None:
        close = row.get("close", 0)
        pre_close = row.get("pre_close", 0)
        if close == 0 or pre_close == 0:
            return f"数据不完整(close={close}, pre_close={pre_close})"
        return None


class PriceLimitValidator(BaseValidator):
    """涨跌停封板检测。"""

    def validate(
        self,
        code: str,
        direction: str,
        row: pd.Series,
        symbols_info: pd.DataFrame | None = None,
    ) -> str | None:
        close = row.get("close", 0)
        pre_close = row.get("pre_close", 0)
        if close == 0 or pre_close == 0:
            return None  # DataCompletenessValidator已处理

        up_limit = row.get("up_limit", None)
        down_limit = row.get("down_limit", None)
        if up_limit is None or down_limit is None:
            # 优先 symbols_info override (e.g. ST 5%), fallback _infer_price_limit
            price_limit = _get_price_limit(code, symbols_info)
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

    def can_trade(
        self,
        code: str,
        direction: str,
        row: pd.Series,
        symbols_info: pd.DataFrame | None = None,
    ) -> tuple[bool, str | None]:
        """返回(can_trade, reject_reason)。

        Args:
            code: 股票代码
            direction: "buy" | "sell"
            row: 行情 Series (close/pre_close/volume/turnover_rate/...)
            symbols_info: 可选 DataFrame, index=code, column='price_limit' 等.
                ST 股 5% price_limit 必须在此 DataFrame 中提供, 否则 fallback 主板 10%.
        """
        for v in self.validators:
            reason = v.validate(code, direction, row, symbols_info)
            if reason:
                return False, reason
        return True, None

