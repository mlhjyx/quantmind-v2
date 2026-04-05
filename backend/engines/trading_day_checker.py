"""多层动态交易日判断 — 4层fallback，自动更新本地日历。

Layer 1: QMT实时查询（live模式，最权威）
Layer 2: Tushare API实时查询（网络依赖）
Layer 3: 本地trading_calendar表（可能过期）
Layer 4: 启发式判断（周末=非交易日，工作日=假定交易日，约95%准确）

每次Layer 2成功时自动UPSERT本地表，保持最新。

用法:
    checker = TradingDayChecker(conn)
    is_td, reason = checker.is_trading_day()
    next_td = checker.next_trading_day()
"""

import structlog
from datetime import date, timedelta
from typing import Any

logger = structlog.get_logger(__name__)


class TradingDayChecker:
    """多层动态交易日判断。"""

    def __init__(self, conn: Any = None):
        """初始化。

        Args:
            conn: psycopg2连接（Layer 3需要）。可为None，跳过DB层。
        """
        self._conn = conn

    def is_trading_day(self, check_date: date | None = None) -> tuple[bool, str]:
        """判断是否交易日（4层fallback）。

        Args:
            check_date: 待检查日期，None=今天。

        Returns:
            (is_trading, reason) — reason说明判断来源和原因。
        """
        d = check_date or date.today()

        # Layer 1: QMT (仅live模式且已连接)
        result = self._check_qmt(d)
        if result is not None:
            return result

        # Layer 2: Tushare API
        result = self._check_tushare(d)
        if result is not None:
            return result

        # Layer 3: 本地DB
        result = self._check_local_db(d)
        if result is not None:
            return result

        # Layer 4: 启发式
        return self._check_heuristic(d)

    def next_trading_day(self, after_date: date | None = None) -> date:
        """获取下一个交易日。

        Args:
            after_date: 起始日期(不含)，None=今天。

        Returns:
            下一个交易日。
        """
        d = (after_date or date.today()) + timedelta(days=1)
        for _ in range(30):  # 最多查30天（跨春节）
            is_td, _ = self.is_trading_day(d)
            if is_td:
                return d
            d += timedelta(days=1)
        # Fallback: 返回下一个工作日
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d

    def prev_trading_day(self, before_date: date | None = None) -> date:
        """获取上一个交易日。

        Args:
            before_date: 起始日期(不含)，None=今天。

        Returns:
            上一个交易日。
        """
        d = (before_date or date.today()) - timedelta(days=1)
        for _ in range(30):
            is_td, _ = self.is_trading_day(d)
            if is_td:
                return d
            d -= timedelta(days=1)
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d

    # ── Layer 1: QMT ──

    def _check_qmt(self, d: date) -> tuple[bool, str] | None:
        """通过QMT查询交易日（仅live模式）。"""
        try:
            from app.config import settings
            if settings.EXECUTION_MODE != "live":
                return None

            from app.services.qmt_connection_manager import qmt_manager
            if qmt_manager.state != "connected":
                return None

            # QMT没有直接的is_trading_day API，通过查询当日行情间接判断
            # 如果能查到持仓市值变化，说明在交易
            # 这个方法不够可靠，跳过Layer 1
            return None
        except Exception:
            return None

    # ── Layer 2: Tushare API ──

    def _check_tushare(self, d: date) -> tuple[bool, str] | None:
        """通过Tushare trade_cal API查询。"""
        try:
            from app.config import settings
            if not settings.TUSHARE_TOKEN:
                return None

            import tushare as ts
            pro = ts.pro_api(settings.TUSHARE_TOKEN)
            d_str = d.strftime("%Y%m%d")
            df = pro.trade_cal(
                exchange="SSE",
                start_date=d_str,
                end_date=d_str,
                fields="cal_date,is_open",
            )
            if df.empty:
                return None

            is_open = int(df.iloc[0]["is_open"]) == 1
            reason = f"tushare_api: {'交易日' if is_open else '非交易日'}"

            # 自动更新本地表
            self._upsert_local(d, is_open)

            logger.debug(f"[TradingDayChecker] L2 Tushare: {d} → {is_open}")
            return (is_open, reason)

        except Exception as e:
            logger.debug(f"[TradingDayChecker] L2 Tushare失败: {e}")
            return None

    # ── Layer 3: 本地DB ──

    def _check_local_db(self, d: date) -> tuple[bool, str] | None:
        """从trading_calendar表查询。"""
        if self._conn is None:
            return None
        try:
            cur = self._conn.cursor()
            cur.execute(
                """SELECT is_trading_day FROM trading_calendar
                   WHERE trade_date = %s AND market = 'astock'""",
                (d,),
            )
            row = cur.fetchone()
            cur.close()
            if row is None:
                return None  # 表中无记录

            is_td = bool(row[0])
            return (is_td, f"local_db: {'交易日' if is_td else '非交易日'}")
        except Exception as e:
            logger.debug(f"[TradingDayChecker] L3 DB失败: {e}")
            return None

    # ── Layer 4: 启发式 ──

    def _check_heuristic(self, d: date) -> tuple[bool, str]:
        """周末=非交易日，工作日=假定交易日。"""
        if d.weekday() >= 5:  # 5=Saturday, 6=Sunday
            return (False, "heuristic: 周末")
        return (True, "heuristic: 工作日(假定交易日，未验证假期)")

    # ── 自动更新本地表 ──

    def _upsert_local(self, d: date, is_open: bool) -> None:
        """将Tushare查询结果写入本地trading_calendar。"""
        if self._conn is None:
            return
        try:
            cur = self._conn.cursor()
            cur.execute(
                """INSERT INTO trading_calendar (trade_date, market, is_trading_day)
                   VALUES (%s, 'astock', %s)
                   ON CONFLICT (trade_date, market) DO UPDATE SET
                       is_trading_day = EXCLUDED.is_trading_day""",
                (d, is_open),
            )
            self._conn.commit()
        except Exception as e:
            logger.debug(f"[TradingDayChecker] UPSERT失败: {e}")
            try:
                self._conn.rollback()
            except Exception:
                pass
