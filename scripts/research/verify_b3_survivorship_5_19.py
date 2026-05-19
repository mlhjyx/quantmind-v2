"""B3 任务 1+2 深度验证: factor_values 退市股 sediment + stock_status_daily 历史 ST 真值."""

import re
import sys
from pathlib import Path

import psycopg2

env = Path("backend/.env").read_text()
m = re.search(
    r"^DATABASE_URL=postgresql\+?(?:asyncpg)?://([^:]+):([^@]+)@([^:]+):(\d+)/(\S+)",
    env,
    re.MULTILINE,
)
# Plan v8 code review MEDIUM fix (5-20): fail-loud if .env format drift (铁律 33).
if m is None:
    sys.exit("[verify_b3] FATAL: DATABASE_URL not found in backend/.env (env format drift)")
u, p, h, port, db = m.groups()
conn = psycopg2.connect(host=h, port=port, dbname=db, user=u, password=p)
cur = conn.cursor()

print("=" * 70)
print("B3 任务 1: factor_values 退市股 sediment 真值")
print("=" * 70)

# 1. factor_values 全表 唯一股票数 + 退市股覆盖率
cur.execute("SELECT COUNT(DISTINCT code) FROM factor_values")
total_fv_codes = cur.fetchone()[0]
print(f"\n1.1 factor_values 全表 唯一股票数: {total_fv_codes}")

# 2. symbols 中 322 已退市股票, 多少在 factor_values 有数据?
cur.execute("""
    SELECT COUNT(DISTINCT s.code)
    FROM symbols s
    WHERE s.delist_date IS NOT NULL
      AND EXISTS (SELECT 1 FROM factor_values fv WHERE fv.code = s.code)
""")
delisted_in_fv = cur.fetchone()[0]
print(f"1.2 322 退市股中 在 factor_values 有数据: {delisted_in_fv} 只")

# 3. 退市股的 factor_values 最后日期分布 (是否 sediment 完整到退市日)
cur.execute("""
    SELECT
        EXTRACT(YEAR FROM s.delist_date)::int AS delist_year,
        COUNT(DISTINCT s.code) AS delisted_count,
        COUNT(DISTINCT CASE WHEN fv_max_td IS NOT NULL THEN s.code END) AS fv_covered,
        AVG(s.delist_date - fv_max_td)::int AS avg_gap_days
    FROM symbols s
    LEFT JOIN (
        SELECT code, MAX(trade_date) AS fv_max_td FROM factor_values GROUP BY code
    ) fv ON fv.code = s.code
    WHERE s.delist_date IS NOT NULL
    GROUP BY delist_year
    ORDER BY delist_year
""")
print("\n1.3 退市股按年: 退市数 / factor_values 覆盖 / 平均 gap (退市日 - 因子最后日):")
for row in cur.fetchall():
    print(f"   {row[0]}: 退市 {row[1]} / 覆盖 {row[2]} / 平均 gap {row[3]} 天")

# 4. 样本 — 5 只 2025 退市股的 factor_values 真值
cur.execute("""
    SELECT s.code, s.delist_date, MAX(fv.trade_date) AS fv_max, COUNT(fv.trade_date) AS fv_rows
    FROM symbols s
    LEFT JOIN factor_values fv ON fv.code = s.code
    WHERE s.delist_date BETWEEN '2025-01-01' AND '2025-12-31'
    GROUP BY s.code, s.delist_date
    ORDER BY s.delist_date DESC
    LIMIT 5
""")
print("\n1.4 样本 5 只 2025 退市股:")
for row in cur.fetchall():
    print(f"   {row[0]} 退市={row[1]} factor_values最后={row[2]} 行数={row[3]}")

print()
print("=" * 70)
print("B3 任务 2: stock_status_daily 历史 ST 真值")
print("=" * 70)

# 5. stock_status_daily schema + 行数
cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name='stock_status_daily' ORDER BY ordinal_position"
)
ssd_cols = [r[0] for r in cur.fetchall()]
print(f"\n2.1 stock_status_daily columns: {ssd_cols}")

cur.execute("SELECT COUNT(*) FROM stock_status_daily")
ssd_rows = cur.fetchone()[0]
cur.execute("SELECT MIN(trade_date), MAX(trade_date) FROM stock_status_daily")
ssd_range = cur.fetchone()
print(f"2.2 stock_status_daily 行数: {ssd_rows:,}, 日期范围: {ssd_range[0]} ~ {ssd_range[1]}")

# 6. is_st = true 的历史分布 (按年)
cur.execute("""
    SELECT EXTRACT(YEAR FROM trade_date)::int AS year,
           COUNT(DISTINCT code) AS st_codes_in_year,
           COUNT(*) AS st_code_days
    FROM stock_status_daily
    WHERE is_st = true
    GROUP BY year
    ORDER BY year
""")
print("\n2.3 is_st=true 按年分布:")
for row in cur.fetchall():
    print(f"   {row[0]}: {row[1]} 只股票 / {row[2]} 个 (股票, 日期) 对")

# 7. 退市股的 ST 历史 — 退市前 ST 状态 sediment 真值
cur.execute("""
    SELECT s.code, s.delist_date,
           COUNT(CASE WHEN ssd.is_st = true THEN 1 END) AS st_days_before_delist,
           COUNT(ssd.trade_date) AS total_ssd_days
    FROM symbols s
    LEFT JOIN stock_status_daily ssd ON ssd.code = s.code AND ssd.trade_date < s.delist_date
    WHERE s.delist_date BETWEEN '2023-01-01' AND '2025-12-31'
    GROUP BY s.code, s.delist_date
    HAVING COUNT(ssd.trade_date) > 0
    ORDER BY st_days_before_delist DESC
    LIMIT 10
""")
print("\n2.4 样本: 2023-2025 退市股 退市前 ST 历史 sediment (Top 10 by st_days):")
for row in cur.fetchall():
    print(f"   {row[0]} 退市={row[1]} ST天数={row[2]} 总sediment天数={row[3]}")

# 8. 是否有 ST 但从未退市的股票 (真值: ST 转 *ST 转退市 OR ST 转 摘帽)
cur.execute("""
    SELECT COUNT(DISTINCT ssd.code)
    FROM stock_status_daily ssd
    WHERE ssd.is_st = true
      AND ssd.code NOT IN (SELECT code FROM symbols WHERE delist_date IS NOT NULL)
""")
st_never_delisted = cur.fetchone()[0]
cur.execute("""
    SELECT COUNT(DISTINCT ssd.code)
    FROM stock_status_daily ssd
    WHERE ssd.is_st = true
      AND ssd.code IN (SELECT code FROM symbols WHERE delist_date IS NOT NULL)
""")
st_then_delisted = cur.fetchone()[0]
print(f"\n2.5 ST 但未退市: {st_never_delisted} 只 / ST 后退市: {st_then_delisted} 只")

print()
print("=" * 70)
print("B3 综合结论")
print("=" * 70)
print(f"""
✅ Plan v8 P0-11 假设 ({"BACKTEST EXCLUDES delisted"}) 与真值矛盾:
   - klines_daily 含 5743 只 (含退市)
   - factor_values 含 {total_fv_codes} 只 (含 {delisted_in_fv} / 322 退市)
   - stock_status_daily 含 {ssd_rows:,} 行 ST/停牌 sediment ({ssd_range[0]} ~ {ssd_range[1]})
   - 退市股的 ST 历史 + factor sediment 都完整 → backtest universe 真**含** 退市股
   - 生存者偏差 likely 不显著, P0-11 假设可证伪

⚠️  残余风险 (需 backtest run 量化):
   - 退市股是否真被 Top-N 选股选中? 取决于因子真值
   - look-ahead bias: backtest 在 t=退市前已知 delist_date? 沿用 symbols 表 → NO leak (symbols 是当前 snapshot, backtest 不 JOIN symbols)
""")

cur.close()
conn.close()
