# QuantMind V2 后端全面审计报告

生成时间: 2026-04-02T19:30:00+08:00
审计目标: 为前端重建准备一个干净、可靠、一致的后端基础
代码修改: 无（纯诊断）

---

## 总览

| # | 维度 | 状态 | 问题数 | 关键发现 |
|---|------|------|--------|---------|
| 1 | async/sync架构 | ⚠️ | 2 | 两套DB连接共存，realtime用sync阻塞 |
| 2 | paper/live数据模型 | ✅ | 1 | 4表正确区分，信号链路固定paper |
| 3 | API契约一致性 | ❌ | 4 | 70%端点无类型，无统一响应格式 |
| 4 | API端点完整性 | ✅ | 2 | 62端点97%通过，40%缺execution_mode参数 |
| 5 | 数据库层 | ✅ | 2 | 43表健全，缺复合索引，少量N+1 |
| 6 | Celery任务 | ⚠️ | 3 | Beat未激活，与Task Scheduler重叠，无重试 |
| 7 | 服务依赖降级 | ⚠️ | 3 | QMT断连无自动重连，xtdata无超时 |
| 8 | 代码质量 | ✅ | 3 | 3个TODO，130+宽泛except，param_defaults 2031行 |
| 9 | 安全性 | ❌ | 5 | .env明文凭据，WebSocket无认证，SQL构造风险 |
| 10 | 日志与可观测性 | ⚠️ | 3 | structlog配置OK，无请求日志，无Sentry |
| 11 | 配置管理 | ⚠️ | 3 | .env.example不完整，硬编码路径，无生产安全验证 |
| 12 | 数据一致性 | ⚠️ | 3 | 内存缓存非线程安全，rate limit竞态条件 |
| 13 | 性能瓶颈 | ❌ | 5 | system/health 6s，缓存无锁，xtdata连接泄漏 |
| 14 | 文档与代码偏差 | ⚠️ | 4 | DEV_BACKEND目录结构过时，新模块未文档化 |
| 15 | 错误处理 | ⚠️ | 3 | HTTP状态码不统一，静默失败，无全局异常处理 |
| 16 | 技术债务 | ❌ | 6 | QMT代码转换散落4处，xtdata泄漏，DB双栈 |

**总计: 52个问题 — 5个CRITICAL, 12个HIGH, 20个MEDIUM, 15个LOW**

---

## 维度1: async/sync架构

### 现状
- 114个`async def`路由，全部使用AsyncSession(asyncpg)
- services层: signal_service, paper_trading_service等使用sync psycopg2
- API路由不直接调sync服务（通过Celery后台执行）
- **例外**: `realtime.py`用`def`(非async)调sync服务，`execution_ops.py`用`asyncio.to_thread()`包装sync QMT调用

### 问题清单
1. **[HIGH] 两套DB连接共存** — `app/db.py`(asyncpg pool_size=10) + `app/services/db.py`(psycopg2 每次新建)。修复: 统一到asyncpg。工作量: L
2. **[MEDIUM] realtime_data_service全sync** — 在`def`路由的线程池中运行，但缓存无锁保护。修复: 加threading.Lock。工作量: S

### 修复工作量: L（统一DB层需2-3周）

---

## 维度2: paper/live数据模型

### 现状
- 4张表有execution_mode列: performance_series, position_snapshot, trade_log, signals
- performance_series PK已修复为(trade_date, strategy_id, execution_mode)
- position_snapshot PK已含execution_mode
- 信号始终在paper模式生成，live执行通过QMT直接操作

### 问题清单
1. **[LOW] 信号固定paper模式** — `signal_service.py`写入execution_mode='paper'，live交易读paper信号。设计上合理但应文档化。

### 修复工作量: S

---

## 维度3: API契约一致性

### 现状
- ~30%端点有Pydantic response_model，70%返回`dict[str, Any]`
- 无统一响应格式（无ApiResponse[T]包装器）
- 分页: page/page_size（回测）vs offset/limit（其他）混用
- 错误格式: 统一`{"detail": "..."}` (FastAPI默认)

### 问题清单
1. **[HIGH] 70%端点无类型安全** — 返回untyped dict，前端无法自动生成类型。修复: 添加Pydantic response models。工作量: L
2. **[MEDIUM] 无统一响应包装器** — 成功/错误/分页格式各异。修复: 创建ApiResponse[T]。工作量: M
3. **[MEDIUM] 分页模式不统一** — page vs offset两种方式。修复: 统一为offset/limit。工作量: M
4. **[LOW] 百分比格式混乱** — 有的返回0.15，有的返回15。修复: 统一约定。工作量: S

### 修复工作量: L

---

## 维度4: API端点完整性

### 现状
- 62个GET端点，冒烟测试60通过、1慢、1超时
- 20-25个参数化路由未覆盖
- 40%数据端点缺execution_mode参数

### 问题清单
1. **[MEDIUM] 40%端点缺execution_mode** — paper-trading/positions等硬编码paper。修复: 添加参数。工作量: M
2. **[LOW] 参数化路由未测试** — {run_id}, {strategy_id}等路径。修复: 扩展smoke_test。工作量: S

### 修复工作量: M

---

## 维度5: 数据库层

### 现状
- DDL定义43张表，全部在代码中引用
- asyncpg连接池: pool_size=10, max_overflow=5
- 全部SQL使用参数化查询（text() + :param）

### 问题清单
1. **[MEDIUM] 缺少复合索引** — (strategy_id, execution_mode, trade_date)组合查询缺索引。修复: ALTER TABLE ADD INDEX。工作量: S
2. **[MEDIUM] 2-3处N+1查询** — position_repository行业聚合、signal_service行业分组。修复: 改用GROUP BY SQL。工作量: S

### 修复工作量: S

---

## 维度6: Celery任务

### 现状
- 7个Celery任务（backtest, GP mining, bruteforce, daily pipeline×3, onboarding）
- Beat定义了4个定时任务但**未激活**
- Windows Task Scheduler是当前主力（10个任务）

### 问题清单
1. **[MEDIUM] Beat与Task Scheduler重叠** — 激活Beat前需禁用对应Scheduler任务。工作量: S
2. **[LOW] GP/回测无自动重试** — max_retries=0，失败即终。工作量: S
3. **[LOW] 结果存储仅24h TTL** — 爆发任务可能累积Redis内存。工作量: S

### 修复工作量: S

---

## 维度7: 服务依赖降级

### 现状
- 7个外部依赖: PG, Redis, QMT, xtdata, Tushare, DingTalk, DeepSeek
- QMT断连: API返回503，无自动重连
- xtdata挂起: 返回空数据，无超时
- DingTalk失败: 记录日志，不阻塞

### 问题清单
1. **[HIGH] QMT无自动重连** — 断连后需手动重启。修复: 在health_check中检测并重连。工作量: M
2. **[HIGH] xtdata无超时** — get_full_tick()可能无限阻塞。修复: 加asyncio.wait_for()。工作量: S
3. **[MEDIUM] PG健康检查无重试** — 单次失败即标记DOWN。修复: 加3次重试。工作量: S

### 修复工作量: M

---

## 维度8: 代码质量

### 现状
- 3个TODO注释（backtest参数扫描、报告生成、PT收益精确计算）
- 130+ `except Exception` 宽泛捕获
- 85个测试文件
- ruff配置完整（E/F/W/I/N/UP/B/A/SIM）

### 问题清单
1. **[MEDIUM] 130+宽泛except** — 应更具体(ValueError, ConnectionError等)。工作量: M
2. **[LOW] param_defaults.py 2031行** — 应拆分为模块。工作量: M
3. **[LOW] 3个TODO待实现** — backtest参数扫描、报告生成、PT精确计算。工作量: M

### 修复工作量: M

---

## 维度9: 安全性

### 现状
- CORS: localhost:3000（开发）
- 认证: ADMIN_TOKEN（执行操作）+ REMOTE_API_KEY（远程状态）
- 无JWT/OAuth
- WebSocket: 无认证

### 问题清单
1. **[CRITICAL] .env含明文凭据** — Tushare token, DeepSeek key, DingTalk webhook, QMT账号。修复: .gitignore + 轮换密钥。工作量: S
2. **[HIGH] WebSocket无认证** — 任何客户端可连接接收实时数据。修复: 加auth检查。工作量: S
3. **[HIGH] 硬编码DB URL** — backtest_tasks.py, mining_tasks.py中直接写连接字符串。修复: 统一用settings。工作量: S
4. **[MEDIUM] SQL动态构造** — backtest.py where_sql用f-string构建。修复: 参数化。工作量: S
5. **[MEDIUM] 无生产安全验证** — 空ADMIN_TOKEN/REMOTE_API_KEY启动不报错。修复: 启动时检查。工作量: S

### 修复工作量: M

---

## 维度10: 日志与可观测性

### 现状
- structlog JSON日志，10MB轮转×7文件
- 降噪: uvicorn/sqlalchemy/socketio设为WARNING
- 无请求追踪，无Sentry

### 问题清单
1. **[MEDIUM] 无请求/响应日志** — 无法追踪请求流。修复: 加FastAPI middleware。工作量: S
2. **[MEDIUM] 无错误追踪服务** — 错误仅本地日志。修复: 集成Sentry。工作量: M
3. **[LOW] 无性能指标** — 无请求延迟、DB查询耗时统计。修复: 加metrics middleware。工作量: M

### 修复工作量: M

---

## 维度11: 配置管理

### 现状
- Pydantic Settings, 22个配置项
- .env + .env.example
- 优先级: 环境变量 > .env > 默认值

### 问题清单
1. **[MEDIUM] .env.example不完整** — 缺QMT_ALWAYS_CONNECT等新配置。修复: 同步。工作量: S
2. **[MEDIUM] 硬编码路径** — 日志目录、xtquant路径应可配置。修复: 加到Settings。工作量: S
3. **[LOW] 无生产/开发环境区分** — 所有配置都走.env。修复: 文档化必设项。工作量: S

### 修复工作量: S

---

## 维度12: 数据一致性

### 现状
- AsyncSession: 请求级事务（get_db commit/rollback）
- 内存缓存: realtime_data_service的_cache无锁
- Rate limiting: execution_ops的_action_counts无锁

### 问题清单
1. **[HIGH] 缓存非线程安全** — _get_cached()的check-then-act竞态。修复: 加threading.Lock。工作量: S
2. **[HIGH] Rate limit竞态** — _action_counts全局dict在多worker下不安全。修复: 改用Redis。工作量: S
3. **[LOW] 服务层偶尔commit** — backtest_service.py:84直接commit，违反"Service不commit"规则。修复: 移到API层。工作量: S

### 修复工作量: S

---

## 维度13: 性能瓶颈

### 现状
- /api/system/health: 6.1s（Celery inspect subprocess 8s timeout）
- /api/system/scheduler: 3.3s（PowerShell subprocess 10s timeout）
- /api/execution/trades: 超时（QMT盘后查询慢）

### 问题清单
1. **[HIGH] system/health 6s** — subprocess查Celery/磁盘/内存。修复: 缓存30s。工作量: S
2. **[HIGH] system/scheduler 3.3s** — PowerShell每次新建进程。修复: 缓存60s。工作量: S
3. **[HIGH] 缓存stampede** — TTL过期时多线程同时调xtdata。修复: Lock + stale-while-revalidate。工作量: S
4. **[HIGH] xtdata连接泄漏** — 每次reimport无清理。修复: 模块级单次import + 上下文管理。工作量: M
5. **[MEDIUM] N+1查询** — sector分布在Python端聚合。修复: GROUP BY SQL。工作量: S

### 修复工作量: M

---

## 维度14: 文档与代码偏差

### 现状
- DEV_BACKEND.md描述的目录结构部分过时
- SYSTEM_RUNBOOK.md调度表已同步更新
- 新模块(realtime_data_service, execution_ops)未文档化

### 问题清单
1. **[MEDIUM] DEV_BACKEND.md目录过时** — 写`routers/`实际是`api/`。修复: 更新。工作量: S
2. **[MEDIUM] 新模块未文档化** — realtime_data_service.py, execution_ops.py。修复: 补文档。工作量: S
3. **[LOW] Service commit规则偏差** — 文档说"不commit"但代码有。修复: 更新规则或代码。工作量: S
4. **[LOW] RegimeModifier/FX未实现** — 设计文档有但代码未接入。修复: 标注为Phase D。工作量: S

### 修复工作量: S

---

## 维度15: 错误处理

### 现状
- HTTPException用法一致（detail字段）
- 服务层: ValueError → API层转HTTPException
- 无全局异常处理器

### 问题清单
1. **[MEDIUM] HTTP状态码不统一** — 同类错误在不同模块用不同状态码。修复: 制定规范。工作量: S
2. **[MEDIUM] 静默失败** — realtime_data_service返回{}而不报错。修复: 返回时带data_source标记。工作量: S
3. **[LOW] 无全局异常处理器** — 未捕获的异常返回generic 500。修复: 加exception_handler。工作量: S

### 修复工作量: S

---

## 维度16: 技术债务（Claude自主发现）

### 本Session发现的问题汇总

| 发现 | 位置 | 临时方案 | 正确方案 |
|------|------|---------|---------|
| QMT代码后缀转换散落4处 | realtime_data_service, execution_ops, qmt_execution_adapter, daily_reconciliation | 每处inline处理 | 提取到utils/qmt_code.py |
| industry列名不一致 | symbols.industry_sw1 vs 代码中用"industry" | 手动指定列名 | 统一命名或文档化 |
| NSSM无reload | 服务配置 | --workers 2 | 迁移到supervisor或加reload |
| performance_series PK修复 | ALTER TABLE | 已修复 | 纳入DDL |
| xtdata path双层嵌套 | .venv/Lib/site-packages/Lib/site-packages | 每个文件append path | 提取到utils/xtquant_path.py |
| 信号paper vs 执行live | 信号链路 | drift查询分离signal_mode/position_mode | 文档化设计决策 |

### 问题清单
1. **[CRITICAL] xtdata连接泄漏** — 长期运行(周级)可能OOM。修复: 模块级import + 连接管理。工作量: M
2. **[HIGH] QMT代码转换DRY违反** — 4处重复逻辑。修复: utils/qmt_code.py。工作量: S
3. **[HIGH] xtquant路径DRY违反** — 3+处重复路径append。修复: utils/xtquant_path.py。工作量: S
4. **[MEDIUM] 缓存实现无锁** — threading.Lock缺失。修复: 加锁。工作量: S
5. **[MEDIUM] 内存rate limit** — 多worker不共享。修复: Redis rate limit。工作量: S
6. **[LOW] audit_log无清理策略** — 只增不删。修复: 30天归档。工作量: S

### 修复工作量: M

---

## 修复优先级排序

### P0 — 必须立即修复（影响系统稳定）

| # | 问题 | 维度 | 工作量 | 理由 |
|---|------|------|--------|------|
| 1 | 缓存加threading.Lock | D12/D13 | S (5行) | 并发请求下cache stampede |
| 2 | system/health + scheduler加缓存 | D13 | S (20行) | 6s端点阻塞所有请求 |
| 3 | xtdata连接泄漏修复 | D16 | M (50行) | 长期运行OOM风险 |
| 4 | .env凭据保护 | D9 | S (10行) | 安全硬伤 |

### P1 — 前端重建前必须完成

| # | 问题 | 维度 | 工作量 | 理由 |
|---|------|------|--------|------|
| 5 | API统一响应格式ApiResponse[T] | D3 | M | 前端类型系统基础 |
| 6 | 所有端点加execution_mode参数 | D4 | M | 前端需要查询live数据 |
| 7 | Pydantic response models | D3 | L | 前端自动生成TypeScript类型 |
| 8 | 分页格式统一 | D3 | M | 前端列表组件标准化 |
| 9 | 百分比/数字格式约定 | D3 | S | 前端显示一致性 |

### P2 — 应尽快修复（影响可靠性）

| # | 问题 | 维度 | 工作量 | 理由 |
|---|------|------|--------|------|
| 10 | QMT自动重连 | D7 | M | 盘中断连=无法交易 |
| 11 | WebSocket认证 | D9 | S | 安全 |
| 12 | 硬编码DB URL清理 | D9 | S | 安全 |
| 13 | Redis rate limiting | D12 | S | 多worker安全 |
| 14 | DB复合索引 | D5 | S | 查询性能 |

### P3 — 技术债务清理

| # | 问题 | 维度 | 工作量 |
|---|------|------|--------|
| 15 | QMT代码转换utils提取 | D16 | S |
| 16 | xtquant路径utils提取 | D16 | S |
| 17 | except Exception → 具体类型 | D8 | M |
| 18 | DEV_BACKEND.md更新 | D14 | S |
| 19 | 请求日志middleware | D10 | S |
| 20 | param_defaults.py拆分 | D8 | M |

---

## 前端重建前必须完成的Checklist

```
[ ] API契约统一:
    [ ] 创建ApiResponse[T]包装器 (成功/错误/分页)
    [ ] 所有数据端点加execution_mode参数 (默认live)
    [ ] 统一分页为offset/limit
    [ ] 统一百分比格式 (小数0.15, 前端×100显示)
    [ ] 统一日期格式 (ISO 8601字符串)

[ ] API类型安全:
    [ ] 所有端点添加Pydantic response_model
    [ ] 导出OpenAPI schema → 前端自动生成TypeScript types

[ ] 性能基线:
    [ ] 所有端点响应<3秒 (system/health除外)
    [ ] 缓存threading.Lock加锁
    [ ] xtdata连接管理

[ ] 数据一致性:
    [ ] live数据链路完整 (position_snapshot + performance_series每日写入)
    [ ] 信号查询paper/live模式正确

[ ] 安全基线:
    [ ] WebSocket认证
    [ ] .env不入git
    [ ] 硬编码凭据清理
```

---

## 架构建议

如果我来设计，后端应该是：

### 1. 统一async
- 全部使用asyncpg (SQLAlchemy async)
- 消除psycopg2依赖
- services层: `async def method(self, session: AsyncSession)`
- engines层: 保持纯计算无IO

### 2. 类型安全API
```python
class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None
    error: str | None = None
    meta: PaginationMeta | None = None
```
所有端点: `@router.get("/factors", response_model=ApiResponse[list[FactorSummary]])`

### 3. 统一数据访问层
```
API Route → Service → Repository → AsyncSession
              ↓
           Engine (纯计算)
```
Repository封装SQL，Service编排业务逻辑，API处理HTTP。

### 4. 配置驱动的execution_mode
```python
class ExecutionContext:
    mode: Literal["paper", "live"]
    strategy_id: UUID

    @classmethod
    def from_request(cls, request: Request) -> "ExecutionContext":
        ...
```
所有端点通过Depends注入ExecutionContext，不再硬编码。

### 5. xtdata/QMT连接池
```python
class QMTConnectionPool:
    def get_connection(self) -> ContextManager[MiniQMTBroker]:
        ...
    def get_tick_data(self, codes: list[str]) -> dict:
        # 模块级单次import, 带超时, 带连接复用
        ...
```

---

## 全面思考

### 1. 后端何时算"准备好"？
当以下全部满足：
- 所有GET端点<3s响应（当前2个超6s）
- API类型100%覆盖（当前30%）
- 0个CRITICAL安全问题（当前1个）
- live数据链路每日自动写入（当前依赖对账脚本）
- 缓存线程安全（当前不安全）

### 2. 最大3个结构性问题
1. **两套DB连接共存** — 根源问题，导致性能/架构/维护三方面问题
2. **API无类型安全** — 70%端点返回dict，前端只能手动mapping
3. **paper/live信号链分离** — 信号永远paper模式生成，live执行读paper信号，语义混乱

### 3. 2周优先做什么？
- Week 1: P0全部(缓存锁/性能缓存/xtdata泄漏/.env保护) + API响应格式统一
- Week 2: execution_mode参数化 + Pydantic models(核心20个端点) + WebSocket认证

### 4. 只有看完整代码才能发现的问题
- **xtdata每次reimport** — 设计文档不会提到import行为导致的连接泄漏
- **industry_sw1列名** — DDL定义正确但代码中用错列名的bug
- **rate limit内存竞态** — 多worker下全局dict的线程安全问题
- **QMT代码后缀散落** — 每个新文件都会重新实现一次strip逻辑
- **subprocess在async路由中** — system/health的Celery检查实际是subprocess阻塞

### 5. 其他想说的
这个项目的**底层设计是好的** — engines纯计算、Service层隔离业务逻辑、Repository封装数据访问。问题出在**过渡期的实现不一致**：旧代码sync、新代码async、临时workaround累积。如果统一到async + 类型安全API，后端会是一个非常solid的基础。前端重建的最大阻碍不是功能缺失，而是API契约不一致——修好这个，前端可以自动生成80%的类型代码。
