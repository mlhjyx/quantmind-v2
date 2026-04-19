"""信号合成引擎 — 因子→信号→目标持仓。

Phase 0: 等权Top-N信号合成。
- 每个因子等权(1/N)
- 截面zscore后求和
- 排名取Top-N
- 行业约束(单行业≤25%)
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# 因子方向: +1表示因子值越大越好, -1表示越小越好
FACTOR_DIRECTION = {
    "momentum_5": 1,
    "momentum_10": 1,
    "momentum_20": 1,
    "reversal_5": 1,  # 已经取反(calc_reversal = -pct_change)
    "reversal_10": 1,
    "reversal_20": 1,
    "volatility_20": -1,  # 低波动好
    "volatility_60": -1,
    "volume_std_20": -1,  # 低量波动好
    "turnover_mean_20": -1,  # 低换手好
    "turnover_std_20": -1,
    "amihud_20": 1,  # 高非流动性=小盘溢价
    "ln_market_cap": -1,  # 小市值好(Phase 0)
    "bp_ratio": 1,  # 高B/P=价值股好
    "ep_ratio": 1,  # 高E/P好
    "price_volume_corr_20": -1,  # 低价量相关好
    "high_low_range_20": -1,  # 低振幅好
    "mf_momentum_divergence": -1,  # 资金流动量背离: 值越负=背离越大→信号越强
    "earnings_surprise_car": 1,  # PEAD盈利惊喜CAR: 正惊喜→正漂移, 方向+1
    # ---- v1.2 新增因子 ----
    "price_level_factor": -1,  # -ln(close), 方向-1: 低价股偏好（因子本身已取负，direction再取反→选低价）
    "relative_volume_20": -1,  # 相对成交量, 方向-1: 低异常放量好
    "dv_ttm": 1,  # 股息率TTM, 方向+1: 高股息好
    "turnover_surge_ratio": -1,  # 换手率突增比, 方向-1: 低突增好
    # ---- Phase 2.1 E2E因子 ----
    "high_vol_price_ratio_20": -1,  # 高波动日价偏高=庄家出货
    "IMAX_20": -1,   # 极端正收益=彩票偏好被高估
    "IMIN_20": 1,    # 深跌后均值回归
    "QTLU_20": -1,   # 上行偏度=过度乐观
    "CORD_20": -1,   # 强上行趋势=反转
    "RSQR_20": -1,   # 低R²=特质风险=散户溢价
    "RESI_20": 1,    # 正alpha=近期跑赢
}


# ============================================================
# MVP 1.3b: Direction DB 化 — 3 层 fallback
# ============================================================
# 默认 FeatureFlag `use_db_direction` = False → 走 FACTOR_DIRECTION hardcoded
# (regression max_diff=0 锚点稳定). 切 True 后走 FactorRegistry + in-memory cache.
# DB 挂或 cache miss → fallback hardcoded (永远兜底).
#
# 调用方 (PT / FastAPI / test) 通过 `init_platform_dependencies(registry, flag_db)`
# 注入 DBFactorRegistry + DBFeatureFlag 实例. 未注入时 _get_direction 直接走 hardcoded.

_PLATFORM_REGISTRY = None  # type: ignore[var-annotated]  # DBFactorRegistry | None
_PLATFORM_FLAG_DB = None   # type: ignore[var-annotated]  # DBFeatureFlag | None
_USE_DB_DIRECTION_FLAG_NAME = "use_db_direction"


def init_platform_dependencies(registry=None, flag_db=None) -> None:
    """PT / FastAPI 启动时注入 Platform 单例. 允许 None (保向后兼容)."""
    global _PLATFORM_REGISTRY, _PLATFORM_FLAG_DB
    _PLATFORM_REGISTRY = registry
    _PLATFORM_FLAG_DB = flag_db


def _get_direction(fname: str) -> int:
    """3 层 fallback 读 direction.

    Layer 0: FeatureFlag `use_db_direction` 未开或未注入 → hardcoded (默认)
    Layer 1: Flag 开 + Registry 有 → DB + cache (新路径)
    Layer 3: 任一 Layer 1 异常 → hardcoded (兜底, logger.warning)
    """
    if _PLATFORM_FLAG_DB is not None and _PLATFORM_REGISTRY is not None:
        try:
            if _PLATFORM_FLAG_DB.is_enabled(_USE_DB_DIRECTION_FLAG_NAME):
                try:
                    return _PLATFORM_REGISTRY.get_direction(fname)
                except Exception as e:
                    logger.warning(
                        f"[signal_engine] DB direction lookup failed for {fname}: {e}. "
                        f"Fallback to hardcoded."
                    )
        except Exception:  # silent_ok: FlagNotFound / DB transient → hardcoded fallback
            pass
    return FACTOR_DIRECTION.get(fname, 1)


# MVP 2.3 Sub3 C2: CORE3+dv_ttm hardcoded fallback 常量 (SSOT drift 消除).
#
# 用途:
#   1. SignalConfig.factor_names=None sentinel 回退 (50+ 老调用方 0 break)
#   2. _build_paper_trading_config YAML load 失败时的 fail-safe
#
# 权威: `configs/pt_live.yaml:strategy.factors` (auditor.py L96-98 注释明定).
# 本常量仅作 sentinel 回退值, auditor.check_config_alignment 会审 yaml ↔ python 对齐
# 检出 drift 抛 ConfigDriftError (铁律 34). 若 yaml 改了因子, 更新此常量 + pt_live.yaml
# 对齐即可, drift 被 auditor 硬拦截.
_PT_FACTOR_NAMES_DEFAULT: tuple[str, ...] = (
    "turnover_mean_20",
    "volatility_20",
    "bp_ratio",
    "dv_ttm",
)


@dataclass
class SignalConfig:
    """信号生成配置.

    Sub3 C2 change (2026-04-19): `factor_names` 改 sentinel `None` + `__post_init__` 回退
    到 `_PT_FACTOR_NAMES_DEFAULT` (CORE3+dv_ttm). 动机:

      - 消除 hardcoded `default_factory` 与 `_build_paper_trading_config` 的双份 SSOT 源
      - 兼容 50+ 老调用方 `SignalConfig()` 无参构造 (行为保持 CORE3+dv_ttm)
      - 硬拦截放 `auditor.check_config_alignment` (铁律 34), 不放 dataclass 侧

    其他字段保持旧行为 — `rebalance_freq` / `turnover_cap` 默认仍匹配 PT 生产值 (monthly / 0.50),
    避免破 50+ 调用方. PT 生产路径通过 `_build_paper_trading_config()` 从 YAML 读覆盖.

    S2 F40 fix (2026-04-15): 默认值已对齐生产 PT (CORE3+dv_ttm + monthly + no industry cap + SN=0.50).
    任何未显式传参的 `SignalConfig()` 调用将拿到与 `PAPER_TRADING_CONFIG` 等价的默认值.
    """

    top_n: int = 20
    weight_method: str = "equal"  # 'equal' or 'score_weighted'
    industry_cap: float = 1.0  # 1.0=无约束 (原 0.25 已不匹配生产 PT)
    rebalance_freq: str = "monthly"  # 'weekly', 'biweekly', 'monthly' — 原 biweekly 已过期
    turnover_cap: float = 0.50  # 单次换手率上限50%
    cash_buffer: float = 0.03  # 现金缓冲3%: 目标权重总和 = 1 - cash_buffer
    size_neutral_beta: float = 0.50  # Step 6-H 验证, WF OOS Sharpe 0.8659 依赖此值
    regime_mode: str = "vol_regime"  # 'vol_regime'（启发式）或 'hmm_regime'（HMM）
    # Sub3 C2: sentinel None → __post_init__ 回退 _PT_FACTOR_NAMES_DEFAULT 消除 SSOT drift
    factor_names: list[str] | None = None

    def __post_init__(self) -> None:
        """Sub3 C2: factor_names=None 回退 CORE3+dv_ttm (50+ 老调用方 0 break)."""
        if self.factor_names is None:
            self.factor_names = list(_PT_FACTOR_NAMES_DEFAULT)


# Route A配置: CORE3+dv_ttm 等权 + 月频
# Sub3 C2 change (2026-04-19): `_build_paper_trading_config` 改从 `configs/pt_live.yaml` 读
# factor_names / rebalance_freq / turnover_cap 取代 hardcoded 副本 (auditor.py L96-98 注释明定
# "YAML 是 factor_list / rebalance_freq / turnover_cap 权威"). YAML 加载失败 fail-safe 回退
# _PT_FACTOR_NAMES_DEFAULT (铁律 33 非静默: logger.warning 暴露).
#
# 其他字段仍从 .env 读 (top_n / industry_cap / size_neutral_beta 是 .env 权威字段, PT 可配置).
def _load_pt_yaml_strategy() -> dict:
    """直接读取 configs/pt_live.yaml 的 strategy 段. 独立 helper 避免 side effect.

    Sub3 C2 review fix (自测): 原走 `from app.services.config_loader import load_config`
    会触发 `app.services.__init__.py` import chain → sqlalchemy 等 IO 依赖加载,
    破 `test_platform_import_has_no_side_effects` (Platform 入口纯度守门).
    改直接 `yaml.safe_load` 绕开 app.services 整体 import.

    Returns:
        strategy 段 dict (空 dict 若文件缺失 / 格式异常, 让调用方 fallback).
    """
    import yaml

    # 项目根 = backend/engines/signal_engine.py 向上 3 层
    project_root = Path(__file__).resolve().parent.parent.parent
    yaml_path = project_root / "configs" / "pt_live.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(f"pt_live.yaml not found: {yaml_path}")
    with yaml_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError(f"pt_live.yaml 顶层不是 dict: {yaml_path}")
    strategy = cfg.get("strategy", {})
    if not isinstance(strategy, dict):
        raise ValueError(f"pt_live.yaml strategy 段不是 dict: {yaml_path}")
    return strategy


def _build_paper_trading_config() -> SignalConfig:
    """从 YAML + .env 构建 PT 配置 (YAML 权威 for factor/freq/turnover, .env 权威 for top_n/industry/SN)."""
    from app.config import settings

    # Sub3 C2: YAML 权威字段 (factor_names / rebalance_freq / turnover_cap)
    factor_names: list[str]
    rebalance_freq: str
    turnover_cap: float
    try:
        strategy = _load_pt_yaml_strategy()
        factors_raw = strategy.get("factors", [])
        factor_names = [f["name"] for f in factors_raw if isinstance(f, dict) and "name" in f]
        if not factor_names:
            raise ValueError("pt_live.yaml strategy.factors 为空或格式不符 (expect list[{name, direction}])")
        rebalance_freq = str(strategy.get("rebalance_freq", "monthly"))
        turnover_cap = float(strategy.get("turnover_cap", 0.50))
    except Exception as e:  # noqa: BLE001 — fail-safe fallback to hardcoded (铁律 33: warn non-silent)
        logger.warning(
            "[signal_engine] _build_paper_trading_config YAML load failed, "
            "fallback hardcoded CORE3+dv_ttm (auditor 仍会审 drift): %s",
            e,
        )
        factor_names = list(_PT_FACTOR_NAMES_DEFAULT)
        rebalance_freq = "monthly"
        turnover_cap = 0.50

    return SignalConfig(
        factor_names=factor_names,
        top_n=settings.PT_TOP_N,
        weight_method="equal",
        rebalance_freq=rebalance_freq,
        industry_cap=settings.PT_INDUSTRY_CAP,
        turnover_cap=turnover_cap,
        size_neutral_beta=settings.PT_SIZE_NEUTRAL_BETA,
    )


PAPER_TRADING_CONFIG = _build_paper_trading_config()

# 注: V12_CONFIG 于 2026-04-15 删除 (S1 audit F41).
# 原因: mf_momentum_divergence 已被 v3.4 证伪 (IC=-2.27% 非 9.1%, INVALIDATED),
# V12_CONFIG 的注释基于已否决的虚假 IC 数据, 且当前生产 PT 走 PAPER_TRADING_CONFIG,
# V12_CONFIG 无任何生产/研究引用 (grep 确认). 详见 docs/audit/S1_three_way_alignment.md F41.


class SignalComposer:
    """信号合成器 — 因子→composite score→排名。"""

    def __init__(self, config: SignalConfig):
        self.config = config

    def compose(
        self,
        factor_df: pd.DataFrame,
        universe: set[str] | None = None,
        exclude: set[str] | None = None,
    ) -> pd.Series:
        """合成综合因子得分。

        Args:
            factor_df: 宽表 columns=[code, factor_name, neutral_value]
                       （单日截面数据）
            universe: 可选的universe包含集合
            exclude: 可选的排除集合(ST/停牌/新股/BJ等,日期级过滤)

        Returns:
            pd.Series indexed by code, values = composite score
        """
        # Pivot to wide format: code × factor_name
        pivot = factor_df.pivot_table(
            index="code",
            columns="factor_name",
            values="neutral_value",
            aggfunc="first",
        )

        if universe:
            pivot = pivot[pivot.index.isin(universe)]

        if exclude:
            pivot = pivot[~pivot.index.isin(exclude)]

        # 选择配置的因子
        available = [f for f in self.config.factor_names if f in pivot.columns]
        if not available:
            logger.warning("无可用因子")
            return pd.Series(dtype=float)

        pivot = pivot[available]

        # 方向调整 — MVP 1.3b: 3 层 fallback (cache → DB → hardcoded).
        # FeatureFlag `use_db_direction` 默认 False → 走 hardcoded (老路径, regression max_diff=0 锚点)
        for fname in available:
            direction = _get_direction(fname)
            if direction == -1:
                pivot[fname] = -pivot[fname]

        # 等权合成
        weights = {f: 1.0 / len(available) for f in available}
        composite = sum(pivot[f] * w for f, w in weights.items())

        # A10: mergesort保证相同score下行顺序确定性（quicksort不稳定）
        return composite.sort_values(ascending=False, kind="mergesort")


class PortfolioBuilder:
    """目标持仓构建器 — composite score → 目标权重。"""

    def __init__(self, config: SignalConfig):
        self.config = config

    def build(
        self,
        scores: pd.Series,
        industry: pd.Series,
        prev_holdings: dict[str, float] | None = None,
        vol_regime_scale: float = 1.0,
        volatility_map: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """构建目标持仓权重。

        Args:
            scores: 综合得分 (code → score), 已排序
            industry: 行业分类 (code → industry_sw1)
            prev_holdings: 上期持仓权重 (code → weight)
            vol_regime_scale: 波动率regime缩放系数 [0.5, 2.0]，默认1.0（不调整）。
                              由vol_regime.calc_vol_regime()计算并在调用方传入。
            volatility_map: 个股波动率 {code: raw_value}，risk_parity/min_variance模式必需。
                            用raw_value（非neutral_value），中性化后的不适合做绝对风险度量。

        Returns:
            dict: {code: target_weight}, 权重之和 = (1 - cash_buffer) × vol_regime_scale
        """
        top_n = self.config.top_n
        industry_cap = self.config.industry_cap
        max_per_industry = int(top_n * industry_cap)

        # 1. 按分数排名选股，加行业约束
        selected = []
        industry_count = {}

        for code in scores.index:
            if len(selected) >= top_n:
                break

            ind = industry.get(code, "其他")
            cnt = industry_count.get(ind, 0)
            if cnt >= max_per_industry:
                continue

            selected.append(code)
            industry_count[ind] = cnt + 1

        if not selected:
            return {}

        # 2. 权重分配
        if self.config.weight_method == "equal":
            weight = 1.0 / len(selected)
            target = {code: weight for code in selected}
        elif self.config.weight_method == "risk_parity":
            target = self._calc_risk_parity_weights(selected, volatility_map, power=1)
        elif self.config.weight_method == "min_variance":
            target = self._calc_risk_parity_weights(selected, volatility_map, power=2)
        else:
            # score_weighted (Phase 1)
            sel_scores = scores.loc[selected]
            sel_scores = sel_scores - sel_scores.min() + 1e-6  # shift to positive
            total = sel_scores.sum()
            target = {code: float(s / total) for code, s in sel_scores.items()}

        # 3. 换手率约束（在cash_buffer缩放前做，以便内部归一化不影响缓冲比例）
        if prev_holdings and self.config.turnover_cap < 1.0:
            target = self._apply_turnover_cap(target, prev_holdings)

        # 4. 现金缓冲: 目标权重总和 = 1 - cash_buffer (强制保留现金，最后一步应用)
        # 放在turnover_cap之后，避免被内部归一化覆盖
        if self.config.cash_buffer > 0:
            invest_ratio = 1.0 - self.config.cash_buffer
            target = {code: w * invest_ratio for code, w in target.items()}

        # 5. 波动率regime缩放: 高波动降仓，低波动加仓 (Sprint 1.1)
        # scale在cash_buffer之后应用，进一步调整总投入比例
        if abs(vol_regime_scale - 1.0) > 1e-6:
            target = {code: w * vol_regime_scale for code, w in target.items()}
            logger.info(
                f"[VolRegime] 仓位缩放 scale={vol_regime_scale:.4f}, "
                f"权重总和={sum(target.values()):.4f}"
            )

        return target

    def _calc_risk_parity_weights(
        self,
        selected: list[str],
        volatility_map: dict[str, float] | None,
        power: int = 1,
    ) -> dict[str, float]:
        """反波动率加权: w_i ∝ 1/σ_i^power。

        power=1: 风险平价（risk parity），每只股票风险贡献近似均等。
        power=2: 最小方差近似（min variance），更激进地惩罚高波动。

        Args:
            selected: 选中的股票代码列表。
            volatility_map: {code: raw_volatility}，来自factor_values.raw_value。
            power: 波动率的幂次（1=风险平价, 2=最小方差）。

        Returns:
            {code: weight}，权重和=1。
        """
        import numpy as np

        n = len(selected)
        if n == 0:
            return {}

        # fallback: 无波动率数据时退化为等权
        if not volatility_map:
            logger.warning("[RiskParity] 无volatility_map，退化为等权")
            w = 1.0 / n
            return {code: w for code in selected}

        # 提取波动率，缺失值用截面中位数填充
        vols_raw = [volatility_map.get(code) for code in selected]
        valid_vols = [v for v in vols_raw if v is not None and v > 0]

        if not valid_vols:
            logger.warning("[RiskParity] 所有股票波动率缺失，退化为等权")
            w = 1.0 / n
            return {code: w for code in selected}

        median_vol = float(np.median(valid_vols))
        vols = []
        for v in vols_raw:
            if v is not None and v > 0:
                vols.append(v)
            else:
                vols.append(median_vol)

        vols_arr = np.array(vols, dtype=float)

        # clip到[5th, 95th]分位数防极端权重
        lo, hi = np.percentile(vols_arr, [5, 95])
        if lo < hi:
            vols_arr = np.clip(vols_arr, lo, hi)

        # 反波动率加权
        inv_vol = 1.0 / (vols_arr ** power)
        weights = inv_vol / inv_vol.sum()

        # 单只上限: min(15%, 2/N)
        max_w = min(0.15, 2.0 / n)
        weights = np.clip(weights, 0, max_w)
        weights = weights / weights.sum()  # 重新归一化

        target = {code: float(w) for code, w in zip(selected, weights, strict=False)}

        logger.info(
            f"[RiskParity] power={power}, n={n}, "
            f"vol range=[{vols_arr.min():.4f}, {vols_arr.max():.4f}], "
            f"weight range=[{weights.min():.4f}, {weights.max():.4f}]"
        )
        return target

    def _apply_turnover_cap(
        self,
        target: dict[str, float],
        prev: dict[str, float],
    ) -> dict[str, float]:
        """应用换手率上限（严格保持Top-N持仓数）。

        关键不变式: 输出持仓数 <= len(target) = top_n。
        旧持仓中不在target的股票目标权重=0（全卖），
        换手率上限只控制卖出速度，不保留旧持仓。

        Bug fix: 原代码对target∪prev取并集做blend,
        导致持仓从20膨胀到43。修复: blend后只保留target中的股票。
        """
        target_codes = set(target)
        all_codes = target_codes | set(prev)
        turnover = sum(abs(target.get(c, 0) - prev.get(c, 0)) for c in all_codes) / 2  # 单边换手

        if turnover <= self.config.turnover_cap:
            return target

        # 缩放变化量，降低换手率
        ratio = self.config.turnover_cap / max(turnover, 1e-12)
        blended = {}
        for c in all_codes:
            t = target.get(c, 0)
            p = prev.get(c, 0)
            blended[c] = p + ratio * (t - p)

        # ── 关键修复: 只保留target中的股票 ──
        # 旧持仓中不在target的股票: blended值>0但不应保留在目标中。
        # 它们在execute时会因target_weight=0而被卖出（受can_trade限制）。
        blended = {c: w for c, w in blended.items() if c in target_codes and w > 0.001}

        # 重新归一化
        total = sum(blended.values())
        if total > 0:
            blended = {c: w / total for c, w in blended.items()}

        return blended


def get_rebalance_dates(
    start_date: date,
    end_date: date,
    freq: str = "biweekly",
    conn=None,
) -> list[date]:
    """获取调仓日历(信号生成日)。

    调仓日=周五(信号日), 执行日=下周一。

    Args:
        start_date: 开始日期
        end_date: 结束日期
        freq: 'weekly', 'biweekly', 'monthly'
        conn: psycopg2连接

    Returns:
        list of signal dates (Fridays)
    """
    # MVP 2.1c 铁律 31: SELECT DISTINCT trade_date 迁至 DAL.read_calendar.
    # conn 参数保留向后兼容 (30+ 调用方签名不变), 但本函数内部改由 DAL 管理连接.
    del conn
    from app.services.price_utils import _get_sync_conn
    from backend.platform.data.access_layer import PlatformDataAccessLayer

    dal = PlatformDataAccessLayer(
        conn_factory=_get_sync_conn, paramstyle="%s",
    )
    all_dates = dal.read_calendar(start=start_date, end=end_date)

    if not all_dates:
        return []

    # 按周分组
    date_series = pd.Series(all_dates)

    if freq == "weekly":
        # 每周最后一个交易日
        weeks = date_series.groupby(date_series.apply(lambda d: d.isocalendar()[:2])).last()
        return sorted(weeks.tolist())

    elif freq == "biweekly":
        # 每两周最后一个交易日
        weeks = date_series.groupby(date_series.apply(lambda d: d.isocalendar()[:2])).last()
        return sorted(weeks.iloc[::2].tolist())

    elif freq == "monthly":
        # 每月最后一个交易日
        months = date_series.groupby(date_series.apply(lambda d: (d.year, d.month))).last()
        return sorted(months.tolist())

    else:
        raise ValueError(f"Unknown freq: {freq}")
