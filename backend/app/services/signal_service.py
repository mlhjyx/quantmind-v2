"""SignalService — 信号生成Service。

从scripts/run_paper_trading.py L1107-1279迁移。
完整信号生成: compose -> build -> 4项验证 -> Beta -> 写signals表。

复用现有engines(SignalComposer/PortfolioBuilder)，不重新实现。
Service内部不commit，由调用方统一管理事务。
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional

import pandas as pd

from engines.beta_hedge import calc_portfolio_beta
from engines.paper_broker import PaperBroker
from engines.signal_engine import (
    PAPER_TRADING_CONFIG,
    PortfolioBuilder,
    SignalComposer,
    SignalConfig,
)
from app.config import settings
from app.services.notification_service import send_alert

logger = logging.getLogger(__name__)


@dataclass
class SignalResult:
    """信号生成结果。"""

    target_weights: dict[str, float]  # code -> weight
    signals_list: list[dict]          # 写入signals表的记录
    beta: float
    is_rebalance: bool
    warnings: list[str] = field(default_factory=list)


class SignalService:
    """信号生成Service。

    职责:
    1. 因子完整性检查（缺失因子阻塞、覆盖率检查）
    2. 信号合成（SignalComposer.compose）
    3. 目标持仓构建（PortfolioBuilder.build）
    4. 行业集中度检查、持仓重合度检查
    5. Beta监控
    6. 写入signals表
    """

    def generate_signals(
        self,
        conn,
        strategy_id: str,
        trade_date: date,
        factor_df: pd.DataFrame,
        universe: set[str],
        industry: pd.Series,
        config: SignalConfig,
        dry_run: bool = False,
        vol_regime_scale: float = 1.0,
    ) -> SignalResult:
        """完整信号生成：compose -> build -> 4项验证 -> Beta -> 写signals表。

        Args:
            conn: psycopg2连接（调用方管理事务）。
            strategy_id: 策略ID。
            trade_date: 信号日期（T日）。
            factor_df: 因子宽表 columns=[code, factor_name, neutral_value]。
            universe: 可交易股票池。
            industry: 行业分类 (code -> industry_sw1)。
            config: 信号配置。
            dry_run: 不写DB。
            vol_regime_scale: 波动率regime仓位缩放系数 [0.5, 2.0]，默认1.0（不调整）。
                              由调用方用vol_regime.calc_vol_regime()计算后传入。

        Returns:
            SignalResult: 包含目标权重、信号列表、Beta等。

        Raises:
            ValueError: 因子缺失或信号为空。
        """
        warnings: list[str] = []

        # ── 检查1: 因子完整性（缺失即阻塞）──
        # 对应 script L1118-1133
        available_factors = set()
        if "factor_name" in factor_df.columns:
            available_factors = set(factor_df["factor_name"].unique())
        elif hasattr(factor_df, "columns"):
            available_factors = set(factor_df.columns)

        required_factors = set(config.factor_names)
        missing_factors = required_factors - available_factors
        if missing_factors:
            msg = (
                f"因子缺失: {missing_factors}。"
                f"配置要求{len(required_factors)}因子，"
                f"实际只有{len(required_factors - missing_factors)}。"
                f"不允许静默降级。"
            )
            raise ValueError(msg)

        # ── 检查2: 因子截面覆盖率 ──
        # 对应 script L1135-1159
        for fname in config.factor_names:
            if "factor_name" in factor_df.columns:
                count = factor_df[factor_df["factor_name"] == fname].shape[0]
            else:
                count = len(factor_df)

            if count < 1000:
                msg = (
                    f"因子 {fname} 截面覆盖率严重不足: {count}只 < 1000。"
                    f"可能数据源故障或拉取异常。"
                )
                raise ValueError(msg)
            elif count < 3000:
                msg = (
                    f"因子 {fname} 截面覆盖率偏低: {count}只 < 3000。"
                    f"信号生成继续，但请排查数据完整性。"
                )
                logger.warning(f"[SignalService] P1 {msg}")
                warnings.append(msg)
                if not dry_run:
                    send_alert(
                        "P1", f"因子覆盖率偏低 {trade_date}", msg,
                        settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn,
                    )
            else:
                logger.info(f"[SignalService] 因子 {fname} 覆盖率正常: {count}只")

        # ── 信号合成 ──
        # 对应 script L1164-1172
        composer = SignalComposer(config)
        builder = PortfolioBuilder(config)

        scores = composer.compose(factor_df, universe)
        if scores.empty:
            raise ValueError("信号合成结果为空(scores为空)")

        # ── 读取当前持仓权重 ──
        # 对应 script L1174-1185
        prev_weights = self._load_prev_weights(conn, strategy_id)

        # ── 构建目标持仓 ──
        # 对应 script L1187-1188
        target = builder.build(scores, industry, prev_weights, vol_regime_scale=vol_regime_scale)
        logger.info(
            f"[SignalService] 目标持仓: {len(target)}只, "
            f"总权重={sum(target.values()):.3f}"
        )

        # ── Beta监控（只记录，不缩放权重）──
        # 对应 script L1190-1196
        beta = calc_portfolio_beta(
            trade_date, strategy_id, lookback_days=60, conn=conn,
        )
        hedged_target = target  # 不缩放，直接使用原始权重
        logger.info(
            f"[SignalService] Beta={beta:.3f}(监控), "
            f"总权重={sum(hedged_target.values()):.3f}"
        )

        # ── 检查3: 行业集中度（最大行业权重<25%）──
        # 对应 script L1198-1226
        if hedged_target:
            ind_warning = self._check_industry_concentration(
                conn, hedged_target, trade_date, dry_run,
            )
            if ind_warning:
                warnings.append(ind_warning)

        # ── 检查4: 持仓重合度（与上期持仓比较，<30%重合 -> P1告警）──
        # 对应 script L1228-1244
        if hedged_target and prev_weights:
            overlap_warning = self._check_overlap(
                hedged_target, prev_weights, trade_date, dry_run, conn,
            )
            if overlap_warning:
                warnings.append(overlap_warning)

        # ── 判断是否调仓日 ──
        # 对应 script L1247-1252
        paper_broker = PaperBroker(
            strategy_id=strategy_id,
            initial_capital=settings.PAPER_INITIAL_CAPITAL,
        )
        paper_broker.load_state(conn)
        is_rebalance = paper_broker.needs_rebalance(trade_date, conn)

        # ── 构建signals记录 + 写signals表 ──
        # 对应 script L1254-1278
        signals_list: list[dict] = []
        sorted_codes = sorted(
            hedged_target.keys(),
            key=lambda c: hedged_target[c],
            reverse=True,
        )
        for rank, code in enumerate(sorted_codes, 1):
            score_val = float(scores.get(code, 0)) if not scores.empty else 0
            action = "rebalance" if is_rebalance else "hold"
            signals_list.append({
                "code": code,
                "trade_date": trade_date,
                "strategy_id": strategy_id,
                "alpha_score": score_val,
                "rank": rank,
                "target_weight": hedged_target[code],
                "action": action,
            })

        if not dry_run:
            self._write_signals(conn, strategy_id, trade_date, signals_list)

        return SignalResult(
            target_weights=hedged_target,
            signals_list=signals_list,
            beta=beta,
            is_rebalance=is_rebalance,
            warnings=warnings,
        )

    def get_latest_signals(
        self,
        conn,
        strategy_id: str,
        signal_date: date,
    ) -> list[dict]:
        """读取signals表中指定日期的信号。

        对应 script L1386-1393。

        Args:
            conn: psycopg2连接。
            strategy_id: 策略ID。
            signal_date: 信号日期。

        Returns:
            信号记录列表，每条含code/target_weight/action/rank。
        """
        cur = conn.cursor()
        cur.execute(
            """SELECT code, target_weight, action, rank
               FROM signals
               WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'paper'
               ORDER BY rank""",
            (signal_date, strategy_id),
        )
        rows = cur.fetchall()
        return [
            {
                "code": r[0],
                "target_weight": float(r[1]),
                "action": r[2],
                "rank": r[3],
            }
            for r in rows
        ]

    # ──────────────────────────────────────────────
    # 内部方法
    # ──────────────────────────────────────────────

    def _load_prev_weights(self, conn, strategy_id: str) -> dict[str, float]:
        """读取最新持仓权重。对应 script L1174-1185。"""
        cur = conn.cursor()
        cur.execute(
            """SELECT code, weight FROM position_snapshot
               WHERE strategy_id = %s AND execution_mode = 'paper'
                 AND trade_date = (
                   SELECT MAX(trade_date) FROM position_snapshot
                   WHERE strategy_id = %s AND execution_mode = 'paper'
                 )""",
            (strategy_id, strategy_id),
        )
        return {r[0]: float(r[1] or 0) for r in cur.fetchall()}

    def _check_industry_concentration(
        self,
        conn,
        hedged_target: dict[str, float],
        trade_date: date,
        dry_run: bool,
    ) -> Optional[str]:
        """行业集中度检查。对应 script L1198-1226。

        Returns:
            告警消息字符串，无告警则返回None。
        """
        top_codes = sorted(
            hedged_target, key=lambda c: hedged_target[c], reverse=True,
        )[:20]
        if not top_codes:
            return None

        top_weights = {c: hedged_target[c] for c in top_codes}
        cur = conn.cursor()
        placeholders = ",".join(["%s"] * len(top_codes))
        cur.execute(
            f"""SELECT code, industry_sw1 FROM symbols
                WHERE code IN ({placeholders})""",
            tuple(top_codes),
        )
        code_industry = dict(cur.fetchall())

        industry_weights: dict[str, float] = {}
        for code in top_codes:
            ind = code_industry.get(code, "未知")
            industry_weights[ind] = industry_weights.get(ind, 0) + top_weights[code]

        max_ind = max(industry_weights, key=industry_weights.get) if industry_weights else "N/A"
        max_ind_weight = industry_weights.get(max_ind, 0)
        logger.info(
            f"[SignalService] 行业集中度: 最大行业={max_ind} "
            f"权重={max_ind_weight:.1%}"
        )

        if max_ind_weight > 0.25:
            top5 = sorted(industry_weights.items(), key=lambda x: -x[1])[:5]
            msg = (
                f"Top20持仓行业集中度过高: {max_ind} "
                f"权重={max_ind_weight:.1%} > 25%。"
                f"行业分布: {', '.join(f'{k}={v:.1%}' for k, v in top5)}"
            )
            logger.warning(f"[SignalService] P1 {msg}")
            if not dry_run:
                send_alert(
                    "P1", f"行业集中度超标 {trade_date}", msg,
                    settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn,
                )
            return msg
        return None

    def _check_overlap(
        self,
        hedged_target: dict[str, float],
        prev_weights: dict[str, float],
        trade_date: date,
        dry_run: bool,
        conn,
    ) -> Optional[str]:
        """持仓重合度检查。对应 script L1228-1244。

        Returns:
            告警消息字符串，无告警则返回None。
        """
        current_top = set(
            sorted(hedged_target, key=lambda c: hedged_target[c], reverse=True)[:20]
        )
        prev_top = set(
            sorted(prev_weights, key=lambda c: prev_weights[c], reverse=True)[:20]
        )
        if not prev_top:
            return None

        overlap = len(current_top & prev_top)
        overlap_ratio = overlap / max(len(prev_top), 1)
        logger.info(
            f"[SignalService] 持仓重合度: {overlap}/{len(prev_top)} "
            f"= {overlap_ratio:.0%}"
        )

        if overlap_ratio < 0.30:
            new_in = ", ".join(sorted(current_top - prev_top)[:10])
            out = ", ".join(sorted(prev_top - current_top)[:10])
            msg = (
                f"持仓重合度过低: {overlap}/{len(prev_top)} "
                f"= {overlap_ratio:.0%} < 30%。"
                f"换手剧烈，建议人工确认信号合理性。"
                f"\n新进: {new_in}"
                f"\n退出: {out}"
            )
            logger.warning(f"[SignalService] P1 {msg}")
            if not dry_run:
                send_alert(
                    "P1", f"持仓换手剧烈 {trade_date}", msg,
                    settings.DINGTALK_WEBHOOK_URL, settings.DINGTALK_SECRET, conn,
                )
            return msg
        return None

    def _write_signals(
        self,
        conn,
        strategy_id: str,
        trade_date: date,
        signals_list: list[dict],
    ) -> None:
        """写入signals表。对应 script L1256-1275。

        不commit，由调用方管理事务。
        """
        cur = conn.cursor()
        # 清除当日旧信号（幂等）
        cur.execute(
            """DELETE FROM signals
               WHERE trade_date = %s AND strategy_id = %s AND execution_mode = 'paper'""",
            (trade_date, strategy_id),
        )
        now_utc = datetime.now(timezone.utc)
        for sig in signals_list:
            cur.execute(
                """INSERT INTO signals
                   (code, trade_date, strategy_id, alpha_score, rank,
                    target_weight, action, execution_mode, signal_generated_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, 'paper', %s)""",
                (
                    sig["code"],
                    sig["trade_date"],
                    sig["strategy_id"],
                    sig["alpha_score"],
                    sig["rank"],
                    sig["target_weight"],
                    sig["action"],
                    now_utc,
                ),
            )
