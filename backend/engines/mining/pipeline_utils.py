"""GP Pipeline 公共工具函数 — 从 scripts/run_gp_pipeline.py 提取的共享接口。

将原脚本中的私有函数提取为公开接口，供 Celery 任务（mining_tasks.py）和
脚本（run_gp_pipeline.py）共同使用，消除代码重复。

设计文档:
  - docs/GP_CLOSED_LOOP_DESIGN.md §6: 完整闭环流程
  - docs/DEV_BACKEND.md §4.12.3: Celery Task 模板

注意:
  - 所有函数均无副作用，纯数据加载/计算/通知
  - async 函数（load_market_data/load_existing_factor_data）
    在 Celery worker 中通过 asyncio.run() 的上下文内调用
  - PT 代码隔离：不修改 v1.1 信号链路（宪法 §16.2）
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


async def load_market_data(db_url: str, lookback_days: int = 365) -> pd.DataFrame:
    """从 PG 加载行情数据（最近 lookback_days 日）。

    列: trade_date, code, open, high, low, close, volume(手), amount(千元, klines_daily),
        turnover_rate(%, daily_basic), returns

    Args:
        db_url: PostgreSQL 连接字符串。
        lookback_days: 回看天数，默认 365（1年，GP 快速回测用）。

    Returns:
        行情宽表 DataFrame。加载失败时返回空 DataFrame。
    """
    from datetime import date

    import asyncpg

    try:
        conn = await asyncpg.connect(db_url)
        cutoff = date.today().replace(year=date.today().year - 1)
        rows = await conn.fetch(
            """
            SELECT
                k.trade_date,
                k.code,
                k.open,
                k.high,
                k.low,
                k.close,
                k.volume,
                k.amount,
                k.turnover_rate
            FROM klines_daily k
            JOIN symbols s ON k.code = s.code
            WHERE k.trade_date >= $1
              AND s.market = 'astock'
              AND s.is_active = true
            ORDER BY k.trade_date, k.code
            """,
            cutoff,
        )
        await conn.close()

        if not rows:
            logger.warning("行情数据为空", cutoff=str(cutoff))
            return pd.DataFrame()

        df = pd.DataFrame(
            rows,
            columns=[
                "trade_date",
                "code",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "turnover_rate",
            ],
        )

        # 计算 returns（当日收益率，用于 amihud 等因子）
        df = df.sort_values(["code", "trade_date"], kind="mergesort")
        df["returns"] = df.groupby("code")["close"].pct_change()

        logger.info("行情数据加载完成", rows=len(df), codes=df["code"].nunique())
        return df

    except Exception as exc:
        logger.error("行情数据加载失败", error=str(exc))
        return pd.DataFrame()


async def load_existing_factor_data(db_url: str) -> dict[str, pd.Series]:
    """加载现有 Active 因子值（用于正交性奖励计算）。

    取最新截面（最新交易日）的 neutral_value，供 GP 引擎计算正交性奖励。

    Args:
        db_url: PostgreSQL 连接字符串。

    Returns:
        {factor_name: pd.Series(factor_value, index=code)}。
        加载失败时返回空 dict（GP 引擎仍可运行，仅跳过正交性奖励）。
    """
    import asyncpg

    try:
        conn = await asyncpg.connect(db_url)
        rows = await conn.fetch(
            """
            SELECT fv.factor_name, fv.code, fv.neutral_value AS factor_value
            FROM factor_values fv
            JOIN factor_registry fr ON fr.name = fv.factor_name
            WHERE fr.status = 'active'
              AND fv.trade_date = (
                  SELECT MAX(trade_date) FROM factor_values fv2
                  WHERE fv2.factor_name = fv.factor_name
              )
              AND fv.neutral_value IS NOT NULL
            """,
        )
        await conn.close()

        result: dict[str, pd.Series] = {}
        if rows:
            df = pd.DataFrame(rows, columns=["factor_name", "code", "factor_value"])
            for name, grp in df.groupby("factor_name"):
                result[str(name)] = grp.set_index("code")["factor_value"].astype(float)

        logger.info("现有因子数据加载完成", factors=list(result.keys()))
        return result

    except Exception as exc:
        logger.warning("现有因子数据加载失败，跳过正交性计算", error=str(exc))
        return {}


def compute_forward_returns(
    market_data: pd.DataFrame,
    forward_days: int = 20,
) -> pd.Series:
    """计算前向收益率（月度，20 个交易日）。

    使用最新截面的前向 forward_days 日收益，供 GP 适应度和 Gate 计算。

    Args:
        market_data: 行情宽表（含 trade_date/code/close 列）。
        forward_days: 前向窗口，默认 20（与月度调仓一致）。

    Returns:
        pd.Series(forward_return, index=code)，使用最新截面。
        数据不足时返回空 Series。
    """
    if market_data.empty:
        return pd.Series(dtype=float)

    df = market_data[["trade_date", "code", "close"]].copy()
    df = df.sort_values(["code", "trade_date"], kind="mergesort")

    latest_date = df["trade_date"].max()
    all_dates = sorted(df["trade_date"].unique())

    try:
        latest_idx = list(all_dates).index(latest_date)
        if latest_idx + forward_days < len(all_dates):
            fwd_date = all_dates[latest_idx + forward_days]
        else:
            # 不够 forward_days，用最后可用日期
            fwd_date = all_dates[-1]
    except ValueError:
        return pd.Series(dtype=float)

    current = df[df["trade_date"] == latest_date].set_index("code")["close"]
    future = df[df["trade_date"] == fwd_date].set_index("code")["close"]

    common = current.index.intersection(future.index)
    if len(common) < 100:
        logger.warning("前向收益计算：股票覆盖不足", n_stocks=len(common))

    fwd_returns = (future.loc[common] - current.loc[common]) / current.loc[common]
    logger.info(
        "前向收益计算完成",
        n_stocks=len(fwd_returns),
        mean_return=round(float(fwd_returns.mean()), 4),
    )
    return fwd_returns


def run_full_gate(
    candidates: list[Any],
    market_data: pd.DataFrame,
    forward_returns: pd.Series,
    blacklist: set[str],
) -> list[dict[str, Any]]:
    """对 GP 产出的 Top 候选运行完整 Gate G1-G8。

    Args:
        candidates: GPResult 列表（按 fitness 降序），每个元素需有
                    factor_expr / ast_hash / fitness / ic_mean / t_stat /
                    complexity / novelty / parent_seed / generation /
                    island_id / param_slots 属性。
        market_data: 行情宽表（含 trade_date/code/close 等列）。
        forward_returns: 前向收益率 Series（index=code）。
        blacklist: AST hash 黑名单，命中则直接跳过。

    Returns:
        通过完整 Gate 的因子字典列表，含:
        factor_expr / ast_hash / fitness / ic_mean / t_stat /
        complexity / novelty / gate_result / parent_seed /
        generation / island_id / param_slots
    """
    from engines.factor_gate import FactorGatePipeline

    gate = FactorGatePipeline()
    passed: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for i, candidate in enumerate(candidates):
        factor_expr: str = candidate.factor_expr
        ast_hash: str = candidate.ast_hash

        # 黑名单检查
        if ast_hash in blacklist:
            logger.debug("候选因子在黑名单中，跳过", expr=factor_expr, hash=ast_hash)
            continue

        # AST 去重（同一批候选中）
        if ast_hash in seen_hashes:
            logger.debug("候选因子重复（同批），跳过", expr=factor_expr)
            continue
        seen_hashes.add(ast_hash)

        logger.info(
            "运行完整 Gate G1-G8",
            i=i + 1,
            total=len(candidates),
            expr=factor_expr,
            fitness=round(candidate.fitness, 4),
        )

        try:
            # 计算因子值
            from engines.mining.factor_dsl import FactorDSL

            dsl = FactorDSL()
            tree = dsl.from_string(factor_expr)
            factor_values = tree.evaluate(market_data)

            if factor_values is None or factor_values.empty:
                logger.warning("因子值计算为空，跳过", expr=factor_expr)
                continue

            # 运行完整 Gate
            report = gate.run(
                factor_name=f"gp_{ast_hash[:8]}",
                factor_values=factor_values,
                forward_returns=forward_returns,
            )

            gate_summary = {g: str(r.status) for g, r in report.gate_results.items()}
            overall_pass = report.overall_passed

            logger.info(
                "Gate G1-G8 结果",
                expr=factor_expr,
                passed=overall_pass,
                gates=gate_summary,
            )

            if overall_pass:
                passed.append(
                    {
                        "factor_expr": factor_expr,
                        "ast_hash": ast_hash,
                        "fitness": round(candidate.fitness, 6),
                        "ic_mean": round(candidate.ic_mean, 6),
                        "t_stat": round(candidate.t_stat, 4),
                        "complexity": round(candidate.complexity, 4),
                        "novelty": round(candidate.novelty, 4),
                        "gate_result": gate_summary,
                        "parent_seed": candidate.parent_seed,
                        "generation": candidate.generation,
                        "island_id": candidate.island_id,
                        "param_slots": candidate.param_slots,
                    }
                )

        except Exception as exc:
            logger.warning("Gate 评估异常，跳过", expr=factor_expr, error=str(exc))
            continue

    logger.info(
        "完整 Gate 筛选完成",
        evaluated=len(seen_hashes),
        passed=len(passed),
        pass_rate=f"{len(passed) / max(len(seen_hashes), 1):.1%}",
    )
    return passed


def send_dingtalk_notification(
    webhook_url: str,
    secret: str | None,
    run_id: str,
    stats: dict[str, Any],
    passed_factors: list[dict[str, Any]],
    error: str | None = None,
) -> None:
    """发送钉钉通知（候选因子摘要）。

    失败不抛异常，只记录警告日志。

    Args:
        webhook_url: 钉钉 Webhook URL。空字符串时直接跳过。
        secret: 签名密钥（可选，None 时不签名）。
        run_id: 本次运行 ID。
        stats: 运行统计信息（keys: total_evaluated/passed_quick_gate/
               best_fitness/elapsed_seconds/n_generations_completed）。
        passed_factors: 通过 Gate 的因子列表。
        error: 整体错误信息（None=成功，非空=P0告警）。
    """
    if not webhook_url:
        logger.debug("未配置钉钉 Webhook，跳过通知")
        return

    try:
        from app.services.dispatchers import dingtalk

        if error:
            title = f"[P0] GP Pipeline 失败 — {run_id}"
            content = (
                f"## GP Pipeline 运行异常\n\n"
                f"**运行ID**: `{run_id}`\n\n"
                f"**错误**: {error}\n\n"
                f"**评估数量**: {stats.get('total_evaluated', 0)}\n\n"
                f"请检查日志: `logs/gp_pipeline.log`"
            )
        else:
            n_candidates = stats.get("passed_quick_gate", 0)
            n_passed = len(passed_factors)
            best_fitness = stats.get("best_fitness", -999)
            elapsed_min = stats.get("elapsed_seconds", 0) / 60

            title = f"GP本周产出 {n_passed} 个候选因子 — {run_id}"

            factor_lines = ""
            for i, f in enumerate(passed_factors[:5], 1):
                factor_lines += (
                    f"\n{i}. `{f['factor_expr'][:60]}`"
                    f"  fitness={f['fitness']:.3f}"
                    f"  IC={f['ic_mean']:.4f}"
                )

            content = (
                f"## GP Pipeline 完成\n\n"
                f"**运行ID**: `{run_id}`\n\n"
                f"| 指标 | 值 |\n"
                f"|------|----|\n"
                f"| 总评估个体 | {stats.get('total_evaluated', 0)} |\n"
                f"| 通过快速Gate | {n_candidates} |\n"
                f"| 通过完整Gate G1-G8 | {n_passed} |\n"
                f"| 最优适应度 | {best_fitness:.4f} |\n"
                f"| 运行时长 | {elapsed_min:.1f} 分钟 |\n"
                f"| 完成代数 | {stats.get('n_generations_completed', 0)} |\n\n"
                f"**Top 候选因子**:{factor_lines or ' 无'}\n\n"
                f"请登录前端审批队列处理候选因子。"
            )

        dingtalk.send_markdown(
            webhook_url=webhook_url,
            secret=secret or "",
            title=title,
            content=content,
        )
        logger.info("钉钉通知发送成功", title=title)

    except Exception as exc:
        logger.warning("钉钉通知发送失败", error=str(exc))
