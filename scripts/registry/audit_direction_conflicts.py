"""MVP 1.3b Step 1: 审计并修复 factor_registry direction vs hardcoded 冲突.

背景:
  MVP 1.3a 回填时对 `reversal_20` 选择了 "保 DB 值" (DB=-1, hardcoded=+1),
  但 regression baseline 是基于 signal_engine.py hardcoded 跑出的 max_diff=0 锚点.
  如果直接切 DB, PT 信号会反向. 本脚本先把 DB 对齐 hardcoded, 让 DB 成为
  signal_engine 的**镜像真相源**, 再切 FeatureFlag 才安全.

策略:
  - hardcoded (signal_engine.py + _constants.py) 为权威
  - 发现冲突 → UPDATE DB direction = hardcoded 值
  - 备份所有修改到 JSON, 支持 rollback
  - 幂等: 重复跑无 side effect

Usage:
    # dry-run 默认 (不写 DB)
    python scripts/registry/audit_direction_conflicts.py

    # 真正写入
    python scripts/registry/audit_direction_conflicts.py --apply

    # 用 backup JSON 回滚
    python scripts/registry/audit_direction_conflicts.py --rollback <backup.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT / "backend") not in sys.path:
    sys.path.append(str(_PROJECT_ROOT / "backend"))


# ============================================================
# 硬编码 direction 合并 (对齐 backfill_factor_registry.py 的 Layer 2)
# ============================================================
# 保证和 signal_engine.py FACTOR_DIRECTION + _constants.py 完全一致

_SIGNAL_ENGINE_DIRECTION: dict[str, int] = {
    "momentum_5": 1, "momentum_10": 1, "momentum_20": 1,
    "reversal_5": 1, "reversal_10": 1, "reversal_20": 1,
    "volatility_20": -1, "volatility_60": -1, "volume_std_20": -1,
    "turnover_mean_20": -1, "turnover_std_20": -1,
    "amihud_20": 1, "ln_market_cap": -1,
    "bp_ratio": 1, "ep_ratio": 1,
    "price_volume_corr_20": -1, "high_low_range_20": -1,
    "mf_momentum_divergence": -1, "earnings_surprise_car": 1,
    "price_level_factor": -1, "relative_volume_20": -1,
    "dv_ttm": 1, "turnover_surge_ratio": -1,
    "high_vol_price_ratio_20": -1,
}


def _load_hardcoded_directions() -> dict[str, int]:
    """合并 _constants.py 所有 direction dict + signal_engine 内嵌."""
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


def _load_db_directions(conn) -> dict[str, int]:
    with conn.cursor() as cur:
        cur.execute("SELECT name, direction FROM factor_registry")
        return {row[0]: int(row[1]) for row in cur.fetchall()}


def _find_conflicts(
    hardcoded: dict[str, int], db: dict[str, int]
) -> list[dict[str, Any]]:
    """找 DB vs hardcoded 不一致的项."""
    conflicts: list[dict[str, Any]] = []
    for name, hc_dir in sorted(hardcoded.items()):
        db_dir = db.get(name)
        if db_dir is None:
            continue  # DB 没这个因子, 不是冲突 (由 backfill 处理)
        if db_dir != hc_dir:
            conflicts.append({"name": name, "db": db_dir, "hardcoded": hc_dir})
    return conflicts


def _apply_fix(conn, conflicts: list[dict[str, Any]]) -> tuple[int, Path]:
    """把 DB direction 更新为 hardcoded. 保存 backup JSON."""
    if not conflicts:
        return 0, Path()

    # 1. backup JSON
    backup_dir = _PROJECT_ROOT / "cache" / "registry_audit"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_path = backup_dir / f"direction_conflict_backup_{ts}.json"
    backup_path.write_text(
        json.dumps(
            {
                "timestamp_utc": ts,
                "action": "direction_fix",
                "conflicts": conflicts,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 2. UPDATE
    n_updated = 0
    with conn.cursor() as cur:
        for c in conflicts:
            cur.execute(
                "UPDATE factor_registry SET direction = %s, updated_at = NOW() "
                "WHERE name = %s AND direction = %s",
                (c["hardcoded"], c["name"], c["db"]),
            )
            n_updated += cur.rowcount
    conn.commit()
    return n_updated, backup_path


def _rollback_from_backup(conn, backup_path: Path) -> int:
    """读 backup JSON, 回滚 DB 为 backup.conflicts[i].db 值."""
    data = json.loads(backup_path.read_text(encoding="utf-8"))
    conflicts = data["conflicts"]
    n = 0
    with conn.cursor() as cur:
        for c in conflicts:
            # 回滚 = 把 direction 改回 DB 原始值
            cur.execute(
                "UPDATE factor_registry SET direction = %s, updated_at = NOW() "
                "WHERE name = %s AND direction = %s",
                (c["db"], c["name"], c["hardcoded"]),
            )
            n += cur.rowcount
    conn.commit()
    return n


def _print_report(
    hardcoded: dict[str, int],
    db: dict[str, int],
    conflicts: list[dict[str, Any]],
) -> None:
    print("=" * 78)
    print("MVP 1.3b direction conflict 审计")
    print("=" * 78)
    print(f"hardcoded direction 因子数: {len(hardcoded)}")
    print(f"DB factor_registry 因子数:  {len(db)}")
    print(f"交集因子 (双方都定义):     {len(set(hardcoded) & set(db))}")
    print(f"DB 独有 (legacy, 保持):    {len(set(db) - set(hardcoded))}")
    print(f"hardcoded 独有 (未入 DB):  {len(set(hardcoded) - set(db))}")
    print()
    if not conflicts:
        print("✅ 0 冲突. DB 与 hardcoded 全部 direction 对齐.")
    else:
        print(f"⚠️  发现 {len(conflicts)} 项冲突 (将修 DB 对齐 hardcoded):")
        for c in conflicts:
            print(f"  {c['name']:30s} DB={c['db']:+d} → hardcoded={c['hardcoded']:+d}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MVP 1.3b direction conflict 审计")
    parser.add_argument("--apply", action="store_true", help="真正写入 DB (默认 dry-run)")
    parser.add_argument("--rollback", type=str, default=None,
                        help="从 backup JSON 回滚 (提供 path)")
    args = parser.parse_args()

    from app.services.db import get_sync_conn

    conn = get_sync_conn()
    try:
        if args.rollback:
            backup_path = Path(args.rollback)
            if not backup_path.is_absolute():
                backup_path = _PROJECT_ROOT / backup_path
            print(f"[ROLLBACK] 从 {backup_path} 回滚 ...")
            n = _rollback_from_backup(conn, backup_path)
            print(f"✅ 回滚 {n} 行")
            return

        print("[1/3] 加载 hardcoded direction ...")
        hardcoded = _load_hardcoded_directions()

        print("[2/3] 加载 live PG factor_registry ...")
        db = _load_db_directions(conn)

        print("[3/3] 对比找冲突 ...")
        conflicts = _find_conflicts(hardcoded, db)
        _print_report(hardcoded, db, conflicts)

        if args.apply:
            print("\n" + "=" * 78)
            print("--apply 模式: 开始修 DB")
            print("=" * 78)
            n, backup_path = _apply_fix(conn, conflicts)
            print(f"✅ UPDATE {n} 行. Backup: {backup_path}")
            print(f"   回滚命令: python scripts/registry/audit_direction_conflicts.py "
                  f"--rollback {backup_path.relative_to(_PROJECT_ROOT)}")
        elif conflicts:
            print("\n" + "=" * 78)
            print("DRY-RUN: 不写 DB. 确认后跑 --apply.")
            print("=" * 78)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
