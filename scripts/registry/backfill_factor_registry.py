"""MVP 1.3a: factor_registry 回填脚本.

把 live PG factor_values 出现的所有 factor_name 补齐到 factor_registry 表,
补字段: direction / category / pool / hypothesis / source / status / lookback_days.

3 层数据源合并 (优先级从高到低):
  Layer 1: live PG factor_registry 现有行 (DB 是最权威, UPSERT 只补缺字段)
  Layer 2: _constants.py + HARDCODED_SIGNAL_ENGINE_DIRECTION (硬编码 direction)
  Layer 3: factor_values distinct factor_name (发现孤儿, 走默认)

回填后:
  - CORE3+dv_ttm 4 因子 → pool='CORE' (PT 生产)
  - CORE5 baseline 2 因子 → pool='CORE5_baseline'
  - 已知 hardcoded + 画像过的 → pool='PASS'
  - 无元数据 → pool='LEGACY', direction=1, hypothesis='[AUTO_BACKFILL] 需人工审核'
  - INVALIDATED 列表 → pool='INVALIDATED'

Usage:
    # dry-run 默认 (不写 DB, 只输出 diff)
    python scripts/registry/backfill_factor_registry.py

    # 真正写入
    python scripts/registry/backfill_factor_registry.py --apply
"""
from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT / "backend") not in sys.path:
    sys.path.append(str(_PROJECT_ROOT / "backend"))


# ============================================================
# 硬编码 direction (从 signal_engine.py FACTOR_DIRECTION 复制, 避免 import 副作用)
# ============================================================
# Source: backend/engines/signal_engine.py L20-53 (2026-04-17 snapshot)
_SIGNAL_ENGINE_DIRECTION: dict[str, int] = {
    "momentum_5": 1,
    "momentum_10": 1,
    "momentum_20": 1,
    "reversal_5": 1,
    "reversal_10": 1,
    "reversal_20": 1,  # historical, CORE5_baseline
    "volatility_20": -1,
    "volatility_60": -1,
    "volume_std_20": -1,
    "turnover_mean_20": -1,  # CORE
    "turnover_std_20": -1,
    "amihud_20": 1,  # CORE5_baseline
    "ln_market_cap": -1,
    "bp_ratio": 1,  # CORE
    "ep_ratio": 1,
    "price_volume_corr_20": -1,
    "high_low_range_20": -1,
    # Session 27 Task B 清理 (2026-04-24): 2 条 orphan (mf_momentum_divergence +
    # earnings_surprise_car) 从 _HARDCODED_DIRECTIONS 删除. 原因:
    #   - mf_momentum_divergence: INVALIDATED (IC=-2.27% 非 9.1%, failed_directions 已记)
    #     + 已从 factor_registry DELETE (migration cleanup_orphan_factors_session27.sql)
    #   - earnings_surprise_car: ghost factor (signal_engine.FACTOR_DIRECTION 有
    #     direction 但无 calc_*), registry 已改 status=deprecated + pool=DEPRECATED
    # _POOL_INVALIDATED 保留 mf_momentum_divergence (防未来 LLM 重名复用, 铁律 12).
    "price_level_factor": -1,
    "relative_volume_20": -1,
    "dv_ttm": 1,  # CORE (新加 2026-04-12)
    "turnover_surge_ratio": -1,
    "high_vol_price_ratio_20": -1,
}


# ============================================================
# 生命周期池分类 (CLAUDE.md + FACTOR_TEST_REGISTRY.md 共识)
# ============================================================
_POOL_CORE: frozenset[str] = frozenset(
    {"turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm"}
)  # CORE3+dv_ttm, PT 生产在用 (WF OOS Sharpe=0.8659)
_POOL_CORE5_BASELINE: frozenset[str] = frozenset(
    {"reversal_20", "amihud_20"}
)  # CORE5 历史基线 (regression_test 用)
_POOL_INVALIDATED: frozenset[str] = frozenset(
    {"mf_momentum_divergence"}  # IC=-2.27% 非 9.1%, v3.4 证伪
)
_POOL_DEPRECATED: frozenset[str] = frozenset(
    {
        # Phase 6-F 废弃动量/波动系列 (CLAUDE.md §因子池状态):
        "momentum_5", "momentum_10", "momentum_60",
        "volatility_60", "turnover_std_20",
        # Session 27 Task B 清理 (2026-04-24): factor_values 0 行 orphan, registry
        # UPDATE status=deprecated + pool=DEPRECATED (migration
        # cleanup_orphan_factors_session27.sql). 加入本 set 防 backfill 重跑
        # 走 Layer2 hardcoded direction 路径将 pool 从 DEPRECATED revert 回 PASS.
        # 注: mf_momentum_divergence 已 DELETE (类别 A INVALIDATED), 本 set 仍保留名字作
        # 重命名防护 + _POOL_INVALIDATED 双重保险; earnings_surprise_car 类 ghost 无 calc;
        # 8 个 fundamental factors (pead_q1+roe_delta+...) 有 calc 但 factor_set='core'
        # 生产调度不含, 未来 Phase X 重启 fundamental pipeline 时从本 set 移除即可.
        "mf_momentum_divergence",        # INVALIDATED ghost (类别 A, DELETE)
        "earnings_surprise_car",         # ghost (signal_engine FACTOR_DIRECTION 有 dir 无 calc)
        "pead_q1",                       # PEAD 有 calc (pead.py) 但无 daily pipeline
        "eps_acceleration",              # FUNDAMENTAL_DELTA_META 有 meta + load_fundamental_pit_data 计算
        "gross_margin_delta",            # 同上
        "net_margin_delta",              # 同上
        "revenue_growth_yoy",            # 同上
        "roe_delta",                     # 同上
        "debt_change",                   # 同上
        "days_since_announcement",       # FUNDAMENTAL_TIME_META 有 meta + load_fundamental_pit_data 计算
        "reporting_season_flag",         # 同上
    }
)  # CLAUDE.md §因子池状态


# ============================================================
# Category 推断规则 (从因子名 prefix/pattern 推断)
# ============================================================
_CATEGORY_RULES: list[tuple[str, str]] = [
    # (pattern 子串, category) — 顺序优先, **特定 pattern 必须放通用 pattern 前**.
    # 微结构 (放 volatility / momentum / corr 等通用 pattern 前)
    ("high_freq", "microstructure"),
    ("vwap_bias", "microstructure"),
    ("vwap_deviation", "microstructure"),
    ("rsrs", "microstructure"),
    ("volume_concentration", "microstructure"),
    ("volume_autocorr", "microstructure"),
    ("volume_price_divergence", "microstructure"),
    ("smart_money", "microstructure"),
    ("opening_volume_share", "microstructure"),
    ("closing_trend_strength", "microstructure"),
    ("order_flow_imbalance", "microstructure"),
    ("intraday_momentum", "microstructure"),
    ("weighted_price", "microstructure"),
    # 资金流 (放 momentum 前)
    ("mf_", "moneyflow"),
    ("buy_sm", "moneyflow"),
    ("buy_md", "moneyflow"),
    ("buy_lg", "moneyflow"),
    ("buy_elg", "moneyflow"),
    ("net_mf", "moneyflow"),
    # price_volume (放 corr 前)
    ("price_volume_corr", "price_volume"),
    ("high_low_range", "price_volume"),
    ("turnover_surge", "price_volume"),
    # 事件 (放 event-related pattern)
    ("pead", "event"),
    ("earnings_surprise", "event"),
    # alpha158 子包
    ("a158_", "alpha158"),
    # phase21 (放 通用 CORR 前)
    ("high_vol_price_ratio", "phase21"),
    ("IMAX", "phase21"),
    ("IMIN", "phase21"),
    ("QTLU", "phase21"),
    ("CORD", "phase21"),
    ("RSQR", "phase21"),
    ("RESI", "phase21"),
    ("CNTD", "phase21"),
    ("CNTN", "phase21"),
    ("CNTP", "phase21"),
    ("CORR", "phase21"),  # 通用 CORR (price_volume_corr 已在前面处理)
    # 北向
    ("nb_", "northbound"),
    ("northbound", "northbound"),
    # liquidity
    ("turnover", "liquidity"),
    ("volume_ratio", "liquidity"),
    ("amihud", "liquidity"),
    ("relative_volume", "liquidity"),
    # 基本面 (放 momentum 前以免 "eps_acceleration" 匹 momentum-like)
    ("bp_ratio", "fundamental"),
    ("ep_ratio", "fundamental"),
    ("pe_ttm", "fundamental"),
    ("dv_ttm", "fundamental"),
    ("roe", "fundamental"),
    ("revenue", "fundamental"),
    ("margin", "fundamental"),
    ("debt", "fundamental"),
    ("net_margin", "fundamental"),
    ("eps", "fundamental"),
    ("days_since_announcement", "fundamental"),
    ("reporting_season", "fundamental"),
    # momentum
    ("momentum", "momentum"),
    ("reversal", "momentum"),
    ("price_level", "momentum"),
    # 风险 (最后放, 因 volatility / std / beta 是很通用的关键词)
    ("volatility", "risk"),
    ("_std_", "risk"),
    ("beta", "risk"),
]


def _infer_category(name: str) -> str:
    """按 _CATEGORY_RULES 推断 category, 找不到返 'legacy'."""
    lowered = name.lower()
    for pattern, cat in _CATEGORY_RULES:
        if pattern.lower() in lowered:
            return cat
    return "legacy"


def _infer_pool(name: str, has_hardcoded_direction: bool) -> str:
    """推断 pool."""
    if name in _POOL_CORE:
        return "CORE"
    if name in _POOL_CORE5_BASELINE:
        return "CORE5_baseline"
    if name in _POOL_INVALIDATED:
        return "INVALIDATED"
    if name in _POOL_DEPRECATED:
        return "DEPRECATED"
    if has_hardcoded_direction:
        return "PASS"
    return "LEGACY"


def _infer_status(name: str) -> str:
    """pool → status 映射."""
    if name in _POOL_CORE or name in _POOL_CORE5_BASELINE:
        return "active"
    if name in _POOL_INVALIDATED:
        return "deprecated"
    if name in _POOL_DEPRECATED:
        return "deprecated"
    return "warning"  # 默认: 历史因子有待确认


# ============================================================
# 数据加载 (3 层)
# ============================================================


def _load_layer1_existing_registry(conn) -> dict[str, dict[str, Any]]:
    """Layer 1: live PG factor_registry 现有行 (最权威)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT name, category, direction, expression, hypothesis, "
            "       source, lookback_days, status, pool "
            "FROM factor_registry ORDER BY name"
        )
        rows = cur.fetchall()
        cols = ["name", "category", "direction", "expression", "hypothesis",
                "source", "lookback_days", "status", "pool"]
    return {row[0]: dict(zip(cols, row, strict=True)) for row in rows}


def _load_layer2_hardcoded_directions() -> dict[str, int]:
    """Layer 2: hardcoded direction 合并 (_constants.py + signal_engine snapshot)."""
    from engines.factor_engine._constants import (
        ALPHA158_FACTOR_DIRECTION,
        FUNDAMENTAL_FACTOR_DIRECTION,
        MINUTE_FACTOR_DIRECTION,
        PEAD_FACTOR_DIRECTION,
        PHASE21_FACTOR_DIRECTION,
        RESERVE_FACTOR_DIRECTION,
    )
    merged: dict[str, int] = {}
    for d in (
        _SIGNAL_ENGINE_DIRECTION,
        ALPHA158_FACTOR_DIRECTION,
        RESERVE_FACTOR_DIRECTION,
        PEAD_FACTOR_DIRECTION,
        PHASE21_FACTOR_DIRECTION,
        FUNDAMENTAL_FACTOR_DIRECTION,
        MINUTE_FACTOR_DIRECTION,
    ):
        merged.update(d)
    return merged


def _load_layer3_factor_values_distinct(conn) -> list[str]:
    """Layer 3: factor_values 表 distinct factor_name."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")
        return [row[0] for row in cur.fetchall()]


# ============================================================
# 合并 + 回填
# ============================================================


def _merge_plan(
    layer1: dict[str, dict[str, Any]],
    layer2: dict[str, int],
    layer3: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """合并 3 层数据源, 产出 INSERT/UPDATE 列表.

    Returns:
      (to_insert, to_update, conflicts): to_insert = 新行; to_update = 只补缺字段的行;
      conflicts = layer1 vs layer2 direction 冲突的因子名 (跳过不 overwrite, WARN).
    """
    all_names = set(layer1) | set(layer2) | set(layer3)

    to_insert: list[dict[str, Any]] = []
    to_update: list[dict[str, Any]] = []
    conflicts: list[str] = []

    for name in sorted(all_names):
        direction_hc = layer2.get(name)
        existing = layer1.get(name)

        if existing is not None:
            # Layer 1 存在 — 只补缺字段, 不改 direction
            # 冲突检查
            if direction_hc is not None and int(existing["direction"]) != int(direction_hc):
                conflicts.append(
                    f"{name}: DB={existing['direction']} vs hardcoded={direction_hc} (保留 DB)"
                )
            # pool 是新字段, layer 1 都是默认 'CANDIDATE', 需要重新推断
            has_hc = direction_hc is not None
            new_pool = _infer_pool(name, has_hc)
            new_status = _infer_status(name)
            needs_update = (
                existing.get("pool") == "CANDIDATE"  # 刚 migration 后全是 CANDIDATE
                or (existing.get("pool") != new_pool and new_pool != "LEGACY")
                or (existing.get("status") is None)
            )
            if needs_update:
                to_update.append({
                    "name": name,
                    "pool": new_pool,
                    "status": new_status,
                })
            continue

        # Layer 1 不存在, 新建行
        direction = direction_hc if direction_hc is not None else 1
        category = _infer_category(name)
        has_hc = direction_hc is not None
        pool = _infer_pool(name, has_hc)
        status = _infer_status(name)
        hypothesis = (
            f"[AUTO_BACKFILL] {name}: hardcoded direction={direction} from "
            f"_constants.py/signal_engine.py"
            if has_hc
            else f"[AUTO_BACKFILL] {name}: 无元数据, 默认 direction=1. 人工审核后修正"
        )
        to_insert.append({
            "name": name,
            "category": category,
            "direction": direction,
            "expression": None,  # legacy 因子无表达式, MVP 1.3b 再补
            "hypothesis": hypothesis,
            "source": "builtin" if has_hc else "legacy",
            "lookback_days": 60,
            "status": status,
            "pool": pool,
        })

    return to_insert, to_update, conflicts


def _apply_inserts(conn, rows: list[dict[str, Any]]) -> int:
    """批量 INSERT 新行. 跳过 id / gate_* / ic_decay_ratio (默认 NULL + uuid_generate_v4())."""
    if not rows:
        return 0
    sql = """
        INSERT INTO factor_registry
            (name, category, direction, expression, hypothesis, source,
             lookback_days, status, pool, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (name) DO NOTHING
    """
    now = datetime.now(UTC)
    params = [
        (
            r["name"], r["category"], r["direction"], r["expression"],
            r["hypothesis"], r["source"], r["lookback_days"], r["status"],
            r["pool"], now, now,
        )
        for r in rows
    ]
    n_ok = 0
    with conn.cursor() as cur:
        for p in params:
            cur.execute(sql, p)
            n_ok += cur.rowcount
    return n_ok


def _apply_updates(conn, rows: list[dict[str, Any]]) -> int:
    """批量 UPDATE 仅 pool + status (保留其他字段不动)."""
    if not rows:
        return 0
    sql = """
        UPDATE factor_registry
        SET pool = %s, status = %s, updated_at = NOW()
        WHERE name = %s
    """
    n_ok = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(sql, (r["pool"], r["status"], r["name"]))
            n_ok += cur.rowcount
    return n_ok


# ============================================================
# CLI
# ============================================================


def _print_diff(
    to_insert: list[dict[str, Any]],
    to_update: list[dict[str, Any]],
    conflicts: list[str],
) -> None:
    print("=" * 78)
    print("MVP 1.3a factor_registry backfill diff")
    print("=" * 78)
    print(f"INSERT {len(to_insert)} 行:")
    # pool 统计
    pool_counts: dict[str, int] = {}
    for r in to_insert:
        pool_counts[r["pool"]] = pool_counts.get(r["pool"], 0) + 1
    for pool, n in sorted(pool_counts.items()):
        print(f"  pool={pool}: {n} 行")
    # 样本
    print("\n样本 (前 10 + 抽 pool=LEGACY 3 + pool=CORE 所有):")
    shown: set[str] = set()
    for r in to_insert[:10]:
        print(f"  {r['name']:35s} direction={r['direction']:+d} pool={r['pool']:15s} "
              f"category={r['category']:15s} source={r['source']}")
        shown.add(r["name"])
    core_samples = [r for r in to_insert if r["pool"] == "CORE"]
    for r in core_samples:
        if r["name"] not in shown:
            print(f"  {r['name']:35s} direction={r['direction']:+d} pool={r['pool']:15s} "
                  f"category={r['category']:15s} (CORE 新增)")
    legacy_samples = [r for r in to_insert if r["pool"] == "LEGACY"][:3]
    for r in legacy_samples:
        if r["name"] not in shown:
            print(f"  {r['name']:35s} direction={r['direction']:+d} pool={r['pool']:15s} "
                  f"category={r['category']:15s} (LEGACY 样本)")

    print(f"\nUPDATE {len(to_update)} 行 (补 pool/status):")
    for r in to_update:
        print(f"  {r['name']:35s} → pool={r['pool']}, status={r['status']}")

    print(f"\nCONFLICTS {len(conflicts)} 项 (保留 DB 值):")
    for c in conflicts:
        print(f"  {c}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MVP 1.3a factor_registry backfill")
    parser.add_argument("--apply", action="store_true", help="真正写入 DB (默认 dry-run)")
    args = parser.parse_args()

    from app.services.db import get_sync_conn

    conn = get_sync_conn()
    try:
        print("[1/4] 加载 Layer 1: live PG factor_registry 现有行 ...")
        layer1 = _load_layer1_existing_registry(conn)
        print(f"  → {len(layer1)} 行")

        print("[2/4] 加载 Layer 2: _constants.py + signal_engine hardcoded direction ...")
        layer2 = _load_layer2_hardcoded_directions()
        print(f"  → {len(layer2)} 因子 hardcoded direction")

        print("[3/4] 加载 Layer 3: factor_values distinct factor_name ...")
        layer3 = _load_layer3_factor_values_distinct(conn)
        print(f"  → {len(layer3)} distinct factor_name")

        print("[4/4] 合并 + 产出 diff ...")
        to_insert, to_update, conflicts = _merge_plan(layer1, layer2, layer3)
        _print_diff(to_insert, to_update, conflicts)

        if args.apply:
            print("\n" + "=" * 78)
            print("--apply 模式: 开始写入 DB")
            print("=" * 78)
            n_ins = _apply_inserts(conn, to_insert)
            n_upd = _apply_updates(conn, to_update)
            conn.commit()
            print(f"✅ INSERT {n_ins} 行, UPDATE {n_upd} 行, 事务 commit.")
            # 验收
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM factor_registry")
                total = cur.fetchone()[0]
            print(f"✅ factor_registry 现有 {total} 行")
        else:
            print("\n" + "=" * 78)
            print("DRY-RUN 模式: 不写 DB. 确认无误后跑:")
            print("  python scripts/registry/backfill_factor_registry.py --apply")
            print("=" * 78)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
