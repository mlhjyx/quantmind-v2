"""[DEPRECATED] 旧版Tushare客户端 — 已合并到tushare_api.py。

向后兼容shim: `from app.data_fetcher.tushare_client import TushareClient` 仍可用。
新代码请用 `from app.data_fetcher.tushare_api import TushareAPI`。
"""

from app.data_fetcher.tushare_api import TushareAPI as TushareClient  # noqa: F401

__all__ = ["TushareClient"]
