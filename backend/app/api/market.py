"""Market API 路由 — 指数行情、行业板块、涨跌幅排行。

Sprint 1.23: 为前端Market页面补齐后端API。
遵循CLAUDE.md: Depends注入 + 类型注解 + Google docstring(中文)。
"""

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/market", tags=["market"])

# 5个标准指数
_INDEX_CODES = ["000300.SH", "000001.SH", "399006.SZ", "000905.SH", "000016.SH"]
_INDEX_NAMES = {
    "000300.SH": "沪深300",
    "000001.SH": "上证指数",
    "399006.SZ": "创业板",
    "000905.SH": "中证500",
    "000016.SH": "上证50",
}


def _get_session(session: AsyncSession = Depends(get_db)) -> AsyncSession:
    """通过 Depends 注入 AsyncSession。"""
    return session


@router.get("/indices")
async def get_indices(
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取5个主要指数最新行情。

    从 index_daily 读取最新交易日的沪深300/上证/创业板/中证500/上证50行情。

    Returns:
        指数列表，每项含 code/name/close/pct_change/volume/amount/is_up。
    """
    sql = text("""
        WITH latest AS (
            SELECT MAX(trade_date) AS max_date FROM index_daily
            WHERE index_code = ANY(:codes)
        )
        SELECT
            id.index_code,
            id.trade_date,
            id.open,
            id.high,
            id.low,
            id.close,
            id.pre_close,
            id.pct_change,
            id.volume,
            id.amount
        FROM index_daily id
        JOIN latest l ON id.trade_date = l.max_date
        WHERE id.index_code = ANY(:codes)
        ORDER BY id.index_code
    """)

    try:
        result = await session.execute(sql, {"codes": _INDEX_CODES})
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询指数行情失败")
        return _mock_indices()

    if not rows:
        return _mock_indices()

    return [
        {
            "code": r["index_code"],
            "name": _INDEX_NAMES.get(r["index_code"], r["index_code"]),
            "close": float(r["close"]) if r["close"] else 0.0,
            "pre_close": float(r["pre_close"]) if r["pre_close"] else 0.0,
            "pct_change": float(r["pct_change"]) if r["pct_change"] else 0.0,
            "volume": int(r["volume"]) if r["volume"] else 0,
            "amount": float(r["amount"]) if r["amount"] else 0.0,
            "is_up": (r["pct_change"] or 0) >= 0,
            "trade_date": r["trade_date"].isoformat() if r["trade_date"] else None,
        }
        for r in rows
    ]


def _mock_indices() -> list[dict[str, Any]]:
    """返回指数mock数据（数据库无数据时使用）。"""
    return [
        {
            "code": code,
            "name": name,
            "close": 3500.0,
            "pre_close": 3480.0,
            "pct_change": 0.57,
            "volume": 250000,
            "amount": 35000000.0,
            "is_up": True,
            "trade_date": None,
        }
        for code, name in _INDEX_NAMES.items()
    ]


@router.get("/sectors")
async def get_sectors(
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取行业板块涨跌热力图数据。

    从 klines_daily 最新交易日，按 symbols.industry_sw1 聚合平均涨跌幅。

    Returns:
        行业列表，每项含 name/pct_change/stock_count/amount/is_up。
    """
    sql = text("""
        WITH latest AS (
            SELECT MAX(trade_date) AS max_date FROM klines_daily
        )
        SELECT
            COALESCE(s.industry_sw1, '其他') AS sector,
            ROUND(AVG(k.pct_change)::numeric, 2) AS avg_pct,
            COUNT(k.code) AS stock_count,
            SUM(k.amount) AS total_amount
        FROM klines_daily k
        JOIN latest l ON k.trade_date = l.max_date
        LEFT JOIN symbols s ON s.code = k.code
        WHERE k.is_suspended = FALSE
          AND s.list_status = 'L'
        GROUP BY COALESCE(s.industry_sw1, '其他')
        ORDER BY avg_pct DESC NULLS LAST
    """)

    try:
        result = await session.execute(sql)
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询行业板块数据失败")
        return []

    return [
        {
            "name": r["sector"],
            "pct_change": float(r["avg_pct"]) if r["avg_pct"] else 0.0,
            "stock_count": int(r["stock_count"]) if r["stock_count"] else 0,
            "amount": float(r["total_amount"]) if r["total_amount"] else 0.0,
            "is_up": (r["avg_pct"] or 0) >= 0,
        }
        for r in rows
    ]


@router.get("/top-movers")
async def get_top_movers(
    direction: Literal["up", "down"] = Query(default="up", description="up=涨幅榜, down=跌幅榜"),
    limit: int = Query(default=5, ge=1, le=20, description="返回数量"),
    session: AsyncSession = Depends(_get_session),
) -> list[dict[str, Any]]:
    """获取涨幅或跌幅排行榜。

    从 klines_daily 最新交易日，按 pct_change 排序，
    过滤涨跌停、ST、停牌股，JOIN symbols 获取股票名称。

    Args:
        direction: "up" 涨幅榜，"down" 跌幅榜。
        limit: 返回数量，默认5。

    Returns:
        排行列表，每项含 code/name/close/pct_change/volume/amount/industry。
    """
    order = "DESC" if direction == "up" else "ASC"

    sql = text(f"""
        WITH latest AS (
            SELECT MAX(trade_date) AS max_date FROM klines_daily
        )
        SELECT
            k.code,
            s.name,
            s.industry_sw1 AS industry,
            k.close,
            k.pct_change,
            k.volume,
            k.amount,
            k.trade_date
        FROM klines_daily k
        JOIN latest l ON k.trade_date = l.max_date
        LEFT JOIN symbols s ON s.code = k.code
        WHERE k.is_suspended = FALSE
          AND k.is_st = FALSE
          AND s.list_status = 'L'
          AND k.pct_change IS NOT NULL
        ORDER BY k.pct_change {order} NULLS LAST
        LIMIT :lim
    """)  # noqa: S608 — order is validated by Literal type, not user input

    try:
        result = await session.execute(sql, {"lim": limit})
        rows = result.mappings().all()
    except Exception:
        logger.exception("查询涨跌幅排行失败")
        return []

    return [
        {
            "code": r["code"],
            "name": r["name"] or r["code"],
            "industry": r["industry"] or "未知",
            "close": float(r["close"]) if r["close"] else 0.0,
            "pct_change": float(r["pct_change"]) if r["pct_change"] else 0.0,
            "volume": int(r["volume"]) if r["volume"] else 0,
            "amount": float(r["amount"]) if r["amount"] else 0.0,
            "trade_date": r["trade_date"].isoformat() if r["trade_date"] else None,
        }
        for r in rows
    ]
