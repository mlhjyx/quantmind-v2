"""Phase 0 基础数据拉取 — 一次性全量导入

按顺序拉取:
1. symbols (含退市股)
2. trading_calendar
3. klines_daily + adj_factor (合并入库)
4. daily_basic
5. index_daily (沪深300/中证500/中证1000)
6. financial_indicators (fina_indicator, 用ann_date做PIT)

使用方法:
    cd backend && python -m app.data_fetcher.fetch_base_data
"""

import asyncio
import time
from datetime import date, timedelta

import pandas as pd
from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.data_fetcher.tushare_api import TushareAPI as TushareClient

# 数据拉取范围: 2019-01-01起 (多留1年lookback给因子计算)
START_DATE = "20190101"
END_DATE = date.today().strftime("%Y%m%d")

# 需要拉取的指数
INDEX_CODES = ["000300.SH", "000905.SH", "000852.SH"]  # 沪深300/中证500/中证1000


def _board_from_ts_code(ts_code: str, name: str) -> str:
    """从ts_code后缀和名称推断板块"""
    if ts_code.startswith("68"):
        return "star"  # 科创板
    if ts_code.startswith("30"):
        return "gem"   # 创业板
    if ts_code.startswith("8") or ts_code.startswith("4"):
        return "bse"   # 北交所
    return "main"


def _price_limit(board: str, name: str) -> float:
    """涨跌停幅度"""
    if "ST" in name or "st" in name:
        return 0.05
    if board == "gem" or board == "star":
        return 0.20
    if board == "bse":
        return 0.30
    return 0.10


class BaseDataFetcher:
    """Phase 0 全量数据拉取器"""

    def __init__(self):
        self.client = TushareClient()
        # 用同步方式创建engine(数据拉取是一次性脚本)
        self.engine = create_async_engine(
            settings.DATABASE_URL,
            echo=False,
            pool_size=5,
        )
        self.session_factory = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def run_all(self) -> None:
        """按顺序执行全量数据拉取"""
        t0 = time.time()
        logger.info("=" * 60)
        logger.info("开始 Phase 0 全量数据拉取")
        logger.info(f"范围: {START_DATE} ~ {END_DATE}")
        logger.info("=" * 60)

        await self.fetch_symbols()
        await self.fetch_trading_calendar()
        await self.fetch_klines_daily()
        await self.fetch_daily_basic()
        await self.fetch_index_daily()
        await self.fetch_financial_indicators()

        elapsed = time.time() - t0
        logger.info(f"全量数据拉取完成，耗时 {elapsed:.0f} 秒")
        await self.engine.dispose()

    # ── 1. symbols ──────────────────────────────────────

    async def fetch_symbols(self) -> None:
        """拉取全量股票(含退市股)，写入symbols表"""
        logger.info("[1/6] 拉取 symbols...")

        # 上市中
        df_l = self.client.query("stock_basic", exchange="", list_status="L",
                                 fields="ts_code,symbol,name,area,industry,market,"
                                        "list_date,list_status,exchange,is_hs")
        # 退市
        df_d = self.client.query("stock_basic", exchange="", list_status="D",
                                 fields="ts_code,symbol,name,area,industry,market,"
                                        "list_date,delist_date,list_status,exchange,is_hs")
        # 暂停上市
        df_p = self.client.query("stock_basic", exchange="", list_status="P",
                                 fields="ts_code,symbol,name,area,industry,market,"
                                        "list_date,list_status,exchange,is_hs")

        df = pd.concat([df_l, df_d, df_p], ignore_index=True)
        logger.info(f"  获取 {len(df)} 只股票 (上市{len(df_l)}, 退市{len(df_d)}, 暂停{len(df_p)})")

        if df.empty:
            logger.error("  symbols数据为空，终止！")
            return

        # 构造入库数据
        rows = []
        for _, r in df.iterrows():
            ts_code = str(r["ts_code"])
            code = ts_code  # 保留完整ts_code作为code（统一带后缀格式）
            name = str(r["name"])
            board = _board_from_ts_code(ts_code, name)
            exchange = "SSE" if ts_code.endswith(".SH") else "SZSE"
            if board == "bse":
                exchange = "BSE"

            rows.append({
                "code": code,
                "ts_code": ts_code,
                "name": name,
                "market": "astock",
                "board": board,
                "exchange": exchange,
                "industry_sw1": str(r.get("industry", "")) or None,
                "area": str(r.get("area", "")) or None,
                "list_date": pd.to_datetime(r.get("list_date")).date() if pd.notna(r.get("list_date")) else None,
                "delist_date": pd.to_datetime(r.get("delist_date")).date() if pd.notna(r.get("delist_date")) else None,
                "list_status": str(r.get("list_status", "L")),
                "is_hs": str(r.get("is_hs", "")) or None,
                "price_limit": _price_limit(board, name),
                "lot_size": 100,
                "is_active": str(r.get("list_status", "L")) == "L",
            })

        async with self.session_factory() as session:
            # 清空后重新插入(全量刷新)
            await session.execute(text("TRUNCATE symbols CASCADE"))
            for batch_start in range(0, len(rows), 500):
                batch = rows[batch_start:batch_start + 500]
                await session.execute(
                    text("""
                        INSERT INTO symbols (code, ts_code, name, market, board, exchange,
                            industry_sw1, area, list_date, delist_date, list_status,
                            is_hs, price_limit, lot_size, is_active)
                        VALUES (:code, :ts_code, :name, :market, :board, :exchange,
                            :industry_sw1, :area, :list_date, :delist_date, :list_status,
                            :is_hs, :price_limit, :lot_size, :is_active)
                        ON CONFLICT (code) DO UPDATE SET
                            name=EXCLUDED.name, list_status=EXCLUDED.list_status,
                            delist_date=EXCLUDED.delist_date, is_active=EXCLUDED.is_active,
                            updated_at=NOW()
                    """),
                    batch,
                )
            await session.commit()
        logger.info(f"  symbols 入库完成: {len(rows)} 条")

    # ── 2. trading_calendar ─────────────────────────────

    async def fetch_trading_calendar(self) -> None:
        """拉取交易日历"""
        logger.info("[2/6] 拉取 trading_calendar...")

        df = self.client.query(
            "trade_cal",
            exchange="SSE",
            start_date="20190101",
            end_date="20261231",
            fields="cal_date,is_open,pretrade_date",
        )
        logger.info(f"  获取 {len(df)} 天日历")

        rows = []
        for _, r in df.iterrows():
            rows.append({
                "trade_date": pd.to_datetime(r["cal_date"]).date(),
                "market": "astock",
                "is_trading_day": bool(r["is_open"]),
                "pretrade_date": pd.to_datetime(r["pretrade_date"]).date() if pd.notna(r.get("pretrade_date")) else None,
            })

        async with self.session_factory() as session:
            await session.execute(text("DELETE FROM trading_calendar WHERE market='astock'"))
            for batch_start in range(0, len(rows), 1000):
                batch = rows[batch_start:batch_start + 1000]
                await session.execute(
                    text("""
                        INSERT INTO trading_calendar (trade_date, market, is_trading_day, pretrade_date)
                        VALUES (:trade_date, :market, :is_trading_day, :pretrade_date)
                        ON CONFLICT (trade_date, market) DO NOTHING
                    """),
                    batch,
                )
            await session.commit()
        logger.info(f"  trading_calendar 入库完成: {len(rows)} 条")

    # ── 3. klines_daily + adj_factor ────────────────────

    async def fetch_klines_daily(self) -> None:
        """按日期拉取日线行情 + 复权因子，合并入库。

        Tushare daily接口: 按日期拉 → 单次最多5000条
        adj_factor: 按日期拉
        """
        logger.info("[3/6] 拉取 klines_daily + adj_factor...")

        # 获取交易日列表
        async with self.session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT trade_date FROM trading_calendar
                    WHERE market='astock' AND is_trading_day=TRUE
                      AND trade_date >= :start AND trade_date <= :end
                    ORDER BY trade_date
                """),
                {"start": pd.to_datetime(START_DATE).date(),
                 "end": pd.to_datetime(END_DATE).date()},
            )
            trade_dates = [row[0] for row in result.fetchall()]

        logger.info(f"  需拉取 {len(trade_dates)} 个交易日")

        # 检查已有数据，支持断点续拉
        async with self.session_factory() as session:
            result = await session.execute(
                text("SELECT DISTINCT trade_date FROM klines_daily ORDER BY trade_date")
            )
            existing_dates = {row[0] for row in result.fetchall()}

        remaining = [d for d in trade_dates if d not in existing_dates]
        logger.info(f"  已有 {len(existing_dates)} 天，待拉取 {len(remaining)} 天")

        # 加载有效code集合(过滤FK不存在的code)
        async with self.session_factory() as session:
            result = await session.execute(text("SELECT code FROM symbols"))
            valid_codes = {row[0] for row in result.fetchall()}
        logger.info(f"  有效code数: {len(valid_codes)}")

        total = len(remaining)
        for i, td in enumerate(remaining):
            td_str = td.strftime("%Y%m%d")

            # 拉取日线
            df_daily = self.client.query(
                "daily", trade_date=td_str,
                fields="ts_code,trade_date,open,high,low,close,pre_close,"
                       "change,pct_chg,vol,amount",
            )

            # 拉取复权因子
            df_adj = self.client.query(
                "adj_factor", trade_date=td_str,
                fields="ts_code,trade_date,adj_factor",
            )

            # 拉取涨跌停价
            df_limit = self.client.query(
                "stk_limit", trade_date=td_str,
                fields="ts_code,trade_date,up_limit,down_limit",
            )

            if df_daily.empty:
                if (i + 1) % 100 == 0:
                    logger.info(f"  [{i+1}/{total}] {td_str} 无数据(跳过)")
                continue

            # 合并
            df = df_daily.copy()
            if not df_adj.empty:
                df = df.merge(df_adj[["ts_code", "adj_factor"]], on="ts_code", how="left")
            else:
                df["adj_factor"] = 1.0

            if not df_limit.empty:
                df = df.merge(df_limit[["ts_code", "up_limit", "down_limit"]], on="ts_code", how="left")
            else:
                df["up_limit"] = None
                df["down_limit"] = None

            # 构造入库数据(过滤掉symbols表中不存在的code)
            rows = []
            for _, r in df.iterrows():
                ts_code = str(r["ts_code"])
                code = ts_code  # 保留带后缀格式
                if code not in valid_codes:
                    continue
                vol = r.get("vol")  # Tushare daily.vol = 手
                amount = r.get("amount")  # Tushare daily.amount = 千元

                # 判断停牌: volume=0
                is_suspended = (pd.isna(vol) or vol == 0)
                rows.append({
                    "code": code,
                    "trade_date": td,
                    "open": float(r["open"]) if pd.notna(r.get("open")) else None,
                    "high": float(r["high"]) if pd.notna(r.get("high")) else None,
                    "low": float(r["low"]) if pd.notna(r.get("low")) else None,
                    "close": float(r["close"]) if pd.notna(r.get("close")) else None,
                    "pre_close": float(r["pre_close"]) if pd.notna(r.get("pre_close")) else None,
                    "change": float(r["change"]) if pd.notna(r.get("change")) else None,
                    "pct_change": float(r["pct_chg"]) if pd.notna(r.get("pct_chg")) else None,
                    "volume": int(vol) if pd.notna(vol) else None,
                    "amount": float(amount) if pd.notna(amount) else None,
                    "adj_factor": float(r["adj_factor"]) if pd.notna(r.get("adj_factor")) else 1.0,
                    "is_suspended": is_suspended,
                    "up_limit": float(r["up_limit"]) if pd.notna(r.get("up_limit")) else None,
                    "down_limit": float(r["down_limit"]) if pd.notna(r.get("down_limit")) else None,
                })

            if rows:
                async with self.session_factory() as session:
                    for batch_start in range(0, len(rows), 500):
                        batch = rows[batch_start:batch_start + 500]
                        await session.execute(
                            text("""
                                INSERT INTO klines_daily (code, trade_date, open, high, low, close,
                                    pre_close, change, pct_change, volume, amount,
                                    adj_factor, is_suspended, up_limit, down_limit)
                                VALUES (:code, :trade_date, :open, :high, :low, :close,
                                    :pre_close, :change, :pct_change, :volume, :amount,
                                    :adj_factor, :is_suspended, :up_limit, :down_limit)
                                ON CONFLICT (code, trade_date) DO NOTHING
                            """),
                            batch,
                        )
                    await session.commit()

            if (i + 1) % 50 == 0 or (i + 1) == total:
                logger.info(f"  [{i+1}/{total}] {td_str} 入库 {len(rows)} 条")

        logger.info("  klines_daily 拉取完成")

    # ── 4. daily_basic ──────────────────────────────────

    async def fetch_daily_basic(self) -> None:
        """拉取每日基本面指标"""
        logger.info("[4/6] 拉取 daily_basic...")

        # 获取交易日列表
        async with self.session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT trade_date FROM trading_calendar
                    WHERE market='astock' AND is_trading_day=TRUE
                      AND trade_date >= :start AND trade_date <= :end
                    ORDER BY trade_date
                """),
                {"start": pd.to_datetime(START_DATE).date(),
                 "end": pd.to_datetime(END_DATE).date()},
            )
            trade_dates = [row[0] for row in result.fetchall()]

        # 断点续拉
        async with self.session_factory() as session:
            result = await session.execute(
                text("SELECT DISTINCT trade_date FROM daily_basic ORDER BY trade_date")
            )
            existing_dates = {row[0] for row in result.fetchall()}

        remaining = [d for d in trade_dates if d not in existing_dates]
        logger.info(f"  已有 {len(existing_dates)} 天，待拉取 {len(remaining)} 天")

        # 加载有效code集合
        async with self.session_factory() as session:
            result = await session.execute(text("SELECT code FROM symbols"))
            valid_codes = {row[0] for row in result.fetchall()}

        total = len(remaining)
        for i, td in enumerate(remaining):
            td_str = td.strftime("%Y%m%d")

            df = self.client.query(
                "daily_basic", trade_date=td_str,
                fields="ts_code,trade_date,close,turnover_rate,turnover_rate_f,"
                       "volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,"
                       "total_share,float_share,free_share,total_mv,circ_mv",
            )

            if df.empty:
                continue

            rows = []
            for _, r in df.iterrows():
                code = str(r["ts_code"])  # 保留带后缀格式
                if code not in valid_codes:
                    continue
                row = {"code": code, "trade_date": td}
                for col in ["close", "turnover_rate", "turnover_rate_f", "volume_ratio",
                            "pe", "pe_ttm", "pb", "ps", "ps_ttm", "dv_ratio", "dv_ttm",
                            "total_share", "float_share", "free_share", "total_mv", "circ_mv"]:
                    val = r.get(col)
                    row[col] = float(val) if pd.notna(val) else None
                rows.append(row)

            if rows:
                async with self.session_factory() as session:
                    for batch_start in range(0, len(rows), 500):
                        batch = rows[batch_start:batch_start + 500]
                        await session.execute(
                            text("""
                                INSERT INTO daily_basic (code, trade_date, close,
                                    turnover_rate, turnover_rate_f, volume_ratio,
                                    pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm,
                                    total_share, float_share, free_share, total_mv, circ_mv)
                                VALUES (:code, :trade_date, :close,
                                    :turnover_rate, :turnover_rate_f, :volume_ratio,
                                    :pe, :pe_ttm, :pb, :ps, :ps_ttm, :dv_ratio, :dv_ttm,
                                    :total_share, :float_share, :free_share, :total_mv, :circ_mv)
                                ON CONFLICT (code, trade_date) DO NOTHING
                            """),
                            batch,
                        )
                    await session.commit()

            if (i + 1) % 50 == 0 or (i + 1) == total:
                logger.info(f"  [{i+1}/{total}] {td_str} 入库 {len(rows)} 条")

        logger.info("  daily_basic 拉取完成")

    # ── 5. index_daily ──────────────────────────────────

    async def fetch_index_daily(self) -> None:
        """拉取沪深300/中证500/中证1000指数日线"""
        logger.info("[5/6] 拉取 index_daily...")

        for idx_code in INDEX_CODES:
            logger.info(f"  拉取指数: {idx_code}")
            df = self.client.query(
                "index_daily",
                ts_code=idx_code,
                start_date=START_DATE,
                end_date=END_DATE,
                fields="ts_code,trade_date,open,high,low,close,pre_close,pct_chg,vol,amount",
            )

            if df.empty:
                logger.warning(f"  {idx_code} 无数据!")
                continue

            rows = []
            for _, r in df.iterrows():
                rows.append({
                    "index_code": str(r["ts_code"]),
                    "trade_date": pd.to_datetime(r["trade_date"]).date(),
                    "open": float(r["open"]) if pd.notna(r.get("open")) else None,
                    "high": float(r["high"]) if pd.notna(r.get("high")) else None,
                    "low": float(r["low"]) if pd.notna(r.get("low")) else None,
                    "close": float(r["close"]) if pd.notna(r.get("close")) else None,
                    "pre_close": float(r["pre_close"]) if pd.notna(r.get("pre_close")) else None,
                    "pct_change": float(r["pct_chg"]) if pd.notna(r.get("pct_chg")) else None,
                    "volume": int(r["vol"]) if pd.notna(r.get("vol")) else None,
                    "amount": float(r["amount"]) if pd.notna(r.get("amount")) else None,
                })

            async with self.session_factory() as session:
                await session.execute(
                    text("DELETE FROM index_daily WHERE index_code = :idx"),
                    {"idx": idx_code},
                )
                for batch_start in range(0, len(rows), 1000):
                    batch = rows[batch_start:batch_start + 1000]
                    await session.execute(
                        text("""
                            INSERT INTO index_daily (index_code, trade_date, open, high, low,
                                close, pre_close, pct_change, volume, amount)
                            VALUES (:index_code, :trade_date, :open, :high, :low,
                                :close, :pre_close, :pct_change, :volume, :amount)
                            ON CONFLICT (index_code, trade_date) DO NOTHING
                        """),
                        batch,
                    )
                await session.commit()
            logger.info(f"  {idx_code} 入库 {len(rows)} 条")

        logger.info("  index_daily 拉取完成")

    # ── 6. financial_indicators ─────────────────────────

    async def fetch_financial_indicators(self) -> None:
        """拉取财务指标(fina_indicator)，用ann_date做PIT对齐。

        Tushare fina_indicator: 按股票拉，每次一只。
        这里改为按报告期拉取(更高效)。
        """
        logger.info("[6/6] 拉取 financial_indicators...")

        # 报告期列表: 2018Q4 ~ 最近
        periods = []
        for year in range(2018, date.today().year + 1):
            for q_end in ["0331", "0630", "0930", "1231"]:
                p = f"{year}{q_end}"
                if p <= END_DATE:
                    periods.append(p)

        logger.info(f"  需拉取 {len(periods)} 个报告期")

        # 加载有效code集合
        async with self.session_factory() as session:
            result = await session.execute(text("SELECT code FROM symbols"))
            {row[0] for row in result.fetchall()}

        total = len(periods)
        total_rows = 0
        for i, period in enumerate(periods):
            df = self.client.query(
                "fina_indicator",
                period=period,
                fields="ts_code,ann_date,end_date,roe,roe_dt,roa,"
                       "grossprofit_margin,netprofit_margin,"
                       "revenue_yoy,netprofit_yoy,basic_eps_yoy,"
                       "eps,bps,current_ratio,quick_ratio,debt_to_assets",
            )

            if df.empty:
                continue

            rows = []
            for _, r in df.iterrows():
                code = str(r["ts_code"])  # 保留带后缀格式
                report_date = pd.to_datetime(r["end_date"]).date()

                # PIT关键: 用ann_date (实际公告日)
                ann_date = None
                if pd.notna(r.get("ann_date")):
                    ann_date = pd.to_datetime(r["ann_date"]).date()
                else:
                    # fallback: report_date + 90天
                    ann_date = report_date + timedelta(days=90)

                row = {
                    "code": code,
                    "report_date": report_date,
                    "actual_ann_date": ann_date,
                }
                field_map = {
                    "roe": "roe", "roe_dt": "roe_dt", "roa": "roa",
                    "grossprofit_margin": "gross_profit_margin",
                    "netprofit_margin": "net_profit_margin",
                    "revenue_yoy": "revenue_yoy",
                    "netprofit_yoy": "net_profit_yoy",
                    "basic_eps_yoy": "basic_eps_yoy",
                    "eps": "eps", "bps": "bps",
                    "current_ratio": "current_ratio",
                    "quick_ratio": "quick_ratio",
                    "debt_to_assets": "debt_to_asset",
                }
                for src, dst in field_map.items():
                    val = r.get(src)
                    row[dst] = float(val) if pd.notna(val) else None
                rows.append(row)

            if rows:
                async with self.session_factory() as session:
                    for batch_start in range(0, len(rows), 500):
                        batch = rows[batch_start:batch_start + 500]
                        await session.execute(
                            text("""
                                INSERT INTO financial_indicators (code, report_date, actual_ann_date,
                                    roe, roe_dt, roa, gross_profit_margin, net_profit_margin,
                                    revenue_yoy, net_profit_yoy, basic_eps_yoy,
                                    eps, bps, current_ratio, quick_ratio, debt_to_asset)
                                VALUES (:code, :report_date, :actual_ann_date,
                                    :roe, :roe_dt, :roa, :gross_profit_margin, :net_profit_margin,
                                    :revenue_yoy, :net_profit_yoy, :basic_eps_yoy,
                                    :eps, :bps, :current_ratio, :quick_ratio, :debt_to_asset)
                                ON CONFLICT (code, report_date) DO UPDATE SET
                                    actual_ann_date=EXCLUDED.actual_ann_date,
                                    roe=EXCLUDED.roe, roe_dt=EXCLUDED.roe_dt
                            """),
                            batch,
                        )
                    await session.commit()
                total_rows += len(rows)

            if (i + 1) % 5 == 0 or (i + 1) == total:
                logger.info(f"  [{i+1}/{total}] 报告期 {period}, 累计 {total_rows} 条")

        logger.info(f"  financial_indicators 拉取完成: {total_rows} 条")


async def main():
    fetcher = BaseDataFetcher()
    await fetcher.run_all()


if __name__ == "__main__":
    asyncio.run(main())
