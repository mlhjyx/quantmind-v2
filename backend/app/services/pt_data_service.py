"""PT数据拉取服务 — 并行拉取klines/basic/index + stock_status增量更新。

从run_paper_trading.py Step1提取(Step 6-A)。
调用DataPipeline入库。

2026-04-14修复: 新增 update_stock_status_daily() — 增量更新ST/停牌/新股状态。
之前stock_status_daily只有全量回填(build_stock_status.py)，日常不更新，
导致数据滞后→ST过滤失效(688184.SH事件)。
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import pandas as pd

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

    # klines拉取完成后，增量更新stock_status_daily（依赖klines的volume字段）
    # 铁律 33 fail-loud: stock_status 更新失败是关键数据链路断点, 不允许 silent swallow.
    # 2026-04-18 LL-058 教训: 04-16 silent error swallow 导致 04-17 health check 失败 +
    # PT 链路断 4 天. 改为 raise 让 signal_phase catch + log_step("signal_phase", "failed", ...)
    # + pt_watchdog 20:00 钉钉告警, 不再静默.
    if results["klines_rows"] > 0:
        try:
            status_rows = update_stock_status_daily(trade_date, conn)
            results["status_rows"] = status_rows
        except Exception as e:
            logger.error(
                "[Data] stock_status_daily 更新失败 (FAIL-LOUD 铁律 33): %s", e
            )
            results["status_rows"] = 0
            raise  # 传播到 signal_phase except → scheduler_task_log "failed"
    else:
        results["status_rows"] = 0

    results["elapsed"] = round(time.time() - t0, 1)
    logger.info(
        "[Data] 拉取完成: klines=%d, basic=%d, index=%d, status=%d (%.1fs)",
        results["klines_rows"],
        results["basic_rows"],
        results["index_rows"],
        results["status_rows"],
        results["elapsed"],
    )

    if own_conn:
        conn.close()

    return results


def update_stock_status_daily(trade_date: date, conn) -> int:
    """增量更新单日stock_status_daily。

    依赖: klines_daily(volume判断停牌) + symbols(list_date/board) + Tushare namechange(ST)。
    在fetch_daily_data拉取klines后自动调用，确保stock_status_daily与klines同步。

    2026-04-14新增: 修复stock_status_daily数据滞后导致ST过滤失效。

    Args:
        trade_date: 交易日期。
        conn: psycopg2连接。

    Returns:
        插入/更新行数。
    """
    cur = conn.cursor()

    # 检查是否已存在
    cur.execute("SELECT COUNT(*) FROM stock_status_daily WHERE trade_date = %s", (trade_date,))
    existing = cur.fetchone()[0]
    if existing > 0:
        logger.info("[Status] %s 已存在 %d 行，跳过", trade_date, existing)
        cur.close()
        return existing

    # 检查klines是否存在
    cur.execute("SELECT COUNT(*) FROM klines_daily WHERE trade_date = %s", (trade_date,))
    klines_count = cur.fetchone()[0]
    if klines_count == 0:
        logger.warning("[Status] %s 无klines数据，跳过status更新", trade_date)
        cur.close()
        return 0

    # 方案1(快速): 从前一天复制ST状态，用klines更新停牌
    # 这避免每天都调Tushare namechange API
    cur.execute(
        "SELECT MAX(trade_date) FROM stock_status_daily WHERE trade_date < %s",
        (trade_date,),
    )
    prev_row = cur.fetchone()
    prev_date = prev_row[0] if prev_row and prev_row[0] else None

    if prev_date is not None:
        # 快速路径: 从前一天复制 + 更新volume=0为停牌
        _count = _incremental_from_previous(cur, conn, trade_date, prev_date)
        cur.close()
        return _count

    # 慢路径: 无前一天数据，需要全量构建(调Tushare)
    logger.warning("[Status] 无前一天数据，使用Tushare全量构建 %s", trade_date)
    _count = _full_build_single_day(cur, conn, trade_date)
    cur.close()
    return _count


def _incremental_from_previous(cur, conn, trade_date: date, prev_date: date) -> int:
    """从前一天stock_status复制并更新当天停牌状态。

    ST状态日内不变(namechange是按时间段的)，停牌由当天volume=0判断。
    """
    # 获取当天所有klines的code+volume
    cur.execute("SELECT code, volume FROM klines_daily WHERE trade_date = %s", (trade_date,))
    today_klines = {row[0]: row[1] for row in cur.fetchall()}

    # 获取前一天的status
    cur.execute(
        """SELECT code, is_st, is_new_stock, board, list_date, delist_date
           FROM stock_status_daily WHERE trade_date = %s""",
        (prev_date,),
    )
    prev_status = {row[0]: row[1:] for row in cur.fetchall()}

    # 获取symbols信息(给没在prev中的新code用)
    cur.execute("SELECT code, list_date, delist_date, board FROM symbols")
    symbols = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}

    records = []
    for code, volume in today_klines.items():
        is_suspended = volume is not None and int(volume) == 0

        if code in prev_status:
            is_st, is_new, board, list_dt, delist_dt = prev_status[code]
            # 更新新股状态(可能已过60天)
            if list_dt and (trade_date - list_dt).days >= 60:
                is_new = False
        else:
            # 新出现的code, 用symbols信息
            sym = symbols.get(code)
            list_dt = sym[0] if sym else None
            delist_dt = sym[1] if sym else None
            board = (sym[2] if sym else None) or _infer_board(code)
            is_st = False  # 保守: 新code默认非ST, 下次全量rebuild会修正
            is_new = list_dt is not None and 0 <= (trade_date - list_dt).days < 60

        records.append((code, trade_date, is_st, is_suspended, is_new, board, list_dt, delist_dt))

    if records:
        # MVP 2.1c Sub2: execute_values → DataPipeline.ingest (铁律 17, STOCK_STATUS_DAILY Contract)
        _ingest_stock_status(conn, records)

    st_count = sum(1 for r in records if r[2])
    logger.info(
        "[Status] %s 增量更新: %d行 (从%s复制, %d ST, %d 停牌)",
        trade_date,
        len(records),
        prev_date,
        st_count,
        sum(1 for r in records if r[3]),
    )
    return len(records)


def _ingest_stock_status(conn, records: list[tuple]) -> None:
    """统一 stock_status_daily 写路径 → DataPipeline.ingest (铁律 17).

    records tuples: (code, trade_date, is_st, is_suspended, is_new_stock,
                     board, list_date, delist_date)
    """
    from app.data_fetcher.contracts import STOCK_STATUS_DAILY
    from app.data_fetcher.pipeline import DataPipeline

    df = pd.DataFrame(
        records,
        columns=[
            "code", "trade_date", "is_st", "is_suspended", "is_new_stock",
            "board", "list_date", "delist_date",
        ],
    )
    pipeline = DataPipeline(conn)
    result = pipeline.ingest(df, STOCK_STATUS_DAILY)
    if result.rejected_rows > 0:
        logger.warning(
            "[Status] DataPipeline 拒绝 %d 行: %s",
            result.rejected_rows, result.reject_reasons,
        )


def _full_build_single_day(cur, conn, trade_date: date) -> int:
    """全量构建单日stock_status(调Tushare namechange)。"""
    from app.data_fetcher.tushare_api import TushareAPI

    api = TushareAPI()

    # Fetch ST periods
    all_nc = []
    for offset in range(0, 200000, 10000):
        df = api.query(
            "namechange",
            fields="ts_code,name,start_date,end_date",
            limit=10000,
            offset=offset,
        )
        if df is None or df.empty:
            break
        all_nc.append(df)
        if len(df) < 10000:
            break

    st_lookup: dict[str, list[tuple[date, date]]] = {}
    if all_nc:
        nc = pd.concat(all_nc).drop_duplicates(subset=["ts_code", "name", "start_date", "end_date"])
        st_mask = nc["name"].str.contains("ST", case=False, na=False)
        for _, row in nc[st_mask].iterrows():
            code = row["ts_code"]
            st_start = pd.to_datetime(row["start_date"]).date()
            end_val = row["end_date"]
            st_end = pd.to_datetime(end_val).date() if pd.notna(end_val) else date(2099, 12, 31)
            st_lookup.setdefault(code, []).append((st_start, st_end))

    def is_st(code, td):
        return any(s <= td <= e for s, e in st_lookup.get(code, []))

    # Load symbols + klines
    cur.execute("SELECT code, list_date, delist_date, board FROM symbols")
    symbols = {r[0]: (r[1], r[2], r[3]) for r in cur.fetchall()}

    cur.execute("SELECT code, volume FROM klines_daily WHERE trade_date = %s", (trade_date,))
    records = []
    for code, volume in cur.fetchall():
        sym = symbols.get(code)
        list_dt = sym[0] if sym else None
        delist_dt = sym[1] if sym else None
        board = (sym[2] if sym else None) or _infer_board(code)
        records.append(
            (
                code,
                trade_date,
                is_st(code, trade_date),
                volume is not None and int(volume) == 0,
                list_dt is not None and 0 <= (trade_date - list_dt).days < 60,
                board,
                list_dt,
                delist_dt,
            )
        )

    if records:
        # MVP 2.1c Sub2: 统一走 DataPipeline (与 _incremental_from_previous 一致)
        _ingest_stock_status(conn, records)

    logger.info("[Status] %s 全量构建: %d行", trade_date, len(records))
    return len(records)


def _infer_board(code: str) -> str:
    """从code推断板块。"""
    if code.startswith("68"):
        return "star"
    if code.startswith("30"):
        return "gem"
    if code.endswith(".BJ") or code.startswith(("8", "4", "92")):
        return "bse"
    return "main"
