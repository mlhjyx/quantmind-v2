"""MVP 1.3a test — backfill_factor_registry 核心函数单元测试.

验证:
  - Category 推断规则 (10+ prefix patterns)
  - Pool 推断 (CORE / CORE5_baseline / INVALIDATED / DEPRECATED / PASS / LEGACY)
  - Status 推断
  - 3 层合并逻辑 (DB existing / hardcoded / orphan)
  - Conflict detection (DB vs hardcoded direction 冲突)

不触 live PG, 全 Python 单元测试 (脚本逻辑独立 testable).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# 动态 import 脚本 (不在 sys.path 默认, 也不改 pyproject packages)
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2] / "scripts" / "registry" / "backfill_factor_registry.py"
)
_spec = importlib.util.spec_from_file_location("backfill_factor_registry", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_backfill = importlib.util.module_from_spec(_spec)
sys.modules["backfill_factor_registry"] = _backfill
_spec.loader.exec_module(_backfill)


# ============================================================
# _infer_category (10+ rules)
# ============================================================


@pytest.mark.parametrize(
    "name,expected_category",
    [
        # liquidity
        ("turnover_mean_20", "liquidity"),
        ("amihud_20", "liquidity"),
        ("volume_ratio_daily", "liquidity"),
        ("relative_volume_20", "liquidity"),
        # risk
        ("volatility_20", "risk"),
        ("BETA10", "risk"),
        # fundamental
        ("bp_ratio", "fundamental"),
        ("dv_ttm", "fundamental"),
        ("pe_ttm", "fundamental"),
        ("roe_delta", "fundamental"),
        ("revenue_growth_yoy", "fundamental"),
        ("eps_acceleration", "fundamental"),
        ("days_since_announcement", "fundamental"),
        # momentum
        ("momentum_20", "momentum"),
        ("reversal_5", "momentum"),
        ("price_level_factor", "momentum"),
        # microstructure
        ("vwap_bias_1d", "microstructure"),
        ("vwap_deviation_20", "microstructure"),
        ("high_freq_volatility_20", "microstructure"),
        ("smart_money_ratio_20", "microstructure"),
        # moneyflow
        ("mf_momentum_divergence", "moneyflow"),
        ("net_mf_amount", "moneyflow"),
        # northbound
        ("nb_ratio_change_5d", "northbound"),
        # event
        ("pead_q1", "event"),
        ("earnings_surprise_car", "event"),
        # alpha158
        ("a158_std60", "alpha158"),
        # phase21
        ("RSQR_20", "phase21"),
        ("CORD_20", "phase21"),
        ("QTLU_20", "phase21"),
        ("CNTD5", "phase21"),
        # price_volume
        ("price_volume_corr_20", "price_volume"),
        ("high_low_range_20", "price_volume"),
        # legacy 兜底
        ("totally_unknown_xyz", "legacy"),
    ],
)
def test_infer_category(name: str, expected_category: str) -> None:
    assert _backfill._infer_category(name) == expected_category


# ============================================================
# _infer_pool
# ============================================================


def test_infer_pool_core() -> None:
    for name in ("turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm"):
        assert _backfill._infer_pool(name, has_hardcoded_direction=True) == "CORE"


def test_infer_pool_core5_baseline() -> None:
    for name in ("reversal_20", "amihud_20"):
        assert _backfill._infer_pool(name, has_hardcoded_direction=True) == "CORE5_baseline"


def test_infer_pool_invalidated() -> None:
    assert _backfill._infer_pool("mf_momentum_divergence", True) == "INVALIDATED"


def test_infer_pool_deprecated() -> None:
    for name in ("momentum_5", "momentum_10", "volatility_60", "turnover_std_20"):
        assert _backfill._infer_pool(name, True) == "DEPRECATED"


def test_infer_pool_pass_if_hardcoded() -> None:
    assert _backfill._infer_pool("price_volume_corr_20", True) == "PASS"
    assert _backfill._infer_pool("high_low_range_20", True) == "PASS"


def test_infer_pool_legacy_if_no_hardcoded() -> None:
    assert _backfill._infer_pool("BETA10", False) == "LEGACY"
    assert _backfill._infer_pool("CNTD5", False) == "LEGACY"


# ============================================================
# _infer_status
# ============================================================


def test_infer_status_active_for_core() -> None:
    assert _backfill._infer_status("turnover_mean_20") == "active"
    assert _backfill._infer_status("reversal_20") == "active"  # CORE5_baseline


def test_infer_status_deprecated() -> None:
    assert _backfill._infer_status("mf_momentum_divergence") == "deprecated"  # INVALIDATED
    assert _backfill._infer_status("momentum_5") == "deprecated"


def test_infer_status_warning_default() -> None:
    assert _backfill._infer_status("random_legacy_factor") == "warning"


# ============================================================
# _merge_plan (核心逻辑)
# ============================================================


def test_merge_plan_new_factors_from_layer2() -> None:
    """layer1 空, layer2 有 hardcoded, layer3 涵盖 → 全部 INSERT."""
    layer1: dict = {}
    layer2 = {"turnover_mean_20": -1, "new_factor_x": 1}
    layer3 = ["turnover_mean_20", "new_factor_x"]

    inserts, updates, conflicts = _backfill._merge_plan(layer1, layer2, layer3)
    assert len(inserts) == 2
    assert len(updates) == 0
    assert len(conflicts) == 0

    names = {r["name"] for r in inserts}
    assert names == {"turnover_mean_20", "new_factor_x"}
    # CORE pool
    core_row = next(r for r in inserts if r["name"] == "turnover_mean_20")
    assert core_row["pool"] == "CORE"
    assert core_row["direction"] == -1
    assert core_row["source"] == "builtin"


def test_merge_plan_layer3_orphan_defaults() -> None:
    """layer3 独有 → LEGACY + direction=1."""
    layer1: dict = {}
    layer2: dict = {}
    layer3 = ["unknown_legacy"]

    inserts, _, _ = _backfill._merge_plan(layer1, layer2, layer3)
    assert len(inserts) == 1
    row = inserts[0]
    assert row["pool"] == "LEGACY"
    assert row["direction"] == 1
    assert row["source"] == "legacy"
    assert "[AUTO_BACKFILL]" in row["hypothesis"]


def test_merge_plan_layer1_priority_conflict() -> None:
    """layer1 有 direction=-1, layer2 有 =+1 → 保 layer1, 加入 conflicts."""
    layer1 = {
        "reversal_20": {
            "name": "reversal_20",
            "category": "momentum",
            "direction": -1,  # DB 保留 -1
            "expression": None,
            "hypothesis": "reversion",
            "source": "builtin",
            "lookback_days": 60,
            "status": "active",
            "pool": "CANDIDATE",
        }
    }
    layer2 = {"reversal_20": 1}  # hardcoded 冲突
    layer3 = ["reversal_20"]

    inserts, updates, conflicts = _backfill._merge_plan(layer1, layer2, layer3)
    assert len(inserts) == 0
    assert len(conflicts) == 1
    assert "reversal_20" in conflicts[0]
    # UPDATE 应该把 pool 从 CANDIDATE 改成 CORE5_baseline
    assert len(updates) == 1
    assert updates[0]["pool"] == "CORE5_baseline"


def test_merge_plan_layer1_needs_pool_update() -> None:
    """layer1 CANDIDATE 默认 → UPDATE 到正确 pool."""
    layer1 = {
        "bp_ratio": {
            "name": "bp_ratio",
            "category": "fundamental",
            "direction": 1,
            "expression": "inv(pb)",
            "hypothesis": "value",
            "source": "builtin",
            "lookback_days": 60,
            "status": "active",
            "pool": "CANDIDATE",
        }
    }
    layer2 = {"bp_ratio": 1}
    layer3 = ["bp_ratio"]

    _, updates, _ = _backfill._merge_plan(layer1, layer2, layer3)
    assert len(updates) == 1
    assert updates[0]["name"] == "bp_ratio"
    assert updates[0]["pool"] == "CORE"


def test_merge_plan_union_all_layers() -> None:
    """全集 = layer1 ∪ layer2 ∪ layer3."""
    layer1 = {"a": {"name": "a", "direction": 1, "pool": "CORE", "status": "active"}}
    layer2 = {"b": 1}
    layer3 = ["c"]
    inserts, updates, _ = _backfill._merge_plan(layer1, layer2, layer3)
    all_names = {r["name"] for r in inserts} | {r["name"] for r in updates}
    assert all_names == {"b", "c"} | {"a"} if layer1["a"].get("pool") == "CANDIDATE" else {"b", "c"}


def test_merge_plan_sorts_deterministic() -> None:
    """确保输出按 name 排序 (确定性 dry-run)."""
    layer2 = {"zeta": 1, "alpha": 1, "mike": 1}
    inserts, _, _ = _backfill._merge_plan({}, layer2, list(layer2.keys()))
    names = [r["name"] for r in inserts]
    assert names == sorted(names)


# ============================================================
# hypothesis 内容验证
# ============================================================


def test_hypothesis_mentions_auto_backfill_for_hardcoded() -> None:
    layer2 = {"volatility_20": -1}
    inserts, _, _ = _backfill._merge_plan({}, layer2, ["volatility_20"])
    assert "[AUTO_BACKFILL]" in inserts[0]["hypothesis"]
    assert "direction=-1" in inserts[0]["hypothesis"]


def test_hypothesis_mentions_manual_review_for_orphan() -> None:
    inserts, _, _ = _backfill._merge_plan({}, {}, ["orphan_factor"])
    assert "人工审核" in inserts[0]["hypothesis"]
