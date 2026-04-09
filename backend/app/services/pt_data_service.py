"""PT数据拉取服务 — 并行拉取klines/basic/index。

从run_paper_trading.py Step1提取(Step 6-A)。
调用DataPipeline入库。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

from app.data_fetcher.data_loader import get_sync_conn, upsert_daily_basic, upsert_klines_daily

logger = logging.getLogger("paper_trading")


def fetch_daily_data(trade_date: date, conn=None, skip_fetch: bool = False) -> dict:
    """并行拉取当日klines+basic+index数据并入库。

    Args:
        trade_date: 交易日期
        conn: 可选DB连接
        skip_fetch: 跳过拉取(调试用)

    Returns:
        {"klines_rows": int, "basic_rows": int, "index_rows": int, "elapsed": float}
    """
    if skip_fetch:
        logger.info("[Data] skip_fetch=True, 跳过数据拉取")
        return {"klines_rows": 0, "basic_rows": 0, "index_rows": 0, "elapsed": 0}

    from app.data_fetcher.tushare_api import TushareAPI

    api = TushareAPI()
    own_conn = conn is None
    if own_conn:
        conn = get_sync_conn()

    td_str = trade_date.strftime("%Y%m%d")
    t0 = time.time()
    results = {"klines_rows": 0, "basic_rows": 0, "index_rows": 0}

    def _fetch_klines():
        df = api.merge_daily_data(td_str)
        if df.empty:
            return 0
        return upsert_klines_daily(df, conn)

    def _fetch_basic():
        df = api.fetch_daily_basic_by_date(td_str)
        if df.empty:
            return 0
        return upsert_daily_basic(df, conn)

    def _fetch_index():
        """拉取主要指数日线。"""
        index_codes = ["000300.SH", "000905.SH", "000852.SH"]
        total = 0
        for idx_code in index_codes:
            try:
                df = api.fetch_index_daily(idx_code, td_str, td_str)
                if not df.empty:
                    # 直接通过data_loader的upsert(index有自己的路径)

                    from app.data_fetcher.contracts import INDEX_DAILY
                    from app.data_fetcher.pipeline import DataPipeline

                    pipeline = DataPipeline(conn)
                    result = pipeline.ingest(df, INDEX_DAILY)
                    total += result.upserted_rows
            except Exception as e:
                logger.warning("[Data] 指数%s拉取失败: %s", idx_code, str(e)[:60])
        return total

    # 并行拉取
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_fetch_klines): "klines",
            executor.submit(_fetch_basic): "basic",
            executor.submit(_fetch_index): "index",
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                count = future.result()
                results[f"{name}_rows"] = count
            except Exception as e:
                logger.error("[Data] %s拉取失败: %s", name, e)

    results["elapsed"] = round(time.time() - t0, 1)
    logger.info(
        "[Data] 拉取完成: klines=%d, basic=%d, index=%d (%.1fs)",
        results["klines_rows"], results["basic_rows"], results["index_rows"],
        results["elapsed"],
    )

    if own_conn:
        conn.close()

    return results
