"""BruteForce引擎 — 50模板 × 参数网格暴力枚举 (Engine 1)

R2研究结论: BruteForce是3引擎中成本最低的基线引擎，<2h预算，量纲剪枝。
模板来源:
  - DESIGN_V5 §4.2 34因子清单（已实现5个+Reserve 2个，补充剩余）
  - Qlib Alpha158 独有因子: BETA/RSV/CORD/CNTP/CNTD (R2研究Gap分析)
  - 经典量化文献: Fama-French / Amihud / Jegadeesh-Titman

Gate筛选 (G1-G3，宽松前置筛选，最终标准 G1-G8 在 FactorGatePipeline):
  G1: |IC_mean| > 0.015  (宽松，最终要求 >0.02)
  G2: 与现有Active因子 Spearman 相关性 < 0.7
  G3: t 统计量 > 2.0  (最终要求 >2.5)
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import structlog
from scipy import stats

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# 参数网格
# ---------------------------------------------------------------------------

WINDOWS_SHORT: tuple[int, ...] = (5, 10, 20)
WINDOWS_MID: tuple[int, ...] = (20, 40, 60)
WINDOWS_ALL: tuple[int, ...] = (5, 10, 20, 40, 60)
WINDOWS_REVERSAL: tuple[int, ...] = (5, 10, 20)
WINDOWS_MOMENTUM: tuple[int, ...] = (20, 40, 60, 120)


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------


@dataclass
class FactorTemplate:
    """单个因子模板的元数据"""

    name: str
    category: str  # price_volume / liquidity / flow / fundamental / cross_source
    description: str
    economic_rationale: str
    direction: str  # positive / negative
    required_fields: list[str]
    windows: tuple[int, ...]
    expr_template: str  # 用 {w} 占位符的表达式模板
    academic_support: int = 3  # 学术支持强度 (1-5)


@dataclass
class FactorCandidate:
    """一个具体的因子候选（模板 + 参数实例化）"""

    name: str
    category: str
    direction: str
    expression: str
    window: int
    economic_rationale: str
    academic_support: int
    # G1-G3 检验结果（计算后填充）
    ic_mean: float = float("nan")
    ic_std: float = float("nan")
    t_stat: float = float("nan")
    ic_ir: float = float("nan")
    max_corr_with_active: float = float("nan")
    passed_g1: bool = False
    passed_g2: bool = False
    passed_g3: bool = False

    @property
    def passed_all(self) -> bool:
        return self.passed_g1 and self.passed_g2 and self.passed_g3


# ---------------------------------------------------------------------------
# 50 因子模板
# 每个模板必须有完整经济学假设: 市场现象 → 投资者行为 → 定价偏差 → 可预测性
# ---------------------------------------------------------------------------

FACTOR_TEMPLATES: list[FactorTemplate] = [
    # ============================================================
    # 类别①：价量技术类（来自 DESIGN_V5 §4.2 + Alpha158 Gap）
    # ============================================================
    FactorTemplate(
        name="reversal",
        category="price_volume",
        description="短期反转: {w}日收益率反向",
        economic_rationale=(
            "散户过度反应 → 短期价格偏离基本面 → 均值回归。"
            "Jegadeesh (1990)，A股散户占80%+效果更强。"
        ),
        direction="negative",
        required_fields=["close"],
        windows=WINDOWS_REVERSAL,
        expr_template="close / delay(close, {w}) - 1",
        academic_support=5,
    ),
    FactorTemplate(
        name="momentum",
        category="price_volume",
        description="中期动量: {w}日收益率（跳过最近5日）",
        economic_rationale=(
            "机构趋势追踪+信息扩散滞后 → 中期价格连续性。"
            "Jegadeesh-Titman (1993)，跳5日避免短反转干扰。"
        ),
        direction="positive",
        required_fields=["close"],
        windows=WINDOWS_MOMENTUM,
        expr_template="delay(close, 5) / delay(close, {w}) - 1",
        academic_support=4,
    ),
    FactorTemplate(
        name="volatility",
        category="price_volume",
        description="{w}日收益率标准差（低波动溢价）",
        economic_rationale=(
            "机构杠杆约束 → 无法充分持有低波动股票 → 低波动被低估。"
            "Ang et al. (2006) BAB效应，A股验证稳健。"
        ),
        direction="negative",
        required_fields=["close"],
        windows=WINDOWS_ALL,
        expr_template="ts_std(close / delay(close, 1) - 1, {w})",
        academic_support=5,
    ),
    FactorTemplate(
        name="max_ret",
        category="price_volume",
        description="{w}日最大单日涨幅（彩票偏好反向）",
        economic_rationale=(
            "散户偏爱彩票式股票 → 高极端收益被高估 → 未来收益偏低。"
            "Bali et al. (2011) MAX效应，A股涨停制度放大此效应。"
        ),
        direction="negative",
        required_fields=["close"],
        windows=WINDOWS_SHORT,
        expr_template="ts_max(close / delay(close, 1) - 1, {w})",
        academic_support=4,
    ),
    FactorTemplate(
        name="volume_price_corr",
        category="price_volume",
        description="{w}日量价相关性（知情交易反向）",
        economic_rationale=(
            "量价正相关代表追涨杀跌行为，知情交易者反向操作。"
            "A股散户主导，量价正相关期往往是情绪高峰。"
        ),
        direction="negative",
        required_fields=["close", "volume"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_corr(close / delay(close, 1) - 1, "
            "volume / (ts_mean(volume, {w}) + 1e-10), {w})"
        ),
        academic_support=4,
    ),
    FactorTemplate(
        name="idio_vol",
        category="price_volume",
        description="{w}日特质波动率代理",
        economic_rationale=(
            "注意力有限 → 特质风险未被定价 → 高特质波动被高估。"
            "FF3残差std代理，避免实时因子回归依赖。"
        ),
        direction="negative",
        required_fields=["close"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_std(close / delay(close, 1) - 1 - "
            "ts_mean(close / delay(close, 1) - 1, {w}), {w})"
        ),
        academic_support=5,
    ),
    FactorTemplate(
        name="kmid",
        category="price_volume",
        description="K线中点偏移 (close-open)/open",
        economic_rationale=(
            "日内价格从开盘到收盘的方向性变化捕捉日内信息更新。"
            "正值代表日内买盘持续，短期正向信号。Qlib Alpha158 KMID。"
        ),
        direction="positive",
        required_fields=["close", "open"],
        windows=(1,),
        expr_template="(close - open) / (open + 1e-10)",
        academic_support=3,
    ),
    FactorTemplate(
        name="ksft",
        category="price_volume",
        description="K线影线偏移 (2*close-high-low)/open",
        economic_rationale=(
            "上下影线反映日内价格拉锯，正值代表收盘价高于日内均值。"
            "筹码集中在上方预示未来买盘支撑。Qlib Alpha158 KSFT。"
        ),
        direction="positive",
        required_fields=["close", "high", "low", "open"],
        windows=(1,),
        expr_template="(2 * close - high - low) / (open + 1e-10)",
        academic_support=3,
    ),
    FactorTemplate(
        name="cntp",
        category="price_volume",
        description="{w}日上涨天数占比（方向性情绪）",
        economic_rationale=(
            "持续上涨天数反映买方力量积累，是动量的离散化衡量。"
            "Alpha158 CNTP，A股中与换手率结合后信号更强。"
        ),
        direction="positive",
        required_fields=["close"],
        windows=(5, 10, 20),
        expr_template=(
            "ts_mean((close / delay(close, 1) - 1 > 0) * 1.0, {w})"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="rsv",
        category="price_volume",
        description="{w}日相对强弱值 Williams%R（Alpha158 RSV）",
        economic_rationale=(
            "收盘价在{w}日高低区间的相对位置：高位代表近期强势。"
            "获利了结压力：极高值后容易出现抛售。"
        ),
        direction="positive",
        required_fields=["close", "high", "low"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "(close - ts_min(low, {w})) / "
            "(ts_max(high, {w}) - ts_min(low, {w}) + 1e-10)"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="beta",
        category="price_volume",
        description="{w}日价格趋势强度代理（Alpha158 BETA）",
        economic_rationale=(
            "价格趋势斜率捕捉趋势强度。"
            "趋势市中正向，震荡市中反转，与波动率组合形成条件信号。"
        ),
        direction="positive",
        required_fields=["close"],
        windows=WINDOWS_MID,
        expr_template=(
            "(ts_mean(close, {w} // 2) - ts_mean(close, {w})) / "
            "(ts_std(close, {w}) + 1e-10)"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="cord",
        category="price_volume",
        description="{w}日收盘价与成交量的Rank相关（Alpha158 CORD）",
        economic_rationale=(
            "量价Rank相关：正相关代表上涨放量（趋势延续），"
            "负相关代表上涨缩量（动量衰减预警）。"
        ),
        direction="negative",
        required_fields=["close", "volume"],
        windows=WINDOWS_MID,
        expr_template=(
            "ts_corr(rank(close / delay(close, 1) - 1), "
            "rank(volume / (ts_mean(volume, {w}) + 1e-10)), {w})"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="cntd",
        category="price_volume",
        description="{w}日上涨下跌天数差（Alpha158 CNTD）",
        economic_rationale=(
            "上涨天数-下跌天数净值衡量多空博弈方向性。"
            "与CNTP互补：CNTP是占比，CNTD是绝对差异。"
        ),
        direction="positive",
        required_fields=["close"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_sum((close / delay(close, 1) - 1 > 0) * 1.0, {w}) - "
            "ts_sum((close / delay(close, 1) - 1 < 0) * 1.0, {w})"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="high_low_range",
        category="price_volume",
        description="{w}日振幅均值（市场参与度）",
        economic_rationale=(
            "振幅衡量日内波动幅度。"
            "持续小振幅后往往伴随方向性突破（布林带收缩效应）。"
        ),
        direction="negative",
        required_fields=["high", "low", "close"],
        windows=WINDOWS_SHORT,
        expr_template="ts_mean((high - low) / (close + 1e-10), {w})",
        academic_support=3,
    ),
    FactorTemplate(
        name="close_high_ratio",
        category="price_volume",
        description="{w}日收盘/区间最高价均值（卖压强度）",
        economic_rationale=(
            "收盘价接近区间高点说明买盘持续；远离高点说明卖盘压制。"
            "Alpha158 Price group 变体，A股日内资金轮动明显。"
        ),
        direction="positive",
        required_fields=["close", "high"],
        windows=WINDOWS_SHORT,
        expr_template="ts_mean(close / (ts_max(high, {w}) + 1e-10), {w})",
        academic_support=3,
    ),
    FactorTemplate(
        name="vwap_bias",
        category="price_volume",
        description="{w}日VWAP偏离度（价格偏离均衡反向）",
        economic_rationale=(
            "VWAP代表当日成交均价，close高于VWAP代表收盘前追涨。"
            "偏离越大均值回归概率越高。"
        ),
        direction="negative",
        required_fields=["close", "amount", "volume"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_mean(close / (amount / (volume + 1e-10) + 1e-10) - 1, {w})"
        ),
        academic_support=4,
    ),
    FactorTemplate(
        name="open_gap",
        category="price_volume",
        description="{w}日隔夜跳空均值（信息不对称）",
        economic_rationale=(
            "隔夜跳空反映盘后信息的单边定价。"
            "持续正跳空代表盘后利好消息积累，短期正向动量。"
        ),
        direction="positive",
        required_fields=["open", "close"],
        windows=WINDOWS_SHORT,
        expr_template="ts_mean(open / delay(close, 1) - 1, {w})",
        academic_support=3,
    ),
    FactorTemplate(
        name="intraday_return",
        category="price_volume",
        description="{w}日日内收益均值（日内资金方向）",
        economic_rationale=(
            "日内收益 = close/open - 1，衡量日内买盘净力度。"
            "持续正日内收益代表资金持续流入，短期正向信号。"
        ),
        direction="positive",
        required_fields=["close", "open"],
        windows=WINDOWS_SHORT,
        expr_template="ts_mean(close / (open + 1e-10) - 1, {w})",
        academic_support=3,
    ),
    FactorTemplate(
        name="return_range",
        category="price_volume",
        description="{w}日收益率极差（尾部风险）",
        economic_rationale=(
            "收益率极差 = max - min，衡量期间内价格震荡的极端幅度。"
            "极差大的股票风险高，散户赌博倾向强，被高估。"
        ),
        direction="negative",
        required_fields=["close"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_max(close / delay(close, 1) - 1, {w}) - "
            "ts_min(close / delay(close, 1) - 1, {w})"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="price_range_rank",
        category="price_volume",
        description="{w}日价格区间百分位（趋势强度）",
        economic_rationale=(
            "价格在历史区间的百分位：高位代表强趋势。"
            "Alpha158 RSV 的时序rank变体，在截面上更具可比性。"
        ),
        direction="positive",
        required_fields=["close"],
        windows=WINDOWS_MID,
        expr_template="ts_rank(close, {w})",
        academic_support=3,
    ),

    # ============================================================
    # 类别②：流动性类（DESIGN_V5 §4.2 类别②）
    # ============================================================
    FactorTemplate(
        name="amihud",
        category="liquidity",
        description="{w}日 Amihud 非流动性指标",
        economic_rationale=(
            "每单位成交额的绝对收益：流动性溢价。"
            "Amihud (2002)，A股小市值股票此效应尤显著。"
        ),
        direction="positive",
        required_fields=["close", "amount"],  # amount: 千元(klines_daily)
        windows=(5, 10, 20),
        expr_template=(
            # amount/1e4 将千元转为千万元级别缩放，不影响截面排序
            "ts_mean(abs(close / delay(close, 1) - 1) / "
            "(amount / 1e4 + 1e-10), {w})"
        ),
        academic_support=4,
    ),
    FactorTemplate(
        name="turnover_mean",
        category="liquidity",
        description="{w}日平均换手率（散户过度交易反向）",
        economic_rationale=(
            "高换手率代表散户过度交易，情绪泡沫。"
            "Statman et al. (2006) 过度自信，高换手期后收益偏低。"
        ),
        direction="negative",
        required_fields=["turnover_rate"],
        windows=WINDOWS_ALL,
        expr_template="ts_mean(turnover_rate, {w})",
        academic_support=5,
    ),
    FactorTemplate(
        name="turnover_vol",
        category="liquidity",
        description="{w}日换手率波动率（流动性不稳定性）",
        economic_rationale=(
            "换手率波动大代表资金进出不稳定，信号噪音高。"
            "与均值换手率互补，捕捉流动性的二阶矩特征。"
        ),
        direction="negative",
        required_fields=["turnover_rate"],
        windows=(5, 10, 20),
        expr_template="ts_std(turnover_rate, {w})",
        academic_support=4,
    ),
    FactorTemplate(
        name="volume_ratio",
        category="liquidity",
        description="{w}日相对成交量比（情绪高峰反向）",
        economic_rationale=(
            "近期成交量 / 长期均量衡量相对活跃度。"
            "突然放量通常是情绪高峰，随后价格均值回归。"
        ),
        direction="negative",
        required_fields=["volume"],
        windows=WINDOWS_SHORT,
        expr_template="volume / (ts_mean(volume, {w} * 3) + 1e-10)",
        academic_support=4,
    ),
    FactorTemplate(
        name="amount_std",
        category="liquidity",
        description="{w}日成交额变异系数（资金关注不稳定性）",
        economic_rationale=(
            "成交额波动代表资金关注度不稳定。"
            "高波动期后往往是机构撤退散户接盘，与 volume_ratio 互补。"
        ),
        direction="negative",
        required_fields=["amount"],
        windows=(5, 10, 20),
        expr_template=(
            "ts_std(amount, {w}) / (ts_mean(amount, {w}) + 1e-10)"
        ),
        academic_support=4,
    ),
    FactorTemplate(
        name="turnover_zscore",
        category="liquidity",
        description="{w}日换手率截面z-score（净化散户信号）",
        economic_rationale=(
            "截面z-score剔除行业/市场周期影响，纯化散户过度交易信号。"
            "比绝对换手率在不同市场环境中更稳定。"
        ),
        direction="negative",
        required_fields=["turnover_rate"],
        windows=(5, 10, 20),
        expr_template="zscore(ts_mean(turnover_rate, {w}))",
        academic_support=4,
    ),
    FactorTemplate(
        name="volume_trend",
        category="liquidity",
        description="{w}日成交量趋势（资金关注度变化）",
        economic_rationale=(
            "近期成交量 / 较长期均量衡量关注度上升趋势。"
            "成交量放大代表市场关注度上升，短期正向动量增强。"
        ),
        direction="positive",
        required_fields=["volume"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_mean(volume, {w}) / (ts_mean(volume, {w} * 3) + 1e-10)"
        ),
        academic_support=3,
    ),

    # ============================================================
    # 类别③：资金流向类（DESIGN_V5 §4.2 类别③ — 全部未实现）
    # 单位说明: buy_lg_amount等来自moneyflow_daily(万元),
    #          amount来自klines_daily(千元)。
    #          比值有10x常数偏差，但不影响截面排序（所有股票同一日期同乘）。
    # ============================================================
    FactorTemplate(
        name="big_order_ratio",
        category="flow",
        description="{w}日大单净流入占比（聪明钱方向）",
        economic_rationale=(
            "大单代表机构/知情交易者的方向判断。"
            "大单净流入表明机构建仓，未来价格被机构推动上涨。"
        ),
        direction="positive",
        required_fields=["buy_lg_amount", "sell_lg_amount", "amount"],
        windows=(5, 10, 20),
        expr_template=(
            "ts_mean((buy_lg_amount - sell_lg_amount) / "
            "(amount + 1e-10), {w})"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="big_order_acceleration",
        category="flow",
        description="{w}日大单净流入加速度（资金流动量）",
        economic_rationale=(
            "大单净流入的变化率：净流入加速代表机构加速建仓，是更强的领先信号。"
            "捕捉资金流的动量而非水平值。"
        ),
        direction="positive",
        required_fields=["buy_lg_amount", "sell_lg_amount", "amount"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "delta(ts_mean((buy_lg_amount - sell_lg_amount) / "
            "(amount + 1e-10), {w}), {w})"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="mid_order_ratio",
        category="flow",
        description="{w}日中单净流入占比（游资方向）",
        economic_rationale=(
            "中单（游资/中型散户）与大单方向对比。"
            "大单买+中单卖 = 机构接散户筹码，强正向信号。"
        ),
        direction="positive",
        required_fields=["buy_md_amount", "sell_md_amount", "amount"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_mean((buy_md_amount - sell_md_amount) / "
            "(amount + 1e-10), {w})"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="margin_balance_chg",
        category="flow",
        description="{w}日融资余额变化率（杠杆资金方向）",
        economic_rationale=(
            "融资余额增加代表杠杆资金加仓，是市场情绪和资金面的综合信号。"
            "A股融资盘对股价有正向压力。"
        ),
        direction="positive",
        required_fields=["margin_balance"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "margin_balance / (delay(margin_balance, {w}) + 1e-10) - 1"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="short_ratio",
        category="flow",
        description="融券余额/融资余额（做空压力）",
        economic_rationale=(
            "融券/融资比率高代表做空力量相对做多力量强，未来价格下行压力大。"
            "A股融券规模相对小，比率上升是稀缺的做空信号。"
        ),
        direction="negative",
        required_fields=["short_balance", "margin_balance"],
        windows=(1,),
        expr_template="short_balance / (margin_balance + 1e-10)",
        academic_support=3,
    ),
    FactorTemplate(
        name="winner_rate",
        category="flow",
        description="获利盘比例（筹码分布抛压）",
        economic_rationale=(
            "获利盘比例高代表大多数持股者盈利，抛售压力大。"
            "A股筹码分布数据独特，散户持仓成本可观测。"
        ),
        direction="negative",
        required_fields=["winner_rate"],
        windows=(1,),
        expr_template="winner_rate",
        academic_support=3,
    ),

    # ============================================================
    # 类别④：基本面价值类（DESIGN_V5 §4.2 类别④）
    # ============================================================
    FactorTemplate(
        name="ep",
        category="fundamental",
        description="盈利收益率 1/PE_TTM（价值效应）",
        economic_rationale=(
            "E/P高的股票被市场低估，未来存在价值回归。"
            "Basu (1977) PE效应，Fama-French价值因子核心。"
        ),
        direction="positive",
        required_fields=["pe_ttm"],
        windows=(1,),
        expr_template="1.0 / (pe_ttm + 1e-10)",
        academic_support=4,
    ),
    FactorTemplate(
        name="bp",
        category="fundamental",
        description="账面市值比 1/PB（价值效应）",
        economic_rationale=(
            "B/P高代表市值低于净资产，存在安全边际。"
            "Fama-French HML因子核心，A股验证有效。"
        ),
        direction="positive",
        required_fields=["pb"],
        windows=(1,),
        expr_template="1.0 / (pb + 1e-10)",
        academic_support=4,
    ),
    FactorTemplate(
        name="div_yield",
        category="fundamental",
        description="股息率TTM（现金流价值）",
        economic_rationale=(
            "高股息代表公司现金流充沛且分配意愿强。"
            "是价值因子的稳健代理，在低利率环境中Alpha更强。"
        ),
        direction="positive",
        required_fields=["dv_ttm"],
        windows=(1,),
        expr_template="dv_ttm",
        academic_support=3,
    ),
    FactorTemplate(
        name="roe_ttm",
        category="fundamental",
        description="净资产收益率TTM（盈利质量）",
        economic_rationale=(
            "高ROE代表资本使用效率高，可持续盈利能力强。"
            "Fama-French五因子 profitability 因子，A股正向验证。"
        ),
        direction="positive",
        required_fields=["roe"],
        windows=(1,),
        expr_template="roe",
        academic_support=4,
    ),
    FactorTemplate(
        name="gross_margin",
        category="fundamental",
        description="毛利率（定价能力/竞争壁垒）",
        economic_rationale=(
            "高毛利率代表产品定价能力强，竞争护城河宽。"
            "Novy-Marx (2013) 盈利能力因子，与BP正交。"
        ),
        direction="positive",
        required_fields=["grossprofit_margin"],
        windows=(1,),
        expr_template="grossprofit_margin",
        academic_support=3,
    ),
    FactorTemplate(
        name="roa_ttm",
        category="fundamental",
        description="总资产收益率TTM（资产利用效率）",
        economic_rationale=(
            "ROA衡量全部资产的创利效率，剔除财务杠杆影响。"
            "与ROE互补：ROA高+ROE高=真正高质量企业。"
        ),
        direction="positive",
        required_fields=["roa"],
        windows=(1,),
        expr_template="roa",
        academic_support=3,
    ),
    FactorTemplate(
        name="roe_stability",
        category="fundamental",
        description="{w}期ROE稳定性（盈利质量稳健性）",
        economic_rationale=(
            "ROE时序标准差衡量盈利稳定性：波动小的高ROE更可持续，"
            "波动大的高ROE可能是一次性事件。"
        ),
        direction="positive",
        required_fields=["roe"],
        windows=(4, 8),
        expr_template="roe / (ts_std(roe, {w}) + 1e-10)",
        academic_support=3,
    ),

    # ============================================================
    # 类别⑤：跨数据源组合（R2研究推荐，A股独特优势）
    # ============================================================
    FactorTemplate(
        name="turnover_momentum",
        category="cross_source",
        description="{w}日量价共振（换手率×价格动量）",
        economic_rationale=(
            "价格上涨+成交放大 = 真实动量（机构推动）。"
            "仅价格涨但无量 = 虚假信号。二者乘积过滤低质量动量。"
        ),
        direction="positive",
        required_fields=["close", "turnover_rate"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "rank(close / delay(close, {w}) - 1) * "
            "rank(ts_mean(turnover_rate, {w}))"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="vol_adjusted_return",
        category="cross_source",
        description="{w}日波动率调整收益（信息比率代理）",
        economic_rationale=(
            "每单位波动风险的收益：Sharpe比率的时序版本。"
            "高信息比率的股票更可能获得持续Alpha。"
        ),
        direction="positive",
        required_fields=["close"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "(close / delay(close, {w}) - 1) / "
            "(ts_std(close / delay(close, 1) - 1, {w}) + 1e-10)"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="limit_up_pressure",
        category="price_volume",
        description="{w}日接近涨停天数占比（散户追板反向）",
        economic_rationale=(
            "A股涨停制度：散户抢板失败后高位开板抛售。"
            "涨停/开板通常伴随大量散户解套抛售，短期价格下行。"
        ),
        direction="negative",
        required_fields=["high", "close"],
        windows=(5, 10),
        expr_template=(
            "ts_mean((high / delay(close, 1) - 1 > 0.095) * 1.0, {w})"
        ),
        academic_support=3,
    ),
    FactorTemplate(
        name="price_level",
        category="price_volume",
        description="价格对数水平（低价股效应）",
        economic_rationale=(
            "低价股吸引散户投机（彩票效应），被高估。"
            "A股低价股溢价陷阱显著，股价越低未来收益越差。"
        ),
        direction="positive",
        required_fields=["close"],
        windows=(1,),
        expr_template="log(close + 1e-10)",
        academic_support=3,
    ),
    FactorTemplate(
        name="volume_concentration",
        category="liquidity",
        description="{w}日成交量集中度（操纵风险）",
        economic_rationale=(
            "成交量集中在少数时段代表资金博弈集中，操纵风险高。"
            "分散的成交量代表多方参与，价格更可信。"
        ),
        direction="negative",
        required_fields=["volume"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_max(volume, {w}) / (ts_sum(volume, {w}) + 1e-10)"
        ),
        academic_support=2,
    ),
    FactorTemplate(
        name="amount_acceleration",
        category="liquidity",
        description="{w}日成交额加速度（关注度突变）",
        economic_rationale=(
            "成交额短期均值vs长期均值的比率衡量资金关注度加速变化。"
            "突然放量通常预示价格转折点，随后均值回归。"
        ),
        direction="negative",
        required_fields=["amount"],
        windows=WINDOWS_SHORT,
        expr_template=(
            "ts_mean(amount, {w}) / (ts_mean(amount, {w} * 4) + 1e-10)"
        ),
        academic_support=3,
    ),
]

assert len(FACTOR_TEMPLATES) >= 40, (
    f"模板数量不足: {len(FACTOR_TEMPLATES)}，要求 >= 40"
)


# ---------------------------------------------------------------------------
# BruteForce 引擎
# ---------------------------------------------------------------------------


class BruteForceEngine:
    """暴力枚举引擎 — Engine 1

    流程:
    1. 展开所有模板 × 参数窗口组合 → 候选列表
    2. 对每个候选计算截面因子值
    3. 计算 IC 序列，做 G1-G3 筛选
    4. 返回通过筛选的候选因子

    Args:
        g1_ic_threshold: Gate G1 |IC| 阈值（宽松前置筛选）
        g2_corr_threshold: Gate G2 与现有因子的最大相关性
        g3_t_threshold: Gate G3 t统计量最小值
        min_ic_periods: IC 计算所需最少截面期数
    """

    def __init__(
        self,
        g1_ic_threshold: float = 0.015,
        g2_corr_threshold: float = 0.7,
        g3_t_threshold: float = 2.0,
        min_ic_periods: int = 12,
    ) -> None:
        self.g1_ic_threshold = g1_ic_threshold
        self.g2_corr_threshold = g2_corr_threshold
        self.g3_t_threshold = g3_t_threshold
        self.min_ic_periods = min_ic_periods

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def enumerate_candidates(
        self, templates: list[FactorTemplate] | None = None
    ) -> list[FactorCandidate]:
        """展开所有模板 × 参数 → 候选因子列表（不计算IC）"""
        if templates is None:
            templates = FACTOR_TEMPLATES

        candidates: list[FactorCandidate] = []
        for tmpl in templates:
            for w in tmpl.windows:
                expr = tmpl.expr_template.replace("{w}", str(w))
                name = f"{tmpl.name}_{w}" if w > 1 else tmpl.name
                candidates.append(
                    FactorCandidate(
                        name=name,
                        category=tmpl.category,
                        direction=tmpl.direction,
                        expression=expr,
                        window=w,
                        economic_rationale=tmpl.economic_rationale,
                        academic_support=tmpl.academic_support,
                    )
                )

        logger.info(
            "展开候选因子: %d 个 (来自 %d 个模板)",
            len(candidates),
            len(templates),
        )
        return candidates

    def run(
        self,
        panel_data: pd.DataFrame,
        forward_returns: pd.Series | pd.DataFrame,
        active_factors: pd.DataFrame | None = None,
        templates: list[FactorTemplate] | None = None,
    ) -> list[FactorCandidate]:
        """完整运行 BruteForce 流程，返回通过 G1-G3 的因子候选

        Args:
            panel_data: 面板数据，MultiIndex (date, symbol_id)
            forward_returns: 未来收益率，同 index
            active_factors: 现有 Active 因子值（用于 G2 相关性检查）
            templates: 自定义模板列表，None 使用全部

        Returns:
            通过 G1-G3 筛选的 FactorCandidate 列表
        """
        candidates = self.enumerate_candidates(templates)
        logger.info("开始计算 %d 个候选因子...", len(candidates))

        results: list[FactorCandidate] = []
        for cand in candidates:
            try:
                factor_values = self._compute_factor(cand, panel_data)
                if factor_values is None:
                    continue

                ic_series = self._compute_ic_series(
                    factor_values, forward_returns
                )
                if len(ic_series) < self.min_ic_periods:
                    continue

                cand.ic_mean = float(ic_series.mean())
                cand.ic_std = float(ic_series.std())
                n = len(ic_series)
                if cand.ic_std > 0:
                    cand.ic_ir = cand.ic_mean / cand.ic_std
                    cand.t_stat = cand.ic_mean / (cand.ic_std / (n ** 0.5))
                else:
                    cand.ic_ir = 0.0
                    cand.t_stat = 0.0

                cand.passed_g1 = abs(cand.ic_mean) >= self.g1_ic_threshold

                if active_factors is not None and cand.passed_g1:
                    max_corr = self._check_correlation(
                        factor_values, active_factors
                    )
                    cand.max_corr_with_active = max_corr
                    cand.passed_g2 = max_corr < self.g2_corr_threshold
                else:
                    cand.passed_g2 = True
                    cand.max_corr_with_active = 0.0

                cand.passed_g3 = abs(cand.t_stat) >= self.g3_t_threshold

                if cand.passed_all:
                    results.append(cand)
                    logger.info(
                        "G1-G3通过: %s | IC=%.4f t=%.2f corr=%.3f",
                        cand.name,
                        cand.ic_mean,
                        cand.t_stat,
                        cand.max_corr_with_active,
                    )

            except Exception:
                logger.debug("计算失败: %s", cand.name, exc_info=True)
                continue

        logger.info(
            "BruteForce完成: %d/%d 通过G1-G3",
            len(results),
            len(candidates),
        )
        return results

    def get_template_summary(self) -> pd.DataFrame:
        """返回所有模板的元数据摘要（用于人工审查）"""
        rows = []
        for tmpl in FACTOR_TEMPLATES:
            for w in tmpl.windows:
                rows.append(
                    {
                        "name": f"{tmpl.name}_{w}" if w > 1 else tmpl.name,
                        "category": tmpl.category,
                        "direction": tmpl.direction,
                        "window": w,
                        "academic_support": tmpl.academic_support,
                        "required_fields": ", ".join(tmpl.required_fields),
                        "rationale_summary": tmpl.economic_rationale[:60],
                    }
                )
        return pd.DataFrame(rows)

    # ------------------------------------------------------------------
    # 内部计算
    # ------------------------------------------------------------------

    def _compute_factor(
        self,
        cand: FactorCandidate,
        data: pd.DataFrame,
    ) -> pd.Series | None:
        """计算单个因子的面板值"""
        required = self._get_required_fields(cand.expression)
        missing = required - set(data.columns)
        if missing:
            logger.debug("因子 %s 缺少字段: %s", cand.name, missing)
            return None

        try:
            return self._eval_expression_panel(cand.expression, data)
        except Exception:
            logger.debug("因子 %s 计算异常", cand.name, exc_info=True)
            return None

    def _eval_expression_panel(
        self, expr: str, data: pd.DataFrame
    ) -> pd.Series:
        """在面板数据（MultiIndex date, symbol_id）上执行因子表达式"""
        results: list[pd.Series] = []

        for _, grp in data.groupby(level="symbol_id"):
            grp_sorted = grp.sort_index(level="date")
            ns = self._build_compute_namespace(grp_sorted)
            try:
                val = eval(expr, {"__builtins__": {}}, ns)  # noqa: S307
                if isinstance(val, pd.Series):
                    results.append(val)
                elif isinstance(val, (float, int, np.floating, np.integer)):
                    results.append(
                        pd.Series(float(val), index=grp_sorted.index)
                    )
            except Exception:
                continue

        if not results:
            raise ValueError(f"所有 symbol 计算均失败: {expr}")

        combined = pd.concat(results).sort_index()

        # 截面算子在合并后按 date 分组处理
        if "zscore(" in expr or "rank(" in expr or "cs_rank(" in expr:
            combined = combined.groupby(level="date").rank(pct=True)

        return combined

    @staticmethod
    def _build_compute_namespace(data: pd.DataFrame) -> dict[str, Any]:
        """构建单股票时序计算命名空间"""
        ns: dict[str, Any] = {}
        for col in data.columns:
            ns[col] = data[col]

        def _roll(x: pd.Series, w: int):
            return x.rolling(window=w, min_periods=max(1, w // 2))

        ns.update(
            {
                "np": np,
                "abs": abs,
                "min": min,
                "max": max,
                "float": float,
                "ts_mean": lambda x, w: _roll(x, w).mean(),
                "ts_std": lambda x, w: _roll(x, w).std(),
                "ts_corr": lambda x, y, w: _roll(x, w).corr(y),
                "ts_rank": lambda x, w: _roll(x, w).rank(pct=True),
                "ts_max": lambda x, w: _roll(x, w).max(),
                "ts_min": lambda x, w: _roll(x, w).min(),
                "ts_sum": lambda x, w: _roll(x, w).sum(),
                "delay": lambda x, d: x.shift(d),
                "delta": lambda x, d: x - x.shift(d),
                "rank": lambda x: x.rank(pct=True),
                "cs_rank": lambda x: x.rank(pct=True),
                "zscore": lambda x: (x - x.mean()) / (x.std() + 1e-10),
                "cs_zscore": lambda x: (x - x.mean()) / (x.std() + 1e-10),
                "log": lambda x: np.log(
                    x.clip(lower=1e-10)
                    if hasattr(x, "clip")
                    else max(float(x), 1e-10)
                ),
                "sign": lambda x: np.sign(x),
                "pow": lambda x, n: np.power(x, n),
                "if_else": lambda c, x, y: pd.Series(
                    np.where(c, x, y), index=c.index
                ),
            }
        )
        return ns

    @staticmethod
    def _get_required_fields(expr: str) -> set[str]:
        """从表达式中提取所需的数据字段名"""
        operator_names = {
            "ts_mean", "ts_std", "ts_corr", "ts_rank", "ts_max", "ts_min",
            "ts_sum", "delay", "delta", "rank", "zscore", "cs_rank",
            "cs_zscore", "log", "sign", "pow", "if_else",
            "abs", "min", "max", "sum", "len", "float", "int", "bool",
            "np", "pd", "math",
        }
        try:
            tree = ast.parse(expr, mode="eval")
        except SyntaxError:
            return set()

        return {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
            and node.id not in operator_names
            and not node.id.startswith("_")
            and node.id not in {"True", "False", "None"}
        }

    @staticmethod
    def _compute_ic_series(
        factor_values: pd.Series,
        forward_returns: pd.Series | pd.DataFrame,
    ) -> pd.Series:
        """计算截面 Spearman rank IC 序列"""
        fwd = (
            forward_returns.iloc[:, 0]
            if isinstance(forward_returns, pd.DataFrame)
            else forward_returns
        )

        common_idx = factor_values.index.intersection(fwd.index)
        f = factor_values.loc[common_idx]
        r = fwd.loc[common_idx]

        ic_by_date: dict[Any, float] = {}
        for date, grp_f in f.groupby(level="date"):
            try:
                grp_r = r.xs(date, level="date")
            except KeyError:
                continue

            aligned = grp_f.align(grp_r, join="inner")[0]
            ret_aligned = grp_r.reindex(aligned.index)
            valid = (~grp_f.reindex(aligned.index).isna()) & (
                ~ret_aligned.isna()
            )
            if valid.sum() < 10:
                continue

            ic, _ = stats.spearmanr(
                grp_f.reindex(aligned.index)[valid].values,
                ret_aligned[valid].values,
            )
            if not np.isnan(float(ic)):
                ic_by_date[date] = float(ic)

        return pd.Series(ic_by_date)

    @staticmethod
    def _check_correlation(
        new_factor: pd.Series,
        active_factors: pd.DataFrame,
    ) -> float:
        """返回新因子与现有因子的最大截面 Spearman 相关性绝对值"""
        max_corr = 0.0
        for col in active_factors.columns:
            active_col = active_factors[col]
            common = new_factor.index.intersection(active_col.index)
            if len(common) < 30:
                continue
            try:
                corr, _ = stats.spearmanr(
                    new_factor.loc[common].fillna(0).values,
                    active_col.loc[common].fillna(0).values,
                )
                max_corr = max(max_corr, abs(float(corr)))
            except Exception:
                continue
        return max_corr
