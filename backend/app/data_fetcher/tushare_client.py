"""Tushare Pro API 封装 — 带限速和重试"""

import time

import pandas as pd
import tushare as ts
from loguru import logger

from app.config import settings


class TushareClient:
    """Tushare API 客户端，统一限速和错误处理。

    8000积分: 500请求/分钟 → sleep 0.15s 安全间隔
    """

    def __init__(self, token: str | None = None):
        self.token = token or settings.TUSHARE_TOKEN
        if not self.token:
            raise ValueError("TUSHARE_TOKEN 未配置")
        ts.set_token(self.token)
        self.pro = ts.pro_api()
        self._last_call_time: float = 0
        self._min_interval: float = 0.15  # 8000积分=500req/min

    def _rate_limit(self) -> None:
        """限速：确保两次调用间隔 >= min_interval"""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def query(
        self,
        api_name: str,
        max_retries: int = 3,
        **kwargs,
    ) -> pd.DataFrame:
        """通用查询接口，带重试和限速。

        Args:
            api_name: Tushare接口名，如 'stock_basic', 'daily'
            max_retries: 最大重试次数
            **kwargs: 接口参数
        """
        for attempt in range(1, max_retries + 1):
            try:
                self._rate_limit()
                df = self.pro.query(api_name, **kwargs)
                if df is None:
                    df = pd.DataFrame()
                return df
            except Exception as e:
                logger.warning(
                    f"Tushare {api_name} 第{attempt}次失败: {e}"
                )
                if attempt < max_retries:
                    wait = 2 ** attempt
                    logger.info(f"等待{wait}秒后重试...")
                    time.sleep(wait)
                else:
                    logger.error(f"Tushare {api_name} 最终失败，已重试{max_retries}次")
                    raise
        return pd.DataFrame()  # unreachable
