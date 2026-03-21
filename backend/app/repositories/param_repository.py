"""Param Repository — ai_parameters + param_change_log 表访问。

DDL表:
  - ai_parameters: 参数存储（param_name/param_value/param_min/param_max/param_default/param_type/module）
  - param_change_log: 参数变更审计日志（param_name/old_value/new_value/changed_by/reason）

CLAUDE.md: 所有数据库操作用async/await，Service通过Depends获取db session。
"""

import json
from typing import Any

from app.repositories.base_repository import BaseRepository


class ParamRepository(BaseRepository):
    """ai_parameters + param_change_log 表的数据访问。"""

    # ─── ai_parameters 表操作 ───

    async def get_all_params(self, module: str | None = None) -> list[dict[str, Any]]:
        """获取全部参数（可按模块过滤）。

        Args:
            module: 模块名，为None时返回全部。

        Returns:
            参数列表，每项含 param_name/param_value/param_type/module 等字段。
        """
        sql = """
            SELECT param_name, param_value, param_min, param_max,
                   param_default, param_type, module, market,
                   updated_by, authorization_level, cooldown_hours,
                   cooldown_until, updated_at
            FROM ai_parameters
        """
        params: dict[str, Any] = {}
        if module:
            sql += " WHERE module = :module"
            params["module"] = module
        sql += " ORDER BY module, param_name"

        rows = await self.fetch_all(sql, params)
        return [
            {
                "param_name": r[0],
                "param_value": r[1],
                "param_min": r[2],
                "param_max": r[3],
                "param_default": r[4],
                "param_type": r[5],
                "module": r[6],
                "market": r[7],
                "updated_by": r[8],
                "authorization_level": r[9],
                "cooldown_hours": r[10],
                "cooldown_until": r[11],
                "updated_at": r[12],
            }
            for r in rows
        ]

    async def get_param(self, param_name: str) -> dict[str, Any] | None:
        """获取单个参数。

        Args:
            param_name: 参数名。

        Returns:
            参数字典，不存在时返回None。
        """
        row = await self.fetch_one(
            """SELECT param_name, param_value, param_min, param_max,
                      param_default, param_type, module, market,
                      updated_by, authorization_level, cooldown_hours,
                      cooldown_until, updated_at
               FROM ai_parameters
               WHERE param_name = :name""",
            {"name": param_name},
        )
        if not row:
            return None
        return {
            "param_name": row[0],
            "param_value": row[1],
            "param_min": row[2],
            "param_max": row[3],
            "param_default": row[4],
            "param_type": row[5],
            "module": row[6],
            "market": row[7],
            "updated_by": row[8],
            "authorization_level": row[9],
            "cooldown_hours": row[10],
            "cooldown_until": row[11],
            "updated_at": row[12],
        }

    async def upsert_param(
        self,
        param_name: str,
        param_value: Any,
        param_type: str,
        module: str,
        param_default: Any,
        param_min: Any = None,
        param_max: Any = None,
        updated_by: str = "manual",
    ) -> None:
        """插入或更新参数。

        Args:
            param_name: 参数名。
            param_value: 参数值（将序列化为JSONB）。
            param_type: 参数类型。
            module: 所属模块。
            param_default: 默认值。
            param_min: 最小值。
            param_max: 最大值。
            updated_by: 更新者（manual/ai/system）。
        """
        await self.execute(
            """INSERT INTO ai_parameters
                   (param_name, param_value, param_type, module,
                    param_default, param_min, param_max, updated_by, updated_at)
               VALUES (:name, :val, :ptype, :mod, :pdef, :pmin, :pmax, :by, NOW())
               ON CONFLICT (param_name)
               DO UPDATE SET
                   param_value = :val,
                   param_type = :ptype,
                   module = :mod,
                   param_min = :pmin,
                   param_max = :pmax,
                   updated_by = :by,
                   updated_at = NOW()""",
            {
                "name": param_name,
                "val": json.dumps(param_value),
                "ptype": param_type,
                "mod": module,
                "pdef": json.dumps(param_default),
                "pmin": json.dumps(param_min) if param_min is not None else None,
                "pmax": json.dumps(param_max) if param_max is not None else None,
                "by": updated_by,
            },
        )

    async def update_param_value(
        self,
        param_name: str,
        new_value: Any,
        updated_by: str = "manual",
    ) -> bool:
        """更新参数值。

        Args:
            param_name: 参数名。
            new_value: 新值。
            updated_by: 更新者。

        Returns:
            是否更新成功（参数是否存在）。
        """
        result = await self.execute(
            """UPDATE ai_parameters
               SET param_value = :val, updated_by = :by, updated_at = NOW()
               WHERE param_name = :name""",
            {
                "name": param_name,
                "val": json.dumps(new_value),
                "by": updated_by,
            },
        )
        return result.rowcount > 0

    # ─── param_change_log 表操作 ───

    async def insert_change_log(
        self,
        param_name: str,
        old_value: Any,
        new_value: Any,
        changed_by: str,
        reason: str,
    ) -> None:
        """写入参数变更日志。

        Args:
            param_name: 参数名。
            old_value: 旧值。
            new_value: 新值。
            changed_by: 变更者（manual/ai/system）。
            reason: 变更原因。
        """
        await self.execute(
            """INSERT INTO param_change_log
                   (param_name, old_value, new_value, changed_by, reason)
               VALUES (:name, :old, :new, :by, :reason)""",
            {
                "name": param_name,
                "old": json.dumps(old_value) if old_value is not None else None,
                "new": json.dumps(new_value),
                "by": changed_by,
                "reason": reason,
            },
        )

    async def get_change_log(
        self,
        param_name: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询参数变更历史。

        Args:
            param_name: 参数名，为None时返回全部参数的变更日志。
            limit: 返回条数上限。

        Returns:
            变更日志列表，按时间倒序。
        """
        sql = """
            SELECT id, param_name, old_value, new_value,
                   changed_by, reason, created_at
            FROM param_change_log
        """
        params: dict[str, Any] = {"limit": limit}
        if param_name:
            sql += " WHERE param_name = :name"
            params["name"] = param_name
        sql += " ORDER BY created_at DESC LIMIT :limit"

        rows = await self.fetch_all(sql, params)
        return [
            {
                "id": str(r[0]),
                "param_name": r[1],
                "old_value": r[2],
                "new_value": r[3],
                "changed_by": r[4],
                "reason": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]
