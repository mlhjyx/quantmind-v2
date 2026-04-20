"""QMT Data Service — 独立常驻进程，Servy管理。

职责:
1. 每分钟同步: query_positions() + query_asset() → Redis缓存
2. 持仓股票价格: get_full_tick() → Redis缓存 market:latest:{code} (TTL=60s)
3. 交易指令: 监听 qm:trade:commands → 调用MiniQMTBroker → 结果写 qm:trade:results
4. 连接状态: 通过StreamBus广播 qm:qmt:status

架构: 复用 MiniQMTBroker + QMTExecutionAdapter，不重写。

MVP 2.1c Sub3.4 (2026-04-18): `_sync_prices` 走 `QMTDataSource.fetch(QMT_TICKS_CONTRACT)`
(Platform DataSource), 不再本脚本直接 import xtquant. xtquant 通过 QMTDataSource lazy import
间接使用 (仍需 ensure_xtquant_path 先设 path). Servy 服务配置 0 改动, 入口/行为保持.

用法:
    python scripts/qmt_data_service.py
    # 或由 Servy 管理为 Windows 服务
"""

import json
import logging
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# 项目路径设置
_project_root = Path(__file__).resolve().parent.parent
sys.path.append(str(_project_root / "backend"))

from app.config import settings  # noqa: E402
from app.core.stream_bus import (  # noqa: E402
    STREAM_QMT_STATUS,
    get_stream_bus,
)
from app.core.xtquant_path import ensure_xtquant_path  # noqa: E402

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("qmt_data_service")

# Redis缓存键
CACHE_PORTFOLIO_CURRENT = "portfolio:current"  # Hash: code → shares
CACHE_PORTFOLIO_NAV = "portfolio:nav"  # String: JSON {cash, total, updated_at}
CACHE_MARKET_PREFIX = "market:latest:"  # String per code, TTL=60s
CACHE_QMT_STATUS = "qmt:connection_status"  # String: connected/disconnected

# 同步间隔
SYNC_INTERVAL_SEC = 60
TICK_TTL_SEC = 90  # 价格缓存TTL，略大于同步间隔


class QMTDataService:
    """QMT数据同步服务。"""

    def __init__(self) -> None:
        self._running = False
        self._broker = None
        self._redis = None
        self._bus = get_stream_bus()

    def _get_redis(self):
        """获取Redis连接（懒初始化）。"""
        if self._redis is None:
            import redis

            self._redis = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis

    def _connect_qmt(self) -> bool:
        """连接QMT，复用MiniQMTBroker。"""
        ensure_xtquant_path()
        try:
            from engines.broker_qmt import MiniQMTBroker

            qmt_path = getattr(settings, "QMT_PATH", "")
            account_id = getattr(settings, "QMT_ACCOUNT_ID", "")

            if not qmt_path or not account_id:
                logger.error("QMT_PATH 或 QMT_ACCOUNT_ID 未配置")
                return False

            self._broker = MiniQMTBroker(qmt_path, account_id)
            self._broker.connect()
            logger.info("QMT连接成功: account=%s", account_id)

            self._publish_status("connected")
            self._get_redis().set(CACHE_QMT_STATUS, "connected")
            return True
        except Exception:
            logger.exception("QMT连接失败")
            self._publish_status("connect_failed")
            self._get_redis().set(CACHE_QMT_STATUS, "disconnected")
            return False

    def _disconnect_qmt(self) -> None:
        """断开QMT连接。"""
        if self._broker:
            try:
                self._broker.disconnect()
            except Exception:
                logger.warning("QMT断开连接异常", exc_info=True)
            self._broker = None
            self._publish_status("disconnected")

    def _publish_status(self, status: str) -> None:
        """通过StreamBus广播连接状态。"""
        self._bus.publish_sync(
            STREAM_QMT_STATUS,
            {"status": status, "timestamp": datetime.now(UTC).isoformat()},
            source="qmt_data_service",
        )

    def _sync_positions(self) -> None:
        """同步持仓和资产到Redis缓存。"""
        if not self._broker:
            return

        r = self._get_redis()

        try:
            # 查询持仓
            positions = self._broker.get_positions()
            # positions: dict[code, shares] 或 list[Position]
            pos_dict = {}
            if isinstance(positions, dict):
                pos_dict = {k: str(v) for k, v in positions.items()}
            elif isinstance(positions, list):
                for p in positions:
                    code = getattr(p, "stock_code", getattr(p, "code", ""))
                    vol = getattr(p, "volume", getattr(p, "quantity", 0))
                    if code and vol > 0:
                        pos_dict[code] = str(vol)

            # 写入Redis Hash (F68: 加 TTL 防止 QMT 停止后数据永不过期)
            pipe = r.pipeline()
            pipe.delete(CACHE_PORTFOLIO_CURRENT)
            if pos_dict:
                pipe.hset(CACHE_PORTFOLIO_CURRENT, mapping=pos_dict)
            pipe.expire(CACHE_PORTFOLIO_CURRENT, 180)  # 3min TTL, 同步间隔60s
            pipe.execute()

            # 查询资产
            asset = self._broker.query_asset()
            nav_data = {
                "cash": float(asset.get("cash", 0)) if isinstance(asset, dict) else 0,
                "total_value": float(asset.get("total_asset", 0)) if isinstance(asset, dict) else 0,
                "updated_at": datetime.now(UTC).isoformat(),
                "position_count": len(pos_dict),
            }
            r.set(CACHE_PORTFOLIO_NAV, json.dumps(nav_data))

            logger.debug("持仓同步完成: %d只股票", len(pos_dict))
            return pos_dict
        except Exception:
            logger.warning("持仓同步失败", exc_info=True)
            return None

    def _sync_prices(self, codes: list[str]) -> None:
        """同步持仓股票实时价格到Redis缓存。

        MVP 2.1c Sub3.4 (2026-04-18): 走 Platform QMTDataSource (MVP 2.1b) 替代直接 import xtquant.
        QMTDataSource 内部 lazy import xtquant, 本 method 不再直接 `from xtquant import xtdata`.
        ensure_xtquant_path() 仍需调用 (lazy import 触发前 path setup).
        """
        if not codes:
            return

        r = self._get_redis()

        try:
            ensure_xtquant_path()  # QMTDataSource lazy import xtquant, 需要 path 先 setup
            from datetime import date as _date

            from backend.platform.data.sources.qmt_source import (
                QMT_TICKS_CONTRACT,
                QMTDataSource,
            )

            source = QMTDataSource(broker=self._broker, codes=list(codes))
            df = source.fetch(QMT_TICKS_CONTRACT, since=_date.today())

            pipe = r.pipeline()
            synced = 0
            for _, row in df.iterrows():
                updated = row["updated_at"]
                updated_iso = (
                    updated.isoformat() if hasattr(updated, "isoformat") else str(updated)
                )
                # v2 (2026-04-20 Session 18): 盘中 live 事故修复 — 不再写 high/low 到 Redis.
                # 根因: QMT_TICKS_CONTRACT v2 已移除 high/low (tick 层无日 OHLC 语义).
                # 下游 qmt_client.get_price/get_prices 只读 price 字段, 无消费者用 high/low.
                price_info = json.dumps(
                    {
                        "price": float(row["last_price"]),
                        "volume": int(row["volume"]),
                        "updated_at": updated_iso,
                    }
                )
                pipe.setex(f"{CACHE_MARKET_PREFIX}{row['code']}", TICK_TTL_SEC, price_info)
                synced += 1
            pipe.execute()
            logger.debug("价格同步完成 (via QMTDataSource): %d/%d", synced, len(codes))
        except Exception:
            logger.warning("价格同步失败 (via QMTDataSource)", exc_info=True)

    def _run_sync_loop(self) -> None:
        """主同步循环。"""
        logger.info("同步循环启动，间隔=%ds", SYNC_INTERVAL_SEC)

        while self._running:
            try:
                # 同步持仓
                pos_dict = self._sync_positions()

                # 同步持仓股票价格
                if pos_dict:
                    codes = list(pos_dict.keys())
                    self._sync_prices(codes)
            except Exception:
                logger.exception("同步循环异常")

            # 等待下一轮（可被信号中断）
            for _ in range(SYNC_INTERVAL_SEC):
                if not self._running:
                    break
                time.sleep(1)

    def start(self) -> None:
        """启动服务。"""
        logger.info("=== QMT Data Service 启动 ===")
        self._running = True

        # 注册信号处理
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

        # 连接QMT（带退避重试）
        if not self._connect_qmt():
            logger.warning("QMT未连接，服务将以退避模式重试连接")
            retry_delay = 30  # 初始30秒
            max_delay = 300  # 最大5分钟
            retry_count = 0
            while self._running:
                # 等待（可被信号中断）
                for _ in range(retry_delay):
                    if not self._running:
                        break
                    time.sleep(1)
                if not self._running:
                    break
                retry_count += 1
                if self._connect_qmt():
                    logger.info("QMT重连成功（第%d次尝试）", retry_count)
                    break
                # 退避：30 → 60 → 120 → 300（封顶）
                retry_delay = min(retry_delay * 2, max_delay)
                if retry_count % 10 == 0:
                    logger.warning("QMT连续%d次连接失败，下次重试间隔%ds", retry_count, retry_delay)

        if not self._running:
            return

        # 开始同步循环
        self._run_sync_loop()

        # 清理
        self._disconnect_qmt()
        logger.info("=== QMT Data Service 已停止 ===")

    def _handle_shutdown(self, signum, frame) -> None:
        """优雅关闭。"""
        logger.info("收到关闭信号 (sig=%d)，正在停止...", signum)
        self._running = False


def main() -> None:
    """入口函数。"""
    service = QMTDataService()
    service.start()


if __name__ == "__main__":
    main()
