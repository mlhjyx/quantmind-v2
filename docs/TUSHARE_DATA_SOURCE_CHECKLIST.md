# Tushare Pro 数据源 Checklist

> **原则**: 不靠猜测做技术判断。任何数据源接入前先完整阅读官方文档确认数据格式、字段含义、使用限制。
> **教训**: V1的复权因子(adj_factor)事故 + HashMap非确定性事故均源于未读文档。
> **适用**: QuantMind V2 Phase 0 全部Tushare接口接入。
> **积分**: 8000（已开通）
> **官方文档**: https://tushare.pro/document/2

---

## 一、接口总览与优先级

| 优先级 | 接口 | 积分 | DB目标表 | Phase | 用途 |
|--------|------|------|----------|-------|------|
| P0 | stock_basic | 120 | symbols | 0 | 股票列表/上市日期/行业 |
| P0 | trade_cal | 120 | trading_calendar | 0 | 交易日历 |
| P0 | daily | 120 | klines_daily | 0 | 日线OHLCV（未复权） |
| P0 | adj_factor | 120 | adj_factors | 0 | 复权因子 |
| P0 | daily_basic | 2000 | daily_basic | 0 | 每日指标(PE/PB/换手率/市值) |
| P1 | fina_indicator | 2000 | fina_indicator | 0 | 财务指标(ROE/ROA/毛利率) |
| P1 | moneyflow | 2000 | moneyflow_daily | 0 | 个股资金流向 |
| P1 | income | 3000 | income_statement | 1 | 利润表 |
| P1 | balancesheet | 3000 | balance_sheet | 1 | 资产负债表 |
| P1 | cashflow | 3000 | cash_flow | 1 | 现金流量表 |
| P2 | forecast | 5000 | earnings_forecast | 1 | 业绩预告 |
| P2 | share_float | 5000 | share_float | 1 | 限售解禁 |
| P2 | stk_holdernumber | 5000 | holder_number | 1 | 股东人数 |
| P3 | index_daily | 2000 | index_klines | 0 | 指数行情(基准) |

---

## 二、逐接口字段定义与单位

### 2.1 stock_basic — 股票列表

**文档**: https://tushare.pro/document/2?doc_id=25
**积分**: 120 | **频次**: 500次/分钟 | **单次上限**: 5000条

| 字段 | 类型 | 单位/格式 | 说明 | DB映射 |
|------|------|-----------|------|--------|
| ts_code | str | 000001.SZ | Tushare代码（含交易所后缀） | code（需去后缀）或保留全称 |
| symbol | str | 000001 | 纯数字代码 | code |
| name | str | 平安银行 | 股票名称 | name |
| area | str | 深圳 | 地区 | area |
| industry | str | 银行 | 所属行业 | industry |
| market | str | 主板 | 市场类型 | market_type |
| list_date | str | YYYYMMDD | 上市日期 | list_date |
| list_status | str | L/D/P | L=上市 D=退市 P=暂停 | status |
| exchange | str | SSE/SZSE | 交易所 | exchange |
| delist_date | str | YYYYMMDD | 退市日期（可能为空） | delist_date |
| is_hs | str | N/H/S | 是否沪深港通：N否 H沪 S深 | is_hs |

**⚠️ 已知坑**:
1. `ts_code`格式为`000001.SZ`，code转换时注意交易所后缀。SH=上交所 SZ=深交所
2. `list_date`格式为YYYYMMDD纯数字字符串，非YYYY-MM-DD，入库时需转换
3. 需定期拉取更新——新股上市/退市/改名/ST变更 不会自动推送
4. `name`字段包含ST/\*ST前缀，用于过滤风险股
5. 科创板(688开头)、创业板(300开头)涨跌停20%，主板10%——需在交易规则中区分

**验证SQL**:
```sql
-- 拉取后验证
SELECT COUNT(*) FROM symbols WHERE market = 'a_share';  -- 预期 ~5300
SELECT COUNT(*) FROM symbols WHERE list_status = 'L' AND market = 'a_share';  -- 预期 ~5100
SELECT COUNT(*) FROM symbols WHERE name LIKE '%ST%';  -- 预期 ~100-200
SELECT COUNT(*) FROM symbols WHERE list_date IS NULL;  -- 应为0
-- 交易所分布
SELECT exchange, COUNT(*) FROM symbols WHERE list_status = 'L' GROUP BY exchange;
-- SSE ~1800, SZSE ~2700 (近似)
```

---

### 2.2 trade_cal — 交易日历

**文档**: https://tushare.pro/document/2?doc_id=26
**积分**: 120 | **频次**: 500次/分钟

| 字段 | 类型 | 单位/格式 | 说明 |
|------|------|-----------|------|
| exchange | str | SSE | 交易所（默认上交所） |
| cal_date | str | YYYYMMDD | 日历日期 |
| is_open | int | 0/1 | 0=休市 1=开市 |
| pretrade_date | str | YYYYMMDD | 上一交易日 |

**⚠️ 已知坑**:
1. 默认返回上交所(SSE)日历。A股沪深两市交易日完全一致，拉SSE即可
2. `is_open=0`包含周末和法定假日
3. 中国春节/国庆长假会连休7-9天——回测中连续非交易日跨度最长可达9天
4. `pretrade_date`可直接用于T+1卖出日期计算

**验证SQL**:
```sql
SELECT COUNT(*) FROM trading_calendar WHERE is_trading = TRUE 
  AND date BETWEEN '2020-01-01' AND '2024-12-31';  -- 预期 ~1220 (每年约244个交易日)
-- 确认无缺失
SELECT EXTRACT(YEAR FROM date) AS yr, COUNT(*) FROM trading_calendar 
  WHERE is_trading = TRUE GROUP BY yr ORDER BY yr;
-- 每年应在240-250之间
```

---

### 2.3 daily — 日线行情 ⭐最重要

**文档**: https://tushare.pro/document/2?doc_id=27
**积分**: 120 | **频次**: 500次/分钟 | **单次上限**: 6000条
**⚡ 关键**: 本接口是**未复权**行情，停牌期间不提供数据

| 字段 | 类型 | 单位 | 说明 | DB映射 |
|------|------|------|------|--------|
| ts_code | str | — | 股票代码 | symbol_id (FK) |
| trade_date | str | YYYYMMDD | 交易日期 | date |
| open | float | **元** | 开盘价（未复权） | open |
| high | float | **元** | 最高价（未复权） | high |
| low | float | **元** | 最低价（未复权） | low |
| close | float | **元** | 收盘价（未复权） | close |
| pre_close | float | **元** | 昨收价（未复权） | pre_close |
| change | float | **元** | 涨跌额 | change |
| pct_chg | float | **%** | 涨跌幅（注意：已乘100，如5.06表示5.06%） | pct_change |
| vol | float | **手** | 成交量（⚠️ 1手=100股） | volume |
| amount | float | **千元** | 成交额（⚠️ 千元不是元） | amount |

**⚠️ 已知坑（按严重程度排序）**:

1. **🔴 vol单位是"手"不是"股"** — 1手=100股。如果因子计算中直接用vol做amihud_illiquidity = |return| / vol，需要意识到这里vol是手。如果要转成股需×100。**但如果只做截面排序(cs_rank)不受影响**
2. **🔴 amount单位是"千元"不是"元"** — 如果要计算VWAP = amount / vol，结果单位是 千元/手 = 10元/股，需要转换。**建议入库时统一转元: amount_yuan = amount × 1000**
3. **🔴 价格是未复权的** — 直接用close计算多日收益率会在除权日产生跳变。必须配合adj_factor做前复权: adj_close = close × adj_factor / latest_adj_factor
4. **🟡 pct_chg已经是百分比** — 5.06表示涨5.06%，不是0.0506。如果因子用pct_chg做收益率，需除以100
5. **🟡 停牌日无数据** — 不是close=pre_close，而是整条记录不存在。回测中遇到停牌需要特殊处理（跳过交易/延后执行）
6. **🟡 新股首日** — 无pre_close（或pre_close=发行价），pct_chg=44%（涨停板）。新股上市60个交易日内应排除出选股池

**验证SQL**:
```sql
-- 总量
SELECT COUNT(*), MIN(date), MAX(date), COUNT(DISTINCT symbol_id) FROM klines_daily;
-- 预期: ~600万+行, 日期从2015起, ~5000只股票

-- 价格异常
SELECT COUNT(*) FROM klines_daily WHERE close <= 0 OR open <= 0;  -- 应为0
SELECT COUNT(*) FROM klines_daily WHERE high < low;  -- 应为0

-- 单位验证（抽样比对Tushare官网）
-- 取一只已知股票某日数据，与Tushare数据工具对比
SELECT date, open, close, volume, amount FROM klines_daily 
  WHERE symbol_id = (SELECT id FROM symbols WHERE code = '000001') 
  AND date = '2024-01-02';
-- volume应为"手"数量级(几十万~几百万手), amount应为"千元"数量级

-- 停牌检测
SELECT COUNT(*) FROM klines_daily WHERE volume = 0;  -- 少量正常（集合竞价失败等极端情况）

-- 每日股票数量（检测数据完整性）
SELECT date, COUNT(*) AS cnt FROM klines_daily 
  GROUP BY date ORDER BY cnt ASC LIMIT 10;
-- 最少应>3000（早期），近期应>5000
```

---

### 2.4 adj_factor — 复权因子 ⭐关键

**文档**: https://tushare.pro/document/2?doc_id=28
**积分**: 120 | **频次**: 500次/分钟

| 字段 | 类型 | 单位 | 说明 |
|------|------|------|------|
| ts_code | str | — | 股票代码 |
| trade_date | str | YYYYMMDD | 交易日期 |
| adj_factor | float | 无量纲 | 复权因子 |

**前复权公式**: `adj_close = close × (adj_factor / latest_adj_factor)`

其中 `latest_adj_factor` 是该股票最新交易日的adj_factor值。

**⚠️ 已知坑（V1血的教训）**:

1. **🔴 adj_factor是累积因子，不是每日比率** — 除权日adj_factor会跳变（如10送10，adj_factor翻倍），非除权日adj_factor不变
2. **🔴 前复权 vs 后复权** — 前复权使当前价格不变、历史价格调低；后复权使IPO价格不变、当前价格调高。**QuantMind用前复权（行业标准）**
3. **🔴 每次拉取新数据后必须用最新adj_factor重新计算全部历史adj_close** — 因为latest_adj_factor变了，所有历史的adj_close都要重算。这是V1事故根源：用了缓存的旧latest_adj_factor
4. **🟡 新股首日adj_factor=1.0** — 从未除权的股票adj_factor始终=1.0
5. **🟡 与daily数据必须日期对齐** — 停牌日daily无数据，adj_factor也可能无数据（需确认）

**验证SQL**:
```sql
-- adj_factor范围检查
SELECT MIN(adj_factor), MAX(adj_factor), AVG(adj_factor) FROM adj_factors;
-- MIN应>0, MAX可能很大（老股多次送转可达100+）

-- 除权事件检测（adj_factor跳变的日期）
SELECT a.symbol_id, a.date, a.adj_factor, b.adj_factor AS prev_adj,
       a.adj_factor / b.adj_factor AS ratio
FROM adj_factors a 
JOIN adj_factors b ON a.symbol_id = b.symbol_id
JOIN trading_calendar tc ON b.date = tc.pretrade_date AND a.date = tc.date
WHERE ABS(a.adj_factor / b.adj_factor - 1) > 0.01
ORDER BY a.date DESC LIMIT 20;
-- ratio应为整数比（如2.0=10送10, 1.5=10送5）

-- 覆盖率
SELECT COUNT(DISTINCT symbol_id) FROM adj_factors;
-- 应与klines_daily的symbol_id数量一致
```

---

### 2.5 daily_basic — 每日指标 ⭐因子核心

**文档**: https://tushare.pro/document/2?doc_id=32
**积分**: 2000 | **频次**: 200次/分钟(2000积分), 500次/分钟(8000积分) | **单次上限**: 6000条

| 字段 | 类型 | 单位 | 说明 | 因子用途 |
|------|------|------|------|----------|
| ts_code | str | — | 股票代码 | — |
| trade_date | str | YYYYMMDD | 交易日期 | — |
| close | float | 元 | 当日收盘价 | 参考 |
| turnover_rate | float | **%** | 换手率（总股本） | 换手率因子 |
| turnover_rate_f | float | **%** | 换手率（自由流通股本） | ⭐推荐用这个 |
| volume_ratio | float | 倍 | 量比 | 量比因子 |
| pe | float | 倍 | 市盈率（总市值/净利润，静态） | — |
| pe_ttm | float | 倍 | 市盈率（TTM，滚动12个月） | ⭐PE因子 |
| pb | float | 倍 | 市净率（总市值/净资产） | ⭐PB因子 |
| ps | float | 倍 | 市销率（静态） | — |
| ps_ttm | float | 倍 | 市销率（TTM） | ⭐PS因子 |
| dv_ratio | float | **%** | 股息率（静态） | 股息因子 |
| dv_ttm | float | **%** | 股息率（TTM） | ⭐股息因子 |
| total_share | float | **万股** | 总股本 | — |
| float_share | float | **万股** | 流通股本 | — |
| free_share | float | **万股** | 自由流通股本 | — |
| total_mv | float | **万元** | 总市值 | ⭐市值因子 |
| circ_mv | float | **万元** | 流通市值 | ⭐流通市值因子 |

**⚠️ 已知坑**:

1. **🔴 total_mv和circ_mv单位是"万元"** — 如果因子计算中要用市值做分母（如 amount / total_mv），必须统一单位。建议入库时转元: `total_mv_yuan = total_mv × 10000`，或者因子计算时明确标注
2. **🔴 turnover_rate vs turnover_rate_f** — 两个换手率含义不同。`turnover_rate`基于总股本，`turnover_rate_f`基于自由流通股本。量化研究通常用`turnover_rate_f`（排除了大股东锁定股）。**代码中必须明确用哪个，不能混用**
3. **🔴 pe_ttm可以是负数** — 亏损公司pe_ttm<0，不能直接取倒数。因子计算需处理负值（如取绝对值rank或winsorize）
4. **🟡 pe_ttm是滚动12个月(TTM)** — 使用最近4个季度的净利润，非最新单季度。这是正确的做法
5. **🟡 NaN值** — 新股上市初期/刚公布财报前，某些字段可能为NaN。入库时保留NaN，因子计算时过滤
6. **🟡 total_share单位是"万股"** — 不是"股"也不是"亿股"

**验证SQL**:
```sql
-- 单位验证（抽样）
SELECT date, close, turnover_rate, turnover_rate_f, pe_ttm, pb, 
       total_mv, circ_mv, total_share
FROM daily_basic 
WHERE symbol_id = (SELECT id FROM symbols WHERE code = '600519')  -- 贵州茅台
AND date = '2024-01-02';
-- total_mv应为~2万亿元 → 单位万元 → 值应~20000000 (2千万个万元=2万亿)
-- pe_ttm应为~30倍
-- turnover_rate应为~0.1-0.5%

-- 负PE检查
SELECT COUNT(*) FROM daily_basic WHERE pe_ttm < 0;  -- 有值正常（亏损公司）

-- NaN比例
SELECT date, 
  COUNT(*) AS total,
  SUM(CASE WHEN pe_ttm IS NULL THEN 1 ELSE 0 END) AS null_pe,
  SUM(CASE WHEN total_mv IS NULL THEN 1 ELSE 0 END) AS null_mv
FROM daily_basic 
WHERE date = '2024-06-28'
GROUP BY date;
-- null_mv应接近0, null_pe可能有几百只（亏损或新股）

-- 换手率范围
SELECT MIN(turnover_rate_f), MAX(turnover_rate_f), AVG(turnover_rate_f) 
FROM daily_basic WHERE date = '2024-06-28';
-- MIN接近0, MAX可能50%+（首日/妖股），AVG约2-5%
```

---

### 2.6 fina_indicator — 财务指标

**文档**: https://tushare.pro/document/2?doc_id=79
**积分**: 2000 | **频次**: 200次/分钟 | **单次上限**: 6000条

| 字段 | 类型 | 单位 | 说明 | 因子用途 |
|------|------|------|------|----------|
| ts_code | str | — | 股票代码 | — |
| ann_date | str | YYYYMMDD | 公告日期 | ⭐用这个做时间对齐（避免未来信息） |
| end_date | str | YYYYMMDD | 报告期（如20240331） | 标识季度 |
| roe | float | **%** | 净资产收益率 | ⭐ROE因子 |
| roe_dt | float | **%** | 净资产收益率（扣除非经常损益） | ⭐更真实的ROE |
| roa | float | **%** | 总资产报酬率 | ROA因子 |
| grossprofit_margin | float | **%** | 毛利率 | 毛利率因子 |
| netprofit_margin | float | **%** | 净利率 | 净利率因子 |
| debt_to_assets | float | **%** | 资产负债率 | 杠杆因子 |
| current_ratio | float | 倍 | 流动比率 | 流动性因子 |
| quick_ratio | float | 倍 | 速动比率 | 流动性因子 |
| or_yoy | float | **%** | 营收同比增长率 | ⭐成长因子 |
| netprofit_yoy | float | **%** | 净利润同比增长率 | ⭐成长因子 |
| basic_eps_yoy | float | **%** | 基本每股收益同比 | EPS成长因子 |
| op_yoy | float | **%** | 营业利润同比 | 成长因子 |

**⚠️ 已知坑**:

1. **🔴🔴🔴 必须用ann_date不是end_date做时间对齐** — end_date是报告期（如20240331=一季报），但公司可能在20240425才公告。如果回测在20240401就用了这个数据，等于使用了未来信息。**必须用ann_date >= 当前日期的过滤来保证point-in-time**
2. **🔴 同一end_date可能有多条记录** — 业绩预披露/修正/正式公告会产生多条。需取ann_date最新的那条（最终版）
3. **🔴 百分比字段已乘100** — roe=15.23表示15.23%，不是0.1523
4. **🟡 季度数据非日频** — 一年最多4条（Q1/Q2/Q3/年报）。做日频因子需要forward-fill（沿用最近一次公告的值直到下次更新）
5. **🟡 银行/保险/券商的财务指标含义不同** — 如毛利率对银行无意义。行业分组时需注意

**验证SQL**:
```sql
-- 公告日期 vs 报告期
SELECT ann_date, end_date, roe, netprofit_yoy FROM fina_indicator
WHERE symbol_id = (SELECT id FROM symbols WHERE code = '000001')
ORDER BY end_date DESC LIMIT 10;
-- ann_date应晚于end_date（通常滞后1-4个月）

-- 重复检测
SELECT symbol_id, end_date, COUNT(*) FROM fina_indicator
GROUP BY symbol_id, end_date HAVING COUNT(*) > 1 LIMIT 10;
-- 如果有重复，需要按ann_date取最新

-- ROE范围
SELECT MIN(roe), MAX(roe), AVG(roe) FROM fina_indicator 
WHERE end_date = '20231231';
-- 正常范围 -50% ~ +50%，极端值可能超过
```

---

### 2.7 moneyflow — 个股资金流向

**文档**: https://tushare.pro/document/2?doc_id=170
**积分**: 2000 | **频次**: 200次/分钟 | **单次上限**: 6000条

| 字段 | 类型 | 单位 | 说明 |
|------|------|------|------|
| ts_code | str | — | 股票代码 |
| trade_date | str | YYYYMMDD | 交易日期 |
| buy_sm_vol | int | **手** | 小单买入量 |
| buy_sm_amount | float | **万元** | 小单买入金额 |
| sell_sm_vol | int | **手** | 小单卖出量 |
| sell_sm_amount | float | **万元** | 小单卖出金额 |
| buy_md_vol | int | **手** | 中单买入量 |
| buy_md_amount | float | **万元** | 中单买入金额 |
| sell_md_vol | int | **手** | 中单卖出量 |
| sell_md_amount | float | **万元** | 中单卖出金额 |
| buy_lg_vol | int | **手** | 大单买入量 |
| buy_lg_amount | float | **万元** | 大单买入金额 |
| sell_lg_vol | int | **手** | 大单卖出量 |
| sell_lg_amount | float | **万元** | 大单卖出金额 |
| buy_elg_vol | int | **手** | 特大单买入量 |
| buy_elg_amount | float | **万元** | 特大单买入金额 |
| sell_elg_vol | int | **手** | 特大单卖出量 |
| sell_elg_amount | float | **万元** | 特大单卖出金额 |
| net_mf_vol | int | **手** | 净流入量 |
| net_mf_amount | float | **万元** | 净流入额 |

**⚠️ 已知坑**:

1. **🔴 金额单位是"万元"** — 不是元！如果因子中用moneyflow金额除以klines的close（元），量纲不对。要么moneyflow转元(×10000)，要么用cs_rank()做截面排序（不受单位影响）
2. **🔴 buy_xx_amount是总买入，不是净买入** — 净流入 = buy_xx_amount - sell_xx_amount。字段名里的"buy"容易误导
3. **🟡 大单/特大单定义由Tushare/交易所决定** — 通常特大单>100万元，大单>20万元，中单>4万元，小单<4万元。但具体阈值可能调整过
4. **🟡 覆盖率** — 不是所有股票每天都有moneyflow数据，部分低流动性股票可能缺失
5. **🟡 vol单位也是"手"** — 与daily一致

**验证SQL**:
```sql
-- 单位验证
SELECT date, buy_elg_amount, sell_elg_amount, net_mf_amount 
FROM moneyflow_daily 
WHERE symbol_id = (SELECT id FROM symbols WHERE code = '600519')
AND date = '2024-01-02';
-- 贵州茅台的特大单买入应在几千万元级别 → 单位万元 → 值应为几千

-- 逻辑一致性
SELECT COUNT(*) FROM moneyflow_daily 
WHERE ABS(net_mf_amount - (buy_sm_amount + buy_md_amount + buy_lg_amount + buy_elg_amount 
  - sell_sm_amount - sell_md_amount - sell_lg_amount - sell_elg_amount)) > 1;
-- 应为0或接近0（浮点误差范围内）

-- 覆盖率
SELECT date, COUNT(*) FROM moneyflow_daily 
WHERE date BETWEEN '2024-01-01' AND '2024-01-31'
GROUP BY date ORDER BY date;
-- 每天应有4000-5000只
```

---

### 2.8 index_daily — 指数日线

**文档**: https://tushare.pro/document/2?doc_id=95
**积分**: 2000 | **频次**: 视积分而定

| 字段 | 类型 | 单位 | 说明 |
|------|------|------|------|
| ts_code | str | — | 指数代码 |
| trade_date | str | YYYYMMDD | 交易日期 |
| close | float | 点 | 收盘点位 |
| open | float | 点 | 开盘点位 |
| high | float | 点 | 最高点位 |
| low | float | 点 | 最低点位 |
| pre_close | float | 点 | 昨收点位 |
| change | float | 点 | 涨跌点位 |
| pct_chg | float | % | 涨跌幅 |
| vol | float | **手** | 成交量 |
| amount | float | **千元** | 成交额 |

**主要指数代码**:
- 000300.SH = 沪深300（主基准）
- 000905.SH = 中证500
- 000852.SH = 中证1000
- 000001.SH = 上证综指
- 399001.SZ = 深证成指
- 399006.SZ = 创业板指

**⚠️ 已知坑**:
1. 深证成指(399001.SZ)只包含500只成分股，不代表全深市。全深市用深证A指(399107.SZ)
2. vol和amount单位与股票daily一致（手/千元）

---

### 2.9 forecast — 业绩预告 (Phase 1)

**文档**: https://tushare.pro/document/2?doc_id=45
**积分**: 5000

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| end_date | str | 报告期 |
| type | str | 预告类型（预增/预减/扭亏/首亏/续亏/续盈/略增/略减/不确定） |
| p_change_min | float | 预告净利润变动幅度下限(%) |
| p_change_max | float | 预告净利润变动幅度上限(%) |
| net_profit_min | float | 预告净利润下限（万元） |
| net_profit_max | float | 预告净利润上限（万元） |

**⚠️ 已知坑**:
1. **🔴 必须用ann_date做时间对齐** — 与fina_indicator同理，避免未来信息
2. **🟡 net_profit单位是"万元"**
3. **🟡 type字段是中文字符串** — 需要映射为数值编码

---

### 2.10 share_float — 限售解禁 (Phase 1)

**文档**: https://tushare.pro/document/2?doc_id=160
**积分**: 5000

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| float_date | str | 解禁日期 |
| float_share | float | 流通股份（万股） |
| float_ratio | float | 流通股份占总股本比(%) |

**⚠️ 已知坑**:
1. **🔴 float_share单位是"万股"**
2. **🟡 解禁日期可能提前/推迟** — 以最终公告为准
3. 做事件因子时用float_date而非ann_date（关注的是解禁日前后的价格反应）

---

### 2.11 stk_holdernumber — 股东人数 (Phase 1)

**文档**: https://tushare.pro/document/2?doc_id=166
**积分**: 5000

| 字段 | 类型 | 说明 |
|------|------|------|
| ts_code | str | 股票代码 |
| ann_date | str | 公告日期 |
| end_date | str | 截止日期 |
| holder_num | int | 股东户数（户） |

**⚠️ 已知坑**:
1. **🔴 同样需要用ann_date避免未来信息**
2. **🟡 更新频率不固定** — 季报/半年报/年报时披露，中间可能有临时公告
3. 因子逻辑：股东人数下降 → 筹码集中 → 看多信号

---

## 三、跨接口单位一致性矩阵

这是最容易出错的地方——不同接口的"同类"字段单位不同。

| 数据项 | daily | daily_basic | moneyflow | fina_indicator | 统一入库建议 |
|--------|-------|-------------|-----------|----------------|-------------|
| 价格 | 元（未复权） | 元 | — | — | 元 + adj_close列 |
| 成交量 | **手** | — | **手** | — | 转股: ×100 或 保留手但标注 |
| 成交额 | **千元** | — | **万元** | — | **⚠️ 不同!** 统一转元 |
| 市值 | — | **万元** | — | — | 转元: ×10000 或 保留万元但标注 |
| 股本 | — | **万股** | — | — | 保留万股但标注 |
| 换手率 | — | **%** | — | — | 保留%，因子用时注意 |
| 涨跌幅 | **%** | — | — | — | 保留%，转小数时÷100 |
| 财务指标 | — | — | — | **%** | 保留%，转小数时÷100 |
| 净利润 | — | — | — | 元(fina)/万元(forecast) | **⚠️ 不同!** 明确标注 |

**🔴 最危险的混用场景**:
1. `daily.amount`(千元) 与 `moneyflow.buy_elg_amount`(万元) → 相差10倍
2. `daily.amount`(千元) 与 `daily_basic.total_mv`(万元) → 相差10倍
3. `daily.vol`(手) 直接做amihud分母 → 比用"股"小100倍

---

## 四、数据拉取规范

### 4.1 拉取策略

```
全量初始化拉取:
  时间范围: 2015-01-01 ~ 今天
  按stock逐只拉取（daily/adj_factor）或按日期逐日拉取（daily_basic/moneyflow）
  
增量每日更新:
  时间: 收盘后 16:00-17:00（Tushare入库时间约15:00-16:00）
  拉取当日数据 upsert 入库

断点续传:
  维护 data_fetch_progress.json 记录已完成的stock/date
  中断后重运行自动跳过
```

### 4.2 限速控制

| 积分 | 频次限制 | 单次条数 | 建议sleep |
|------|---------|---------|-----------|
| 120 | 500次/分 | 6000条 | 0.15s |
| 2000 | 200次/分 | 6000条 | 0.35s |
| 5000 | 300次/分 | 6000条 | 0.25s |
| 8000 | 500次/分 | 6000条 | 0.15s |

**注意**: 8000积分对大部分接口频次为500次/分钟，但部分接口仍受限。遇到HTTP 429错误时自动backoff。

### 4.3 错误处理

```python
# 标准拉取模板
def fetch_with_retry(api_func, max_retries=3, **kwargs):
    for attempt in range(max_retries):
        try:
            df = api_func(**kwargs)
            if df is not None and not df.empty:
                return df
            return pd.DataFrame()  # 空数据（如停牌日）
        except Exception as e:
            if '每分钟' in str(e) or '频次' in str(e):
                time.sleep(60)  # 限频，等1分钟
            elif '权限' in str(e):
                raise  # 积分不够，直接报错
            else:
                time.sleep(2 ** attempt)  # 指数退避
    raise Exception(f"Failed after {max_retries} retries")
```

---

## 五、入库后必跑验证清单

每次拉取新数据后（无论全量还是增量），必须跑以下验证：

### 5.1 数据完整性

```sql
-- 1. 每日股票数量趋势（检测数据断裂）
SELECT date, COUNT(*) AS cnt FROM klines_daily 
WHERE date >= '2024-01-01'
GROUP BY date ORDER BY date;
-- 看cnt是否平稳，有无骤降

-- 2. klines与daily_basic日期对齐
SELECT k.date, COUNT(DISTINCT k.symbol_id) AS k_cnt, COUNT(DISTINCT d.symbol_id) AS d_cnt
FROM klines_daily k 
LEFT JOIN daily_basic d ON k.symbol_id = d.symbol_id AND k.date = d.date
WHERE k.date >= '2024-01-01'
GROUP BY k.date
HAVING COUNT(DISTINCT k.symbol_id) - COUNT(DISTINCT d.symbol_id) > 100
ORDER BY k.date;
-- 差异应很小（<50），大差异说明daily_basic拉取有缺失

-- 3. adj_factor覆盖率
SELECT k.date, COUNT(DISTINCT k.symbol_id) AS k_cnt, COUNT(DISTINCT a.symbol_id) AS a_cnt
FROM klines_daily k
LEFT JOIN adj_factors a ON k.symbol_id = a.symbol_id AND k.date = a.date
WHERE k.date = '2024-06-28'
GROUP BY k.date;
-- k_cnt和a_cnt应基本一致
```

### 5.2 数据正确性（抽样比对）

```sql
-- 取3只已知股票，手动与Tushare数据工具/Wind/东方财富 对比
-- 股票1: 贵州茅台(600519) — 高价股
-- 股票2: 平安银行(000001) — 大盘股
-- 股票3: 某创业板小盘股

SELECT s.code, s.name, k.date, k.open, k.close, k.volume, k.amount,
       d.pe_ttm, d.pb, d.turnover_rate_f, d.total_mv, d.circ_mv
FROM klines_daily k
JOIN symbols s ON k.symbol_id = s.id
LEFT JOIN daily_basic d ON k.symbol_id = d.symbol_id AND k.date = d.date
WHERE s.code IN ('600519', '000001', '300750')
AND k.date = '2024-06-28';

-- 逐字段与官方数据工具比对:
-- https://tushare.pro/document/2 → 数据工具 → 选接口 → 输入参数 → 查看
```

### 5.3 单位一致性验证

```sql
-- VWAP验证: amount(千元)/vol(手) 应约等于 close(元) × 10
-- 因为: (千元/手) = (1000元 / 100股) = 10元/股
SELECT date, close, 
       CASE WHEN volume > 0 THEN amount / volume ELSE NULL END AS vwap_ratio,
       CASE WHEN volume > 0 THEN close / (amount / volume) ELSE NULL END AS check_ratio
FROM klines_daily 
WHERE symbol_id = (SELECT id FROM symbols WHERE code = '600519')
AND date = '2024-06-28';
-- check_ratio 应约等于 0.1 (即 close ≈ vwap_ratio × 0.1)
-- 如果check_ratio ≈ 1, 说明amount/vol的比值直接等于价格，单位可能已被转换过

-- moneyflow单位验证: 买卖金额之和应≈daily的amount
SELECT k.date, k.amount AS daily_amount_千元,
       (m.buy_sm_amount + m.buy_md_amount + m.buy_lg_amount + m.buy_elg_amount) AS mf_buy_万元
FROM klines_daily k
JOIN moneyflow_daily m ON k.symbol_id = m.symbol_id AND k.date = m.date
WHERE k.symbol_id = (SELECT id FROM symbols WHERE code = '600519')
AND k.date = '2024-06-28';
-- daily_amount(千元) ≈ mf_total(万元) × 10 
-- 因为 万元/千元 = 10
```

---

## 六、因子计算中的单位处理规范

### 6.1 截面排序因子（推荐，不受单位影响）

```sql
-- 用cs_rank()做截面排序，输入值的绝对大小不影响排序结果
-- 例: turnover因子
cs_rank(turnover_rate_f)  -- 无论%还是小数，排序结果一样
```

### 6.2 需要跨表计算的因子（必须对齐单位）

```python
# amihud非流动性 = |return| / (amount_元)
# 如果amount存的是千元:
amihud = abs(pct_chg / 100) / (amount * 1000)  # 千元→元

# 或者如果amount已入库时转为元:
amihud = abs(pct_chg / 100) / amount  # 直接用

# moneyflow净主力流入占比 = net_mf_amount / daily_amount
# moneyflow是万元, daily是千元:
ratio = (net_mf_amount * 10000) / (daily_amount * 1000)  # 统一为元后相除
# 或者: ratio = net_mf_amount / daily_amount * 10  # 万元/千元 = 10
```

### 6.3 入库单位转换决策

**推荐方案**: 入库时保持原始单位不变，但在数据库列注释中明确标注单位。因子计算层负责转换。

原因：
1. 保持与Tushare文档一致，方便排查
2. 不引入二次转换错误
3. 任何使用者都必须读本checklist确认单位

```sql
-- DB列注释示例
COMMENT ON COLUMN klines_daily.volume IS '成交量（手，1手=100股）';
COMMENT ON COLUMN klines_daily.amount IS '成交额（千元）';
COMMENT ON COLUMN daily_basic.total_mv IS '总市值（万元）';
COMMENT ON COLUMN moneyflow_daily.buy_elg_amount IS '特大单买入金额（万元）';
```

---

## 七、Checklist执行记录

每次接入新接口时，在下方打勾确认：

| # | 检查项 | stock_basic | trade_cal | daily | adj_factor | daily_basic | fina_indicator | moneyflow | index_daily |
|---|--------|-------------|-----------|-------|------------|-------------|----------------|-----------|-------------|
| 1 | 已读官方文档页 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 2 | 确认所有字段单位 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 3 | 写入DB列注释 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 4 | 跑验证SQL通过 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 5 | 抽样比对官方工具 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |
| 6 | 跨表单位一致性检查 | — | — | ☐ | ☐ | ☐ | — | ☐ | — |
| 7 | 因子计算代码标注单位 | — | — | ☐ | ☐ | ☐ | ☐ | ☐ | — |
| 8 | 限速/断点续传测试 | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ | ☐ |

---

## 八、AKShare备用源对照

以下数据同时可从AKShare获取（免费、无积分限制但有限速）：

| 数据 | Tushare接口 | AKShare接口 | 优先用 | 备注 |
|------|------------|-------------|--------|------|
| 北向资金持股 | — | stock_hsgt_hold_stock_em | AKShare | Tushare无此接口 |
| 融资融券 | margin_detail(5000) | stock_margin_detail_szse | AKShare | 免费且覆盖充分 |
| 资金流向 | moneyflow(2000) | stock_individual_fund_flow | 都行 | AKShare有限速 |
| 日线行情 | daily(120) | stock_zh_a_hist | Tushare | 更稳定 |
| 指数行情 | index_daily(2000) | stock_zh_index_daily | 都行 | — |

降级策略: Tushare失败 → 等待60s重试 → 3次失败后切AKShare → AKShare也失败则报警。

---

*最后更新: 2026-03-20*
*适用版本: QuantMind V2 Phase 0*
*维护者: Stanley*
