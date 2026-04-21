"""滚动 IC 移动平均计算 — factor_ic_history.ic_ma20/ic_ma60 回填 (Phase 2 of 铁律 11).

**Session 22 Part 7 (2026-04-21)**: scripts/compute_daily_ic.py (PR #37) 明确 defer:
    "Scope (v1): 只写 ic_5d/10d/20d + ic_abs_5d. 不写 ic_ma20/ic_ma60/decay_level
    (需跨 60 日 rolling, 独立脚本处理). factor_lifecycle 需 ic_ma20/60, 未来 Phase 2 再补."

本脚本即该 Phase 2 独立脚本. 消除 factor_lifecycle_monitor 周五 19:00 跳过 27
factors 的 gap (DB 实测: 113 factors 有 ic_20d, 只 86 有 ic_ma20).

**Canonical 算法 (source of truth: factor_onboarding.py:739-740)**:
    ic_df["ic_ma20"] = ic_df["ic_20d"].rolling(window=20, min_periods=5).mean()
    ic_df["ic_ma60"] = ic_df["ic_20d"].rolling(window=60, min_periods=10).mean()

Rolling 按 factor_name 分组独立计算, 不跨因子 bleed.

**铁律 17 例外声明**: 本脚本对已存在行做 UPDATE **仅 ic_ma20/ic_ma60 两列**, 不 INSERT
新行. 不能走 DataPipeline.ingest: 其 upsert 的 "补缺失 nullable 列为 None" + "UPDATE
SET non_pk = EXCLUDED" 行为会把 ic_5d/10d/20d/ic_abs_5d/decay_level 全 NULL 化, 破坏
已有数据. 本脚本用手工 UPDATE + psycopg2 execute_values. 铁律 17 风险 (单位混乱/code
格式) 在 UPDATE 场景不适用 — PK (factor_name, trade_date) 已存在 = 之前入库已过
DataPipeline 契约验证.

**铁律 32**: 本脚本 (orchestration) 负责 commit, Service 不 commit.
**铁律 33**: 单因子失败 fail-loud + 继续下一因子, 不 silent swallow.

Usage:
    python scripts/compute_ic_rolling.py                # 所有 active factors, 全量重算
    python scripts/compute_ic_rolling.py --factors bp_ratio,dv_ttm   # 指定 factors
    python scripts/compute_ic_rolling.py --core         # 仅 CORE 4
    python scripts/compute_ic_rolling.py --all-factors  # 所有 factors (含 retired)
    python scripts/compute_ic_rolling.py --dry-run      # 不写 DB, 报告 planned updates
    python scripts/compute_ic_rolling.py --verbose      # 详细日志

Cron (Session 22+): 可 wire 到 schtasks, 跟在 compute_daily_ic (18:00) 之后,
e.g. 18:15 (compute_daily_ic 写 ic_20d 完成后 rolling 重算 ic_ma). 不强制 trading_day
guard — rolling 是纯幂等重算, 节假日跑也无害.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# .venv/.pth 已把 backend 加入 sys.path. 避免 insert(0) 与 stdlib platform shadow.
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

import pandas as pd  # noqa: E402
import psycopg2.extensions  # noqa: E402
import psycopg2.extras  # noqa: E402

from app.services.db import get_sync_conn  # noqa: E402

logger = logging.getLogger(__name__)

LOG_DIR = PROJECT_ROOT / "logs"

CORE_FACTORS = ("turnover_mean_20", "volatility_20", "bp_ratio", "dv_ttm")

# Canonical rolling params (factor_onboarding.py:739-740). DO NOT diverge.
MA20_WINDOW = 20
MA20_MIN_PERIODS = 5
MA60_WINDOW = 60
MA60_MIN_PERIODS = 10

# factor_ic_history.ic_ma20/ic_ma60 是 numeric(8,6) → round 到 6 小数
DB_PRECISION = 6

# execute_values batch 大小 (psycopg2 默认 100, 提到 5000 减少 round-trip)
BATCH_SIZE = 5000


def _configure_logging() -> None:
    """延迟 logging 配置 (避免 pytest collect 阶段副作用, 对齐 compute_daily_ic 模式)."""
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_DIR / "compute_ic_rolling.log", encoding="utf-8"),
            logging.StreamHandler(sys.stderr),
        ],
        force=True,
    )


def _fetch_target_factors(
    conn: psycopg2.extensions.connection,
    explicit: list[str] | None,
    all_factors: bool,
) -> list[str]:
    """确定要重算的 factor 列表.

    优先级: explicit (--factors / --core) > --all-factors > default (active/warning only).
    """
    if explicit is not None:
        return explicit
    with conn.cursor() as cur:
        if all_factors:
            cur.execute(
                "SELECT DISTINCT factor_name FROM factor_ic_history "
                "WHERE ic_20d IS NOT NULL ORDER BY factor_name"
            )
        else:
            cur.execute(
                "SELECT name FROM factor_registry "
                "WHERE status IN ('active', 'warning') ORDER BY name"
            )
        return [r[0] for r in cur.fetchall()]


def _load_ic_20d(conn: psycopg2.extensions.connection, factors: list[str]) -> pd.DataFrame:
    """读所有目标 factor 的 (factor_name, trade_date, ic_20d, ic_ma20, ic_ma60).

    ic_20d IS NOT NULL 才参与 rolling. 现有 ic_ma20/ic_ma60 带上用于 idempotent diff.
    """
    if not factors:
        return pd.DataFrame(columns=["factor_name", "trade_date", "ic_20d", "ic_ma20", "ic_ma60"])
    with conn.cursor() as cur:
        cur.execute(
            """SELECT factor_name, trade_date, ic_20d, ic_ma20, ic_ma60
               FROM factor_ic_history
               WHERE factor_name = ANY(%s)
                 AND ic_20d IS NOT NULL
               ORDER BY factor_name, trade_date""",
            (list(factors),),
        )
        rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["factor_name", "trade_date", "ic_20d", "ic_ma20", "ic_ma60"])
    if df.empty:
        return df
    df["ic_20d"] = pd.to_numeric(df["ic_20d"], errors="coerce")
    df["ic_ma20"] = pd.to_numeric(df["ic_ma20"], errors="coerce")
    df["ic_ma60"] = pd.to_numeric(df["ic_ma60"], errors="coerce")
    return df


def compute_rolling(df: pd.DataFrame) -> pd.DataFrame:
    """Canonical rolling (factor_onboarding.py:739-740 对齐).

    Args:
        df: 必须含 [factor_name, trade_date, ic_20d], 按 (factor_name, trade_date) 排序.

    Returns:
        df 原列 + 新增/覆盖 ic_ma20_new / ic_ma60_new 两列 (round 到 DB_PRECISION).

    rolling 按 factor_name 分组, 避免跨因子污染.
    """
    if df.empty:
        out = df.copy()
        out["ic_ma20_new"] = pd.Series(dtype="float64")
        out["ic_ma60_new"] = pd.Series(dtype="float64")
        return out

    out = df.sort_values(["factor_name", "trade_date"]).copy()
    out["ic_ma20_new"] = out.groupby("factor_name")["ic_20d"].transform(
        lambda s: s.rolling(window=MA20_WINDOW, min_periods=MA20_MIN_PERIODS).mean()
    )
    out["ic_ma60_new"] = out.groupby("factor_name")["ic_20d"].transform(
        lambda s: s.rolling(window=MA60_WINDOW, min_periods=MA60_MIN_PERIODS).mean()
    )
    out["ic_ma20_new"] = out["ic_ma20_new"].round(DB_PRECISION)
    out["ic_ma60_new"] = out["ic_ma60_new"].round(DB_PRECISION)
    return out


def _to_nullable(v: float | None) -> float | None:
    """NaN → None (DB NULL). 铁律 29."""
    if v is None or pd.isna(v):
        return None
    return float(v)


def diff_updates(computed: pd.DataFrame) -> list[tuple[str, date, float | None, float | None]]:
    """对比 new vs current → 仅返回需 UPDATE 的行 (幂等).

    输入需含 ic_ma20/ic_ma60 (当前值) + ic_ma20_new/ic_ma60_new (计算值).
    Skip: 两列都 NaN 或两列都相等 (精度 DB_PRECISION 内).
    """
    updates: list[tuple[str, date, float | None, float | None]] = []
    if computed.empty:
        return updates

    for row in computed.itertuples(index=False):
        new20 = _to_nullable(row.ic_ma20_new)
        new60 = _to_nullable(row.ic_ma60_new)
        cur20 = _to_nullable(row.ic_ma20)
        cur60 = _to_nullable(row.ic_ma60)

        # 两列都 NaN 且现值都 NULL → skip (常见: rolling 尾部前几行 min_periods 未满)
        if new20 is None and new60 is None and cur20 is None and cur60 is None:
            continue

        # 完全相等 (考虑 None == None, float == float 精度已 round 到 6) → skip
        if new20 == cur20 and new60 == cur60:
            continue

        updates.append((row.factor_name, row.trade_date, new20, new60))
    return updates


def apply_updates(
    conn: psycopg2.extensions.connection,
    updates: list[tuple[str, date, float | None, float | None]],
) -> int:
    """批量 UPDATE factor_ic_history. 调用方 commit (铁律 32).

    SQL 仅 SET ic_ma20/ic_ma60 两列, 不触 ic_5d/10d/20d/ic_abs_5d/decay_level.
    """
    if not updates:
        return 0
    sql = """
        UPDATE factor_ic_history AS f
        SET ic_ma20 = v.ic_ma20::numeric, ic_ma60 = v.ic_ma60::numeric
        FROM (VALUES %s) AS v(factor_name, trade_date, ic_ma20, ic_ma60)
        WHERE f.factor_name = v.factor_name
          AND f.trade_date = v.trade_date::date
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(cur, sql, updates, page_size=BATCH_SIZE)
        return cur.rowcount


def compute_and_update(
    conn: psycopg2.extensions.connection,
    factors: list[str] | None,
    all_factors: bool,
    dry_run: bool,
) -> dict:
    """核心: 加载 ic_20d → rolling → diff → UPDATE.

    Returns: {processed_factors, total_ic20d_rows, planned_updates, applied_updates,
              elapsed_sec, factor_summary}
    """
    t0 = time.time()
    target_factors = _fetch_target_factors(conn, factors, all_factors)
    logger.info("[ic_rolling] 目标 factors: %d", len(target_factors))
    if not target_factors:
        logger.warning("[ic_rolling] 无目标 factor, 退出")
        return {
            "processed_factors": 0,
            "total_ic20d_rows": 0,
            "planned_updates": 0,
            "applied_updates": 0,
            "elapsed_sec": 0.0,
            "factor_summary": [],
        }

    df = _load_ic_20d(conn, target_factors)
    logger.info(
        "[ic_rolling] 加载 %d rows across %d factors (有 ic_20d)",
        len(df),
        df["factor_name"].nunique() if not df.empty else 0,
    )

    computed = compute_rolling(df)
    updates = diff_updates(computed)
    logger.info("[ic_rolling] planned updates: %d 行 (幂等 diff 后)", len(updates))

    # per-factor summary
    summary: list[dict] = []
    if not computed.empty:
        grouped = computed.groupby("factor_name")
        updates_by_factor: dict[str, int] = {}
        for u in updates:
            updates_by_factor[u[0]] = updates_by_factor.get(u[0], 0) + 1
        for fname, g in grouped:
            latest = g.iloc[-1]
            summary.append(
                {
                    "factor": fname,
                    "rows": len(g),
                    "latest_ma20": _to_nullable(latest["ic_ma20_new"]),
                    "latest_ma60": _to_nullable(latest["ic_ma60_new"]),
                    "updates": updates_by_factor.get(fname, 0),
                }
            )

    applied = 0
    if dry_run:
        logger.info("[ic_rolling] [DRY-RUN] 跳过 UPDATE, 本应修改 %d 行", len(updates))
    else:
        applied = apply_updates(conn, updates)
        logger.info("[ic_rolling] applied %d 行 UPDATE", applied)

    elapsed = time.time() - t0
    logger.info(
        "[ic_rolling] 完成: %d factors / %d rows / %d updates / %.1fs",
        len(target_factors),
        len(df),
        applied if not dry_run else len(updates),
        elapsed,
    )
    return {
        "processed_factors": len(target_factors),
        "total_ic20d_rows": len(df),
        "planned_updates": len(updates),
        "applied_updates": applied,
        "elapsed_sec": elapsed,
        "factor_summary": summary,
    }


def main() -> int:
    _configure_logging()

    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--factors", type=str, help="逗号分隔 factor 列表 (覆盖 registry)")
    group.add_argument(
        "--core", action="store_true", help=f"仅 {len(CORE_FACTORS)} CORE: {CORE_FACTORS}"
    )
    group.add_argument(
        "--all-factors",
        action="store_true",
        help="所有 factor_ic_history 中有 ic_20d 的 factors (含 retired)",
    )
    parser.add_argument("--dry-run", action="store_true", help="不写 DB, 仅报告")
    parser.add_argument("--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    factors: list[str] | None = None
    if args.core:
        factors = list(CORE_FACTORS)
    elif args.factors:
        factors = [f.strip() for f in args.factors.split(",") if f.strip()]

    conn = get_sync_conn()
    try:
        result = compute_and_update(
            conn,
            factors=factors,
            all_factors=args.all_factors,
            dry_run=args.dry_run,
        )
        if not args.dry_run and result["applied_updates"] > 0:
            conn.commit()
            logger.info("[ic_rolling] commit %d 行", result["applied_updates"])
        logger.info("结果: %s", result)
        return 0
    except Exception:
        conn.rollback()
        logger.exception("[ic_rolling] 执行失败, rollback")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
