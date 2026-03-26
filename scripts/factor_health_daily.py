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
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from app.config import settings
from app.services.notification_service import send_alert
from app.services.price_utils import _get_sync_conn
from engines.factor_analyzer import FactorAnalyzer
from engines.signal_engine import PAPER_TRADING_CONFIG

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
        factor_count = cur.fetchone()[0]
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
            logger.info(f"  总体状态: HEALTHY")
        elif overall == "warning":
            logger.warning(f"  总体状态: WARNING")
        elif overall == "critical":
            logger.error(f"  总体状态: CRITICAL")
        logger.info("=" * 60)

        # ── 发送钉钉告警（warning/critical时）──
        if overall in ("warning", "critical"):
            alert_level = "P0" if overall == "critical" else "P1"
            # 构建告警摘要
            problem_factors = []
            for fname in ACTIVE_FACTORS:
                fh = health["factors"].get(fname, {})
                fstatus = fh.get("status", "unknown")
                if fstatus in ("warning", "critical"):
                    daily_ic = fh.get("daily_ic")
                    ic_str = f"{daily_ic:.4f}" if daily_ic is not None else "N/A"
                    problem_factors.append(f"{fname}({fstatus}, IC={ic_str})")
            alert_msg = (
                f"因子健康状态: {overall.upper()}\n"
                f"异常因子: {', '.join(problem_factors)}\n"
                f"高相关对: {len(high_corr_pairs)}对"
            )
            try:
                send_alert(
                    alert_level, f"因子健康{overall} {trade_date}", alert_msg,
                    settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn,
                )
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
                logger.info(f"[DB] 因子健康日报已写入 scheduler_task_log 表")
            except Exception as e:
                logger.warning(f"[DB] 写入scheduler_task_log失败: {e}")
                try:
                    conn.rollback()
                except Exception:
                    pass

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
