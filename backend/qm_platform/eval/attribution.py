"""MVP 4.2 Performance Attribution — DailyAttribution dataclass + interface (iter 59 entry).

Per QPB v1.16 §Wave 4 详细 MVP 4.2 spec + docs/mvp/MVP_4_2_attribution.md.

每日自动产出 DailyAttribution JSON, 拆解 PT NAV 变化为:
  - by_factor: per-factor P&L
  - by_sector: per-sector P&L
  - by_regime: regime context
  - by_cost: commission/slippage/impact/overnight_gap
  - alpha_vs_benchmark: 超额 vs CSI300/等权
  - unexplained_residual: 归因残差 (>阈值告警)

实施分批 (multi-iter campaign per MVP_4_2_attribution.md §4):
  - iter 59 (本): dataclass skeleton + interface stub + shape tests
  - iter 60+: compute_by_factor (WLS regression)
  - iter 61+: compute_by_sector (SW1 industry mapping)
  - iter 62+: compute_by_cost (trade_log aggregation)
  - iter 63+: compute_by_regime (HMM regime_detector)
  - iter 64+: residual alert via AlertRouter SDK (复用 batch 3.x pattern)
  - iter 65+: Daily Beat task

铁律对齐:
  - 24 (MVP ≤ 2页 spec)
  - 31 (Engine 纯计算 — compute_* 函数 stateless, 0 DB/HTTP/Redis)
  - 38 (Blueprint sustained — QPB v1.16 §Wave 4)

Platform 严格隔离 (沿用 MVP 1.1 test_platform_strict_isolation):
  - 0 import backend.app.* / backend.data.* / backend.engines.*
  - DI via conn_factory (writes) + DAL (reads), 沿用 factor/strategy registry 体例
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class RegimeInfo:
    """Regime detection context for daily attribution.

    Source: backend/engines/regime_detector.py 3-state HMM (bull/sideways/bear).
    iter 59: shape only; iter 63+ wire actual HMM probabilities.
    """

    detected: str  # "bull" / "sideways" / "bear"
    expected_perf_bps: float  # HMM 期望日收益 (basis points)
    actual_perf_bps: float  # 实际日收益 (basis points)


@dataclass(frozen=True)
class DailyAttribution:
    """每日归因 JSON payload (QPB v1.16 §Wave 4 MVP 4.2 spec).

    All P&L fields are decimal fractions (0.0012 = 0.12% = 12 bps).
    Residual = nav_change_pct - sum(by_factor) - sum(by_sector) - sum(by_cost) - alpha_vs_benchmark.
    """

    trade_date: date
    strategy_id: str
    execution_mode: str  # "paper" / "live" (sustained sustained namespace from V3 红线)
    nav_change_pct: float  # daily NAV change as decimal (0.012 = 1.2%)
    by_factor: dict[str, float] = field(default_factory=dict)
    by_sector: dict[str, float] = field(default_factory=dict)
    by_regime: RegimeInfo | None = None
    by_cost: dict[str, float] = field(default_factory=dict)
    alpha_vs_benchmark: float = 0.0  # vs CSI300 default
    unexplained_residual: float = 0.0


class AttributionEngine(Protocol):
    """MVP 4.2 attribution engine interface (iter 59 stub).

    Implementations (iter 60+):
      - WLSFactorAttributor (compute_by_factor via factor exposure regression)
      - SectorAttributor (compute_by_sector via SW1 industry mapping)
      - CostAttributor (compute_by_cost via trade_log slippage / commission fields)
      - RegimeAttributor (compute_by_regime via HMM 3-state probabilities)
      - ResidualAlerter (compute_residual_alert + AlertRouter SDK dispatch)
    """

    def compute(
        self,
        trade_date: date,
        strategy_id: str,
        execution_mode: str = "paper",
    ) -> DailyAttribution:
        """Compute daily attribution for given strategy + execution mode."""
        ...


def residual_exceeds_threshold(
    attribution: DailyAttribution,
    threshold_bps: float = 20.0,
) -> bool:
    """Check if unexplained_residual exceeds alert threshold.

    Default threshold 20 bps (= 0.20% = 0.002 decimal). Per QPB MVP 4.2 spec:
    "残差 > 阈值自动 flag" (iter 64+ wire AlertRouter SDK dispatch).

    Args:
        attribution: DailyAttribution payload.
        threshold_bps: alert threshold in basis points (default 20).

    Returns:
        True if abs(unexplained_residual) > threshold_bps / 10000.
    """
    return abs(attribution.unexplained_residual) > (threshold_bps / 10000.0)


def compute_by_factor(
    portfolio_weights: dict[str, float],
    factor_exposures: dict[str, dict[str, float]],
    factor_returns: dict[str, float],
) -> dict[str, float]:
    """Per-factor P&L contribution via Brinson-style cross-sectional attribution (iter 60 entry).

    daily attribution (single trade_date snapshot):
        portfolio_exposure_f = Σ_i w_i × z_f(i)
        by_factor[f] = portfolio_exposure_f × factor_return_f

    For multi-period or parameter-uncertainty attribution (iter 60+ future iter), WLS
    regression on historical returns time-series would replace this cross-sectional
    formula. For now, daily snapshot is the QPB MVP 4.2 §2 spec target.

    沿用 fast_neutralize_batch + factor_engine convention (factor_values store
    neutralized z-scores). 铁律 31 Engine 纯计算 — 0 DB / 0 HTTP / 0 Redis.

    Args:
        portfolio_weights: {stock_code: weight} dict. Weights typically sum to 1.0
            but function does NOT enforce; caller handles normalization.
        factor_exposures: {factor_name: {stock_code: z_score}} nested dict. Stocks
            missing from a factor's exposure dict are skipped for that factor.
        factor_returns: {factor_name: cross_sectional_return} dict (decimal,
            0.0012 = 0.12% = 12 bps).

    Returns:
        {factor_name: contribution} dict. Empty when any input is empty.
        Sum approximates total factor-explained portfolio return; residual
        (vs actual portfolio return) attributed to other components (sector /
        cost / regime) + unexplained_residual.

    Examples:
        >>> weights = {"000001.SZ": 0.5, "600000.SH": 0.5}
        >>> exposures = {
        ...     "turnover_mean_20": {"000001.SZ": 1.0, "600000.SH": -1.0},
        ...     "bp_ratio": {"000001.SZ": 0.5, "600000.SH": 0.5},
        ... }
        >>> returns = {"turnover_mean_20": 0.001, "bp_ratio": 0.002}
        >>> compute_by_factor(weights, exposures, returns)
        {'turnover_mean_20': 0.0, 'bp_ratio': 0.001}
    """
    by_factor: dict[str, float] = {}
    if not portfolio_weights or not factor_exposures or not factor_returns:
        return by_factor

    for factor_name, factor_ret in factor_returns.items():
        exposure_map = factor_exposures.get(factor_name)
        if not exposure_map:
            continue  # silent_ok: factor with no exposure data → 0 contribution (skip)

        # portfolio_exposure_f = Σ_i w_i × z_f(i), 仅 portfolio + exposure 都有的 stock
        portfolio_exposure = sum(
            weight * exposure_map[stock_code]
            for stock_code, weight in portfolio_weights.items()
            if stock_code in exposure_map
        )

        by_factor[factor_name] = portfolio_exposure * factor_ret

    return by_factor


def compute_by_sector(
    portfolio_weights: dict[str, float],
    stock_industry_map: dict[str, str],
    industry_returns: dict[str, float],
) -> dict[str, float]:
    """Per-sector P&L contribution via Brinson allocation effect (iter 61).

    Daily attribution (single trade_date snapshot):
        industry_weight = Σ_stock∈industry portfolio_weights[stock]
        by_sector[industry] = industry_weight × industry_return

    For multi-period Brinson-Fachler decomp (allocation + selection + interaction)
    use backend/qm_platform/eval/attribution_brinson.py (research module, not
    integrated to platform yet). Daily snapshot per QPB MVP 4.2 §2 spec is
    sufficient for `by_sector` field.

    沿用 SW1 (申万一级) industry classification convention (sustained
    backend/data/sw1_industry_loader 体例 if exists, else caller provides
    stock_industry_map). 铁律 31 Engine 纯计算 — 0 DB / HTTP / Redis.

    Args:
        portfolio_weights: {stock_code: weight} dict.
        stock_industry_map: {stock_code: sw1_industry_name} mapping (caller-supplied).
            Stocks missing from this dict are aggregated to "_unmapped" bucket.
        industry_returns: {industry_name: cross_sectional_return} dict (decimal).

    Returns:
        {industry_name: contribution} dict. Empty when any input is empty.

    Examples:
        >>> weights = {"000001.SZ": 0.4, "600000.SH": 0.3, "000333.SZ": 0.3}
        >>> map_ = {"000001.SZ": "银行", "600000.SH": "银行", "000333.SZ": "家电"}
        >>> rets = {"银行": 0.002, "家电": -0.001}
        >>> compute_by_sector(weights, map_, rets)
        {'银行': 0.0014, '家电': -0.00030000000000000003}
    """
    by_sector: dict[str, float] = {}
    if not portfolio_weights or not industry_returns:
        return by_sector

    # Aggregate portfolio weight per industry (silent _unmapped bucket for missing stocks)
    industry_weights: dict[str, float] = {}
    for stock_code, weight in portfolio_weights.items():
        industry = stock_industry_map.get(stock_code, "_unmapped")
        industry_weights[industry] = industry_weights.get(industry, 0.0) + weight

    # Per-industry contribution: industry_weight × industry_return
    for industry, ind_weight in industry_weights.items():
        ind_ret = industry_returns.get(industry)
        if ind_ret is None:
            # silent_ok: industry without return data (e.g. _unmapped or rare sector) → 0 contribution
            continue
        by_sector[industry] = ind_weight * ind_ret

    return by_sector


_COST_FIELDS = ("commission", "slippage", "impact", "overnight_gap")


def compute_by_regime(
    state_probs: dict[int, float] | list[float],
    state_mapping: dict[int, str],
    actual_perf_bps: float,
    baseline_perf_bps: dict[str, float] | None = None,
) -> RegimeInfo:
    """HMM 3-state regime attribution (iter 63, sub-iter 5).

    Per MVP_4_2_attribution.md §4 step 5 + backend/engines/regime_detector.py
    3-state HMM (bull / sideways / bear). Constructs RegimeInfo with detected state +
    expected performance (state-weighted baseline) + actual performance.

    Algorithm:
        detected = state_mapping[argmax(state_probs)]
        expected_perf_bps = Σ_state state_prob × baseline_perf_bps[state_name]
        return RegimeInfo(detected, expected_perf_bps, actual_perf_bps)

    Default baselines (per backend/engines/regime_detector.py SCALE_BEAR=0.3 + standard
    A股 regime returns from research-kb):
        bull: +12 bps/day (long-term bull expected)
        sideways: 0 bps/day (mean-reverting)
        bear: -8 bps/day (negative drift)

    沿用 regime_detector.py state mapping convention. 铁律 31 Engine 纯计算.

    Args:
        state_probs: HMM posterior probabilities. dict[int, float] keyed by state index,
            OR list[float] indexed by state position.
        state_mapping: dict[int → state_name_str] from regime_detector._state_mapping.
        actual_perf_bps: actual portfolio daily return in basis points.
        baseline_perf_bps: optional state→bps baseline. Defaults to {bull: 12, sideways: 0, bear: -8}.

    Returns:
        RegimeInfo with detected state + expected + actual perf bps.

    Raises:
        ValueError: state_probs empty / state_mapping missing detected state.

    Examples:
        >>> probs = {0: 0.7, 1: 0.2, 2: 0.1}
        >>> mapping = {0: "bull", 1: "sideways", 2: "bear"}
        >>> info = compute_by_regime(probs, mapping, actual_perf_bps=10.0)
        >>> info.detected
        'bull'
        >>> info.expected_perf_bps
        7.6
    """
    if not state_probs:
        raise ValueError("state_probs is empty; HMM regime detection requires ≥1 state")
    if not state_mapping:
        raise ValueError("state_mapping is empty; cannot resolve detected state name")

    if baseline_perf_bps is None:
        baseline_perf_bps = {"bull": 12.0, "sideways": 0.0, "bear": -8.0}

    # Normalize state_probs to dict[int, float]
    if isinstance(state_probs, list):
        probs_dict = dict(enumerate(state_probs))
    else:
        probs_dict = dict(state_probs)

    # Detected = argmax state index → name
    max_state_idx = max(probs_dict, key=lambda k: probs_dict[k])
    detected = state_mapping.get(max_state_idx)
    if detected is None:
        raise ValueError(
            f"state_mapping missing argmax index {max_state_idx}; mapping keys={list(state_mapping)}"
        )

    # Expected perf = state-weighted average of baselines
    expected_perf_bps = 0.0
    for state_idx, prob in probs_dict.items():
        state_name = state_mapping.get(state_idx)
        if state_name is None:
            continue  # silent_ok: missing mapping → skip (rare HMM state)
        baseline_bps = baseline_perf_bps.get(state_name, 0.0)
        expected_perf_bps += prob * baseline_bps

    return RegimeInfo(
        detected=detected,
        expected_perf_bps=expected_perf_bps,
        actual_perf_bps=actual_perf_bps,
    )


def compute_by_cost(
    trades: list[dict[str, float]],
    nav: float = 1.0,
) -> dict[str, float]:
    """Aggregate trade-level cost fields into per-category P&L impact (iter 62).

    Daily attribution single-day breakdown (per MVP_4_2_attribution.md §4 step 4):
        per_category_total_yuan = Σ_trade trade[category]
        by_cost[category] = -per_category_total_yuan / nav  (negative for costs)

    Cost categories (per QPB MVP 4.2 §2 spec):
        - commission: brokerage trade fee (国金 0.854/10000 + min 5 yuan + 印花税 + 过户费)
        - slippage: actual_price vs expected_price difference × shares
        - impact: market impact for large orders (3-factor slippage_model)
        - overnight_gap: open-to-close gap effect (if PT not at close)

    Trade-level fields convention (沿用 trade_log DDL line ~349 + slippage_model.py):
        trade = {"commission": yuan, "slippage": yuan, "impact": yuan, "overnight_gap": yuan}
        positive yuan → cost incurred → negative portfolio P&L impact

    沿用 backend/engines/slippage_model.py 3-factor decomposition convention.
    铁律 31 Engine 纯计算 — 0 DB / HTTP / Redis (trades dict 由 caller fetch).

    Args:
        trades: list of trade-level cost dicts (commission_yuan / slippage_yuan /
            impact_yuan / overnight_gap_yuan fields).
        nav: portfolio NAV in yuan for normalization (default 1.0 = no normalization,
            output in yuan). Set nav=actual_portfolio_yuan for decimal output.

    Returns:
        {category: P&L_impact} dict with 4 categories. All values negative if costs
        incurred. Output in yuan if nav=1.0; decimal fraction (e.g. -0.0008 = -8 bps)
        if nav=actual_portfolio_yuan.

    Examples:
        >>> trades = [
        ...     {"commission": 5.0, "slippage": 2.0, "impact": 1.0, "overnight_gap": 0.0},
        ...     {"commission": 5.0, "slippage": 3.0, "impact": 1.5, "overnight_gap": 0.5},
        ... ]
        >>> compute_by_cost(trades, nav=100000.0)
        {'commission': -0.0001, 'slippage': -5e-05, 'impact': -2.5e-05, 'overnight_gap': -5e-06}
    """
    by_cost: dict[str, float] = {field: 0.0 for field in _COST_FIELDS}
    if not trades:
        return by_cost

    totals: dict[str, float] = dict.fromkeys(_COST_FIELDS, 0.0)
    for trade in trades:
        for field_name in _COST_FIELDS:
            value = trade.get(field_name, 0.0)
            # silent_ok: missing field → 0 contribution (sustained Brinson convention)
            totals[field_name] += value

    # Normalize by NAV; costs are negative P&L impact
    if nav <= 0:
        # Defensive: nav must be positive; raise per 铁律 33 vs silent zero division
        raise ValueError(f"nav must be positive for normalization; got {nav}")

    return {field_name: -total / nav for field_name, total in totals.items()}


__all__ = [
    "AttributionEngine",
    "DailyAttribution",
    "RegimeInfo",
    "compute_by_cost",
    "compute_by_factor",
    "compute_by_regime",
    "compute_by_sector",
    "residual_exceeds_threshold",
]
