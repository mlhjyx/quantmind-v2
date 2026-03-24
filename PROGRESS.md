# Phase 0 Progress Tracker

> Last updated: 2026-03-25
> Current: Phase 1, Sprint 1.3b COMPLETED → Sprint 1.4 规划中
> Paper Trading: v1.1 Day 3/60, NAV=979,294
> Blockers: 无硬阻塞
> 宪法: V3.1 生效 (7铁律+按需spawn+因子审批链)

## Week 0: Data Feasibility Verification ✅ COMPLETED

### Day 1: Tushare API Field Verification ✅
- [x] Verify Tushare credit consumption (pull 1 month sample)
- [x] Check up_limit/down_limit fields in daily interface
- [x] Check ann_date field in fina_indicator interface
- [x] Check industry classification (industry_sw1) in stock_basic

### Day 2-3: Data Quality Validation ✅
- [x] Verify adj_factor correctness (spot check 3 stocks)
- [x] Verify daily_basic field completeness
- [x] Confirm industry classification coverage rate
- [x] Document findings and go/no-go decision → **GO**

## Week 1: Database + Core Data Pull ✅ COMPLETED

### Database Setup ✅
- [x] Execute DDL (43 tables from QUANTMIND_V2_DDL_FINAL.sql)
- [x] Pull symbols (5810 stocks including delisted: L+D+P statuses)
- [x] Board detection + price_limit mapping (main/gem/star/bse/ST)

### Data Fetcher Implementation ✅
- [x] `tushare_fetcher.py` — by-date pull strategy, retry logic, merge_daily_data
- [x] `data_loader.py` — upsert functions with FK filtering, connection reuse
- [x] `pull_full_data.py` — CLI with --table/--start/--end/--dry-run, checkpoint resume
- [x] `refresh_symbols.py` — full stock universe refresh script
- [x] `validate_data.sql` — 12-check verification script

### Core Data Pull ✅
- [x] klines_daily: 7,347,829 rows | 5,700 stocks | 1,501 dates | 2020-01-02→2026-03-19
- [x] daily_basic: 7,307,433 rows | 5,700 stocks | 1,503 dates | 2020-01-02→2026-03-19
- [x] index_daily: 4,509 rows | 3 indices | 1,503 dates | 2020-01-02→2026-03-19
- [x] Run validate_data.sql — all 12 checks passed
- [x] Git commit data fetcher code

### Fixes Applied (from quant/arch/qa review)
- Fixed: North Exchange (8xx) filtering in stk_limit
- Fixed: pct_chg → pct_change rename in index_daily
- Fixed: Code suffix stripping (000001.SZ → 000001)
- Fixed: FK pre-filtering with symbols cache
- Fixed: Float comparison for is_suspended detection
- Fixed: itertuples for 10x performance over iterrows
- Fixed: Connection reuse across upsert calls
- Fixed: Dynamic end date (today vs hardcoded)
- Fixed: Consecutive failure abort logic

## Week 2: Data Cross-Validation + adj_close工具 ✅ COMPLETED

### P0补齐（Data工程师审查结果）✅
- [x] adj_close计算工具函数 (`backend/app/services/price_utils.py`)
- [x] validate_data.sql补充: klines vs daily_basic每日对齐检查 (Check 13)
- [x] validate_data.sql补充: 退市股覆盖检查 (Check 14: D=320)
- [x] validate_data.sql补充: adj_factor NULL率按日期检查 (Check 15: 0 NULL)
- [x] validate_data.sql补充: total_mv数量级验证 (Check 16: 茅台18194亿✓)
- [x] validate_data.sql补充: adj_factor除权事件检测 (Check 17)

### 数据交叉验证 ✅
- [x] 3-stock手工比对: 600519/000001/300750 2025-03-14数据合理
- [x] adj_close除权事件验证: 茅台2023-2025共6次除权,ratio均为1.01-1.02(纯分红,合理)
- [x] klines vs daily_basic对齐: gap约100只(2-3%),系部分小盘股无daily_basic,正常
- [x] 行业分类覆盖率: industry_sw1 100%覆盖(5490/5490)

### Strategy决策记录
- 调仓频率: 双周频为默认，保留周频/月频可配置，Week 5做频率敏感性对比
- 风格暴露: BACKLOG，Week 5回测完成后做Barra分解
- 2021年压测: 回测年度分解中重点标注

## Week 3: Minimal Factor Set (6 factors) ✅ COMPLETED

### 因子引擎 ✅
- [x] 6 core factors: momentum_20, volatility_20, turnover_mean_20, amihud_20, bp_ratio, ln_market_cap
- [x] Preprocessing pipeline (MAD→fill→neutralize→zscore) — 严格按CLAUDE.md顺序
- [x] IC calculation pipeline (excess return vs CSI300) — Spearman rank IC
- [x] Batch computation (load_bulk_data一次加载 → 逐日预处理+写入)
- [x] Batch write (by-date, single transaction per day)
- [x] calc_factors.py脚本 (--date/--start/--end/--chunk-months)

### 验证通过 ✅
- [x] 单日因子分布: 6因子mean=0 std=1 ✓
- [x] IC测试(2025-03-10): ln_mcap=-0.15, vol=-0.14, mom=-0.11 (合理)
- [x] Bug修复: load_daily_data DISTINCT trade_date, index_code .SH suffix

### 全量计算 ✅
- [x] 6因子: 2020-07-01 → 2026-03-19 批量计算完成 (~3900万行, ~30min)

## Week 4: Signal + SimpleBacktester ✅ COMPLETED

### 信号引擎 ✅
- [x] SignalComposer (等权合成 + 因子方向调整)
- [x] PortfolioBuilder (Top-N选股 + 行业约束25% + 换手率约束50%)
- [x] get_rebalance_dates (双周频/周频/月频调仓日历)

### SimBroker ✅
- [x] can_trade() (涨跌停封板检测, CLAUDE.md规则1)
- [x] 整手约束 (floor(value/price/100)*100, CLAUDE.md规则2)
- [x] 资金T+1 (卖出回款当日可用)
- [x] 滑点模型 (固定bps, Phase 1切换volume-impact)
- [x] 成本模型 (佣金万1.5+印花税千0.5+过户费万0.1)

### SimpleBacktester ✅
- [x] 先卖后买调仓逻辑
- [x] 每日NAV跟踪
- [x] 换手率记录

### 绩效指标 ✅
- [x] 13项核心指标 (Sharpe/MDD/Calmar/Sortino/Beta/IR等)
- [x] Bootstrap Sharpe 95%CI (1000次采样)
- [x] 成本敏感性 (0.5x/1x/1.5x/2x)
- [x] 年度分解 + 月度热力图
- [x] 隔夜跳空统计
- [x] run_backtest.py脚本

### 端到端回测 ✅
- [x] 6因子基线: Sharpe=0.41, 年化4.88%, MDD=-28.11%

## Week 5: Credibility Rules + Report ✅ COMPLETED

### CLAUDE.md回测可信度规则全部实现 ✅
- [x] 规则1: 涨跌停封板检测 (can_trade in SimBroker)
- [x] 规则2: 整手约束 + 资金T+1 (SimBroker)
- [x] 规则3: 确定性测试 (test_factor_determinism.py — PASSED)
- [x] 规则4: Bootstrap Sharpe 95%CI (已实现并验证)
- [x] 规则5: 隔夜跳空统计 (已实现并验证)
- [x] 规则6: 成本敏感性分析 (已实现并验证)

### 回测报告必含指标 — 全部实现 ✅
- [x] Sharpe / MDD / Calmar / Sortino / Beta / IR
- [x] Bootstrap Sharpe CI
- [x] 成本敏感性 (0.5x/1x/1.5x/2x)
- [x] 隔夜跳空统计
- [x] 年度分解
- [x] 月度热力图
- [x] 胜率 + 盈亏比
- [x] 最大连续亏损天数
- [x] 年化换手率

## Week 6: Expand to 17 Factors ✅ COMPLETED

### 因子扩展 ✅
- [x] 新增11因子: momentum_5/10, reversal_5/10/20, volatility_60, volume_std_20, turnover_std_20, ep_ratio, price_volume_corr_20, high_low_range_20
- [x] northbound_pct 推迟到Phase 1 (需AKShare额外数据源)
- [x] 全量计算完成: 1.07亿行, 17因子, 1385交易日, 2020-07-01→2026-03-19
- [x] Bug修复: inf值过滤 (ep_ratio/bp_ratio除零产生inf, PostgreSQL NUMERIC不支持)

### 17因子 vs 6因子对比 ✅
| 指标 | 6因子 | 17因子 | 变化 |
|------|------|--------|------|
| 总收益 | 26.66% | 35.44% | +8.78% ✅ |
| 年化收益 | 4.88% | 6.30% | +1.42% ✅ |
| Sharpe | 0.41 | 0.45 | +0.04 ✅ |
| MDD | -28.11% | -29.97% | -1.86% |
| IR | 0.53 | 0.58 | +0.05 ✅ |
| 2021年 | -8.51% | +10.29% | +18.8% ✅ |
| 换手率 | 1.95x | 7.52x | +5.57x ⚠️ |

### 17因子回测详情 (2021-01-01 → 2025-12-31)
```
总收益:     35.44%
年化收益:    6.30%
Sharpe:     0.45 [-0.44, 1.37] (95% CI)
最大回撤:   -29.97%
Calmar:     0.21
Sortino:    0.56
Beta:       0.568
IR:         0.58
年化换手率:  7.52x
胜率:       47.8%
隔夜跳空:   -0.0466%

年度分解:
  2021: +10.29% (excess +16.51%, Sharpe 0.73, MDD -9.03%)
  2022: -14.49% (excess +6.78%,  Sharpe -0.95, MDD -20.85%)
  2023:  +2.52% (excess +14.27%, Sharpe 0.28, MDD -14.09%)
  2024: +10.51% (excess -5.69%,  Sharpe 0.55, MDD -21.05%)
  2025: +26.13% (excess +4.94%,  Sharpe 1.63, MDD -11.14%)

成本敏感性:
  0.5x → Sharpe 0.44 | 1.0x → 0.42 | 1.5x → 0.40 | 2.0x → 0.38
```

---

## Phase 0 完成总结

### 交付物
| 组件 | 文件 | 状态 |
|------|------|------|
| 数据拉取 | `tushare_fetcher.py`, `data_loader.py`, `pull_full_data.py` | ✅ |
| 数据验证 | `validate_data.sql` (17项检查) | ✅ |
| 复权价格 | `price_utils.py` | ✅ |
| 因子引擎 | `factor_engine.py` (17因子+预处理管道) | ✅ |
| 信号引擎 | `signal_engine.py` (等权合成+Top-N选股) | ✅ |
| 回测引擎 | `backtest_engine.py` (SimBroker+SimpleBacktester) | ✅ |
| 绩效指标 | `metrics.py` (13项+Bootstrap CI+成本敏感性) | ✅ |
| CLI脚本 | `calc_factors.py`, `run_backtest.py` | ✅ |
| 确定性测试 | `test_factor_determinism.py` | ✅ PASSED |

### 数据资产
| 表 | 行数 | 覆盖范围 |
|----|------|----------|
| klines_daily | 7,347,829 | 5,700股 × 1,501天 |
| daily_basic | 7,307,433 | 5,700股 × 1,503天 |
| index_daily | 4,509 | 3指数 × 1,503天 |
| factor_values | 107,679,192 | 5,694股 × 17因子 × 1,385天 |

### 采纳的团队建议汇总

| 来源 | 建议 | 决定 | 效果 |
|------|------|------|------|
| **Strategy** | 双周频调仓为默认 | ✅ 采纳 | 128个调仓日, 合理频率 |
| **Strategy** | 2021年回测重点标注 | ✅ 采纳 | 年度分解表已实现, 2021年标注 |
| **Strategy** | Week 5做Barra风格分解 | ⏳ 推迟Phase 1 | Phase 0先完成基线 |
| **Data** | adj_close工具函数必须补齐 | ✅ 采纳 | price_utils.py已实现 |
| **Data** | validate_data.sql补充5项检查 | ✅ 采纳 | Check 13-17全部通过 |
| **Quant** | 等权Top-N作为基线 | ✅ 采纳 | CLAUDE.md明确的策略 |
| **Arch** | 因子批量计算按月分片 | ✅ 采纳 | chunk-months=6, 避免OOM |
| **QA** | 确定性测试框架 | ✅ 采纳 | test_factor_determinism.py |
| **Factor** | 先6核心再扩展到18 | ✅ 采纳 | 6→17因子, 渐进式验证 |

### Phase 0结论
- **管道完整性**: 数据→因子→信号→回测→报告 全链路打通 ✅
- **绩效基线**: 年化6.3%, Sharpe 0.45 — 低于目标(15-25%, Sharpe 1.0-2.0)
- **关键发现**: Bootstrap CI跨越0, 统计上不显著; MDD(-30%)超标; 超额收益稳定(IR=0.58)
- **Phase 1方向**: AI因子挖掘 + IC加权(替换等权) + 风格控制(Beta偏高0.57)

---

## Team (Phase 0)

| Role | Scope | Status |
|------|-------|--------|
| **Team Lead** (Claude主线程) | 任务分配、进度跟踪、验收 | Completed |
| **quant** | 量化逻辑审查，一票否决权 | Completed |
| **arch** | Service层+回测引擎编码 | Completed |
| **qa** | 功能测试(API/因子/回测) | Completed |
| **data** | 数据管道全权(拉取/清洗/验证/备份) | Completed |
| **factor** | 因子研究(审查+新因子设计) | Completed |
| **strategy** | 策略研究(回测审查+策略优化) | Completed |

## Key Decisions Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-20 | Initial 6 factors, not 18 | Validate pipeline first |
| 2026-03-20 | SimpleBacktester, not Hybrid | Phase 0 is weekly rebalance only |
| 2026-03-20 | Decimal for money, float64+4dp for returns | Balance precision and performance |
| 2026-03-20 | 20 stocks @100万, 30 @200万+ | Control lot-size deviation |
| 2026-03-20 | Excess IC is gold standard | Consistent with CLAUDE.md |
| 2026-03-20 | T-day 17:00 start pull | Give Tushare 1 extra hour |
| 2026-03-20 | By-date pull (not by-stock) | ~5000 API calls for 5 years |
| 2026-03-20 | Industry merge: <30 stocks → nearest large industry | 110→48 categories |
| 2026-03-20 | Skip TimescaleDB Phase 0 | PG16 vs PG17 compatibility |
| 2026-03-20 | 双周频调仓为默认 | Strategy建议: 18因子中长周期居多 |
| 2026-03-20 | Week 5做Barra风格分解 | Strategy建议: 推迟到Phase 1 |
| 2026-03-20 | 2021年回测重点标注 | Strategy建议: 赛道极化年份 |
| 2026-03-20 | 17因子(非18) | northbound_pct需AKShare, Phase 1补 |
| 2026-03-20 | inf值过滤 | ep_ratio/bp_ratio除零产生inf |

---

## P1 Optimization Progress (2026-03-21)

### Route A: Parameter Sensitivity ✅ COMPLETED

18-config grid search (Top-N 20/30/50 × Freq biweekly/monthly × IndCap 20/25/30%).

**Key finding**: Monthly rebalance (avg Sharpe 1.243) >> Biweekly (avg 0.976).
Top-N and IndCap have minor impact within monthly configs.

**Locked config**: Top20 monthly IndCap=25%, 5因子等权, **无Beta对冲**（A股无做空工具）
- Sharpe ≈1.29 (unhedged), MDD ≈-32.9%, CI_lo=0.41
- Pre-trade hedge测试: Sharpe 1.01, CI_lo=0.04 — 三方讨论共识：对冲=减仓，去掉

### Route B: Paper Trading Pipeline ✅ COMPLETED

| 组件 | 文件 | 状态 |
|------|------|------|
| Beta对冲引擎 | `backend/engines/beta_hedge.py` | ✅ |
| 状态化Broker | `backend/engines/paper_broker.py` | ✅ |
| 健康预检 | `scripts/health_check.py` | ✅ |
| 每日管道 | `scripts/run_paper_trading.py` | ✅ |
| 策略初始化 | `scripts/setup_paper_trading.py` | ✅ 已运行 |
| 状态查询CLI | `scripts/paper_trading_status.py` | ✅ |
| 通知服务 | `backend/services/notification_service.py` | ✅ |
| Crontab安装 | `scripts/install_crontab.sh` | ✅ |

**验证**: 2026-03-19首次建仓20只，NAV=987,251，6张表写入全部正确。

### Route C: Financial Quality Factors ✅ COMPLETED

| 任务 | 状态 |
|------|------|
| financial_indicators表创建 | ✅ |
| Tushare fina_indicator数据拉取 | ✅ 408,984行 |
| 因子设计 (roe_change_q, revenue_accel, accrual_anomaly) | ✅ |
| IC测试 | ✅ revenue_accel IC=2.37%通过Gate, 其余未通过 |
| 6因子组合回测 | ✅ 加入revenue_accel后Sharpe未提升(1.28→1.28), **不纳入基线** |

### Sprint 0.1: P0-Bug修复 ✅ COMPLETED

**6-Agent独立审查→quant一票否决→全面修复**

| Bug | 修复 | 状态 |
|-----|------|------|
| R1 执行价格(T日open→T+1 open) | 两阶段pipeline | ✅ 已修复 |
| R2 Beta方法(post-hoc vs pre-trade) | pre-trade回测确认Sharpe=1.01, 三方共识去掉对冲 | ✅ 已修复(移除) |
| R3 Cash从ratio反推 | 直接存cash列到performance_series | ✅ 已修复 |
| R4 调仓日SQL | 去掉 trade_date<=限制 | ✅ 已修复 |
| R7 并发保护 | pg_advisory_lock | ✅ 已修复 |
| Beta对冲移除 | 改为纯监控指标 | ✅ 已修复 |
| L1/L2熔断机制 | risk评审→方案确定 | ⚠️ 编码未完成，遗留到Sprint 1.4 |

---

## Sprint 1.1: 参数敏感性 + Paper Trading基础设施 ✅ COMPLETED (2026-03-21)

### 参数敏感性 (Route A) ✅
- 18-config grid search (Top-N 20/30/50 × Freq biweekly/monthly × IndCap 20/25/30%)
- **关键发现**: 月度调仓(avg Sharpe 1.243) >> 双周频(avg 0.976)
- **锁定配置**: Top20 monthly IndCap=25%, 5因子等权, 无Beta对冲
- Sharpe ≈1.29(unhedged), MDD ≈-32.9%
- 波动率自适应阈值: clip(0.5, 2.0)

### Paper Trading Pipeline (Route B) ✅
- paper_broker.py / run_paper_trading.py / health_check.py / setup_paper_trading.py
- 首次建仓: 2026-03-19, 20只, NAV=987,251

### 财务质量因子 (Route C) ✅
- roe_change_q/revenue_accel/accrual_anomaly → revenue_accel IC=2.37%通过但组合未提升

### Bug修复 ✅
- 持仓膨胀bug (LL-002), MDD peak初始化 (LL-003), 时序不一致 (LL-004/005)

---

## Sprint 1.2: 多策略探索 + 配置优化 ✅ COMPLETED (2026-03-22)

### 5候选策略全部失败
- 候选2 红利低波: corr=0.778, 无分散价值
- 候选4 大盘低波: OOS Sharpe=-0.11
- 候选5 中期反转: corr=0.627, 不够正交
- **教训**: 因子正交≠选股正交(LL-009), Proxy≠正式回测(LL-011)

### 配置优化 ✅
- Top20→Top15: 整手误差8%→3%, Sharpe无差异 → KEEP
- L1延迟方案C: L1触发时月度调仓延迟不跳过 → KEEP
- days_gap改交易日: 修复国庆/五一误杀 → KEEP

### v1.1确立
- 5因子等权 + Top15 + 月度 + 行业25%
- 基线Sharpe=1.037(Mac), MDD=-39.7%

---

## Sprint 1.2a: 统计工具 ✅ COMPLETED (2026-03-22)

- DSR(Deflated Sharpe Ratio): DSR=0.591("可疑") → engines/dsr.py
- BH-FDR多重检验校正 → engines/config_guard.py
- 波动率自适应熔断阈值 → risk_control_service.py

---

## Sprint 1.3: 因子挖掘深度 ✅ COMPLETED (2026-03-22~23)

### alpha_miner因子挖掘 (Batch 1~8)
- 67个因子测试(FACTOR_TEST_REGISTRY.md)
- **亮点**: mf_divergence IC=9.1%(全项目最强), price_level IC=8.42%
- **陷阱**: big_small_consensus原始IC=12.74%中性化后-1.0%(虚假alpha, LL-014)
- PEAD earnings_surprise: IC=5.34%, corr<0.11最干净新维度

### moneyflow数据拉取 ✅
- moneyflow_daily: 614万行入库

---

## Sprint 1.3a: v1.2升级验证 ✅ COMPLETED (2026-03-23)

- v1.2(+mf_divergence) paired bootstrap: p=0.387, 增量不显著 → NOT JUSTIFIED
- **决策**: v1.2升级取消, v1.1维持

---

## Sprint 1.3b: 线性合成全面对比 + 收尾 ✅ COMPLETED (2026-03-23)

### 9种线性合成方法 vs 等权基线
| 方法 | 最佳Sharpe | vs 基线1.035 | 结论 |
|------|-----------|-------------|------|
| 最大化ICIR加权 | 0.992 | 劣 | Reverted |
| 最大化IC加权 | 0.929 | 劣 | Reverted |
| ICIR简单加权 | 0.912 | 劣 | Reverted |
| 收益率加权 | 0.861 | 劣 | Reverted |
| 因子择时(5F) | 0.876 | 劣 | Reverted |
| 因子择时+PEAD(6F) | 0.679 | 最差 | Reverted |
| 半衰期加权 | 0.838 | 劣 | Reverted |
| BP子维度融合 | 0.820 | 劣 | Reverted |
| 分层排序A/B/C | 0.666~0.820 | 劣 | Reverted |

**结论**: 等权=线性全局最优(LL-018), 突破需要非线性(LightGBM)

### 其他完成项
- KBAR 15因子: 15/20 PASS, 大部分与vol/rev冗余, 3个独立候选入Reserve
- Deprecated 5因子标记(momentum_20/volatility_60/turnover_std_20/high_low_range_20/volume_std_20)
- 封板补单机制实现
- PEAD加入等权组合验证→Sharpe-0.085, 确认等权天花板(LL-017)
- v1.1配置锁死, 60天Paper Trading启动(2026-03-23)

---

## Windows迁移 ✅ COMPLETED (2026-03-24~25)

### 完成项
- [x] Python 3.11.9 安装
- [x] PostgreSQL 16 (D:\pgsql, D:\pgdata16, 用户xin)
- [x] Redis Windows服务
- [x] Python虚拟环境 + 依赖安装
- [x] 数据库恢复(2.8GB dump, 1.6亿行, 46张表)
- [x] 行数校验: 160,299,461行全部匹配
- [x] Paper Trading 3/23首次运行(Windows) + 3/24补跑
- [x] Task Scheduler注册: QuantMind_DailySignal(16:30) + QuantMind_DailyExecute(09:00)
- [x] macOS残留清理(278个._文件 + 12个.DS_Store)
- [x] .gitignore重建
- [x] CLAUDE.md环境描述更新
- [x] Python脚本UTF-8编码修复

### Sharpe差异诊断
- Windows: 1.019 vs Mac: 1.037 (差0.018)
- **根因**: dump中reversal_20因子在2021-01-29(第一个月度调仓日)缺失, 该日用4因子等权而非5因子
- **决策**: 接受1.019为Windows新基线, 毕业标准调整为Sharpe≥0.71

---

## Paper Trading v1.1 运行状态

- **启动**: 2026-03-23
- **当前**: Day 3 / 60天
- **NAV**: 979,294 (+2.15% on Day 2)
- **持仓**: 15只
- **自动化**: Task Scheduler (16:30信号 + 09:00执行)
- **毕业标准**: Sharpe≥0.71, MDD<35%, 滑点偏差<50%

---

## 当前团队状态 (2026-03-25)

| 角色 | 状态 | 待办 |
|------|------|------|
| Team Lead | 活跃 | Sprint 1.3b复盘 + 1.4规划 |
| quant | 待命 | — |
| arch | 待命 | Deprecated因子停止计算 |
| data | 待命 | 3/25 Task Scheduler首次自动运行验证 |
| qa | 待命 | Windows环境全量pytest |
| factor | 待命 | — |
| strategy | 待命 | — |
| risk | 待命 | **L1/L2熔断编码(逾期)** |
| alpha_miner | 待命 | 目标转型→LightGBM特征池 |
| frontend | 未启用 | Phase 1B |
| ml | 未启用 | Phase 1C |

## Blockers
- 无硬阻塞
- L1/L2熔断编码逾期(从Sprint 0.1遗留), 优先级P1
- accrual_anomaly因子blocked(需cash_flow表), 优先级低
