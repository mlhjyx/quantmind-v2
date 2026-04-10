"""PMS (阶梯利润保护) API路由。"""

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter

from app.config import settings
from app.core.qmt_client import get_qmt_client
from app.services.db import get_sync_conn
from app.services.pms_engine import PMSEngine

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/pms", tags=["pms"])


@router.get("/positions")
def get_pms_positions() -> dict[str, Any]:
    """当前持仓监控列表（含浮盈/最高价/回撤/保护线距离）。"""
    engine = PMSEngine()
    conn = get_sync_conn()
    try:
        strategy_id = settings.PAPER_STRATEGY_ID
        positions = engine.sync_positions(conn, strategy_id)

        if not positions:
            return {"positions": [], "count": 0}

        codes = [p["code"] for p in positions]
        peak_prices = engine.get_peak_prices(conn, codes)

        # 从Redis读取当前价格，QMT代码格式
        from app.services.pms_engine import _to_qmt_code

        client = get_qmt_client()
        qmt_codes = [_to_qmt_code(c) for c in codes]
        current_prices = client.get_prices(qmt_codes)

        # Fallback: 非交易日/无实时数据时用klines_daily最新收盘价
        if not current_prices:
            cur = conn.cursor()
            for code in codes:
                cur.execute(
                    """SELECT close FROM klines_daily
                    WHERE code = %s ORDER BY trade_date DESC LIMIT 1""",
                    (code,),
                )
                row = cur.fetchone()
                if row and row[0]:
                    current_prices[_to_qmt_code(code)] = float(row[0])

        monitor_data = engine.build_monitor_data(positions, peak_prices, current_prices)
        return {"positions": monitor_data, "count": len(monitor_data)}
    finally:
        conn.close()


@router.get("/history")
def get_pms_history(limit: int = 50) -> dict[str, Any]:
    """历史PMS触发记录。"""
    conn = get_sync_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """SELECT symbol, entry_date, entry_price, peak_price, trigger_price,
                      unrealized_pnl_pct, drawdown_from_peak_pct,
                      pms_level_triggered, trigger_date, status
            FROM position_monitor
            WHERE pms_level_triggered IS NOT NULL
            ORDER BY trigger_date DESC, created_at DESC
            LIMIT %s""",
            (limit,),
        )
        rows = cur.fetchall()
        cols = [
            "symbol",
            "entry_date",
            "entry_price",
            "peak_price",
            "trigger_price",
            "unrealized_pnl_pct",
            "drawdown_from_peak_pct",
            "pms_level_triggered",
            "trigger_date",
            "status",
        ]
        history = []
        for row in rows:
            record = {}
            for i, col in enumerate(cols):
                val = row[i]
                if isinstance(val, date):
                    val = val.isoformat()
                elif hasattr(val, "__float__"):
                    val = float(val)
                record[col] = val
            history.append(record)

        return {"history": history, "count": len(history)}
    finally:
        conn.close()


@router.get("/config")
async def get_pms_config() -> dict[str, Any]:
    """当前PMS配置。"""
    return {
        "enabled": settings.PMS_ENABLED,
        "levels": [
            {
                "level": 1,
                "min_gain_pct": settings.PMS_LEVEL1_GAIN,
                "max_drawdown_pct": settings.PMS_LEVEL1_DRAWDOWN,
            },
            {
                "level": 2,
                "min_gain_pct": settings.PMS_LEVEL2_GAIN,
                "max_drawdown_pct": settings.PMS_LEVEL2_DRAWDOWN,
            },
            {
                "level": 3,
                "min_gain_pct": settings.PMS_LEVEL3_GAIN,
                "max_drawdown_pct": settings.PMS_LEVEL3_DRAWDOWN,
            },
        ],
    }


@router.post("/check")
def trigger_pms_check() -> dict[str, Any]:
    """手动触发一次PMS检查（调试用）。"""
    if not settings.PMS_ENABLED:
        return {"status": "disabled", "message": "PMS is disabled in .env"}

    engine = PMSEngine()
    conn = get_sync_conn()
    try:
        strategy_id = settings.PAPER_STRATEGY_ID
        positions = engine.sync_positions(conn, strategy_id)

        if not positions:
            return {"status": "ok", "message": "无持仓", "triggers": []}

        codes = [p["code"] for p in positions]
        peak_prices = engine.get_peak_prices(conn, codes)

        client = get_qmt_client()
        current_prices = client.get_prices(codes)

        sell_signals = engine.check_all_positions(positions, peak_prices, current_prices)

        triggers = []
        for sig in sell_signals:
            # 记录触发
            engine.record_trigger(conn, sig, strategy_id, date.today())
            triggers.append(
                {
                    "code": sig.code,
                    "level": sig.level,
                    "unrealized_pnl_pct": sig.unrealized_pnl_pct,
                    "drawdown_from_peak_pct": sig.drawdown_from_peak_pct,
                    "shares": sig.shares,
                }
            )

            # StreamBus广播
            try:
                from app.core.stream_bus import (
                    STREAM_PMS_PROTECTION_TRIGGERED,
                    get_stream_bus,
                )

                get_stream_bus().publish_sync(
                    STREAM_PMS_PROTECTION_TRIGGERED,
                    {
                        "code": sig.code,
                        "level": sig.level,
                        "pnl_pct": sig.unrealized_pnl_pct,
                        "drawdown_pct": sig.drawdown_from_peak_pct,
                        "current_price": sig.current_price,
                    },
                    source="pms_engine",
                )
            except Exception:
                pass

        conn.commit()
        return {
            "status": "ok",
            "checked": len(positions),
            "triggered": len(triggers),
            "triggers": triggers,
        }
    except Exception as exc:
        conn.rollback()
        logger.exception("[PMS] check failed")
        return {"status": "error", "message": str(exc)}
    finally:
        conn.close()
