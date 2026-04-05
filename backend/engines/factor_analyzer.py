"""因子分析引擎 -- 单因子完整分析 + 因子健康日检。

提供给Dashboard和因子健康日报使用:
- 单因子IC时序、分组收益、IC衰减、相关矩阵、覆盖率
- 每日因子健康检查（Paper Trading用）
- 因子间截面相关矩阵

遵循CLAUDE.md: IC使用沪深300超额收益、复权价格。
"""

from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import structlog
from scipy import stats

logger = structlog.get_logger(__name__)


class FactorAnalyzer:
    """因子分析器。

    提供单因子完整分析报告和每日健康检查。
    所有方法使用同步psycopg2连接（脚本/pipeline场景）。
    """

    def __init__(self, conn: Any) -> None:
        """初始化因子分析器。

        Args:
            conn: psycopg2数据库连接。
        """
        self.conn = conn

    def analyze_single_factor(
        self,
        factor_name: str,
        start_date: date,
        end_date: date,
    ) -> dict[str, Any]:
        """单因子完整分析报告。

        Args:
            factor_name: 因子名称。
            start_date: 分析起始日期。
            end_date: 分析结束日期。

        Returns:
            包含以下键的字典:
            - ic_series: 月度IC时序 (list[dict])
            - ic_mean: IC均值
            - ic_std: IC标准差
            - ir: IC信息比率 (ic_mean / ic_std)
            - t_stat: IC的t统计量
            - ic_decay: IC衰减 (1/5/10/20日)
            - quintile_returns: 分组收益(5组单调性)
            - correlation: 与其他因子的相关系数
            - coverage: 覆盖率统计
        """
        result: dict[str, Any] = {"factor_name": factor_name}

        # 加载因子值和收益数据
        factor_df = self._load_factor_data(factor_name, start_date, end_date)
        if factor_df.empty:
            logger.warning("因子 %s 在 [%s, %s] 无数据", factor_name, start_date, end_date)
            result["error"] = "no_data"
            return result

        returns_df = self._load_excess_returns(start_date, end_date)
        if returns_df.empty:
            logger.warning("收益数据在 [%s, %s] 为空", start_date, end_date)
            result["error"] = "no_returns"
            return result

        # IC时序（月度）
        ic_monthly = self._calc_ic_series(factor_df, returns_df, freq="monthly")
        result["ic_series"] = ic_monthly
        ic_values = [r["ic"] for r in ic_monthly if r["ic"] is not None]

        if ic_values:
            ic_arr = np.array(ic_values)
            result["ic_mean"] = float(np.mean(ic_arr))
            result["ic_std"] = float(np.std(ic_arr, ddof=1)) if len(ic_arr) > 1 else 0.0
            result["ir"] = result["ic_mean"] / result["ic_std"] if result["ic_std"] > 0 else 0.0
            n = len(ic_arr)
            result["t_stat"] = (
                result["ic_mean"] / (result["ic_std"] / np.sqrt(n))
                if result["ic_std"] > 0 and n > 1
                else 0.0
            )
        else:
            result["ic_mean"] = 0.0
            result["ic_std"] = 0.0
            result["ir"] = 0.0
            result["t_stat"] = 0.0

        # IC衰减 (1/5/10/20日)
        result["ic_decay"] = self._calc_ic_decay(factor_df, returns_df, horizons=[1, 5, 10, 20])

        # 分组收益（5组）
        result["quintile_returns"] = self._calc_quintile_returns(factor_df, returns_df)

        # 与其他因子的相关矩阵（取最近一个截面）
        result["correlation"] = self._calc_factor_correlation(factor_name, end_date)

        # 覆盖率统计
        result["coverage"] = self._calc_coverage(factor_name, start_date, end_date)

        return result

    def daily_health_check(
        self,
        factor_names: list[str],
        trade_date: date,
    ) -> dict[str, Any]:
        """因子健康日检（给Paper Trading用）。

        Args:
            factor_names: 因子名称列表。
            trade_date: 检查日期。

        Returns:
            包含以下键的字典:
            - date: 检查日期
            - factors: dict[factor_name, factor_health]
            - cross_correlation: 因子间截面相关变化
            - overall_status: 'healthy' / 'warning' / 'critical'
        """
        result: dict[str, Any] = {
            "date": trade_date.isoformat(),
            "factors": {},
            "overall_status": "healthy",
        }

        # 加载近20日的因子数据和收益
        lookback_start = trade_date - timedelta(days=40)  # 多拉以覆盖交易日
        returns_df = self._load_excess_returns(lookback_start, trade_date)

        warnings = 0
        criticals = 0

        for fname in factor_names:
            fhealth: dict[str, Any] = {"factor_name": fname}

            # 加载因子数据
            factor_df = self._load_factor_data(fname, lookback_start, trade_date)
            if factor_df.empty:
                fhealth["status"] = "critical"
                fhealth["reason"] = "no_data"
                criticals += 1
                result["factors"][fname] = fhealth
                continue

            # 当日IC（与前5日收益的rank IC）
            fhealth["daily_ic"] = self._calc_single_day_ic(
                factor_df, returns_df, trade_date, horizon=5
            )

            # 20日滚动IC趋势
            rolling_ic = self._calc_rolling_ic(
                factor_df, returns_df, trade_date, window=20, horizon=5
            )
            fhealth["rolling_ic_20d"] = rolling_ic

            # 覆盖率
            coverage = self._calc_single_day_coverage(fname, trade_date)
            fhealth["coverage"] = coverage

            # 状态判断
            status = "healthy"
            reasons = []
            if fhealth["daily_ic"] is not None and abs(fhealth["daily_ic"]) < 0.005:
                reasons.append(f"daily_ic={fhealth['daily_ic']:.4f}")
                status = "warning"
            if rolling_ic and rolling_ic[-1] is not None and abs(rolling_ic[-1]) < 0.01:
                reasons.append("rolling_ic_weak")
                status = "warning"
            if coverage is not None and coverage < 0.8:
                reasons.append(f"coverage={coverage:.1%}")
                status = "critical" if coverage < 0.5 else "warning"

            fhealth["status"] = status
            fhealth["reasons"] = reasons
            if status == "warning":
                warnings += 1
            elif status == "critical":
                criticals += 1

            result["factors"][fname] = fhealth

        # 因子间相关性
        result["cross_correlation"] = self.factor_correlation_matrix(factor_names, trade_date)

        # 总体状态
        if criticals > 0:
            result["overall_status"] = "critical"
        elif warnings >= len(factor_names) // 2:
            result["overall_status"] = "warning"

        return result

    def factor_correlation_matrix(
        self,
        factor_names: list[str],
        trade_date: date,
    ) -> pd.DataFrame:
        """因子间截面相关矩阵。

        Args:
            factor_names: 因子名称列表。
            trade_date: 日期。

        Returns:
            因子间Spearman相关矩阵 (DataFrame)。
        """
        df = pd.read_sql(
            """SELECT code, factor_name, neutral_value
               FROM factor_values
               WHERE trade_date = %s AND factor_name = ANY(%s)""",
            self.conn,
            params=(trade_date, factor_names),
        )

        if df.empty:
            return pd.DataFrame()

        pivot = df.pivot_table(index="code", columns="factor_name", values="neutral_value")

        if pivot.shape[1] < 2:
            return pd.DataFrame()

        # Spearman相关（CLAUDE.md: 去重基于Spearman相关性>0.7判定重复）
        corr = pivot.rank().corr(method="pearson")
        return corr

    # ────────────────────── 内部方法 ──────────────────────

    def _load_factor_data(self, factor_name: str, start_date: date, end_date: date) -> pd.DataFrame:
        """加载因子值。"""
        return pd.read_sql(
            """SELECT code, trade_date, neutral_value
               FROM factor_values
               WHERE factor_name = %s AND trade_date BETWEEN %s AND %s""",
            self.conn,
            params=(factor_name, start_date, end_date),
        )

    def _load_excess_returns(self, start_date: date, end_date: date) -> pd.DataFrame:
        """加载超额收益（相对沪深300）。

        CLAUDE.md: forward return使用相对沪深300的超额收益。
        使用复权价格计算。
        """
        # 个股收益（复权）
        stock_ret = pd.read_sql(
            """SELECT code, trade_date,
                      (close * adj_factor) /
                      LAG(close * adj_factor) OVER (PARTITION BY code ORDER BY trade_date) - 1
                      AS ret
               FROM klines_daily
               WHERE trade_date BETWEEN %s AND %s AND volume > 0
               ORDER BY trade_date, code""",
            self.conn,
            params=(start_date, end_date),
        )

        # 沪深300收益
        bench_ret = pd.read_sql(
            """SELECT trade_date,
                      close / LAG(close) OVER (ORDER BY trade_date) - 1 AS bench_ret
               FROM index_daily
               WHERE index_code = '000300.SH'
                 AND trade_date BETWEEN %s AND %s
               ORDER BY trade_date""",
            self.conn,
            params=(start_date, end_date),
        )

        if stock_ret.empty or bench_ret.empty:
            return pd.DataFrame()

        merged = stock_ret.merge(bench_ret, on="trade_date", how="left")
        merged["excess_ret"] = merged["ret"] - merged["bench_ret"].fillna(0)

        return merged[["code", "trade_date", "excess_ret"]].dropna()

    def _calc_ic_series(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        freq: str = "monthly",
    ) -> list[dict[str, Any]]:
        """计算IC时序（Rank IC = Spearman相关系数）。"""
        # 对齐: 因子值 T日 vs 收益 T+1日（即因子预测次日收益）
        factor_df = factor_df.copy()
        returns_df = returns_df.copy()

        # 合并: 因子T日 + 收益T+1~T+5日（用5日forward return）
        ic_list: list[dict[str, Any]] = []

        # 按月分组
        factor_df["month"] = factor_df["trade_date"].apply(
            lambda d: (d.year, d.month) if hasattr(d, "year") else (d.year, d.month)
        )

        for month_key, group in factor_df.groupby("month"):
            # 取月末截面
            last_date = group["trade_date"].max()
            cross_section = group[group["trade_date"] == last_date]

            # 对应5日后的收益
            future_date = last_date + timedelta(days=7)  # 近似5个交易日
            future_rets = returns_df[
                (returns_df["trade_date"] > last_date) & (returns_df["trade_date"] <= future_date)
            ]

            if future_rets.empty:
                continue

            # 累积5日超额收益
            cum_ret = future_rets.groupby("code")["excess_ret"].sum()

            # 计算Rank IC
            merged = cross_section.set_index("code")["neutral_value"].to_frame()
            merged = merged.join(cum_ret.rename("fwd_ret"), how="inner")
            merged = merged.dropna()

            if len(merged) < 30:  # 样本太少不可靠
                continue

            ic, _ = stats.spearmanr(merged["neutral_value"], merged["fwd_ret"])
            ic_list.append(
                {
                    "month": f"{month_key[0]}-{month_key[1]:02d}",
                    "date": last_date.isoformat()
                    if hasattr(last_date, "isoformat")
                    else str(last_date),
                    "ic": float(ic) if not np.isnan(ic) else None,
                    "n_stocks": len(merged),
                }
            )

        return ic_list

    def _calc_ic_decay(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        horizons: list[int],
    ) -> dict[int, float]:
        """计算IC衰减（不同持仓周期的IC均值）。"""
        decay: dict[int, float] = {}
        dates = sorted(factor_df["trade_date"].unique())

        for h in horizons:
            ic_values: list[float] = []

            for dt in dates:
                cross_section = factor_df[factor_df["trade_date"] == dt]
                future_end = dt + timedelta(days=int(h * 1.5))  # 近似交易日
                future_rets = returns_df[
                    (returns_df["trade_date"] > dt) & (returns_df["trade_date"] <= future_end)
                ]
                if future_rets.empty:
                    continue

                cum_ret = future_rets.groupby("code")["excess_ret"].sum()
                merged = cross_section.set_index("code")["neutral_value"].to_frame()
                merged = merged.join(cum_ret.rename("fwd_ret"), how="inner").dropna()

                if len(merged) < 30:
                    continue

                ic, _ = stats.spearmanr(merged["neutral_value"], merged["fwd_ret"])
                if not np.isnan(ic):
                    ic_values.append(float(ic))

            decay[h] = float(np.mean(ic_values)) if ic_values else 0.0

        return decay

    def _calc_quintile_returns(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
    ) -> list[dict[str, float]]:
        """计算分组收益（5组单调性检验）。"""
        dates = sorted(factor_df["trade_date"].unique())
        group_rets: dict[int, list[float]] = {g: [] for g in range(1, 6)}

        for dt in dates:
            cs = factor_df[factor_df["trade_date"] == dt].copy()
            future_end = dt + timedelta(days=7)
            future_rets = returns_df[
                (returns_df["trade_date"] > dt) & (returns_df["trade_date"] <= future_end)
            ]
            if future_rets.empty or len(cs) < 50:
                continue

            cum_ret = future_rets.groupby("code")["excess_ret"].sum()
            cs = cs.set_index("code")
            cs = cs.join(cum_ret.rename("fwd_ret"), how="inner").dropna()

            if len(cs) < 50:
                continue

            # 5分位
            cs["quintile"] = pd.qcut(cs["neutral_value"], 5, labels=False, duplicates="drop") + 1

            for q in range(1, 6):
                qr = cs[cs["quintile"] == q]["fwd_ret"]
                if not qr.empty:
                    group_rets[q].append(float(qr.mean()))

        result = []
        for q in range(1, 6):
            vals = group_rets[q]
            result.append(
                {
                    "quintile": q,
                    "mean_return": float(np.mean(vals)) if vals else 0.0,
                    "count": len(vals),
                }
            )

        return result

    def _calc_factor_correlation(self, factor_name: str, ref_date: date) -> dict[str, float]:
        """计算与其他所有因子的截面相关。"""
        df = pd.read_sql(
            """SELECT code, factor_name, neutral_value
               FROM factor_values WHERE trade_date = %s""",
            self.conn,
            params=(ref_date,),
        )
        if df.empty:
            return {}

        pivot = df.pivot_table(index="code", columns="factor_name", values="neutral_value")
        if factor_name not in pivot.columns:
            return {}

        corr_dict: dict[str, float] = {}
        for col in pivot.columns:
            if col == factor_name:
                continue
            valid = pivot[[factor_name, col]].dropna()
            if len(valid) < 30:
                continue
            r, _ = stats.spearmanr(valid[factor_name], valid[col])
            if not np.isnan(r):
                corr_dict[col] = round(float(r), 4)

        return corr_dict

    def _calc_coverage(self, factor_name: str, start_date: date, end_date: date) -> dict[str, Any]:
        """覆盖率统计。"""
        df = pd.read_sql(
            """SELECT fv.trade_date,
                      COUNT(fv.code) AS factor_count,
                      total.total_count
               FROM factor_values fv
               JOIN (
                   SELECT trade_date, COUNT(DISTINCT code) AS total_count
                   FROM klines_daily
                   WHERE trade_date BETWEEN %s AND %s AND volume > 0
                   GROUP BY trade_date
               ) total ON fv.trade_date = total.trade_date
               WHERE fv.factor_name = %s
                 AND fv.trade_date BETWEEN %s AND %s
               GROUP BY fv.trade_date, total.total_count
               ORDER BY fv.trade_date""",
            self.conn,
            params=(start_date, end_date, factor_name, start_date, end_date),
        )

        if df.empty:
            return {"mean_coverage": 0.0, "min_coverage": 0.0, "dates_with_data": 0}

        df["coverage"] = df["factor_count"] / df["total_count"].clip(lower=1)
        return {
            "mean_coverage": round(float(df["coverage"].mean()), 4),
            "min_coverage": round(float(df["coverage"].min()), 4),
            "max_coverage": round(float(df["coverage"].max()), 4),
            "dates_with_data": int(len(df)),
        }

    def _calc_single_day_ic(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        trade_date: date,
        horizon: int = 5,
    ) -> float | None:
        """计算单日IC。"""
        cs = factor_df[factor_df["trade_date"] == trade_date]
        if cs.empty:
            return None

        future_end = trade_date + timedelta(days=int(horizon * 1.5))
        future_rets = returns_df[
            (returns_df["trade_date"] > trade_date) & (returns_df["trade_date"] <= future_end)
        ]
        if future_rets.empty:
            return None

        cum_ret = future_rets.groupby("code")["excess_ret"].sum()
        merged = cs.set_index("code")["neutral_value"].to_frame()
        merged = merged.join(cum_ret.rename("fwd_ret"), how="inner").dropna()

        if len(merged) < 30:
            return None

        ic, _ = stats.spearmanr(merged["neutral_value"], merged["fwd_ret"])
        return float(ic) if not np.isnan(ic) else None

    def _calc_rolling_ic(
        self,
        factor_df: pd.DataFrame,
        returns_df: pd.DataFrame,
        trade_date: date,
        window: int = 20,
        horizon: int = 5,
    ) -> list[float | None]:
        """计算滚动IC趋势。"""
        dates = sorted(factor_df["trade_date"].unique())
        # 取最近window个日期
        dates = [d for d in dates if d <= trade_date][-window:]

        rolling: list[float | None] = []
        for dt in dates:
            ic = self._calc_single_day_ic(factor_df, returns_df, dt, horizon)
            rolling.append(ic)

        return rolling

    def _calc_single_day_coverage(self, factor_name: str, trade_date: date) -> float | None:
        """计算单日覆盖率。"""
        df = pd.read_sql(
            """SELECT
                 (SELECT COUNT(*) FROM factor_values
                  WHERE factor_name = %s AND trade_date = %s) AS fcount,
                 (SELECT COUNT(DISTINCT code) FROM klines_daily
                  WHERE trade_date = %s AND volume > 0) AS tcount""",
            self.conn,
            params=(factor_name, trade_date, trade_date),
        )
        if df.empty or df.iloc[0]["tcount"] == 0:
            return None
        return float(df.iloc[0]["fcount"] / df.iloc[0]["tcount"])
