# QuantMind V2 前后端集成审计报告

生成时间: 2026-04-02T15:30:00+08:00
审计范围: 19个维度（含Claude Code自主发现）
代码修改: 无（纯诊断）

---

## 总览

| 维度 | 状态 | 关键发现数 | 修复工作量 |
|------|------|-----------|-----------|
| 1. 功能模块映射 | ✅ 13/14通 | 1 | S |
| 2. API契约对齐 | ⚠️ | 3 | M |
| 3. 数据流完整链路 | ✅ 5/5通 | 0 | - |
| 4. 调度与事件架构 | ✅ | 1 | S |
| 5. WebSocket通道 | ✅ | 1 | S |
| 6. 错误处理 | ⚠️ | 3 | M |
| 7. 端到端功能验证 | ✅ 6/6通 | 0 | - |
| 8. 前端架构规范性 | ⚠️ | 3 | M |
| 9. 安全与鉴权 | ⚠️ | 3 | L |
| 10. 前端构建 | ✅ | 0 | - |
| 11. 三层一致性 | ✅ | 1 | S |
| 12. Celery任务可见性 | ✅ | 2 | S |
| 13. 通知系统 | ✅ | 0 | - |
| 14. 配置与环境 | ✅ | 1 | S |
| 15. 前端测试覆盖 | ❌ | 1 | XL |
| 16. API文档与发现 | ✅ | 0 | - |
| 17. 性能与大数据 | ⚠️ | 2 | M |
| 18. 定时任务全景 | ⚠️ | 2 | M |
| 19. Claude Code自主发现 | ⚠️ | 8 | L |

**总计: 32个问题, 其中高优先级8个, 中优先级14个, 低优先级10个**

---

## 维度1: 功能模块全景映射

### 现状

14个业务模块完整追踪:

| # | 模块 | 后端Service | API端点 | 前端页面 | 状态 |
|---|------|------------|---------|----------|------|
| 1 | 因子管理 | factor_service.py | /api/factors/* (8端点) | FactorLibrary, FactorEvaluation | ✅ |
| 2 | 回测引擎 | backtest_service.py | /api/backtest/* (6端点) | BacktestConfig/Runner/Results | ✅ |
| 3 | Paper Trading | paper_trading_service.py | /api/paper-trading/* (5端点) | PTGraduation | ✅ |
| 4 | 因子挖掘 | mining_service.py | /api/mining/* (8端点) | MiningTaskCenter, FactorLab | ✅ |
| 5 | 风控 | risk_control_service.py | /api/risk/* (5端点) | RiskManagement | ✅ |
| 6 | AI闭环 | (approval队列) | /api/approval/*, /api/pipeline/* | PipelineConsole | ⚠️ 部分 |
| 7 | 通知系统 | notification_service.py | /api/notifications/* (5端点) | NotificationSystem | ✅ |
| 8 | 参数配置 | param_service.py | /api/params/* (4端点) | SystemSettings | ✅ |
| 9 | 数据管理 | realtime_data_service.py | /api/realtime/*, /api/market/* | MarketData, Dashboard | ✅ |
| 10 | 系统监控 | (health checks) | /api/system/* (4端点) | SystemSettings | ✅ |
| 11 | 策略管理 | strategy_service.py | /api/strategies/* (5端点) | StrategyWorkspace, StrategyLibrary | ✅ |
| 12 | 市场数据 | realtime_data_service.py | /api/market/* (3端点) | MarketData | ✅ |
| 13 | 报告中心 | (report生成) | /api/report/* (3端点) | ReportCenter | ✅ |
| 14 | 调度管理 | celery_app.py, beat_schedule.py | /api/system/scheduler | PipelineConsole | ✅ |

### 问题清单
1. **AI闭环模块仅部分连接** — 3个Agent(StrategyBuild/Diagnostic/RiskControl)在设计文档(DEV_AI_EVOLUTION.md)中定义但代码未实现。PipelineConsole仅有审批队列功能。影响: 低（Phase D scope）

### 修复工作量: S

---

## 维度2: API契约对齐

### 现状
- 后端返回snake_case，前端**无统一转换层**，各API模块手动映射
- 百分比格式: 后端返回小数(0.15)，前端需要手动×100
- 分页: 两种模式混用（offset/limit + page/page_size）
- 时间: 统一ISO 8601字符串

### 问题清单
1. **无集中式snake_case→camelCase转换** — 每个API模块在factors.ts, dashboard.ts等各自手动映射。风险: 新字段容易遗漏转换。影响: 中
   - 涉及: `frontend/src/api/factors.ts:88-96`, `frontend/src/api/dashboard.ts:40-49`
2. **百分比格式不统一** — 有些API返回0.15(需×100)，有些返回15(直接显示)。前端缺乏统一约定。影响: 中
   - 例: `dashboard.ts:43` 对weight做 `p.weight / 100`
3. **分页模式不统一** — notifications/approval用offset/limit，pipeline/backtest用page/page_size。影响: 低

### 修复工作量: M

---

## 维度3: 数据流完整链路

### 现状
5条核心链路全部贯通:

| 链路 | 路径 | 状态 |
|------|------|------|
| A. 因子IC | factor_values → factor_service → GET /factors/health → DashboardOverview → ECharts | ✅ |
| B. PT持仓与净值 | performance_series → paper_trading_service → GET /paper-trading/* → PTGraduation | ✅ |
| C. 回测结果 | backtest_run → backtest_service → GET /backtest/{id}/result → BacktestResults → ECharts | ✅ |
| D. 参数配置 | param_config → param_service → GET/PUT /params/* → SystemSettings → param_change_log | ✅ |
| E. 通知历史 | notifications → notification_service → GET /notifications → NotificationSystem | ✅ |

### 修复工作量: -（无需修复）

---

## 维度4: 调度与事件架构

### 现状

**Celery任务**: 7个任务, 4个队列(默认), Redis broker
- `run_backtest_task`: soft=7200s, hard=7500s
- `run_gp_mining`: soft=10800s, hard=11400s
- `daily_health_check_task`, `daily_signal_task`, `daily_execute_task`

**Celery Beat**: 4个定时任务已定义但**未激活**（Sprint 1.1 scope）
- gp-weekly-mining: 周日22:00
- daily-health-check: 工作日16:25
- daily-signal: 工作日16:30
- daily-execute: 工作日09:00

**Windows Task Scheduler**: 10个定时任务（当前生产主力）

### 问题清单
1. **Celery Beat未激活** — 定义了但未启动。当前由Windows Task Scheduler替代。Sprint 1.1将迁移。影响: 低

### 修复工作量: S

---

## 维度5: WebSocket通道审计

### 现状

| 通道 | 后端emit | 前端listen | 数据格式 | 断线重连 |
|------|---------|-----------|---------|---------|
| backtest:progress | ✅ events.py | ✅ useBacktestProgress | ✅ | ✅ 10次+退避 |
| backtest:status | ✅ events.py | ✅ | ✅ | ✅ |
| backtest:realtime_nav | ✅ events.py | ⚠️ 有polling fallback | ✅ | ✅ |
| backtest:log | ✅ events.py | ✅ | ✅ | ✅ |
| notification | ⚠️ 设计有 | ⚠️ NotificationSystem.tsx listen | 未验证 | ✅ |

### 问题清单
1. **backtest:realtime_nav前端主要用polling fallback** — WebSocket版本存在但可能不活跃。影响: 低

### 修复工作量: S

---

## 维度6: 错误处理与状态一致性

### 现状
- ✅ PageErrorBoundary: 存在，包裹所有路由 (`Layout.tsx`)
- ✅ Skeleton: PageSkeleton + CardSkeleton组件
- ✅ EmptyState: 存在但使用不统一
- ⚠️ API错误: 仅处理401(token过期)，其余错误冒泡到页面
- ⚠️ 后端: HTTPException ad-hoc使用，无统一错误格式

### 问题清单
1. **无全局Error Toast** — API 4xx/5xx错误只在个别页面处理，大部分静默失败。影响: 高
   - 位置: `frontend/src/api/client.ts:21-33` 仅处理401
2. **后端错误响应格式不统一** — 有的返回 `{"detail": "..."}`, 有的返回 `{"error": "..."}`, 有的直接字符串。影响: 中
3. **网络断开无检测** — 前端没有offline/online检测和提示。影响: 低

### 修复工作量: M

---

## 维度7: 端到端功能验证

### 现状
6条核心用户流程全部贯通:

| 流程 | 状态 | 关键文件 |
|------|------|---------|
| 1. 回测全流程 | ✅ | BacktestConfig→Runner→Results + WebSocket进度 |
| 2. 因子探索 | ✅ | FactorLibrary→FactorEvaluation + IC曲线 + 相关性 |
| 3. 参数修改 | ✅ | SystemSettings→load→edit→save + changelog |
| 4. PT监控 | ✅ | Dashboard→NAV→持仓→交易→因子健康 |
| 5. 通知流程 | ✅ | Backend trigger→DB→DingTalk→前端铃铛→已读 |
| 6. 挖掘任务 | ✅ | MiningTaskCenter→GP POST→Celery→进度→结果 |

### 修复工作量: -

---

## 维度8: 前端架构规范性

### 现状

**文件规模** (超500行的巨型组件):
| 文件 | 行数 | 建议 |
|------|------|------|
| DashboardOverview.tsx | 923 | 拆分KPI/Chart/Holdings子组件 |
| Execution.tsx | 885 | 拆分Modals到独立文件 |
| BacktestResults.tsx | 745 | 可拆分Chart/Table/Metrics |
| MiningTaskCenter.tsx | 728 | 可拆分GP/BF/LLM面板 |
| SystemSettings.tsx | 649 | 可拆分Tab内容 |
| PipelineConsole.tsx | 633 | 可拆分Flow/Approval/History |

**架构指标**:
- 页面: 19个 | 组件: 30+ | Zustand Store: 4个
- CSS: Tailwind 4.1 + inline style混用
- TypeScript: strict模式 ✅, any使用15处
- 路由: React Router v7, 嵌套路由 ✅, lazy loading ✅

### 问题清单
1. **8个组件超500行** — DashboardOverview 923行最严重。影响: 中
2. **无路由守卫** — 所有路由无ProtectedRoute包装。影响: 中（单用户系统暂可接受）
3. **Tailwind + inline style混用** — 部分组件大量inline style(C.bg1等theme token)。影响: 低

### 修复工作量: M

---

## 维度9: 安全与鉴权链路

### 现状
- ❌ 无后端认证模块（无JWT/session/OAuth）
- ✅ 前端有token注入逻辑（client.ts interceptor）但后端不校验
- ❌ 无路由守卫（所有页面公开）
- ⚠️ CORS硬编码 `localhost:3000`
- ✅ ADMIN_TOKEN保护执行操作API

### 问题清单
1. **所有API无认证保护** — 除execution_ops.py外，所有端点裸跑。影响: 中（单用户本地系统，非公网暴露）
2. **CORS硬编码开发域名** — `main.py:54` allow_origins只有localhost:3000。影响: 低
3. **前端无路由守卫** — router.tsx所有路由公开。影响: 低（同上，单用户）

### 修复工作量: L（如需完整认证体系）/ S（如仅加基本token校验）

---

## 维度10: 前端构建可行性

### 现状
- ✅ npm install: 26个依赖，无冲突
- ✅ tsc --noEmit: 0 error
- ✅ npm run build: 4.46s通过
- ⚠️ 1个chunk超500KB（ECharts + Recharts）
- TypeScript strict: true, noUnusedLocals: true

### 修复工作量: -

---

## 维度11: DB Model → API Schema → 前端Type 三层一致性

### 现状

| 实体 | DB Model | API Schema | 前端Type | 一致性 |
|------|---------|-----------|---------|--------|
| FactorValue | factor.py | factors.py | factors.ts | ⚠️ 需adapter |
| BacktestRun | backtest.py | backtest.py | backtest.ts | ✅ 完整映射 |
| Position | trade.py | dashboard.py | execution.ts | ✅ |
| PerformanceSeries | trade.py | backtest.py | backtest.ts | ✅ |
| AIParameter | (隐式) | params.py | SystemSettings | ⚠️ 前端用any |

### 问题清单
1. **AIParameter前端未定义TypeScript类型** — SystemSettings.tsx使用any。影响: 低

### 修复工作量: S

---

## 维度12: Celery任务 → 前端可见性

### 现状

| 任务 | 队列 | 预计耗时 | 前端可见 | 失败重试 | 取消 |
|------|------|---------|---------|---------|------|
| run_backtest_task | default | 2-30min | ✅ WS+轮询 | ✅ | ✅ |
| run_gp_mining | default | 30-180min | ✅ 轮询 | ⚠️ 仅新建 | ✅ |
| run_brute_force | default | 10-60min | ✅ 轮询 | ⚠️ 仅新建 | ✅ |
| daily_health_check | default | <1min | ❌ | N/A | N/A |
| daily_signal | default | 2-5min | ❌ | N/A | N/A |
| daily_execute | default | 1-3min | ❌ | N/A | N/A |

### 问题清单
1. **无真正的任务重试** — 只能新建任务，不能按task_id重试。影响: 低
2. **Beat任务前端不可见** — daily_*任务无UI展示。影响: 低

### 修复工作量: S

---

## 维度13: 通知系统端到端

### 现状
- ✅ 10+模板注册
- ✅ 5个API端点（列表/未读数/详情/已读/测试）
- ✅ DingTalk dispatcher + HMAC签名
- ✅ 4级限流（P0=60s, P1=600s, P2=1800s, P3=3600s）
- ✅ 前端NotificationSystem + Bell图标 + 未读badge

### 修复工作量: -

---

## 维度14: 配置与环境管理

### 现状
- ✅ .env + .env.example模板
- ✅ Pydantic Settings（11个配置组）
- ✅ Vite proxy配置（/api → localhost:8000）
- ✅ API密钥全部env管理，无硬编码

### 问题清单
1. **CORS应改为可配置** — 当前硬编码localhost:3000。可通过param系统动态配置。影响: 低

### 修复工作量: S

---

## 维度15: 前端测试覆盖

### 现状
- 前端测试: **3个文件, ~20个测试**
- 后端测试: **85个文件, ~2005个测试**
- **比例: 1:100**（严重不平衡）
- 覆盖: 仅groupFactorsByCategory等纯函数，无组件/页面测试

### 问题清单
1. **前端测试严重不足** — 19个页面/30+组件，仅3个测试文件。影响: 高

### 修复工作量: XL

---

## 维度16: API文档与自动发现

### 现状
- ✅ FastAPI自动生成Swagger(/docs) + ReDoc(/redoc)
- ✅ 20个API模块, ~81+端点
- ✅ 前端~81个API调用
- ✅ 覆盖率~90%（良好对齐）
- ✅ 所有端点有中文docstring + 类型注解

### 修复工作量: -

---

## 维度17: 性能与大数据量处理

### 现状
- ✅ 所有列表端点有分页（50-500 items上限）
- ✅ ECharts数据预聚合
- ✅ 通知限流防洪
- ❌ 无虚拟滚动

### 问题清单
1. **无虚拟滚动** — 大表格(持仓/通知/交易记录)超100行时可能卡顿。影响: 低（当前数据量小）
2. **因子values查询无日期范围限制** — 2.12亿行表，需确保WHERE条件+索引。影响: 中

### 修复工作量: M

---

## 维度18: 定时任务全景

### 现状

**Windows Task Scheduler (生产主力, 10个任务):**

| # | 任务名 | 触发 | 做什么 | 失败告警 | 前端可见 |
|---|--------|------|--------|---------|---------|
| 1 | QM-DailyBackup | 02:00 | PG备份+7天轮转 | ❌ | ❌ |
| 2 | QM-HealthCheck | 16:25 M-F | 健康检查 | ❌ | ❌ |
| 3 | DailySignal | 16:30 M-F | 信号生成 | ❌ | ❌ |
| 4 | DailyMoneyflow | 16:35 M-F | 资金流补数 | ❌ | ❌ |
| 5 | DataQualityCheck | 16:40 M-F | 数据巡检 | ❌ | ❌ |
| 6 | DailyExecute | 09:00 M-F | QMT live执行 | ❌ | ❌ |
| 7 | DailyReconciliation | 15:10 M-F | 对账 | ❌ | ❌ |
| 8 | DailyExecuteAfterData | 17:05 M-F | SimBroker执行 | ❌ | ❌ |
| 9 | FactorHealthDaily | 17:30 M-F | 因子衰减检测 | ❌ | ❌ |
| 10 | IntradayMonitor | 09:35-15:00 每5min | 盘中风控 | ❌ | ❌ |

**NSSM服务**: QuantMind-FastAPI, QuantMind-Celery

### 问题清单
1. **10个定时任务全部无失败告警** — 任务失败后静默，只记Event Viewer。影响: 高
2. **前端无任务状态可见性** — 运维只能通过Task Scheduler GUI查看。影响: 中

### 修复工作量: M

---

## 维度19: Claude Code自主发现

### 19.1 架构级问题

#### A. async/sync混用导致后端频繁阻塞（最严重）
**问题**: 所有API路由都是`async def`，但FactorService/BacktestService等使用sync psycopg2做DB查询。在uvicorn单worker模式下，任何sync调用都会阻塞整个event loop，导致所有并发请求超时。
**表现**: 本次审计中后端多次挂死(health超时)，每次需要重启服务。
**影响**: 高 — 生产环境任何慢查询都会让整个API不可用
**修复方案**:
- 短期: NSSM加`--workers 2`（已做）
- 中期: 将所有与sync服务交互的路由改为`def`（非`async def`）
- 长期: 统一迁移到async psycopg(asyncpg) + SQLAlchemy async session

#### B. realtime_data_service的xtdata调用可能阻塞
**问题**: `xtdata.get_full_tick()`是同步阻塞调用，在`def`路由中运行于线程池，但每次调用可能耗时1-3秒。5秒缓存缓解了频率，但缓存过期时的并发请求仍可能阻塞。
**位置**: `backend/app/services/realtime_data_service.py:78-90`
**修复**: 缓存层应使用锁机制，避免缓存穿透时多个线程同时调xtdata。

### 19.2 最需要优先修复的5个问题

1. **async/sync架构冲突** — 每次后端挂死都影响所有功能。工作量M，收益极高。
2. **定时任务无失败告警** — 09:00执行失败=当天不交易，16:30信号失败=次日无信号。加DingTalk通知仅需在每个脚本末尾加try/except + send_alert()。工作量S。
3. **前端测试几乎为零** — 19个页面0个测试覆盖。任何重构都是盲改。优先为核心页面(Dashboard/Portfolio/Execution)加snapshot测试。工作量L。
4. **全局Error Toast缺失** — API失败用户看不到任何反馈，只有空白或skeleton永远转。在apiClient拦截器加toast即可。工作量S。
5. **因子库FDR/Gate计算在API层** — 当前在`factors.py`的列表端点中计算gate_score，逻辑应该在Service/Engine层。影响: 低但违反分层原则。

### 19.3 最大技术债务

**sync psycopg2在async FastAPI中的使用** — 这是整个后端最大的结构性问题:
- CLAUDE.md写明 "sync psycopg2, Service内部不commit"
- 但main.py的db.py提供AsyncSession(asyncpg)
- 实际: 旧Service用sync psycopg2(通过get_sync_conn)，新API用AsyncSession(通过get_db)
- **两套DB连接共存**，代码中既有`conn.cursor().execute()`也有`await session.execute(text(...))`
- 这导致部分路由可以async，部分必须sync，混乱且容易阻塞

### 19.4 设计文档vs代码实现差异

**设计有但代码未实现:**
- AI闭环3个Agent(StrategyBuild/Diagnostic/RiskControl) — DEV_AI_EVOLUTION.md设计完整，代码仅有pipeline审批队列
- RegimeModifier — DEV_BACKTEST_ENGINE.md设计完整，代码有regime_modifier.py但未集成到信号链路
- 外汇策略(FX1-FX11调度) — DEV_SCHEDULER.md设计了11个外汇任务，代码完全未实现
- 多频率调仓 — multi_freq_backtest.py存在但未接入前端

**代码有但设计文档未提及:**
- realtime_data_service.py — 本次新建的实时数据聚合层
- execution_ops.py — 本次新建的QMT操作API
- QMT_ALWAYS_CONNECT机制 — 本次新增

### 19.5 前端架构改进建议

1. **组件拆分**: DashboardOverview(923行)应拆为 `<KPIGrid>`, `<EquityCurve>`, `<HoldingsTable>`, `<MonthlyHeatmap>`, `<IndustryDistribution>` 独立组件
2. **状态管理**: 当前Zustand 4个store足够，但建议增加executionStore集中管理交易状态(paused/connected/orders)，避免Execution.tsx内部useState过多
3. **数据获取统一**: queryKeys.ts已建立但仅Execution/Strategy使用，应全面推广到所有页面
4. **Theme Token**: 当前用`C.bg1`等inline style，建议迁移到Tailwind CSS variables，减少运行时style计算
5. **代码分割**: ECharts+Recharts占bundle 300KB+，可通过dynamic import按页面延迟加载

### 19.6 "迟早会爆"的隐患

1. **xtdata连接泄漏** — 每次`_get_realtime_ticks()`从模块级导入xtdata，如果QMT断连xtdata不释放资源，长时间运行后可能OOM
2. **psycopg2连接池缺失** — `get_sync_conn()`每次创建新连接，realtime.py虽有懒加载但无连接池。高并发下PG连接数可能耗尽
3. **Celery worker和Task Scheduler竞争** — 如果Celery Beat未来激活，和现有Task Scheduler的daily_signal/daily_execute会冲突（两套调度做同一件事）
4. **execution_audit_log无清理** — 表只增不删，长期运行后可能膨胀。需要定期归档
5. **WebSocket认证缺失** — Socket.IO `cors_allowed_origins="*"` 且connect事件无auth检查，任何人可连接WebSocket

---

## 优先级排序建议

### P0 — 立即修复（影响系统稳定性）
1. **async/sync路由修复** — 将FactorService/BacktestService等调用的路由从`async def`改为`def`，防止event loop阻塞。工作量: M
2. **定时任务失败告警** — 每个脚本加DingTalk失败通知。工作量: S

### P1 — 本周修复（影响用户体验）
3. **全局Error Toast** — apiClient interceptor加toast通知。工作量: S
4. **queryKeys全面推广** — 剩余15个页面的hardcoded queryKey替换。工作量: S

### P2 — 下周修复（提升工程质量）
5. **前端核心页面测试** — Dashboard/Portfolio/Execution的组件测试。工作量: L
6. **巨型组件拆分** — DashboardOverview等超500行组件。工作量: M

### P3 — Sprint级别（架构优化）
7. **统一DB层** — 消除sync/async两套DB连接共存。工作量: XL
8. **API契约统一** — 建立集中式字段转换层。工作量: M
