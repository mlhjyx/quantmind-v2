"""HC-2b G6: config_guard.assert_live_trading_lock_integrity (V3 §14 mode 15).

HC-2a §14 enforcement matrix G6 finding: config_guard 校验 EXECUTION_MODE
(`assert_execution_mode_integrity`) 但 **0 校验 LIVE_TRADING_DISABLED** — 双锁第 2
锁缺 startup gate. 本 fix 补 startup 双锁完整性校验:
- EXECUTION_MODE=paper + LIVE_TRADING_DISABLED 非 true → 双锁不一致 RAISE ConfigDriftError
- EXECUTION_MODE=live → INFO log (不 raise — 保守方向不阻断启动)

sustained test_config_guard_execution_mode.py 体例 (parallel sibling).
"""

from __future__ import annotations

import pytest

from backend.engines.config_guard import (
    ConfigDriftError,
    assert_live_trading_lock_integrity,
)


class TestPaperModeDoubleLock:
    """paper 模式双锁一致性 — LIVE_TRADING_DISABLED 必 true (红线)."""

    def test_paper_with_lock_enabled_no_raise(self) -> None:
        """paper + LIVE_TRADING_DISABLED=True → 不 raise (红线正常态)."""
        assert_live_trading_lock_integrity(
            execution_mode="paper", live_trading_disabled=True
        )

    def test_paper_with_lock_disabled_raises(self) -> None:
        """paper + LIVE_TRADING_DISABLED=False → ConfigDriftError (双锁不一致)."""
        with pytest.raises(ConfigDriftError):
            assert_live_trading_lock_integrity(
                execution_mode="paper", live_trading_disabled=False
            )

    def test_raise_payload_names_param(self) -> None:
        """ConfigDriftError payload 标 LIVE_TRADING_DISABLED param."""
        with pytest.raises(ConfigDriftError) as exc_info:
            assert_live_trading_lock_integrity(
                execution_mode="paper", live_trading_disabled=False
            )
        assert "LIVE_TRADING_DISABLED" in str(exc_info.value)


class TestLiveMode:
    """live 模式 — INFO log, 不 raise (保守方向不阻断启动)."""

    def test_live_with_lock_enabled_no_raise(self) -> None:
        """live + LIVE_TRADING_DISABLED=True → fail-secure 安全态, 不 raise."""
        assert_live_trading_lock_integrity(
            execution_mode="live", live_trading_disabled=True
        )

    def test_live_with_lock_disabled_no_raise(self) -> None:
        """live + LIVE_TRADING_DISABLED=False → 真金放行态, 不 raise."""
        assert_live_trading_lock_integrity(
            execution_mode="live", live_trading_disabled=False
        )


class TestSettingsFallback:
    """None args → 读 settings (生产默认路径覆盖, sustained execution_mode test 体例)."""

    def test_none_args_paper_locked_no_raise(self, monkeypatch) -> None:
        from app import config as app_config

        monkeypatch.setattr(app_config.settings, "EXECUTION_MODE", "paper")
        monkeypatch.setattr(app_config.settings, "LIVE_TRADING_DISABLED", True)
        assert_live_trading_lock_integrity()  # paper + True → no raise

    def test_none_args_paper_unlocked_raises(self, monkeypatch) -> None:
        from app import config as app_config

        monkeypatch.setattr(app_config.settings, "EXECUTION_MODE", "paper")
        monkeypatch.setattr(app_config.settings, "LIVE_TRADING_DISABLED", False)
        with pytest.raises(ConfigDriftError):
            assert_live_trading_lock_integrity()

    def test_partial_explicit_mode_reads_lock_from_settings(self, monkeypatch) -> None:
        """execution_mode 显式 + live_trading_disabled=None → 后者读 settings."""
        from app import config as app_config

        monkeypatch.setattr(app_config.settings, "LIVE_TRADING_DISABLED", False)
        with pytest.raises(ConfigDriftError):
            assert_live_trading_lock_integrity(execution_mode="paper")
