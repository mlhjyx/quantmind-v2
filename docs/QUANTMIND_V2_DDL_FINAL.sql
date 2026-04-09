-- ============================================================================
-- QuantMind V2 — 完整数据库DDL（合并版）
-- ============================================================================
-- 本文件是所有表的唯一DDL来源。Claude Code建表只看这一份文件。
-- 基于原版DDL命名规范(code做PK, trade_date) + 三轮review全部补丁
--
-- 总计: 43张表
--   域1 基础数据(5) + 域2 另类数据(5+1) + 域3 因子(3) + 域4 信号(3)
--   域5 交易执行(3) + 域6 AI模型(3) + 域7 系统运维(6) + 域8 外汇(3)
--   域9 回测引擎(6) + 域10 因子挖掘(3) + 域11 AI闭环(3)
--
-- 字段单位: 全部在COMMENT中标明。参考 TUSHARE_DATA_SOURCE_CHECKLIST.md
-- 前置: CREATE EXTENSION IF NOT EXISTS timescaledb;
--        CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- ============================================================================

-- ═══════════════════════════════════════════════════
-- 域1: 基础数据（5张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE symbols (
    code            VARCHAR(10) PRIMARY KEY,
    ts_code         VARCHAR(12),                       -- Tushare格式 '000001.SZ'
    name            VARCHAR(20) NOT NULL,
    market          VARCHAR(10) NOT NULL DEFAULT 'astock',  -- astock/forex
    board           VARCHAR(10),                       -- main/gem/star/bse (主板/创业板/科创板/北交所)
    exchange        VARCHAR(10),                       -- SSE/SZSE
    industry_sw1    VARCHAR(50),                       -- 申万一级行业
    industry_sw2    VARCHAR(20),                       -- 申万二级行业
    area            VARCHAR(20),
    list_date       DATE,
    delist_date     DATE,                              -- ⭐退市日期（必须保留退市股！存活偏差）
    list_status     VARCHAR(2) DEFAULT 'L',            -- L=上市 D=退市 P=暂停
    is_hs           VARCHAR(2),                        -- N/H/S 沪深港通标记
    price_limit     DECIMAL(4,2) DEFAULT 0.10,         -- 涨跌停: 0.10/0.20/0.05/0.30
    lot_size        INT DEFAULT 100,                   -- 最小交易单位(股)
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE symbols IS '股票/货币对基础信息。⭐必须包含退市股(list_status=D)以避免存活偏差';
COMMENT ON COLUMN symbols.price_limit IS '涨跌停幅度: 主板0.10, 创业板/科创板0.20, ST0.05, 北交所0.30';
CREATE INDEX idx_symbols_market ON symbols(market, list_status);

CREATE TABLE klines_daily (
    code            VARCHAR(10) NOT NULL REFERENCES symbols(code),
    trade_date      DATE NOT NULL,
    open            DECIMAL(12,4),
    high            DECIMAL(12,4),
    low             DECIMAL(12,4),
    close           DECIMAL(12,4),
    pre_close       DECIMAL(12,4),                     -- 昨收价(未复权)
    change          DECIMAL(12,4),                     -- 涨跌额(元)
    pct_change      DECIMAL(8,4),                      -- 涨跌幅(%, 已乘100: 5.06=涨5.06%)
    volume          BIGINT,                            -- 手(1手=100股)
    amount          DECIMAL(16,2),                     -- 千元(Tushare原始单位)
    turnover_rate   DECIMAL(8,4),                      -- 换手率%(总股本)
    adj_factor      DECIMAL(12,6) DEFAULT 1.0,         -- 复权因子(累积因子,非每日比率)
    is_suspended    BOOLEAN DEFAULT FALSE,
    is_st           BOOLEAN DEFAULT FALSE,
    up_limit        DECIMAL(12,4),                     -- 涨停价
    down_limit      DECIMAL(12,4),                     -- 跌停价
    PRIMARY KEY (code, trade_date)
);
COMMENT ON TABLE klines_daily IS '日线行情。价格=未复权元, volume=手(×100=股), amount=千元';
COMMENT ON COLUMN klines_daily.volume IS '成交量（手，1手=100股）';
COMMENT ON COLUMN klines_daily.amount IS '成交额（千元，⚠️与moneyflow的万元不同！）';
COMMENT ON COLUMN klines_daily.pct_change IS '涨跌幅（%，已乘100：5.06表示涨5.06%）';
COMMENT ON COLUMN klines_daily.adj_factor IS '累积复权因子。adj_close = close × adj_factor / latest_adj_factor';
SELECT create_hypertable('klines_daily', 'trade_date', if_not_exists => TRUE,
                         chunk_time_interval => INTERVAL '1 month');

CREATE TABLE forex_bars (                              -- Phase 2
    symbol          VARCHAR(10) NOT NULL,              -- EURUSD etc
    timeframe       VARCHAR(5) NOT NULL,               -- D1/H4/H1/M15
    bar_time        TIMESTAMPTZ NOT NULL,
    open            DECIMAL(10,5),
    high            DECIMAL(10,5),
    low             DECIMAL(10,5),
    close           DECIMAL(10,5),
    tick_volume     BIGINT,
    spread          DECIMAL(6,1),                      -- 点差(points)
    session         VARCHAR(10),                       -- tokyo/london/newyork
    is_holiday      BOOLEAN DEFAULT FALSE,
    data_source     VARCHAR(10) DEFAULT 'mt5',
    PRIMARY KEY (symbol, timeframe, bar_time)
);
SELECT create_hypertable('forex_bars', 'bar_time', if_not_exists => TRUE);

CREATE TABLE daily_basic (
    code            VARCHAR(10) NOT NULL REFERENCES symbols(code),
    trade_date      DATE NOT NULL,
    close           DECIMAL(12,4),                     -- 元
    turnover_rate   DECIMAL(8,4),                      -- %(总股本换手率)
    turnover_rate_f DECIMAL(8,4),                      -- %(⭐自由流通换手率，推荐用这个)
    volume_ratio    DECIMAL(8,4),                      -- 倍(量比)
    pe              DECIMAL(12,4),                      -- 倍(静态PE)
    pe_ttm          DECIMAL(12,4),                      -- 倍(TTM PE, 可为负)
    pb              DECIMAL(12,4),                      -- 倍
    ps              DECIMAL(12,4),
    ps_ttm          DECIMAL(12,4),
    dv_ratio        DECIMAL(8,4),                      -- %(股息率静态)
    dv_ttm          DECIMAL(8,4),                      -- %(股息率TTM)
    total_share     DECIMAL(16,4),                     -- 万股
    float_share     DECIMAL(16,4),                     -- 万股
    free_share      DECIMAL(16,4),                     -- 万股
    total_mv        DECIMAL(16,2),                     -- 万元(⚠️不是元！)
    circ_mv         DECIMAL(16,2),                     -- 万元(⚠️不是元！)
    PRIMARY KEY (code, trade_date)
);
COMMENT ON TABLE daily_basic IS '每日指标。total_mv/circ_mv=万元, turnover_rate=%';
COMMENT ON COLUMN daily_basic.total_mv IS '总市值（万元，⚠️不是元！跨表计算注意单位）';
COMMENT ON COLUMN daily_basic.turnover_rate_f IS '换手率-自由流通股（%，⭐因子计算推荐用这个）';

CREATE TABLE trading_calendar (
    trade_date      DATE NOT NULL,
    market          VARCHAR(10) NOT NULL DEFAULT 'astock',
    is_trading_day  BOOLEAN NOT NULL,
    is_half_day     BOOLEAN DEFAULT FALSE,
    pretrade_date   DATE,                              -- 上一交易日
    PRIMARY KEY (trade_date, market)
);
COMMENT ON TABLE trading_calendar IS '交易日历。年初导入+每日T0预检校验';
CREATE INDEX idx_calendar_trading ON trading_calendar(market, is_trading_day, trade_date);

-- ═══════════════════════════════════════════════════
-- 域2: 另类数据（5+1张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE moneyflow_daily (
    code            VARCHAR(10) NOT NULL REFERENCES symbols(code),
    trade_date      DATE NOT NULL,
    buy_sm_vol      BIGINT,                            -- 手
    buy_sm_amount   DECIMAL(16,2),                     -- 万元(⚠️不是千元！与klines不同)
    sell_sm_vol     BIGINT,
    sell_sm_amount  DECIMAL(16,2),                     -- 万元
    buy_md_vol      BIGINT,
    buy_md_amount   DECIMAL(16,2),                     -- 万元
    sell_md_vol     BIGINT,
    sell_md_amount  DECIMAL(16,2),
    buy_lg_vol      BIGINT,
    buy_lg_amount   DECIMAL(16,2),                     -- 万元
    sell_lg_vol     BIGINT,
    sell_lg_amount  DECIMAL(16,2),
    buy_elg_vol     BIGINT,
    buy_elg_amount  DECIMAL(16,2),                     -- 万元
    sell_elg_vol    BIGINT,
    sell_elg_amount DECIMAL(16,2),
    net_mf_vol      BIGINT,                            -- 手
    net_mf_amount   DECIMAL(16,2),                     -- 万元(大单+超大单净流入)
    PRIMARY KEY (code, trade_date)
);
COMMENT ON TABLE moneyflow_daily IS '资金流向。金额=万元（⚠️与klines的千元不同，相差10倍！）';
COMMENT ON COLUMN moneyflow_daily.buy_elg_amount IS '特大单买入金额（万元，总买入不是净买入）';

CREATE TABLE northbound_holdings (
    code            VARCHAR(10) NOT NULL REFERENCES symbols(code),
    trade_date      DATE NOT NULL,
    hold_vol        BIGINT,                            -- 股
    hold_ratio      DECIMAL(8,4),                      -- %
    hold_mv         DECIMAL(16,2),                     -- 万元
    net_buy_vol     BIGINT,                            -- 当日净买入量
    PRIMARY KEY (code, trade_date)
);
COMMENT ON TABLE northbound_holdings IS '北向资金持仓（数据源: AKShare）';

CREATE TABLE margin_data (
    code            VARCHAR(10) NOT NULL REFERENCES symbols(code),
    trade_date      DATE NOT NULL,
    margin_balance  DECIMAL(16,2),                     -- 元(融资余额)
    margin_buy      DECIMAL(16,2),                     -- 元
    short_balance   DECIMAL(16,2),                     -- 元(融券余额)
    short_vol       BIGINT,                            -- 融券余量
    PRIMARY KEY (code, trade_date)
);
COMMENT ON TABLE margin_data IS '融资融券（数据源: AKShare）。单位=元';

CREATE TABLE chip_distribution (                       -- Phase 1, 数据质量存疑
    code            VARCHAR(10) NOT NULL REFERENCES symbols(code),
    trade_date      DATE NOT NULL,
    winner_rate     DECIMAL(8,4),                      -- %
    cost_5pct       DECIMAL(12,4),
    cost_15pct      DECIMAL(12,4),
    cost_50pct      DECIMAL(12,4),
    cost_85pct      DECIMAL(12,4),
    cost_95pct      DECIMAL(12,4),
    PRIMARY KEY (code, trade_date)
);
COMMENT ON TABLE chip_distribution IS '筹码分布（Phase 1, 数据质量存疑, Phase 0不依赖筹码类因子）';

CREATE TABLE financial_indicators (
    code            VARCHAR(10) NOT NULL REFERENCES symbols(code),
    report_date     DATE NOT NULL,                     -- 报告期(2024-12-31)
    actual_ann_date DATE,                              -- ⭐实际公告日(PIT关键!用这个做时间对齐)
    roe             DECIMAL(12,4),                     -- %(已乘100)
    roe_dt          DECIMAL(12,4),                     -- %(扣非ROE)
    roa             DECIMAL(12,4),                     -- %
    gross_profit_margin DECIMAL(12,4),                 -- %
    net_profit_margin   DECIMAL(12,4),                 -- %
    revenue_yoy     DECIMAL(12,4),                     -- %(营收同比)
    net_profit_yoy  DECIMAL(12,4),                     -- %(净利润同比)
    basic_eps_yoy   DECIMAL(12,4),                     -- %(EPS同比)
    eps             DECIMAL(12,4),
    bps             DECIMAL(12,4),
    current_ratio   DECIMAL(12,4),                     -- 倍
    quick_ratio     DECIMAL(12,4),                     -- 倍
    debt_to_asset   DECIMAL(12,4),                     -- %
    PRIMARY KEY (code, report_date)
);
COMMENT ON TABLE financial_indicators IS '财务指标PIT版。⚠️必须用actual_ann_date做时间对齐！入库前actual_ann_date为NULL时用report_date+90天做fallback';
COMMENT ON COLUMN financial_indicators.actual_ann_date IS '实际公告日（⭐PIT关键）。NULL时fallback=report_date+90天，入库前必须填充';
CREATE INDEX idx_fina_pit ON financial_indicators(code, actual_ann_date);
CREATE UNIQUE INDEX idx_fina_dedup ON financial_indicators(code, report_date, actual_ann_date) WHERE actual_ann_date IS NOT NULL;

CREATE TABLE index_daily (
    index_code      VARCHAR(12) NOT NULL,              -- 000300.SH
    trade_date      DATE NOT NULL,
    open            DECIMAL(12,4),
    high            DECIMAL(12,4),
    low             DECIMAL(12,4),
    close           DECIMAL(12,4),
    pre_close       DECIMAL(12,4),
    pct_change      DECIMAL(8,4),                      -- %
    volume          BIGINT,                            -- 手
    amount          DECIMAL(16,2),                     -- 千元
    PRIMARY KEY (index_code, trade_date)
);
COMMENT ON TABLE index_daily IS '指数日线(沪深300/中证500/中证1000等)';

-- ⭐ Review新增表
CREATE TABLE index_components (
    index_code      VARCHAR(12) NOT NULL,
    code            VARCHAR(10) NOT NULL,
    trade_date      DATE NOT NULL,
    weight          DECIMAL(8,6),                      -- 权重 0.035 = 3.5%
    PRIMARY KEY (index_code, code, trade_date)
);
COMMENT ON TABLE index_components IS '指数成分股权重历史（行业中性化/基准对冲/IC超额收益）';
CREATE INDEX idx_index_comp_date ON index_components(trade_date, index_code);

-- ═══════════════════════════════════════════════════
-- 域3: 因子（3张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE factor_registry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(50) NOT NULL UNIQUE,
    category        VARCHAR(30) NOT NULL,              -- price_volume/liquidity/money_flow/fundamental/size
    direction       SMALLINT NOT NULL DEFAULT 1,       -- 1=正向 -1=反向
    expression      TEXT,
    code_content    TEXT,
    hypothesis      TEXT,
    source          VARCHAR(20) DEFAULT 'builtin',     -- builtin/gp/llm/brute/manual
    lookback_days   INT DEFAULT 60,
    status          VARCHAR(20) DEFAULT 'active',      -- candidate/active/warning/critical/retired
    gate_ic         DECIMAL(8,4),
    gate_ir         DECIMAL(8,4),
    gate_mono       DECIMAL(8,4),
    gate_t          DECIMAL(8,4),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE factor_registry IS '因子注册表。状态机: candidate→active→warning→critical→retired';

CREATE TABLE factor_values (
    code            VARCHAR(10) NOT NULL,
    trade_date      DATE NOT NULL,
    factor_name     VARCHAR(50) NOT NULL,
    raw_value       DECIMAL(16,6),
    neutral_value   DECIMAL(16,6),                     -- 中性化后(去极值→填充→中性化→标准化顺序)
    zscore          DECIMAL(16,6),                     -- 标准化后
    PRIMARY KEY (code, trade_date, factor_name)
);
COMMENT ON TABLE factor_values IS '因子值(长表)。写入模式: 按日期批量写(单事务写入当日全部)';
SELECT create_hypertable('factor_values', 'trade_date', if_not_exists => TRUE,
                         chunk_time_interval => INTERVAL '1 month');
CREATE INDEX idx_fv_date_factor ON factor_values(trade_date, factor_name);

CREATE TABLE factor_ic_history (
    factor_name     VARCHAR(50) NOT NULL,
    trade_date      DATE NOT NULL,
    ic_1d           DECIMAL(8,6),                      -- 超额收益IC(相对沪深300)
    ic_5d           DECIMAL(8,6),
    ic_10d          DECIMAL(8,6),
    ic_20d          DECIMAL(8,6),
    ic_abs_1d       DECIMAL(8,6),                      -- 绝对收益IC
    ic_abs_5d       DECIMAL(8,6),
    ic_ma20         DECIMAL(8,6),
    ic_ma60         DECIMAL(8,6),
    decay_level     VARCHAR(10) DEFAULT 'normal',      -- normal/warning/critical
    PRIMARY KEY (factor_name, trade_date)
);
COMMENT ON TABLE factor_ic_history IS 'IC=相对沪深300超额收益。ic_abs=绝对收益IC';

-- ═══════════════════════════════════════════════════
-- 域4: Universe与信号（3张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE universe_daily (
    code            VARCHAR(10) NOT NULL,
    trade_date      DATE NOT NULL,
    in_universe     BOOLEAN NOT NULL,
    exclude_reason  VARCHAR(50),                       -- st/suspended/new/limit/liquidity/mcap/industry/delisting
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE signals (
    code            VARCHAR(10) NOT NULL,
    trade_date      DATE NOT NULL,
    strategy_id     UUID,
    alpha_score     DECIMAL(12,6),
    rank            INT,
    target_weight   DECIMAL(8,6),
    action          VARCHAR(10),                       -- buy/sell/hold
    execution_mode  VARCHAR(10) DEFAULT 'paper',       -- paper/live
    signal_generated_at TIMESTAMPTZ DEFAULT NULL,      -- 信号生成时间(UTC), gap_hours毕业指标
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (code, trade_date, strategy_id)
);
CREATE INDEX idx_signals_date ON signals(trade_date, strategy_id);

-- ═══════════════════════════════════════════════════
-- 域5: 交易执行（3张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE trade_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code            VARCHAR(10) NOT NULL,
    trade_date      DATE NOT NULL,
    strategy_id     UUID,
    market          VARCHAR(10) DEFAULT 'astock',
    direction       VARCHAR(4) NOT NULL,               -- buy/sell
    quantity        INT NOT NULL,                       -- 股数(已整手约束: floor(x/100)*100)
    target_price    DECIMAL(12,4),
    fill_price      DECIMAL(12,4),
    slippage_bps    DECIMAL(8,2),                      -- 滑点(基点)
    commission      DECIMAL(12,4),                     -- 元
    stamp_tax       DECIMAL(12,4),                     -- 元
    swap_cost       DECIMAL(12,4) DEFAULT 0,           -- 外汇Swap
    total_cost      DECIMAL(12,4),                     -- 元
    execution_mode  VARCHAR(10) DEFAULT 'paper',       -- ⭐paper/live
    reject_reason   VARCHAR(100),                      -- limit_up/limit_down/suspended/insufficient_fund
    executed_at     TIMESTAMPTZ DEFAULT NULL,           -- 实际执行确认时间(UTC)
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE trade_log IS '交易记录。execution_mode区分paper/live';
CREATE INDEX idx_trade_log_date ON trade_log(trade_date, market);

CREATE TABLE position_snapshot (
    code            VARCHAR(10) NOT NULL,
    trade_date      DATE NOT NULL,
    strategy_id     UUID,
    market          VARCHAR(10) DEFAULT 'astock',
    quantity        INT,                               -- 股数
    avg_cost        DECIMAL(12,4),                     -- 元/股
    market_value    DECIMAL(16,2),                     -- 元
    weight          DECIMAL(8,6),
    unrealized_pnl  DECIMAL(16,2),                     -- 元
    holding_days    INT,
    execution_mode  VARCHAR(10) NOT NULL DEFAULT 'paper',  -- ⭐paper/live/qmt_sim
    PRIMARY KEY (code, trade_date, strategy_id, execution_mode)
);
COMMENT ON TABLE position_snapshot IS '每日持仓快照。execution_mode参与PK，paper/live天然隔离';

CREATE TABLE performance_series (
    trade_date      DATE NOT NULL,
    strategy_id     UUID,
    market          VARCHAR(10) DEFAULT 'astock',
    nav             DECIMAL(16,6),
    daily_return    DECIMAL(12,8),
    cumulative_return DECIMAL(12,8),
    drawdown        DECIMAL(12,8),
    cash_ratio      DECIMAL(8,6),
    position_count  INT,
    turnover        DECIMAL(8,6),
    benchmark_nav   DECIMAL(16,6),
    excess_return   DECIMAL(12,8),
    execution_mode  VARCHAR(10) NOT NULL DEFAULT 'paper',  -- ⭐paper/live/qmt_sim
    PRIMARY KEY (trade_date, strategy_id, execution_mode)
);

-- ═══════════════════════════════════════════════════
-- 域6: AI模型管理（3张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE model_registry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_type      VARCHAR(20) NOT NULL,              -- lgbm/rf/xgboost/mlp
    market          VARCHAR(10) DEFAULT 'astock',
    purpose         VARCHAR(30),                       -- factor_compose/signal_filter/vol_predict
    version         INT DEFAULT 1,
    train_date      DATE,
    train_window    VARCHAR(30),
    oos_sharpe      DECIMAL(8,4),
    oos_ic          DECIMAL(8,6),
    feature_importance JSONB,
    parameters      JSONB,
    file_path       VARCHAR(200),
    status          VARCHAR(10) DEFAULT 'candidate',   -- candidate/active/retired
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ai_parameters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    param_name      VARCHAR(50) UNIQUE NOT NULL,
    param_value     JSONB NOT NULL,                    -- JSONB支持各种类型
    param_min       JSONB,
    param_max       JSONB,
    param_default   JSONB NOT NULL,
    param_type      VARCHAR(20) DEFAULT 'float',       -- float/int/bool/enum
    module          VARCHAR(30),                       -- universe/factor/signal/risk
    market          VARCHAR(10) DEFAULT 'global',
    updated_by      VARCHAR(10) DEFAULT 'manual',      -- manual/ai
    authorization_level VARCHAR(10) DEFAULT 'auto',    -- auto/approval/frozen
    cooldown_hours  INT DEFAULT 168,
    cooldown_until  TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE experiments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_type VARCHAR(30) NOT NULL,              -- backtest/factor_mining/param_search
    parameters      JSONB,
    results         JSONB,
    status          VARCHAR(10) DEFAULT 'running',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    completed_at    TIMESTAMPTZ
);

-- ═══════════════════════════════════════════════════
-- 域7: 系统运维（6张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE strategy (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,
    market          VARCHAR(10) DEFAULT 'astock',
    mode            VARCHAR(10) DEFAULT 'visual',      -- visual/code
    factor_config   JSONB,
    code_content    TEXT,
    backtest_config JSONB,
    active_version  INT DEFAULT 1,                     -- ⭐当前活跃版本号(回滚=改这个)
    status          VARCHAR(15) DEFAULT 'draft',       -- draft/backtested/paper/deployed/archived
    deployed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE strategy IS '策略定义。active_version指向strategy_configs的version';

CREATE TABLE strategy_configs (
    strategy_id     UUID NOT NULL REFERENCES strategy(id),
    version         INT NOT NULL,
    config          JSONB NOT NULL,                    -- 完整配置快照
    changelog       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (strategy_id, version)
);
COMMENT ON TABLE strategy_configs IS '策略版本管理。每次变更插入新version行(不更新旧行)。回滚=改active_version';

CREATE TABLE notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level           VARCHAR(2) NOT NULL,               -- P0/P1/P2/P3
    category        VARCHAR(20) NOT NULL,
    market          VARCHAR(10) DEFAULT 'system',
    title           VARCHAR(100) NOT NULL,
    content         TEXT,
    link            VARCHAR(200),
    is_read         BOOLEAN DEFAULT FALSE,
    is_acted        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_notifications_unread ON notifications(is_read, created_at DESC);

CREATE TABLE notification_preferences (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    toast_p0 BOOLEAN DEFAULT TRUE, toast_p1 BOOLEAN DEFAULT TRUE,
    toast_p2 BOOLEAN DEFAULT TRUE, toast_p3 BOOLEAN DEFAULT TRUE,
    dingtalk_enabled BOOLEAN DEFAULT FALSE,
    dingtalk_webhook VARCHAR(500),
    dispatch_p0 BOOLEAN DEFAULT TRUE, dispatch_p1 BOOLEAN DEFAULT TRUE,
    dispatch_p2 BOOLEAN DEFAULT FALSE,
    quiet_enabled BOOLEAN DEFAULT TRUE,
    quiet_start SMALLINT DEFAULT 23, quiet_end SMALLINT DEFAULT 7,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ⭐ Review新增: 健康预检表(与调度绑定)
CREATE TABLE health_checks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    check_date      DATE NOT NULL,
    check_time      TIMESTAMPTZ DEFAULT NOW(),
    postgresql_ok   BOOLEAN NOT NULL,
    redis_ok        BOOLEAN NOT NULL,
    data_fresh      BOOLEAN NOT NULL,                  -- klines最新日期=上一交易日
    factor_nan_ok   BOOLEAN NOT NULL,                  -- 抽样检查无NaN
    disk_ok         BOOLEAN NOT NULL,                  -- 磁盘>10GB
    celery_ok       BOOLEAN NOT NULL,
    all_pass        BOOLEAN NOT NULL,
    failed_items    TEXT[],
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE health_checks IS '每日全链路健康预检(T0)。all_pass=false暂停全链路';
CREATE INDEX idx_health_date ON health_checks(check_date DESC);

CREATE TABLE scheduler_task_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_name       VARCHAR(50) NOT NULL,
    market          VARCHAR(10),
    schedule_time   TIMESTAMPTZ NOT NULL,
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    duration_sec    INT,
    status          VARCHAR(10) NOT NULL,              -- success/failed/running/skipped
    error_message   TEXT,
    retry_count     INT DEFAULT 0,
    result_json     JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_scheduler_log_date ON scheduler_task_log(schedule_time DESC);

-- ═══════════════════════════════════════════════════
-- 域8: 外汇专用（2张表）— Phase 2
-- forex_bars已在域1
-- ═══════════════════════════════════════════════════

CREATE TABLE forex_swap_rates (
    symbol          VARCHAR(10) NOT NULL,
    trade_date      DATE NOT NULL,
    swap_long       DECIMAL(10,4),
    swap_short      DECIMAL(10,4),
    PRIMARY KEY (symbol, trade_date)
);

CREATE TABLE forex_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_time      TIMESTAMPTZ NOT NULL,
    currency        VARCHAR(3) NOT NULL,
    event_name      VARCHAR(100) NOT NULL,
    importance      SMALLINT,                          -- 1/2/3
    actual          VARCHAR(20),
    forecast        VARCHAR(20),
    previous        VARCHAR(20),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_forex_events_time ON forex_events(event_time);

-- ═══════════════════════════════════════════════════
-- 域9: 回测引擎（6张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE backtest_run (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     UUID REFERENCES strategy(id),
    name            VARCHAR(100),
    config_json     JSONB NOT NULL,
    factor_list     TEXT[] NOT NULL,
    status          VARCHAR(20) DEFAULT 'pending',     -- pending/running/success/failed
    -- 基础指标
    annual_return   DECIMAL(8,4),
    sharpe_ratio    DECIMAL(8,4),
    max_drawdown    DECIMAL(8,4),
    excess_return   DECIMAL(8,4),
    -- ⭐ Review新增12项指标
    calmar_ratio    DECIMAL(8,4),
    sortino_ratio   DECIMAL(8,4),
    information_ratio DECIMAL(8,4),
    beta            DECIMAL(8,4),
    win_rate        DECIMAL(8,4),
    profit_loss_ratio DECIMAL(8,4),
    annual_turnover DECIMAL(8,4),
    max_consecutive_loss_days INT,
    sharpe_ci_lower DECIMAL(8,4),                      -- Bootstrap 95% CI下界
    sharpe_ci_upper DECIMAL(8,4),                      -- Bootstrap 95% CI上界
    avg_overnight_gap DECIMAL(8,4),                    -- 开盘跳空平均偏差
    position_deviation DECIMAL(8,4),                   -- 实际vs理论仓位偏差
    cost_sensitivity_json JSONB,                       -- {0.5x:{sharpe,return,mdd}, ...}
    annual_breakdown_json JSONB,                       -- 每年收益/Sharpe/MDD
    market_state_json JSONB,                           -- 牛/熊/震荡分段绩效
    -- 元数据
    total_trades    INT,
    start_date      DATE,
    end_date        DATE,
    elapsed_sec     INT,
    error_message   TEXT,
    -- Step 6-B 新增: 可复现性追溯 (铁律15)
    config_yaml_hash VARCHAR(64),                       -- configs/strategy/*.yaml 的 sha256
    git_commit      VARCHAR(40),                        -- 回测运行时的git commit
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_backtest_strategy ON backtest_run(strategy_id, created_at DESC);
CREATE INDEX idx_backtest_config_hash ON backtest_run(config_yaml_hash);

CREATE TABLE backtest_daily_nav (
    run_id          UUID NOT NULL REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    nav             DECIMAL(16,6) NOT NULL,
    cash            DECIMAL(16,2),
    market_value    DECIMAL(16,2),
    daily_return    DECIMAL(12,8),
    benchmark_nav   DECIMAL(16,6),
    excess_return   DECIMAL(12,8),
    drawdown        DECIMAL(12,8),
    PRIMARY KEY (run_id, trade_date)
);

CREATE TABLE backtest_trades (
    run_id          UUID NOT NULL REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    trade_id        UUID DEFAULT gen_random_uuid(),
    signal_date     DATE NOT NULL,
    exec_date       DATE NOT NULL,
    stock_code      VARCHAR(10) NOT NULL,
    side            VARCHAR(4) NOT NULL,               -- buy/sell
    shares          INT NOT NULL,                      -- 已整手约束
    exec_price      DECIMAL(12,4) NOT NULL,
    slippage_bps    DECIMAL(8,2),
    commission      DECIMAL(12,4),
    stamp_tax       DECIMAL(12,4),
    total_cost      DECIMAL(12,4),
    reject_reason   VARCHAR(100),                      -- limit_up/limit_down/suspended/insufficient_fund
    PRIMARY KEY (run_id, trade_id)
);
CREATE INDEX idx_bt_trades_date ON backtest_trades(run_id, exec_date);

CREATE TABLE backtest_holdings (
    run_id          UUID NOT NULL REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    trade_date      DATE NOT NULL,
    stock_code      VARCHAR(10) NOT NULL,
    shares          INT NOT NULL,
    cost_basis      DECIMAL(12,4),
    market_price    DECIMAL(12,4),
    weight          DECIMAL(8,6),
    buy_date        DATE,
    industry_code   VARCHAR(10),
    PRIMARY KEY (run_id, trade_date, stock_code)
);

CREATE TABLE backtest_wf_windows (
    run_id          UUID REFERENCES backtest_run(run_id) ON DELETE CASCADE,
    window_id       INT NOT NULL,
    train_start     DATE NOT NULL,
    train_end       DATE NOT NULL,
    valid_start     DATE,
    valid_end       DATE,
    test_start      DATE NOT NULL,
    test_end        DATE NOT NULL,
    oos_annual_return DECIMAL(8,4),
    oos_sharpe      DECIMAL(8,4),
    oos_max_drawdown DECIMAL(8,4),
    selected_factors TEXT[],
    model_params    JSONB,
    PRIMARY KEY (run_id, window_id)
);

-- ═══════════════════════════════════════════════════
-- 域10: 因子挖掘管理（3张表）
-- ═══════════════════════════════════════════════════

CREATE TABLE factor_evaluation (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factor_name     VARCHAR(50) NOT NULL,
    eval_date       DATE NOT NULL,
    ic_stats        JSONB,                             -- {ic_mean, ic_std, ic_ir, ...}
    group_returns   JSONB,
    decay_analysis  JSONB,
    correlation     JSONB,
    annual_breakdown JSONB,
    market_state    JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_factor_eval ON factor_evaluation(factor_name, eval_date DESC);

CREATE TABLE factor_mining_task (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    method          VARCHAR(20) NOT NULL,              -- gp/llm/brute/manual
    config_json     JSONB,
    status          VARCHAR(20) DEFAULT 'pending',
    total_candidates INT DEFAULT 0,
    passed_filter   INT DEFAULT 0,
    entered_library INT DEFAULT 0,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE mining_knowledge (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    factor_name     VARCHAR(100),
    factor_hash     VARCHAR(64),                       -- ⭐AST结构哈希，与 gp_approval_queue.ast_hash 一致
    expression      TEXT NOT NULL,
    hypothesis      TEXT,
    ic_mean         DECIMAL(8,6),
    ic_stats        JSONB,                             -- ⭐{ic_mean,ic_std,t_stat,ic_ir,ic_win_rate}
    status          VARCHAR(10) NOT NULL,              -- success/failed
    failure_node    VARCHAR(20),                       -- ⭐失败节点: G1-G8 | approved | entry
    failure_reason  JSONB,                             -- ⭐结构化: {"gate":"G3","ic_mean":0.008,"threshold":0.015}
    failure_mode    VARCHAR(30),                       -- ⭐失败模式: ic_insufficient/correlation_high/...
    spearman_max_existing DECIMAL(8,4),                -- ⭐与现有因子最大Spearman相关性
    source          VARCHAR(20),                       -- llm/gp/brute_force/manual
    run_id          UUID REFERENCES pipeline_runs(run_id) ON DELETE SET NULL,  -- ⭐关联pipeline_runs
    tags            TEXT[],                            -- ⭐标签数组: ['momentum','reversal']
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
COMMENT ON TABLE mining_knowledge IS '因子挖掘知识库(Sprint 1.18扩展)。记录成功/失败尝试，供Idea Agent读取避免重复';
COMMENT ON COLUMN mining_knowledge.factor_hash IS 'AST结构哈希，与gp_approval_queue.ast_hash一致，用于跨表去重';
COMMENT ON COLUMN mining_knowledge.failure_node IS '失败的Pipeline节点: G1/G2/.../G8 | approved | entry';
COMMENT ON COLUMN mining_knowledge.failure_mode IS 'AlphaAgent失败模式: ic_insufficient/correlation_high/neutralization_decay/hypothesis_invalid/coverage_low/turnover_high/stability_low/compute_fail';
CREATE INDEX idx_mining_knowledge_factor_hash ON mining_knowledge(factor_hash) WHERE factor_hash IS NOT NULL;
CREATE INDEX idx_mining_knowledge_failure_mode ON mining_knowledge(failure_mode) WHERE failure_mode IS NOT NULL;
CREATE INDEX idx_mining_knowledge_status_source ON mining_knowledge(status, source);
CREATE INDEX idx_mining_knowledge_run_id ON mining_knowledge(run_id) WHERE run_id IS NOT NULL;

-- ═══════════════════════════════════════════════════
-- 域11: AI闭环（3张表）— Phase 1
-- ═══════════════════════════════════════════════════

CREATE TABLE pipeline_run (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    round_number    INT NOT NULL,
    trigger_type    VARCHAR(20),                       -- weekly/event_driven/manual
    automation_level VARCHAR(20) DEFAULT 'semi',
    current_state   VARCHAR(30),
    diagnosis_result JSONB,
    factor_changes  JSONB,
    backtest_comparison JSONB,
    approval_status VARCHAR(20) DEFAULT 'pending',
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE agent_decision_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_run_id UUID REFERENCES pipeline_run(id),
    agent_name      VARCHAR(30) NOT NULL,
    decision_type   VARCHAR(30),
    reasoning       TEXT,
    action_taken    TEXT,
    input_json      JSONB,
    output_json     JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE approval_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_run_id UUID REFERENCES pipeline_run(id),
    approval_type   VARCHAR(30) NOT NULL,              -- factor_entry/strategy_deploy/param_change
    item_summary    TEXT,
    detail_json     JSONB,
    status          VARCHAR(20) DEFAULT 'pending',     -- pending/approved/rejected
    reviewer_note   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ
);

CREATE TABLE param_change_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    param_name      VARCHAR(50) NOT NULL,
    old_value       JSONB,
    new_value       JSONB NOT NULL,
    changed_by      VARCHAR(20),                       -- manual/ai/system
    reason          TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ═══════════════════════════════════════════════════
-- 域12: GP因子挖掘Pipeline（2张表）— Sprint 1.17
-- 注: pipeline_run(域11)是AI进化闭环运行记录
--     pipeline_runs(域12)是GP/BruteForce/LLM引擎运行记录，粒度不同
-- ═══════════════════════════════════════════════════

CREATE TABLE pipeline_runs (
    run_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engine_type     VARCHAR(20) NOT NULL,              -- gp/bruteforce/llm
    status          VARCHAR(20) NOT NULL DEFAULT 'running', -- running/completed/failed/cancelled
    config          JSONB NOT NULL,                    -- GPConfig/BruteForceConfig序列化
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    candidates_found INT NOT NULL DEFAULT 0,           -- 通过快速Gate的候选因子数
    gate_passed     INT NOT NULL DEFAULT 0,            -- 通过完整Gate G1-G8的因子数
    result_summary  JSONB,                             -- {best_fitness, best_expr, total_evaluated, ...}
    error_message   TEXT                               -- 失败时的错误信息
);
COMMENT ON TABLE pipeline_runs IS 'GP/BruteForce/LLM引擎每次运行的记录。engine_type区分三引擎';
COMMENT ON COLUMN pipeline_runs.candidates_found IS '通过快速Gate(G1-G4)的候选因子数';
COMMENT ON COLUMN pipeline_runs.gate_passed IS '通过完整Gate(G1-G8)的因子数';
COMMENT ON COLUMN pipeline_runs.result_summary IS 'JSONB摘要: {best_fitness, best_expr, total_evaluated, elapsed_seconds}';

CREATE INDEX idx_pipeline_runs_engine_type ON pipeline_runs(engine_type);
CREATE INDEX idx_pipeline_runs_status ON pipeline_runs(status);
CREATE INDEX idx_pipeline_runs_started_at ON pipeline_runs(started_at DESC);

CREATE TABLE gp_approval_queue (
    id              SERIAL PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES pipeline_runs(run_id),
    factor_name     VARCHAR(100) NOT NULL,             -- 建议名称，如 gp_ts_mean_cs_rank_20
    factor_expr     TEXT NOT NULL,                     -- DSL表达式字符串
    ast_hash        VARCHAR(64) NOT NULL,              -- AST结构哈希（去重用）
    gate_report     JSONB NOT NULL,                    -- G1-G8详细结果
    status          VARCHAR(20) NOT NULL DEFAULT 'pending', -- pending/approved/rejected/hold
    reviewer_notes  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at     TIMESTAMPTZ,
    reviewed_by     VARCHAR(50)                        -- 'user' | 'auto' | agent名称
);
COMMENT ON TABLE gp_approval_queue IS 'GP引擎产出因子的人工审批队列。通过完整Gate G1-G8后进入';
COMMENT ON COLUMN gp_approval_queue.ast_hash IS 'ExprNode.to_ast_hash()结果，用于跨队列去重';
COMMENT ON COLUMN gp_approval_queue.gate_report IS 'JSONB: {G1:{passed:bool,reason:str}, ..., G8:...}';
COMMENT ON COLUMN gp_approval_queue.status IS 'pending=待审批 approved=通过 rejected=拒绝 hold=搁置';

CREATE INDEX idx_gp_approval_queue_run_id ON gp_approval_queue(run_id);
CREATE INDEX idx_gp_approval_queue_status ON gp_approval_queue(status);
CREATE INDEX idx_gp_approval_queue_ast_hash ON gp_approval_queue(ast_hash);

-- ═══════════════════════════════════════════════════
-- Step 3-B 新增 (2026-04-09): stock_status_daily
-- 用途: 日期级股票状态 (解决 klines_daily.is_st 只存当前 vs 回测需要历史)
-- Contract: backend/app/data_fetcher/contracts.py::STOCK_STATUS_DAILY
-- ═══════════════════════════════════════════════════
CREATE TABLE stock_status_daily (
    code            VARCHAR(16) NOT NULL,              -- 带后缀, 如 600519.SH
    trade_date      DATE NOT NULL,
    is_st           BOOLEAN NOT NULL DEFAULT false,
    is_suspended    BOOLEAN NOT NULL DEFAULT false,
    is_new_stock    BOOLEAN NOT NULL DEFAULT false,    -- 上市60日内
    board           VARCHAR(20),                        -- main/gem/star/bj
    list_date       DATE,
    delist_date     DATE,
    PRIMARY KEY (code, trade_date)
);
CREATE INDEX idx_stock_status_daily_date ON stock_status_daily(trade_date);
COMMENT ON TABLE stock_status_daily IS 'Step 3-B: 日期级股票状态快照。回测必须按日期读, 不能用klines_daily当前状态';

-- ═══════════════════════════════════════════════════
-- Step 6-B 新增 (2026-04-09): minute_bars DDL确认
-- 用途: Baostock 5分钟K线 (2021-至今, 2537只A股)
-- Contract: backend/app/data_fetcher/contracts.py::MINUTE_BARS
-- 注: 表在Step 6-B前已存在 (代码动态建表), 此处DDL化确认正式schema
--     列名 ts_code → code (Step 6-B rename), code格式统一为带后缀
-- ═══════════════════════════════════════════════════
CREATE TABLE minute_bars (
    id              BIGSERIAL PRIMARY KEY,
    code            VARCHAR(16) NOT NULL,              -- 带后缀, 如 600519.SH (原 ts_code, Step 6-B 已 RENAME)
    trade_time      TIMESTAMP NOT NULL,                -- 分钟级时间戳
    trade_date      DATE NOT NULL,
    open            NUMERIC(12,4),
    high            NUMERIC(12,4),
    low             NUMERIC(12,4),
    close           NUMERIC(12,4),
    volume          BIGINT NOT NULL DEFAULT 0,         -- 手(全系统一致)
    amount          NUMERIC(18,2) NOT NULL DEFAULT 0,  -- 元
    adjustflag      VARCHAR(4) DEFAULT '3',            -- 1=后复权 2=前复权 3=不复权
    UNIQUE (code, trade_time)
);
CREATE INDEX idx_minute_bars_code_date ON minute_bars(code, trade_date);
CREATE INDEX idx_minute_bars_trade_date ON minute_bars(trade_date);
COMMENT ON TABLE minute_bars IS 'Step 6-B: Baostock 5min K线, 所有code统一带后缀';

-- ═══════════════════════════════════════════════════
-- 总计: 47张表（+2: stock_status_daily + minute_bars正式DDL化）
-- 旧版QUANTMIND_V2_DDL_COMPLETE.sql 已废弃，以本文件为准
-- ═══════════════════════════════════════════════════
