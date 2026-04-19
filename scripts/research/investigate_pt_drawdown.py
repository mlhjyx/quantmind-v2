"""PT 本周回撤根因调查 (Session 10, 2026-04-19).

只读查询, 不改任何数据. 直接用 psycopg2, 不走 backend imports 防 shadow.
DATABASE_URL 从 env / backend/.env 读 (铁律 35 源码不硬编码密码).

用法:
    .venv/Scripts/python.exe scripts/research/investigate_pt_drawdown.py
"""

import os
import warnings
from pathlib import Path

import pandas as pd
import psycopg2

# 压 pandas 对 raw psycopg2 的 UserWarning (pandas >= 2.0 推荐 SQLAlchemy, 对一次性调查脚本不引入)
warnings.filterwarnings("ignore", message="pandas only supports SQLAlchemy")

# 从 backend/.env 或环境读 DATABASE_URL (铁律 35)
_ENV = Path(__file__).resolve().parents[2] / "backend" / ".env"
if _ENV.exists():
    for _line in _ENV.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())

PG = os.environ.get("DATABASE_URL")
if not PG:
    raise RuntimeError(
        "DATABASE_URL not set; backend/.env 也读不到. "
        "source backend/.env 或显式设 DATABASE_URL env var."
    )
# asyncpg URL → psycopg2 格式
if PG.startswith("postgresql+asyncpg://"):
    PG = "postgresql://" + PG[len("postgresql+asyncpg://") :]

STRAT = os.environ.get("PAPER_STRATEGY_ID", "28fc37e5-2d32-4ada-92e0-41c11a5103d0")

conn = psycopg2.connect(PG)
conn.autocommit = True


def section(t: str) -> None:
    print("\n" + "=" * 80)
    print(f"[{t}]")
    print("=" * 80)


# 1. trade_log 本周按日/方向
section("1. trade_log 本周 (4-13~4-18) 按日/方向/模式")
df = pd.read_sql(
    """
    SELECT trade_date, direction, execution_mode, COUNT(*) n,
           SUM(quantity) shares_total,
           ROUND(SUM(quantity * fill_price)::numeric, 0) AS gross,
           ROUND(AVG(slippage_bps)::numeric, 2) AS avg_slip_bps,
           ROUND(SUM(total_cost)::numeric, 0) AS total_cost
    FROM trade_log
    WHERE trade_date BETWEEN '2026-04-13' AND '2026-04-18'
      AND strategy_id = %s
    GROUP BY trade_date, direction, execution_mode
    ORDER BY trade_date, direction
""",
    conn,
    params=(STRAT,),
)
print(df.to_string(index=False) if not df.empty else "(空)")

# 2. performance_series 本周每日 NAV/drawdown
section("2. performance_series 本周 NAV/回撤/turnover")
df = pd.read_sql(
    """
    SELECT trade_date,
           ROUND(nav::numeric, 0) AS nav,
           ROUND(cash::numeric, 0) AS cash,
           ROUND((daily_return*100)::numeric, 3) AS ret_pct,
           ROUND((drawdown*100)::numeric, 3) AS dd_pct,
           ROUND((cash_ratio*100)::numeric, 1) AS cash_ratio_pct,
           position_count pos_n,
           ROUND(turnover::numeric, 0) AS turnover,
           ROUND((excess_return*100)::numeric, 3) AS excess_pct
    FROM performance_series
    WHERE trade_date BETWEEN '2026-04-08' AND '2026-04-18'
      AND strategy_id = %s
    ORDER BY trade_date
""",
    conn,
    params=(STRAT,),
)
print(df.to_string(index=False) if not df.empty else "(空)")

# 3. 买入立即卖出 pattern
section("3. 买入后 <=5天 即卖出 pattern (快进快出)")
df = pd.read_sql(
    """
    WITH buys AS (
        SELECT code, trade_date AS buy_date, quantity AS buy_qty, fill_price AS buy_p
        FROM trade_log
        WHERE trade_date BETWEEN '2026-04-13' AND '2026-04-18'
          AND strategy_id = %s AND direction = 'buy' AND fill_price IS NOT NULL
    ),
    sells AS (
        SELECT code, trade_date AS sell_date, quantity AS sell_qty, fill_price AS sell_p
        FROM trade_log
        WHERE trade_date BETWEEN '2026-04-13' AND '2026-04-22'
          AND strategy_id = %s AND direction = 'sell' AND fill_price IS NOT NULL
    )
    SELECT b.code, b.buy_date, s.sell_date,
           (s.sell_date - b.buy_date) AS hold_days,
           b.buy_qty, ROUND(b.buy_p::numeric, 2) AS buy_p,
           ROUND(s.sell_p::numeric, 2) AS sell_p,
           ROUND(((s.sell_p - b.buy_p) / b.buy_p * 100)::numeric, 2) AS pct_return
    FROM buys b
    JOIN sells s
      ON b.code = s.code
     AND s.sell_date > b.buy_date
     AND s.sell_date <= b.buy_date + 5
    ORDER BY b.buy_date, b.code
""",
    conn,
    params=(STRAT, STRAT),
)
print(df.to_string(index=False) if not df.empty else "(空 - 无快进快出)")

# 4. 本周买入股票的 stock_status 复核 (过滤漏网)
section("4. 本周买入的股票 ST/新股/停牌/BJ 复核 (过滤漏网)")
df = pd.read_sql(
    """
    SELECT t.trade_date, t.code,
           t.direction, t.quantity,
           ROUND(t.fill_price::numeric, 2) AS fill_p,
           ss.is_st, ss.is_suspended, ss.is_new_stock, ss.board,
           s.list_status
    FROM trade_log t
    LEFT JOIN stock_status_daily ss ON t.code = ss.code AND t.trade_date = ss.trade_date
    LEFT JOIN symbols s ON t.code = s.code
    WHERE t.trade_date BETWEEN '2026-04-13' AND '2026-04-18'
      AND t.strategy_id = %s
      AND t.direction = 'buy'
      AND (ss.is_st = true OR ss.is_suspended = true OR ss.is_new_stock = true
           OR ss.board = 'bse' OR t.code LIKE '%%.BJ' OR COALESCE(s.list_status, 'L') != 'L')
    ORDER BY t.trade_date, t.code
""",
    conn,
    params=(STRAT,),
)
print(df.to_string(index=False) if not df.empty else "(空 - 本周无违规买入)")

# 5. signals 本周 target 违规
section("5. signals 本周 target 中 ST/停牌/BJ 检查")
df = pd.read_sql(
    """
    SELECT sig.trade_date, sig.code, sig.action, sig.rank,
           ROUND(sig.target_weight::numeric, 4) AS w,
           ss.is_st, ss.is_suspended, ss.is_new_stock, ss.board
    FROM signals sig
    LEFT JOIN stock_status_daily ss
      ON sig.code = ss.code AND sig.trade_date = ss.trade_date
    WHERE sig.trade_date BETWEEN '2026-04-13' AND '2026-04-18'
      AND sig.strategy_id = %s
      AND sig.execution_mode = 'paper'
      AND (ss.is_st = true OR ss.is_suspended = true OR ss.is_new_stock = true
           OR ss.board = 'bse' OR sig.code LIKE '%%.BJ')
    ORDER BY sig.trade_date, sig.code
""",
    conn,
    params=(STRAT,),
)
print(df.to_string(index=False) if not df.empty else "(空 - 信号层过滤干净)")

# 6. stock_status_daily 本周覆盖率
section("6. stock_status_daily 本周每日记录数 (数据新鲜度)")
df = pd.read_sql(
    """
    SELECT trade_date, COUNT(*) n,
           SUM(CASE WHEN is_st THEN 1 ELSE 0 END) n_st,
           SUM(CASE WHEN is_suspended THEN 1 ELSE 0 END) n_susp,
           SUM(CASE WHEN is_new_stock THEN 1 ELSE 0 END) n_new,
           SUM(CASE WHEN board='bse' THEN 1 ELSE 0 END) n_bse
    FROM stock_status_daily
    WHERE trade_date BETWEEN '2026-04-13' AND '2026-04-18'
    GROUP BY trade_date ORDER BY trade_date
""",
    conn,
)
print(df.to_string(index=False) if not df.empty else "(空)")

# 7. 调仓日 4-14: 卖 + 买
section("7. 4-14 调仓日: 卖 + 买 明细")
df = pd.read_sql(
    """
    SELECT direction, code, quantity,
           ROUND(fill_price::numeric, 2) AS fill_p,
           ROUND((quantity*fill_price)::numeric, 0) AS amt,
           ROUND(slippage_bps::numeric, 2) AS slip_bps,
           reject_reason
    FROM trade_log
    WHERE trade_date = '2026-04-14'
      AND strategy_id = %s
    ORDER BY direction, amt DESC
""",
    conn,
    params=(STRAT,),
)
print(df.to_string(index=False) if not df.empty else "(空)")

# 8. PMS position_monitor (注意: 无 strategy_id 过滤)
section("8. PMS position_monitor 本周触发记录 (全 strategy)")
df = pd.read_sql(
    """
    SELECT entry_date, symbol,
           ROUND(entry_price::numeric, 2) AS entry_p,
           ROUND(peak_price::numeric, 2) AS peak_p,
           ROUND(current_price::numeric, 2) AS cur_p,
           ROUND(unrealized_pnl_pct::numeric, 3) AS pnl_pct,
           ROUND(drawdown_from_peak_pct::numeric, 3) AS dd_pct,
           pms_level_triggered AS lvl,
           trigger_date, status
    FROM position_monitor
    WHERE COALESCE(trigger_date, updated_at::date)
          BETWEEN '2026-04-13' AND '2026-04-18'
       OR (status = 'active' AND updated_at::date >= '2026-04-13')
    ORDER BY trigger_date NULLS LAST, symbol
    LIMIT 50
""",
    conn,
)
print(df.to_string(index=False) if not df.empty else "(空 - PMS 无记录)")

# 9. 总换手 + 成本估算
section("9. 本周总换手 + 理论成本估算 (实际 fill)")
df = pd.read_sql(
    """
    SELECT COUNT(*) n_trades,
           ROUND(SUM(quantity*fill_price)::numeric, 0) AS turnover,
           ROUND(SUM(stamp_tax)::numeric, 0) AS stamp_actual,
           ROUND(SUM(commission)::numeric, 0) AS commission_actual,
           ROUND(SUM(total_cost)::numeric, 0) AS total_cost,
           ROUND(AVG(slippage_bps)::numeric, 2) AS avg_slip_bps,
           ROUND((SUM(total_cost)/SUM(quantity*fill_price)*10000)::numeric, 2) AS cost_bps
    FROM trade_log
    WHERE trade_date BETWEEN '2026-04-13' AND '2026-04-18'
      AND strategy_id = %s
      AND fill_price IS NOT NULL
""",
    conn,
    params=(STRAT,),
)
print(df.to_string(index=False) if not df.empty else "(空)")

# 10. 本周持仓换手率 (position_snapshot delta)
section("10. 本周持仓明细 (position_snapshot) — 多日透视")
df = pd.read_sql(
    """
    SELECT trade_date, COUNT(*) n_pos,
           ROUND(SUM(market_value)::numeric, 0) AS mv_sum,
           ROUND(SUM(unrealized_pnl)::numeric, 0) AS upl_sum,
           ROUND(AVG(holding_days)::numeric, 1) AS avg_hold_days
    FROM position_snapshot
    WHERE trade_date BETWEEN '2026-04-10' AND '2026-04-18'
      AND strategy_id = %s
    GROUP BY trade_date ORDER BY trade_date
""",
    conn,
    params=(STRAT,),
)
print(df.to_string(index=False) if not df.empty else "(空)")

# 11. 各股本周 PnL 贡献 (找出拖累元凶)
section("11. 本周 PnL 贡献分解 (持仓股 unrealized + 已卖出实现)")
df = pd.read_sql(
    """
    SELECT code,
           MIN(trade_date) AS first_date,
           MAX(trade_date) AS last_date,
           MAX(holding_days) AS max_hold,
           ROUND(MIN(unrealized_pnl)::numeric, 0) AS min_upl,
           ROUND(MAX(unrealized_pnl)::numeric, 0) AS max_upl,
           ROUND((MAX(unrealized_pnl) - MIN(unrealized_pnl))::numeric, 0) AS range_upl
    FROM position_snapshot
    WHERE trade_date BETWEEN '2026-04-13' AND '2026-04-18'
      AND strategy_id = %s
    GROUP BY code
    ORDER BY MIN(unrealized_pnl) ASC
    LIMIT 15
""",
    conn,
    params=(STRAT,),
)
print(df.to_string(index=False) if not df.empty else "(空)")

conn.close()
print("\n[DONE]")
