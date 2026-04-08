"""统一实时数据服务 — 前端所有页面的核心数据源。

聚合 QMT持仓 + xtdata实时行情 + 信号目标 → 组合快照。
服务端缓存5秒，多页面同时请求只查QMT/xtdata一次。
"""

from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from app.config import settings
from app.services.qmt_connection_manager import qmt_manager

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Server-side cache
# ---------------------------------------------------------------------------
_cache: dict[str, Any] = {}
_cache_ts: dict[str, float] = {}
PORTFOLIO_TTL = 5  # seconds
MARKET_TTL = 10


def _get_cached(key: str, fetch_fn: Any, ttl: float) -> Any:
    """带TTL的服务端缓存。"""
    now = time.time()
    if key in _cache and now - _cache_ts.get(key, 0) < ttl:
        return _cache[key]
    data = fetch_fn()
    _cache[key] = data
    _cache_ts[key] = now
    return data


# ---------------------------------------------------------------------------
# xtdata helpers (import on demand)
# ---------------------------------------------------------------------------

def _ensure_xtquant_path() -> None:
    """确保xtquant路径在sys.path中。"""
    _xt = Path(__file__).resolve().parent.parent.parent.parent / ".venv" / "Lib" / "site-packages" / "Lib" / "site-packages"
    if _xt.exists() and str(_xt) not in sys.path:
        sys.path.append(str(_xt))


def _to_qmt_code(code: str) -> str:
    """6位代码 → QMT格式(带交易所后缀)。"""
    if "." in code:
        return code
    if code.startswith("920"):
        return f"{code}.BJ"
    if code.startswith("6"):
        return f"{code}.SH"
    if code.startswith(("0", "3")):
        return f"{code}.SZ"
    if code.startswith(("4", "8")):
        return f"{code}.BJ"
    return f"{code}.SZ"


def _from_qmt_code(qmt_code: str) -> str:
    """QMT格式 → DB代码（统一后均为带后缀格式，直接返回）。"""
    return qmt_code


def _get_realtime_ticks(codes: list[str]) -> dict[str, dict[str, Any]]:
    """批量获取实时行情。返回 {6位code: tick_dict}。"""
    if not codes:
        return {}
    _ensure_xtquant_path()
    try:
        from xtquant import xtdata
        qmt_codes = [_to_qmt_code(c) for c in codes]
        ticks = xtdata.get_full_tick(qmt_codes)
        if not isinstance(ticks, dict):
            return {}
        result: dict[str, dict[str, Any]] = {}
        for qmt_code, tick in ticks.items():
            if tick and isinstance(tick, dict):
                result[_from_qmt_code(qmt_code)] = tick
        return result
    except Exception:
        logger.debug("xtdata获取行情失败，将使用fallback")
        return {}


def _is_market_open() -> bool:
    """判断当前是否在交易时段。"""
    now = datetime.now()
    if now.weekday() >= 5:  # 周末
        return False
    t = now.hour * 100 + now.minute
    return 915 <= t <= 1505


# ---------------------------------------------------------------------------
# RealtimeDataService
# ---------------------------------------------------------------------------

class RealtimeDataService:
    """统一实时数据服务。"""

    def __init__(self, conn: Any = None) -> None:
        """初始化。

        Args:
            conn: psycopg2同步连接（用于DB查询）。
        """
        self._conn = conn

    def get_portfolio_snapshot(self) -> dict[str, Any]:
        """获取当前完整组合快照（缓存5秒）。"""
        return _get_cached("portfolio", self._build_portfolio_snapshot, PORTFOLIO_TTL)

    def get_market_overview(self) -> dict[str, Any]:
        """获取市场概览（缓存10秒）。"""
        return _get_cached("market", self._build_market_overview, MARKET_TTL)

    # ------------------------------------------------------------------
    # Portfolio snapshot builder
    # ------------------------------------------------------------------

    def _build_portfolio_snapshot(self) -> dict[str, Any]:
        """构建组合快照。"""
        is_connected = qmt_manager.state == "connected" and qmt_manager.broker is not None

        # 1. QMT持仓
        qmt_positions = self._get_qmt_positions()

        # 2. 实时行情
        all_codes = list(qmt_positions.keys())
        signal_targets = self._get_signal_targets()
        # 加上信号中有但持仓没有的股票
        for code in signal_targets:
            if code not in all_codes:
                all_codes.append(code)
        realtime_prices = _get_realtime_ticks(all_codes) if _is_market_open() or is_connected else {}

        # 3. 股票名称和行业
        names = self._get_stock_names(all_codes)
        industries = self._get_industries(all_codes)

        # 4. 账户资金
        asset = self._get_qmt_asset()

        # 5. 构建持仓明细
        positions: list[dict[str, Any]] = []
        total_market_value = 0.0
        total_cost = 0.0
        total_daily_pnl = 0.0

        for code, pos in qmt_positions.items():
            tick = realtime_prices.get(code, {})
            cost_price = pos.get("avg_price", 0)
            shares = pos.get("volume", 0)
            available = pos.get("can_use_volume", shares)

            last_price = tick.get("lastPrice", 0)
            if last_price <= 0:
                last_price = cost_price  # fallback
            prev_close = tick.get("lastClose", last_price)

            market_value = last_price * shares
            cost_value = cost_price * shares
            pnl = market_value - cost_value
            pnl_pct = (pnl / cost_value * 100) if cost_value > 0 else 0
            daily_change = last_price - prev_close
            daily_return = (daily_change / prev_close * 100) if prev_close > 0 else 0

            signal = signal_targets.get(code, {})
            target_shares = signal.get("target_shares", 0)
            if target_shares > 0:
                drift_pct = (shares - target_shares) / target_shares * 100
            elif shares > 0:
                drift_pct = 100.0
            else:
                drift_pct = 0.0

            if shares == 0 and target_shares > 0:
                drift_status = "missing"
            elif abs(drift_pct) > 30:
                drift_status = "overweight" if drift_pct > 0 else "underweight"
            else:
                drift_status = "normal"

            positions.append({
                "code": code,
                "name": names.get(code, code),
                "shares": shares,
                "available": available,
                "cost_price": round(cost_price, 3),
                "last_price": round(last_price, 3),
                "prev_close": round(prev_close, 3),
                "market_value": round(market_value, 0),
                "pnl": round(pnl, 0),
                "pnl_pct": round(pnl_pct, 2),
                "daily_return": round(daily_return, 2),
                "weight": 0,  # filled after totals
                "target_shares": target_shares,
                "drift_pct": round(drift_pct, 1),
                "drift_status": drift_status,
                "industry": industries.get(code, ""),
            })

            total_market_value += market_value
            total_cost += cost_value
            total_daily_pnl += daily_change * shares

        # Fill weight
        for p in positions:
            if total_market_value > 0:
                p["weight"] = round(p["market_value"] / total_market_value * 100, 2)

        # Sort by |pnl| descending
        positions.sort(key=lambda x: abs(x["pnl"]), reverse=True)

        # 6. 缺失股票
        missing: list[dict[str, Any]] = []
        for code, signal in signal_targets.items():
            if code not in qmt_positions:
                tick = realtime_prices.get(code, {})
                est_price = tick.get("lastPrice", 0)
                target_shares = signal.get("target_shares", 0)
                missing.append({
                    "code": code,
                    "name": names.get(code, code),
                    "target_shares": target_shares,
                    "estimated_cost": round(target_shares * est_price, 0) if est_price > 0 else 0,
                    "drift_status": "missing",
                })

        # 7. 行业分布
        industry_alloc: dict[str, float] = {}
        for p in positions:
            ind = p["industry"] or "未知"
            industry_alloc[ind] = industry_alloc.get(ind, 0) + p["weight"]

        total_pnl = total_market_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        available_cash = asset.get("cash", 0)
        total_asset = asset.get("total_asset", total_market_value + available_cash)

        return {
            "timestamp": datetime.now().isoformat(),
            "qmt_connected": is_connected,
            "data_source": "qmt" if is_connected else "db_fallback",
            "is_market_open": _is_market_open(),
            "account": {
                "total_asset": round(total_asset, 0),
                "market_value": round(total_market_value, 0),
                "available_cash": round(available_cash, 0),
                "frozen_cash": round(asset.get("frozen_cash", 0), 0),
                "total_pnl": round(total_pnl, 0),
                "total_pnl_pct": round(total_pnl_pct, 2),
                "daily_pnl": round(total_daily_pnl, 0),
            },
            "positions": positions,
            "missing": missing,
            "summary": {
                "total_stocks": len(positions),
                "target_stocks": len(signal_targets),
                "overweight_count": sum(1 for p in positions if p["drift_status"] == "overweight"),
                "missing_count": len(missing),
                "max_single_weight": round(max((p["weight"] for p in positions), default=0), 2),
            },
            "industry_allocation": industry_alloc,
        }

    # ------------------------------------------------------------------
    # Market overview builder
    # ------------------------------------------------------------------

    def _build_market_overview(self) -> dict[str, Any]:
        """构建市场概览。"""
        indices = {
            "000300.SH": "沪深300",
            "000001.SH": "上证指数",
            "399006.SZ": "创业板指",
        }
        market_open = _is_market_open()

        # 尝试xtdata实时数据
        _ensure_xtquant_path()
        result_indices: dict[str, dict[str, Any]] = {}
        try:
            from xtquant import xtdata
            qmt_codes = list(indices.keys())
            ticks = xtdata.get_full_tick(qmt_codes)
            if isinstance(ticks, dict):
                for qmt_code, name in indices.items():
                    tick = ticks.get(qmt_code) if ticks else None
                    if tick and isinstance(tick, dict) and tick.get("lastPrice", 0) > 0:
                        last_price = tick["lastPrice"]
                        prev_close = tick.get("lastClose", last_price)
                        change_pct = (last_price - prev_close) / prev_close * 100 if prev_close > 0 else 0
                        result_indices[qmt_code] = {
                            "name": name,
                            "price": round(last_price, 2),
                            "prev_close": round(prev_close, 2),
                            "change_pct": round(change_pct, 2),
                            "amount": tick.get("amount", 0),
                        }
        except Exception:
            logger.debug("xtdata获取指数行情失败")

        # DB fallback for missing indices
        if len(result_indices) < len(indices) and self._conn:
            try:
                cur = self._conn.cursor()
                missing_codes = [c for c in indices if c not in result_indices]
                placeholders = ",".join(["%s"] * len(missing_codes))
                cur.execute(
                    f"""SELECT ts_code, close, pre_close, amount
                        FROM index_daily
                        WHERE ts_code IN ({placeholders})
                          AND trade_date = (SELECT MAX(trade_date) FROM index_daily WHERE ts_code = %s)""",
                    [*missing_codes, missing_codes[0]],
                )
                for row in cur.fetchall():
                    ts_code = row[0]
                    close = float(row[1]) if row[1] else 0
                    pre_close = float(row[2]) if row[2] else close
                    change_pct = (close - pre_close) / pre_close * 100 if pre_close > 0 else 0
                    result_indices[ts_code] = {
                        "name": indices.get(ts_code, ts_code),
                        "price": round(close, 2),
                        "prev_close": round(pre_close, 2),
                        "change_pct": round(change_pct, 2),
                        "amount": float(row[3]) if row[3] else 0,
                    }
            except Exception:
                logger.debug("DB获取指数数据失败")

        return {
            "timestamp": datetime.now().isoformat(),
            "is_market_open": market_open,
            "indices": result_indices,
        }

    # ------------------------------------------------------------------
    # Data fetchers
    # ------------------------------------------------------------------

    def _get_qmt_positions(self) -> dict[str, dict[str, Any]]:
        """QMT持仓，fallback到DB。返回 {6位代码: {...}}。"""
        if qmt_manager.state == "connected" and qmt_manager.broker is not None:
            try:
                raw = qmt_manager.broker.query_positions()
                return {
                    _from_qmt_code(p["stock_code"]): {
                        "volume": p["volume"],
                        "can_use_volume": p["can_use_volume"],
                        "avg_price": p["avg_price"],
                        "market_value": p["market_value"],
                    }
                    for p in raw
                }
            except Exception:
                logger.warning("QMT持仓查询失败，回退DB")

        return self._read_db_positions()

    def _read_db_positions(self) -> dict[str, dict[str, Any]]:
        """从DB读取最新持仓快照。"""
        if not self._conn:
            return {}
        try:
            cur = self._conn.cursor()
            cur.execute("""
                SELECT code, quantity, avg_cost, market_value
                FROM position_snapshot
                WHERE execution_mode = 'live' AND quantity > 0
                  AND trade_date = (
                    SELECT MAX(trade_date) FROM position_snapshot
                    WHERE execution_mode = 'live' AND quantity > 0
                  )
            """)
            result: dict[str, dict[str, Any]] = {}
            for row in cur.fetchall():
                result[row[0]] = {
                    "volume": int(row[1]),
                    "can_use_volume": int(row[1]),
                    "avg_price": float(row[2]) if row[2] else 0,
                    "market_value": float(row[3]) if row[3] else 0,
                }
            return result
        except Exception:
            logger.warning("DB持仓查询失败")
            return {}

    def _get_qmt_asset(self) -> dict[str, float]:
        """QMT账户资产，fallback到DB。"""
        if qmt_manager.state == "connected" and qmt_manager.broker is not None:
            try:
                asset = qmt_manager.broker.query_asset()
                return {
                    "total_asset": float(asset.get("total_asset", 0)),
                    "cash": float(asset.get("cash", 0)),
                    "frozen_cash": float(asset.get("frozen_cash", 0)),
                    "market_value": float(asset.get("market_value", 0)),
                }
            except Exception:
                logger.warning("QMT资产查询失败，回退DB")

        if self._conn:
            try:
                cur = self._conn.cursor()
                cur.execute("""
                    SELECT nav, cash_ratio FROM performance_series
                    WHERE execution_mode = 'live'
                    ORDER BY trade_date DESC LIMIT 1
                """)
                row = cur.fetchone()
                if row:
                    nav = float(row[0]) if row[0] else 0
                    cash_ratio = float(row[1]) if row[1] else 0
                    return {
                        "total_asset": nav,
                        "cash": nav * cash_ratio,
                        "frozen_cash": 0,
                        "market_value": nav * (1 - cash_ratio),
                    }
            except Exception:
                pass
        return {"total_asset": 0, "cash": 0, "frozen_cash": 0, "market_value": 0}

    def _get_signal_targets(self) -> dict[str, dict[str, Any]]:
        """最新信号目标。"""
        if not self._conn:
            return {}
        try:
            sid = settings.PAPER_STRATEGY_ID
            if not sid:
                return {}
            cur = self._conn.cursor()
            cur.execute("""
                SELECT code, target_weight
                FROM signals
                WHERE strategy_id = %s AND execution_mode = 'live'
                  AND trade_date = (
                    SELECT MAX(trade_date) FROM signals
                    WHERE strategy_id = %s AND execution_mode = 'live'
                  )
            """, (sid, sid))

            # 计算target_shares需要总资产
            asset = self._get_qmt_asset()
            total = asset.get("total_asset", 0)

            result: dict[str, dict[str, Any]] = {}
            for row in cur.fetchall():
                code = row[0]
                weight = float(row[1]) if row[1] else 0
                # 估算目标股数（需要实时价格，这里先用权重×总资产/估计价格）
                target_value = weight * total
                result[code] = {
                    "target_weight": weight,
                    "target_value": target_value,
                    "target_shares": 0,  # 需要价格才能算，由调用方填充
                }
            return result
        except Exception:
            logger.debug("信号目标查询失败")
            return {}

    def _get_stock_names(self, codes: list[str]) -> dict[str, str]:
        """批量查询股票名称。"""
        if not self._conn or not codes:
            logger.debug("_get_stock_names跳过", has_conn=self._conn is not None, codes_count=len(codes))
            return {}
        try:
            cur = self._conn.cursor()
            placeholders = ",".join(["%s"] * len(codes))
            cur.execute(
                f"SELECT code, name FROM symbols WHERE code IN ({placeholders})",
                codes,
            )
            result = {row[0]: row[1] for row in cur.fetchall()}
            logger.debug("_get_stock_names OK", found=len(result), total=len(codes))
            return result
        except Exception as e:
            logger.warning("_get_stock_names失败", error=str(e))
            return {}

    def _get_industries(self, codes: list[str]) -> dict[str, str]:
        """批量查询行业。"""
        if not self._conn or not codes:
            return {}
        try:
            cur = self._conn.cursor()
            placeholders = ",".join(["%s"] * len(codes))
            cur.execute(
                f"SELECT code, industry_sw1 FROM symbols WHERE code IN ({placeholders})",
                codes,
            )
            return {row[0]: (row[1] or "") for row in cur.fetchall()}
        except Exception:
            return {}
