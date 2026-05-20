"""Plan G unit tests — DSR wiring into rolling_wf (DEV_BACKTEST_ENGINE §4.12.1).

覆盖:
  - _compute_dsr: 正常计算 / 数据不足 / None 收益 / NaN skew (2 点序列) / 引擎异常
  - _classify_result: DSR suffix 渲染 + DSR_LOW 升级 (OK→WARN) + 不下调 P1/WARN +
    旧 result JSON 无 DSR 字段兼容 (--skip-wf path)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import rolling_wf as rwf  # noqa: E402

# interpret_dsr 的 3 个返回串 (engines/dsr.py SSOT) — 测试断言 membership 用
_DSR_INTERPS = (
    "统计显著: Sharpe大概率不是运气",
    "可疑: 可能部分来自过拟合",
    "不显著: 大概率是过拟合",
)


def _returns(n: int = 300, mu: float = 0.0008, sigma: float = 0.012, seed: int = 42):
    """构造合成 WF OOS 拼接日收益 Series。"""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mu, sigma, n))


# ─────────────────────────── _compute_dsr ───────────────────────────


class TestComputeDsr:
    def test_normal_case_returns_dsr_in_range(self):
        dsr, interp = rwf._compute_dsr(0.86, _returns(), 300)
        assert dsr is not None
        assert 0.0 <= dsr <= 1.0
        # round 到 4 位
        assert dsr == round(dsr, 4)
        assert interp in _DSR_INTERPS

    def test_insufficient_days_returns_none(self):
        """total_oos_days < 2 → 数据不足 guard 命中, 返 (None, "")."""
        dsr, interp = rwf._compute_dsr(0.86, _returns(n=1), 1)
        assert dsr is None
        assert interp == ""

    def test_none_returns_series_returns_none(self):
        """combined_oos_returns is None → guard 命中 (短路, 不抛 len(None))."""
        dsr, interp = rwf._compute_dsr(0.86, None, 300)
        assert dsr is None
        assert interp == ""

    def test_nonfinite_skew_returns_none(self):
        """2 点序列 .skew()=NaN → np.isfinite guard 命中, 安全返 None 不抛异常."""
        two_point = pd.Series([0.01, 0.02])
        dsr, interp = rwf._compute_dsr(0.86, two_point, 2)
        assert dsr is None
        assert interp == ""

    def test_engine_exception_returns_none(self, monkeypatch):
        """DSR 引擎抛异常 → _compute_dsr 吞掉返 None (补充指标不阻断 WF 主结果)."""

        def _boom(**kwargs):
            raise ValueError("synthetic engine failure")

        monkeypatch.setattr("engines.dsr.deflated_sharpe_ratio", _boom)
        dsr, interp = rwf._compute_dsr(0.86, _returns(), 300)
        assert dsr is None
        assert interp == ""


# ─────────────────────────── _classify_result ───────────────────────────


def _wf(chain_sharpe, neg_folds=0, dsr=None, dsr_interpretation=""):
    return {
        "chain_sharpe": chain_sharpe,
        "neg_folds": neg_folds,
        "dsr": dsr,
        "dsr_interpretation": dsr_interpretation,
    }


class TestClassifyResultDsr:
    def test_ok_with_high_dsr_stays_stable(self):
        c = rwf._classify_result(
            _wf(0.86, dsr=0.97, dsr_interpretation="统计显著: Sharpe大概率不是运气")
        )
        assert c["level"] == "OK"
        assert c["label"] == "STABLE"
        assert "DSR=0.97" in c["msg"]

    def test_ok_sharpe_but_low_dsr_escalates_to_warn(self):
        """Sharpe 判定 OK 但 DSR < 0.5 → 升级 WARN, label=DSR_LOW."""
        c = rwf._classify_result(_wf(0.86, dsr=0.4, dsr_interpretation="不显著: 大概率是过拟合"))
        assert c["level"] == "WARN"
        assert c["label"] == "DSR_LOW"
        assert "0.4" in c["msg"]

    def test_dsr_none_no_escalation_no_suffix(self):
        """旧 result JSON (无 DSR 字段, --skip-wf) → dsr=None, OK 不升级, msg 无 DSR."""
        c = rwf._classify_result(_wf(0.86, dsr=None))
        assert c["level"] == "OK"
        assert c["label"] == "STABLE"
        assert "DSR" not in c["msg"]

    def test_skip_wf_legacy_dict_without_dsr_keys(self):
        """完全无 dsr/dsr_interpretation key 的旧 dict — .get() 兼容不 KeyError."""
        c = rwf._classify_result({"chain_sharpe": 0.86, "neg_folds": 0})
        assert c["level"] == "OK"
        assert c["label"] == "STABLE"

    def test_negative_fold_stays_p1_regardless_of_dsr(self):
        """neg_fold → P1; 即使 DSR 高 (0.99) 也不下调等级."""
        c = rwf._classify_result(_wf(0.5, neg_folds=1, dsr=0.99))
        assert c["level"] == "P1"
        assert c["label"] == "NEGATIVE_FOLD"

    def test_sharpe_alert_stays_p1_with_dsr_suffix(self):
        """chain_sharpe < 基线*0.70 (=0.606) → P1 SHARPE_ALERT, msg 含 DSR suffix."""
        c = rwf._classify_result(_wf(0.3, dsr=0.2, dsr_interpretation="不显著: 大概率是过拟合"))
        assert c["level"] == "P1"
        assert c["label"] == "SHARPE_ALERT"
        assert "DSR=0.2" in c["msg"]

    def test_sharpe_warn_stays_warn_with_dsr_suffix(self):
        """基线*0.70 (0.606) <= chain_sharpe < 基线*0.85 (0.736) → WARN SHARPE_WARN."""
        c = rwf._classify_result(_wf(0.65, dsr=0.8))
        assert c["level"] == "WARN"
        assert c["label"] == "SHARPE_WARN"
        assert "DSR=0.8" in c["msg"]
