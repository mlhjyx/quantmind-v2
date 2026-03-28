"""Strategy Repository — strategy + strategy_configs表访问。

策略元数据和版本配置的CRUD。
CLAUDE.md: strategy_configs.config是JSONB，每次变更插入新version行。
"""

import json

from app.repositories.base_repository import BaseRepository


class StrategyRepository(BaseRepository):
    """strategy + strategy_configs表的数据访问。"""

    async def get_strategy(self, strategy_id: str) -> dict | None:
        """获取策略基本信息。"""
        row = await self.fetch_one(
            """SELECT id, name, market, mode, factor_config, backtest_config,
                      active_version, status, deployed_at, created_at
               FROM strategy WHERE id = :sid""",
            {"sid": strategy_id},
        )
        if not row:
            return None
        return {
            "id": str(row[0]),
            "name": row[1],
            "market": row[2],
            "mode": row[3],
            "factor_config": row[4],
            "backtest_config": row[5],
            "active_version": row[6],
            "status": row[7],
            "deployed_at": row[8],
            "created_at": row[9],
        }

    async def get_active_config(self, strategy_id: str) -> dict | None:
        """获取策略当前激活版本的配置。"""
        row = await self.fetch_one(
            """SELECT sc.version, sc.config, sc.changelog, sc.created_at
               FROM strategy_configs sc
               JOIN strategy s ON sc.strategy_id = s.id AND sc.version = s.active_version
               WHERE s.id = :sid""",
            {"sid": strategy_id},
        )
        if not row:
            return None
        return {
            "version": row[0],
            "config": row[1],
            "changelog": row[2],
            "created_at": row[3],
        }

    async def get_config_history(self, strategy_id: str) -> list[dict]:
        """获取策略全部配置版本历史。"""
        rows = await self.fetch_all(
            """SELECT version, config, changelog, created_at
               FROM strategy_configs
               WHERE strategy_id = :sid
               ORDER BY version DESC""",
            {"sid": strategy_id},
        )
        return [
            {"version": r[0], "config": r[1], "changelog": r[2], "created_at": r[3]} for r in rows
        ]

    async def create_config_version(
        self,
        strategy_id: str,
        config: dict,
        changelog: str,
    ) -> int:
        """创建新配置版本（插入新行，不更新旧行）。

        CLAUDE.md: 每次变更插入新version行，回滚=把active_version指回旧版本号。
        """
        # 获取当前最大版本号
        max_ver = await self.fetch_scalar(
            "SELECT COALESCE(MAX(version), 0) FROM strategy_configs WHERE strategy_id = :sid",
            {"sid": strategy_id},
        )
        new_version = (max_ver or 0) + 1

        await self.execute(
            """INSERT INTO strategy_configs (strategy_id, version, config, changelog)
               VALUES (:sid, :ver, :cfg, :log)""",
            {
                "sid": strategy_id,
                "ver": new_version,
                "cfg": json.dumps(config),
                "log": changelog,
            },
        )

        # 更新策略的active_version
        await self.execute(
            "UPDATE strategy SET active_version = :ver, updated_at = NOW() WHERE id = :sid",
            {"sid": strategy_id, "ver": new_version},
        )

        return new_version

    async def rollback_version(self, strategy_id: str, target_version: int) -> None:
        """回滚到指定版本（只改active_version指针，不删除版本记录）。"""
        await self.execute(
            "UPDATE strategy SET active_version = :ver, updated_at = NOW() WHERE id = :sid",
            {"sid": strategy_id, "ver": target_version},
        )

    async def list_strategies(
        self, market: str | None = None, status: str | None = None
    ) -> list[dict]:
        """列出策略。"""
        sql = "SELECT id, name, market, status, active_version, created_at FROM strategy WHERE 1=1"
        params: dict = {}
        if market:
            sql += " AND market = :market"
            params["market"] = market
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"

        rows = await self.fetch_all(sql, params)
        return [
            {
                "id": str(r[0]),
                "name": r[1],
                "market": r[2],
                "status": r[3],
                "active_version": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    async def create_strategy(
        self,
        name: str,
        market: str,
        config: dict,
        factor_names: list[str],
    ) -> str:
        """创建新策略记录，返回新strategy的UUID字符串。

        Args:
            name: 策略名称。
            market: 市场类型（'astock'/'forex'）。
            config: 策略初始配置（JSONB）。
            factor_names: 因子名称列表，写入factor_config字段。

        Returns:
            新策略的UUID字符串。
        """
        new_id = await self.fetch_scalar(
            """INSERT INTO strategy (name, market, factor_config, backtest_config, status)
               VALUES (:name, :market, :factor_cfg, :bt_cfg, 'draft')
               RETURNING id""",
            {
                "name": name,
                "market": market,
                "factor_cfg": json.dumps({"factor_names": factor_names, **config}),
                "bt_cfg": json.dumps({}),
            },
        )
        return str(new_id)

    async def update_strategy(
        self,
        strategy_id: str,
        updates: dict,
    ) -> bool:
        """更新策略基本信息（name/status/factor_config/backtest_config）。

        Args:
            strategy_id: 策略ID。
            updates: 待更新字段字典，支持 name/status/factor_config/backtest_config。

        Returns:
            是否成功更新（True=找到并更新，False=策略不存在）。
        """
        allowed = {"name", "status", "factor_config", "backtest_config"}
        set_clauses = []
        params: dict = {"sid": strategy_id}
        for key, val in updates.items():
            if key not in allowed:
                continue
            set_clauses.append(f"{key} = :{key}")
            params[key] = json.dumps(val) if isinstance(val, dict) else val

        if not set_clauses:
            return True  # 无有效字段，视为成功

        set_clauses.append("updated_at = NOW()")
        sql = f"UPDATE strategy SET {', '.join(set_clauses)} WHERE id = :sid"
        result = await self.execute(sql, params)
        return result.rowcount > 0

    async def soft_delete_strategy(self, strategy_id: str) -> bool:
        """软删除策略，将status设为'archived'。

        Args:
            strategy_id: 策略ID。

        Returns:
            是否成功（True=找到并归档，False=不存在）。
        """
        result = await self.execute(
            "UPDATE strategy SET status = 'archived', updated_at = NOW() WHERE id = :sid",
            {"sid": strategy_id},
        )
        return result.rowcount > 0
