"""参数管理 Service — 参数CRUD、校验、变更日志。

DEV_PARAM_CONFIG.md四级控制体系中的L2级别参数管理。
通过ParamRepository操作ai_parameters和param_change_log表，
通过param_defaults.py获取参数约束定义进行校验。

CLAUDE.md: Service依赖注入统一用FastAPI的Depends链注入。
"""

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.param_repository import ParamRepository
from app.services.param_defaults import (
    ParamDef,
    ParamType,
    get_all_param_defs,
    get_modules,
    get_param_def,
)


class ParamValidationError(ValueError):
    """参数校验失败时抛出。"""

    pass


class ParamService:
    """参数管理服务。

    提供参数查询、更新、校验、变更日志查询。
    策略参数走strategy_configs表（StrategyService管理），
    系统/模块级参数走ai_parameters表（本Service管理）。
    """

    def __init__(self, session: AsyncSession) -> None:
        self.repo = ParamRepository(session)

    async def get_all_params(self, module: str | None = None) -> dict[str, list[dict[str, Any]]]:
        """获取全部参数，按模块分组返回。

        DB中已有的参数从ai_parameters表读取，
        未入库的参数返回param_defaults.py中的默认定义。

        Args:
            module: 模块名，为None时返回全部模块。

        Returns:
            按模块分组的字典: {module_name: [param_dict, ...]}。
        """
        # 从DB读已有参数
        db_params = await self.repo.get_all_params(module=module)
        db_by_name: dict[str, dict[str, Any]] = {p["param_name"]: p for p in db_params}

        # 合并默认定义
        defs = get_all_param_defs(module=module)
        result: dict[str, list[dict[str, Any]]] = {}

        for key, param_def in defs.items():
            mod = param_def.module.value
            if mod not in result:
                result[mod] = []

            if key in db_by_name:
                # DB中有此参数，使用DB值
                entry = db_by_name[key]
                entry["description"] = param_def.description
                entry["level"] = param_def.level
                if param_def.enum_options:
                    entry["enum_options"] = param_def.enum_options
                result[mod].append(entry)
            else:
                # DB中无此参数，返回默认值
                result[mod].append(self._def_to_dict(param_def))

        # 加入DB中有但defaults中未定义的参数（AI动态创建的等）
        for name, db_param in db_by_name.items():
            if name not in defs:
                mod = db_param.get("module", "unknown")
                if module and mod != module:
                    continue
                if mod not in result:
                    result[mod] = []
                result[mod].append(db_param)

        return result

    async def get_param(self, key: str) -> dict[str, Any]:
        """获取单个参数的当前值和元数据。

        优先从DB读取，DB无记录时返回默认定义。

        Args:
            key: 参数key。

        Returns:
            参数信息字典。

        Raises:
            ValueError: 参数不存在（DB和默认定义中都没有）。
        """
        # 先查DB
        db_param = await self.repo.get_param(key)
        if db_param:
            # 补充默认定义中的描述等元数据
            param_def = get_param_def(key)
            if param_def:
                db_param["description"] = param_def.description
                db_param["level"] = param_def.level
                if param_def.enum_options:
                    db_param["enum_options"] = param_def.enum_options
            return db_param

        # DB无记录，查默认定义
        param_def = get_param_def(key)
        if param_def:
            return self._def_to_dict(param_def)

        raise ValueError(f"参数不存在: {key}")

    async def update_param(
        self,
        key: str,
        value: Any,
        reason: str,
        changed_by: str = "manual",
    ) -> dict[str, Any]:
        """更新参数值（含校验和变更日志）。

        CLAUDE.md工作原则: 参数变更必须记录reason。

        Args:
            key: 参数key。
            value: 新值。
            reason: 变更原因（必填）。
            changed_by: 变更者（manual/ai/system）。

        Returns:
            更新后的参数信息。

        Raises:
            ValueError: 参数不存在。
            ParamValidationError: 值不符合约束。
        """
        # 校验
        self.validate_param(key, value)

        # 获取旧值
        old_param = await self.repo.get_param(key)
        old_value = old_param["param_value"] if old_param else None

        # 获取参数定义
        param_def = get_param_def(key)
        if not param_def and not old_param:
            raise ValueError(f"参数不存在: {key}")

        if old_param:
            # DB中已有，直接更新值
            await self.repo.update_param_value(key, value, updated_by=changed_by)
        else:
            # DB中无记录，从默认定义创建
            assert param_def is not None  # validate_param已确认存在
            await self.repo.upsert_param(
                param_name=key,
                param_value=value,
                param_type=param_def.param_type.value,
                module=param_def.module.value,
                param_default=param_def.default_value,
                param_min=param_def.min_value,
                param_max=param_def.max_value,
                updated_by=changed_by,
            )

        # 写变更日志
        await self.repo.insert_change_log(
            param_name=key,
            old_value=old_value,
            new_value=value,
            changed_by=changed_by,
            reason=reason,
        )

        # 返回更新后的参数
        return await self.get_param(key)

    def validate_param(self, key: str, value: Any) -> None:
        """校验参数值是否符合约束。

        检查项:
        1. 参数key是否存在
        2. 类型是否匹配
        3. 数值范围是否在[min, max]内
        4. 枚举值是否在选项列表内

        Args:
            key: 参数key。
            value: 待校验的值。

        Raises:
            ParamValidationError: 校验失败。
        """
        param_def = get_param_def(key)
        if not param_def:
            # 允许更新DB中已有但defaults未定义的参数（跳过约束校验）
            return

        # 类型校验
        self._validate_type(param_def, value)

        # 范围校验
        if (
            param_def.min_value is not None
            and isinstance(value, (int, float))
            and value < param_def.min_value
        ):
            raise ParamValidationError(f"参数 {key} 值 {value} 低于最小值 {param_def.min_value}")
        if (
            param_def.max_value is not None
            and isinstance(value, (int, float))
            and value > param_def.max_value
        ):
            raise ParamValidationError(f"参数 {key} 值 {value} 超过最大值 {param_def.max_value}")

        # 枚举校验
        if param_def.enum_options is not None and value not in param_def.enum_options:
            raise ParamValidationError(
                f"参数 {key} 值 {value!r} 不在可选列表 {param_def.enum_options} 中"
            )

    async def get_change_log(
        self,
        key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """查询参数变更历史。

        Args:
            key: 参数key，为None时返回全部参数的变更日志。
            limit: 返回条数上限。

        Returns:
            变更日志列表，按时间倒序。
        """
        return await self.repo.get_change_log(param_name=key, limit=limit)

    async def rollback_to(
        self,
        timestamp: datetime,
        reason: str,
        changed_by: str = "system",
    ) -> dict[str, Any]:
        """将所有参数回滚到指定时间点的状态 (DEV_PARAM_CONFIG §4.4 一键回滚)。

        回滚 = 对每个在 timestamp 之后变更过的参数, 将其值恢复为该时点的值
        (param_change_log 中该参数 post-T 最早一条变更的 old_value)。回滚动作
        本身写入 param_change_log 审计 (reason 带 [rollback→T] 前缀便于检索)。

        timestamp 之后才首次创建的参数 (该时点尚不存在) 不回滚, 也不删除参数行,
        在返回的 skipped_created_after 中报告, 由调用方决定是否单独处理。

        回滚按历史值原样恢复, 不重新做 min/max 校验 —— 该值在当初被设置时已
        校验通过, rollback 是状态还原而非新增变更。

        Args:
            timestamp: 回滚目标时间点 (tz-aware ISO datetime)。
            reason: 回滚原因 (必填, 写入审计)。
            changed_by: 发起者 manual/ai/system (审计 changed_by + updated_by)。

        Returns:
            回滚摘要字典:
            - timestamp: 回滚目标时间点 ISO 串
            - rolled_back: 已回滚的参数名列表 (按名称排序)
            - rolled_back_count: 已回滚数量
            - skipped_created_after: 因 T 之后才创建而跳过的参数名列表
            - skipped_count: 跳过数量
        """
        audit_reason = f"[rollback→{timestamp.isoformat()}] {reason}"
        outcome = await self.repo.rollback_to(timestamp, reason=audit_reason, changed_by=changed_by)
        rolled_back = sorted(outcome["rolled_back"])
        skipped = sorted(outcome["skipped"])
        return {
            "timestamp": timestamp.isoformat(),
            "rolled_back": rolled_back,
            "rolled_back_count": len(rolled_back),
            "skipped_created_after": skipped,
            "skipped_count": len(skipped),
        }

    async def init_defaults(self) -> int:
        """将param_defaults中的参数定义初始化到DB。

        仅写入DB中不存在的参数（不覆盖已有值）。
        用于首次部署或新增参数定义后的初始化。

        Returns:
            新写入的参数数量。
        """
        defs = get_all_param_defs()
        count = 0
        for key, param_def in defs.items():
            existing = await self.repo.get_param(key)
            if not existing:
                await self.repo.upsert_param(
                    param_name=key,
                    param_value=param_def.default_value,
                    param_type=param_def.param_type.value,
                    module=param_def.module.value,
                    param_default=param_def.default_value,
                    param_min=param_def.min_value,
                    param_max=param_def.max_value,
                    updated_by="system",
                )
                count += 1
        return count

    async def get_modules(self) -> list[str]:
        """获取所有模块名列表。"""
        return get_modules()

    # ─── 内部方法 ───

    @staticmethod
    def _validate_type(param_def: ParamDef, value: Any) -> None:
        """校验值类型是否匹配参数定义。

        Args:
            param_def: 参数定义。
            value: 待校验值。

        Raises:
            ParamValidationError: 类型不匹配。
        """
        pt = param_def.param_type
        if pt == ParamType.INT:
            if not isinstance(value, int) or isinstance(value, bool):
                raise ParamValidationError(
                    f"参数 {param_def.key} 类型应为int，实际为 {type(value).__name__}"
                )
        elif pt == ParamType.FLOAT:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ParamValidationError(
                    f"参数 {param_def.key} 类型应为float，实际为 {type(value).__name__}"
                )
        elif pt == ParamType.BOOL:
            if not isinstance(value, bool):
                raise ParamValidationError(
                    f"参数 {param_def.key} 类型应为bool，实际为 {type(value).__name__}"
                )
        elif pt == ParamType.STR:
            if not isinstance(value, str):
                raise ParamValidationError(
                    f"参数 {param_def.key} 类型应为str，实际为 {type(value).__name__}"
                )
        elif pt == ParamType.ENUM:
            if not isinstance(value, str):
                raise ParamValidationError(
                    f"参数 {param_def.key} 类型应为str(enum)，实际为 {type(value).__name__}"
                )
        elif pt == ParamType.LIST and not isinstance(value, list):
            raise ParamValidationError(
                f"参数 {param_def.key} 类型应为list，实际为 {type(value).__name__}"
            )

    @staticmethod
    def _def_to_dict(param_def: ParamDef) -> dict[str, Any]:
        """将参数定义转换为API返回格式。

        Args:
            param_def: 参数定义。

        Returns:
            参数信息字典。
        """
        d: dict[str, Any] = {
            "param_name": param_def.key,
            "param_value": param_def.default_value,
            "param_min": param_def.min_value,
            "param_max": param_def.max_value,
            "param_default": param_def.default_value,
            "param_type": param_def.param_type.value,
            "module": param_def.module.value,
            "description": param_def.description,
            "level": param_def.level,
            "updated_by": "default",
        }
        if param_def.enum_options:
            d["enum_options"] = param_def.enum_options
        return d


# ─── 参数变更影响预估 (DEV_PARAM_CONFIG §4.2) ───

# 影响预估公式: 键为真实参数 key (param_defaults dotted key)。每个公式接收
# float(old) / float(new), 返回人类可读影响串。仅做事实性陈述 (单位换算 /
# 重述), 不做启发式预测 —— 凭空预测数字 (换手率/成本变化) 会误导用户。
_PARAM_IMPACT_FORMULAS: dict[str, Callable[[float, float], str]] = {
    "signal.top_n": lambda o, n: f"选股数 {int(o)} → {int(n)} 只",
    "signal.turnover_cap": lambda o, n: f"换手率上限 {o * 100:.0f}% → {n * 100:.0f}%",
    "signal.industry_cap": lambda o, n: f"行业权重上限 {o * 100:.0f}% → {n * 100:.0f}%",
    "signal.single_stock_cap": lambda o, n: f"单股权重上限 {o * 100:.0f}% → {n * 100:.0f}%",
    "backtest.initial_capital": lambda o, n: f"初始资金 ¥{o:,.0f} → ¥{n:,.0f}",
}


def estimate_param_impact(param_name: str, old_value: Any, new_value: Any) -> str:
    """预估参数变更影响, 返回人类可读说明 (DEV_PARAM_CONFIG §4.2)。

    用于前端参数变更确认弹窗。对 _PARAM_IMPACT_FORMULAS 中登记的数值型参数
    给出单位换算后的事实陈述; 其余参数 (及任一值无法转 float 时) 回退为通用
    `{name}: {old} → {new}` 串。不做启发式预测 (换手率/成本预测等 —— 凭空
    数字会误导用户, 反 fake-precision)。

    Args:
        param_name: 参数 key (param_defaults dotted key)。
        old_value: 当前值。
        new_value: 拟变更的新值。

    Returns:
        影响说明字符串。
    """
    formula = _PARAM_IMPACT_FORMULAS.get(param_name)
    if formula is not None:
        try:
            return formula(float(old_value), float(new_value))
        except (TypeError, ValueError):
            pass  # silent_ok: 值非数值 → 回退通用串 (formula 仅适用数值参数)
    return f"{param_name}: {old_value} → {new_value}"
