#!/usr/bin/env python3
"""因子生命周期滚动IC监控脚本。

Sprint 1.5 — 因子生命周期管理基础设施。

功能:
  1. 从factor_values表读取最近12个月的因子值
  2. 计算每月截面Spearman Rank IC（vs 5日前瞻超额收益，相对沪深300）
  3. 更新factor_lifecycle表的rolling_ic_12m
  4. 执行状态转换逻辑:
     - active → warning:  滚动12月IC绝对值 < 入池IC的50%
     - warning → retired: 连续6月IC < 0
     - warning → monitoring: 滚动IC恢复到入池IC的70%以上
  5. 输出因子健康报告

用法:
    python scripts/monitor_factor_ic.py
    python scripts/monitor_factor_ic.py --dingtalk   # 发送钉钉通知
    python scripts/monitor_factor_ic.py --months 24  # 自定义滚动窗口
"""

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

# 项目路径
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.services.price_utils import _get_sync_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Active因子列表: 从PT配置动态读取 (铁律34 single source of truth)
try:
    from engines.signal_engine import PAPER_TRADING_CONFIG
    ACTIVE_FACTORS = list(PAPER_TRADING_CONFIG.factor_names)
except ImportError:
    # fallback: CORE3+dv_ttm (2026-04-12 WF PASS配置)
    ACTIVE_FACTORS = [
        "turnover_mean_20",
        "volatility_20",
        "bp_ratio",
        "dv_ttm",
    ]


# ============================================================
# 数据加载
# ============================================================

def get_conn():
    """获取psycopg2同步连接（读.env配置）。"""
    return _get_sync_conn()


def load_lifecycle(conn) -> pd.DataFrame:
    """加载factor_lifecycle表。"""
    sql = "SELECT * FROM factor_lifecycle ORDER BY factor_name"
    return pd.read_sql(sql, conn, parse_dates=["entry_date", "rolling_ic_updated",
                                                 "warning_date", "retired_date"])


def load_index_returns(conn, start_date: date) -> pd.Series:
    """加载沪深300日收益率。"""
    sql = """
    SELECT trade_date, close
    FROM index_daily
    WHERE index_code = '000300.SH' AND trade_date >= %s
    ORDER BY trade_date
    """
    df = pd.read_sql(sql, conn, params=(start_date,), parse_dates=["trade_date"])
    df = df.set_index("trade_date").sort_index()
    df["close"] = df["close"].astype(float)
    df["index_ret"] = df["close"].pct_change()
    return df["index_ret"]


def load_stock_returns(conn, start_date: date) -> pd.DataFrame:
    """加载个股日收益率（复权）。"""
    sql = """
    SELECT code, trade_date, close, adj_factor
    FROM klines_daily
    WHERE trade_date >= %s AND is_suspended = false
    ORDER BY code, trade_date
    """
    df = pd.read_sql(sql, conn, params=(start_date,), parse_dates=["trade_date"])
    df["close"] = df["close"].astype(float)
    df["adj_factor"] = df["adj_factor"].astype(float)
    df["adj_close"] = df["close"] * df["adj_factor"]
    df = df.sort_values(["code", "trade_date"])
    df["ret"] = df.groupby("code")["adj_close"].pct_change()
    return df[["code", "trade_date", "ret"]].dropna()


def load_factor_values(conn, factor_names: list[str], start_date: date) -> pd.DataFrame:
    """加载指定因子的zscore值。"""
    placeholders = ",".join(["%s"] * len(factor_names))
    sql = f"""
    SELECT code, trade_date, factor_name, zscore
    FROM factor_values
    WHERE factor_name IN ({placeholders})
      AND trade_date >= %s
      AND zscore IS NOT NULL
    ORDER BY trade_date, code
    """
    params = factor_names + [start_date]
    df = pd.read_sql(sql, conn, params=params, parse_dates=["trade_date"])
    df["zscore"] = df["zscore"].astype(float)
    return df


# ============================================================
# IC计算
# ============================================================

def compute_forward_excess_return(
    stock_ret_df: pd.DataFrame,
    index_ret_series: pd.Series,
    forward_days: int = 5,
) -> pd.DataFrame:
    """计算N日前瞻超额收益。

    Args:
        stock_ret_df: 个股日收益率 (code, trade_date, ret)
        index_ret_series: 沪深300日收益率
        forward_days: 前瞻天数

    Returns:
        DataFrame: (trade_date, code, fwd_excess_ret)
    """
    ret_wide = stock_ret_df.pivot(index="trade_date", columns="code", values="ret")
    index_ret_aligned = index_ret_series.reindex(ret_wide.index)

    # Forward cumulative return
    stock_fwd = (
        (1 + ret_wide)
        .rolling(forward_days)
        .apply(lambda x: x.prod(), raw=True)
        .shift(-forward_days)
        - 1
    )
    index_fwd = (
        (1 + index_ret_aligned)
        .rolling(forward_days)
        .apply(lambda x: x.prod(), raw=True)
        .shift(-forward_days)
        - 1
    )

    excess_ret = stock_fwd.subtract(index_fwd, axis=0)
    excess_long = excess_ret.stack().reset_index()
    excess_long.columns = ["trade_date", "code", "fwd_excess_ret"]
    return excess_long


def compute_daily_ic(
    factor_df: pd.DataFrame,
    excess_ret_df: pd.DataFrame,
    factor_name: str,
    min_stocks: int = 30,
) -> pd.Series:
    """计算某因子的每日截面Spearman Rank IC。

    Args:
        factor_df: 因子zscore (code, trade_date, factor_name, zscore)
        excess_ret_df: 前瞻超额收益 (trade_date, code, fwd_excess_ret)
        factor_name: 因子名
        min_stocks: 最小截面股票数

    Returns:
        pd.Series: index=trade_date, values=IC
    """
    f = factor_df[factor_df["factor_name"] == factor_name][
        ["code", "trade_date", "zscore"]
    ]
    merged = f.merge(excess_ret_df, on=["code", "trade_date"], how="inner").dropna()

    def _daily_ic(group: pd.DataFrame) -> float:
        if len(group) < min_stocks:
            return np.nan
        rho, _ = stats.spearmanr(group["zscore"], group["fwd_excess_ret"])
        return rho

    ic_series = merged.groupby("trade_date").apply(_daily_ic).dropna()
    ic_series.name = factor_name
    return ic_series


def compute_monthly_ic(daily_ic: pd.Series) -> pd.Series:
    """将日频IC聚合为月频IC（月内均值）。

    Args:
        daily_ic: 日频IC序列

    Returns:
        pd.Series: index=month (period), values=月均IC
    """
    monthly = daily_ic.groupby(daily_ic.index.to_period("M")).mean()
    return monthly


# ============================================================
# 状态转换逻辑
# ============================================================

def evaluate_transitions(
    lifecycle_df: pd.DataFrame,
    monthly_ic_dict: dict[str, pd.Series],
    today: date,
) -> list[dict]:
    """评估每个因子的状态转换。

    规则:
      - active → warning:  rolling_ic_12m绝对值 < entry_ic绝对值的50%
      - warning → retired: 连续6月IC < 0
      - warning → monitoring: rolling_ic恢复到entry_ic的70%以上
      - retired → candidate: 手动触发（不在此自动执行）

    Args:
        lifecycle_df: factor_lifecycle表内容
        monthly_ic_dict: 每个因子的月频IC序列
        today: 当前日期

    Returns:
        list[dict]: 状态变更记录
    """
    transitions = []

    for _, row in lifecycle_df.iterrows():
        fname = row["factor_name"]
        current_status = row["status"]
        entry_ic = float(row["entry_ic"]) if pd.notna(row["entry_ic"]) else None

        if fname not in monthly_ic_dict or entry_ic is None:
            continue

        monthly_ic = monthly_ic_dict[fname]
        if len(monthly_ic) < 3:
            logger.warning("Factor %s: insufficient monthly IC data (%d months), skipping.",
                           fname, len(monthly_ic))
            continue

        # 最近12个月的滚动IC均值
        rolling_ic_12m = float(monthly_ic.tail(12).mean())

        # 最近6个月的月IC
        recent_6m = monthly_ic.tail(6)

        if current_status == "active":
            # active → warning: 滚动IC绝对值 < 入池IC绝对值的50%
            if abs(rolling_ic_12m) < abs(entry_ic) * 0.50:
                transitions.append({
                    "factor_name": fname,
                    "from_status": "active",
                    "to_status": "warning",
                    "reason": (
                        f"Rolling 12m |IC|={abs(rolling_ic_12m):.4f} < "
                        f"50% of entry |IC|={abs(entry_ic) * 0.50:.4f}"
                    ),
                    "rolling_ic_12m": rolling_ic_12m,
                    "warning_date": today,
                })

        elif current_status == "warning":
            # warning → retired: 连续6月IC < 0
            if len(recent_6m) >= 6 and (recent_6m < 0).all():
                transitions.append({
                    "factor_name": fname,
                    "from_status": "warning",
                    "to_status": "retired",
                    "reason": "6 consecutive months IC < 0",
                    "rolling_ic_12m": rolling_ic_12m,
                    "retired_date": today,
                })
            # warning → monitoring: 滚动IC恢复到入池IC的70%以上
            elif abs(rolling_ic_12m) >= abs(entry_ic) * 0.70:
                transitions.append({
                    "factor_name": fname,
                    "from_status": "warning",
                    "to_status": "monitoring",
                    "reason": (
                        f"Rolling 12m |IC|={abs(rolling_ic_12m):.4f} >= "
                        f"70% of entry |IC|={abs(entry_ic) * 0.70:.4f}, recovered"
                    ),
                    "rolling_ic_12m": rolling_ic_12m,
                })

        elif current_status == "monitoring":
            # monitoring → warning: 与active相同条件
            if abs(rolling_ic_12m) < abs(entry_ic) * 0.50:
                transitions.append({
                    "factor_name": fname,
                    "from_status": "monitoring",
                    "to_status": "warning",
                    "reason": (
                        f"Rolling 12m |IC|={abs(rolling_ic_12m):.4f} < "
                        f"50% of entry |IC|={abs(entry_ic) * 0.50:.4f}"
                    ),
                    "rolling_ic_12m": rolling_ic_12m,
                    "warning_date": today,
                })

    return transitions


# ============================================================
# 数据库更新
# ============================================================

def update_lifecycle(
    conn,
    factor_name: str,
    rolling_ic_12m: float,
    today: date,
    new_status: str | None = None,
    warning_date: date | None = None,
    retired_date: date | None = None,
) -> None:
    """更新factor_lifecycle表。"""
    cur = conn.cursor()

    # 始终更新rolling_ic
    cur.execute("""
        UPDATE factor_lifecycle
        SET rolling_ic_12m = %s,
            rolling_ic_updated = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE factor_name = %s
    """, (rolling_ic_12m, today, factor_name))

    # 状态转换
    if new_status:
        updates = ["status = %s"]
        params = [new_status]
        if warning_date:
            updates.append("warning_date = %s")
            params.append(warning_date)
        if retired_date:
            updates.append("retired_date = %s")
            params.append(retired_date)
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(factor_name)

        sql = f"UPDATE factor_lifecycle SET {', '.join(updates)} WHERE factor_name = %s"
        cur.execute(sql, params)

    conn.commit()
    cur.close()


# ============================================================
# 报告生成
# ============================================================

def generate_report(
    lifecycle_df: pd.DataFrame,
    monthly_ic_dict: dict[str, pd.Series],
    transitions: list[dict],
) -> str:
    """生成因子健康报告文本。"""
    lines = []
    lines.append("=" * 60)
    lines.append("Factor Lifecycle Health Report")
    lines.append(f"Date: {date.today().isoformat()}")
    lines.append("=" * 60)

    lines.append("")
    lines.append("--- Factor Status Summary ---")
    lines.append(
        f"{'Factor':<25s} {'Status':<12s} {'Entry IC':>10s} "
        f"{'Roll IC 12m':>12s} {'IC Ratio':>10s} {'Health':>8s}"
    )
    lines.append("-" * 80)

    for _, row in lifecycle_df.iterrows():
        fname = row["factor_name"]
        status = row["status"]
        entry_ic = float(row["entry_ic"]) if pd.notna(row["entry_ic"]) else 0.0

        if fname in monthly_ic_dict and len(monthly_ic_dict[fname]) > 0:
            roll_ic = float(monthly_ic_dict[fname].tail(12).mean())
        else:
            roll_ic = float(row["rolling_ic_12m"]) if pd.notna(row["rolling_ic_12m"]) else 0.0

        ratio = abs(roll_ic) / abs(entry_ic) if abs(entry_ic) > 1e-08 else 0.0

        if ratio >= 0.70:
            health = "OK"
        elif ratio >= 0.50:
            health = "WATCH"
        else:
            health = "ALERT"

        lines.append(
            f"{fname:<25s} {status:<12s} {entry_ic:>+10.4f} "
            f"{roll_ic:>+12.4f} {ratio:>10.1%} {health:>8s}"
        )

    # Monthly IC trend (last 6 months)
    lines.append("")
    lines.append("--- Monthly IC Trend (last 6 months) ---")
    for fname in ACTIVE_FACTORS:
        if fname not in monthly_ic_dict:
            continue
        recent = monthly_ic_dict[fname].tail(6)
        trend_str = " | ".join(
            f"{p}: {v:+.4f}" for p, v in zip(recent.index.astype(str), recent.values, strict=False)
        )
        lines.append(f"  {fname}: {trend_str}")

    # Transitions
    if transitions:
        lines.append("")
        lines.append("--- Status Transitions ---")
        for t in transitions:
            lines.append(
                f"  {t['factor_name']}: {t['from_status']} -> {t['to_status']}"
            )
            lines.append(f"    Reason: {t['reason']}")
    else:
        lines.append("")
        lines.append("--- No status transitions triggered ---")

    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


# ============================================================
# 钉钉通知
# ============================================================

def send_dingtalk(report: str, transitions: list[dict]) -> None:
    """发送钉钉通知（需配置webhook）。"""
    try:
        import os
        import urllib.request

        from dotenv import load_dotenv

        env_path = Path(__file__).resolve().parent.parent / "backend" / ".env"
        load_dotenv(env_path)

        webhook_url = os.getenv("DINGTALK_WEBHOOK_URL")
        keyword = os.getenv("DINGTALK_KEYWORD", "xin")

        if not webhook_url:
            logger.warning("DINGTALK_WEBHOOK_URL not configured, skipping notification.")
            return

        # 构造消息
        if transitions:
            title = f"{keyword} Factor Alert: {len(transitions)} transition(s)"
        else:
            title = f"{keyword} Factor Health: All OK"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": f"### {title}\n\n```\n{report}\n```",
            },
        }

        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("errcode") == 0:
                logger.info("DingTalk notification sent successfully.")
            else:
                logger.warning("DingTalk API error: %s", result)

    except Exception as e:
        logger.error("Failed to send DingTalk notification: %s", e)


# ============================================================
# 主流程
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="Factor lifecycle rolling IC monitor")
    parser.add_argument("--months", type=int, default=12,
                        help="Rolling window in months (default: 12)")
    parser.add_argument("--dingtalk", action="store_true",
                        help="Send DingTalk notification")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute and report but do not update DB")
    args = parser.parse_args()

    today = date.today()
    # 多加3个月的数据缓冲（用于前瞻收益计算和热身期）
    lookback_months = args.months + 3
    start_date = today - timedelta(days=lookback_months * 31)

    conn = get_conn()
    try:
        # 1. 加载生命周期表
        logger.info("Loading factor_lifecycle table...")
        lifecycle_df = load_lifecycle(conn)
        factor_names = lifecycle_df["factor_name"].tolist()

        if not factor_names:
            logger.error("No factors in factor_lifecycle table. Run setup_factor_lifecycle.py first.")
            return

        logger.info("Tracking %d factors: %s", len(factor_names), factor_names)

        # 2. 加载行情数据
        logger.info("Loading index returns from %s...", start_date)
        index_ret = load_index_returns(conn, start_date)
        logger.info("  Index return records: %d", len(index_ret))

        logger.info("Loading stock returns from %s...", start_date)
        stock_ret = load_stock_returns(conn, start_date)
        logger.info("  Stock return records: %d", len(stock_ret))

        # 3. 计算5日前瞻超额收益
        logger.info("Computing 5-day forward excess returns...")
        excess_ret = compute_forward_excess_return(stock_ret, index_ret, forward_days=5)
        logger.info("  Excess return records: %d", len(excess_ret))

        # 4. 加载因子值
        logger.info("Loading factor values from %s...", start_date)
        factor_df = load_factor_values(conn, factor_names, start_date)
        logger.info("  Factor value records: %d", len(factor_df))

        # 5. 计算每个因子的日频IC并聚合为月频
        logger.info("Computing IC for each factor...")
        monthly_ic_dict: dict[str, pd.Series] = {}

        for fname in factor_names:
            daily_ic = compute_daily_ic(factor_df, excess_ret, fname)
            if len(daily_ic) == 0:
                logger.warning("Factor %s: no valid IC data.", fname)
                continue

            monthly_ic = compute_monthly_ic(daily_ic)
            monthly_ic_dict[fname] = monthly_ic

            rolling_mean = float(monthly_ic.tail(args.months).mean())
            logger.info(
                "  %s: daily IC count=%d, monthly IC count=%d, rolling %dm mean=%+.4f",
                fname, len(daily_ic), len(monthly_ic), args.months, rolling_mean,
            )

        # 6. 评估状态转换
        logger.info("Evaluating state transitions...")
        transitions = evaluate_transitions(lifecycle_df, monthly_ic_dict, today)

        for t in transitions:
            logger.info("  TRANSITION: %s %s -> %s (%s)",
                         t["factor_name"], t["from_status"], t["to_status"], t["reason"])

        # 7. 更新数据库
        if not args.dry_run:
            logger.info("Updating factor_lifecycle table...")
            for fname in factor_names:
                if fname in monthly_ic_dict:
                    roll_ic = float(monthly_ic_dict[fname].tail(args.months).mean())
                else:
                    continue

                # 查找该因子是否有转换
                trans = next((t for t in transitions if t["factor_name"] == fname), None)

                update_lifecycle(
                    conn,
                    factor_name=fname,
                    rolling_ic_12m=roll_ic,
                    today=today,
                    new_status=trans["to_status"] if trans else None,
                    warning_date=trans.get("warning_date") if trans else None,
                    retired_date=trans.get("retired_date") if trans else None,
                )
            logger.info("Database updated.")
        else:
            logger.info("Dry-run mode: skipping DB update.")

        # 8. 生成报告
        # 重新加载lifecycle以反映更新
        if not args.dry_run:
            lifecycle_df = load_lifecycle(conn)

        report = generate_report(lifecycle_df, monthly_ic_dict, transitions)
        print(report)

        # 9. 钉钉通知
        if args.dingtalk:
            send_dingtalk(report, transitions)
    finally:
        conn.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
