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
import contextlib
import logging
import os
import sys
import time
import traceback
from collections import Counter
from datetime import date, datetime
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

# Session 26 LL-068 铁律 43: PG 硬超时常量 (reviewer python-P2 采纳, 对齐 pt_watchdog
# / data_quality_check). 60s 足够 daily rolling MA query (秒级完成).
STATEMENT_TIMEOUT_MS = 60_000


def _configure_logging() -> None:
    """延迟 logging 配置 (避免 pytest collect 阶段副作用, 对齐 compute_daily_ic 模式).

    Session 26 LL-068 扩散: FileHandler delay=True 防 Windows 多 process zombie
    文件锁 (data_quality_check 4-23 0-log 事故同类防御).
    """
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_DIR / "compute_ic_rolling.log", encoding="utf-8", delay=True),
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


def _to_nullable(v: object) -> float | None:
    """NaN / None / pd.NA → None (DB NULL). 铁律 29.

    Accepts: float / int / numpy.float64 / Decimal / pd.NA / None.
    reviewer P1 (python-reviewer) 采纳: 旧注解 `float | None` 误导静态分析认为调用方
    已转 float. 改 `object` 反映真实契约 — 调用方可传任意数值类型, helper 内部统一
    `pd.isna` 判 null + `float()` 转换.
    """
    if v is None or pd.isna(v):
        return None
    return float(v)  # type: ignore[arg-type]


def _approx_eq(a: float | None, b: float | None) -> bool:
    """精度 DB_PRECISION (6 位小数) 内相等. 幂等比较专用.

    reviewer P2 (python-reviewer) 采纳: `new == cur` 浮点 == 理论上有精度陷阱 (rolling
    mean 可能产生 round(6) 不能完全消除的噪声, 导致每次重跑都判不等产生无效 UPDATE).
    用 round(DB_PRECISION) 归一后再比.
    """
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return round(a, DB_PRECISION) == round(b, DB_PRECISION)


def diff_updates(computed: pd.DataFrame) -> list[tuple[str, date, float | None, float | None]]:
    """对比 new vs current → 仅返回需 UPDATE 的行 (幂等).

    输入需含 ic_ma20/ic_ma60 (当前值) + ic_ma20_new/ic_ma60_new (计算值).
    Skip 条件:
    - 两列都 NaN 且现值都 NULL (常见: rolling 尾部 min_periods 未满)
    - 两列值在 DB_PRECISION 精度内相等 (幂等, 避免 round 噪声触发无效 UPDATE)
    """
    updates: list[tuple[str, date, float | None, float | None]] = []
    if computed.empty:
        return updates

    for row in computed.itertuples(index=False):
        new20 = _to_nullable(row.ic_ma20_new)
        new60 = _to_nullable(row.ic_ma60_new)
        cur20 = _to_nullable(row.ic_ma20)
        cur60 = _to_nullable(row.ic_ma60)

        if new20 is None and new60 is None and cur20 is None and cur60 is None:
            continue

        if _approx_eq(new20, cur20) and _approx_eq(new60, cur60):
            continue

        updates.append((row.factor_name, row.trade_date, new20, new60))
    return updates


def apply_updates(
    conn: psycopg2.extensions.connection,
    updates: list[tuple[str, date, float | None, float | None]],
) -> int:
    """批量 UPDATE factor_ic_history. 调用方 commit (铁律 32).

    SQL 仅 SET ic_ma20/ic_ma60 两列, 不触 ic_5d/10d/20d/ic_abs_5d/decay_level.

    reviewer P1 (code+python) 采纳: psycopg2.extras.execute_values 在 multi-batch
    (len(updates) > page_size) 场景下 cur.rowcount 只返回最后 batch 的数量
    (官方文档明确). 这里**手动分批**累积 total, 确保返回真实总行数.

    LL-034 注: SQL cast `::numeric` / `::date` 在 raw psycopg2 VALUES 子句中是标准
    PostgreSQL 语法, LL-034 禁令范围是 SQLAlchemy text() 场景, 本脚本不受影响.
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
    total = 0
    with conn.cursor() as cur:
        for i in range(0, len(updates), BATCH_SIZE):
            batch = updates[i : i + BATCH_SIZE]
            psycopg2.extras.execute_values(cur, sql, batch, page_size=BATCH_SIZE)
            if cur.rowcount > 0:
                total += cur.rowcount
    return total


def compute_and_update(
    conn: psycopg2.extensions.connection,
    factors: list[str] | None,
    all_factors: bool,
    dry_run: bool,
) -> dict:
    """核心: 加载 ic_20d → rolling → diff → UPDATE.

    Args:
        factors: **None → 走 factor_registry 查询 active/warning**.
                 **空 list `[]` → 无因子不处理** (不降级到 registry 查询).
                 非空 list → 精确使用该列表 (覆盖 registry).
        all_factors: True → 读 factor_ic_history 所有有 ic_20d 的 factors (含 retired).
                     仅在 factors is None 时生效.
        dry_run: True 不入库, 仅报告 planned_updates.

    Returns: {processed_factors, total_ic20d_rows, planned_updates, applied_updates,
              elapsed_sec, factor_summary}

    reviewer P2 (python-reviewer) 采纳: `factors=None` 与 `factors=[]` 语义区分显式化.
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

    # per-factor summary (reviewer P3 采纳: Counter 替代手动字典 +1 累积)
    summary: list[dict] = []
    if not computed.empty:
        updates_by_factor = Counter(u[0] for u in updates)
        for fname, g in computed.groupby("factor_name"):
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


def _run(args: argparse.Namespace) -> int:
    """主流程 (铁律 43-d: 顶层 try/except 由 main 包裹, reviewer code-MED-1 采纳)."""
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    factors: list[str] | None = None
    if args.core:
        factors = list(CORE_FACTORS)
    elif args.factors:
        factors = [f.strip() for f in args.factors.split(",") if f.strip()]

    conn = get_sync_conn()
    try:
        # LL-068 扩散 (铁律 43-a): session-level statement_timeout, 防 cold-cache / lock hang.
        # reviewer code-LOW-2 采纳: psycopg2 autocommit=False 默认, SET 在当前 implicit
        # transaction 中, 后续 queries 共享同 transaction 所以 timeout 实际生效 (session GUC).
        with conn.cursor() as cur_timeout:
            cur_timeout.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
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
        # reviewer P2 (code-reviewer) 采纳: align compute_daily_ic.py exit code —
        # 无 target factor 时返回 1, 便于 schtask 监控发现异常 (registry 被清空 /
        # DB 连接异常导致空查询等).
        return 0 if result["processed_factors"] > 0 else 1
    except Exception:
        conn.rollback()
        logger.exception("[ic_rolling] 执行失败, rollback")
        raise
    finally:
        conn.close()


def main() -> int:
    """Script entry (铁律 43-c boot probe + 43-d 顶层 try/except → exit(2)).

    reviewer code-MED-1 采纳: 原 main() 只 raise 不保证 exit 2 (uncaught raise
    通常 exit 1) + 无 `FATAL:` stderr 结构化输出, 违反铁律 43-d 契约.
    拆 `_run` + `main` wrapper 对齐 compute_daily_ic / pt_watchdog.
    """
    # Fail-loud boot 探针 (铁律 43-c)
    print(
        f"[compute_ic_rolling] boot {datetime.now().isoformat()} pid={os.getpid()}",
        flush=True,
        file=sys.stderr,
    )
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

    try:
        return _run(args)
    except Exception as e:
        msg = f"[compute_ic_rolling] FATAL: {type(e).__name__}: {e}"
        print(msg, flush=True, file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        # silent_ok: 最外层兜底, logger 可能未初始化成功 (铁律 33-d)
        with contextlib.suppress(Exception):
            logger.critical(msg, exc_info=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
