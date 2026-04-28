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

    # MVP 3.5 Follow-up A 历史回放 (跨 PR follow-up Session 43, 2026-04-28):
    python scripts/factor_lifecycle_monitor.py --replay-from 2026-01-01 --weeks 12 \
        --report-out logs/lifecycle_replay.json

铁律 23/24: 独立可执行, 单 MVP.
铁律 32: Service 不 commit → 本脚本 (orchestration) 负责 commit.
铁律 33: 异常 fail-loud (发现层报告, 不 silent swallow).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
# 铁律 10b shadow fix: append 而非 insert(0) 避免 backend/platform/ shadow stdlib
# platform (参考 PR #67 pt_daily_summary 8 天 silent-fail 根因).
if str(BACKEND_DIR) not in sys.path:
    sys.path.append(str(BACKEND_DIR))
# MVP 3.5 Follow-up A (Session 43 2026-04-28): qm_platform.backtest.memory_registry
# 用 `backend.qm_platform._types` prefix, 需 PROJECT_ROOT 在 path. CLI 直跑
# (`python scripts/factor_lifecycle_monitor.py`) sys.path[0] 是 SCRIPT_DIR, 缺
# PROJECT_ROOT. Celery Beat 路径 setup 不同, append 兜底 CLI 模式.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

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
    CompositeMode,
    DualPathComparison,
    TransitionDecision,
    build_lifecycle_context,
    compare_paths,
    compute_composite_decision,
    count_days_below_critical,
    default_lifecycle_pipeline,
    evaluate_transition,
    extract_failed_gate_names,
)

STREAM_NAME = "qm:ai:monitoring"
EVENT_TYPE = "factor_status_transition"
DUAL_PATH_EVENT_TYPE = "factor_lifecycle_dual_path_mismatch"
PERSISTENCE_LOOKBACK_DAYS = 30  # 回溯窗口 (大于持续性阈值 20 天)
IC_SERIES_LOOKBACK_DAYS = 60  # 新路径 G1 t-stat 取最近 60 日 ic_20d 序列


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


def _load_ic_tail(
    conn,
    factor_name: str,
    lookback_days: int,
    snapshot_date: date | None = None,
) -> list[dict]:
    """加载因子最近 N 个有 ic_ma20/ic_ma60 的记录 (按 trade_date 升序).

    Args:
      snapshot_date: None → 今天为锚点 (生产 Beat 用法).
        非 None → trade_date <= snapshot_date 为锚点 (历史回放, MVP 3.5 Follow-up A).
    """
    if snapshot_date is None:
        sql = """
            SELECT trade_date, ic_ma20, ic_ma60
            FROM factor_ic_history
            WHERE factor_name = %s
              AND ic_ma20 IS NOT NULL
              AND ic_ma60 IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT %s
        """
        params: tuple = (factor_name, lookback_days)
    else:
        sql = """
            SELECT trade_date, ic_ma20, ic_ma60
            FROM factor_ic_history
            WHERE factor_name = %s
              AND trade_date <= %s
              AND ic_ma20 IS NOT NULL
              AND ic_ma60 IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT %s
        """
        params = (factor_name, snapshot_date, lookback_days)
    with conn.cursor() as cur:
        cur.execute(sql, params)
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
    """写入 factor_registry + 发事件. 调用方负责 commit.

    PR #124 reviewer P2 fix: SELECT FOR UPDATE 防并发 lost-update.
    场景 — Beat weekly 跑期间 manual `--factor X` 同时跑, 两 process 都读 status='active'
    都计算 →warning 还可接受 (idempotent), 但 active→warning 与 warning→critical 同时跑
    会 lost-update (后写覆盖前写). 加 FOR UPDATE 串行化, 第二 process 等第一 commit 后再读.
    """
    with conn.cursor() as cur:
        # SELECT FOR UPDATE 锁该因子行直至本 tx commit/rollback
        cur.execute(
            "SELECT status FROM factor_registry WHERE name = %s FOR UPDATE",
            (decision.factor_name,),
        )
        if cur.fetchone() is None:
            raise RuntimeError(f"factor {decision.factor_name} 不存在 (FOR UPDATE 锁失败)")
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


# ============================================================================
# MVP 3.5 batch 2 (Session 42) — 新路径 PlatformEvaluationPipeline 接入
# ============================================================================


def _load_ic_series(
    conn,
    factor_name: str,
    lookback_days: int,
    snapshot_date: date | None = None,
):
    """加载因子最近 N 天的 ic_20d 时间序列 (G1 t-stat 用).

    Args:
      snapshot_date: None → 今天为锚点. 非 None → trade_date <= snapshot_date 为锚点
        (历史回放, MVP 3.5 Follow-up A).

    Returns:
      np.ndarray (升序), 或 None 若无数据. 注: 类型注解略以避 module-level np import
      (engines/qm_platform 已统一 lazy numpy).
    """
    import numpy as np

    if snapshot_date is None:
        sql = """
            SELECT trade_date, ic_20d
            FROM factor_ic_history
            WHERE factor_name = %s
              AND ic_20d IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT %s
        """
        params: tuple = (factor_name, lookback_days)
    else:
        sql = """
            SELECT trade_date, ic_20d
            FROM factor_ic_history
            WHERE factor_name = %s
              AND trade_date <= %s
              AND ic_20d IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT %s
        """
        params = (factor_name, snapshot_date, lookback_days)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    if not rows:
        return None
    rows.reverse()  # 升序
    return np.asarray([float(r[1]) for r in rows], dtype=np.float64)


def _load_factor_meta(conn, factor_name: str):
    """加载因子注册表元信息 → FactorMeta (G10 hypothesis 用).

    PR #124 reviewer P1 fix: 用 cur.description 字典访问 (与 _load_registry_factors /
    _load_ic_tail 一致 pattern), 避免 row[N] positional 索引在 schema 演进时 silently 漂.

    Returns:
      FactorMeta or None.
    """
    from qm_platform.factor.interface import FactorMeta, FactorStatus

    sql = """
        SELECT id, name, category, direction, expression, code_content, hypothesis,
               source, lookback_days, status, pool, gate_ic, gate_ir, gate_mono,
               gate_t, ic_decay_ratio, created_at, updated_at
        FROM factor_registry
        WHERE name = %s
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, (factor_name,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d[0] for d in cur.description]
    rec = dict(zip(cols, row, strict=True))

    try:
        status_val = (
            FactorStatus(rec["status"]) if rec.get("status") else FactorStatus.CANDIDATE
        )
    except ValueError:
        status_val = FactorStatus.CANDIDATE

    def _opt_float(key: str) -> float | None:
        v = rec.get(key)
        return float(v) if v is not None else None

    return FactorMeta(
        factor_id=rec["id"],
        name=rec["name"],
        category=rec.get("category") or "unknown",
        direction=int(rec["direction"]) if rec.get("direction") is not None else 1,
        expression=rec.get("expression"),
        code_content=rec.get("code_content"),
        hypothesis=rec.get("hypothesis"),
        source=rec.get("source") or "manual",
        lookback_days=rec.get("lookback_days"),
        status=status_val,
        pool=rec.get("pool") or "CANDIDATE",
        gate_ic=_opt_float("gate_ic"),
        gate_ir=_opt_float("gate_ir"),
        gate_mono=_opt_float("gate_mono"),
        gate_t=_opt_float("gate_t"),
        ic_decay_ratio=_opt_float("ic_decay_ratio"),
        created_at=str(rec["created_at"]) if rec.get("created_at") is not None else "",
        updated_at=str(rec["updated_at"]) if rec.get("updated_at") is not None else "",
    )


def _publish_dual_path_mismatch(comparison: DualPathComparison) -> None:
    """mismatch 时发事件 qm:ai:monitoring (新路径仅 log, 不阻塞决策)."""
    from app.core.stream_bus import get_stream_bus

    payload = {
        "event_type": DUAL_PATH_EVENT_TYPE,
        "factor_name": comparison.factor_name,
        "old_label": comparison.old_label,
        "new_label": comparison.new_label,
        "new_decision_value": comparison.new_decision_value,
        "mismatch_summary": comparison.mismatch_summary,
        "old_decision": (
            {
                "from_status": comparison.old_decision.from_status,
                "to_status": comparison.old_decision.to_status,
                "reason": comparison.old_decision.reason,
            }
            if comparison.old_decision is not None
            else None
        ),
    }
    bus = get_stream_bus()
    msg_id = bus.publish_sync(STREAM_NAME, payload, source="factor_lifecycle_monitor")
    if msg_id:
        logger.info("  [dual-path] published mismatch %s: %s", STREAM_NAME, msg_id)
    else:
        logger.warning("  [dual-path] publish to %s failed (non-blocking)", STREAM_NAME)


def _evaluate_new_path(
    conn,
    factor_name: str,
    old_decision: TransitionDecision | None,
) -> DualPathComparison | None:
    """新路径评估单因子 + 比对老路径 (batch 2 双路径 4 周观察期).

    新路径仅 log 决策权威仍在老路径. 缺数据 / 异常 fail-soft (返 None, 不影响老路径).

    Returns:
      DualPathComparison or None (新路径数据不全跳过).
    """
    try:
        ic_series = _load_ic_series(conn, factor_name, IC_SERIES_LOOKBACK_DAYS)
        if ic_series is None or ic_series.size < 30:
            # G1 需 ≥ 30 样本, 缺则跳过 (不算 mismatch)
            return None
        factor_meta = _load_factor_meta(conn, factor_name)
        ctx = build_lifecycle_context(
            factor_name,
            ic_series=ic_series,
            factor_meta=factor_meta,
        )
        pipeline = default_lifecycle_pipeline(context_loader=lambda _name: ctx)
        report = pipeline.evaluate_full(factor_name)
        return compare_paths(factor_name, old_decision, report)
    except Exception as e:  # noqa: BLE001 — 新路径 fail-soft, 不影响老路径决策
        logger.warning(
            "  [dual-path] %s 评估异常 %s: %s (fail-soft, 老路径继续)",
            factor_name,
            type(e).__name__,
            e,
        )
        return None


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


def run(
    dry_run: bool = False,
    factor_filter: str | None = None,
    compare: bool = False,
) -> dict:
    """主执行逻辑.

    Args:
      dry_run: True 不写 DB / 不发事件.
      factor_filter: 仅检查指定因子.
      compare: True 启用 batch 2 新路径双路径比对 (4 周观察期, 老路径仍权威).
    """
    logger.info("=" * 60)
    logger.info(
        "[Lifecycle] 开始 (dry_run=%s, filter=%s, compare=%s, critical_ratio=%s)",
        dry_run,
        factor_filter,
        compare,
        CRITICAL_RATIO,
    )

    conn = _get_conn()
    transitions: list[TransitionDecision] = []
    comparisons: list[DualPathComparison] = []
    mismatches: list[DualPathComparison] = []
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

            # batch 2 新路径双路径比对 (在老路径决策后, 不影响老路径权威)
            comparison: DualPathComparison | None = None
            if compare:
                comparison = _evaluate_new_path(conn, name, decision)
                if comparison is not None:
                    comparisons.append(comparison)
                    if comparison.consistent:
                        logger.info(
                            "  [dual-path] %s: consistent (%s)",
                            name,
                            comparison.old_label,
                        )
                    else:
                        logger.warning(
                            "  [dual-path] %s: MISMATCH %s",
                            name,
                            comparison.mismatch_summary,
                        )
                        mismatches.append(comparison)
                        if not dry_run:
                            _publish_dual_path_mismatch(comparison)

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

    summary = (
        f"[Lifecycle] 完成: 检查={checked}, 无数据={no_data}, 转换={len(transitions)}"
    )
    if compare:
        summary += (
            f", dual-path 已比对={len(comparisons)}, mismatch={len(mismatches)}"
        )
    logger.info(summary)
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
        "dual_path_compared": len(comparisons),
        "dual_path_mismatches": [
            {
                "factor": c.factor_name,
                "old": c.old_label,
                "new": c.new_label,
                "summary": c.mismatch_summary,
            }
            for c in mismatches
        ],
    }


# ============================================================================
# MVP 3.5 Follow-up A (Session 43, 2026-04-28) — 历史回放加速 4 周观察期
# ============================================================================
#
# 设计意图:
#   - 不等 4 周生产观察 (Friday 19:00 weekly), 用 factor_ic_history 历史数据 N 周
#     回放双路径 (老 evaluate_transition / 新 PlatformEvaluationPipeline G1+G10)
#   - 输出 mismatch_rate / by_label_matrix / per_factor_breakdown / recommendation
#   - mismatch < 5% AND 无 P1 反向 mismatch (老 demote / 新 keep) → 推荐 SUNSET
#   - 否则推荐 DEFER (留生产观察期 + 重审 rule alignment)
#
# 限制:
#   - factor_registry.status 是当前 state, 无 history. 回放固定 current_status='active'
#     (老/新路径同输入, 比对 rule 一致性 vs 历史复现). 文档化为已知缺口.
#   - factor_meta.hypothesis 取当前快照 (变更频率低, 影响 G10 边际)
#   - 无 days_below_critical 持续性回放 (active→warning 即可 demote, warning→critical
#     需 20 天连续, 回放 active starting 状态下不会 cascade)


def _generate_replay_fridays(start_date: date, weeks: int) -> list[date]:
    """生成回放快照日 (Friday) 列表, 从 start_date 起向后 weeks 周, clamped to today.

    Friday 选择对齐 Beat schedule (factor-lifecycle Beat 周五 19:00 触发).
    """
    if weeks <= 0:
        raise ValueError(f"weeks 必须 > 0, got {weeks}")
    fridays: list[date] = []
    today = date.today()
    d = start_date
    # Advance to first Friday on or after start_date
    while d.weekday() != 4:  # Mon=0, Fri=4
        d += timedelta(days=1)
    for _ in range(weeks):
        if d > today:
            break
        fridays.append(d)
        d += timedelta(days=7)
    return fridays


def _replay_one_factor(
    conn,
    factor_name: str,
    snapshot: date,
    factor_meta=None,
) -> dict | None:
    """单 (factor, snapshot) 回放双路径决策, 返 comparison dict 或 None 若数据不足.

    Args:
      conn: psycopg2 connection.
      factor_name: 因子名.
      snapshot: 回放快照日 (factor_ic_history 取 trade_date <= snapshot DATE compare —
        DDL `factor_ic_history.trade_date` 是 DATE 列, psycopg2 直传 Python date 对象,
        无 timezone 漂移. 若未来改 timestamptz 需重审 (铁律 41).
      factor_meta: 预加载 FactorMeta (db reviewer P2 fix 2026-04-28 PR #127 — 避 N+1).
        None 时 fallback 到 _load_factor_meta(conn, name) 旧行为 (保单测兼容).

    Returns:
      dict {snapshot, factor, old_label, new_label, new_decision_value, consistent,
             old_to_status, ic_ma20, ic_ma60} 或 None 若 ic_ma 数据不足 / G1 样本 < 30.
    """
    tail = _load_ic_tail(conn, factor_name, PERSISTENCE_LOOKBACK_DAYS, snapshot_date=snapshot)
    if not tail:
        return None
    ic_series = _load_ic_series(
        conn, factor_name, IC_SERIES_LOOKBACK_DAYS, snapshot_date=snapshot
    )
    if ic_series is None or ic_series.size < 30:
        return None

    # 回放固定 current_status='active' (回放上下文不可信 historical status).
    # P2.3 reviewer 2026-04-28 PR #128 文档化: factor_registry.status 是当前快照,
    # 历史状态不可重建. 复合模式 composite_demote_counts 因此低估非-active 因子的
    # demote (warning/critical 状态下 G1 fail 不会触发新合成 — 由老路径主导持续性升级).
    # 实证 g1-only=550 / strict=576 是 active-only baseline 的下界, 真实生产含 warning
    # 因子 G1 fail 通过老路径 warning→critical 升级路径仍能 demote.
    old_decision = _compute_decision(factor_name, "active", tail)

    if factor_meta is None:
        factor_meta = _load_factor_meta(conn, factor_name)
    ctx = build_lifecycle_context(
        factor_name, ic_series=ic_series, factor_meta=factor_meta
    )
    pipeline = default_lifecycle_pipeline(context_loader=lambda _n: ctx)
    report = pipeline.evaluate_full(factor_name)
    comparison = compare_paths(factor_name, old_decision, report)

    # MVP 3.5 Follow-up B (Session 43): 计算 3 mode 复合决策 demote 标志 (分析用)
    ic_ma20_val = float(tail[-1]["ic_ma20"]) if tail[-1]["ic_ma20"] is not None else None
    ic_ma60_val = float(tail[-1]["ic_ma60"]) if tail[-1]["ic_ma60"] is not None else None
    failed_gates = extract_failed_gate_names(report)
    composite_demote: dict[str, bool] = {}
    for mode in (CompositeMode.OFF, CompositeMode.G1_ONLY, CompositeMode.STRICT):
        decision = compute_composite_decision(
            factor_name=factor_name,
            current_status="active",
            old_decision=old_decision,
            new_report=report,
            mode=mode,
            ic_ma20=ic_ma20_val,
            ic_ma60=ic_ma60_val,
        )
        # demote = decision 存在 AND to_status != active
        composite_demote[mode.value] = (
            decision is not None and decision.to_status != "active"
        )

    return {
        "snapshot": snapshot.isoformat(),
        "factor": factor_name,
        "old_label": comparison.old_label,
        "new_label": comparison.new_label,
        "new_decision_value": comparison.new_decision_value,
        "consistent": comparison.consistent,
        "old_to_status": (
            comparison.old_decision.to_status
            if comparison.old_decision is not None
            else None
        ),
        "ic_ma20": ic_ma20_val,
        "ic_ma60": ic_ma60_val,
        # Follow-up B 复合决策 demote 标志 (per mode)
        "failed_gates": sorted(failed_gates),
        "composite_demote_off": composite_demote["off"],
        "composite_demote_g1_only": composite_demote["g1-only"],
        "composite_demote_strict": composite_demote["strict"],
    }


def replay(
    start_date: date,
    weeks: int = 12,
    factor_filter: str | None = None,
    report_out: str | None = None,
    sunset_mismatch_threshold: float = 0.05,
) -> dict:
    """历史回放老/新路径 N 周, 输出 mismatch 统计 + sunset 推荐.

    Args:
      start_date: 回放起始日 (会前进到首个 Friday).
      weeks: 回放周数, 默认 12 (4 周观察期 3 倍 statistical power).
      factor_filter: 仅回放指定因子 (None = 全因子).
      report_out: JSON 报告路径, None 则不写文件.
      sunset_mismatch_threshold: SUNSET 推荐阈值, 默认 0.05 (5%).

    Returns:
      summary dict + details list.
    """
    logger.info("=" * 60)
    logger.info(
        "[Replay] 开始 start=%s weeks=%d factor_filter=%s threshold=%.2f%%",
        start_date,
        weeks,
        factor_filter,
        sunset_mismatch_threshold * 100,
    )

    fridays = _generate_replay_fridays(start_date, weeks)
    if not fridays:
        logger.warning("[Replay] 无可用 Friday 快照 (start > today?)")
        return {"summary": {"total_evaluations": 0, "recommendation": "NO_DATA"}}

    logger.info(
        "[Replay] %d Friday 快照: %s ~ %s",
        len(fridays),
        fridays[0],
        fridays[-1],
    )

    conn = _get_conn()
    try:
        # reviewer (python+db) P2/P3 2026-04-28 PR #127:
        # - readonly=True: 显式 read-only 防意外 write (replay 是纯查询)
        # - autocommit=True: 防 ~10K queries 累积 1 个 long-running implicit tx 阻塞 vacuum
        # - statement_timeout 5s: 单 query slow path 兜底 (铁律 43 spirit, 即便 CLI 非 schtask)
        try:
            conn.set_session(readonly=True, autocommit=True)
        except Exception:  # noqa: BLE001 — mock conn 可能不支持 set_session
            logger.debug("conn.set_session 失败, mock 或老 driver, fail-soft")
        try:
            with conn.cursor() as _cur_init:
                _cur_init.execute("SET LOCAL statement_timeout = 5000")
        except Exception:  # noqa: BLE001 — autocommit=True 下 SET LOCAL 可能不持久, mock 也不支持
            logger.debug("SET statement_timeout 失败, fail-soft")

        factors = _load_registry_factors(conn, factor_filter)
        factor_names = [f["name"] for f in factors]
        logger.info("[Replay] %d 因子参与回放", len(factor_names))

        # db reviewer P2 fix: 预加载 factor_meta 字典 (286 因子 1 次 SELECT 替代 286×12 次)
        factor_meta_cache: dict[str, object] = {}
        for fname in factor_names:
            meta = _load_factor_meta(conn, fname)
            if meta is not None:
                factor_meta_cache[fname] = meta
        logger.info("[Replay] 预加载 factor_meta cache: %d entries", len(factor_meta_cache))

        details: list[dict] = []
        skipped_no_data = 0
        consistent_count = 0
        mismatch_count = 0
        # 6-cell label matrix + "other" bucket (python reviewer HIGH fix 2026-04-28 PR #127):
        # 防 compare_paths 未来扩 label 范围 (e.g. 'critical') 静默漏入 schema 外 key.
        EXPECTED_LABELS = {"keep", "demote", "unknown"}  # noqa: N806
        label_matrix: dict[str, int] = {
            "keep_keep": 0, "keep_demote": 0, "keep_unknown": 0,
            "demote_keep": 0, "demote_demote": 0, "demote_unknown": 0,
            "other": 0,
        }
        per_factor_mismatch: dict[str, int] = {}
        # MVP 3.5 Follow-up B: 各 composite mode 累计 demote count (分析用)
        composite_demote_counts: dict[str, int] = {
            "off": 0, "g1-only": 0, "strict": 0,
        }

        for snapshot in fridays:
            for fname in factor_names:
                row = _replay_one_factor(
                    conn,
                    fname,
                    snapshot,
                    factor_meta=factor_meta_cache.get(fname),
                )
                if row is None:
                    skipped_no_data += 1
                    continue

                # HIGH fix: validate labels in expected set 防 silently 漏入未知 key
                old_label = row["old_label"]
                new_label = row["new_label"]
                if old_label in EXPECTED_LABELS and new_label in EXPECTED_LABELS:
                    key = f"{old_label}_{new_label}"
                    label_matrix[key] += 1
                else:
                    label_matrix["other"] += 1
                    logger.warning(
                        "[Replay] unexpected label combo old=%s new=%s on %s/%s "
                        "(routed to 'other' bucket, may indicate compare_paths schema drift)",
                        old_label,
                        new_label,
                        fname,
                        snapshot,
                    )

                if row["consistent"]:
                    consistent_count += 1
                else:
                    mismatch_count += 1
                    per_factor_mismatch[fname] = per_factor_mismatch.get(fname, 0) + 1

                # Follow-up B: 累计 composite demote per mode (分析 OR 复合规则触发率)
                if row.get("composite_demote_off"):
                    composite_demote_counts["off"] += 1
                if row.get("composite_demote_g1_only"):
                    composite_demote_counts["g1-only"] += 1
                if row.get("composite_demote_strict"):
                    composite_demote_counts["strict"] += 1

                details.append(row)
    finally:
        conn.close()

    total = consistent_count + mismatch_count
    mismatch_rate = mismatch_count / total if total > 0 else 0.0

    # P1 反向 mismatch: 老 demote (factor 衰减) 但新 keep (significant) — 老路径捕获新路径漏掉的 decay
    p1_old_demote_new_keep = label_matrix.get("demote_keep", 0)
    # P2 正向 mismatch: 老 keep 但新 demote — 新路径更严, 可接受
    p2_old_keep_new_demote = label_matrix.get("keep_demote", 0)
    # 不可下定论: unknown — 数据不足, 不算 mismatch 实质
    unknown_count = (
        label_matrix.get("keep_unknown", 0) + label_matrix.get("demote_unknown", 0)
    )

    if total == 0:
        recommendation = "NO_DATA"
        reasoning = "0 evaluations completed (data missing or factor_filter too narrow)"
    elif mismatch_rate < sunset_mismatch_threshold and p1_old_demote_new_keep == 0:
        recommendation = "SUNSET"
        reasoning = (
            f"mismatch_rate={mismatch_rate:.2%} < {sunset_mismatch_threshold:.2%} "
            f"threshold AND 0 P1 reverse mismatches (老 demote / 新 keep). "
            f"新路径 G1+G10 可独立替代老 evaluate_transition."
        )
    elif p1_old_demote_new_keep > 0:
        recommendation = "DEFER"
        reasoning = (
            f"P1 反向 mismatch={p1_old_demote_new_keep} (老 demote/新 keep) — 新路径漏掉 "
            f"decay 信号. 不能 sunset 老路径, 考虑改 AND/OR 复合规则 (老 OR 新 → demote)."
        )
    else:
        recommendation = "DEFER"
        reasoning = (
            f"mismatch_rate={mismatch_rate:.2%} >= {sunset_mismatch_threshold:.2%} "
            f"threshold. 留生产观察 + 复审 rule alignment."
        )

    summary = {
        "replay_window": {
            "start": start_date.isoformat(),
            "weeks": weeks,
            "fridays_count": len(fridays),
            "fridays": [f.isoformat() for f in fridays],
        },
        "factors_evaluated_count": len(factor_names),
        "total_evaluations": total,
        "skipped_no_data": skipped_no_data,
        "consistent_count": consistent_count,
        "mismatch_count": mismatch_count,
        "mismatch_rate": round(mismatch_rate, 6),
        "by_label_matrix": label_matrix,
        "per_factor_mismatch": per_factor_mismatch,
        "p1_reverse_mismatch": p1_old_demote_new_keep,
        "p2_forward_mismatch": p2_old_keep_new_demote,
        "unknown_count": unknown_count,
        "sunset_threshold": sunset_mismatch_threshold,
        "recommendation": recommendation,
        "reasoning": reasoning,
        # MVP 3.5 Follow-up B: OR 复合决策 demote 总数 per mode
        # off = 仅老路径 (生产 baseline) / g1-only = 老 OR G1 fail / strict = 老 OR (G1|G10)
        # 用于 Phase 2 wire-up 前评估 demote 增长合理性
        "composite_demote_counts": composite_demote_counts,
    }

    logger.info("[Replay] 完成: total=%d mismatch=%d (%.2f%%) → %s",
                total, mismatch_count, mismatch_rate * 100, recommendation)
    logger.info("[Replay] reasoning: %s", reasoning)

    result = {"summary": summary, "details": details}

    if report_out:
        out_path = Path(report_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        logger.info("[Replay] JSON 报告写入 %s (%d details rows)", out_path, len(details))

    return result


def main():
    parser = argparse.ArgumentParser(description="因子生命周期自动状态转换 (Phase 3 MVP A)")
    parser.add_argument("--dry-run", action="store_true", help="不写 DB/不发事件")
    parser.add_argument("--factor", type=str, default=None, help="仅检查指定因子")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="启用 batch 2 新路径双路径比对 (PlatformEvaluationPipeline G1+G10), "
        "老路径决策权威, 新路径仅 log + mismatch 告警",
    )
    # MVP 3.5 Follow-up A (Session 43, 2026-04-28) — 历史回放
    parser.add_argument(
        "--replay-from",
        type=str,
        default=None,
        help="历史回放起始日期 YYYY-MM-DD. 设置后跳过常规 run, 走 replay 模式.",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=12,
        help="回放周数, 默认 12 (4 周生产观察期 3 倍 statistical power)",
    )
    parser.add_argument(
        "--report-out",
        type=str,
        default=None,
        help="JSON 报告输出路径 (replay 模式专用)",
    )
    parser.add_argument(
        "--sunset-threshold",
        type=float,
        default=0.05,
        help="SUNSET 推荐 mismatch_rate 阈值, 默认 0.05",
    )
    args = parser.parse_args()

    if args.replay_from:
        try:
            start = date.fromisoformat(args.replay_from)
        except ValueError as e:
            parser.error(f"--replay-from 格式无效 (需 YYYY-MM-DD): {e}")
        # python reviewer P2 fix 2026-04-28 PR #127: --weeks <= 0 用 parser.error 包装
        # (而非让 _generate_replay_fridays raw raise ValueError 给 stderr 不友好 traceback)
        if args.weeks <= 0:
            parser.error(f"--weeks 必须 >= 1, got {args.weeks}")
        if not 0.0 <= args.sunset_threshold <= 1.0:
            parser.error(
                f"--sunset-threshold 必须在 [0.0, 1.0], got {args.sunset_threshold}"
            )
        result = replay(
            start_date=start,
            weeks=args.weeks,
            factor_filter=args.factor,
            report_out=args.report_out,
            sunset_mismatch_threshold=args.sunset_threshold,
        )
        logger.info("Replay summary: %s", result["summary"])
        return

    result = run(
        dry_run=args.dry_run,
        factor_filter=args.factor,
        compare=args.compare,
    )
    logger.info("结果: %s", result)


if __name__ == "__main__":
    main()
