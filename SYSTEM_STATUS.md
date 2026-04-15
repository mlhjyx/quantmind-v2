# QuantMind V2 系统全面梳理报告

> **目的**: 重构前系统真实状态完整记录，供架构顾问审阅
> **日期**: 2026-04-09 (初版) + Step 6-H 更新 (2026-04-10) + Phase 2.1 更新 (2026-04-11) + Phase 2.4 更新 (2026-04-12) + PT配置更新 CORE3+dv_ttm (2026-04-12)
> **基于**: 实际查询数据，非设计文档描述

---

## §0.2 Phase 2.4 Research Exploration (2026-04-12)

**状态: 完成 — 5个独立改善方向发现, 最佳Sharpe=1.04**

### 核心发现 (36个实验, 22个超基线)
| Rank | Method | Sharpe | MDD | vs Base(0.67) |
|------|--------|--------|-----|---------------|
| 1 | CORE3+RSQR_20+dv_ttm | **1.0417** | -26.11% | +56.6% |
| 2 | Top-40 (CORE5+SN) | 0.9097 | -31.04% | +36.7% |
| 3 | CORE5+dv_ttm | 0.8660 | -19.53% | +30.2% |
| 4 | Quarterly rebalance | 0.8302 | -25.97% | +24.8% |
| 5 | SN b=0.30 | 0.7895 | -47.24% | +18.7% |

### 关键结论
1. **Alpha 100%来自微盘** — 非微盘区间Sharpe≈0, universe filter方向关闭
2. **dv_ttm(股息率)是关键增量因子** — 加入即+30% Sharpe, 大幅降MDD
3. **CORE3+RSQR+dv首次突破Sharpe 1.0** — 去amihud/reversal, 换RSQR/dv_ttm
4. **Top-20次优** — Top-25~40分散更好(Sharpe +25-37%)
5. **季度调仓优于月度** — 减少交易成本, Sharpe +25%
6. **Composite IC=0.113, IR=1.15, t=44.65** — 信号极强且稳定

### 已关闭方向
- Universe filter替代SN → 失败(alpha全在微盘)
- LambdaRank作为因子 → 信号冲突(-27%)
- RSQR_20/QTLU_20单独加入 → 零增量

### WF验证结果 (2026-04-12)
| Config | OOS Sharpe | OOS MDD | Overfit | Stability | Verdict |
|--------|-----------|---------|---------|-----------|---------|
| BASELINE CORE5+SN | 0.6521 | -30.23% | - | - | - |
| **CORE3+dv+SN Top20 Monthly** | **0.8659** | **-13.91%** | **0.84** | **STABLE** | **PASS ✅** |
| CORE5+dv+SN Top20 Monthly | 0.6992 | -13.26% | 0.80 | STABLE | MARGINAL ⚠️ |
| CORE3+dv+SN Top25 Quarterly | 0.7034 | -17.18% | 0.01 | UNSTABLE | MARGINAL ⚠️ |

**P0修正**: RSQR_20有害(-0.089 Sharpe), 移除。最终配置: CORE3+dv_ttm (4因子)。

### PT配置更新 (2026-04-12)
- pt_live.yaml: CORE5→CORE3+dv_ttm (4因子+方向)
- signal_engine.py: PAPER_TRADING_CONFIG 更新
- parquet_cache.py: CORE_FACTORS 更新
- .env: PT_SIZE_NEUTRAL_BETA=0.50 新增
- 验证: config_guard双向通过, dv_ttm DB 11.7M行/neutral_value 11.6M有效

### 下一步
1. ~~WF验证~~ ✅ PASS
2. ~~PT配置更新~~ ✅ 完成
3. Phase 3: 自动化(Rolling WF + IC监控)
4. Phase 4: PT重启(health_check + dry-run)

详见: `docs/research-kb/findings/phase24-exploration-results.md`

---

## §0.3 Phase 2.3 前置：策略市值暴露诊断 (2026-04-11)

**状态: 完成**

### 核心发现
| 指标 | 无SN | SN b=0.50 |
|------|------|-----------|
| Top-20 中位数市值 | 32.3亿 (微盘) | 3,593亿 (大盘) |
| 微盘(<100亿)占比 | 91.5% | 42.0% |
| 大盘(>500亿)占比 | 1.5% | 58.0% |
| 小中盘(100-500亿)占比 | 7.0% | **0.0%** |

### 结论
1. **无SN = 纯微盘策略** (91.5%<100亿), SN b=0.50 = barbell结构 (58%大盘+42%微盘, 0%中间)
2. **CSI300是最差基准** (corr=0.077), 全A等权最匹配 (corr=0.334)
3. **IC对基准不敏感** — Spearman Rank IC是基准无关的(数学证明), 历史IC研究结论不受影响
4. **因子是真alpha但微盘放大IC 3-4倍** — 所有因子在中盘/大盘仍显著(t>2.5)
5. **amihud在中盘IC≈0** (0.007, t=3.0勉强) — 如收窄universe到中盘需考虑替换
6. **bp_ratio最稳健** — 跨市值衰减最小(-58%)
7. **SN过度矫正** — 从P25%直接推到P99.8%, 应考虑universe filter替代

### 数据质量修正
- `models/astock.py:322` 注释"万元"已修正为"元" (DataPipeline已转换)

### 后续建议
- 收窄universe到中盘(100-500亿) — 所有因子中盘IC显著
- SN beta如保留应降到0.15-0.30, 或改用universe filter
- 基准改用全A等权

详见: `docs/research-kb/findings/phase23-mcap-diagnostic.md`

---

## §0.4 Phase 2.1 E2E Fusion 结果 (2026-04-11, commit f47349b)

**状态: NO-GO**

### 实验结果
| 实验 | 因子数 | OOS IC | ICIR | 判定 |
|------|--------|--------|------|------|
| Exp-C (CORE5) | 5 | **0.0912** | 1.06 | 最佳 |
| Exp-A (+QTLU+RSQR) | 7 | 0.0912 | 1.06 | =Exp-C, 零增量 |
| Exp-B (+Tier2+NB) | 16 | 0.0687 | 0.74 | 比CORE5差25% |

- 完美预测上界: Sharpe=3.02 (GO gate), MVO=等权(完美预测下无差异)
- Layer 2 PortfolioNetwork: val_sharpe=1.26, 实盘Sharpe=-0.99 (sim-to-real gap 282%)
- 60月LightGBM窗口比24月提升36% (IC 0.067→0.0912, 唯一有效改进)

### 新增因子 (factor_values)
7个因子已入库(12yr, 100% neutralized): QTLU_20, RSQR_20, high_vol_price_ratio_20, IMAX_20, IMIN_20, CORD_20, RESI_20

### 新增引擎
- `backend/engines/portfolio_network.py`: PortfolioMLP + PortfolioLayer + sharpe_loss (已测试, 但实盘无效)

### 结论
- IC天花板≈0.09, CORE5最优, 更多因子=更多噪声
- 可微分Sharpe Loss在A股不可行 (真实交易成本不可微分)
- 瓶颈100%在预测质量, 非portfolio构建
- Phase 2.2 Gate验证: NO-GO — 6方法全败(LambdaRank+SN=0.56最佳, IC加权=0.27, MVO=0.26, 均<基线0.62)
- 下一步: Phase 3 自动化(因子生命周期监控+Rolling WF)

---

## §0.5 PT 重启记录 (Step 6-C, 2026-04-09 17:43)

### PT 重启信息
- **重启时间**: 2026-04-09 17:43 (Step 6-C 冒烟测试通过后)
- **新引擎版本**: `c83c72c` (Step 6-B commit) + Step 6-C 6 个 runtime bug 修复
- **配置文件**: `configs/pt_live.yaml` (5 因子等权 Top-20 月度, 排除 BJ)
- **毕业评估窗口**: 从 2026-04-09 重新计算 60 个交易日
- **老 PT 状态**: 2026-03-23~2026-04-08 (12 个交易日, NAV ≈ ¥989K), **已作废** (因 BJ 股偏差 + 老基线代码)

### Step 6-C 冒烟测试结果
| # | 项目 | 结果 |
|---|------|------|
| 1 | DataPipeline (Tushare → 带后缀 → 入库) | ✅ PASS (2026-04-08/09, 5490+5491 行) |
| 2 | stock_status_daily 验证 | ✅ PASS (发现并修复 board 推断 bug) |
| 3 | 因子计算 compute_daily_factors | ✅ PASS (24 因子 × 5491 股 = 131784 行) |
| 4 | 信号生成 SignalService | ✅ PASS (20 只, 0 ST/BJ) |
| 5 | regression_test 5yr | ✅ PASS (Sharpe=0.6095, max_diff=0, 80s) |
| 6 | pytest 核心重构测试 | ✅ PASS (Step 5 新增 44/44, legacy 4 失败非回归) |
| 7 | Servy 服务 + FastAPI health | ✅ PASS (all_pass=true, PG/Redis/Celery OK) |
| 8 | config_guard 三源对齐 | ✅ PASS (PAPER_TRADING_CONFIG + pt_live.yaml + backtest_12yr.yaml) |

### Step 6-C 发现并修复的 runtime bug
1. **scripts/run_paper_trading.py:189** — `SignalService.generate_signals()` 缺少 `config` 参数 (Step 2/6-A 遗留)
2. **scripts/run_paper_trading.py:174,282** — `check_circuit_breaker_sync()` 参数名错误 (`trade_date` → `exec_date + initial_capital`)
3. **scripts/run_paper_trading.py:77** — `scheduler_task_log` INSERT 缺 `schedule_time` NOT NULL 列
4. **backend/app/services/pt_qmt_state.py:48** — `nav / prev_nav` 混合 float/Decimal 类型错误
5. **scripts/run_backtest.py::load_universe** — 声称排除 ST/BJ/新股但实际只过滤 `volume>0`, **BJ 股全部未过滤** (Step 6-C 核心 fix, 让 PT 产出真实非 BJ 信号)
6. **backend/tests/test_can_trade_board.py** — import 旧 `backend.engines.backtest_engine._infer_price_limit` (Step 4-A 遗留)

### Task Scheduler 状态
14/16 任务已 Enabled (Ready), 2 维持 Disabled (QM-SmokeTest, QuantMind_DailyExecuteAfterData — 暂停前本就 Disabled)。

### CeleryBeat 状态
已启动 (Running), 调度: `gp-weekly-mining` (周日 22:00) + `pms-daily-check` (工作日 14:30)。重启时 PMS 发现 15 只持仓但无当日实时价格, 安全 no-op。

### 首次信号生成 (2026-04-09, 非 dry_run)
| 指标 | 值 |
|------|-----|
| 目标持仓 | 20 只 |
| BJ 股数 | **0** (新 universe 过滤生效) |
| 行业集中度 | 专用机械 28.9% (> 25% P1 告警, 因 industry_cap=1.0 无约束) |
| 持仓重合度 vs 老 17 只 | 6/17 = 35% (6 只 688xxx 保留, 10 只 920xxx BJ 强制清仓, 1 只自然退出) |
| Beta vs CSI300 | 0.0 (历史数据不足) |
| is_rebalance | False (下次调仓在月末) |
| rebalance 首日预期换手 | ~70% (几乎全新组合, 由 BJ 强制清仓驱动) |

**kept (6 科创板)**: 688057 / 688121 / 688132 / 688211 / 688570 / 688606
**forced exit (10 BJ)**: 920175 / 920212 / 920245 / 920519 / 920608 / 920701 / 920703 / 920807 / 920819 / 920950
**new entries (14)**: 000012 / 000050 / 000725 / 002598 / 300822 / 301151 / 301296 / 301383 / 301581 / 688075 / 688303 / 688420 / 688739 / 688755

---

## §0.6 Step 6-H 完成 + SN b=0.50 激活 (2026-04-10)

### Step 6-D~H 研究成果总结
| Step | 主要发现 |
|------|---------|
| 6-D | 12年首次真跑 Sharpe=0.5309 (非0.6095), WF 5-fold OOS chain-link=0.6336, FF3 Alpha=+18.98%/年 |
| 6-E | IC口径统一(ic_calculator+铁律19), Alpha衰减半衰期~6月, Regime线性检测5指标全p>0.05 |
| 6-F | 因子替换无效(p=0.92), Size-neutral有效, 噪声鲁棒性21因子全PASS(retention≥0.59@20%) |
| 6-G | Vol-targeting/DD-aware/组合Modifier全无效, Partial SN是唯一有效Modifier |
| 6-H | SN inner Sharpe=0.68/MDD=-39.35%, WF OOS=0.6521, Regime动态beta无效, LightGBM 17因子Sharpe=0.09 |

### 当前基线 (Step 6-H 后)
| 指标 | Base (12yr) | SN b=0.50 inner | SN WF OOS |
|------|-------------|-----------------|-----------|
| Sharpe | 0.5309 | **0.68** | 0.6521 |
| MDD | -56.37% | **-39.35%** | -30.23% |
| 年化 | 13.06% | — | — |
| FF3 Alpha | +18.98%/年 (t=2.90) | — | — |

### PT 状态更新
- **状态**: ⛔ **已暂停+已清仓 (2026-04-10)**
- **暂停原因**:
  1. **P0 SN config 未生效**: `PAPER_TRADING_CONFIG.size_neutral_beta=0.0` (关闭), `configs/pt_live.yaml` 的 `0.50` 被 PT 忽略。PT 从 4/9 起实际运行 b=0.0 (无 SN)。
  2. CeleryBeat 已恢复, 但审计修复未完成
  3. 框架升级 (Qlib 调研) 未开始
- **4/9~4/10 PT 数据**: 无效 (b=0.0 配置错误, 非预期的 SN b=0.50)
- **旧持仓**: 17 只 (7 SH/科创 + 10 BJ 遗留), 需手动在 QMT 客户端清仓
- **已执行停止操作**:
  - Servy: QMTData=Stopped
  - Task Scheduler: 8 个 PT 任务已 Disabled (DailyExecute/Signal/Moneyflow/Reconciliation/CancelStaleOrders/IntradayMonitor/MiniQMT_AutoStart/PTWatchdog)
  - CeleryBeat: 保持运行 (PMS 为重启做准备)

### PT 重启硬门槛 (全部满足才能重启)
- [ ] P0 SN config 修复 + 验证运行时 `PAPER_TRADING_CONFIG.size_neutral_beta == 0.50`
- [ ] CeleryBeat 运行 + PMS 链路端到端验证
- [ ] 审计 CRITICAL 项全部修复或验证为误报
- [ ] IC 时间对齐验证脚本通过
- [ ] 冒烟测试 8 项全部 PASS
- [ ] Qlib 调研完成 + 路线决策
- [x] 至少 1 个新信号维度 IC 评估完成 (Phase 1.2: Alpha158六因子6/6 PASS + 行业动量2/2 + 北向V2 15因子 + PEAD-SUE + SW1中性化迁移53因子, 2026-04-11)
- [ ] QMT 清仓确认 (持仓=0, 无挂单)

---

## §0 重构完成状态 (Step 6-B 追加, 2026-04-09)

本报告原为 Step 0 开始前的 pre-refactor 快照。Step 0→6-B 重构完成后, 以下关键状态发生变化:

### 核心指标变化
| 维度 | 重构前 | 重构后 (Step 6-B) |
|------|-------|-----------------|
| 基线 Sharpe | 0.94 (5年 Phase 1 加固) | **5yr 0.6095 / 12yr 0.5309** — Step 6-D 发现之前把5yr误写成12yr. 5yr基线`cache/baseline/metrics_5yr.json` + `regression_test.py` (max_diff=0), 12yr基线`cache/baseline/metrics_12yr.json` (2026-04-09首跑) |
| 基线 MDD | -40.77% | 5yr -50.75% / 12yr **-56.37%** |
| run_paper_trading.py | 1734 行单体 | 345 行编排器 + 4 Service |
| backtest_engine.py | 单文件 >3000 行 | backend/engines/backtest/ 8 模块 |
| 测试数 | 2051 | 2115 (Step 5 +48) |
| DB code 格式 | 36% 带后缀/64% 无后缀混合 | **全表带后缀统一** (Step 1 + Step 6-B) |
| minute_bars 列名 | ts_code | **code** (Step 6-B RENAME) |
| minute_bars code 格式 | 全部无后缀 | **全部带后缀** (Step 6-B UPDATE) |
| 数据入库路径 | 多处直接 INSERT | DataPipeline.ingest() 唯一入口 (铁律 17) |
| 信号路径 | PT/回测 2 套 | SignalComposer 唯一路径 (铁律 16) |
| 策略配置 | 硬编码 | YAML 驱动 (configs/pt_live.yaml / backtest_12yr.yaml) |
| 12 年回测 | OOM 无法运行 | **328 秒跑通** (12yr full in-sample, Step 6-D 首次真跑 `build_12yr_baseline.py`. Step 5 声称的 80 秒 "12年跑通" 实为 5yr regression) |
| 回测可复现 | 无配置指纹 | (config_yaml_hash, git_commit) 进 DB (铁律 15) |

### §9 问题清单状态更新 (以下问题已在 Step 0→6-B 中解决)

**🔴 致命问题 → 已解决**
- ✅ F1 code 格式混乱 → Step 1 + Step 6-B 统一带后缀
- ✅ F2 DataFeed.from_database() 不可用 → Step 3-A 修复
- ✅ F3 PT/回测两条信号链路 → Step 2 统一 SignalComposer

**🟡 高优先级 → 已解决**
- ✅ H1 ST 标记用当前快照 → Step 3-B stock_status_daily 日期级
- ✅ H2 standardize_units 启发式猜测 → Step 3-A DataContract 显式单位
- ✅ H5 ST 过滤集合级 → Step 3-B 日期级
- ✅ H6 因子引擎 DB IO 违反 Engine 纯计算 → Step 4-A 引擎只消费 DataFeed
- ✅ H7 run_paper_trading.py 1734 行单体 → Step 6-A 拆分 345 行 + 4 Service

**🟠 中优先级 → 部分解决**
- ✅ M1 minute_bars ts_code → Step 6-B RENAME COLUMN + 带后缀
- ✅ M4 缓存基于 2020-2025 → Step 5 新 Parquet 缓存覆盖 12 年

### §9 问题清单状态更新 (2026-04-10 遗留清理)

**🔴 致命 → 状态变更**
- ✅ F4 CeleryBeat → 实际已在运行 (调查确认 Running 状态)

**🟡 高优先级 → 已解决 (2026-04-10)**
- ✅ H3 两个 Tushare 客户端 → tushare_fetcher.py 删除(0引用), tushare_client.py 删除(1引用→改到 tushare_api)
- ✅ H8 两个备份任务重复 → 确认 QM-DailyBackup 和 QuantMind_DailyBackup 完全相同(同脚本/同时间/双双失败), 建议 disable QuantMind_DailyBackup

**🟡 高优先级 → 仍然开放**
- ⬜ H4 financial_indicators upsert 只更新 3/16 字段

**🟠 中优先级 → 已解决 (2026-04-10)**
- ✅ M6 两个同名 notification_service.py → backend/services/ 版本已确认 0 引用, 标记 DEPRECATED

**🟠 中优先级 → 仍然开放**
- ⬜ M2 退市检测 hardcoded 20 天
- ⬜ M3 slippage volume 单位脆弱
- ⬜ M5 DEV_SCHEDULER.md 与实际偏离
- ⬜ M7 24 张空表

**其他修复 (2026-04-10 遗留清理)**
- ✅ P0: PT Size-Neutral b=0.50 config 修复 (config.py + signal_engine.py + .env)
- ✅ IC 时间对齐验证脚本 5/5 PASS (scripts/research/verify_ic_alignment.py)
- ✅ db.py 连接计数器泄漏修复 (_TrackedConnection 包装器)
- ✅ pms.py 3 个 async def → def (阻塞 IO 不可用 async)
- ✅ DDL 单位注释 12 处修正 (万元/千元 → 元, DataPipeline 已转换)
- ✅ 硬编码凭证清理 6 文件 (统一用 get_sync_conn)
- ✅ ic_calculator.py 死代码删除 (exit_p 重复赋值)

**铁律17 INSERT 违规扫描 (Part 4, 2026-04-10)**
- 生产路径: 65 处 INSERT (6 CRITICAL: fetch_base_data.py 直接写 Contract 表)
- 研究脚本: 5 处 (pull_historical_data.py)
- 归档/测试: 49 处 (可忽略)
- Engine 层 DB 写入违规: 12 处 (factor_engine/paper_broker/factor_profiler 等)
- Engine 层 DB 读取违规: 20 文件
- 详细清单见本次 commit message 或 git log

**重构历史详见**: `docs/QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md §第四部分`

下方 §1-§14 保留为 Step 0 开始前的 pre-refactor 原始快照, 作为重构前/后对比的基准。

---

## §1 系统环境

### 硬件
| 项目 | 值 |
|------|-----|
| OS | Windows 11 Pro 10.0.26200 |
| CPU | AMD Ryzen 9 9900X3D, 12C/24T @ 4400MHz |
| RAM | 31.1 GB DDR5 (当前可用16.7GB, 使用46%) |
| GPU | NVIDIA RTX 5070, 12GB VRAM, 驱动595.79 |
| 主板 | Gigabyte B850M AORUS PRO WIFI7 |

### 磁盘
| 盘符 | 总量 | 已用 | 剩余 | 用途 |
|------|------|------|------|------|
| C: | 250GB | 165GB (66%) | 85GB | OS + 软件 |
| D: | 1000GB | 147GB (15%) | 853GB | 项目 + PG数据 |
| E: | 657GB | 15GB (2%) | 642GB | 备用 |

### 软件版本
| 组件 | 版本 |
|------|------|
| Python | 3.11.9 |
| FastAPI | 0.135.2 |
| Celery | 5.6.3 |
| Redis | 5.0.14.1 (server) / 7.4.0 (py client) |
| PostgreSQL | 16.8 (社区版) |
| TimescaleDB | 2.26.0 |
| pandas | 2.3.3 |
| numpy | 2.4.3 |
| PyTorch | 2.11.0+cu128 |
| Tushare | 1.4.29 |
| SQLAlchemy | 2.0.48 |
| psycopg2 | 2.9.11 |
| structlog | 25.5.0 |
| ruff | 0.15.7 |
| Servy | 7.6.0 |
| Node.js | (前端构建用) |

### 服务状态
| 服务名 | 状态 | 说明 |
|--------|------|------|
| QuantMind-FastAPI | ✅ Running | uvicorn --workers 2, port 8000 |
| QuantMind-Celery | ✅ Running | celery worker --pool=solo |
| QuantMind-CeleryBeat | ✅ Running | 定时调度器 (PMS 14:30 + GP 周日22:00), 自04-03 Servy迁移后持续运行 |
| QuantMind-QMTData | 🔴 **Stopped** | PT暂停期间已停止 (2026-04-10) |
| Redis | ✅ Running | port 6379, uptime 2天 |
| PostgreSQL | ✅ Running | port 5432 |

> ℹ️ CeleryBeat 自04-03 Servy迁移后持续运行。QMTData 因PT暂停已停止。

---

## §2 数据库

### 2.1 表清单（62张表，38张有数据）

**核心行情表（全部2014起）**
| 表 | 行数 | 时间范围 | 备注 |
|----|------|----------|------|
| klines_daily | 11,699,794 | 2014-01-02 ~ 2026-04-08 | TimescaleDB hypertable |
| daily_basic | 11,604,975 | 2014-01-02 ~ 2026-04-08 | |
| moneyflow_daily | 11,375,743 | 2014-01-02 ~ 2026-04-08 | 2020年已补 ✅ |
| index_daily | 55,657 | 2014-01-02 ~ 2026-04-08 | |
| northbound_holdings | 5,542,237 | 2017-01-03 ~ 2026-04-02 | 2019年238天 ✅ |
| minute_bars | 139,303,467 | 2021-01-04 ~ 2025-12-31 | 列名ts_code(非code) |
| symbols | 11,631 | - | 含5821只历史退市股 |

**因子表**
| 表 | 行数 | 时间范围 | 备注 |
|----|------|----------|------|
| factor_values | 501,360,926 | 2014-01-02 ~ 2026-04-07 | TimescaleDB hypertable, ~53GB |
| factor_ic_history | 57,711 | 2021-01-04 ~ 2026-04-06 | |
| factor_registry | 5 | - | 仅Active 5因子 |
| factor_profile | 51 | - | |

**交易/PT表**
| 表 | 行数 | 时间范围 | 备注 |
|----|------|----------|------|
| signals | 170 | 2026-03-20 ~ 2026-04-07 | |
| trade_log | 72 | 2026-03-23 ~ 2026-04-08 | |
| position_snapshot | 206 | 2026-03-23 ~ 2026-04-08 | |
| performance_series | 14 | 2026-03-23 ~ 2026-04-08 | |
| execution_audit_log | 103 | 2026-04-03 ~ 2026-04-08 | |

**财务表**
| 表 | 行数 | 备注 |
|----|------|------|
| balance_sheet | 265,409 | |
| cash_flow | 286,015 | |
| financial_indicators | 240,923 | upsert只更新3/16字段 🟡 |
| earnings_announcements | 207,668 | 2015-04-07 ~ 2026-04-07 |

**空表（24张）**: agent_decision_log, ai_parameters, approval_queue, backtest_holdings, backtest_wf_windows, chip_distribution, circuit_breaker_log, experiments, factor_evaluation, factor_mining_task, forex_bars, forex_events, forex_swap_rates, gp_approval_queue, mining_knowledge, model_registry, notification_preferences, operation_audit_log, param_change_log, pipeline_run, position_monitor, universe_daily

**其他有数据表**: trading_calendar(4383), health_checks(929), scheduler_task_log(818), notifications(541), sw_industry_mapping(110), margin_data(95398), holder_number(82286), index_components(33600), backtest_daily_nav(224), backtest_trades(204), backtest_run(7), modifier_signals(2341), shadow_portfolio(60), pipeline_runs(4), intraday_monitor_log(3), factor_health_log(5), factor_lifecycle(5), strategy(1), strategy_configs(2), circuit_breaker_state(1)

### 2.2 已知问题验证

| 问题 | 状态 | 详情 |
|------|------|------|
| is_st标记 | ✅ 已修复 | is_st=true: 85,147行, is_st=false: 11,614,647行 |
| moneyflow 2020 | ✅ 已补 | 243个交易日 |
| 北向2019 | ✅ 已补 | 238个交易日(Tushare限制,部分港休日无数据) |
| stock_status_daily表 | ❌ 不存在 | |
| st_history表 | ❌ 不存在 | ST标记直接写在klines_daily.is_st列 |
| alembic迁移 | ❌ 无 | 没有alembic_version表,无迁移管理 |

### 2.3 ✅ code格式已统一 (2026-04-09 Step 1完成)

| 表 | 带后缀(.SH/.SZ/.BJ) | 不带后缀 | 后缀比例 |
|----|---------------------|---------|---------|
| klines_daily | 4,280,764 | 7,419,030 | **36.6%** |
| daily_basic | 4,226,341 | 7,378,634 | **36.4%** |
| moneyflow_daily | 5,165,660 | 6,210,083 | **45.4%** |
| northbound_holdings | 0 | 5,542,237 | 0% |
| factor_values | 119,727,328 | 381,633,598 | **23.9%** |
| symbols | 5,821 | 5,810 | **50.0%** |
| trade_log | 0 | 72 | 0% |
| signals | 0 | 170 | 0% |
| position_snapshot | 0 | 206 | 0% |

> 🔴 **根因**: 原始数据(fetch_base_data.py)去掉后缀存储;后来补拉的历史数据(pull_historical_data.py)保留了Tushare原始的`.SH/.SZ`后缀。两批数据混在同一张表中。
> 
> **影响**: 跨表JOIN时code不匹配——例如klines_daily中`600519`与factor_values中`600519.SH`是两条不同记录,导致因子与价格无法关联。

### 2.4 adj_factor PIT安全性验证

**结论: ✅ PIT安全(无后缀的旧数据)**

| 股票 | DB adj_factor (2022-01-04) | Tushare PIT值 | Tushare最新值 | DB匹配PIT | DB匹配最新 |
|------|--------------------------|--------------|-------------|---------|---------|
| 600519 (茅台) | 7.474 | 7.474 | 8.4464 | ✅ | ❌ |
| 000001 (平安) | 111.922 | 111.922 | 134.5794 | ✅ | ❌ |
| 601318 (中国平安) | 2.561 | 2.561 | 3.1328 | ✅ | ❌ |

DB中存储的adj_factor是**拉取时的历史值**,不会被后续分红/送股更新 → **PIT安全**。

**adj_factor适用范围**: 适用于所有OHLCV列。`前复权价 = 原始价 × adj_factor / 最新adj_factor`。
注意: Tushare `pro_bar(adj='qfq')` 的前复权是基于最新adj_factor计算的,会随时间变化。直接用raw price × 历史adj_factor做回测时需注意基准对齐。

**⚠️ 带后缀的新拉取数据(4.28M行)未验证adj_factor值** — 需要确认这部分是否也是PIT安全的。

### 2.5 TimescaleDB
- hypertable: `factor_values`, `klines_daily`
- chunk数量和大小未能通过SQL查询获取(权限/API变化)

### 2.6 minute_bars
- 139,303,467行, 2021-01-04 ~ 2025-12-31
- 列名用`ts_code`(非`code`),与其他表不一致 🟡
- 拉取进度: 未完成(之前~36%,当前未继续)

---

## §3 代码状态

### 3.1 代码统计
| 项目 | 数量 |
|------|------|
| Git commits | 224 |
| Python文件 (backend/) | 274 |
| Python文件 (scripts/) | 169 (含131归档) |
| TS/TSX文件 (frontend/) | 122 |
| 最新commit | `96c8d38` fix: 回测引擎OOM修复 + ST标记过滤 |

### 3.2 Git状态
```
 M backend/.omc/state/idle-notif-cooldown.json
 M backend/.omc/state/last-tool-error.json
 D docs/archive/DEV_FOREX.md
 D docs/archive/DEV_NOTIFICATIONS.md
?? docs/DEV_FOREX.md
?? docs/DEV_NOTIFICATIONS.md
```
> 2个文档从archive移到了docs/但未提交。

### 3.3 Lint
- ruff: **1 error** (B905 zip-without-strict in backtest_engine.py)
- 之前5704→0的清理成果基本保持

### 3.4 测试
- 收集: **2115 tests**, 98 test files (Step 5 新增 48 测试: validators/broker_costs/pms/config_loader/engine_e2e)
- backtest 核心测试: **88 passed** (40 原有 + 48 新增) ✅

### 3.5 TODO/FIXME/HACK
极少(6个文件各1-2个),主要在archive脚本中,不影响生产。

### 3.6 特定代码验证

**vectorized_signal.py L109 vs run_backtest.py L51:**
| 文件 | 字段 |
|------|------|
| vectorized_signal.py L109 | `values="raw_value"` (pivot factor_df) |
| run_backtest.py L51 | `SELECT code, factor_name, neutral_value` |

> 🔴 **不一致!** vectorized_signal用`raw_value`,run_backtest加载`neutral_value`。
> 但实际调用时,研究脚本的SQL用`COALESCE(neutral_value, raw_value) AS raw_value`传给vectorized_signal,所以**字段名一致但语义不同** — vectorized_signal收到的可能是neutral_value或raw_value,取决于调用方的SQL。

**DataFeed.from_database():**
> 🔴 **FAILED** — SQL引用`k.ts_code`(应为`k.code`)、`adj_factor`表(应为klines_daily列)、`stk_limit`表(应为klines_daily列)、`symbols_info`表(不存在)。这个方法在当前schema下**完全不可用**。

**TushareClient vs TushareFetcher:**
| 类 | 位置 | 用途 |
|----|------|------|
| TushareClient | `backend/app/data_fetcher/tushare_client.py` | fetch_base_data.py使用, `query(api_name)` |
| TushareFetcher | `backend/app/data_fetcher/tushare_fetcher.py` | 日增量拉取, `_api_call_with_retry()` |

> 🟡 两个独立的Tushare封装,重试/限流逻辑不同。

---

## §4 模块依赖分析

### backtest_engine.py 导出类的引用方

**生产代码(backend/app/)**: 无直接import — 回测引擎完全独立于FastAPI服务层。

**研究脚本(scripts/research/)**: 7个文件import
- `BacktestConfig` + `run_hybrid_backtest`: 5个文件
- `BacktestConfig` + `run_composite_backtest`: 2个文件
- `BacktestConfig` + `SimpleBacktester`: 2个文件(直接用底层API)
- `PMSConfig`: 2个文件

**归档脚本(scripts/archive/)**: 9个文件import(已归档,不维护)

**结论**: 回测引擎的公开接口是 `run_hybrid_backtest()` 和 `run_composite_backtest()`。`SimpleBacktester` 偶尔被直接使用。拆分时这三个入口必须保持。`ValidatorChain` 无外部引用。

---

## §5 PT完整调用链

### 信号生成路径
```
run_paper_trading.py
  ├── compute_daily_factors()  → factor_engine/__init__.py  [因子计算, Phase C C1 后仍暂留 __init__, C3 迁 compute_service]
  ├── save_daily_factors()     → factor_engine/__init__.py  [因子入库, 走 DataPipeline(FACTOR_VALUES)]
  ├── load_factor_values()     → run_backtest.py:L48  [加载neutral_value]
  ├── SignalService()          → signal_service.py    [信号合成]
  │     └── SignalComposer.compose()  → signal_engine.py [等权排序→Top-N]
  ├── ExecutionService()       → execution_service.py [执行]
  │     └── QMT模式 → qmt_execution_adapter.py
  │     └── Paper模式 → SimBroker (内部)
  └── 收尾: moneyflow拉取 / IC监控 / 因子衰减检查
```

### 🔴 两条信号链路不一致

| | PT生产 | 回测研究 |
|--|--------|---------|
| 入口 | `SignalService.generate_signals()` | `build_target_portfolios()` |
| 合成器 | `SignalComposer.compose()` | vectorized_signal内联逻辑 |
| 因子值 | `neutral_value` (via run_backtest.py L51) | `raw_value` (由调用方SQL决定) |
| Universe | 传入的universe参数 | 无过滤(全量factor_df) |

> 同一个策略在PT和回测中可能产生不同的信号。

---

## §6 实际运行流程

### Task Scheduler注册任务（16个）

| 任务名 | 状态 | 触发时间 | 说明 |
|--------|------|----------|------|
| QM-DailyBackup | Ready | 02:00 | pg_dump备份 |
| QM-HealthCheck | Ready | 16:25 | 盘前健康检查 |
| QM-LogRotate | Ready | 06:00 | 日志轮转 |
| QM-SmokeTest | **Disabled** | 00:05 | 冒烟测试(已禁用) |
| QuantMind_CancelStaleOrders | Ready | 09:05 | QMT撤单 |
| QuantMind_DailyBackup | Ready | 02:00 | 🟡 与QM-DailyBackup重复 |
| QuantMind_DailyExecute | Ready | 09:31 | QMT执行 |
| QuantMind_DailyExecuteAfterData | **Disabled** | 17:05 | SimBroker执行(已禁用) |
| QuantMind_DailyMoneyflow | Ready | 17:00 | moneyflow拉取 |
| QuantMind_DailyReconciliation | Ready | 15:10 | 收盘对账 |
| QuantMind_DailySignal | Ready | 17:15 | 🟡 NextRun显示03-25(过期?) |
| QuantMind_DataQualityCheck | Ready | 16:40 | 数据巡检 |
| QuantMind_FactorHealthDaily | Ready | 17:30 | 因子健康检查 |
| QuantMind_IntradayMonitor | Ready | 09:35 | 盘中监控 |
| QuantMind_MiniQMT_AutoStart | Ready | - | QMT自启动 |
| QuantMind_PTWatchdog | Ready | 20:00 | PT心跳监控 |

> 🟡 两个备份任务重复: QM-DailyBackup和QuantMind_DailyBackup
> 🟡 QuantMind_DailySignal的NextRun显示3月25日,可能触发条件有问题

### Celery Beat调度（正常运行 ✅）
CeleryBeat 自2026-04-03 Servy迁移后持续运行,以下任务正常调度:
- PMS 14:30阶梯利润保护检查 (工作日, 最近触发: 2026-04-10 14:30)
- GP因子挖掘(周日22:00, 最近触发: 2026-04-05 22:00)
- 其他Beat定时任务

> ⚠️ 审计时 (04-02) 误判为 Stopped, 实际 stderr 日志显示 04-03 17:32 首次启动后持续运行。历史记录: 04-07→04-09 有短暂中断 (PT暂停期间), 04-09 17:34 自动恢复。

---

## §7 性能基准

### 查询性能
| 查询 | 耗时(中位数) | 说明 |
|------|------------|------|
| factor_values 单因子1年10万行 | 0.26s | TimescaleDB chunk exclusion |

### 缓存文件 (cache/)
| 文件 | 大小 | 最后修改 | 用途 |
|------|------|----------|------|
| neutral_values.parquet | 424MB | 2026-04-05 | 中性化因子缓存 |
| fwd_excess_*.parquet (6个) | 318MB合计 | 2026-04-05 | 前瞻收益缓存(1d/5d/10d/20d/60d/120d) |
| close_pivot.parquet | 48MB | 2026-04-05 | 收盘价pivot缓存 |
| industry_map.parquet | <1MB | 2026-04-05 | 行业映射 |
| earnings_sue.parquet | 2MB | 2026-04-06 | 盈利公告SUE因子 |
| cache_meta.json | <1MB | 2026-04-05 | 缓存元数据 |
| csi300_close.parquet | <1MB | 2026-04-05 | CSI300基准 |
| csi_monthly.parquet | <1MB | 2026-04-05 | 月度CSI300 |

> ⚠️ 缓存全部基于2020-2025数据,12年扩展后需要重建。

### models/目录
包含LightGBM/Alpha158研究产出(CSV文件),非可执行模型。`all_astock_codes.txt`、`csi500_codes.txt`为股票列表。

---

## §8 后台任务状态

| 任务 | 状态 | 说明 |
|------|------|------|
| 分钟数据拉取 | ⏸️ 中断 | ~36%完成(1867/5194只),进程已结束 |
| ST标记修复 | ✅ 完成 | 85,147行已标记 |
| 12年因子补算 | ✅ 完成 | core+full+ML+北向全部补算 |
| 12年数据拉取 | ✅ 完成 | klines/basic/moneyflow/index/northbound |

---

## §9 文件资产盘点

### scripts/research/ (17个研究脚本)
| 脚本 | 大小 | 已被引擎吸收? |
|------|------|-------------|
| pull_historical_data.py | 11K | 否(一次性拉取工具) |
| earnings_factor_calc.py | 27K | 否(盈利因子待验证) |
| factor_pool_expansion.py | 21K | 否(独立性筛选) |
| factor_pool_ic_weighted.py | 23K | 否(IC加权实验) |
| strategy_overlay_backtest.py | 19K | 否(策略叠加实验) |
| template11_modifier_backtest.py | 24K | 部分(Modifier逻辑已入backtest_engine) |
| template11_param_optimize.py | 15K | 否(参数优化) |
| verify_factor_expansion.py | 14K | 否(验证脚本) |
| mdd_reduction_dual_modifier.py | 7K | 结论已入(双层Modifier) |
| paired_bootstrap_top9.py | 7K | 结论已入(9因子FAIL) |
| 其余7个 | 7-9K | 均为一次性研究 |

### backend/wrappers/
- `quantstats_wrapper.py` — QuantStats报表封装
- `ta_wrapper.py` — 技术指标封装
- 当前无生产引用,可能是早期代码

### backend/services/ (非app/services/)
- `notification_service.py` — 与`app/services/notification_service.py`不同文件同名 🟡

---

## §10 备份状态

| 类型 | 最新备份 | 大小 | 自动化 |
|------|---------|------|--------|
| daily | 2026-04-08 02:09 | 7.7GB | ✅ QM-DailyBackup |
| monthly | 2026-04-01 02:05 | 3.9GB | ✅ |
| parquet | 空 | 0 | ❌ 未配置 |

> ✅ 备份自动化正常运行,每日pg_dump到D:/quantmind-v2/backups/daily/。
> ⚠️ 重构前建议手动做一次完整备份(当前最新自动备份已有)。

---

## §11 Redis

### StreamBus Streams
| Stream | 积压 | 说明 |
|--------|------|------|
| qm:execution:order_filled | 0 | |
| qm:health:check_result | 0 | |
| qm:signal:generated | 0 | |
| qm:qmt:status | 4424 | QMT状态累积(maxlen=10000) |

### 其他Key
- `portfolio:current` — QMT当前持仓(Hash)
- `portfolio:nav` — QMT资产(JSON)
- `qmt:connection_status` — "connected"
- Celery相关: `_kombu.binding.*`, `celery`

> Redis状态正常,无积压。

---

## §12 外部依赖

| 依赖 | 状态 | 说明 |
|------|------|------|
| Tushare API | ✅ 正常 | Token: ecc9...dd23 (len=56) |
| QMT连接 | ✅ connected | Redis key确认 |
| GitHub | ✅ | mlhjyx/quantmind-v2 private, 224 commits |

---

## §13 V3设计文档

| 文档 | 行数 | 最后修改(git) | 与代码偏离 |
|------|------|-------------|-----------|
| DEV_BACKEND.md | 1236 | 2026-03-28 | 🟡 分层规则正确,但Engine层DB IO违反实际存在 |
| DEV_BACKTEST_ENGINE.md | 1779 | 2026-04-08 | ✅ 最近更新,较准确 |
| DEV_FACTOR_MINING.md | 1137 | 2026-03-28 | 🟡 未反映12年数据扩展 |
| DEV_FRONTEND_UI.md | 1362 | 2026-03-28 | 🟡 前端开发暂停,文档未追踪实际 |
| DEV_SCHEDULER.md | 414 | 2026-03-28 | 🔴 文档说T0-T17 Celery调度,实际用Task Scheduler |
| DEV_PARAM_CONFIG.md | 452 | 2026-03-28 | 🟡 |
| DEV_AI_EVOLUTION.md | 1050 | 2026-03-28 | 🟡 AI闭环尚未实施 |
| GP_CLOSED_LOOP_DESIGN.md | 663 | 2026-03-28 | 🟡 GP产出0因子,Beat已停 |
| RISK_CONTROL_SERVICE_DESIGN.md | 678 | 2026-03-22 | 🟡 L1-L4设计,实际只有L4 approve_l4.py |
| ML_WALKFORWARD_DESIGN.md | 1121 | 2026-04-05 | ✅ 较准确 |
| ROADMAP_V3.md | 2267 | 2026-04-05 | ✅ 路线图最新 |
| DDL_FINAL.sql | 813 | 2026-04-06 | 🟡 DDL 45张 vs DB实际62张(代码动态建的17张未同步) |
| IMPLEMENTATION_MASTER.md | 2545 | 2026-03-29 | 🟡 Sprint编号与实际不同步 |
| DEV_FOREX.md | 676 | 未提交 | 外汇模块空表,未实施 |
| DEV_NOTIFICATIONS.md | 213 | 未提交 | |

---

## §14 额外发现

### 14.1 run_paper_trading.py是1734行的单体脚本
- 45个import
- 包含因子计算、信号生成、执行、moneyflow拉取、数据质量检查、IC监控、因子衰减、HMM regime检测、LightGBM影子模型等**全部**逻辑
- 重复import: `qmt_manager`和`TushareFetcher`各import两次
- 是系统中最脆弱的单点

### 14.2 两个notification_service.py
- `backend/app/services/notification_service.py`
- `backend/services/notification_service.py`
- 不确定哪个在用,需确认

### 14.3 minute_bars用ts_code而非code
与其他表的code列名不一致(但minute_bars是Baostock拉取的,格式不同)。

### 14.4 24张空表
62张表中24张完全为空,包括所有forex表(4张)、AI相关表(4张)、GP相关表(2张)。这些是设计预留但从未使用的。

---

## §9 分析与建议

### 问题清单（按严重度排序）

**🔴 致命（必须在重构中首先解决）**

| # | 问题 | 影响 | 来源 |
|---|------|------|------|
| F1 | **code格式混乱**: 同一张表同时存在`600519`和`600519.SH`两种格式 | 跨表JOIN失效,因子与价格无法关联,所有依赖code的查询结果不可信 | §2.3 |
| F2 | **DataFeed.from_database()完全不可用**: SQL引用不存在的表/列 | 生产回测数据源断路 | §3.6 |
| F3 | **PT和回测两条不同信号链路**: SignalComposer vs vectorized_signal | 同一策略在PT和回测产生不同结果,回测验证无意义 | §5 |
| F4 | ~~**CeleryBeat已停**~~ ✅ **误报**: 审计时误判, 实际自04-03 Servy迁移后持续运行 | ~~PT无利润保护~~ PMS正常执行 | §1 |

**🟡 高（重构中必须处理）**

| # | 问题 | 影响 |
|---|------|------|
| H1 | ST标记用当前快照非PIT: 新拉取数据在tushare_fetcher.py中用stock_basic当前名称判断 | 回测有前瞻偏差 |
| H2 | standardize_units()用启发式猜测单位: 中位数阈值在小盘/大盘子集可能误判 | 滑点/成交量计算错误 |
| H3 | 两个Tushare客户端: TushareClient和TushareFetcher重试/限流逻辑不同 | 数据拉取行为不一致 |
| H4 | financial_indicators upsert只更新3/16字段 | 财务数据修正被丢弃 |
| H5 | ST过滤是集合级(整段排除)而非日期级: 曾ST 1个月的股票被排除5年 | 回测过度排除 |
| H6 | 因子引擎违反Engine层纯计算约束: compute_daily_factors直接做DB IO | 架构腐化 |
| H7 | run_paper_trading.py 1734行单体: 全系统最脆弱单点 | 难维护,改一处影响全局 |
| H8 | 两个备份任务重复: QM-DailyBackup和QuantMind_DailyBackup | 浪费存储,混淆 |

**🟠 中（重构中应处理）**

| # | 问题 | 影响 |
|---|------|------|
| M1 | minute_bars用ts_code而非code | 与其他表不一致 |
| M2 | 退市检测hardcoded 20天: 长期停牌被误判退市 | 假清算 |
| M3 | slippage模型volume单位"手"vs文档"股": 当前碰巧正确但脆弱 | 未来修改可能引入100x错误 |
| M4 | 缓存基于2020-2025: 12年扩展后失效 | 需重建 |
| M5 | DEV_SCHEDULER.md说Celery调度但实际用Task Scheduler | 文档与实际严重偏离 |
| M6 | 两个同名notification_service.py在不同路径 | 混淆 |
| M7 | 24张空表占用schema空间 | 管理复杂度 |

### 风险预警（重构可能踩的坑）

1. **code格式统一会触发连锁反应**: 选择保留哪种格式后,需要更新所有SQL查询、所有Python代码中的字符串处理、所有Parquet缓存。factor_values 5亿行的UPDATE需要数小时。建议选一种格式后**新建表+迁移**而非原地UPDATE。

2. **run_paper_trading.py的任何改动都有PT风险**: 这个1734行的文件是PT的唯一入口。重构它时PT必须暂停。建议先提取出独立模块再替换。

3. **backtest_engine.py内部耦合**: SimBroker/SimpleBacktester/_PriceIdx/日循环/PMS/退市检测/ValidatorChain全在一个文件中。拆分时需要仔细处理内部状态传递(pms_state, _delist_count等是闭包变量)。

4. **CeleryBeat重启后积压任务可能批量触发**: 如果Beat停了多天后重启,之前错过的periodic task可能积压执行。需要先清理Beat schedule再重启。

5. **symbols表同时有带后缀(5821)和不带后缀(5810)**: 原始5810只是老数据(无后缀),后来补充的5821只退市股带后缀。FK约束指向这张表——统一code格式时symbols必须先改。

6. **12年回测仍OOM**: 当前dict-based PriceIdx + groupby daily_close在11M行上仍OOM。分块回测是必须的,但分块边界处的持仓延续需要特殊处理。

### 方案建议

**建议实施顺序:**

1. **首先统一code格式** — 这是所有其他修复的前提。建议统一为带后缀格式(`600519.SH`),因为Tushare原生格式就是带后缀的,减少后续转换。用新表+批量INSERT替代原地UPDATE。

2. **合并两条信号链路** — PT和回测必须用同一个信号生成函数。建议以vectorized_signal的`build_target_portfolios()`为标准(它更简洁),让SignalService也调用它而非SignalComposer。

3. **拆分backtest_engine.py** — 建议拆为:
   - `sim_broker.py` — SimBroker + 订单填充
   - `backtest_runner.py` — SimpleBacktester + 日循环
   - `backtest_config.py` — BacktestConfig/PMSConfig/SignalConfig
   - `backtest_entry.py` — run_hybrid/run_composite入口

4. **统一数据清洗层** — 新建`DataCleaner`,所有数据入库前必经。显式单位标注替代启发式猜测。

5. **分块回测** — 按年分块,每块独立加载数据,块间传递持仓状态。

6. ~~**重启CeleryBeat**~~ ✅ 已确认持续运行中 (自04-03), 无需重启。

### 疑问（需确认）

1. **PT是否暂停?** — 你说"PT暂停,研究暂停,全力重构",但Task Scheduler任务全是Ready状态,QMT显示connected。需要手动禁用Task Scheduler任务吗?

2. **code格式选哪个?** — 带后缀(`600519.SH`) vs 不带(`600519`)。前者是Tushare原生格式,后者是现有PT/signals/trade_log的格式。统一方向需要你决定。

3. **backend/wrappers/ 和 backend/services/notification_service.py 是废弃代码吗?** — 无生产引用,但不确定是否有计划使用。

4. **24张空表清理还是保留?** — 如果外汇/AI/GP模块在重构路线图中,保留;如果不在,清理DDL减少复杂度。

5. **分钟数据拉取是否继续?** — 36%中断状态。重构后数据管道改变,可能需要重新开始。

6. **前端重构范围?** — 122个TS/TSX文件,但你只提到了后端重构。前端API层是否也要改?

---

*报告完毕。所有数据基于2026-04-09实际查询,未修改任何代码或数据。*
