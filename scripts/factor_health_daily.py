#!/usr/bin/env python3
"""因子健康日报 — 每日自动生成因子健康简报。

基于factor_analyzer.py的daily_health_check()，计算:
1. 最近一个交易日5因子的5日超额IC
2. 20日滚动IC趋势（上升/衰减/稳定）
3. 因子间截面相关性矩阵（5x5）
4. 输出格式化日志 + 写入health_checks表

用法:
    # 指定日期
    python scripts/factor_health_daily.py --date 2026-03-21

    # 默认当天
    python scripts/factor_health_daily.py

    # 不写DB
    python scripts/factor_health_daily.py --date 2026-03-21 --dry-run

可纳入crontab在signal阶段后自动运行（T日 17:30）。
"""

import argparse
import contextlib
import json
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Platform SDK 顶层 import (batch 3.x pattern, 防 import-in-try NameError).
import functools  # noqa: E402

import numpy as np
import pandas as pd
from engines.factor_analyzer import FactorAnalyzer
from engines.factor_decay import (
    DecayLevel,
    check_all_factors_decay,
)
from engines.signal_engine import PAPER_TRADING_CONFIG
from qm_platform.observability import AlertDispatchError  # noqa: E402

from app.config import settings
from app.services.notification_service import send_alert as _legacy_send_alert
from app.services.price_utils import _get_sync_conn

# ── 日志配置 ──
LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "factor_health_daily.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("factor_health_daily")


# ── 当前Paper Trading使用的因子列表 ──
ACTIVE_FACTORS = PAPER_TRADING_CONFIG.factor_names


def classify_ic_trend(rolling_ic: list[float | None]) -> str:
    """判断IC趋势：上升/衰减/稳定。

    方法：对非None的IC序列做线性回归，看斜率。
    - slope > 0.001: 上升
    - slope < -0.001: 衰减
    - 否则: 稳定

    Args:
        rolling_ic: 20日滚动IC列表。

    Returns:
        趋势标签字符串。
    """
    valid = [(i, v) for i, v in enumerate(rolling_ic) if v is not None]
    if len(valid) < 5:
        return "数据不足"

    x = np.array([v[0] for v in valid], dtype=float)
    y = np.array([v[1] for v in valid], dtype=float)

    if len(x) < 2:
        return "数据不足"

    slope = np.polyfit(x, y, 1)[0]

    if slope > 0.001:
        return "上升"
    elif slope < -0.001:
        return "衰减"
    else:
        return "稳定"


def format_correlation_matrix(corr_df: pd.DataFrame) -> str:
    """格式化相关矩阵为可读字符串。

    Args:
        corr_df: 因子间相关矩阵DataFrame。

    Returns:
        格式化的字符串表格。
    """
    if corr_df.empty:
        return "  (无数据)"

    # 缩短因子名
    short_names = {}
    for col in corr_df.columns:
        parts = col.split("_")
        if len(parts) >= 2:
            short_names[col] = parts[0][:4] + "_" + parts[-1][:4]
        else:
            short_names[col] = col[:8]

    lines = []
    header = "         " + "  ".join(f"{short_names.get(c, c):>8s}" for c in corr_df.columns)
    lines.append(header)

    for idx in corr_df.index:
        row_vals = []
        for col in corr_df.columns:
            v = corr_df.loc[idx, col]
            if pd.isna(v):
                row_vals.append("     N/A")
            elif idx == col:
                row_vals.append("    1.00")
            else:
                row_vals.append(f"{v:8.3f}")
        row_label = short_names.get(idx, idx)
        lines.append(f"{row_label:>8s}  " + "  ".join(row_vals))

    return "\n".join(lines)


def check_and_update_lifecycle(
    conn,
    trade_date: date,
    dry_run: bool = False,
) -> list[dict]:
    """检查并自动迁移因子生命周期状态。

    迁移规则（基于factor_ic_history表，DDL状态: candidate/active/warning/critical/retired）:
    - active  → warning: 近3个月均IC < 历史均IC × 0.5
    - warning → active:  近3个月均IC ≥ 历史均IC × 0.5

    所有其他状态（candidate / critical / retired）不参与自动迁移。

    Args:
        conn: psycopg2同步连接。
        trade_date: 当前检查日期。
        dry_run: 不写入DB，仅返回迁移列表。

    Returns:
        迁移记录列表，每项含 factor_name / old_status / new_status / reason。
    """
    recent_days = 63   # ~3个月交易日
    degrade_ratio = 0.5
    min_history_days = 20  # 历史均IC至少需要这么多样本

    recent_cutoff = trade_date - timedelta(days=recent_days)

    cur = conn.cursor()

    # 取所有 active/warning 因子（DDL状态机：active↔warning自动迁移）
    cur.execute(
        """SELECT name, status
           FROM factor_registry
           WHERE status IN ('active', 'warning')
           ORDER BY name"""
    )
    candidates = cur.fetchall()

    if not candidates:
        logger.info("[Lifecycle] 无active/warning因子，跳过生命周期检查")
        return []

    transitions: list[dict] = []

    for factor_name, current_status in candidates:
        # 历史均IC（截止到近3个月之前，至少MIN_HISTORY_DAYS条）
        cur.execute(
            """SELECT AVG(ABS(ic_1d)), COUNT(*)
               FROM factor_ic_history
               WHERE factor_name = %s
                 AND trade_date < %s""",
            (factor_name, recent_cutoff),
        )
        hist_row = cur.fetchone()
        # SQL AVG 返回 Decimal, 显式 cast 避免与 float degrade_ratio 混合运算 TypeError
        hist_abs_ic: float | None = float(hist_row[0]) if hist_row and hist_row[0] is not None else None
        hist_count: int = hist_row[1] if hist_row and hist_row[1] is not None else 0

        if hist_abs_ic is None or hist_count < min_history_days:
            logger.debug(
                f"[Lifecycle] {factor_name}: 历史数据不足({hist_count}条)，跳过迁移判断"
            )
            continue

        # 近3个月均IC
        cur.execute(
            """SELECT AVG(ABS(ic_1d)), COUNT(*)
               FROM factor_ic_history
               WHERE factor_name = %s
                 AND trade_date >= %s
                 AND trade_date <= %s""",
            (factor_name, recent_cutoff, trade_date),
        )
        row = cur.fetchone()
        recent_abs_ic: float | None = float(row[0]) if row and row[0] is not None else None
        recent_count: int = row[1] or 0

        if recent_abs_ic is None or recent_count < 5:
            logger.debug(
                f"[Lifecycle] {factor_name}: 近3个月数据不足({recent_count}条)，跳过"
            )
            continue

        threshold = hist_abs_ic * degrade_ratio
        ratio = recent_abs_ic / hist_abs_ic if hist_abs_ic > 0 else 0.0

        logger.debug(
            f"[Lifecycle] {factor_name}: 历史|IC|={hist_abs_ic:.4f}, "
            f"近3月|IC|={recent_abs_ic:.4f}, 比率={ratio:.2f}, 阈值={threshold:.4f}"
        )

        new_status: str | None = None
        reason = ""

        if current_status == "active" and recent_abs_ic < threshold:
            new_status = "warning"
            reason = (
                f"近3月|IC|={recent_abs_ic:.4f} < 历史|IC|×0.5={threshold:.4f}"
                f" (比率={ratio:.2f})"
            )
        elif current_status == "warning" and recent_abs_ic >= threshold:
            new_status = "active"
            reason = (
                f"近3月|IC|={recent_abs_ic:.4f} ≥ 历史|IC|×0.5={threshold:.4f}"
                f" (比率={ratio:.2f}, 已恢复)"
            )

        if new_status is None:
            continue

        transitions.append(
            {
                "factor_name": factor_name,
                "old_status": current_status,
                "new_status": new_status,
                "reason": reason,
                "recent_abs_ic": recent_abs_ic,
                "hist_abs_ic": hist_abs_ic,
            }
        )

        if not dry_run:
            try:
                cur.execute(
                    """UPDATE factor_registry
                       SET status = %s,
                           updated_at = NOW()
                       WHERE name = %s""",
                    (new_status, factor_name),
                )
                conn.commit()
                logger.info(
                    f"[Lifecycle] {factor_name}: {current_status} → {new_status} | {reason}"
                )
            except Exception as e:
                logger.warning(f"[Lifecycle] {factor_name} 状态更新失败: {e}")
                with contextlib.suppress(Exception):
                    conn.rollback()
        else:
            logger.info(
                f"[Lifecycle][DRY-RUN] {factor_name}: {current_status} → {new_status} | {reason}"
            )

    return transitions


# ─────────────────────────── MVP 4.1 batch 3.5 Observability dispatch ───────────────────────────


@functools.lru_cache(maxsize=1)
def _get_rules_engine():
    """Cached AlertRulesEngine load (batch 3.x pattern)."""
    from qm_platform.observability import AlertRulesEngine

    project_root = Path(__file__).resolve().parent.parent
    try:
        return AlertRulesEngine.from_yaml(project_root / "configs" / "alert_rules.yaml")
    except Exception as e:  # noqa: BLE001
        logger.warning("[Observability] AlertRulesEngine load failed: %s, fallback", e)
        return None


def _send_alert_via_platform_sdk(
    level: str, title: str, content: str, trade_date: date
) -> None:
    """走 PlatformAlertRouter + AlertRulesEngine."""
    from datetime import UTC
    from datetime import datetime as _datetime

    from qm_platform._types import Severity
    from qm_platform.observability import Alert, get_alert_router

    severity_value = level.lower() if level.lower() in {"p0", "p1", "p2", "info"} else "p1"
    severity = Severity(severity_value)
    trade_date_str = str(trade_date)

    alert = Alert(
        title=f"[{level}] {title}",
        severity=severity,
        source="factor_health_daily",
        details={"trade_date": trade_date_str, "content": content},
        trade_date=trade_date_str,
        timestamp_utc=_datetime.now(UTC).isoformat(),
    )

    engine = _get_rules_engine()
    rule = engine.match(alert) if engine else None
    if rule:
        dedup_key = rule.format_dedup_key(alert)
        suppress_minutes = rule.suppress_minutes
    else:
        dedup_key = f"factor_health:summary:{trade_date_str}"
        suppress_minutes = None

    router = get_alert_router()
    try:
        result = router.fire(
            alert,
            dedup_key=dedup_key,
            suppress_minutes=suppress_minutes,
        )
        logger.info(
            "[Observability] AlertRouter.fire result=%s key=%s severity=%s",
            result, dedup_key, severity_value,
        )
    except AlertDispatchError as e:
        logger.error("[Observability] AlertRouter sink_failed: %s", e)
        raise


def _send_alert_unified(
    level: str, title: str, content: str, trade_date: date, conn
) -> None:
    """dispatch SDK vs legacy notification_service.send_alert.

    settings.OBSERVABILITY_USE_PLATFORM_SDK 控制路径切换. AlertDispatchError 必传播.
    """
    if settings.OBSERVABILITY_USE_PLATFORM_SDK:
        _send_alert_via_platform_sdk(level, title, content, trade_date)
    else:
        _legacy_send_alert(
            level, title, content,
            settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn,
        )


def run_factor_health_daily(trade_date: date, dry_run: bool = False) -> dict:
    """运行因子健康日报。

    Args:
        trade_date: 检查日期。
        dry_run: 不写入DB。

    Returns:
        健康检查结果字典。
    """
    conn = _get_sync_conn()

    try:
        # 确认是交易日
        cur = conn.cursor()
        cur.execute(
            """SELECT is_trading_day FROM trading_calendar
               WHERE trade_date = %s AND market = 'astock'""",
            (trade_date,),
        )
        row = cur.fetchone()
        if not row or not row[0]:
            logger.info(f"{trade_date} 非交易日，跳过因子健康检查")
            return {"status": "skipped", "reason": "non_trading_day"}

        # 确认因子数据已计算
        cur.execute(
            """SELECT COUNT(DISTINCT factor_name)
               FROM factor_values
               WHERE trade_date = %s""",
            (trade_date,),
        )
        factor_count_row = cur.fetchone()
        factor_count = factor_count_row[0] if factor_count_row else 0
        if factor_count == 0:
            logger.warning(f"{trade_date} 因子数据尚未计算，跳过")
            return {"status": "skipped", "reason": "no_factor_data"}

        logger.info(f"{'='*60}")
        logger.info(f"[因子健康日报] {trade_date}")
        logger.info(f"检查因子: {', '.join(ACTIVE_FACTORS)}")
        logger.info(f"{'='*60}")

        # 使用FactorAnalyzer执行健康检查
        analyzer = FactorAnalyzer(conn)
        health = analyzer.daily_health_check(ACTIVE_FACTORS, trade_date)

        # ── 格式化输出 ──

        # 1. 单因子IC + 趋势
        logger.info("")
        logger.info("=" * 60)
        logger.info("  因子IC及趋势")
        logger.info("=" * 60)
        logger.info(f"{'因子':<25s} {'当日IC':>8s} {'20日均IC':>10s} {'趋势':>6s} {'状态':>8s}")
        logger.info("-" * 60)

        for fname in ACTIVE_FACTORS:
            fh = health["factors"].get(fname, {})
            daily_ic = fh.get("daily_ic")
            rolling = fh.get("rolling_ic_20d", [])
            status = fh.get("status", "unknown")

            # 20日均IC
            valid_rolling = [v for v in rolling if v is not None]
            mean_ic_20d = np.mean(valid_rolling) if valid_rolling else None

            # 趋势
            trend = classify_ic_trend(rolling)

            # 格式化
            ic_str = f"{daily_ic:8.4f}" if daily_ic is not None else "     N/A"
            mean_str = f"{mean_ic_20d:10.4f}" if mean_ic_20d is not None else "       N/A"
            status_marker = ""
            if status == "critical":
                status_marker = " [!!!]"
            elif status == "warning":
                status_marker = " [!]"

            logger.info(f"{fname:<25s} {ic_str} {mean_str} {trend:>6s} {status}{status_marker}")

        # 2. 因子间截面相关矩阵
        logger.info("")
        logger.info("=" * 60)
        logger.info("  因子间截面Spearman相关矩阵")
        logger.info("=" * 60)

        corr_matrix = health.get("cross_correlation")
        high_corr_pairs = []
        if isinstance(corr_matrix, pd.DataFrame) and not corr_matrix.empty:
            # 只显示ACTIVE_FACTORS的子集
            active_in_corr = [f for f in ACTIVE_FACTORS if f in corr_matrix.columns]
            if active_in_corr:
                sub_corr = corr_matrix.loc[active_in_corr, active_in_corr]
                logger.info("\n" + format_correlation_matrix(sub_corr))

                # 标记高相关对（>0.7，CLAUDE.md：Spearman>0.7判定重复）
                high_corr_pairs = []
                for i, f1 in enumerate(active_in_corr):
                    for f2 in active_in_corr[i + 1:]:
                        val = sub_corr.loc[f1, f2]
                        if not pd.isna(val) and abs(val) > 0.7:
                            high_corr_pairs.append((f1, f2, val))

                if high_corr_pairs:
                    logger.warning("")
                    logger.warning("  高相关因子对 (|corr| > 0.7):")
                    for f1, f2, val in high_corr_pairs:
                        logger.warning(f"    {f1} <-> {f2}: {val:.3f}")
                else:
                    logger.info("\n  因子相关性正常，无高相关对")
        else:
            logger.info("  (无相关矩阵数据)")

        # 3. 总体状态
        logger.info("")
        logger.info("=" * 60)
        overall = health.get("overall_status", "unknown")
        if overall == "healthy":
            logger.info("  总体状态: HEALTHY")
        elif overall == "warning":
            logger.warning("  总体状态: WARNING")
        elif overall == "critical":
            logger.error("  总体状态: CRITICAL")
        logger.info("=" * 60)

        # ── 因子生命周期自动迁移 ──
        logger.info("")
        logger.info("=" * 60)
        logger.info("  因子生命周期检查")
        logger.info("=" * 60)
        try:
            transitions = check_and_update_lifecycle(conn, trade_date, dry_run=dry_run)
            if transitions:
                for t in transitions:
                    marker = "[DRY-RUN] " if dry_run else ""
                    logger.info(
                        f"  {marker}{t['factor_name']}: "
                        f"{t['old_status']} → {t['new_status']} | {t['reason']}"
                    )
                health["lifecycle_transitions"] = transitions
            else:
                logger.info("  无需状态迁移，所有因子状态正常")
                health["lifecycle_transitions"] = []
        except Exception as e:
            logger.warning(f"[Lifecycle] 生命周期检查失败: {e}")
            health["lifecycle_transitions"] = []

        # ── C3: 3级衰减检测（基于factor_ic_history的IC_MA20/IC_MA60）──
        logger.info("")
        logger.info("=" * 60)
        logger.info("  因子衰减3级检测 (L0/L1/L2/L3)")
        logger.info("=" * 60)
        try:
            # 从factor_ic_history加载每个因子的IC日频时序
            factor_ic_data = {}
            for fname in ACTIVE_FACTORS:
                ic_df = pd.read_sql(
                    """SELECT trade_date, ic_5d
                       FROM factor_ic_history
                       WHERE factor_name = %s
                       ORDER BY trade_date""",
                    conn,
                    params=(fname,),
                )
                if not ic_df.empty:
                    ic_series = ic_df.set_index("trade_date")["ic_5d"].dropna()
                    if not ic_series.empty:
                        factor_ic_data[fname] = ic_series

            if factor_ic_data:
                decay_results = check_all_factors_decay(factor_ic_data)
                health["decay_results"] = []
                for dr in decay_results:
                    level_marker = ""
                    if dr.decay_level == DecayLevel.L1:
                        level_marker = " [!]"
                        logger.warning(
                            "  %s: %s — %s%s",
                            dr.factor_name, dr.decay_level.value, dr.reason, level_marker,
                        )
                    elif dr.decay_level in (DecayLevel.L2, DecayLevel.L3):
                        level_marker = " [!!!]"
                        logger.error(
                            "  %s: %s — %s%s",
                            dr.factor_name, dr.decay_level.value, dr.reason, level_marker,
                        )
                    else:
                        logger.info(
                            "  %s: %s — %s",
                            dr.factor_name, dr.decay_level.value, dr.reason,
                        )
                    health["decay_results"].append({
                        "factor_name": dr.factor_name,
                        "decay_level": dr.decay_level.value,
                        "ic_ma20": dr.ic_ma20,
                        "ic_ma60": dr.ic_ma60,
                        "consecutive_low_days": dr.consecutive_low_days,
                        "weight_multiplier": dr.weight_multiplier,
                        "reason": dr.reason,
                    })

                    # 写入factor_ic_history.decay_level（非dry_run）
                    if not dry_run and dr.decay_level != DecayLevel.L0:
                        try:
                            cur = conn.cursor()
                            cur.execute(
                                """UPDATE factor_ic_history
                                   SET decay_level = %s
                                   WHERE factor_name = %s AND trade_date = %s""",
                                (dr.decay_level.value.lower(), dr.factor_name, trade_date),
                            )
                            conn.commit()
                        except Exception as e:
                            logger.warning(f"[Decay] 更新decay_level失败: {e}")
                            with contextlib.suppress(Exception):
                                conn.rollback()

                # 升级overall_status（L2/L3比existing lifecycle更严重）
                max_level = max(
                    (dr.decay_level for dr in decay_results),
                    default=DecayLevel.L0,
                    key=lambda x: ["L0", "L1", "L2", "L3"].index(x.value),
                )
                if max_level in (DecayLevel.L2, DecayLevel.L3):
                    overall = "critical"
                    health["overall_status"] = "critical"
                elif max_level == DecayLevel.L1 and overall == "healthy":
                    overall = "warning"
                    health["overall_status"] = "warning"
            else:
                logger.info("  无IC历史数据，跳过衰减检测")
                health["decay_results"] = []
        except Exception as e:
            logger.warning(f"[Decay] 衰减检测失败: {e}")
            health["decay_results"] = []

        # ── 发送钉钉告警（warning/critical时）──
        if overall in ("warning", "critical"):
            alert_level = "P0" if overall == "critical" else "P1"
            # 构建告警摘要 (2 源合并 + 去重: reviewer P1-1 采纳)
            problem_factors: list[str] = []
            seen_factors: set[str] = set()
            # 源 1: FactorAnalyzer.daily_health_check 逐因子 status
            for fname in ACTIVE_FACTORS:
                fh = health["factors"].get(fname, {})
                fstatus = fh.get("status", "unknown")
                if fstatus in ("warning", "critical"):
                    daily_ic = fh.get("daily_ic")
                    ic_str = f"{daily_ic:.4f}" if daily_ic is not None else "N/A"
                    problem_factors.append(f"{fname}({fstatus}, IC={ic_str})")
                    seen_factors.add(fname)
            # 源 2: check_all_factors_decay L1/L2/L3 (原漏, reviewer P1-2: ic_ma20 格式化)
            # reviewer P3-2: DecayLevel enum 比 hardcoded string (防未来 value 漂移)
            decay_values = {DecayLevel.L1.value, DecayLevel.L2.value, DecayLevel.L3.value}
            for dr_dict in health.get("decay_results", []):
                if dr_dict.get("decay_level") not in decay_values:
                    continue
                fname = dr_dict["factor_name"]
                if fname in seen_factors:
                    continue  # 已由源 1 记录, 避免重复
                ic_ma20_val = dr_dict.get("ic_ma20")
                ic_ma20_str = f"{ic_ma20_val:.4f}" if ic_ma20_val is not None else "N/A"
                problem_factors.append(
                    f"{fname}(decay_{dr_dict['decay_level']}, MA20={ic_ma20_str})"
                )
                seen_factors.add(fname)
            # reviewer P3-1 采纳: fallback 命中 → 逻辑 gap, logger.error 可追溯
            if not problem_factors:
                logger.error(
                    "[FactorHealth] overall=%s 但 problem_factors 空 — "
                    "源 1 (daily status) + 源 2 (decay L1/L2/L3) 均未产出, 逻辑 gap 待排查. "
                    "factors=%s, decay_results=%s",
                    overall,
                    list(health.get("factors", {}).keys()),
                    [d.get("factor_name") for d in health.get("decay_results", [])],
                )
            alert_msg = (
                f"因子健康状态: {overall.upper()}\n"
                f"异常因子: {', '.join(problem_factors) if problem_factors else '(无具体列表)'}\n"
                f"高相关对: {len(high_corr_pairs)}对"
            )
            # batch 3.5 dispatch (P1.1 模式: AlertDispatchError 单 catch)
            try:
                _send_alert_unified(
                    alert_level, f"因子健康{overall} {trade_date}", alert_msg,
                    trade_date, conn,
                )
            except AlertDispatchError as e:
                logger.error("[Observability] AlertDispatchError — 因子健康告警未送达: %s", e)
            except Exception as e:
                logger.warning(f"[DingTalk] 因子健康告警发送失败: {e}")

        # ── 写入health_checks表 ──
        if not dry_run:
            # 将结果序列化存入health_checks
            result_json = {
                "date": trade_date.isoformat(),
                "overall_status": overall,
                "factors": {},
            }
            for fname in ACTIVE_FACTORS:
                fh = health["factors"].get(fname, {})
                rolling = fh.get("rolling_ic_20d", [])
                valid_rolling = [v for v in rolling if v is not None]
                result_json["factors"][fname] = {
                    "daily_ic": fh.get("daily_ic"),
                    "mean_ic_20d": float(np.mean(valid_rolling)) if valid_rolling else None,
                    "trend": classify_ic_trend(rolling),
                    "coverage": fh.get("coverage"),
                    "status": fh.get("status", "unknown"),
                }

            # 存入scheduler_task_log表（通用日志表，支持result_json）
            try:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO scheduler_task_log
                       (task_name, market, schedule_time, start_time, status,
                        result_json)
                       VALUES (%s, 'astock', NOW(), NOW(), %s, %s)""",
                    (
                        "factor_health_daily",
                        overall,
                        json.dumps(result_json, ensure_ascii=False, default=str),
                    ),
                )
                conn.commit()
                logger.info("[DB] 因子健康日报已写入 scheduler_task_log 表")
            except Exception as e:
                logger.warning(f"[DB] 写入scheduler_task_log失败: {e}")
                with contextlib.suppress(Exception):
                    conn.rollback()

        return health

    except Exception as e:
        logger.error(f"因子健康日报异常: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "error": str(e)}
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="QuantMind 因子健康日报",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--date", type=str, help="日期 YYYY-MM-DD (默认今天)")
    parser.add_argument("--dry-run", action="store_true", help="不写DB")
    args = parser.parse_args()

    trade_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else date.today()
    )

    result = run_factor_health_daily(trade_date, dry_run=args.dry_run)

    overall = result.get("overall_status", result.get("status", "unknown"))
    if overall == "critical":
        sys.exit(2)  # 非零退出码供crontab检测
    elif overall == "error":
        sys.exit(1)


if __name__ == "__main__":
    main()
