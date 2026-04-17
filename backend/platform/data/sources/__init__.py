"""MVP 2.1b (Wave 2) — Concrete DataSource implementations.

3 fetcher 继承 `backend.platform.data.base_source.BaseDataSource`, 只实现 `_fetch_raw`.
老 `scripts/fetch_minute_bars.py` / `scripts/qmt_data_service.py` /
`backend/app/data_fetcher/fetch_base_data.py` 在 dual-write 期保留, 直到 MVP 2.1c 收尾.

交付顺序 (2026-04-18 session D1 决策):
  - Sub-commit 1 ✅: BaostockDataSource (最低风险, Template 验证)
  - Sub-commit 2 ⏳: QMTDataSource (Redis sink 特殊路径)
  - Sub-commit 3 ⏳: TushareDataSource (生产 PT dual-write)
"""
from .baostock_source import (
    MINUTE_BARS_DATA_CONTRACT,
    BaostockDataSource,
)

__all__ = [
    "BaostockDataSource",
    "MINUTE_BARS_DATA_CONTRACT",
]
