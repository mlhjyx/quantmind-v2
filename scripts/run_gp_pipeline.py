"""GP Pipeline 入口脚本 — 完整闭环运行。

每周日 22:00 由 Task Scheduler 触发（GP_CLOSED_LOOP_DESIGN.md §7.1）。
也可手动运行进行调试。

流程（§6.1 七步）:
  1. 加载上轮结果 → 注入种子扩展+黑名单
  2. 从 PG 加载行情数据 + 现有因子值 + 前向收益
  3. 初始化 GPEngine (Warm Start) 并运行进化
  4. 收集 Top 候选 → 完整 Gate G1-G8 筛选
  5. 通过的写入 pipeline_runs + approval_queue（DB不可用时 fallback 到 JSON）
  6. 发送钉钉通知（候选因子摘要）
  7. 保存本轮结果供下轮使用

异常处理原则:
  - 每步骤独立 try/except，任一步失败记录日志后继续
  - 运行状态随时写 pipeline_runs.status（running→completed/failed）
  - 钉钉告警: P1=步骤失败, P0=整体运行失败

用法:
  python scripts/run_gp_pipeline.py
  python scripts/run_gp_pipeline.py --generations 50 --population 100 --islands 4
  python scripts/run_gp_pipeline.py --dry-run   # 仅加载数据不进化

资源约束（CLAUDE.md）:
  CPU: 8核（multiprocessing限制）
  内存: <1.5GB 总计
  时间预算: GP 120分钟 + Gate/回测 60分钟 = 180分钟
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Any

# 确保 backend 目录在 sys.path 中（脚本从项目根运行时）
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
_BACKEND_DIR = _PROJECT_ROOT / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import pandas as pd  # noqa: E402
import structlog  # noqa: E402

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# GP Pipeline 结果缓存目录（跨轮次学习）
_DEFAULT_OUTPUT_DIR = _PROJECT_ROOT / "gp_results"

# 每轮 GP 取 Top N 候选进完整 Gate
_TOP_CANDIDATES_FOR_FULL_GATE = 20

# 种子因子（与 GP_CLOSED_LOOP_DESIGN §3.2 一致）
_SEED_FACTORS: dict[str, str] = {
    "turnover_mean_20": "ts_mean(turnover_rate, 20)",
    "volatility_20": "ts_std(returns, 20)",
    "reversal_20": "neg(ts_pct(close, 20))",
    "amihud_20": "ts_mean(div(abs(returns), amount), 20)",
    "bp_ratio": "inv(pb)",
}


# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="QuantMind GP Pipeline — 每周自动因子挖掘闭环",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--generations", type=int, default=50, help="进化代数")
    parser.add_argument("--population", type=int, default=100, help="每岛种群大小")
    parser.add_argument("--islands", type=int, default=3, help="岛屿数量（子种群）")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_DEFAULT_OUTPUT_DIR,
        help="结果保存目录（JSON fallback）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只加载数据，不运行进化（调试用）",
    )
    parser.add_argument(
        "--time-budget",
        type=float,
        default=120.0,
        help="GP进化时间预算（分钟）",
    )
    parser.add_argument(
        "--top-n-gate",
        type=int,
        default=_TOP_CANDIDATES_FOR_FULL_GATE,
        help="取Top N候选进完整Gate G1-G8",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------


async def _load_market_data(db_url: str, lookback_days: int = 365) -> pd.DataFrame:
    """从 PG 加载行情数据（最近 lookback_days 日）。

    列: trade_date, code, open, high, low, close, volume, amount,
        turnover_rate, pe_ttm, pb, returns

    Args:
        db_url: PostgreSQL 连接字符串。
        lookback_days: 回看天数，默认365（1年，GP快速回测用）。

    Returns:
        行情宽表 DataFrame。加载失败时返回空 DataFrame。
    """
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
        df = df.sort_values(["code", "trade_date"])
        df["returns"] = df.groupby("code")["close"].pct_change()

        logger.info("行情数据加载完成", rows=len(df), codes=df["code"].nunique())
        return df

    except Exception as exc:
        logger.error("行情数据加载失败", error=str(exc))
        return pd.DataFrame()


async def _load_existing_factor_data(db_url: str) -> dict[str, pd.Series]:
    """加载现有 Active 因子值（用于正交性奖励计算）。

    Args:
        db_url: PostgreSQL 连接字符串。

    Returns:
        {factor_name: pd.Series(factor_value, index=code)}，加载失败时返回空 dict。
    """
    import asyncpg

    try:
        conn = await asyncpg.connect(db_url)
        # 取最近一个截面（最新交易日）的因子值
        # factor_values 是扁平结构: code/trade_date/factor_name/neutral_value
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


def _compute_forward_returns(market_data: pd.DataFrame, forward_days: int = 20) -> pd.Series:
    """计算前向收益率（月度，20个交易日）。

    Args:
        market_data: 行情宽表（含 trade_date/code/close）。
        forward_days: 前向窗口，默认20（与月度调仓一致）。

    Returns:
        pd.Series(forward_return, index=code)，使用最新截面。
    """
    if market_data.empty:
        return pd.Series(dtype=float)

    df = market_data[["trade_date", "code", "close"]].copy()
    df = df.sort_values(["code", "trade_date"])

    # 用最后一个截面的前向收益
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


# ---------------------------------------------------------------------------
# 跨轮次学习：加载/保存轮次结果
# ---------------------------------------------------------------------------


def _load_previous_run_result(output_dir: Path) -> dict[str, Any]:
    """加载上轮 GP 运行结果（JSON fallback 文件）。

    Args:
        output_dir: 结果保存目录。

    Returns:
        包含 top_factors/blacklist/run_id 的字典，不存在时返回空结构。
    """
    result_file = output_dir / "latest_run.json"
    if not result_file.exists():
        logger.info("无上轮结果文件，从零开始", path=str(result_file))
        return {"top_factors": [], "blacklist": [], "run_id": None}

    try:
        with result_file.open(encoding="utf-8") as f:
            data = json.load(f)
        logger.info(
            "加载上轮结果",
            prev_run_id=data.get("run_id"),
            top_factors=len(data.get("top_factors", [])),
            blacklist=len(data.get("blacklist", [])),
        )
        return data
    except Exception as exc:
        logger.warning("上轮结果文件解析失败，从零开始", error=str(exc))
        return {"top_factors": [], "blacklist": [], "run_id": None}


def _save_run_result(
    output_dir: Path,
    run_id: str,
    top_factors: list[dict[str, Any]],
    blacklist: list[str],
    stats: dict[str, Any],
) -> None:
    """保存本轮运行结果供下轮使用。

    Args:
        output_dir: 结果保存目录。
        run_id: 本轮运行ID。
        top_factors: 通过 Gate 的因子列表。
        blacklist: AST hash 黑名单（被 reject 的因子）。
        stats: 运行统计信息。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "run_id": run_id,
        "run_date": date.today().isoformat(),
        "top_factors": top_factors,
        "blacklist": blacklist,
        "stats": stats,
    }

    # latest_run.json: 供下轮使用
    latest_file = output_dir / "latest_run.json"
    with latest_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    # 归档：按 run_id 保存历史
    archive_file = output_dir / f"{run_id}.json"
    with archive_file.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=str)

    logger.info("运行结果已保存", latest=str(latest_file), archive=str(archive_file))


# ---------------------------------------------------------------------------
# Gate 筛选
# ---------------------------------------------------------------------------


def _run_full_gate(
    candidates: list[Any],
    market_data: pd.DataFrame,
    forward_returns: pd.Series,
    blacklist: set[str],
) -> list[dict[str, Any]]:
    """对 GP 产出的 Top 候选运行完整 Gate G1-G8。

    Args:
        candidates: GPResult 列表（按 fitness 降序）。
        market_data: 行情宽表。
        forward_returns: 前向收益率。
        blacklist: AST hash 黑名单（直接跳过）。

    Returns:
        通过完整 Gate 的因子字典列表，含 gate_result/sharpe_proxy/factor_expr。
    """
    from engines.factor_gate import FactorGatePipeline

    gate = FactorGatePipeline()
    passed: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()

    for i, candidate in enumerate(candidates):
        factor_expr = candidate.factor_expr
        ast_hash = candidate.ast_hash

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


# ---------------------------------------------------------------------------
# 数据库写入
# ---------------------------------------------------------------------------


async def _write_to_db(
    db_url: str,
    run_id: str,
    config_dict: dict[str, Any],
    stats: dict[str, Any],
    passed_factors: list[dict[str, Any]],
    status: str = "completed",
    error_message: str | None = None,
) -> bool:
    """写入 pipeline_runs 和 approval_queue 表。

    Args:
        db_url: PostgreSQL 连接字符串。
        run_id: 本次运行 ID。
        config_dict: GP 配置 JSON。
        stats: 运行统计信息。
        passed_factors: 通过 Gate 的因子列表。
        status: 运行状态（completed/failed）。
        error_message: 失败时的错误信息。

    Returns:
        True=写入成功, False=失败（会 fallback 到 JSON）。
    """
    import asyncpg

    try:
        conn = await asyncpg.connect(db_url)

        # 更新 pipeline_runs
        await conn.execute(
            """
            INSERT INTO pipeline_runs
                (run_id, engine_type, started_at, finished_at, status, config, result_summary, error_message)
            VALUES ($1, 'gp', NOW() - INTERVAL '1 second', NOW(), $2, $3, $4, $5)
            ON CONFLICT (run_id) DO UPDATE SET
                finished_at = EXCLUDED.finished_at,
                status = EXCLUDED.status,
                result_summary = EXCLUDED.result_summary,
                error_message = EXCLUDED.error_message
            """,
            run_id,
            status,
            json.dumps(config_dict),
            json.dumps(stats),
            error_message,
        )

        # 写入 approval_queue
        for factor in passed_factors:
            await conn.execute(
                """
                INSERT INTO gp_approval_queue
                    (run_id, factor_name, factor_expr, ast_hash,
                     gate_report, status, created_at)
                VALUES ($1, $2, $3, $4, $5, 'pending', NOW())
                ON CONFLICT DO NOTHING
                """,
                run_id,
                f"gp_{factor['ast_hash'][:8]}",
                factor["factor_expr"],
                factor["ast_hash"],
                json.dumps(factor["gate_result"]),
            )

        await conn.close()
        logger.info(
            "DB 写入完成",
            run_id=run_id,
            status=status,
            approval_queue_added=len(passed_factors),
        )
        return True

    except Exception as exc:
        logger.error("DB 写入失败，将 fallback 到 JSON", error=str(exc))
        return False


# ---------------------------------------------------------------------------
# 钉钉通知
# ---------------------------------------------------------------------------


def _send_dingtalk_notification(
    webhook_url: str,
    secret: str | None,
    run_id: str,
    stats: dict[str, Any],
    passed_factors: list[dict[str, Any]],
    error: str | None = None,
) -> None:
    """发送钉钉通知（候选因子摘要）。

    失败不抛异常，只记录日志。

    Args:
        webhook_url: 钉钉 Webhook URL。
        secret: 签名密钥（可选）。
        run_id: 本次运行 ID。
        stats: 运行统计信息。
        passed_factors: 通过 Gate 的因子列表。
        error: 整体错误信息（None=成功）。
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


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


async def _run_pipeline_async(args: argparse.Namespace) -> int:
    """GP Pipeline 主协程。

    Args:
        args: 命令行参数。

    Returns:
        退出码: 0=成功, 1=失败。
    """
    # 从环境变量读取配置
    db_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://xin:quantmind@localhost:5432/quantmind_v2",
    )
    dingtalk_webhook = os.environ.get("DINGTALK_WEBHOOK_URL", "")
    dingtalk_secret = os.environ.get("DINGTALK_SECRET", "")

    # 生成 run_id（格式: gp_2026w14）
    iso_cal = date.today().isocalendar()
    run_id = f"gp_{iso_cal.year}w{iso_cal.week:02d}_{uuid.uuid4().hex[:6]}"

    logger.info(
        "GP Pipeline 启动",
        run_id=run_id,
        generations=args.generations,
        population=args.population,
        islands=args.islands,
        dry_run=args.dry_run,
    )

    start_time = time.monotonic()
    passed_factors: list[dict[str, Any]] = []
    blacklist: list[str] = []
    stats: dict[str, Any] = {"run_id": run_id, "total_evaluated": 0}
    overall_error: str | None = None

    # ------------------------------------------------------------------
    # Step 1: 加载上轮结果 → 注入种子+黑名单
    # ------------------------------------------------------------------
    prev_result = _load_previous_run_result(args.output_dir)
    blacklist = list(prev_result.get("blacklist", []))
    prev_top = prev_result.get("top_factors", [])
    logger.info(
        "上轮结果注入",
        prev_run_id=prev_result.get("run_id"),
        extra_seeds=len(prev_top),
        blacklist_size=len(blacklist),
    )

    # ------------------------------------------------------------------
    # Step 2: 加载行情数据 + 现有因子值 + 前向收益
    # ------------------------------------------------------------------
    logger.info("Step 2: 加载数据...")
    market_data = await _load_market_data(db_url)
    existing_factors = await _load_existing_factor_data(db_url)

    if market_data.empty:
        msg = "行情数据加载失败，无法继续"
        logger.error(msg)
        _send_dingtalk_notification(dingtalk_webhook, dingtalk_secret, run_id, stats, [], error=msg)
        return 1

    forward_returns = _compute_forward_returns(market_data)

    if args.dry_run:
        logger.info(
            "dry-run 模式：数据加载完成，跳过进化",
            market_rows=len(market_data),
            existing_factors=list(existing_factors.keys()),
            n_forward_returns=len(forward_returns),
        )
        return 0

    # ------------------------------------------------------------------
    # Step 3: 初始化 GPEngine + 运行进化
    # ------------------------------------------------------------------
    logger.info("Step 3: 初始化 GP Engine...")
    gp_results = []
    gp_stats_obj = None

    try:
        from engines.mining.gp_engine import GPConfig, GPEngine

        gp_config = GPConfig(
            n_islands=args.islands,
            population_per_island=args.population,
            n_generations=args.generations,
            time_budget_minutes=args.time_budget,
            # 生产配置
            migration_interval=10,
            migration_size=5,
            seed_ratio=0.8,
            random_ratio=0.2,
        )

        engine = GPEngine(
            config=gp_config,
            existing_factor_data=existing_factors,
        )

        logger.info(
            "GP 进化开始",
            islands=gp_config.n_islands,
            pop_per_island=gp_config.population_per_island,
            generations=gp_config.n_generations,
            time_budget_min=gp_config.time_budget_minutes,
        )

        gp_results, gp_stats_obj = engine.evolve(
            market_data=market_data,
            forward_returns=forward_returns,
            run_id=run_id,
        )

        stats.update(
            {
                "total_evaluated": gp_stats_obj.total_evaluated,
                "passed_quick_gate": gp_stats_obj.passed_quick_gate,
                "best_fitness": round(gp_stats_obj.best_fitness, 6),
                "best_expr": gp_stats_obj.best_expr,
                "elapsed_seconds": round(gp_stats_obj.elapsed_seconds, 1),
                "n_generations_completed": gp_stats_obj.n_generations_completed,
                "timeout": gp_stats_obj.timeout,
                "per_island_best": gp_stats_obj.per_island_best,
            }
        )

        logger.info(
            "GP 进化完成",
            total_evaluated=gp_stats_obj.total_evaluated,
            passed_quick_gate=gp_stats_obj.passed_quick_gate,
            best_fitness=round(gp_stats_obj.best_fitness, 4),
            generations_done=gp_stats_obj.n_generations_completed,
            timeout=gp_stats_obj.timeout,
        )

    except Exception as exc:
        msg = f"GP 进化失败: {exc}"
        logger.error(msg, exc_info=True)
        overall_error = msg
        # 继续后续步骤（钉钉告警）
        _send_dingtalk_notification(dingtalk_webhook, dingtalk_secret, run_id, stats, [], error=msg)
        return 1

    if not gp_results:
        logger.warning("GP 进化产出为空，无候选因子")
        stats["passed_gate_full"] = 0
        _save_run_result(args.output_dir, run_id, [], blacklist, stats)
        _send_dingtalk_notification(dingtalk_webhook, dingtalk_secret, run_id, stats, [])
        return 0

    # ------------------------------------------------------------------
    # Step 4: 完整 Gate G1-G8
    # ------------------------------------------------------------------
    logger.info("Step 4: 完整 Gate G1-G8 筛选...")
    top_candidates = gp_results[: args.top_n_gate]

    try:
        passed_factors = _run_full_gate(
            candidates=top_candidates,
            market_data=market_data,
            forward_returns=forward_returns,
            blacklist=set(blacklist),
        )
        stats["passed_gate_full"] = len(passed_factors)

    except Exception as exc:
        logger.error("完整 Gate 异常，跳过", error=str(exc), exc_info=True)
        passed_factors = []
        stats["passed_gate_full"] = 0

    # ------------------------------------------------------------------
    # Step 5: 写入 DB（fallback 到 JSON）
    # ------------------------------------------------------------------
    logger.info("Step 5: 写入结果到 DB...")
    config_dict = {
        "n_islands": args.islands,
        "population_per_island": args.population,
        "n_generations": args.generations,
        "time_budget_minutes": args.time_budget,
    }

    db_ok = await _write_to_db(
        db_url=db_url,
        run_id=run_id,
        config_dict=config_dict,
        stats=stats,
        passed_factors=passed_factors,
        status="completed" if not overall_error else "failed",
        error_message=overall_error,
    )

    if not db_ok:
        logger.warning("DB 写入失败，使用 JSON fallback")

    # ------------------------------------------------------------------
    # Step 6: 钉钉通知
    # ------------------------------------------------------------------
    logger.info("Step 6: 发送钉钉通知...")
    _send_dingtalk_notification(
        webhook_url=dingtalk_webhook,
        secret=dingtalk_secret,
        run_id=run_id,
        stats=stats,
        passed_factors=passed_factors,
        error=overall_error,
    )

    # ------------------------------------------------------------------
    # Step 7: 保存本轮结果供下轮使用
    # ------------------------------------------------------------------
    logger.info("Step 7: 保存本轮结果...")
    _save_run_result(
        output_dir=args.output_dir,
        run_id=run_id,
        top_factors=passed_factors,
        blacklist=blacklist,  # 本轮未新增 reject，blacklist 不变
        stats=stats,
    )

    elapsed = time.monotonic() - start_time
    logger.info(
        "GP Pipeline 完成",
        run_id=run_id,
        total_elapsed_min=round(elapsed / 60, 1),
        passed_factors=len(passed_factors),
        stats=stats,
    )
    return 0


def main() -> None:
    """脚本入口。"""
    # 初始化 structlog（JSON格式，写入 logs/gp_pipeline.log）
    _setup_logging()

    args = _parse_args()

    exit_code = asyncio.run(_run_pipeline_async(args))
    sys.exit(exit_code)


def _setup_logging() -> None:
    """配置 structlog JSON 日志。

    输出到 stdout（Task Scheduler 重定向到日志文件）。
    """
    import structlog

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    # 也配置标准 logging（依赖 logging 的库）
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


if __name__ == "__main__":
    main()
