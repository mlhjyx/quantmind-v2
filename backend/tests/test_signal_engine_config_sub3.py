"""MVP 2.3 Sub3 C2 · SignalConfig sentinel 回退 + YAML 权威单测.

覆盖:
  - SignalConfig.factor_names sentinel None → __post_init__ 回退 _PT_FACTOR_NAMES_DEFAULT
  - SignalConfig(factor_names=[...]) 显式传入仍用传入值 (50+ 老调用方 0 break)
  - _PT_FACTOR_NAMES_DEFAULT 值 = CORE3+dv_ttm (auditor.py 声明的 YAML 权威)
  - _build_paper_trading_config 从 pt_live.yaml 读 factor_names/rebalance_freq/turnover_cap
  - YAML 加载失败 fail-safe fallback hardcoded + logger.warning (铁律 33 非静默)
  - .env 权威字段 (top_n / industry_cap / size_neutral_beta) 仍从 settings 读

Sub3 C2 消除 signal_engine.py 3 处 hardcoded SSOT drift 源 (factor_names / rebalance_freq /
turnover_cap), auditor.check_config_alignment 负责硬拦截 yaml ↔ python drift (铁律 34).

关联铁律: 25 (代码变更前读当前代码) / 33 (禁 silent failure) / 34 (config SSOT).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

# ─── _PT_FACTOR_NAMES_DEFAULT + SignalConfig sentinel ────────


class TestSignalConfigSentinel:
    def test_default_factor_names_is_core3_plus_dv_ttm(self) -> None:
        """_PT_FACTOR_NAMES_DEFAULT = CORE3+dv_ttm (WF OOS Sharpe 0.8659, 2026-04-12)."""
        from engines.signal_engine import _PT_FACTOR_NAMES_DEFAULT

        assert _PT_FACTOR_NAMES_DEFAULT == (
            "turnover_mean_20",
            "volatility_20",
            "bp_ratio",
            "dv_ttm",
        )
        # tuple 防 mutation (与 PAPER_TRADING_CONFIG.factor_names list 隔离)
        assert isinstance(_PT_FACTOR_NAMES_DEFAULT, tuple)

    def test_signal_config_no_args_fallback_to_default(self) -> None:
        """SignalConfig() 无参 → __post_init__ 回退 CORE3+dv_ttm (50+ 老调用方 0 break)."""
        from engines.signal_engine import SignalConfig

        cfg = SignalConfig()
        assert cfg.factor_names == [
            "turnover_mean_20",
            "volatility_20",
            "bp_ratio",
            "dv_ttm",
        ]
        # 是 list 非 tuple (调用方可能 append, 保兼容)
        assert isinstance(cfg.factor_names, list)

    def test_signal_config_explicit_factor_names_wins(self) -> None:
        """显式传 factor_names → 用传入值 (不触发 sentinel 回退)."""
        from engines.signal_engine import SignalConfig

        cfg = SignalConfig(factor_names=["my_factor_a", "my_factor_b"])
        assert cfg.factor_names == ["my_factor_a", "my_factor_b"]

    def test_signal_config_empty_list_not_treated_as_none(self) -> None:
        """显式传 [] → 保留空 list (不触发 sentinel), 让调用方自己处理."""
        from engines.signal_engine import SignalConfig

        cfg = SignalConfig(factor_names=[])
        assert cfg.factor_names == []

    def test_fallback_independence_from_module_constant(self) -> None:
        """回退 list 是 _PT_FACTOR_NAMES_DEFAULT 的独立副本 (mutation 不污染全局)."""
        from engines.signal_engine import _PT_FACTOR_NAMES_DEFAULT, SignalConfig

        cfg1 = SignalConfig()
        cfg1.factor_names.append("new_factor")
        # 全局常量未被污染
        assert "new_factor" not in _PT_FACTOR_NAMES_DEFAULT
        # 新实例仍回退原始 CORE3+dv_ttm 4 个
        cfg2 = SignalConfig()
        assert len(cfg2.factor_names) == 4


# ─── _build_paper_trading_config YAML 权威 ──────────────────


class TestBuildPaperTradingConfigYamlAuthority:
    """Sub3 C2: _build_paper_trading_config 改从 pt_live.yaml 读 factor_names /
    rebalance_freq / turnover_cap. top_n / industry_cap / size_neutral_beta 仍从 .env.
    """

    def test_pt_config_matches_yaml_production(self) -> None:
        """module-level PAPER_TRADING_CONFIG 值对齐 configs/pt_live.yaml."""
        from engines.signal_engine import PAPER_TRADING_CONFIG

        # YAML 权威字段 (pt_live.yaml L6-12: CORE3+dv_ttm)
        assert set(PAPER_TRADING_CONFIG.factor_names) == {
            "turnover_mean_20",
            "volatility_20",
            "bp_ratio",
            "dv_ttm",
        }
        # YAML 权威 (pt_live.yaml L15/17)
        assert PAPER_TRADING_CONFIG.rebalance_freq == "monthly"
        assert PAPER_TRADING_CONFIG.turnover_cap == 0.50
        # .env 权威 (config.py Settings 默认, 若 .env 缺则 fallback)
        assert PAPER_TRADING_CONFIG.top_n == 20
        assert PAPER_TRADING_CONFIG.industry_cap == 1.0
        assert PAPER_TRADING_CONFIG.size_neutral_beta == 0.50

    def test_yaml_load_failure_falls_back_hardcoded(self, capfd) -> None:
        """YAML 加载失败 → fallback hardcoded CORE3+dv_ttm + warning to stderr (铁律 33 非静默).

        Note: signal_engine 用 structlog (非 stdlib logging), caplog 不捕获;
        structlog 默认输出 stderr, 用 capfd 抓.
        """
        from engines import signal_engine

        def _raise_oops() -> dict:
            raise FileNotFoundError("mock yaml missing")

        with patch.object(signal_engine, "_load_pt_yaml_strategy", side_effect=_raise_oops):
            cfg = signal_engine._build_paper_trading_config()

        # Fallback 值对齐 hardcoded CORE3+dv_ttm
        assert cfg.factor_names == list(signal_engine._PT_FACTOR_NAMES_DEFAULT)
        assert cfg.rebalance_freq == "monthly"
        assert cfg.turnover_cap == 0.50
        # warning 输出 stderr (铁律 33 非静默)
        captured = capfd.readouterr()
        assert "YAML load failed" in captured.err or "YAML load failed" in captured.out

    def test_yaml_empty_factors_falls_back_hardcoded(self, capfd) -> None:
        """YAML strategy.factors 为空 list → raise ValueError → fallback hardcoded."""
        from engines import signal_engine

        def _empty_factors_strategy() -> dict:
            return {"factors": [], "rebalance_freq": "weekly", "turnover_cap": 0.3}

        with patch.object(
            signal_engine, "_load_pt_yaml_strategy", side_effect=_empty_factors_strategy
        ):
            cfg = signal_engine._build_paper_trading_config()

        assert cfg.factor_names == list(signal_engine._PT_FACTOR_NAMES_DEFAULT)
        # rebalance/turnover 也 fallback (整块 try/except 统一 fallback, 防部分 drift)
        assert cfg.rebalance_freq == "monthly"
        assert cfg.turnover_cap == 0.50

    def test_yaml_driven_values_consumed(self) -> None:
        """YAML factor/freq/turnover 改变 → 下次调用读新值 (非 module 永久 cache)."""
        from engines import signal_engine

        def _custom_strategy() -> dict:
            return {
                "factors": [{"name": "xyz_factor", "direction": 1}],
                "rebalance_freq": "weekly",
                "turnover_cap": 0.25,
            }

        with patch.object(signal_engine, "_load_pt_yaml_strategy", side_effect=_custom_strategy):
            cfg = signal_engine._build_paper_trading_config()

        assert cfg.factor_names == ["xyz_factor"]
        assert cfg.rebalance_freq == "weekly"
        assert cfg.turnover_cap == 0.25

    def test_env_fields_still_from_settings(self) -> None:
        """top_n / industry_cap / size_neutral_beta 仍从 settings (.env 权威) 读."""
        from engines import signal_engine

        def _yaml_strategy() -> dict:
            return {
                "factors": [{"name": "yaml_factor", "direction": 1}],
                "rebalance_freq": "monthly",
                "turnover_cap": 0.50,
            }

        fake_settings = SimpleNamespace(
            PT_TOP_N=42,
            PT_INDUSTRY_CAP=0.33,
            PT_SIZE_NEUTRAL_BETA=0.77,
        )

        with (
            patch.object(signal_engine, "_load_pt_yaml_strategy", side_effect=_yaml_strategy),
            patch("app.config.settings", fake_settings),
        ):
            cfg = signal_engine._build_paper_trading_config()

        # .env 权威字段使用 mocked settings
        assert cfg.top_n == 42
        assert cfg.industry_cap == 0.33
        assert cfg.size_neutral_beta == 0.77
        # YAML 权威字段从 mock YAML
        assert cfg.factor_names == ["yaml_factor"]

    def test_malformed_factor_entry_skipped(self) -> None:
        """YAML factors 含非 dict/no-name 项 → 安全 skip (不 raise)."""
        from engines import signal_engine

        def _malformed_strategy() -> dict:
            return {
                "factors": [
                    {"name": "good_factor", "direction": 1},
                    {"direction": 1},  # no name → skip
                    "not_a_dict",  # not dict → skip
                    {"name": "another_good", "direction": -1},
                ],
                "rebalance_freq": "monthly",
                "turnover_cap": 0.50,
            }

        with patch.object(signal_engine, "_load_pt_yaml_strategy", side_effect=_malformed_strategy):
            cfg = signal_engine._build_paper_trading_config()

        assert cfg.factor_names == ["good_factor", "another_good"]


# ─── 50+ 老调用方代表性抽样验证 (0 break) ────────────────────


class TestLegacyCallersCompatibility:
    """Sub3 C2 Plan agent 建议: sentinel 方案保 50+ 老调用方 0 break.

    代表性抽样: backend/engines/vectorized_signal.py / backend/tests/test_regime_detector.py
    / scripts/archive/* — 均裸调 SignalConfig() 无参.
    """

    def test_vectorized_signal_bare_call_compat(self) -> None:
        """backend/engines/vectorized_signal.py::SignalConfig() 裸调用 (L92)."""
        from engines.signal_engine import SignalConfig

        # 模拟 vectorized_signal.py:92 模式
        cfg = SignalConfig()
        # 老调用方预期: top_n=20 / weight_method='equal' / 4 factors CORE3+dv_ttm
        assert cfg.top_n == 20
        assert cfg.weight_method == "equal"
        assert len(cfg.factor_names) == 4

    def test_test_regime_detector_bare_call_compat(self) -> None:
        """backend/tests/test_regime_detector.py:419 SignalConfig() 裸调用."""
        from engines.signal_engine import SignalConfig

        cfg = SignalConfig()
        # 老 test 可能访问 size_neutral_beta / rebalance_freq
        assert cfg.size_neutral_beta == 0.50
        assert cfg.rebalance_freq == "monthly"

    def test_dataclass_still_mutable(self) -> None:
        """SignalConfig 保 @dataclass 非 frozen, 调用方可修改字段 (50+ 老测试依赖)."""
        from engines.signal_engine import SignalConfig

        cfg = SignalConfig()
        # 能 mutate (非 frozen)
        cfg.top_n = 50
        cfg.rebalance_freq = "weekly"
        assert cfg.top_n == 50
        assert cfg.rebalance_freq == "weekly"


# ─── auditor 集成验证 (C3 无需改动的证明) ───────────────────


class TestAuditorIntegrationStillPasses:
    """Sub3 C2 后 auditor.check_alignment 仍能 PASS (yaml ↔ python 对齐)."""

    def test_check_alignment_passes_with_current_config(self) -> None:
        """当前 pt_live.yaml ↔ PAPER_TRADING_CONFIG 对齐, auditor 不 raise."""
        from engines.signal_engine import PAPER_TRADING_CONFIG

        from backend.platform.config.auditor import PlatformConfigAuditor

        # 直接走真实 yaml 文件 + 真实 python config (PR 内部只关心不 raise)
        auditor = PlatformConfigAuditor()
        report = auditor.check_alignment(
            env={},  # 不传 env (auditor 只比 yaml ↔ python)
            python_config=PAPER_TRADING_CONFIG,
            strict=False,
        )
        assert report.passed, f"auditor drift: {report.mismatches}"
