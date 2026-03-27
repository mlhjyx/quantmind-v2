# 设计文档 vs 代码实现审计报告 — Part 3（文档6-11）

> 审计日期: 2026-03-26
> 审计范围: DEV_PARAM_CONFIG / DEV_FRONTEND_UI / DEV_NOTIFICATIONS / DEV_SCHEDULER / DEV_FOREX / FOREX_DESIGN
> 标注说明: ✅已实现 | ⚠️部分实现 | ❌未实现 | 🔮Phase 2+

---

## 文档6: DEV_PARAM_CONFIG.md（参数可配置性系统）

### §1 四级控制体系
- L0硬编码: ✅ param_defaults.py中backtest.lot_size标记level="L0" (backend/app/services/param_defaults.py:267)
- L1配置文件: ✅ backend/app/config.py pydantic-settings读取.env
- L2前端可调: ⚠️ 后端API已实现(backend/app/api/params.py)，前端参数面板未实现
- L3 AI自动调: ❌ 未实现（Phase 1 AI闭环功能）

### §2 统一参数交互组件（前端）
- 三态滑块组件(手动/AI推荐/AI自动): ❌ 前端未实现参数组件
- 参数帮助提示/历史最优显示: ❌ 前端未实现

### §3 完整参数清单（220+参数）
- §3.1 GP遗传编程引擎(13参数): ⚠️ param_defaults.py定义5个GP参数(population_size/generations/crossover_rate/mutation_rate/anti_crowding_threshold)，缺8个
- §3.2 LLM因子挖掘Agent(9参数): ❌ 未定义（Phase 1）
- §3.3 Factor Gate Pipeline(7参数): ⚠️ factor.ic_threshold定义1个，缺t-stat/单调性/相关性/分年稳定等6个
- §3.4 组合构建(6参数): ✅ signal模块定义top_n/weight_method/rebalance_freq/industry_cap/turnover_cap/single_stock_cap (backend/app/services/param_defaults.py:165-218)
- §3.5 Universe(5参数): ✅ universe模块定义min_market_cap/exclude_st/exclude_suspended/min_listing_days/min_avg_turnover (backend/app/services/param_defaults.py:409-452)
- §3.6 风控(3可调+5只读): ✅ risk模块定义7个参数含L1-L4风控线+恢复条件+降仓比例 (backend/app/services/param_defaults.py:294-358)
- §3.7 回测(7参数): ✅ backtest模块定义8个参数含initial_capital/slippage/commission/stamp_tax/lot_size/benchmark/bootstrap/cost_sensitivity (backend/app/services/param_defaults.py:220-291)
- §3.8 AI模型管理(10参数): ❌ 未定义（Phase 1 LightGBM/HMM配置）
- §3.9 调度时间(4参数): ⚠️ scheduler模块定义3个(data_pull_time/pre_market_confirm_time/health_check_enabled)，缺P1告警最大条数
- §3.10 因子预处理(4参数): ✅ factor模块定义neutralize_method/preprocess_mad_multiplier/missing_fill_method，缺标准化方法1个
- §3.11 因子选择(每因子3参数×34因子=102个): ❌ 未实现（因子级别开关/方向/窗口参数化）
- §3.12 回测引擎V2新增(22参数): ❌ 未定义Walk-Forward/市场状态分析参数
- §3.13 AI闭环Agent配置(28参数): ❌ 未定义（Phase 1）

### §4 参数变更安全机制
- §4.1 前端即时合理性检查(PARAM_CONSTRAINTS): ❌ 前端未实现约束检查
- §4.2 变更影响预估弹窗: ❌ 未实现
- §4.3 版本记录(param_change_log表): ✅ DDL已建 + ParamRepository已实现insert_change_log/get_change_log (backend/app/repositories/param_repository.py:178-245)
- §4.4 一键回滚: ❌ 未实现rollback_params_to()

### §5 ai_parameters表初始化数据
- 14条初始数据INSERT: ⚠️ param_defaults.py定义了~50个默认值，但命名与§5不完全一致（如holding_count_n→signal.top_n）。init_defaults()可初始化到DB (backend/app/services/param_service.py:248-273)

### §6 V2新增参数模块
- §3.12回测引擎22参数: ❌ 未定义
- §3.13 Agent配置28参数: ❌ 未定义

### §7 参数变更约束补充
- BACKTEST_CONSTRAINTS: ❌ 未实现跨参数约束校验
- AGENT_CONSTRAINTS: ❌ 未实现

### Review补丁P1 新增可配置参数(16个)
- EXECUTION_MODE: ✅ execution.mode已定义 (param_defaults.py:458)
- MAX_SINGLE_REBALANCE_TURNOVER: ✅ signal.turnover_cap已定义
- PAPER_GRADUATION_*: ✅ paper_trading模块4个毕业参数已定义 (param_defaults.py:360-407)
- HEALTH_CHECK_*: ⚠️ health_check_enabled已定义，MIN_DISK_GB/FACTOR_SAMPLE_N未参数化
- LOG_LEVEL/LOG_MAX_FILES: ❌ 未参数化（在config.py中硬编码）
- COST_SENSITIVITY_MULTIPLIERS: ✅ backtest.cost_sensitivity_multipliers已定义
- BOOTSTRAP_N_SAMPLES: ✅ backtest.bootstrap_samples已定义
- FACTOR_CRITICAL_WEEKS/MIN_ACTIVE_COUNT: ✅ factor.critical_to_retired_days/min_active_count已定义
- AI_CHANGE_*: ❌ 未定义（Phase 1）

### 后端API
- GET /api/params: ✅ (backend/app/api/params.py:45)
- GET /api/params/{key}: ✅ (backend/app/api/params.py:91)
- PUT /api/params/{key}: ✅ (backend/app/api/params.py:115)
- GET /api/params/changelog: ✅ (backend/app/api/params.py:71)
- POST /api/params/init-defaults: ✅ (backend/app/api/params.py:148)

### strategy_configs版本管理
- strategy_configs表JSONB: ✅ StrategyRepository已实现版本插入(不更新旧行) (backend/app/repositories/strategy_repository.py:72-106)
- 版本回滚(改active_version指针): ✅ rollback_version() (backend/app/repositories/strategy_repository.py:108-113)
- GET /api/strategies: ✅ (backend/app/api/strategies.py:39)
- GET /api/strategies/{id}: ✅ (backend/app/api/strategies.py:61)
- POST /api/strategies/{id}/versions: ✅ (backend/app/api/strategies.py:83)
- POST /api/strategies/{id}/rollback: ✅ (backend/app/api/strategies.py:109)

---

## 文档7: DEV_FRONTEND_UI.md（前端UI）

### §1 前端技术选型与UI风格
- React 18+: ✅ frontend/package.json存在
- Tailwind CSS + shadcn/ui: ⚠️ Tailwind已使用(Dashboard.tsx)，shadcn/ui未引入
- ECharts: ❌ 未引入（NAVChart.tsx使用Recharts）
- Recharts: ✅ 已使用
- Monaco Editor: ❌ 未引入
- Zustand: ❌ 未引入
- React Router v6: ❌ 未引入（App.tsx直接渲染Dashboard，无路由）
- Axios + React Query: ❌ 使用原生fetch (frontend/src/api/dashboard.ts)
- socket.io-client: ❌ 未引入
- 深色毛玻璃风格: ✅ Dashboard.tsx使用bg-[#0f172a]+backdrop-blur-md
- 涨跌色可配置: ❌ 未实现配置切换

### §2 回测模块页面（5个）
- 页面①策略工作台: ❌ 未实现
- 页面②回测配置面板: ❌ 未实现
- 页面③回测运行监控: ❌ 未实现
- 页面④回测结果分析: ❌ 未实现
- 页面⑤策略库: ❌ 未实现

### §3 因子挖掘模块页面（4个）
- 页面⑥因子实验室: ❌ 未实现
- 页面⑦挖掘任务中心: ❌ 未实现
- 页面⑧因子评估报告: ❌ 未实现
- 页面⑨因子库: ❌ 未实现

### §4 AI闭环模块页面（2个）
- 页面⑩Pipeline控制台: ❌ 未实现
- 页面⑪Agent配置: ❌ 未实现

### §5 系统设置页面
- 页面⑫系统设置(5Tab): ❌ 未实现

### §6 全局交互规范
- 资金量约束提示: ❌ 未实现
- 错误处理(重试/WS重连): ❌ 未实现
- 数据导出/导入: ❌ 未实现
- 参数变更30天冷却期: ❌ 未实现
- FDR多重检验显示: ❌ 未实现
- 移动端适配: ❌ 未实现

### §7 后端API汇总(~57端点)
- 回测模块14个API: ⚠️ POST /api/backtest/run存在(backend/app/api/backtest.py)，其余大部分未实现
- 因子挖掘模块15个API: ❌ 未实现
- AI闭环模块10个API: ❌ 未实现
- 系统设置8个API: ⚠️ GET /api/system/health已实现(backend/app/api/health.py)，其余未实现

### §8 总览页详细设计
- 总组合默认视图: ⚠️ Dashboard.tsx实现了KPI卡片+NAV曲线+持仓表+熔断状态，但缺少市场快照/待处理事项折叠/分市场卡片/月度收益/因子库状态/AI闭环状态/快速操作
- A股详情视图: ❌ 未实现（无路由）
- 外汇详情视图: ❌ 未实现（Phase 2）
- 总览页API(11个): ⚠️ dashboard/summary+nav-series+positions已实现(frontend/src/api/dashboard.ts)，其余未实现

### §9 导航与路由设计
- 路由表(20+路由): ❌ 无React Router，仅Dashboard单页
- 市场切换器: ❌ 未实现
- 导航栏(左侧折叠): ❌ 未实现
- 面包屑: ❌ 未实现

### §10 组件设计规范
- GlassCard: ⚠️ Dashboard中使用了毛玻璃样式但未封装为组件
- MetricCard: ✅ KPICards组件(frontend/src/components/KPICards.tsx)
- 色彩系统: ⚠️ 使用了深色底但未建立完整色彩token系统

### §11-13 通知中心/数据密度/响应式
- 通知铃铛+中心: ❌ 未实现
- 数据密度切换: ❌ 未实现
- 响应式3档: ❌ 未实现

### 已实现前端组件清单
- ✅ Dashboard页面 (frontend/src/pages/Dashboard.tsx)
- ✅ KPICards组件 (frontend/src/components/KPICards.tsx)
- ✅ NAVChart组件 (frontend/src/components/NAVChart.tsx)
- ✅ PositionTable组件 (frontend/src/components/PositionTable.tsx)
- ✅ CircuitBreaker组件 (frontend/src/components/CircuitBreaker.tsx)
- ✅ Dashboard API层 (frontend/src/api/dashboard.ts)
- ✅ Mock数据 (frontend/src/api/mock.ts)
- ✅ TypeScript类型定义 (frontend/src/types/dashboard.ts)

---

## 文档8: DEV_NOTIFICATIONS.md（通知告警）

### §一 架构
- NotificationService统一入口: ✅ send(level,category,title,content,...) (backend/app/services/notification_service.py:197)
- 写入notifications表: ✅ NotificationRepository.create() (backend/app/services/notification_service.py:34)
- WebSocket推送 /ws/notifications: ❌ 未实现WebSocket
- NotificationDispatcher→钉钉: ✅ _dispatch()调用dingtalk.send_markdown() (backend/app/services/notification_service.py:297)
- 防洪泛Throttler: ✅ NotificationThrottler内存dict实现 (backend/app/services/notification_throttler.py)

### §二 NotificationService
- P3仅日志不存库: ✅ (notification_service.py:251-253)
- P0-P2存库+外发检查: ✅ (notification_service.py:233-248)
- P0始终外发(无视静默): ✅ (notification_service.py:313)
- P1受静默限制: ⚠️ P1默认外发，但静默时间段逻辑未实现（文档要求quiet_start/quiet_end）
- P2看偏好: ⚠️ 当前P2不外发，但未读notification_preferences表

### §三 NotificationDispatcher
- §3.1 钉钉Webhook: ✅ dispatchers/dingtalk.py存在，Markdown格式+emoji+时间戳
- §3.2 微信推送(Phase 3): ❌ 预留接口未实现（符合预期）
- §3.3 邮件(Phase 4): ❌ 预留接口未实现（符合预期）

### §四 通知模板(25+预定义)
- §4.1 风控类(7个): ⚠️ 实现circuit_breaker_triggered 1个，缺drawdown_warning/pause/emergency/margin_warning/call/consecutive_loss/daily_loss共6个
- §4.2 交易类(6个): ⚠️ 实现daily_execute_complete/rebalance_summary 2个，缺forex_open/close/sl_modified/friday_close共4个（Phase 2符合预期）
- §4.3 因子类(2个): ✅ factor_ic_decay + factor_coverage_low/warning 3个（超额实现）
- §4.4 回测类(2个): ❌ 未实现backtest.complete/failed模板
- §4.5 AI闭环类(2个): ❌ 未实现pipeline.complete/approval_needed模板
- §4.6 系统类(6个): ⚠️ 实现health_check_failed/system_disk_warning/pipeline_error 3个，缺data_update_failed/mt5_disconnect/reconnected/scheduler_task_delayed/param_cooldown_expired
- Review补丁新增7个模板: ⚠️ health_check_failed已实现，其余6个(factor.active_count_low/ai.change_approved/rejected/diagnosis_triggered/paper.milestone/graduation_ready)未实现

### §五 防洪泛(Throttler)
- Redis TTL机制: ⚠️ Phase 0使用内存dict实现(notification_throttler.py)，非Redis
- 各模板最小间隔配置: ⚠️ 按级别配置(P0:1min/P1:10min/P2:30min/P3:1h)，未按模板粒度配置

### §六 通知生命周期
- 创建→未读→已读→已处理→归档: ⚠️ 创建/未读/已读已实现，已处理(is_acted)字段存在但无更新逻辑
- 清理任务(30天/90天): ❌ 未实现清理逻辑

### §七 数据库表
- notifications表: ✅ DDL已建(docs/QUANTMIND_V2_DDL_FINAL.sql)
- notification_preferences表: ✅ DDL已建，但后端无读写逻辑

### §八 后端API
- GET /api/notifications: ✅ 列表+分页+筛选 (backend/app/api/notifications.py:54)
- GET /api/notifications/unread-count: ✅ (backend/app/api/notifications.py:87)
- PUT /api/notifications/{id}/read: ✅ (backend/app/api/notifications.py:122)
- PUT /api/notifications/read-all: ❌ 未实现（NotificationRepository有mark_all_read()但API未暴露）
- GET /api/notifications/preferences: ❌ 未实现
- PUT /api/notifications/preferences: ❌ 未实现
- POST /api/notifications/test-dingtalk: ⚠️ 实现为POST /api/notifications/test (backend/app/api/notifications.py:144)，功能相似但路径不同
- DELETE /api/notifications/clear-old: ❌ 未实现
- WS /ws/notifications: ❌ 未实现

---

## 文档9: DEV_SCHEDULER.md（调度与运维）

### §一 调度框架
- Celery Beat + Worker + Redis: ✅ celery_app.py配置完整(backend/app/tasks/celery_app.py)

### §二 A股每日调度时序（Review补丁P1覆盖）
- T0 16:00 全链路健康预检: ✅ daily_health_check_task (backend/app/tasks/daily_pipeline.py:25)，Beat配置16:25
- T1 16:30 数据更新: ⚠️ daily_signal_task复用run_paper_trading.py(含数据拉取)，Beat配置16:30
- T2 数据质量检查: ⚠️ 集成在signal_phase中，未独立为Celery task
- T3 Universe构建: ⚠️ 集成在signal_phase中
- T4 因子计算: ⚠️ 集成在signal_phase中
- T5 因子体检(周一): ⚠️ 有独立脚本scripts/factor_health_daily.py但未注册Celery task
- T6 ML预测: ❌ 未实现（Phase 1 LightGBM）
- T7 信号生成: ✅ daily_signal_task (backend/app/tasks/daily_pipeline.py:116)
- T8 调仓决策: ⚠️ 集成在signal_phase中
- T9 盘后报告→通知: ⚠️ run_paper_trading.py中有钉钉通知但未作为独立task
- T10 T+1盘前执行: ✅ daily_execute_task (backend/app/tasks/daily_pipeline.py:185)，Beat配置09:00
- T16 AI闭环Pipeline(周日): ❌ 未实现
- T17 数据库维护(周日): ❌ 未注册Celery task

### §四 Celery Beat配置
- 队列设计(8个): ❌ 当前所有task使用default队列，未拆分astock_data/compute/trade等
- Worker分配(4个): ⚠️ celery_app.py配置worker_concurrency=4但未按队列分配

### §五 任务依赖管理
- Redis状态键task_status: ❌ 未实现任务依赖链检查
- 前置任务检查: ❌ 未实现

### §六 交易日历
- A股交易日判断: ⚠️ Beat用day_of_week='1-5'过滤周末，task内部判断需查trading_calendar表（部分实现于run_paper_trading.py）

### §七 异常处理与重试
- 数据拉取3次重试: ⚠️ daily_signal_task配置max_retries=2（差1次）
- 执行2次重试: ✅ daily_execute_task配置max_retries=2
- 超时配置: ✅ time_limit=1800/soft_time_limit=1500
- acks_late: ✅ 全部task配置acks_late=True

### §八 监控
- 每日完成度/延迟检测: ❌ 未实现调度监控面板
- 前端调度Tab: ❌ 未实现

### §九 数据库表
- scheduler_task_log表: ✅ DDL已建(docs/QUANTMIND_V2_DDL_FINAL.sql)
- health_checks表: ✅ DDL已建 + HealthRepository已实现 (backend/app/repositories/health_repository.py)

### Review补丁
- P2 全链路健康预检: ✅ 独立脚本scripts/health_check.py + Celery task daily_health_check_task
- P3 数据库备份: ✅ scripts/pg_backup.py + scripts/register_backup_task.ps1
- P4 日志管理: ⚠️ config.py中有LOG_LEVEL配置，LOG_MAX_FILES未实现
- P5 优雅停机: ⚠️ acks_late=True已配置，事务写入+完成标记未实现

---

## 文档10: DEV_FOREX.md（外汇开发详细）

🔮 **Phase 2 未开始** — 全文档25KB，Phase 2功能，当前无任何实现。

涉及内容: MT5 Adapter架构/14品种交易/外汇因子体系/GARCH止损/保证金管理/经济日历/Swap费率/外汇回测引擎/外汇调度时序/外汇风控4层14项等。

---

## 文档11: QUANTMIND_V2_FOREX_DESIGN.md（外汇设计总文档）

🔮 **Phase 2 未开始** — 全文档18KB，外汇模块总架构设计，当前无任何实现。

---

## 总结统计

| 文档 | ✅已实现 | ⚠️部分实现 | ❌未实现 | 🔮Phase2+ |
|------|---------|-----------|---------|----------|
| DEV_PARAM_CONFIG | 15 | 6 | 14 | 0 |
| DEV_FRONTEND_UI | 8 | 5 | 35+ | 0 |
| DEV_NOTIFICATIONS | 9 | 6 | 10 | 2 |
| DEV_SCHEDULER | 6 | 7 | 6 | 0 |
| DEV_FOREX | 0 | 0 | 0 | 全部 |
| FOREX_DESIGN | 0 | 0 | 0 | 全部 |

### 关键缺口（按优先级）

**P0 — 影响当前Paper Trading运行**:
1. 任务依赖链管理(§五)：当前health_check和signal是独立task，health_check失败不会自动阻止signal运行
2. PUT /api/notifications/read-all API缺失
3. 通知静默时间段逻辑未实现（P0通知可能夜间打扰）

**P1 — 影响系统完整性**:
1. 前端仅Dashboard单页，12个页面中仅实现1个（~8%完成度）
2. React Router/导航栏/路由系统未搭建
3. 通知模板覆盖不足（25+预定义中实现14个，~56%）
4. Celery队列未拆分（全部走default队列）
5. notification_preferences表有DDL但后端无读写

**P2 — 可后续迭代**:
1. 参数清单220+中实现~50个（~23%），但已覆盖Phase 0核心参数
2. 跨参数约束校验(PARAM_CONSTRAINTS)未实现
3. 参数一键回滚未实现
4. 调度监控面板未实现
5. 通知清理任务未实现
6. WebSocket推送全部未实现（使用HTTP轮询替代）
