-- ============================================================
-- Week 1 数据拉取后验证脚本
-- 执行: psql -d quantmind -f scripts/validate_data.sql
-- ============================================================

\echo '=== 1. 三表总量核查 ==='
SELECT
    'klines_daily' AS table_name,
    COUNT(*) AS total_rows,
    COUNT(DISTINCT code) AS distinct_codes,
    COUNT(DISTINCT trade_date) AS distinct_dates,
    MIN(trade_date) AS min_date,
    MAX(trade_date) AS max_date
FROM klines_daily
UNION ALL
SELECT 'daily_basic', COUNT(*), COUNT(DISTINCT code),
    COUNT(DISTINCT trade_date), MIN(trade_date), MAX(trade_date)
FROM daily_basic
UNION ALL
SELECT 'index_daily', COUNT(*), COUNT(DISTINCT index_code),
    COUNT(DISTINCT trade_date), MIN(trade_date), MAX(trade_date)
FROM index_daily;

-- 预期: klines ~600万行, daily_basic ~600万行, index_daily ~3600行


\echo '=== 2. 缺失交易日（klines_daily） ==='
SELECT tc.trade_date, COALESCE(kd.row_count, 0) AS klines_rows
FROM trading_calendar tc
LEFT JOIN (
    SELECT trade_date, COUNT(*) AS row_count
    FROM klines_daily GROUP BY trade_date
) kd ON tc.trade_date = kd.trade_date
WHERE tc.is_trading_day = TRUE
  AND tc.market = 'astock'
  AND tc.trade_date >= '2020-01-01'
  AND tc.trade_date <= CURRENT_DATE
  AND kd.row_count IS NULL
ORDER BY tc.trade_date;
-- 预期: 0行


\echo '=== 3. 每日股票数量异常（<中位数90%）==='
WITH daily_counts AS (
    SELECT trade_date, COUNT(*) AS row_count
    FROM klines_daily WHERE trade_date >= '2020-01-01'
    GROUP BY trade_date
),
stats AS (
    SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY row_count) AS median_count
    FROM daily_counts
)
SELECT dc.trade_date, dc.row_count, s.median_count,
    ROUND((dc.row_count::NUMERIC / s.median_count * 100)::NUMERIC, 1) AS pct_of_median
FROM daily_counts dc, stats s
WHERE dc.row_count < s.median_count * 0.90
ORDER BY dc.trade_date;
-- 预期: 0行或极少数早期日期


\echo '=== 4. 价格/成交量异常值 ==='
SELECT 'close <= 0' AS check_name, COUNT(*) AS count FROM klines_daily WHERE close <= 0
UNION ALL SELECT 'high < low', COUNT(*) FROM klines_daily WHERE high < low
UNION ALL SELECT 'volume < 0', COUNT(*) FROM klines_daily WHERE volume < 0
UNION ALL SELECT 'adj_factor <= 0', COUNT(*) FROM klines_daily WHERE adj_factor <= 0
UNION ALL SELECT 'adj_factor IS NULL', COUNT(*) FROM klines_daily WHERE adj_factor IS NULL;
-- 预期: 全部为0（adj_factor NULL可能少量）


\echo '=== 5. 极端涨跌幅（>25%） ==='
SELECT code, trade_date, pct_change, close, pre_close
FROM klines_daily
WHERE ABS(pct_change) > 25 AND is_suspended = FALSE
ORDER BY ABS(pct_change) DESC LIMIT 20;
-- 预期: 仅新股/复牌/北交所


\echo '=== 6. VWAP单位验证（茅台） ==='
SELECT code, trade_date, close, volume, amount,
    ROUND(amount / NULLIF(volume, 0), 2) AS vwap_proxy,
    ROUND(close / NULLIF(amount / NULLIF(volume, 0), 0), 3) AS ratio_check
FROM klines_daily
WHERE code = '600519' AND volume > 0
ORDER BY trade_date DESC LIMIT 3;
-- 预期: ratio_check ≈ 0.1 (千元/手 vs 元/股)


\echo '=== 7. daily_basic NULL率（最近一日） ==='
SELECT COUNT(*) AS total,
    SUM(CASE WHEN pe_ttm IS NULL THEN 1 ELSE 0 END) AS null_pe_ttm,
    SUM(CASE WHEN total_mv IS NULL THEN 1 ELSE 0 END) AS null_total_mv,
    SUM(CASE WHEN turnover_rate_f IS NULL THEN 1 ELSE 0 END) AS null_tr_f
FROM daily_basic
WHERE trade_date = (SELECT MAX(trade_date) FROM daily_basic);
-- 预期: null_total_mv=0, null_pe_ttm 3-8%


\echo '=== 8. index_daily覆盖率 ==='
SELECT index_code, COUNT(*) AS rows, MIN(trade_date), MAX(trade_date)
FROM index_daily GROUP BY index_code;
-- 预期: 3个指数各~1200行


\echo '=== 9. 跨表孤立记录 ==='
SELECT COUNT(DISTINCT k.code) AS orphan_codes
FROM klines_daily k LEFT JOIN symbols s ON k.code = s.code
WHERE s.code IS NULL;
-- 预期: 0


\echo '=== 10. 跨表日期范围对齐 ==='
SELECT 'klines_daily' AS tbl, MIN(trade_date), MAX(trade_date) FROM klines_daily
UNION ALL SELECT 'daily_basic', MIN(trade_date), MAX(trade_date) FROM daily_basic
UNION ALL SELECT 'index_daily', MIN(trade_date), MAX(trade_date) FROM index_daily;
-- 预期: 三表min/max基本一致


\echo '=== 11. pct_change单位验证 ==='
SELECT trade_date, close, pre_close, pct_change,
    ROUND((close - pre_close) / pre_close * 100, 4) AS calc_pct,
    ABS(pct_change - ROUND((close - pre_close) / pre_close * 100, 4)) AS diff
FROM klines_daily
WHERE code = '600519' AND pre_close > 0
ORDER BY trade_date DESC LIMIT 5;
-- 预期: diff < 0.01


\echo '=== 12. 停牌标记分布 ==='
SELECT
    COUNT(*) FILTER (WHERE is_suspended = TRUE) AS suspended,
    COUNT(*) FILTER (WHERE is_suspended = FALSE) AS normal,
    ROUND(COUNT(*) FILTER (WHERE is_suspended = TRUE)::NUMERIC / COUNT(*) * 100, 2) AS pct
FROM klines_daily WHERE trade_date >= '2020-01-01';
-- 预期: pct 在 1-3%


\echo '=== 13. klines vs daily_basic 每日对齐检查 ==='
WITH klines_dates AS (
    SELECT trade_date, COUNT(DISTINCT code) AS klines_codes
    FROM klines_daily WHERE trade_date >= '2020-01-01'
    GROUP BY trade_date
),
basic_dates AS (
    SELECT trade_date, COUNT(DISTINCT code) AS basic_codes
    FROM daily_basic WHERE trade_date >= '2020-01-01'
    GROUP BY trade_date
)
SELECT k.trade_date, k.klines_codes, COALESCE(b.basic_codes, 0) AS basic_codes,
    k.klines_codes - COALESCE(b.basic_codes, 0) AS gap
FROM klines_dates k
LEFT JOIN basic_dates b ON k.trade_date = b.trade_date
WHERE ABS(k.klines_codes - COALESCE(b.basic_codes, 0)) > 100
ORDER BY k.trade_date;
-- 预期: 0行（差异>100说明daily_basic拉取有缺口）


\echo '=== 14. 退市股覆盖检查 ==='
SELECT list_status, COUNT(*) AS count
FROM symbols
WHERE market = 'astock'
GROUP BY list_status
ORDER BY list_status;
-- 预期: D（退市）应有数百条，L（在市）约5000+


\echo '=== 15. adj_factor NULL率（按日期，仅显示NULL>50的日期） ==='
SELECT trade_date,
    COUNT(*) AS total,
    SUM(CASE WHEN adj_factor IS NULL THEN 1 ELSE 0 END) AS null_adj,
    ROUND(SUM(CASE WHEN adj_factor IS NULL THEN 1 ELSE 0 END)::NUMERIC / COUNT(*) * 100, 2) AS null_pct
FROM klines_daily
WHERE trade_date >= '2020-01-01'
GROUP BY trade_date
HAVING SUM(CASE WHEN adj_factor IS NULL THEN 1 ELSE 0 END) > 50
ORDER BY trade_date;
-- 预期: 0行


\echo '=== 16. total_mv数量级验证（贵州茅台,应≈2万亿,单位万元则≈2000万） ==='
SELECT code, trade_date, total_mv, circ_mv,
    ROUND(total_mv / 10000, 0) AS total_mv_亿元
FROM daily_basic
WHERE code = '600519'
ORDER BY trade_date DESC LIMIT 3;
-- 预期: total_mv_亿元 ≈ 20000（约2万亿）


\echo '=== 17. adj_factor除权事件检测（最近20次除权） ==='
WITH adj_changes AS (
    SELECT k1.code, k1.trade_date,
        k1.adj_factor AS curr_adj,
        k0.adj_factor AS prev_adj,
        ROUND((k1.adj_factor / NULLIF(k0.adj_factor, 0))::NUMERIC, 6) AS ratio
    FROM klines_daily k1
    JOIN klines_daily k0 ON k1.code = k0.code
        AND k0.trade_date = (
            SELECT MAX(trade_date) FROM klines_daily k2
            WHERE k2.code = k1.code AND k2.trade_date < k1.trade_date
        )
    WHERE k1.trade_date >= '2024-01-01'
      AND ABS(k1.adj_factor / NULLIF(k0.adj_factor, 0) - 1) > 0.01
)
SELECT * FROM adj_changes ORDER BY trade_date DESC LIMIT 20;
-- 预期: ratio接近整数比(如1.05=5%分红, 2.0=10送10)


\echo '=== 验证完成 ==='
