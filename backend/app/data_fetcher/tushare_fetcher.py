"""[DEPRECATED] 旧版Tushare拉取器 — 已合并到tushare_api.py。

向后兼容shim: `from app.data_fetcher.tushare_fetcher import TushareFetcher` 仍可用。
新代码请用 `from app.data_fetcher.tushare_api import TushareAPI`。

TushareAPI保留了TushareFetcher的全部方法签名:
  fetch_daily_by_date, fetch_adj_factor_by_date, fetch_stk_limit_by_date,
  fetch_daily_basic_by_date, fetch_index_daily, fetch_index_weight,
  merge_daily_data, get_trading_dates
"""

from app.data_fetcher.tushare_api import TushareAPI as TushareFetcher  # noqa: F401

__all__ = ["TushareFetcher"]
