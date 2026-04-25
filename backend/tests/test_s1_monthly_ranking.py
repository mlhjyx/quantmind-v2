"""MVP 3.2 批 2 — S1MonthlyRanking unit tests.

覆盖 generate_signals 的正常路径 + 边界 + SN + prev_holdings + metadata 守门 +
validate_signals + ClassVar + __repr__. 纯 metadata-injection 测试 (不触 DB,
铁律 31 S1 纯计算原则).

对齐 test_s2_pead_event.py (PR #70) 测试风格.
"""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID  # P3 python-reviewer (PR #71): module-top 取代 test body import

import pandas as pd
import pytest

# 对齐 regression_test.py — sys.path 注入 backend 以兼容 `engines.*` import
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.append(str(_BACKEND))

from engines.signal_engine import SignalConfig  # noqa: E402

from backend.engines.strategies.s1_monthly_ranking import (  # noqa: E402
    _S1_FACTOR_POOL,
    _S1_STRATEGY_UUID,
    S1MonthlyRanking,
    get_s1_factor_pool,
)
from backend.qm_platform.strategy.interface import (  # noqa: E402
    RebalanceFreq,
    StrategyContext,
    StrategyStatus,
)

# ─── Fixtures: synthetic factor_df for CORE3+dv_ttm ───────────────────


def _mk_factor_df(
    codes: list[str],
    factor_names: tuple[str, ...] = _S1_FACTOR_POOL,
    base_values: dict[str, list[float]] | None = None,
) -> pd.DataFrame:
    """Build synthetic factor_df with neutral_value per (code, factor_name).

    默认每 code 对每 factor 有 1 行, neutral_value 基于 code 序号 + factor offset
    以产生稳定 ordering (deterministic for tests).
    """
    rows = []
    for i, code in enumerate(codes):
        for j, fname in enumerate(factor_names):
            if base_values and code in base_values:
                val = base_values[code][j] if j < len(base_values[code]) else 0.0
            else:
                # 基于序号的递减值, code0 最好 (direction 无关 — 测试测排名行为)
                val = 10.0 - i * 0.5 + j * 0.01
            rows.append(
                {"code": code, "factor_name": fname, "neutral_value": float(val)}
            )
    return pd.DataFrame(rows)


def _mk_industry_map(codes: list[str]) -> dict[str, str]:
    """N codes 分 2 行业循环 (用于行业约束测试)."""
    inds = ["银行", "医药"]
    return {code: inds[i % len(inds)] for i, code in enumerate(codes)}


def _mk_ctx(
    trade_date: date = date(2026, 4, 28),
    universe: list[str] | None = None,
    factor_df: pd.DataFrame | None = None,
    industry_map: dict[str, str] | None = None,
    ln_mcap: pd.Series | None = None,
    prev_holdings: dict[str, float] | None = None,
    exclude: set[str] | None = None,
    vol_regime_scale: float | None = None,
    volatility_map: dict[str, float] | None = None,
    omit_keys: set[str] | None = None,
) -> StrategyContext:
    """Build StrategyContext with optional metadata keys omitted."""
    if universe is None:
        universe = [f"{i:06d}.SH" for i in range(600000, 600040)]
    if factor_df is None:
        factor_df = _mk_factor_df(universe)
    if industry_map is None:
        industry_map = _mk_industry_map(universe)

    metadata: dict[str, Any] = {"factor_df": factor_df, "industry_map": industry_map}
    if ln_mcap is not None:
        metadata["ln_mcap"] = ln_mcap
    if prev_holdings is not None:
        metadata["prev_holdings"] = prev_holdings
    if exclude is not None:
        metadata["exclude"] = exclude
    if vol_regime_scale is not None:
        metadata["vol_regime_scale"] = vol_regime_scale
    if volatility_map is not None:
        metadata["volatility_map"] = volatility_map

    if omit_keys:
        for k in omit_keys:
            metadata.pop(k, None)

    return StrategyContext(
        trade_date=trade_date,
        capital=Decimal("1000000"),
        universe=universe,
        regime="neutral",
        metadata=metadata,
    )


def _mk_config(
    top_n: int = 20,
    industry_cap: float = 1.0,
    size_neutral_beta: float = 0.50,
    turnover_cap: float = 0.50,
    cash_buffer: float = 0.03,
) -> SignalConfig:
    """Build SignalConfig matching PT production default (CORE3+dv_ttm)."""
    return SignalConfig(
        factor_names=list(_S1_FACTOR_POOL),
        top_n=top_n,
        weight_method="equal",
        rebalance_freq="monthly",
        industry_cap=industry_cap,
        turnover_cap=turnover_cap,
        cash_buffer=cash_buffer,
        size_neutral_beta=size_neutral_beta,
    )


# ─── Class attrs tests (mirror S2 pattern) ────────────────────────────


def test_s1_class_attrs_required_by_abc():
    """ClassVar 契约: strategy_id / name / factor_pool / rebalance_freq / status."""
    assert S1MonthlyRanking.name == "s1_monthly_ranking"
    assert S1MonthlyRanking.rebalance_freq == RebalanceFreq.MONTHLY
    assert S1MonthlyRanking.status == StrategyStatus.LIVE
    # P1 python-reviewer (PR #71) 采纳: factor_pool 改 tuple 防 class-level mutation
    assert S1MonthlyRanking.factor_pool == _S1_FACTOR_POOL
    assert isinstance(S1MonthlyRanking.factor_pool, tuple)
    # UUID 格式 + 必须复用当前 live PT UUID (铁律 34 SSOT)
    UUID(S1MonthlyRanking.strategy_id)  # raises if invalid
    assert S1MonthlyRanking.strategy_id == "28fc37e5-2d32-4ada-92e0-41c11a5103d0"
    assert str(_S1_STRATEGY_UUID) == S1MonthlyRanking.strategy_id


def test_s1_factor_pool_is_core3_plus_dv_ttm():
    """factor_pool 必须是 CORE3+dv_ttm 4 因子 (SSOT 对齐 pt_live.yaml)."""
    assert set(_S1_FACTOR_POOL) == {
        "turnover_mean_20",
        "volatility_20",
        "bp_ratio",
        "dv_ttm",
    }
    assert get_s1_factor_pool() == _S1_FACTOR_POOL


def test_s1_description_mentions_key_params():
    """Description 含关键参数 (Top-20 + SN + 月频) — auditor/docs 用."""
    desc = S1MonthlyRanking.description
    assert "CORE3+dv_ttm" in desc or "Monthly" in desc
    assert "20" in desc or "SN" in desc


# ─── generate_signals: metadata pre-condition guard ───────────────────


def test_missing_factor_df_key_raises_keyerror():
    s1 = S1MonthlyRanking(config=_mk_config())
    ctx = _mk_ctx(omit_keys={"factor_df"})
    with pytest.raises(KeyError, match="factor_df"):
        s1.generate_signals(ctx)


def test_missing_industry_map_key_raises_keyerror():
    s1 = S1MonthlyRanking(config=_mk_config())
    ctx = _mk_ctx(omit_keys={"industry_map"})
    with pytest.raises(KeyError, match="industry_map"):
        s1.generate_signals(ctx)


# ─── generate_signals: normal path ────────────────────────────────────


def test_empty_universe_returns_empty():
    """universe=[] → SignalComposer 无可用股 → 返 []."""
    s1 = S1MonthlyRanking(config=_mk_config(top_n=5, size_neutral_beta=0.0))
    ctx = _mk_ctx(universe=[], factor_df=pd.DataFrame(), industry_map={})
    signals = s1.generate_signals(ctx)
    assert signals == []


def test_normal_path_returns_top_n_signals():
    """40 codes + Top-20 + 等权 → 20 signals 返回."""
    s1 = S1MonthlyRanking(config=_mk_config(top_n=20, size_neutral_beta=0.0))
    ctx = _mk_ctx()  # default 40 codes
    signals = s1.generate_signals(ctx)
    assert len(signals) == 20
    # target_weight 和 ≈ (1 - cash_buffer) = 0.97
    total_weight = sum(s.target_weight for s in signals)
    assert 0.96 <= total_weight <= 0.98
    # strategy_id 一致
    for s in signals:
        assert s.strategy_id == S1MonthlyRanking.strategy_id
        assert s.trade_date == ctx.trade_date
        assert s.target_weight > 0
        assert "action" in s.metadata
        assert s.metadata["action"] == "target"


def test_signals_are_deterministic_across_runs():
    """同输入 → 同输出 (铁律 15 可复现)."""
    s1 = S1MonthlyRanking(config=_mk_config(top_n=10, size_neutral_beta=0.0))
    ctx = _mk_ctx()
    run1 = s1.generate_signals(ctx)
    run2 = s1.generate_signals(ctx)
    assert [s.code for s in run1] == [s.code for s in run2]
    for a, b in zip(run1, run2, strict=True):
        assert a.target_weight == b.target_weight
        assert a.score == b.score


def test_exclude_removes_codes():
    """exclude set 内 codes 不进 signals."""
    s1 = S1MonthlyRanking(config=_mk_config(top_n=10, size_neutral_beta=0.0))
    universe = [f"{i:06d}.SH" for i in range(600000, 600030)]
    excluded = {"600000.SH", "600001.SH", "600002.SH"}
    ctx = _mk_ctx(universe=universe, exclude=excluded)
    signals = s1.generate_signals(ctx)
    code_set = {s.code for s in signals}
    assert excluded.isdisjoint(code_set)


# ─── generate_signals: size-neutral ──────────────────────────────────


def test_sn_beta_zero_skips_size_neutral():
    """beta=0 → apply_size_neutral 不调用, ln_mcap 缺失也不 warning."""
    s1 = S1MonthlyRanking(config=_mk_config(top_n=5, size_neutral_beta=0.0))
    ctx = _mk_ctx()  # 无 ln_mcap
    signals = s1.generate_signals(ctx)
    assert len(signals) == 5


def test_sn_beta_positive_with_ln_mcap_applies_adjustment():
    """beta>0 + ln_mcap 提供 → scores 被 SN 调整 (ordering 与 beta=0 不同).

    P2 code-reviewer (PR #71) 采纳: 原仅验 signals count + weight sum, 未验 SN
    实际生效 (broken SN silently 返 raw scores 也会 pass). 改加 ordering 对比.
    """
    universe = [f"{i:06d}.SH" for i in range(600000, 600020)]
    # ln_mcap: code0 最小 (小盘), code19 最大 (大盘). beta>0 时 SN 惩罚小盘
    # → 原本 code 序号小 (scores 高 + ln_mcap 小) 的股会被降权, ordering 必变.
    ln_mcap = pd.Series(
        {code: 20.0 + i * 0.5 for i, code in enumerate(universe)},
        dtype=float,
        name="ln_mcap",
    )
    ctx_with_sn = _mk_ctx(universe=universe, ln_mcap=ln_mcap)
    s1_sn = S1MonthlyRanking(config=_mk_config(top_n=10, size_neutral_beta=0.50))
    signals_sn = s1_sn.generate_signals(ctx_with_sn)

    ctx_no_sn = _mk_ctx(universe=universe)  # 无 ln_mcap
    s1_no_sn = S1MonthlyRanking(config=_mk_config(top_n=10, size_neutral_beta=0.0))
    signals_no_sn = s1_no_sn.generate_signals(ctx_no_sn)

    # 10 signals each, weight sums normal
    assert len(signals_sn) == 10
    assert len(signals_no_sn) == 10
    assert sum(s.target_weight for s in signals_sn) > 0.9
    assert sum(s.target_weight for s in signals_no_sn) > 0.9
    # **ordering 必须不同** — 若 SN 失效会与 beta=0 完全一样, 此 assert 即 guard
    codes_sn = [s.code for s in signals_sn]
    codes_no_sn = [s.code for s in signals_no_sn]
    assert codes_sn != codes_no_sn, (
        "SN beta=0.50 与 beta=0 产 identical ordering — apply_size_neutral 可能未生效"
    )


def test_sn_beta_positive_with_all_nan_ln_mcap_warns(caplog):
    """P1 code-reviewer (PR #71) 采纳: ln_mcap 所有值 NaN → apply_size_neutral 静默返原
    scores (size_neutral.py L126-127 `df.empty` fallback). 此 test guard 确保 wrapper
    post-SN 检测后 logger.warning 暴露 (铁律 33 fail-loud 非静默).
    """
    import logging

    s1 = S1MonthlyRanking(config=_mk_config(top_n=5, size_neutral_beta=0.50))
    universe = [f"{i:06d}.SH" for i in range(600000, 600015)]
    # ln_mcap 有 entries 但 reindex 后全 NaN (code 不匹配 universe)
    disjoint_codes = [f"{i:06d}.SH" for i in range(700000, 700015)]
    ln_mcap = pd.Series(
        {code: 20.0 + i * 0.5 for i, code in enumerate(disjoint_codes)},
        dtype=float,
        name="ln_mcap",
    )
    ctx = _mk_ctx(universe=universe, ln_mcap=ln_mcap)
    with caplog.at_level(
        logging.WARNING, logger="backend.engines.strategies.s1_monthly_ranking"
    ):
        signals = s1.generate_signals(ctx)
    # 5 signals 仍返回 (fallback to raw scores 语义上 OK, 但 warn 暴露 drift)
    assert len(signals) == 5
    # Guard: logger.warning 必须暴露 SN 未生效
    assert any("SN 未生效" in r.message for r in caplog.records), (
        "post-SN 检测未 warn — apply_size_neutral 静默 fallback 被掩盖"
    )


def test_sn_beta_positive_without_ln_mcap_warns_and_falls_back(caplog):
    """beta>0 but ln_mcap 缺失 → logger.warning + fallback 原 scores (不 raise)."""
    import logging

    s1 = S1MonthlyRanking(config=_mk_config(top_n=5, size_neutral_beta=0.50))
    ctx = _mk_ctx()  # 无 ln_mcap
    with caplog.at_level(logging.WARNING, logger="backend.engines.strategies.s1_monthly_ranking"):
        signals = s1.generate_signals(ctx)
    # 5 signals 仍返回 (fallback 原 scores)
    assert len(signals) == 5
    # warning 记录
    assert any("ln_mcap missing" in r.message for r in caplog.records)


# ─── generate_signals: prev_holdings + turnover_cap ──────────────────


def test_prev_holdings_respected_under_turnover_cap():
    """prev_holdings 提供 + turnover_cap=0.50 → 换手受限 (并非全换)."""
    s1 = S1MonthlyRanking(
        config=_mk_config(top_n=10, turnover_cap=0.50, size_neutral_beta=0.0)
    )
    universe = [f"{i:06d}.SH" for i in range(600000, 600030)]
    # prev_holdings = universe[0:5] 低位 codes (现 scores 最差, 本应全换掉)
    prev = {universe[i]: 0.19 for i in range(5)}
    ctx = _mk_ctx(universe=universe, prev_holdings=prev)
    signals = s1.generate_signals(ctx)
    # 不验具体 code list — turnover_cap 内部 normalize, 只验 signals count + weight sum
    assert len(signals) > 0
    assert sum(s.target_weight for s in signals) > 0


# ─── validate_signals ───────────────────────────────────────────────


def test_validate_signals_passes_valid_buys():
    s1 = S1MonthlyRanking(config=_mk_config(top_n=5, size_neutral_beta=0.0))
    ctx = _mk_ctx()
    signals = s1.generate_signals(ctx)
    validated = s1.validate_signals(signals, ctx)
    assert len(validated) == len(signals)


def test_validate_signals_drops_non_positive_weight():
    s1 = S1MonthlyRanking()
    ctx = _mk_ctx()
    from backend.qm_platform._types import Signal

    bad_signal = Signal(
        strategy_id=s1.strategy_id,
        code=ctx.universe[0],
        target_weight=0.0,  # non-positive
        score=0.5,
        trade_date=ctx.trade_date,
        metadata={},
    )
    validated = s1.validate_signals([bad_signal], ctx)
    assert validated == []


def test_validate_signals_drops_code_not_in_universe():
    s1 = S1MonthlyRanking()
    ctx = _mk_ctx()
    from backend.qm_platform._types import Signal

    bad_signal = Signal(
        strategy_id=s1.strategy_id,
        code="999999.XX",  # 不在 universe
        target_weight=0.05,
        score=1.0,
        trade_date=ctx.trade_date,
        metadata={},
    )
    validated = s1.validate_signals([bad_signal], ctx)
    assert validated == []


# ─── Config introspection ──────────────────────────────────────────


def test_default_init_uses_paper_trading_config():
    """S1() 默认使用 PAPER_TRADING_CONFIG — 权威 yaml + .env."""
    from engines.signal_engine import PAPER_TRADING_CONFIG

    s1 = S1MonthlyRanking()
    cfg = s1.get_config()
    assert cfg is PAPER_TRADING_CONFIG


def test_explicit_config_overrides_default():
    custom = _mk_config(top_n=30, size_neutral_beta=0.0)
    s1 = S1MonthlyRanking(config=custom)
    assert s1.get_config() is custom
    assert s1.get_config().top_n == 30


def test_repr_contains_key_params():
    s1 = S1MonthlyRanking(config=_mk_config(top_n=20, size_neutral_beta=0.50))
    r = repr(s1)
    assert "S1MonthlyRanking" in r
    assert "top_n=20" in r
    assert "0.50" in r
    assert "monthly" in r.lower()


# ─── Regression guard: 确保 wrapper 不破坏核心逻辑 ──────────────────


@pytest.mark.parametrize("sn_beta", [0.0, 0.50])
def test_s1_output_matches_direct_composer_builder_call(sn_beta):
    """S1.generate_signals == direct SignalComposer[+SN]+PortfolioBuilder 等价 (铁律 16).

    硬守门: 若未来有人重构 s1_monthly_ranking.py 偏离 compose+SN+build 原路径,
    此 test 立即失败 (regression max_diff=0 锚点依赖此等价性).

    P1 code-reviewer (PR #71) 采纳: 新增 SN=0.50 parametrize variant 覆盖 live PT
    实际执行路径 (beta=0 只测两步 compose→build, 未覆盖 SN 第三步).
    """
    from engines.signal_engine import PortfolioBuilder, SignalComposer
    from engines.size_neutral import apply_size_neutral

    cfg = _mk_config(top_n=10, size_neutral_beta=sn_beta)
    s1 = S1MonthlyRanking(config=cfg)

    universe = [f"{i:06d}.SH" for i in range(600000, 600030)]
    factor_df = _mk_factor_df(universe)
    industry_map = _mk_industry_map(universe)
    ln_mcap = (
        pd.Series(
            {code: 20.0 + i * 0.5 for i, code in enumerate(universe)},
            dtype=float,
            name="ln_mcap",
        )
        if sn_beta > 0
        else None
    )

    ctx_kwargs: dict[str, Any] = {
        "universe": universe,
        "factor_df": factor_df,
        "industry_map": industry_map,
    }
    if ln_mcap is not None:
        ctx_kwargs["ln_mcap"] = ln_mcap
    ctx = _mk_ctx(**ctx_kwargs)
    s1_signals = s1.generate_signals(ctx)
    s1_codes = [s.code for s in s1_signals]
    s1_weights = {s.code: s.target_weight for s in s1_signals}

    # Direct call — 镜像 S1 orchestration (compose → SN → build) 三步
    composer = SignalComposer(cfg)
    builder = PortfolioBuilder(cfg)
    scores = composer.compose(factor_df, universe=set(universe))
    if sn_beta > 0 and ln_mcap is not None:
        scores = apply_size_neutral(scores, ln_mcap, sn_beta)
    ind_ser = pd.Series(industry_map, dtype=object)
    direct_target = builder.build(scores=scores, industry=ind_ser)

    assert s1_codes == list(direct_target.keys()), (
        f"SN beta={sn_beta}: S1 ordering 偏离 direct path"
    )
    for code, w in direct_target.items():
        assert s1_weights[code] == pytest.approx(float(w), abs=1e-12)
