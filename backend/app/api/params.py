"""参数管理 API 路由。

提供参数列表、单个参数查询、参数更新、变更历史查询。
DEV_PARAM_CONFIG.md: L2级别参数通过前端界面实时调整。
CLAUDE.md: Service依赖注入统一用FastAPI的Depends链注入。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.services.param_service import ParamService, ParamValidationError

router = APIRouter(prefix="/api/params", tags=["params"])


def _get_param_service(
    session: AsyncSession = Depends(get_db),
) -> ParamService:
    """通过 Depends 注入 ParamService。"""
    return ParamService(session)


# ─── 请求/响应模型 ───


class UpdateParamRequest(BaseModel):
    """更新参数的请求体。"""

    value: Any = Field(..., description="新的参数值")
    reason: str = Field(..., min_length=1, max_length=500, description="变更原因（必填）")
    changed_by: str = Field(
        default="manual",
        description="变更者: manual/ai/system",
        pattern=r"^(manual|ai|system)$",
    )


# ─── 路由 ───


@router.get("")
async def list_params(
    module: str = Query(default="", description="按模块过滤: factor/signal/backtest/risk等"),
    svc: ParamService = Depends(_get_param_service),
) -> dict[str, Any]:
    """获取参数列表（按模块分组）。

    返回全部参数或指定模块的参数，包含当前值、默认值、约束范围。
    DB中已有的参数返回实际值，未入库的返回默认定义。

    Args:
        module: 模块名，为空时返回全部模块。

    Returns:
        按模块分组的参数字典:
        - modules: 所有模块名列表
        - params: {module_name: [param_dict, ...]}
    """
    modules = await svc.get_modules()
    params = await svc.get_all_params(module=module or None)
    return {
        "modules": modules,
        "params": params,
    }


@router.get("/changelog")
async def get_changelog(
    key: str = Query(default="", description="参数key，为空时返回全部"),
    limit: int = Query(default=50, ge=1, le=500, description="返回条数上限"),
    svc: ParamService = Depends(_get_param_service),
) -> list[dict[str, Any]]:
    """获取参数变更历史。

    按时间倒序返回param_change_log表记录。

    Args:
        key: 参数key，为空时返回全部参数的变更日志。
        limit: 返回条数上限，默认50。

    Returns:
        变更日志列表，每项含 id/param_name/old_value/new_value/changed_by/reason/created_at。
    """
    return await svc.get_change_log(key=key or None, limit=limit)


@router.get("/{key:path}")
async def get_param(
    key: str,
    svc: ParamService = Depends(_get_param_service),
) -> dict[str, Any]:
    """获取单个参数的当前值和元数据。

    优先从DB读取，DB无记录时返回默认定义值。

    Args:
        key: 参数key（如 factor.ic_threshold）。

    Returns:
        参数信息字典，含 param_name/param_value/param_type/module/description 等。

    Raises:
        HTTPException: 参数不存在时返回404。
    """
    try:
        return await svc.get_param(key)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.put("/{key:path}")
async def update_param(
    key: str,
    body: UpdateParamRequest,
    svc: ParamService = Depends(_get_param_service),
) -> dict[str, Any]:
    """更新参数值。

    更新前自动校验类型和范围约束，校验通过后写入DB并记录变更日志。

    Args:
        key: 参数key（如 factor.ic_threshold）。
        body: 包含 value（新值）和 reason（变更原因）的请求体。

    Returns:
        更新后的参数信息。

    Raises:
        HTTPException: 参数不存在(404)或校验失败(400)。
    """
    try:
        return await svc.update_param(
            key=key,
            value=body.value,
            reason=body.reason,
            changed_by=body.changed_by,
        )
    except ParamValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.post("/init-defaults")
async def init_defaults(
    svc: ParamService = Depends(_get_param_service),
) -> dict[str, Any]:
    """初始化默认参数到DB。

    将param_defaults.py中定义的参数写入ai_parameters表。
    仅写入DB中不存在的参数（不覆盖已有值）。

    Returns:
        初始化结果: {initialized_count: int}。
    """
    count = await svc.init_defaults()
    return {"initialized_count": count}
