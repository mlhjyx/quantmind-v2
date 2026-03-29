"""QMT连接管理器 — 管理MiniQMTBroker生命周期。

Singleton模式，在EXECUTION_MODE=live时:
- FastAPI启动时自动连接miniQMT
- 关闭时断开连接
- 暴露连接状态供健康检查和执行服务使用

PT代码隔离: 此模块是ADDITIVE的，不修改任何现有执行路径。
"""

import logging
from datetime import datetime
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger(__name__)


class QMTConnectionManager:
    """QMT连接管理器（Singleton）。

    职责:
    1. MiniQMTBroker实例的创建和生命周期管理
    2. 连接状态跟踪 (connected/disconnected/reconnecting/disabled)
    3. 供ExecutionService和Health API查询
    """

    _instance: Optional["QMTConnectionManager"] = None

    def __new__(cls) -> "QMTConnectionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._broker: Any = None  # MiniQMTBroker, 延迟导入
        self._state: str = "disabled"  # disabled/connecting/connected/disconnected/error
        self._last_error: str | None = None
        self._connected_at: datetime | None = None
        self._last_check_at: datetime | None = None

    @property
    def is_live_mode(self) -> bool:
        """是否为实盘模式。"""
        return settings.EXECUTION_MODE == "live"

    @property
    def state(self) -> str:
        """连接状态。"""
        return self._state

    @property
    def broker(self) -> Any:
        """获取MiniQMTBroker实例（仅live模式且已连接时有效）。"""
        return self._broker

    def startup(self) -> None:
        """FastAPI启动时调用。仅EXECUTION_MODE=live时连接。"""
        if not self.is_live_mode:
            self._state = "disabled"
            logger.info("[QMTManager] EXECUTION_MODE=paper, QMT连接管理器已禁用")
            return

        if not settings.QMT_PATH or not settings.QMT_ACCOUNT_ID:
            self._state = "error"
            self._last_error = "QMT_PATH或QMT_ACCOUNT_ID未配置"
            logger.error(f"[QMTManager] {self._last_error}")
            return

        self._connect()

    def shutdown(self) -> None:
        """FastAPI关闭时调用。"""
        if self._broker is not None:
            try:
                self._broker.disconnect()
                logger.info("[QMTManager] 已断开QMT连接")
            except Exception:
                logger.exception("[QMTManager] 断开连接时异常")
            self._broker = None
        self._state = "disconnected"

    def _connect(self) -> None:
        """连接miniQMT。"""
        self._state = "connecting"
        try:
            from engines.broker_qmt import MiniQMTBroker

            self._broker = MiniQMTBroker(
                qmt_path=settings.QMT_PATH,
                account_id=settings.QMT_ACCOUNT_ID,
            )
            self._broker.connect()
            self._state = "connected"
            self._connected_at = datetime.now()
            self._last_error = None
            logger.info("[QMTManager] QMT连接成功")
        except Exception as e:
            self._state = "error"
            self._last_error = str(e)
            self._broker = None
            logger.exception("[QMTManager] QMT连接失败")

    def health_check(self) -> dict[str, Any]:
        """返回QMT连接健康状态。

        Returns:
            包含state/account_id/connected_at/last_error等信息的dict。
        """
        self._last_check_at = datetime.now()

        result: dict[str, Any] = {
            "execution_mode": settings.EXECUTION_MODE,
            "state": self._state,
            "account_id": settings.QMT_ACCOUNT_ID or None,
            "qmt_path": settings.QMT_PATH or None,
            "connected_at": self._connected_at.isoformat() if self._connected_at else None,
            "last_error": self._last_error,
        }

        # live模式且已连接时，尝试查询资产验证连接活跃
        if self._state == "connected" and self._broker is not None:
            try:
                asset = self._broker.query_asset()
                result["account_asset"] = {
                    "total_asset": asset.get("total_asset"),
                    "cash": asset.get("cash"),
                    "market_value": asset.get("market_value"),
                }
                result["is_healthy"] = True
            except Exception as e:
                result["is_healthy"] = False
                result["probe_error"] = str(e)
                self._state = "error"
                self._last_error = f"健康检查探测失败: {e}"
        else:
            result["is_healthy"] = self._state == "disabled"  # paper模式视为健康

        return result

    def ensure_connected(self) -> None:
        """确保QMT已连接，未连接则抛出异常。

        供ExecutionService在live模式执行前调用。

        Raises:
            RuntimeError: 未连接或非live模式。
        """
        if not self.is_live_mode:
            raise RuntimeError("当前为paper模式，不支持QMT执行")
        if self._state != "connected" or self._broker is None:
            raise RuntimeError(
                f"QMT未连接 (state={self._state}), "
                f"last_error={self._last_error}"
            )


# 模块级单例
qmt_manager = QMTConnectionManager()
