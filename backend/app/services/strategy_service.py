"""Strategy Service — 策略管理。

CLAUDE.md: strategy_configs.config是JSONB，每次变更插入新version行。
回滚 = 把strategy.active_version指回旧版本号。
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.strategy_repository import StrategyRepository
from app.services.backtest_service import BacktestService


class StrategyService:
    """策略管理服务。

    提供策略CRUD、配置版本创建、版本回滚、回测触发。
    通过FastAPI Depends注入session。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.strategy_repo = StrategyRepository(session)
        self._session = session

    async def get_strategy_detail(self, strategy_id: str) -> dict[str, Any] | None:
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

        new_version = await self.strategy_repo.create_config_version(strategy_id, config, changelog)

        return {
            "version": new_version,
            "strategy_id": strategy_id,
            "changelog": changelog,
        }

    async def rollback(self, strategy_id: str, target_version: int) -> dict[str, Any]:
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
            raise ValueError(f"版本 {target_version} 不存在，可用版本: {sorted(valid_versions)}")

        previous_version = strategy["active_version"]
        await self.strategy_repo.rollback_version(strategy_id, target_version)

        return {
            "strategy_id": strategy_id,
            "rolled_back_to": target_version,
            "previous_version": previous_version,
        }

    async def create_strategy(
        self,
        name: str,
        market: str,
        config: dict[str, Any],
        factor_names: list[str],
    ) -> dict[str, Any]:
        """创建新策略。

        Args:
            name: 策略名称。
            market: 市场类型（'astock'/'forex'）。
            config: 策略配置（JSONB）。
            factor_names: 因子名称列表。

        Returns:
            包含新策略信息的字典：strategy_id/name/market/status。
        """
        strategy_id = await self.strategy_repo.create_strategy(
            name=name,
            market=market,
            config=config,
            factor_names=factor_names,
        )
        return {
            "strategy_id": strategy_id,
            "name": name,
            "market": market,
            "status": "draft",
        }

    async def update_strategy(
        self,
        strategy_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """更新策略配置。

        Args:
            strategy_id: 策略ID。
            updates: 待更新字段（name/status/factor_config/backtest_config）。

        Returns:
            包含更新结果的字典：strategy_id/updated。

        Raises:
            ValueError: 策略不存在时抛出。
        """
        strategy = await self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"策略不存在: {strategy_id}")

        updated = await self.strategy_repo.update_strategy(strategy_id, updates)
        return {"strategy_id": strategy_id, "updated": updated}

    async def delete_strategy(self, strategy_id: str) -> dict[str, Any]:
        """软删除策略（status → 'archived'）。

        Args:
            strategy_id: 策略ID。

        Returns:
            包含删除结果的字典：strategy_id/archived。

        Raises:
            ValueError: 策略不存在时抛出。
        """
        strategy = await self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"策略不存在: {strategy_id}")

        archived = await self.strategy_repo.soft_delete_strategy(strategy_id)
        return {"strategy_id": strategy_id, "archived": archived}

    async def get_strategy_factors(self, strategy_id: str) -> dict[str, Any] | None:
        """获取策略关联因子及分类信息。

        从strategy.factor_config中读取factor_names，
        返回各因子的基本分类信息（类型/方向/衰减周期）。

        Args:
            strategy_id: 策略ID。

        Returns:
            包含因子列表的字典，不存在时返回None。
        """
        strategy = await self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            return None

        factor_config = strategy.get("factor_config") or {}
        if isinstance(factor_config, str):
            import json

            factor_config = json.loads(factor_config)

        factor_names: list[str] = factor_config.get("factor_names", [])

        # 查询因子注册表获取分类信息（factor_registry表）
        factors = []
        for fname in factor_names:
            row = await self.strategy_repo.fetch_one(
                """SELECT name, category, direction, ic_decay_halflife
                   FROM factor_registry WHERE name = :name AND status = 'active'""",
                {"name": fname},
            )
            if row:
                factors.append(
                    {
                        "name": row[0],
                        "category": row[1],
                        "direction": row[2],
                        "ic_decay_halflife": float(row[3]) if row[3] is not None else None,
                    }
                )
            else:
                factors.append(
                    {
                        "name": fname,
                        "category": None,
                        "direction": None,
                        "ic_decay_halflife": None,
                    }
                )

        return {
            "strategy_id": strategy_id,
            "factor_names": factor_names,
            "factors": factors,
        }

    async def trigger_backtest(
        self,
        strategy_id: str,
        backtest_config: dict[str, Any],
    ) -> dict[str, Any]:
        """触发策略回测（通过BacktestService提交Celery任务）。

        Args:
            strategy_id: 策略ID。
            backtest_config: 回测配置（start_date/end_date/top_n/rebalance_freq等）。

        Returns:
            包含run_id的字典：strategy_id/run_id。

        Raises:
            ValueError: 策略不存在时抛出。
        """
        strategy = await self.strategy_repo.get_strategy(strategy_id)
        if not strategy:
            raise ValueError(f"策略不存在: {strategy_id}")

        backtest_svc = BacktestService(self._session)
        run_id = await backtest_svc.submit_backtest(
            strategy_id=strategy_id,
            config=backtest_config,
            market=strategy.get("market", "astock"),
        )
        return {"strategy_id": strategy_id, "run_id": run_id}
