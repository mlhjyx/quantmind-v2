"""MVP 2.3 Sub3 C1 · Platform BacktestConfig 扩 12 字段 + 3 嵌套 dataclass 单测.

覆盖:
  - UniverseFilter / SlippageConfig / PMSConfig 新 frozen dataclass
  - BacktestConfig 新字段默认值对齐 engines.backtest.config.BacktestConfig
  - 17 现有调用方向后兼容 (Sub1 签名 0 break)
  - frozen + hashable (config_hash 锚点所需)
  - config_hash 稳定性 (铁律 15)

Sub3 motivation: 消除 Sub1 PR C3 `engine_config_builder` callable fallback 5-field 硬编码
技术债, Platform 字段齐了 C4 才能做全字段映射.

关联铁律: 15 (配置可复现) / 25 (代码变更前读当前代码) / 34 (config SSOT).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict
from datetime import date

import pytest

from backend.qm_platform.backtest.interface import (
    BacktestConfig,
    PMSConfig,
    SlippageConfig,
    UniverseFilter,
)

# ─── Fixtures ──────────────────────────────────────────────


def _make_minimal_config(**overrides) -> BacktestConfig:
    """Sub1 风格的最小 config — 只传 12 必填字段, 新字段全走 default."""
    base = {
        "start": date(2021, 1, 1),
        "end": date(2025, 12, 31),
        "universe": "csi300",
        "factor_pool": ("bp_ratio", "dv_ttm"),
        "rebalance_freq": "monthly",
        "top_n": 20,
        "industry_cap": 1.0,
        "size_neutral_beta": 0.50,
        "cost_model": "full",
        "capital": "1000000.0",
        "benchmark": "csi300",
        "extra": {},
    }
    base.update(overrides)
    return BacktestConfig(**base)


# ─── UniverseFilter ─────────────────────────────────────────


class TestUniverseFilter:
    def test_defaults_exclude_all_and_60_days(self) -> None:
        """默认值: A 股生产 (exclude ST/BJ/suspended, 新股 60 天)."""
        uf = UniverseFilter()
        assert uf.exclude_st is True
        assert uf.exclude_bj is True
        assert uf.exclude_suspended is True
        assert uf.min_listing_days == 60

    def test_frozen_raises_on_mutation(self) -> None:
        """frozen=True: 修改字段 raise FrozenInstanceError."""
        uf = UniverseFilter()
        with pytest.raises(FrozenInstanceError):
            uf.exclude_st = False  # type: ignore[misc]

    def test_hashable_for_config_hash(self) -> None:
        """hashable: 可进 set / dict key (BacktestConfig.config_hash 依赖)."""
        uf1 = UniverseFilter()
        uf2 = UniverseFilter()
        assert hash(uf1) == hash(uf2)
        assert len({uf1, uf2}) == 1


# ─── SlippageConfig (镜像 engines) ──────────────────────────


class TestSlippageConfig:
    def test_defaults_match_engines_r4_research(self) -> None:
        """字段默认值对齐 `engines.slippage_model.SlippageConfig` (R4 研究结论)."""
        sc = SlippageConfig()
        # Y tiered (大盘/中盘/小盘 冲击乘数)
        assert sc.Y_large == 0.8
        assert sc.Y_mid == 1.0
        assert sc.Y_small == 1.5
        # sell 方向惩罚
        assert sc.sell_penalty == 1.2
        # base bps tiered
        assert sc.base_bps == 5.0  # 旧版 fixed, tiered 模式下被覆盖
        assert sc.base_bps_large == 3.0
        assert sc.base_bps_mid == 5.0
        assert sc.base_bps_small == 8.0
        # 隔夜跳空
        assert sc.gap_penalty_factor == 0.5

    def test_mirror_engine_field_parity(self) -> None:
        """Platform SlippageConfig 与 engines SlippageConfig 字段 1:1 对齐 (防字段漂移)."""
        from engines.slippage_model import SlippageConfig as EngineSC

        platform_fields = set(asdict(SlippageConfig()).keys())
        engine_fields = set(asdict(EngineSC()).keys())
        assert platform_fields == engine_fields, (
            f"Platform vs engines SlippageConfig 字段不对齐: "
            f"only_platform={platform_fields - engine_fields}, "
            f"only_engine={engine_fields - platform_fields}"
        )

    def test_frozen_raises_on_mutation(self) -> None:
        sc = SlippageConfig()
        with pytest.raises(FrozenInstanceError):
            sc.Y_large = 99.0  # type: ignore[misc]

    def test_hashable(self) -> None:
        sc1 = SlippageConfig()
        sc2 = SlippageConfig()
        assert hash(sc1) == hash(sc2)


# ─── PMSConfig (镜像 engines, tiers tuple-of-tuple) ─────────


class TestPMSConfig:
    def test_defaults_disabled_with_3_tiers(self) -> None:
        """默认: enabled=False, 3 层阶梯 (30%/15%, 20%/12%, 10%/10%), next_open."""
        pms = PMSConfig()
        assert pms.enabled is False
        assert pms.tiers == (
            (0.30, 0.15),
            (0.20, 0.12),
            (0.10, 0.10),
        )
        assert pms.exec_mode == "next_open"

    def test_tiers_is_tuple_of_tuple_for_hashable(self) -> None:
        """tiers 必须是 `tuple[tuple[...]]` 非 list (engines PMSConfig 是 list, 破 frozen/hash)."""
        pms = PMSConfig()
        assert isinstance(pms.tiers, tuple)
        for tier in pms.tiers:
            assert isinstance(tier, tuple)
            assert len(tier) == 2

    def test_defaults_match_engines_config(self) -> None:
        """字段默认值对齐 engines.backtest.config.PMSConfig (enabled + exec_mode)."""
        from engines.backtest.config import PMSConfig as EnginePMS

        engine_pms = EnginePMS()
        platform_pms = PMSConfig()
        assert platform_pms.enabled == engine_pms.enabled
        assert platform_pms.exec_mode == engine_pms.exec_mode
        # tiers 对齐 (engines 是 list, Platform 是 tuple-of-tuple)
        assert list(platform_pms.tiers) == [tuple(t) for t in engine_pms.tiers]

    def test_frozen_raises_on_mutation(self) -> None:
        pms = PMSConfig()
        with pytest.raises(FrozenInstanceError):
            pms.enabled = True  # type: ignore[misc]

    def test_hashable(self) -> None:
        pms1 = PMSConfig()
        pms2 = PMSConfig()
        assert hash(pms1) == hash(pms2)


# ─── BacktestConfig 扩字段 + 向后兼容 ───────────────────────


class TestBacktestConfigExpanded:
    def test_sub1_signature_still_works(self) -> None:
        """Sub1 12-field 签名仍 construct (17 调用方 0 break)."""
        cfg = _make_minimal_config()
        # Sub1 原字段访问 OK
        assert cfg.start == date(2021, 1, 1)
        assert cfg.universe == "csi300"
        assert cfg.factor_pool == ("bp_ratio", "dv_ttm")
        assert cfg.top_n == 20
        assert cfg.size_neutral_beta == 0.50

    def test_sub3_new_fields_defaults(self) -> None:
        """Sub3 C1 新字段默认值对齐 engines.backtest.config.BacktestConfig."""
        cfg = _make_minimal_config()
        # Scalar (对齐 engines BacktestConfig 默认)
        assert cfg.turnover_cap == 0.50
        assert cfg.commission_rate == 0.0000854  # 国金万 0.854
        assert cfg.stamp_tax_rate == 0.0005  # 千 0.5
        assert cfg.historical_stamp_tax is True
        assert cfg.transfer_fee_rate == 0.00001
        assert cfg.slippage_bps == 10.0
        assert cfg.slippage_mode == "volume_impact"
        assert cfg.volume_cap_pct == 0.10
        assert cfg.lot_size == 100
        # Nested default_factory (独立实例, Sub3 C1)
        assert isinstance(cfg.universe_filter, UniverseFilter)
        assert isinstance(cfg.slippage_config, SlippageConfig)
        assert isinstance(cfg.pms_config, PMSConfig)

    def test_scalar_defaults_match_engines_backtest_config(self) -> None:
        """BacktestConfig 新 scalar 字段与 engines.backtest.config.BacktestConfig 对齐."""
        from engines.backtest.config import BacktestConfig as EngineBC

        platform_cfg = _make_minimal_config()
        engine_cfg = EngineBC()

        assert platform_cfg.turnover_cap == engine_cfg.turnover_cap
        assert platform_cfg.commission_rate == engine_cfg.commission_rate
        assert platform_cfg.stamp_tax_rate == engine_cfg.stamp_tax_rate
        assert platform_cfg.historical_stamp_tax == engine_cfg.historical_stamp_tax
        assert platform_cfg.transfer_fee_rate == engine_cfg.transfer_fee_rate
        assert platform_cfg.slippage_bps == engine_cfg.slippage_bps
        assert platform_cfg.slippage_mode == engine_cfg.slippage_mode
        assert platform_cfg.volume_cap_pct == engine_cfg.volume_cap_pct
        assert platform_cfg.lot_size == engine_cfg.lot_size

    def test_nested_override_allowed(self) -> None:
        """嵌套字段可显式 override (pt_live.yaml 场景)."""
        cfg = _make_minimal_config(
            universe_filter=UniverseFilter(min_listing_days=180),
            slippage_config=SlippageConfig(Y_large=2.0),
            pms_config=PMSConfig(enabled=True, tiers=((0.25, 0.10),)),
        )
        assert cfg.universe_filter.min_listing_days == 180
        assert cfg.slippage_config.Y_large == 2.0
        assert cfg.pms_config.enabled is True
        assert cfg.pms_config.tiers == ((0.25, 0.10),)

    def test_frozen_raises_on_scalar_mutation(self) -> None:
        cfg = _make_minimal_config()
        with pytest.raises(FrozenInstanceError):
            cfg.turnover_cap = 0.99  # type: ignore[misc]

    def test_default_factory_creates_independent_instances(self) -> None:
        """两个 BacktestConfig 实例的 universe_filter 是独立 instance (不共享引用)."""
        cfg1 = _make_minimal_config()
        cfg2 = _make_minimal_config()
        # 值相等
        assert cfg1.universe_filter == cfg2.universe_filter
        # frozen + default_factory 虽然每次新建, 值相等 hash 相等
        assert hash(cfg1.universe_filter) == hash(cfg2.universe_filter)


# ─── config_hash stability (铁律 15) ────────────────────────


class TestConfigHashStability:
    """BacktestConfig 扩字段后 config_hash 计算仍稳定 (Platform Runner._compute_config_hash)."""

    def test_same_config_same_hash(self) -> None:
        """相同 config 两次构造 → 相同 hash (铁律 15 复现核心)."""
        from backend.qm_platform.backtest.runner import PlatformBacktestRunner

        cfg1 = _make_minimal_config()
        cfg2 = _make_minimal_config()
        h1 = PlatformBacktestRunner._compute_config_hash(cfg1)
        h2 = PlatformBacktestRunner._compute_config_hash(cfg2)
        assert h1 == h2

    def test_nested_override_changes_hash(self) -> None:
        """嵌套字段改变 → config_hash 改变 (新字段纳入 hash, 保灵敏性)."""
        from backend.qm_platform.backtest.runner import PlatformBacktestRunner

        cfg_default = _make_minimal_config()
        cfg_custom_sn = _make_minimal_config(
            slippage_config=SlippageConfig(Y_large=99.0),
        )
        h_default = PlatformBacktestRunner._compute_config_hash(cfg_default)
        h_custom = PlatformBacktestRunner._compute_config_hash(cfg_custom_sn)
        assert h_default != h_custom

    def test_scalar_new_field_changes_hash(self) -> None:
        """新 scalar 字段改变 → config_hash 改变."""
        from backend.qm_platform.backtest.runner import PlatformBacktestRunner

        cfg_default = _make_minimal_config()
        cfg_custom = _make_minimal_config(turnover_cap=0.75)
        h_default = PlatformBacktestRunner._compute_config_hash(cfg_default)
        h_custom = PlatformBacktestRunner._compute_config_hash(cfg_custom)
        assert h_default != h_custom

    def test_asdict_serializable(self) -> None:
        """asdict 可序列化完整 config (sha256 JSON 依赖)."""
        cfg = _make_minimal_config()
        d = asdict(cfg)
        assert "turnover_cap" in d
        assert "slippage_config" in d
        assert isinstance(d["slippage_config"], dict)
        assert d["slippage_config"]["Y_large"] == 0.8
        assert "pms_config" in d
        assert d["pms_config"]["enabled"] is False
