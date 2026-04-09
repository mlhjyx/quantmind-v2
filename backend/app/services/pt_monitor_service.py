"""PT监控服务 — 开盘跳空检测+风险评估。

从run_paper_trading.py提取(Step 6-A)。
"""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd

from app.config import settings
from app.services.notification_service import NotificationService

logger = logging.getLogger("paper_trading")


def check_opening_gap(
    exec_date: date,
    price_data: pd.DataFrame,
    conn,
    notif_svc: NotificationService,
    dry_run: bool,
    single_stock_gap_threshold: float = 0.05,
    portfolio_gap_threshold: float = 0.03,
) -> None:
    """开盘跳空预检 — 在execute阶段执行调仓前检测跳空风险。

    PT阶段：只告警，不暂停执行。
    """
    if price_data.empty:
        logger.warning("[Monitor] 无价格数据，跳过开盘跳空预检")
        return

    df = price_data[["code", "open", "pre_close"]].copy()
    df = df[df["pre_close"] > 0]
    df["gap"] = (df["open"] - df["pre_close"]) / df["pre_close"]

    # 单股跳空 >5% 告警
    large_gaps = df[df["gap"].abs() > single_stock_gap_threshold].copy()
    large_gaps = large_gaps.sort_values("gap", key=abs, ascending=False)

    if not large_gaps.empty:
        gap_summary = ", ".join(
            f"{row['code']}({row['gap']:+.1%})" for _, row in large_gaps.head(5).iterrows()
        )
        msg = f"开盘跳空预警 {exec_date}\n单股跳空>5%: {len(large_gaps)}只\nTop5: {gap_summary}"
        logger.warning("[Monitor] P1 %s", msg)
        if not dry_run:
            notif_svc.send_sync(conn, "P1", "risk", f"开盘跳空P1 {exec_date}", msg)

    # 组合加权平均跳空
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT code, weight FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = 'paper'
               ORDER BY trade_date DESC, weight DESC LIMIT 50""",
            (settings.PAPER_STRATEGY_ID,),
        )
        rows = cur.fetchall()
        if rows:
            weights = {r[0]: float(r[1]) for r in rows}
            total_w = sum(weights.values())
            if total_w > 0:
                gap_map = df.set_index("code")["gap"].to_dict()
                portfolio_gap = (
                    sum(weights.get(code, 0) * gap_map.get(code, 0) for code in weights)
                    / total_w
                )
                logger.info(
                    "[Monitor] 组合加权跳空=%+.2f%% (阈值>%.0f%%告P0)",
                    portfolio_gap * 100,
                    portfolio_gap_threshold * 100,
                )
                if abs(portfolio_gap) > portfolio_gap_threshold:
                    msg = (
                        f"组合开盘跳空告警 {exec_date}\n"
                        f"持仓加权平均跳空={portfolio_gap:+.2%}\n"
                        f"PT阶段继续执行，请人工复核"
                    )
                    logger.error("[Monitor] P0 %s", msg)
                    if not dry_run:
                        notif_svc.send_sync(
                            conn, "P0", "risk", f"组合跳空P0 {exec_date}", msg,
                        )
                        conn.commit()
    except Exception as e:
        logger.warning("[Monitor] 组合跳空计算失败: %s", e)
