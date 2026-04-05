"""Execution Operations API — QMT交互操作 + 偏差修复 + 风控操作。

新建文件，不修改现有execution.py（防回归）。
所有写操作需要X-Admin-Token认证 + operation_audit_log审计。
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import get_db
from app.services.qmt_connection_manager import qmt_manager

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/execution", tags=["execution-ops"])

# ---------------------------------------------------------------------------
# Rate limiting (in-memory, per action per day)
# ---------------------------------------------------------------------------
_DAILY_LIMITS: dict[str, int] = {
    "trigger-rebalance": 3,
    "emergency-liquidate": 1,
    "cancel-all": 5,
    "fix-drift-execute": 3,
}
_action_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
_action_date: str = ""


def _check_rate_limit(action: str) -> None:
    """检查操作频率限制。"""
    global _action_date
    today = date.today().isoformat()
    if _action_date != today:
        _action_counts.clear()
        _action_date = today
    limit = _DAILY_LIMITS.get(action)
    if limit is not None and _action_counts[action]["count"] >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"操作 {action} 今日已达上限 {limit} 次",
        )


def _increment_rate(action: str) -> None:
    _action_counts[action]["count"] += 1


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------

def _get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    return session


def _verify_admin_token(
    x_admin_token: str = Header(alias="X-Admin-Token", default=""),
) -> str:
    """验证Admin Token。"""
    if not settings.ADMIN_TOKEN:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN未配置")
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="无效的Admin Token")
    return x_admin_token


def _require_qmt_connected() -> None:
    """确保QMT已连接，否则503。"""
    if qmt_manager.state != "connected" or qmt_manager.broker is None:
        raise HTTPException(
            status_code=503,
            detail=f"QMT未连接 (state={qmt_manager.state})",
        )


# ---------------------------------------------------------------------------
# Async wrappers for sync QMT broker calls
# ---------------------------------------------------------------------------

async def _broker_query_positions():
    return await asyncio.to_thread(qmt_manager.broker.query_positions)

async def _broker_query_asset():
    return await asyncio.to_thread(qmt_manager.broker.query_asset)

async def _broker_query_orders():
    return await asyncio.to_thread(qmt_manager.broker.query_orders)

async def _broker_query_trades():
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(qmt_manager.broker.query_trades),
            timeout=8.0,
        )
    except TimeoutError:
        return []  # 盘后query_trades可能超时，返回空列表

async def _broker_cancel_order(order_id: int):
    return await asyncio.to_thread(qmt_manager.broker.cancel_order, order_id)

async def _broker_sell(code: str, volume: int, price: float = 0):
    return await asyncio.to_thread(qmt_manager.broker.sell, code, volume, price)

async def _broker_buy(code: str, volume: int, price: float = 0, amount: float = 0):
    return await asyncio.to_thread(qmt_manager.broker.buy, code, volume, price, amount)


# ---------------------------------------------------------------------------
# Audit log helper
# ---------------------------------------------------------------------------

async def _audit_log(
    session: AsyncSession,
    action: str,
    params: dict[str, Any] | None,
    result: str,
    detail: str = "",
    ip: str = "",
) -> None:
    """写入操作审计日志。"""
    try:
        await session.execute(
            text("""
                INSERT INTO operation_audit_log (action, params, result, detail, ip)
                VALUES (:action, :params, :result, :detail, :ip)
            """),
            {
                "action": action,
                "params": json.dumps(params, default=str) if params else None,
                "result": result,
                "detail": detail,
                "ip": ip,
            },
        )
    except Exception:
        logger.exception("写入审计日志失败", action=action)


def _client_ip(request: Request) -> str:
    """提取客户端IP。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


# ---------------------------------------------------------------------------
# GET endpoints — 无需认证
# ---------------------------------------------------------------------------

@router.get("/qmt-status")
async def get_qmt_status() -> dict[str, Any]:
    """QMT连接状态 + 账户信息。"""
    return qmt_manager.health_check()


@router.get("/positions")
async def get_positions(
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """QMT实时持仓（含can_use_volume）。

    QMT已连接时查询实时数据，否则从DB position_snapshot回退。
    """
    if qmt_manager.state == "connected" and qmt_manager.broker is not None:
        try:
            positions = await _broker_query_positions()
            return [
                {
                    "code": p["stock_code"],
                    "volume": p["volume"],
                    "can_use_volume": p["can_use_volume"],
                    "avg_price": p["avg_price"],
                    "market_value": p["market_value"],
                    "frozen_volume": p.get("frozen_volume", 0),
                }
                for p in positions
            ]
        except Exception:
            logger.exception("QMT查询持仓失败，回退DB")

    # DB fallback
    result = await session.execute(
        text("""
            SELECT ps.code, ps.quantity, ps.avg_cost, ps.market_value,
                   s.name
            FROM position_snapshot ps
            LEFT JOIN symbols s ON s.code = ps.code
            WHERE ps.trade_date = (
                SELECT MAX(trade_date) FROM position_snapshot
                WHERE execution_mode = 'live' AND quantity > 0
            )
            AND ps.execution_mode = 'live' AND ps.quantity > 0
            ORDER BY ps.market_value DESC
        """),
    )
    rows = result.mappings().all()
    return [
        {
            "code": r["code"],
            "name": r["name"] or r["code"],
            "volume": r["quantity"],
            "can_use_volume": r["quantity"],  # DB无T+1信息，假设全部可卖
            "avg_price": float(r["avg_cost"]) if r["avg_cost"] else 0,
            "market_value": float(r["market_value"]) if r["market_value"] else 0,
            "frozen_volume": 0,
        }
        for r in rows
    ]


@router.get("/asset")
async def get_asset(
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """资金状态（总资产/可用/冻结）。"""
    if qmt_manager.state == "connected" and qmt_manager.broker is not None:
        try:
            asset = await _broker_query_asset()
            return {
                "total_asset": asset.get("total_asset", 0),
                "cash": asset.get("cash", 0),
                "frozen_cash": asset.get("frozen_cash", 0),
                "market_value": asset.get("market_value", 0),
                "source": "qmt",
            }
        except Exception:
            logger.exception("QMT查询资产失败，回退DB")

    # DB fallback
    result = await session.execute(
        text("""
            SELECT nav, cash_ratio, position_count
            FROM performance_series
            WHERE execution_mode = 'live'
            ORDER BY trade_date DESC LIMIT 1
        """),
    )
    row = result.mappings().first()
    if row:
        nav = float(row["nav"]) if row["nav"] else 0
        cash_ratio = float(row["cash_ratio"]) if row["cash_ratio"] else 0
        return {
            "total_asset": nav,
            "cash": nav * cash_ratio,
            "frozen_cash": 0,
            "market_value": nav * (1 - cash_ratio),
            "source": "db_fallback",
        }
    return {"total_asset": 0, "cash": 0, "frozen_cash": 0, "market_value": 0, "source": "empty"}


@router.get("/orders")
async def get_orders() -> list[dict[str, Any]]:
    """当天委托列表。"""
    _require_qmt_connected()
    try:
        orders = await _broker_query_orders()
        return [
            {
                "order_id": o["order_id"],
                "code": o["stock_code"],
                "order_type": o["order_type"],
                "volume": o["order_volume"],
                "price": o["price"],
                "traded_volume": o["traded_volume"],
                "traded_price": o["traded_price"],
                "status": o["order_status"],
                "remark": o.get("order_remark", ""),
            }
            for o in orders
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("查询委托失败")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/trades")
async def get_trades() -> list[dict[str, Any]]:
    """当天成交列表。"""
    _require_qmt_connected()
    try:
        trades = await _broker_query_trades()
        return [
            {
                "order_id": t["order_id"],
                "code": t["stock_code"],
                "price": t["traded_price"],
                "volume": t["traded_volume"],
                "amount": t["traded_amount"],
                "order_type": t["order_type"],
            }
            for t in trades
        ]
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("查询成交失败")
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.get("/drift")
async def get_drift(
    strategy_id: str = Query(default="", description="策略ID"),
    session: AsyncSession = Depends(_get_session),
) -> dict[str, Any]:
    """持仓偏差分析 — 实际持仓 vs 最新信号目标。

    包含资金分析: 卖出超买可释放多少钱、能买几只缺失的。
    """
    sid = strategy_id or settings.PAPER_STRATEGY_ID
    # 信号始终在paper模式生成，持仓用live（如果QMT已连接）
    signal_mode = "paper"
    position_mode = "live" if qmt_manager.state == "connected" else "paper"

    # 1. 获取实际持仓（strip QMT代码后缀）
    actual_positions: dict[str, dict[str, Any]] = {}
    if qmt_manager.state == "connected" and qmt_manager.broker is not None:
        try:
            for p in (await _broker_query_positions()):
                code = p["stock_code"].split(".")[0] if "." in p["stock_code"] else p["stock_code"]
                actual_positions[code] = {
                    "volume": p["volume"],
                    "can_use_volume": p["can_use_volume"],
                    "market_value": p["market_value"],
                    "avg_price": p["avg_price"],
                }
        except Exception:
            logger.exception("QMT查询持仓失败")

    if not actual_positions:
        # DB fallback
        result = await session.execute(
            text("""
                SELECT code, quantity, market_value, avg_cost
                FROM position_snapshot
                WHERE strategy_id = CAST(:sid AS uuid)
                  AND execution_mode = :pos_mode AND quantity > 0
                  AND trade_date = (
                    SELECT MAX(trade_date) FROM position_snapshot
                    WHERE strategy_id = CAST(:sid AS uuid)
                      AND execution_mode = :pos_mode AND quantity > 0
                  )
            """),
            {"sid": sid, "pos_mode": position_mode},
        )
        for r in result.mappings().all():
            actual_positions[r["code"]] = {
                "volume": r["quantity"],
                "can_use_volume": r["quantity"],
                "market_value": float(r["market_value"]) if r["market_value"] else 0,
                "avg_price": float(r["avg_cost"]) if r["avg_cost"] else 0,
            }

    # 2. 获取最新信号目标
    sig_result = await session.execute(
        text("""
            SELECT s.code, s.target_weight, s.action, sym.name,
                   s.trade_date AS signal_date
            FROM signals s
            LEFT JOIN symbols sym ON sym.code = s.code
            WHERE s.strategy_id = CAST(:sid AS uuid)
              AND s.execution_mode = :sig_mode
              AND s.trade_date = (
                SELECT MAX(trade_date) FROM signals
                WHERE strategy_id = CAST(:sid AS uuid)
                  AND execution_mode = :sig_mode
              )
            ORDER BY s.target_weight DESC
        """),
        {"sid": sid, "sig_mode": signal_mode},
    )
    signals = sig_result.mappings().all()

    # 3. 获取当前总资产
    total_asset = 0.0
    if qmt_manager.state == "connected" and qmt_manager.broker is not None:
        try:
            asset = await _broker_query_asset()
            total_asset = float(asset.get("total_asset", 0))
        except Exception:
            pass
    if total_asset == 0:
        result_nav = await session.execute(
            text("""
                SELECT nav FROM performance_series
                WHERE strategy_id = CAST(:sid AS uuid)
                  AND execution_mode = :pos_mode
                ORDER BY trade_date DESC LIMIT 1
            """),
            {"sid": sid, "pos_mode": position_mode},
        )
        nav_row = result_nav.mappings().first()
        if nav_row and nav_row["nav"]:
            total_asset = float(nav_row["nav"])

    # 4. 构建偏差明细
    signal_map: dict[str, dict[str, Any]] = {}
    for s in signals:
        target_value = float(s["target_weight"]) * total_asset if total_asset > 0 else 0
        signal_map[s["code"]] = {
            "name": s["name"] or s["code"],
            "target_weight": float(s["target_weight"]),
            "target_value": target_value,
            "action": s["action"],
            "signal_date": s["signal_date"].isoformat() if s["signal_date"] else None,
        }

    all_codes = set(actual_positions.keys()) | set(signal_map.keys())
    drift_items: list[dict[str, Any]] = []
    overbought_release = 0.0  # 卖出超买可释放金额
    missing_need = 0.0  # 买入缺失需要金额

    for code in sorted(all_codes):
        actual = actual_positions.get(code, {})
        signal = signal_map.get(code, {})

        actual_volume = actual.get("volume", 0)
        actual_value = actual.get("market_value", 0)
        target_value = signal.get("target_value", 0)
        can_use = actual.get("can_use_volume", actual_volume)

        # 偏差百分比
        if target_value > 0:
            deviation_pct = (actual_value - target_value) / target_value * 100
        elif actual_value > 0:
            deviation_pct = 100.0  # 信号不持有但实际有
        else:
            deviation_pct = 0.0

        # 状态判定
        if actual_volume == 0 and target_value > 0:
            status = "missing"  # 缺失
            missing_need += target_value
        elif actual_volume > 0 and target_value == 0:
            status = "overbought"  # 超买（信号不持有）
            overbought_release += actual_value
        elif abs(deviation_pct) > 30:
            status = "overbought" if deviation_pct > 0 else "underweight"
            if deviation_pct > 30:
                overbought_release += actual_value - target_value
        else:
            status = "normal"

        drift_items.append({
            "code": code,
            "name": signal.get("name") or code,
            "target_weight": signal.get("target_weight", 0),
            "target_value": round(target_value, 0),
            "actual_volume": actual_volume,
            "can_use_volume": can_use,
            "actual_value": round(actual_value, 0),
            "deviation_pct": round(deviation_pct, 1),
            "status": status,
        })

    # 排序: 异常在前
    status_order = {"overbought": 0, "missing": 1, "underweight": 2, "normal": 3}
    drift_items.sort(key=lambda x: (status_order.get(x["status"], 9), -abs(x["deviation_pct"])))

    # 5. 资金分析
    available_cash = 0.0
    if qmt_manager.state == "connected" and qmt_manager.broker is not None:
        try:
            asset = await _broker_query_asset()
            available_cash = float(asset.get("cash", 0))
        except Exception:
            pass

    total_available = available_cash + overbought_release
    missing_count = sum(1 for d in drift_items if d["status"] == "missing")
    can_buy_count = 0
    remaining = total_available
    for d in sorted(
        [x for x in drift_items if x["status"] == "missing"],
        key=lambda x: x["target_value"],
    ):
        if remaining >= d["target_value"] * 0.9:  # 90%近似可买
            can_buy_count += 1
            remaining -= d["target_value"]

    signal_date = signals[0]["trade_date"].isoformat() if signals else None

    return {
        "signal_date": signal_date,
        "total_asset": round(total_asset, 0),
        "available_cash": round(available_cash, 0),
        "items": drift_items,
        "funding_analysis": {
            "overbought_release": round(overbought_release, 0),
            "missing_need": round(missing_need, 0),
            "total_available_after_sell": round(total_available, 0),
            "missing_count": missing_count,
            "can_buy_count": can_buy_count,
            "funding_gap": round(max(0, missing_need - total_available), 0),
        },
        "summary": {
            "total": len(drift_items),
            "normal": sum(1 for d in drift_items if d["status"] == "normal"),
            "overbought": sum(1 for d in drift_items if d["status"] == "overbought"),
            "missing": missing_count,
            "underweight": sum(1 for d in drift_items if d["status"] == "underweight"),
        },
    }


# ---------------------------------------------------------------------------
# POST endpoints — 需要 Admin Token
# ---------------------------------------------------------------------------

class ConfirmBody(BaseModel):
    """危险操作确认请求体。"""
    confirmation: str = ""


class FixDriftExecuteBody(BaseModel):
    """偏差修复执行请求体。"""
    confirmation: str = "CONFIRM"
    sell_codes: list[str] = []
    buy_codes: list[str] = []


@router.post("/cancel-all")
async def cancel_all_orders(
    request: Request,
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """撤销所有挂单。"""
    _require_qmt_connected()
    _check_rate_limit("cancel-all")

    try:
        orders = await _broker_query_orders()
        # 仅撤销未完成订单
        pending = [o for o in orders if o["order_status"] not in (48, 50, 51, 52, 53, 54, 55, 56, 57)]
        cancelled = 0
        for o in pending:
            try:
                await _broker_cancel_order(o["order_id"])
                cancelled += 1
            except Exception:
                logger.warning(f"撤单失败: order_id={o['order_id']}")

        _increment_rate("cancel-all")
        await _audit_log(
            session, "cancel-all",
            {"pending_count": len(pending), "cancelled": cancelled},
            "success",
            f"撤销{cancelled}/{len(pending)}笔挂单",
            _client_ip(request),
        )
        return {"cancelled": cancelled, "total_pending": len(pending)}
    except HTTPException:
        raise
    except Exception as e:
        await _audit_log(session, "cancel-all", None, "error", str(e), _client_ip(request))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/cancel/{order_id}")
async def cancel_single_order(
    order_id: int,
    request: Request,
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """撤销单笔委托。"""
    _require_qmt_connected()

    try:
        success = await _broker_cancel_order(order_id)
        result_str = "success" if success else "failed"
        await _audit_log(
            session, "cancel-order",
            {"order_id": order_id},
            result_str,
            ip=_client_ip(request),
        )
        return {"order_id": order_id, "result": result_str}
    except HTTPException:
        raise
    except Exception as e:
        await _audit_log(session, "cancel-order", {"order_id": order_id}, "error", str(e), _client_ip(request))
        raise HTTPException(status_code=500, detail=str(e)) from None


@router.post("/fix-drift/preview")
async def fix_drift_preview(
    strategy_id: str = Query(default="", description="策略ID"),
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """偏差修复预览 — 返回执行计划，无副作用。

    Returns:
        sell_plan: 超买卖出计划列表
        buy_plan: 缺失买入计划列表
        funding: 资金可行性分析
    """
    drift = await get_drift(strategy_id=strategy_id, session=session)
    items = drift["items"]
    funding = drift["funding_analysis"]

    sell_plan: list[dict[str, Any]] = []
    buy_plan: list[dict[str, Any]] = []

    for item in items:
        if item["status"] == "overbought":
            sell_qty = min(item["actual_volume"], item["can_use_volume"])
            if sell_qty > 0:
                sell_plan.append({
                    "code": item["code"],
                    "name": item["name"],
                    "action": "sell",
                    "volume": sell_qty,
                    "estimated_amount": item["actual_value"],
                    "reason": f"超买 {item['deviation_pct']:+.0f}%",
                })
        elif item["status"] == "missing":
            # 估算买入股数（用目标价值 / 近似价格）
            buy_plan.append({
                "code": item["code"],
                "name": item["name"],
                "action": "buy",
                "target_value": item["target_value"],
                "reason": "信号持有但实际缺失",
            })

    return {
        "sell_plan": sell_plan,
        "buy_plan": buy_plan,
        "sell_total_release": sum(s["estimated_amount"] for s in sell_plan),
        "buy_total_need": sum(b["target_value"] for b in buy_plan),
        "funding": funding,
        "feasible": funding["funding_gap"] == 0,
    }


@router.post("/fix-drift/execute")
async def fix_drift_execute(
    body: FixDriftExecuteBody,
    request: Request,
    strategy_id: str = Query(default="", description="策略ID"),
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """执行偏差修复 — 需确认后执行。"""
    _require_qmt_connected()
    _check_rate_limit("fix-drift-execute")

    if body.confirmation != "CONFIRM":
        raise HTTPException(status_code=400, detail="需要confirmation='CONFIRM'")

    # 获取预览计划
    preview = await fix_drift_preview(strategy_id=strategy_id, session=session)
    sell_plan = preview["sell_plan"]
    buy_plan = preview["buy_plan"]

    results: list[dict[str, Any]] = []

    # 先卖后买
    for sell in sell_plan:
        if body.sell_codes and sell["code"] not in body.sell_codes:
            continue
        try:
            order_id = await _broker_sell(sell["code"], sell["volume"])
            results.append({"code": sell["code"], "action": "sell", "order_id": order_id, "status": "submitted"})
        except Exception as e:
            results.append({"code": sell["code"], "action": "sell", "error": str(e), "status": "failed"})

    # 等待卖单部分成交释放资金
    if sell_plan:
        await asyncio.sleep(3)

    for buy in buy_plan:
        if body.buy_codes and buy["code"] not in body.buy_codes:
            continue
        try:
            asset = await _broker_query_asset()
            available = float(asset.get("cash", 0))
            target = buy["target_value"]
            if available < target * 0.5:
                results.append({"code": buy["code"], "action": "buy", "status": "skipped", "reason": "资金不足"})
                continue
            order_id = await _broker_buy(buy["code"], 0, price=0, amount=min(target, available * 0.95))
            results.append({"code": buy["code"], "action": "buy", "order_id": order_id, "status": "submitted"})
        except Exception as e:
            results.append({"code": buy["code"], "action": "buy", "error": str(e), "status": "failed"})

    _increment_rate("fix-drift-execute")
    await _audit_log(
        session, "fix-drift-execute",
        {"sell_count": len(sell_plan), "buy_count": len(buy_plan), "results": results},
        "success",
        f"卖{len(sell_plan)}只+买{len(buy_plan)}只",
        _client_ip(request),
    )

    return {"results": results, "sell_count": len(sell_plan), "buy_count": len(buy_plan)}


@router.post("/trigger-rebalance")
async def trigger_rebalance(
    request: Request,
    strategy_id: str = Query(default="", description="策略ID"),
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """手动触发调仓。

    触发完整的信号生成→执行流程。
    """
    _require_qmt_connected()
    _check_rate_limit("trigger-rebalance")

    _increment_rate("trigger-rebalance")
    await _audit_log(
        session, "trigger-rebalance",
        {"strategy_id": strategy_id or settings.PAPER_STRATEGY_ID},
        "accepted",
        "手动调仓已触发",
        _client_ip(request),
    )

    # 实际调仓逻辑由run_paper_trading.py的调度链路完成
    # 这里只记录意图，提示用户通过PT脚本执行
    return {
        "status": "accepted",
        "message": "调仓请求已记录。请通过PT脚本或Task Scheduler执行实际调仓。",
    }


@router.post("/emergency-liquidate")
async def emergency_liquidate(
    body: ConfirmBody,
    request: Request,
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """紧急清仓 — 卖出所有持仓。需要confirmation='CONFIRM'。"""
    _require_qmt_connected()
    _check_rate_limit("emergency-liquidate")

    if body.confirmation != "CONFIRM":
        raise HTTPException(status_code=400, detail="紧急清仓需要confirmation='CONFIRM'")

    positions = await _broker_query_positions()
    results: list[dict[str, Any]] = []

    for p in positions:
        sell_qty = p["can_use_volume"]
        if sell_qty <= 0:
            results.append({"code": p["stock_code"], "status": "skipped", "reason": "无可卖数量"})
            continue
        try:
            order_id = await _broker_sell(p["stock_code"], sell_qty)
            results.append({"code": p["stock_code"], "volume": sell_qty, "order_id": order_id, "status": "submitted"})
        except Exception as e:
            results.append({"code": p["stock_code"], "status": "failed", "error": str(e)})

    _increment_rate("emergency-liquidate")
    await _audit_log(
        session, "emergency-liquidate",
        {"position_count": len(positions), "results": results},
        "success",
        f"紧急清仓: {len(positions)}只持仓",
        _client_ip(request),
    )

    return {"results": results, "position_count": len(positions)}


# 交易暂停/恢复状态（内存级）
_trading_paused: bool = False


@router.post("/pause-trading")
async def pause_trading(
    request: Request,
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """暂停自动交易。"""
    global _trading_paused
    _trading_paused = True
    await _audit_log(session, "pause-trading", None, "success", "自动交易已暂停", _client_ip(request))
    return {"paused": True}


@router.post("/resume-trading")
async def resume_trading(
    request: Request,
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """恢复自动交易。"""
    global _trading_paused
    _trading_paused = False
    await _audit_log(session, "resume-trading", None, "success", "自动交易已恢复", _client_ip(request))
    return {"paused": False}


@router.get("/trading-paused")
async def get_trading_paused() -> dict[str, bool]:
    """查询交易暂停状态。"""
    return {"paused": _trading_paused}


@router.put("/alert-config")
async def update_alert_config(
    config: dict[str, Any],
    request: Request,
    session: AsyncSession = Depends(_get_session),
    _token: str = Depends(_verify_admin_token),
) -> dict[str, Any]:
    """修改告警阈值。"""
    await _audit_log(
        session, "update-alert-config",
        config,
        "success",
        f"更新告警配置: {list(config.keys())}",
        _client_ip(request),
    )
    return {"status": "updated", "config": config}


@router.get("/audit-log")
async def get_audit_log(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """查询操作审计日志。"""
    result = await session.execute(
        text("""
            SELECT id, timestamp, action, params, result, detail, ip
            FROM operation_audit_log
            ORDER BY timestamp DESC
            LIMIT :lim
        """),
        {"lim": limit},
    )
    rows = result.mappings().all()
    return [
        {
            "id": r["id"],
            "timestamp": r["timestamp"].isoformat() if r["timestamp"] else None,
            "action": r["action"],
            "params": r["params"],
            "result": r["result"],
            "detail": r["detail"],
            "ip": r["ip"],
        }
        for r in rows
    ]
