"""Strategy Service — 策略管理。

CLAUDE.md: strategy_configs.config是JSONB，每次变更插入新version行。
回滚 = 把strategy.active_version指回旧版本号。
"""

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.strategy_repository import StrategyRepository


class StrategyService:
    """策略管理服务。

    提供策略详情查询、配置版本创建、版本回滚。
    通过FastAPI Depends注入session。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.strategy_repo = StrategyRepository(session)

    async def get_strategy_detail(
        self, strategy_id: str
    ) -> Optional[dict[str, Any]]:
        """获取策略完整信息（基本信息 + 当前配置 + 历史版本）。

        Args:
            strategy_id: 策略ID。

        Returns:
            策略详情字典，包含：
            - strategy: 策略基本信息
            - active_config: 当前激活版本配置
            - version_history: 全部配置版本列表
            不存在时返回None。
        """
        strategy = await self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            return None

        active_config = await self.strategy_repo.get_active_config(strategy_id)
        version_history = await self.strategy_repo.get_config_history(strategy_id)

        return {
            "strategy": strategy,
            "active_config": active_config,
            "version_history": version_history,
        }

    async def create_version(
        self,
        strategy_id: str,
        config: dict[str, Any],
        changelog: str,
    ) -> dict[str, Any]:
        """创建新配置版本。

        CLAUDE.md: 每次变更插入新version行，不更新旧行。
        每个版本有独立回测记录，支持V1 vs V2 vs V3对比。

        Args:
            strategy_id: 策略ID。
            config: 新版本配置（JSONB）。
            changelog: 变更说明。

        Returns:
            包含新版本号的字典：
            - version: 新版本号
            - strategy_id: 策略ID
            - changelog: 变更说明

        Raises:
            ValueError: 策略不存在时抛出。
        """
        strategy = await self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"策略不存在: {strategy_id}")

        new_version = await self.strategy_repo.create_config_version(
            strategy_id, config, changelog
        )

        return {
            "version": new_version,
            "strategy_id": strategy_id,
            "changelog": changelog,
        }

    async def rollback(
        self, strategy_id: str, target_version: int
    ) -> dict[str, Any]:
        """回滚到指定版本。

        CLAUDE.md: 回滚 = 把active_version指回旧版本号，不删除版本记录。

        Args:
            strategy_id: 策略ID。
            target_version: 目标版本号。

        Returns:
            包含回滚结果的字典：
            - strategy_id: 策略ID
            - rolled_back_to: 目标版本号
            - previous_version: 回滚前的版本号

        Raises:
            ValueError: 策略不存在或目标版本无效时抛出。
        """
        strategy = await self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"策略不存在: {strategy_id}")

        # 验证目标版本存在
        history = await self.strategy_repo.get_config_history(strategy_id)
        valid_versions = {h["version"] for h in history}
        if target_version not in valid_versions:
            raise ValueError(
                f"版本 {target_version} 不存在，可用版本: {sorted(valid_versions)}"
            )

        previous_version = strategy["active_version"]
        await self.strategy_repo.rollback_version(strategy_id, target_version)

        return {
            "strategy_id": strategy_id,
            "rolled_back_to": target_version,
            "previous_version": previous_version,
        }
