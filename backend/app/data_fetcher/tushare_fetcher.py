"""Tushare数据拉取模块 — 按日期策略拉取，合入klines_daily表。

量化专家审查要点：
- adj_factor是累积因子，存原始值，使用时动态计算adj_close
- volume单位=手(×100=股), amount单位=千元
- pct_change已×100（即5.06表示5.06%）
- up_limit/down_limit来自stk_limit接口

工程架构师审查要点：
- 按trade_date拉取（非按symbol），单次返回全市场数据
- sleep间隔：daily/adj_factor/stk_limit=0.15s, daily_basic=0.30s
- daily_basic必须指定fields参数（避免brotli解码错误）
- 批量upsert入库，单日单事务
"""

import asyncio
import logging
import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pandas as pd
import tushare as ts

from app.config import settings

logger = logging.getLogger(__name__)

# Tushare接口sleep间隔（秒）
SLEEP_INTERVALS = {
    'daily': 0.15,
    'adj_factor': 0.15,
    'stk_limit': 0.15,
    'daily_basic': 0.30,
    'index_daily': 0.15,
    'index_weight': 0.30,
    'fina_indicator': 0.30,
}

# daily_basic只拉需要的字段（避免brotli大payload错误）
DAILY_BASIC_FIELDS = (
    'ts_code,trade_date,close,turnover_rate,turnover_rate_f,'
    'volume_ratio,pe,pe_ttm,pb,ps,ps_ttm,dv_ratio,dv_ttm,'
    'total_share,float_share,free_share,total_mv,circ_mv'
)


class TushareFetcher:
    """Tushare数据拉取器。

    拉取策略：按trade_date拉取（非按symbol），单次API调用返回全市场数据。
    全量5年数据仅需~5000次API调用，约20分钟完成。
    """

    def __init__(self) -> None:
        self.pro = ts.pro_api(settings.TUSHARE_TOKEN)
        self._call_count = 0

    def _api_call_with_retry(
        self, api_name: str, max_retries: int = 3, **kwargs: Any
    ) -> pd.DataFrame:
        """带重试的API调用。"""
        interval = SLEEP_INTERVALS.get(api_name, 0.20)
        for attempt in range(max_retries):
            try:
                time.sleep(interval)
                method = getattr(self.pro, api_name)
                df = method(**kwargs)
                self._call_count += 1
                return df if df is not None else pd.DataFrame()
            except Exception as e:
                if attempt < max_retries - 1:
                    wait = min(60 * (2 ** attempt), 300)
                    logger.warning(
                        f'{api_name} attempt {attempt+1} failed: {e}, '
                        f'retrying in {wait}s'
                    )
                    time.sleep(wait)
                else:
                    logger.error(f'{api_name} failed after {max_retries} retries: {e}')
                    raise

    # ── 按日期拉取全市场数据 ──────────────────────────────────

    def fetch_daily_by_date(self, trade_date: str) -> pd.DataFrame:
        """拉取某日全市场日线。返回~5400行。

        字段：ts_code, trade_date, open, high, low, close, pre_close,
              change, pct_chg, vol(手), amount(千元)
        """
        return self._api_call_with_retry(
            'daily', trade_date=trade_date
        )

    def fetch_adj_factor_by_date(self, trade_date: str) -> pd.DataFrame:
        """拉取某日全市场复权因子。"""
        return self._api_call_with_retry(
            'adj_factor', trade_date=trade_date
        )

    def fetch_stk_limit_by_date(self, trade_date: str) -> pd.DataFrame:
        """拉取某日涨跌停价格。需过滤只保留A股。"""
        df = self._api_call_with_retry(
            'stk_limit', trade_date=trade_date
        )
        if len(df) == 0:
            return df
        # 过滤A股：主板(0/6) + 创业板(3) + 北交所(8)
        mask = df['ts_code'].str[:1].isin(['0', '3', '6', '8'])
        return df[mask].reset_index(drop=True)

    def fetch_daily_basic_by_date(self, trade_date: str) -> pd.DataFrame:
        """拉取某日全市场基础指标。指定fields避免brotli错误。"""
        return self._api_call_with_retry(
            'daily_basic', trade_date=trade_date,
            fields=DAILY_BASIC_FIELDS
        )

    def fetch_index_daily(
        self, ts_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """拉取指数日线数据。"""
        return self._api_call_with_retry(
            'index_daily', ts_code=ts_code,
            start_date=start_date, end_date=end_date
        )

    def fetch_index_weight(
        self, index_code: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """拉取指数成分股权重。"""
        return self._api_call_with_retry(
            'index_weight', index_code=index_code,
            start_date=start_date, end_date=end_date
        )

    # ── 合并单日数据为klines_daily格式 ──────────────────────

    def merge_daily_data(
        self, trade_date: str
    ) -> pd.DataFrame:
        """合并daily + adj_factor + stk_limit为单日入库格式。

        返回的DataFrame列名与klines_daily表对齐：
        code, trade_date, open, high, low, close, pre_close, change,
        pct_change, volume, amount, turnover_rate, adj_factor,
        is_suspended, is_st, up_limit, down_limit
        """
        df_daily = self.fetch_daily_by_date(trade_date)
        if len(df_daily) == 0:
            logger.warning(f'No daily data for {trade_date}')
            return pd.DataFrame()

        df_adj = self.fetch_adj_factor_by_date(trade_date)
        df_limit = self.fetch_stk_limit_by_date(trade_date)

        # Merge
        df = df_daily.copy()

        # Merge adj_factor
        if len(df_adj) > 0:
            df = df.merge(
                df_adj[['ts_code', 'adj_factor']],
                on='ts_code', how='left'
            )
        else:
            df['adj_factor'] = None

        # Merge stk_limit
        if len(df_limit) > 0:
            df = df.merge(
                df_limit[['ts_code', 'up_limit', 'down_limit']],
                on='ts_code', how='left'
            )
        else:
            df['up_limit'] = None
            df['down_limit'] = None

        # 转换列名以匹配DDL
        df = df.rename(columns={
            'ts_code': 'code',
            'pct_chg': 'pct_change',
            'vol': 'volume',
        })
        # Strip交易所后缀: 000001.SZ → 000001（与symbols表PK对齐）
        df['code'] = df['code'].str.split('.').str[0]

        # 标记停牌：volume=0 且 close≈pre_close（用容差避免浮点精度问题）
        df['is_suspended'] = (
            (df['volume'] == 0) &
            ((df['close'] - df['pre_close']).abs() < 0.001)
        )

        # 标记ST：从symbols表获取（后续在入库时join）
        df['is_st'] = False  # 默认False，入库时更新

        # turnover_rate在daily接口中没有，设为None
        if 'turnover_rate' not in df.columns:
            df['turnover_rate'] = None

        # 选择最终列
        cols = [
            'code', 'trade_date', 'open', 'high', 'low', 'close',
            'pre_close', 'change', 'pct_change', 'volume', 'amount',
            'turnover_rate', 'adj_factor', 'is_suspended', 'is_st',
            'up_limit', 'down_limit'
        ]
        return df[cols]

    # ── 获取交易日列表 ──────────────────────────────────────

    def get_trading_dates(
        self, start_date: str, end_date: str
    ) -> list[str]:
        """从Tushare获取交易日列表。"""
        df = self._api_call_with_retry(
            'trade_cal', exchange='SSE',
            start_date=start_date, end_date=end_date
        )
        if df.empty or 'is_open' not in df.columns:
            raise ValueError(
                f'trade_cal returned unexpected result: '
                f'empty={df.empty}, columns={list(df.columns)}'
            )
        trading_dates = df[df['is_open'].astype(int) == 1]['cal_date'].tolist()
        if not trading_dates:
            raise ValueError(
                f'No trading dates found for {start_date}~{end_date}'
            )
        return sorted(trading_dates)
