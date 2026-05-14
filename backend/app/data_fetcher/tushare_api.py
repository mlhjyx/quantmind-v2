"""统一Tushare API客户端 — 合并TushareClient + TushareFetcher。

取两者之长:
- TushareClient: 通用query()接口, 指数退避重试
- TushareFetcher: per-API限流间隔(生产验证), 高级fetch方法, structlog

用法:
    api = TushareAPI()
    df = api.query("daily", trade_date="20260408")
    df = api.merge_daily_data("20260408")  # 高级: 合并daily+adj+limit
"""

from __future__ import annotations

import time
from typing import Any

import pandas as pd
import structlog
import tushare as ts

from app.config import settings

logger = structlog.get_logger(__name__)

# Per-API sleep间隔(秒) — 来自TushareFetcher生产验证
SLEEP_INTERVALS: dict[str, float] = {
    "daily": 0.15,
    "adj_factor": 0.15,
    "stk_limit": 0.15,
    "daily_basic": 0.30,
    "index_daily": 0.15,
    "index_weight": 0.30,
    "fina_indicator": 0.30,
    "moneyflow": 0.35,
    "stock_basic": 0.15,
    "trade_cal": 0.15,
    "hk_hold": 0.35,
    "namechange": 0.15,
}
DEFAULT_INTERVAL = 0.20

# V3 §14 mode 7: Tushare 限速 detection — keyword set for rate-limit error classification.
# Module-level constant + pure helper so the disaster-drill (test_v3_hc_2c_disaster_drill.py)
# imports + asserts the REAL detection, NOT a replicated copy (铁律 34 single source).
RATE_LIMIT_KEYWORDS: tuple[str, ...] = ("每分钟", "频率", "频次", "limit", "too many")


def is_rate_limit_error(err_msg: str) -> bool:
    """Classify a Tushare API error message as rate-limit (V3 §14 mode 7).

    rate-limit → 固定 60s 冷却; 非 rate-limit → 指数退避 (见 TushareAPI._call_with_retry).
    """
    return any(kw in err_msg for kw in RATE_LIMIT_KEYWORDS)


# daily_basic只拉需要的字段(避免brotli大payload错误)
DAILY_BASIC_FIELDS = (
    "ts_code,trade_date,close,turnover_rate,turnover_rate_f,"
    "volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
    "total_share,float_share,free_share,total_mv,circ_mv"
)


class TushareAPI:
    """统一Tushare API客户端。

    - per-API限流(SLEEP_INTERVALS)
    - 指数退避重试(max 3次, 频率限制错误60s冷却)
    - structlog日志
    - 调用计数
    """

    def __init__(self, token: str | None = None):
        self.token = token or settings.TUSHARE_TOKEN
        if not self.token:
            raise ValueError("TUSHARE_TOKEN未配置")
        ts.set_token(self.token)
        self.pro = ts.pro_api()
        self._call_count = 0
        self._last_call_time: float = 0.0

    @property
    def call_count(self) -> int:
        return self._call_count

    # ─── 通用查询 ──────────────────────────────────────────

    def query(
        self,
        api_name: str,
        max_retries: int = 3,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """通用查询接口: per-API限流 + 指数退避重试。

        Args:
            api_name: Tushare接口名(如'daily', 'stock_basic')
            max_retries: 最大重试次数
            **kwargs: 接口参数
        """
        interval = SLEEP_INTERVALS.get(api_name, DEFAULT_INTERVAL)

        for attempt in range(1, max_retries + 1):
            try:
                # per-API限流
                elapsed = time.time() - self._last_call_time
                if elapsed < interval:
                    time.sleep(interval - elapsed)

                self._last_call_time = time.time()
                df = self.pro.query(api_name, **kwargs)
                self._call_count += 1

                if df is None:
                    return pd.DataFrame()
                return df

            except Exception as e:
                err_msg = str(e)
                is_rate_limit = is_rate_limit_error(err_msg)

                if attempt < max_retries:
                    if is_rate_limit:
                        wait = 60  # 频率限制: 固定60s冷却
                    else:
                        wait = min(2**attempt, 300)  # 指数退避, 上限5分钟

                    logger.warning(
                        "%s attempt %d/%d failed: %s, retrying in %ds",
                        api_name,
                        attempt,
                        max_retries,
                        str(e)[:80],
                        wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error(
                        "%s failed after %d retries: %s",
                        api_name,
                        max_retries,
                        str(e)[:120],
                    )
                    raise

        return pd.DataFrame()  # unreachable

    # ─── 高级fetch方法(签名与TushareFetcher一致) ──────────

    def fetch_daily_by_date(self, trade_date: str) -> pd.DataFrame:
        """拉取某日全市场日线(~5400行)。"""
        return self.query("daily", trade_date=trade_date)

    def fetch_adj_factor_by_date(self, trade_date: str) -> pd.DataFrame:
        """拉取某日全市场复权因子。"""
        return self.query("adj_factor", trade_date=trade_date)

    def fetch_stk_limit_by_date(self, trade_date: str) -> pd.DataFrame:
        """拉取某日涨跌停价格(过滤只保留A股)。"""
        df = self.query("stk_limit", trade_date=trade_date)
        if df.empty:
            return df
        mask = df["ts_code"].str[:1].isin(["0", "3", "6", "8"])
        return df[mask].reset_index(drop=True)

    def fetch_daily_basic_by_date(self, trade_date: str) -> pd.DataFrame:
        """拉取某日全市场基础指标(指定fields避免brotli错误)。"""
        return self.query("daily_basic", trade_date=trade_date, fields=DAILY_BASIC_FIELDS)

    def fetch_index_daily(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """拉取指数日线数据。"""
        return self.query("index_daily", ts_code=ts_code, start_date=start_date, end_date=end_date)

    def fetch_index_weight(
        self, index_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """拉取指数成分股权重。"""
        return self.query("index_weight", index_code=index_code, start_date=start_date, end_date=end_date)

    # ─── 合并单日数据为klines_daily格式 ────────────────────

    def merge_daily_data(self, trade_date: str) -> pd.DataFrame:
        """合并daily + adj_factor + stk_limit为klines_daily入库格式。

        返回列: code, trade_date, open, high, low, close, pre_close, change,
        pct_change, volume, amount, turnover_rate, adj_factor, is_suspended,
        is_st, up_limit, down_limit
        """
        df_daily = self.fetch_daily_by_date(trade_date)
        if df_daily.empty:
            logger.warning("No daily data for %s", trade_date)
            return pd.DataFrame()

        df_adj = self.fetch_adj_factor_by_date(trade_date)
        df_limit = self.fetch_stk_limit_by_date(trade_date)

        df = df_daily.copy()

        # Merge adj_factor
        if not df_adj.empty:
            df = df.merge(df_adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
        else:
            df["adj_factor"] = None

        # Merge stk_limit
        if not df_limit.empty:
            df = df.merge(df_limit[["ts_code", "up_limit", "down_limit"]], on="ts_code", how="left")
        else:
            df["up_limit"] = None
            df["down_limit"] = None

        # 转换列名
        df = df.rename(columns={"ts_code": "code", "pct_chg": "pct_change", "vol": "volume"})

        # 标记停牌
        df["is_suspended"] = (df["volume"] == 0) & ((df["close"] - df["pre_close"]).abs() < 0.001)

        # 标记ST(从stock_basic获取当前ST名称)
        try:
            st_df = self.query("stock_basic", exchange="", fields="ts_code,name")
            st_codes = set(
                st_df.loc[st_df["name"].str.contains("ST", case=False, na=False), "ts_code"]
            )
            df["is_st"] = df["code"].isin(st_codes)
        except Exception:
            df["is_st"] = False

        if "turnover_rate" not in df.columns:
            df["turnover_rate"] = None

        cols = [
            "code", "trade_date", "open", "high", "low", "close",
            "pre_close", "change", "pct_change", "volume", "amount",
            "turnover_rate", "adj_factor", "is_suspended", "is_st",
            "up_limit", "down_limit",
        ]
        return df[cols]

    # ─── 交易日列表 ────────────────────────────────────────

    def get_trading_dates(self, start_date: str, end_date: str) -> list[str]:
        """从Tushare获取交易日列表。"""
        df = self.query("trade_cal", exchange="SSE", start_date=start_date, end_date=end_date)
        if df.empty or "is_open" not in df.columns:
            raise ValueError(f"trade_cal returned unexpected: empty={df.empty}")
        dates = df[df["is_open"].astype(int) == 1]["cal_date"].tolist()
        if not dates:
            raise ValueError(f"No trading dates for {start_date}~{end_date}")
        return sorted(dates)
