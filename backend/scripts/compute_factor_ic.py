"""因子IC批量计算脚本。

对factor_values中的因子批量计算Rank IC（Spearman相关系数），
写入factor_ic_history表，并更新factor_registry的gate汇总统计。

用法:
    python compute_factor_ic.py                      # 计算所有因子，最近2年
    python compute_factor_ic.py --factor bp_ratio    # 只算1个因子
    python compute_factor_ic.py --start 2022-01-01   # 自定义起始日期
    python compute_factor_ic.py --dry-run            # 只计算不写库

设计说明:
- IC定义: Rank IC = Spearman(neutral_value_t, forward_return_t+N)
- forward_return: 使用adj_factor复权的真实收益率（非超额），因子IC本身反映预测力
- 数据对齐: 用交易日历（klines_daily的distinct dates）计算精确N日后收益
- 写入策略: INSERT ... ON CONFLICT DO UPDATE（幂等，可重跑）
- gate_ic/gate_ir/gate_t更新: 用ic_20d的全期均值/IR/t统计
"""

import argparse
import logging
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from scipy import stats

# ─── 日志配置 ────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─── 常量 ────────────────────────────────────────────────────────────────────

def _get_db_dsn() -> dict:
    """从 .env 或环境变量读取数据库连接信息，避免硬编码凭证。"""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    # asyncpg URL: postgresql+asyncpg://user:pass@host:port/db
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # 解析 postgresql+asyncpg://user:pass@host:port/dbname
        import re
        m = re.match(r"postgresql\+?\w*://(\w+):([^@]+)@([^:]+):(\d+)/(\w+)", url)
        if m:
            return dict(user=m.group(1), password=m.group(2), host=m.group(3),
                        port=int(m.group(4)), dbname=m.group(5))
    return dict(
        dbname=os.environ.get("DB_NAME", "quantmind_v2"),
        user=os.environ.get("DB_USER", "xin"),
        password=os.environ.get("DB_PASSWORD", ""),
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
    )


DB_DSN = _get_db_dsn()

# v1.1策略的5个核心因子优先计算，其余因子按名称排序
V1_1_FACTORS = [
    "bp_ratio",
    "amihud_20",
    "turnover_mean_20",
    "reversal_20",
    "volatility_20",
]

HORIZONS = [1, 5, 10, 20]  # 计算IC的持仓周期（交易日数）

MIN_STOCKS = 30  # 截面有效样本最低要求

DECAY_THRESHOLDS = {
    "fast": 5,    # ic在5日窗口衰减超过50%
    "medium": 10,
    "slow": 20,
}

# ─── 数据库工具函数 ───────────────────────────────────────────────────────────


def get_conn() -> psycopg2.extensions.connection:
    """建立数据库连接。"""
    return psycopg2.connect(**DB_DSN)


def load_trading_dates(conn, start_date: date, end_date: date) -> list[date]:
    """从klines_daily取全部交易日（去重排序）。

    Args:
        conn: psycopg2连接。
        start_date: 起始日（含）。
        end_date: 截止日（含）。

    Returns:
        交易日列表，升序排列。
    """
    cur = conn.cursor()
    cur.execute(
        """SELECT DISTINCT trade_date FROM klines_daily
           WHERE trade_date BETWEEN %s AND %s
           ORDER BY trade_date""",
        (start_date, end_date),
    )
    return [r[0] for r in cur.fetchall()]


def load_adj_returns(conn, start_date: date, end_date: date) -> pd.DataFrame:
    """加载复权后日收益率。

    使用 close * adj_factor 计算真实价格，然后算日收益。
    注意：SQL窗口函数LAG在Python端用shift实现更可靠（避免窗口函数边界问题）。

    Args:
        conn: psycopg2连接。
        start_date: 起始日（含，需比因子起始日早至少20个交易日以便计算forward return）。
        end_date: 截止日（含）。

    Returns:
        DataFrame with columns [code, trade_date, adj_close]。
    """
    logger.info("加载复权收盘价: %s ~ %s ...", start_date, end_date)
    df = pd.read_sql(
        """SELECT code, trade_date, close * adj_factor AS adj_close
           FROM klines_daily
           WHERE trade_date BETWEEN %s AND %s
             AND volume > 0
             AND is_suspended = FALSE
             AND close > 0
             AND adj_factor > 0
           ORDER BY code, trade_date""",
        conn,
        params=(start_date, end_date),
    )
    logger.info("  复权价格: %d 行, %d 只股票", len(df), df["code"].nunique())
    return df


def compute_forward_returns(
    adj_close_df: pd.DataFrame,
    trading_dates: list[date],
    horizons: list[int],
) -> pd.DataFrame:
    """计算各交易日的多期forward return。

    使用精确的交易日历（不用calendar days近似）。

    Args:
        adj_close_df: [code, trade_date, adj_close]。
        trading_dates: 全部交易日列表。
        horizons: 持仓周期列表，如 [1, 5, 10, 20]。

    Returns:
        DataFrame with columns [code, trade_date, fwd_1d, fwd_5d, fwd_10d, fwd_20d]。
        trade_date是买入日（T日），fwd_Nd是T+N日收益率。
    """
    logger.info("计算forward return，周期: %s ...", horizons)

    # 构建 pivot: trade_date行 × code列
    pivot = adj_close_df.pivot(index="trade_date", columns="code", values="adj_close")
    pivot = pivot.sort_index()

    result_frames = []
    for h in horizons:
        # 计算N日后收益: P(T+N)/P(T) - 1
        shifted = pivot.shift(-h)  # shift向上 = N日后的价格
        fwd_ret = (shifted / pivot) - 1.0
        fwd_ret = fwd_ret.stack().reset_index()
        fwd_ret.columns = pd.Index(["trade_date", "code", f"fwd_{h}d"])
        result_frames.append(fwd_ret)

    # 合并所有周期
    merged = result_frames[0]
    for df in result_frames[1:]:
        merged = merged.merge(df, on=["trade_date", "code"], how="outer")

    # 去掉全NA行
    fwd_cols = [f"fwd_{h}d" for h in horizons]
    merged = merged.dropna(subset=fwd_cols, how="all")

    logger.info("  Forward return计算完毕: %d 行", len(merged))
    return merged


def load_factor_values(
    conn,
    factor_name: str,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    """加载因子中性化后的值（与回测universe一致的过滤）。

    过滤条件（对齐run_backtest.py load_universe）:
    - 排除ST/*ST股票
    - 排除上市不足60日的新股
    - 排除总市值<100亿的小盘股
    - 排除停牌股（volume=0）
    - 只保留正常上市状态（list_status='L'）

    Args:
        conn: psycopg2连接。
        factor_name: 因子名称。
        start_date: 起始日（含）。
        end_date: 截止日（含）。

    Returns:
        DataFrame with columns [code, trade_date, neutral_value]。
    """
    df = pd.read_sql(
        """SELECT f.code, f.trade_date, f.neutral_value
           FROM factor_values f
           JOIN symbols s ON f.code = s.code
           JOIN klines_daily k ON f.code = k.code AND f.trade_date = k.trade_date
           LEFT JOIN daily_basic db ON f.code = db.code AND f.trade_date = db.trade_date
           WHERE f.factor_name = %s
             AND f.trade_date BETWEEN %s AND %s
             AND f.neutral_value IS NOT NULL
             -- 与回测universe一致的过滤
             AND s.list_status = 'L'
             AND s.name NOT LIKE '%%ST%%'
             AND (s.list_date IS NULL OR s.list_date <= f.trade_date - INTERVAL '60 days')
             AND COALESCE(db.total_mv, 0) > 100000
             AND k.volume > 0""",
        conn,
        params=(factor_name, start_date, end_date),
    )
    return df


# ─── IC计算核心逻辑 ───────────────────────────────────────────────────────────


def compute_ic_for_factor(
    factor_df: pd.DataFrame,
    fwd_ret_df: pd.DataFrame,
    trading_dates: list[date],
    horizons: list[int],
    factor_name: str,
) -> pd.DataFrame:
    """对单个因子按日计算Rank IC。

    Args:
        factor_df: [code, trade_date, neutral_value]。
        fwd_ret_df: [code, trade_date, fwd_1d, fwd_5d, fwd_10d, fwd_20d]。
        trading_dates: 有序交易日列表（用于进度报告）。
        horizons: IC计算周期列表。
        factor_name: 用于日志。

    Returns:
        DataFrame with columns [trade_date, ic_1d, ic_5d, ic_10d, ic_20d]，
        每个trade_date对应当天因子截面与各forward return的Spearman相关。
    """
    # 合并因子值和forward return（内连接：两边都有数据才算）
    merged = factor_df.merge(fwd_ret_df, on=["code", "trade_date"], how="inner")

    if merged.empty:
        logger.warning("  %s: 因子值与forward return无交集", factor_name)
        return pd.DataFrame()

    factor_dates = sorted(merged["trade_date"].unique())
    records = []
    processed = 0

    for dt in factor_dates:
        cross = merged[merged["trade_date"] == dt].dropna(subset=["neutral_value"])

        if len(cross) < MIN_STOCKS:
            continue

        row: dict = {"trade_date": dt}
        for h in horizons:
            col = f"fwd_{h}d"
            valid = cross[["neutral_value", col]].dropna()
            if len(valid) < MIN_STOCKS:
                row[f"ic_{h}d"] = None
                continue
            ic_val, _ = stats.spearmanr(valid["neutral_value"], valid[col])
            row[f"ic_{h}d"] = float(ic_val) if not np.isnan(ic_val) else None

        records.append(row)
        processed += 1

        if processed % 100 == 0:
            logger.info(
                "  %s: 已处理 %d/%d 个交易日 (当前: %s)",
                factor_name, processed, len(factor_dates), dt,
            )

    if not records:
        return pd.DataFrame()

    ic_df = pd.DataFrame(records)
    ic_df = ic_df.sort_values("trade_date").reset_index(drop=True)
    logger.info("  %s: IC计算完成，共 %d 个交易日", factor_name, len(ic_df))
    return ic_df


def enrich_ic_df(ic_df: pd.DataFrame) -> pd.DataFrame:
    """在IC时序上计算衍生指标。

    新增字段:
    - ic_abs_1d, ic_abs_5d: 绝对值IC
    - ic_ma20, ic_ma60: 20/60日滚动均值（基于ic_20d）
    - decay_level: 衰减速度（fast/medium/slow/stable）

    Args:
        ic_df: [trade_date, ic_1d, ic_5d, ic_10d, ic_20d]。

    Returns:
        enriched DataFrame。
    """
    df = ic_df.copy()

    df["ic_abs_1d"] = pd.to_numeric(df["ic_1d"], errors="coerce").abs() if "ic_1d" in df.columns else np.nan
    df["ic_abs_5d"] = pd.to_numeric(df["ic_5d"], errors="coerce").abs() if "ic_5d" in df.columns else np.nan

    # 滚动均值（min_periods=5避免首期噪音）
    df["ic_ma20"] = df["ic_20d"].rolling(window=20, min_periods=5).mean()
    df["ic_ma60"] = df["ic_20d"].rolling(window=60, min_periods=10).mean()

    # 衰减速度判断：比较各周期IC绝对均值
    ic_means = {
        h: df[f"ic_{h}d"].dropna().abs().mean()
        for h in HORIZONS
        if f"ic_{h}d" in df.columns
    }

    if all(v is not None and not np.isnan(v) for v in ic_means.values()):
        # 1d IC比20d IC下降比例
        if ic_means.get(1, 0) > 0:
            decay_ratio_5 = (ic_means.get(1, 0) - ic_means.get(5, 0)) / ic_means.get(1, 0)
            decay_ratio_20 = (ic_means.get(1, 0) - ic_means.get(20, 0)) / ic_means.get(1, 0)

            if decay_ratio_5 > 0.5:
                decay_level = "fast"
            elif decay_ratio_20 > 0.5:
                decay_level = "medium"
            elif decay_ratio_20 > 0.1:
                decay_level = "slow"
            else:
                decay_level = "stable"
        else:
            decay_level = "unknown"
    else:
        decay_level = "unknown"

    df["decay_level"] = decay_level
    return df


# ─── 写库函数 ─────────────────────────────────────────────────────────────────


def upsert_ic_history(
    conn,
    factor_name: str,
    ic_df: pd.DataFrame,
    dry_run: bool = False,
) -> int:
    """将IC结果写入factor_ic_history（幂等upsert）。

    Args:
        conn: psycopg2连接。
        factor_name: 因子名称。
        ic_df: enriched IC DataFrame。
        dry_run: 若True只打印不写库。

    Returns:
        写入行数。
    """
    if ic_df.empty:
        return 0

    rows = []
    for _, row in ic_df.iterrows():
        rows.append((
            factor_name,
            row["trade_date"],
            _safe_float(row.get("ic_1d")),
            _safe_float(row.get("ic_5d")),
            _safe_float(row.get("ic_10d")),
            _safe_float(row.get("ic_20d")),
            _safe_float(row.get("ic_abs_1d")),
            _safe_float(row.get("ic_abs_5d")),
            _safe_float(row.get("ic_ma20")),
            _safe_float(row.get("ic_ma60")),
            str(row.get("decay_level", "unknown")),
        ))

    if dry_run:
        logger.info(
            "  [DRY-RUN] %s: 将写入 %d 行到 factor_ic_history（示例: %s）",
            factor_name, len(rows), rows[0] if rows else "无",
        )
        return len(rows)

    upsert_sql = """
        INSERT INTO factor_ic_history
            (factor_name, trade_date, ic_1d, ic_5d, ic_10d, ic_20d,
             ic_abs_1d, ic_abs_5d, ic_ma20, ic_ma60, decay_level)
        VALUES %s
        ON CONFLICT (factor_name, trade_date) DO UPDATE SET
            ic_1d      = EXCLUDED.ic_1d,
            ic_5d      = EXCLUDED.ic_5d,
            ic_10d     = EXCLUDED.ic_10d,
            ic_20d     = EXCLUDED.ic_20d,
            ic_abs_1d  = EXCLUDED.ic_abs_1d,
            ic_abs_5d  = EXCLUDED.ic_abs_5d,
            ic_ma20    = EXCLUDED.ic_ma20,
            ic_ma60    = EXCLUDED.ic_ma60,
            decay_level = EXCLUDED.decay_level
    """

    cur = conn.cursor()
    psycopg2.extras.execute_values(cur, upsert_sql, rows, page_size=500)
    conn.commit()
    logger.info("  %s: 写入 %d 行到 factor_ic_history", factor_name, len(rows))
    return len(rows)


def update_factor_registry(
    conn,
    factor_name: str,
    ic_df: pd.DataFrame,
    dry_run: bool = False,
) -> None:
    """更新factor_registry中的gate统计字段。

    gate_ic  = ic_20d均值
    gate_ir  = ic_20d均值 / ic_20d标准差 (IC IR)
    gate_t   = ic_20d均值 / (ic_20d标准差 / sqrt(N))  (t统计量)
    gate_mono不在此处更新（需要分组收益单调性检验，属于另一模块）

    Args:
        conn: psycopg2连接。
        factor_name: 因子名称。
        ic_df: enriched IC DataFrame。
        dry_run: 若True只打印。
    """
    ic_vals = ic_df["ic_20d"].dropna()
    if len(ic_vals) < 2:
        logger.warning("  %s: ic_20d有效数据点不足2个，跳过factor_registry更新", factor_name)
        return

    ic_mean = float(ic_vals.mean())
    ic_std = float(ic_vals.std(ddof=1))
    n = len(ic_vals)

    gate_ic = float(round(ic_mean, 6))
    gate_ir = float(round(ic_mean / ic_std, 4)) if ic_std > 0 else 0.0
    gate_t = float(round(ic_mean / (ic_std / np.sqrt(n)), 4)) if ic_std > 0 else 0.0

    logger.info(
        "  %s 汇总统计: IC均值=%.4f, IC_IR=%.4f, t_stat=%.4f, N=%d",
        factor_name, gate_ic, gate_ir, gate_t, n,
    )

    if dry_run:
        logger.info("  [DRY-RUN] 将更新 factor_registry: gate_ic=%s, gate_ir=%s, gate_t=%s",
                    gate_ic, gate_ir, gate_t)
        return

    cur = conn.cursor()
    cur.execute(
        """UPDATE factor_registry
           SET gate_ic = %s, gate_ir = %s, gate_t = %s, updated_at = NOW()
           WHERE name = %s""",
        (gate_ic, gate_ir, gate_t, factor_name),
    )
    rows_updated = cur.rowcount
    conn.commit()

    if rows_updated == 0:
        logger.warning("  %s: factor_registry中未找到该因子记录（name=%s）", factor_name, factor_name)
    else:
        logger.info("  %s: factor_registry已更新 (gate_ic=%.4f, gate_t=%.4f)",
                    factor_name, gate_ic, gate_t)


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────


def _safe_float(val) -> float | None:
    """将值安全转换为float，NaN/None返回None。"""
    if val is None:
        return None
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def print_summary(results: dict[str, dict]) -> None:
    """打印所有因子IC汇总表格。"""
    print("\n" + "=" * 75)
    print(f"{'因子名称':<25} {'IC均值(20d)':>12} {'IC_IR':>8} {'t统计量':>10} {'N':>6} {'衰减':>8}")
    print("-" * 75)
    for fname, stats_dict in sorted(results.items()):
        if "error" in stats_dict:
            print(f"{fname:<25} {'ERROR: ' + stats_dict['error']}")
            continue
        print(
            f"{fname:<25} {stats_dict.get('ic_mean', 0):>12.4f} "
            f"{stats_dict.get('ic_ir', 0):>8.4f} "
            f"{stats_dict.get('t_stat', 0):>10.4f} "
            f"{stats_dict.get('n', 0):>6d} "
            f"{stats_dict.get('decay_level', '?'):>8}"
        )
    print("=" * 75)

    # 铁律检查：t > 2.5 硬性标准
    print("\n因子审批链检查（铁律: t > 2.5）:")
    for fname, s in sorted(results.items()):
        if "error" in s:
            continue
        t = s.get("t_stat", 0)
        status = "PASS" if t > 2.5 else ("WARN" if t > 2.0 else "FAIL")
        print(f"  {status} {fname}: t={t:.4f}")


# ─── 主流程 ───────────────────────────────────────────────────────────────────


def run(
    factors: list[str],
    start_date: date,
    end_date: date,
    dry_run: bool,
) -> None:
    """主执行函数。

    Args:
        factors: 要计算的因子名称列表。
        start_date: 因子值起始日。
        end_date: 截止日。
        dry_run: 不写数据库。
    """
    logger.info("=" * 60)
    logger.info("因子IC批量计算启动")
    logger.info("  因子: %s", factors)
    logger.info("  日期范围: %s ~ %s", start_date, end_date)
    logger.info("  DRY-RUN: %s", dry_run)
    logger.info("=" * 60)

    conn = get_conn()

    # 向前多加1年以便计算因子值起始日之前的forward return基准价格
    klines_start = date(start_date.year - 1, start_date.month, start_date.day)
    klines_end = end_date

    trading_dates = load_trading_dates(conn, klines_start, klines_end)
    logger.info("加载到 %d 个交易日", len(trading_dates))

    # 一次性加载全部复权价格（所有因子共用）
    adj_df = load_adj_returns(conn, klines_start, klines_end)

    # 计算forward returns（一次性，所有因子共用）
    fwd_ret_df = compute_forward_returns(adj_df, trading_dates, HORIZONS)

    # 释放adj_df内存
    del adj_df

    all_results: dict[str, dict] = {}

    for i, factor_name in enumerate(factors):
        logger.info("")
        logger.info("─" * 50)
        logger.info("[%d/%d] 处理因子: %s", i + 1, len(factors), factor_name)
        logger.info("─" * 50)

        try:
            # 加载因子值
            factor_df = load_factor_values(conn, factor_name, start_date, end_date)
            if factor_df.empty:
                logger.warning("  %s: factor_values无数据，跳过", factor_name)
                all_results[factor_name] = {"error": "no_factor_data"}
                continue

            logger.info("  %s: 加载到 %d 行因子数据 (%d 个日期)",
                        factor_name, len(factor_df), factor_df["trade_date"].nunique())

            # 计算Rank IC
            ic_df = compute_ic_for_factor(
                factor_df, fwd_ret_df, trading_dates, HORIZONS, factor_name
            )

            if ic_df.empty:
                logger.warning("  %s: IC计算结果为空，跳过", factor_name)
                all_results[factor_name] = {"error": "ic_empty"}
                continue

            # 计算衍生指标
            ic_df = enrich_ic_df(ic_df)

            # 汇总统计
            ic_vals = ic_df["ic_20d"].dropna()
            ic_mean = float(ic_vals.mean()) if len(ic_vals) > 0 else 0.0
            ic_std = float(ic_vals.std(ddof=1)) if len(ic_vals) > 1 else 0.0
            n = len(ic_vals)
            ic_ir = ic_mean / ic_std if ic_std > 0 else 0.0
            t_stat = ic_mean / (ic_std / np.sqrt(n)) if ic_std > 0 and n > 1 else 0.0
            decay_level = ic_df["decay_level"].iloc[-1] if not ic_df.empty else "unknown"

            all_results[factor_name] = {
                "ic_mean": ic_mean,
                "ic_std": ic_std,
                "ic_ir": ic_ir,
                "t_stat": t_stat,
                "n": n,
                "decay_level": decay_level,
            }

            # 写入factor_ic_history
            upsert_ic_history(conn, factor_name, ic_df, dry_run=dry_run)

            # 更新factor_registry
            update_factor_registry(conn, factor_name, ic_df, dry_run=dry_run)

        except Exception as exc:
            logger.error("  %s: 计算失败 — %s", factor_name, exc, exc_info=True)
            all_results[factor_name] = {"error": str(exc)}
            # 回滚未提交的事务，继续下一个因子
            conn.rollback()

    conn.close()

    # 打印汇总表格
    print_summary(all_results)

    # 数据质量报告
    logger.info("")
    logger.info("数据质量报告:")
    success = sum(1 for v in all_results.values() if "error" not in v)
    failed = len(all_results) - success
    logger.info("  成功: %d 个因子", success)
    logger.info("  失败: %d 个因子", failed)
    if not dry_run:
        logger.info("  factor_ic_history已写入（可用SELECT COUNT(*) FROM factor_ic_history验证）")


# ─── CLI入口 ──────────────────────────────────────────────────────────────────


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(
        description="因子IC批量计算脚本 — 写入factor_ic_history并更新factor_registry"
    )
    parser.add_argument(
        "--factor",
        type=str,
        help="只计算指定因子（默认：v1.1全部5个因子）",
    )
    parser.add_argument(
        "--all-factors",
        action="store_true",
        help="计算factor_values中的所有因子",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="起始日期 YYYY-MM-DD（默认：2年前）",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="截止日期 YYYY-MM-DD（默认：今天）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只计算不写数据库",
    )

    args = parser.parse_args()

    # 确定日期范围
    end_date = date.fromisoformat(args.end) if args.end else date.today()
    if args.start:
        start_date = date.fromisoformat(args.start)
    else:
        # 默认最近2年
        start_date = date(end_date.year - 2, end_date.month, end_date.day)

    # 确定因子列表
    if args.factor:
        factors = [args.factor]
    elif args.all_factors:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")
        factors = [r[0] for r in cur.fetchall()]
        conn.close()
        logger.info("发现 %d 个因子", len(factors))
    else:
        factors = V1_1_FACTORS

    run(
        factors=factors,
        start_date=start_date,
        end_date=end_date,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
