"""因子生命周期自动状态转换 — Phase 3 MVP A (DEV_AI_EVOLUTION V2.1 §3.1).

读取 factor_ic_history 的 ic_ma20/ic_ma60 → 调用 engines.factor_lifecycle 纯规则 →
UPDATE factor_registry.status + 发布 qm:ai:monitoring 事件.

L1-auto 转换:
  active  ↔  warning   (|IC_MA20|/|IC_MA60| < 0.8 / ≥ 0.8)
  warning →  critical  (ratio < 0.5 持续 20 天)

L2 需人确认 (本脚本不执行):
  critical → retired

用法:
    python scripts/factor_lifecycle_monitor.py              # 正常执行
    python scripts/factor_lifecycle_monitor.py --dry-run    # 不写 DB/不发事件
    python scripts/factor_lifecycle_monitor.py --factor turnover_mean_20  # 指定因子

铁律 23/24: 独立可执行, 单 MVP.
铁律 32: Service 不 commit → 本脚本 (orchestration) 负责 commit.
铁律 33: 异常 fail-loud (发现层报告, 不 silent swallow).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# 铁律 10b shadow fix: append 而非 insert(0) 避免 backend/platform/ shadow stdlib
# platform (参考 PR #67 pt_daily_summary 8 天 silent-fail 根因).
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BACKEND_DIR / ".env")

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_DIR / "factor_lifecycle.log", encoding="utf-8"),
        logging.StreamHandler(sys.stderr),
    ],
    force=True,
)
logger = logging.getLogger("factor_lifecycle")

from engines.factor_lifecycle import (  # noqa: E402
    CRITICAL_RATIO,
    TransitionDecision,
    count_days_below_critical,
    evaluate_transition,
)

STREAM_NAME = "qm:ai:monitoring"
EVENT_TYPE = "factor_status_transition"
PERSISTENCE_LOOKBACK_DAYS = 30  # 回溯窗口 (大于持续性阈值 20 天)


def _get_conn():
    from app.services.db import get_sync_conn

    return get_sync_conn()


def _load_registry_factors(conn, factor_filter: str | None = None) -> list[dict]:
    """加载 factor_registry 中非 retired 的因子 (name, status, updated_at)."""
    sql = """
        SELECT name, status, updated_at
        FROM factor_registry
        WHERE status != 'retired'
    """
    params: tuple = ()
    if factor_filter:
        sql += " AND name = %s"
        params = (factor_filter,)
    sql += " ORDER BY name"

    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def _load_ic_tail(conn, factor_name: str, lookback_days: int) -> list[dict]:
    """加载因子最近 N 个有 ic_ma20/ic_ma60 的记录 (按 trade_date 升序)."""
    sql = """
        SELECT trade_date, ic_ma20, ic_ma60
        FROM factor_ic_history
        WHERE factor_name = %s
          AND ic_ma20 IS NOT NULL
          AND ic_ma60 IS NOT NULL
        ORDER BY trade_date DESC
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (factor_name, lookback_days))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
    rows.reverse()  # 升序
    return rows


def _compute_decision(
    factor_name: str, current_status: str, tail: list[dict]
) -> TransitionDecision | None:
    """从 IC 尾部序列计算转换决策."""
    if not tail:
        return None
    latest = tail[-1]
    ic_ma20 = float(latest["ic_ma20"]) if latest["ic_ma20"] is not None else None
    ic_ma60 = float(latest["ic_ma60"]) if latest["ic_ma60"] is not None else None

    # 持续性: 最近 N 天中连续 |ma20|/|ma60| < CRITICAL_RATIO 的天数
    ratios: list[float] = []
    for r in tail:
        m20, m60 = r["ic_ma20"], r["ic_ma60"]
        if m20 is None or m60 is None or abs(float(m60)) < 1e-6:
            ratios.append(1.0)  # 无意义 → 记为高 ratio 不触发
        else:
            ratios.append(abs(float(m20)) / abs(float(m60)))
    days_below = count_days_below_critical(ratios, lookback_days=PERSISTENCE_LOOKBACK_DAYS)

    return evaluate_transition(
        factor_name=factor_name,
        current_status=current_status,
        ic_ma20=ic_ma20,
        ic_ma60=ic_ma60,
        days_below_critical=days_below,
    )


def _apply_transition(conn, decision: TransitionDecision) -> None:
    """写入 factor_registry + 发事件. 调用方负责 commit."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE factor_registry
               SET status = %s, updated_at = NOW()
               WHERE name = %s""",
            (decision.to_status, decision.factor_name),
        )
        if cur.rowcount != 1:
            raise RuntimeError(
                f"UPDATE factor_registry affected {cur.rowcount} rows for {decision.factor_name}"
            )


def _publish_event(decision: TransitionDecision) -> None:
    """发布 qm:ai:monitoring 事件 (铁律 33: publish 失败 warning 不阻塞)."""
    from app.core.stream_bus import get_stream_bus

    payload = {
        "event_type": EVENT_TYPE,
        "factor_name": decision.factor_name,
        "from_status": decision.from_status,
        "to_status": decision.to_status,
        "reason": decision.reason,
        "ic_ma20": decision.ic_ma20,
        "ic_ma60": decision.ic_ma60,
        "ratio": decision.ratio,
    }
    bus = get_stream_bus()
    msg_id = bus.publish_sync(STREAM_NAME, payload, source="factor_lifecycle_monitor")
    if msg_id:
        logger.info("  published %s: %s", STREAM_NAME, msg_id)
    else:
        logger.warning("  publish to %s failed (non-blocking)", STREAM_NAME)


def run(dry_run: bool = False, factor_filter: str | None = None) -> dict:
    """主执行逻辑."""
    logger.info("=" * 60)
    logger.info(
        "[Lifecycle] 开始 (dry_run=%s, filter=%s, critical_ratio=%s)",
        dry_run,
        factor_filter,
        CRITICAL_RATIO,
    )

    conn = _get_conn()
    transitions: list[TransitionDecision] = []
    checked = 0
    no_data = 0

    try:
        factors = _load_registry_factors(conn, factor_filter)
        logger.info("[Lifecycle] 待检查因子: %d", len(factors))

        for f in factors:
            name, status = f["name"], f["status"]
            tail = _load_ic_tail(conn, name, PERSISTENCE_LOOKBACK_DAYS)
            if not tail:
                no_data += 1
                continue
            checked += 1

            decision = _compute_decision(name, status, tail)
            if decision is None:
                continue

            logger.info(
                "  %s: %s → %s (%s)",
                decision.factor_name,
                decision.from_status,
                decision.to_status,
                decision.reason,
            )
            transitions.append(decision)

            if not dry_run:
                _apply_transition(conn, decision)
                _publish_event(decision)

        if not dry_run and transitions:
            conn.commit()
            logger.info("[Lifecycle] commit %d transitions", len(transitions))
        elif dry_run and transitions:
            logger.info("[DRY-RUN] 跳过 commit, %d 转换未落库", len(transitions))

    except Exception:
        conn.rollback()
        logger.exception("[Lifecycle] 执行失败, rollback")
        raise
    finally:
        conn.close()

    logger.info(
        "[Lifecycle] 完成: 检查=%d, 无数据=%d, 转换=%d",
        checked,
        no_data,
        len(transitions),
    )
    return {
        "checked": checked,
        "no_data": no_data,
        "transitions": [
            {
                "factor": d.factor_name,
                "from": d.from_status,
                "to": d.to_status,
                "reason": d.reason,
                "ratio": d.ratio,
            }
            for d in transitions
        ],
    }


def main():
    parser = argparse.ArgumentParser(description="因子生命周期自动状态转换 (Phase 3 MVP A)")
    parser.add_argument("--dry-run", action="store_true", help="不写 DB/不发事件")
    parser.add_argument("--factor", type=str, default=None, help="仅检查指定因子")
    args = parser.parse_args()

    result = run(dry_run=args.dry_run, factor_filter=args.factor)
    logger.info("结果: %s", result)


if __name__ == "__main__":
    main()
