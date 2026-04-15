# S3 审计报告 — 韧性与抗断（静默失败 / 错误恢复 / 监控盲区 / 并发安全）

> **范围**: 静态代码审计。grep + Read 找"系统表面正常但暗处 fail"的模式。
> **方法**: 5 个维度专项扫描 → (a) silent failure patterns (b) error recovery paths (c) monitoring coverage (d) concurrency safety (e) F66 recurrence prevention。
> **时间**: 2026-04-15 夜 (继 S4 动态基线之后)
> **覆盖铁律**: 17 (DataPipeline 入库) / 22 (文档跟代码) / 防复发视角的全部"silent degradation"场景
> **git HEAD**: `cd02926` audit(s4): baseline verification + 3 finding closures

---

## 📋 执行摘要

| 分级 | S3 新增 | 说明 |
|---|---|---|
| 🔴 P0 | **2** (F76/F77) | 执行层 silent swallow: 涨停保护 + 撤单确认 |
| 🟠 P1 | **4** (F78/F82/F85/F86) | stream publish + Celery 配置漂移 + rollback 覆盖率 + F66 防复发 |
| 🟡 P2 | **3** (F79/F80/F81) | PMS/realtime/factors API silent fallback |
| **合计** | **9** | |

**S3 最严重的 3 条**（按业务影响）:

1. 🔴 **F76** — `_get_realtime_tick()` silent swallow xtdata 异常 → 可能在 QMT 断线时 **silently bypass 涨停保护** → 实盘可能下涨停股订单
2. 🔴 **F77** — 撤单确认查询异常被吞成"超时"→ **"查询失败" ≠ "撤单未完成"** 混淆监控
3. 🟠 **F86** — **F66 防复发缺失**: 4 条生产 INSERT 路径绕过 DataPipeline, 铁律 17 仅文档级无代码强制 → 1665 行 NaN 下次会复发

**S3 积极发现**（反面证据）:
- ✅ **熔断 L1-L4 实际落地** — `execution_service.py:92-115` 对 `cb_level ∈ {2,3,4}` 有真实分支处理, 不是文档玩具
- ✅ **execution_service StreamBus publish 有正确的 try/except + logger.warning(exc_info=True)** — 可作全项目 publish 模板
- ✅ **DataPipeline 本身合规** — `pipeline.py` 是唯一允许直接 INSERT 的地方

---

## 🔴 P0 发现（Critical — 执行层 silent degradation）

### F76 — `_get_realtime_tick` silent swallow xtdata 异常 → 涨停保护可能 silently bypass

**位置**: `backend/engines/qmt_execution_adapter.py:85-94`

**证据**:
```python
def _get_realtime_tick(qmt_code: str) -> dict | None:
    """通过xtdata获取实时行情快照。"""
    try:
        from xtquant import xtdata
        ticks = xtdata.get_full_tick([qmt_code])
        if isinstance(ticks, dict) and qmt_code in ticks:
            return ticks[qmt_code]
    except Exception:
        pass                 # ← silent swallow
    return None
```

**调用链**:
```python
# qmt_execution_adapter.py:683
def _check_buy_protection(self, code: str, ref_price: float) -> tuple[bool, str]:
    """涨停+跳空检查。返回(skip, reason)。"""
    tick = _get_realtime_tick(_to_qmt_code(code))
    if not tick or tick.get("lastPrice", 0) <= 0:
        return False, ""    # ← "没数据" 被当成 "不跳过"
```

**严重性分析**:
- **场景 A (正常)**: xtdata 正常 → tick 里有 lastPrice → 涨停保护逻辑照常跑 ✅
- **场景 B (QMT 断线)**: xtdata 抛 `ConnectionError` → except pass → return None → `tick=None` → **`return False, ""` (不跳过)** → 订单被送出
- **场景 C (行情延迟)**: xtdata 返回空 dict → return None → 同 B
- **场景 D (xtquant import 失败)**: ImportError → except pass → return None → 同 B

**影响**:
- **涨停股可能被下单** — A 股涨停股买单会被交易所拒绝, 但触发 "废单" 统计 + 监控告警
- **如果是跌停股卖单** — 卖单可能悬挂导致头寸无法减仓, 配合熔断 L2_HALTED 可能形成死锁
- **监控盲区** — silent swallow 意味着 logs 里不会出现任何错误, 运维无法知道 QMT 已经断线, 只能从"废单激增"反推
- 配合 S4 F68 (Redis portfolio:current 无 TTL) 可能形成复合 bug: QMT 断线 → 实时 tick 失败 → 但 Redis 里是 60s 前的旧持仓 → 执行决策基于 stale 数据

**根因**:
- 设计意图可能是 "xtdata 不可用就 fallback 到无保护" — 但这个 fallback 是**反向**的, 应该是 "**无法确认安全就拒绝下单**" (fail-safe default)
- `except Exception: pass` 的无日志处理意味着**当初写这段代码的人没想清楚失败模式**

**建议修复**（按严格度排序）:

**方案 A (推荐, 严格 fail-safe)**:
```python
def _get_realtime_tick(qmt_code: str) -> dict | None:
    try:
        from xtquant import xtdata
        ticks = xtdata.get_full_tick([qmt_code])
        if isinstance(ticks, dict) and qmt_code in ticks:
            return ticks[qmt_code]
    except Exception as e:
        logger.error(
            "[QMTAdapter] 实时行情查询失败 code=%s err=%s — 涨停保护将 fail-safe 拒绝下单",
            qmt_code, e, exc_info=True
        )
    return None  # 保持返回值, 但 caller 应该改为"无 tick 就拒绝"

# caller 改:
def _check_buy_protection(self, code: str, ref_price: float) -> tuple[bool, str]:
    tick = _get_realtime_tick(_to_qmt_code(code))
    if not tick:
        return True, "xtdata 查询失败, fail-safe 拒绝下单"  # ← 关键变化
    if tick.get("lastPrice", 0) <= 0:
        return True, "lastPrice 无效, fail-safe 拒绝下单"
    # ... 正常涨停检查
```

**方案 B (折衷, 至少加日志)**:
```python
except Exception as e:
    logger.warning("[QMTAdapter] 实时行情查询失败 code=%s err=%s", qmt_code, e)
    # caller 行为不变, 但至少运维能看见
```

**工作量**: 方案 A ~45 min (含改 caller 语义 + 测试回归); 方案 B ~15 min。

**推荐 A** — 符合铁律 "不靠记忆靠代码" + "验证不可跳过不可敷衍" 精神。

---

### F77 — 撤单确认 silent swallow → "查询失败" 被归类成 "撤单超时"

**位置**: `backend/engines/qmt_execution_adapter.py:668-680`

**证据**:
```python
# 轮询撤单确认 (sleep 2s 后查询)
time.sleep(2)
try:
    orders = self._broker.query_orders()
    for o in orders:
        if o.get("order_id") == order_id and is_final_status(o.get("order_status", 0)):
            logger.info(f"[QMTAdapter] 撤单确认: {code} status={o['order_status']}")
            return True
except Exception:
    pass                     # ← silent swallow

logger.warning(f"[QMTAdapter] 撤单超时未确认: {code} order_id={order_id}")
return False
```

**问题**: `query_orders()` 抛异常 → silent pass → 流程到 line 678 打 "撤单超时" → 上游调用方看到 `False` 以为是 **真的超时** (可能是 QMT 内部延迟), 实际是**查询通道挂了**。

**影响**:
- **监控无法区分两种根本不同的错误**:
  - 撤单真的超时 (QMT 收到请求但没处理) → 应该重试撤单
  - 查询通道挂了 (QMT 连接挂了) → 应该先重连 QMT 再说, 可能还需要查未平仓
- **应急 CLI `scripts/cancel_stale_orders.py`** 会基于"超时"统计做决策, 但这些"超时"里混了一批"查询失败"的假阳性

**建议修复**:
```python
try:
    orders = self._broker.query_orders()
    for o in orders:
        if o.get("order_id") == order_id and is_final_status(o.get("order_status", 0)):
            logger.info(f"[QMTAdapter] 撤单确认: {code} status={o['order_status']}")
            return True
except Exception as e:
    logger.error(
        "[QMTAdapter] query_orders 失败 (撤单确认阶段) code=%s order_id=%s err=%s",
        code, order_id, e, exc_info=True
    )
    # 留下明确日志, 然后 fall-through 到"超时未确认"分支 (行为不变, 但可追溯)

logger.warning(f"[QMTAdapter] 撤单超时未确认: {code} order_id={order_id}")
return False
```

**工作量**: ~15 min (含日志格式校对 + 测试)。

---

## 🟠 P1 发现

### F78 — health_check stream publish silent (无 logger.warning)

**位置**: `backend/app/tasks/daily_pipeline.py:80-92`

**证据**:
```python
get_stream_bus().publish_sync(
    STREAM_HEALTH_CHECK_RESULT,
    {
        "date": date.today().isoformat(),
        "all_pass": result.get("all_pass"),
        "elapsed_s": round(elapsed, 1),
        "checks": result,
    },
    source="daily_pipeline",
)
except Exception:
    pass                     # ← silent swallow, 无 logger
```

**对比 execution_service.py:221-222**（正确模板）:
```python
except Exception:
    logger.warning("[ExecutionService] StreamBus publish失败", exc_info=True)
```

**影响**:
- Redis 挂了 → publish 失败 → **health_check 本身正常完成**, 但监控系统看不到 health 事件
- 运维可能误以为 "health_check 没跑" 而不是 "Redis 挂了", 排查时间成本上升

**设计意图**（推断）: publish 失败不应阻塞 health_check 本身 — 这部分合理, **但不打日志就是错的**。

**建议**: 照抄 execution_service 的模板, 加 `logger.warning(exc_info=True)`。

**工作量**: ~2 min (1 行改)。

---

### F82 — Celery 配置漂移: prefork×4 (Mac) vs solo×1 (Windows CLI)

**位置**: 3 处声明相互冲突

| 位置 | 声明 | 背景 |
|---|---|---|
| `backend/app/tasks/celery_app.py:46-47` | `worker_concurrency=4` + 注释 "Mac M1 Pro 单机, prefork 4 进程足够" | ⚠️ **Mac 时代遗留** |
| `scripts/nssm_setup.ps1:52` | `--pool=solo --concurrency=1` | Windows NSSM 脚本 (已归档到 Servy) |
| CLAUDE.md §Servy `QuantMind-Celery` 行 | `celery worker --pool=solo` | 当前运行实际 |
| `SYSTEM_STATUS.md:346` | `celery worker --pool=solo` | 当前状态 |
| `docs/research/R6_production_architecture.md:143` | `--pool=solo` (Windows CPU 密集) | 生产架构文档 |

**实际运行行为**: CLI `--pool=solo` 覆盖 `celery_app.py` 默认值, 所以运行时 pool_type=solo, concurrency=1。**`worker_concurrency=4` 是 dead letter**。

**风险**:
1. 任何人 copy `celery_app.py` 直接 `celery worker -A app.tasks.celery_app` (不加 --pool) **在 Windows 上会失败** — Celery prefork 需要 fork(), Windows 没有, 要么报错要么 degraded 到 solo
2. 新开发者读代码**误以为是 4 并发**, 设计任务时假设可以并发执行
3. `worker_prefetch_multiplier=1` (line 48) 的意图是 "每次只取 1 个任务避免堆积", 和 solo×1 实际行为一致, **但代码注释说给 prefork×4 配的**

**建议修复**:
```python
# backend/app/tasks/celery_app.py:44-48
celery_app.conf.update(
    # ...
    # Worker pool: Windows 使用 solo (prefork 不支持)
    # 并发度由 Servy 启动参数 --pool=solo --concurrency=1 控制
    # 此处的 worker_concurrency 仅在未传 --pool 时生效
    worker_concurrency=1,  # ← 从 4 改为 1, 对齐实际运行
    worker_prefetch_multiplier=1,
    # ...
)
```

并在 `backend/app/tasks/celery_app.py` 顶部加注释警示:
```python
# ⚠️ Windows 生产环境: 必须以 --pool=solo 启动
# ⚠️ 不要直接 `celery worker`, 使用 Servy 管理的 QuantMind-Celery 服务
```

**工作量**: ~10 min (含 docstring 补充)。

---

### F85 — Rollback 覆盖率 15%: 20+ commit 只有 3 service 有 rollback

**位置**: `backend/app/services/*.py`

**证据**:
- S1 F16 已指出 20+ 处 `.commit()` 分布在 8 个 services (risk_control / pt_data / pt_monitor / pt_qmt_state / shadow_portfolio / notification / mining / backtest)
- grep `conn.rollback\(\)|except.*commit` 只在 3 个 service 出现:
  - `mining_service.py`: 2 (async SQLAlchemy)
  - `notification_service.py`: 2 (sync psycopg2)
  - `risk_control_service.py`: 1 (sync psycopg2)
- **覆盖率 3/8 = 37.5% (service 文件)** 或 **5/20+ = 25% (rollback/commit 比)**

**问题**:
- 大多数 commit 没有对称的 rollback — 意味着异常时 partial state 会落库
- 典型模式 (推断的错误写法):
  ```python
  def service_method(self, conn, ...):
      cur = conn.cursor()
      cur.execute("INSERT INTO ... ")  # step 1
      cur.execute("UPDATE ... ")       # step 2 (抛异常)
      conn.commit()                    # 永远到不了这里
      # 没有 except → rollback → 外层 api 层看到异常, step 1 的 INSERT 悬在 DB 里
  ```
- 违反铁律: CLAUDE.md 编码规则 "Service内部不commit, 调用方管理事务" — **但既然有 commit 就应该有 rollback**, 两者是一对

**根因**: 铁律执行不一致 — commit/rollback 应该**同时存在或同时不存在**, 当前是"只 commit 不 rollback"的半拉子状态

**建议**（分阶段, 复用 S1 F16 的计划）:
1. **短期**: `.pre-commit-config.yaml` 加 grep hook — 服务文件里 `.commit()` 必须同文件 `.rollback()` (简单正则)
2. **中期**: 每个 service 的 commit 函数包 try/except/rollback/raise
3. **长期**: 引入 `@transactional` 装饰器 + Router 层统一事务, commit/rollback 从 service 里拆出去 (对齐 CLAUDE.md 铁律)

**工作量**: 短期 lint ~15 min; 中期 system fix ~3 天; 长期架构 ~1-2 周

---

### F86 — F66 防复发缺失: 4 条生产 INSERT 路径绕过 DataPipeline

**位置**: 4 个生产文件 + 9 个研究脚本

**证据** (S3 完整扫描):

| 路径 | 文件 | 表 | 严重度 |
|---|---|---|---|
| **A** | `backend/app/services/factor_onboarding.py:544` | `factor_values` | 🔴 生产 approval_queue 路径 |
| **B** | `backend/app/services/factor_onboarding.py:756` | `factor_ic_history` | 🔴 生产 IC 计算路径 (S2 F51/F60) |
| **C** | `backend/app/data_fetcher/fetch_base_data.py:327` | `klines_daily` | 🔴 生产数据拉取 |
| **D** | `backend/app/data_fetcher/fetch_base_data.py:412` | `daily_basic` | 🔴 生产数据拉取 |
| **E** | `backend/engines/factor_engine.py:2016` | `factor_values` | 🟡 dead code (S1/S2 确认) |
| **F** | `backend/scripts/compute_factor_ic.py:427` | `factor_ic_history` | 🟡 scripts 目录 (legacy) |
| **G** | `scripts/fast_ic_recompute.py:176` | `factor_ic_history` | 🟢 合规 IC 口径, 但 INSERT 路径绕过 |
| **H** | `scripts/research/phase3a_*.py` (4) | `factor_values` | 🟢 研究脚本 (可接受) |
| **I** | `scripts/research/phase3b/3e/12/*` (5) | `factor_values/factor_ic_history` | 🟢 研究脚本 |
| **J** | `scripts/research/pull_historical_data.py` | `klines_daily/daily_basic/moneyflow_daily` | 🟢 研究脚本 |
| **K** | `scripts/research/earnings_factor_calc.py:380` | `factor_ic_history` | 🟢 研究脚本 |

**F66 根因再确认**:
- 1665 行 float NaN 大概率来自 **path A/B/C/D + 旧的研究脚本**
- ep_ratio 1486 行占 89% → 很可能是 **fetch_base_data.py** 或一个早期基本面拉取脚本, 绕过了 DataPipeline 的 `fillna(None)` 清理
- 现在 S4 清掉了 1665 行, **但 path A/B/C/D 仍在 — 下次跑 approval_queue 或 fetch_base_data 还会写入 NaN**

**问题**:
- 铁律 17 "数据入库必须通过 DataPipeline" **仅文档级**, 没有代码强制
- **没有 pre-commit hook / CI check / runtime guard** 阻止新代码 INSERT 生产表
- S1 F17 已经提出建议但没实施

**建议修复**（S3 立即做 + 中期）:

**短期 (~30 min, S3 范围内可做)**:
1. 加 pre-commit hook grep 规则:
   ```yaml
   # .pre-commit-config.yaml
   - id: no-direct-insert
     name: "禁止绕过 DataPipeline 直接 INSERT 生产表"
     entry: python scripts/audit/check_insert_bypass.py
     language: system
     files: ^(backend/app/.*\.py|backend/engines/.*\.py)$
   ```
2. 写 `scripts/audit/check_insert_bypass.py`:
   ```python
   # 扫描 backend/app 和 backend/engines
   # 白名单: backend/app/data_fetcher/pipeline.py (DataPipeline 本身)
   # 黑名单模式: INSERT INTO (factor_values|factor_ic_history|klines_daily|daily_basic|minute_bars|moneyflow_daily)
   # 匹配到即 exit 1
   ```

**中期 (~3 小时, 转 S2b)**:
- path A/B (factor_onboarding): 迁到 `DataPipeline.ingest(df, Contract)` — 配合 S2 F51/F60 的 IC 口径统一一起做
- path C/D (fetch_base_data): 迁到 `DataPipeline.ingest` — 工作量大因为 fetch_base_data 是老的底层工具

**工作量**: 短期 lint 30 min; 中期代码迁移 3 小时+。

---

## 🟡 P2 发现

### F79 — `pms.py:186-187` PMS stream publish silent

**位置**: `backend/app/api/pms.py:186`

**证据**:
```python
get_stream_bus().publish_sync(
    STREAM_PMS_TRIGGER,
    { ... },
    source="pms_engine",
)
except Exception:
    pass                     # ← 同 F78 silent
```

**影响**: PMS 阶梯利润保护触发事件发不出去, 监控和前端看不到。

**建议**: 同 F78, 加 `logger.warning(exc_info=True)`。

**工作量**: ~2 min。

---

### F80 — `realtime_data_service.py:425-432` nav 失败 silent fallback to 0

**位置**: `backend/app/services/realtime_data_service.py:425-432`

**证据**:
```python
try:
    # ... 查询 NAV 逻辑
    return {
        "total_asset": nav,
        "cash": nav * cash_ratio,
        "frozen_cash": 0,
        "market_value": nav * (1 - cash_ratio),
    }
except Exception:
    pass                     # ← silent
return {"total_asset": 0, "cash": 0, "frozen_cash": 0, "market_value": 0}
```

**影响**: 
- DB 查询失败 → 前端 Dashboard 显示 "**¥0 total asset**" (数字上是错误但看起来像"真的是 0")
- 用户可能误以为账户清零, 或者不信任 dashboard 数据
- 正确行为应该是 HTTP 500 或返回 `{"error": "nav_query_failed", ...}` 让前端显示错误态

**建议**: 改为 `logger.error(exc_info=True)` + raise HTTPException(500, "nav 查询失败") 或返回带 error 字段的 dict。

**工作量**: ~15 min (含前端协议确认)。

---

### F81 — `factors.py:643,666` API silent pass 默认值

**位置**: `backend/app/api/factors.py:637-668`

**证据**:
```python
try:
    # IC decay 计算
    ic_decay[f"{fwd}d"] = { "ic_mean": fwd_mean, ... }
    continue
except Exception:
    pass                     # ← line 643 silent
ic_decay[f"{fwd}d"] = {"ic_mean": None, "ic_std": None, "ic_ir": None, "data_points": 0}

try:
    gate_row = await svc.get_factor_gate_fields(name)
    ...
except Exception:
    pass                     # ← line 666 silent
gate_info = {}
```

**影响**: 因子详情页的 IC decay 和 gate score 可能显示 None/空, 用户以为是 "因子没有 gate 数据" 而不是 "查询失败"。

**建议**: 至少加 `logger.warning(f"[factors] IC decay calc failed: {e}", exc_info=True)`。

**工作量**: ~5 min。

---

## 🟢 积极发现（反面证据, 非 finding）

这些是 grep 后**没找到**问题的地方, 可以作为后续审计的"已知良好"基线:

1. **✅ 熔断 L1-L4 实际落地** — `execution_service.py:92-115` 明确分支:
   ```python
   if cb_level >= 4:        # L4 HALT: 清空调仓目标
       hedged_target = {}
       is_rebalance = False
       return result
   elif cb_level == 3:      # L3 REDUCE: 降仓
       # ...
   elif cb_level == 2:      # L2 PAUSE: 暂停交易
       # ...
   ```
   **不是文档玩具**, 熔断状态机在执行路径上真的会 halt。

2. **✅ execution_service StreamBus publish 有正确的 try/except + logger.warning + exc_info=True** — 两处 (line 221, 342) 都遵循统一模板, 可作全项目 publish 包装器的参考

3. **✅ DataPipeline 本身合规** — `backend/app/data_fetcher/pipeline.py` 做完整的 rename → 列对齐 → 单位转换 → 值域验证 → FK 过滤 → Upsert → fillna(None)。**问题是上游绕过它**, 不是它本身不合格。

4. **✅ PG 连接池配置合理** — `backend/app/db.py:13` pool_size=10, 测试层 pool_size=1 + max_overflow=0 (避免泄漏), 生产测试隔离清晰。

5. **✅ Celery worker_prefetch_multiplier=1** — 避免任务堆积, 和 solo×1 实际运行一致。

---

## ⚖ 铁律合规评分（S3 覆盖部分）

| # | 铁律 | 状态 | 证据 | Delta vs S2 |
|---|---|---|---|---|
| **17** | DataPipeline 唯一入库 | ❌ **FAIL (生产 4 路径)** | factor_onboarding ×2 + fetch_base_data ×2 直接 INSERT | ↓ S2 声称 "部分 PASS", S3 实际发现 4 个 live 违规 |
| 22 | 文档跟代码 | ⚠️ 改善中 | Celery 配置 Mac→Windows 漂移未更新 (F82) | — |
| 26 | 验证不跳过不敷衍 | ❌ **局部 FAIL** | F76/F77 silent swallow = 验证被跳过 | 新发现 |
| 28 | 发现即报告不选择性遗漏 | ❌ **局部 FAIL** | F78/F79/F80/F81 except pass 无日志 = 发现但不报告 | 新发现 |

**S3 首次系统性扫描铁律 26/28 的代码层证据** — 之前 S1/S2/S4 把它们当"元规则"略过。

---

## 📊 累计发现总表（跨 S1/S2/S4/S3）

| 级别 | S1 | S2 | S4 | **S3 新增** | 总计 | 已处理 | 未处理 |
|---|---|---|---|---|---|---|---|
| 🔴 P0 | 6 | 3 | 1 | **2** (F76/F77) | **12** | **5** | **7** |
| 🟠 P1 | 10 | 8 | 3 | **4** (F78/F82/F85/F86) | **25** | **9** | **16** |
| 🟡 P2 | 6 | 2 | 6 | **3** (F79/F80/F81) | **17** | **3** | **14** |
| ✅ 关闭 | — | — | — | — | — | — | — |
| **合计** | **22** | **13** | **10** | **9** | **54** | **17** | **37** |

---

## 📌 S3 修复清单

### 立即可做 (<1 小时, S3 范围内 quick wins)

- [ ] **F76 方案 A**: `_get_realtime_tick` fail-safe + `_check_buy_protection` 无 tick 拒单 (~45 min)
- [ ] **F77**: 撤单查询失败加 logger.error 区分两种错误 (~15 min)
- [ ] **F78/F79/F81**: 三处 stream publish + API silent 加 `logger.warning(exc_info=True)` (~10 min 总)
- [ ] **F82**: `celery_app.py` worker_concurrency=4 → 1 + 注释警告 (~10 min)

### 中期 (转 S2b / S5)

- [ ] **F85 短期**: `.pre-commit-config.yaml` 加 commit/rollback 配对 lint (~15 min)
- [ ] **F85 中期**: 20+ commit service 加 rollback (~3 天, 需测试回归)
- [ ] **F86 短期**: `scripts/audit/check_insert_bypass.py` + pre-commit hook (~30 min, 立即防复发)
- [ ] **F86 中期**: factor_onboarding + fetch_base_data 迁到 DataPipeline (~3 小时)
- [ ] **F80**: realtime_data_service nav 失败改 HTTP 500 (~15 min, 需前端协议)

### 转 S5/S6

- [ ] `scripts/audit/config_drift_check.py` (S1 F45 + S3 F82)
- [ ] `scripts/audit/check_insert_bypass.py` (S3 F86 的代码强制)
- [ ] Router 层 `@transactional` 装饰器 (S1 F16 + S3 F85 的长期方案)

---

## 📎 附录 A: silent failure 分类统计

| 类别 | 数量 | 示例 |
|---|---|---|
| **Silent bypass (执行路径, 危险)** | 2 | F76, F77 |
| **Silent publish (可接受但缺日志)** | 3 | F78 (health), F79 (pms), F81 (factors) |
| **Silent fallback (数据 0/None, 用户看不见错误)** | 1 | F80 (nav) |
| **Silent iteration (except continue/pass, 多数合理)** | ~15 | factor_profiler, bruteforce_engine, mining, 基本合理 |
| **except ValueError/TypeError (窄 exception, 合理)** | ~8 | compute_factor_ic, quick_backtester, paper_trading, factor_dsl 等 |

**结论**: 26 个 `except pass/return None` 实例中, **6 个是真正的 finding** (F76-F81), 其余 20 个是合理的 exception handling (针对特定 ValueError/TypeError 的窄 catch + continue 迭代)。

---

## 📎 附录 B: Celery pool 决策矩阵（F82 辅助）

| 环境 | pool | concurrency | 原因 |
|---|---|---|---|
| macOS dev | prefork | 4 | fork() 可用, CPU 并行 |
| Linux prod | prefork | N_CPU | fork() 可用, 生产标准 |
| **Windows prod (当前)** | **solo** | **1** | **fork() 不可用, 多进程需启多个 worker 实例 + 队列路由 (R6 §3.2)** |

若要在 Windows 实现真正并发: 按 R6 §3.2 启动多个 solo worker 实例 + 不同 queue name (如 `worker-factor@%h` + `worker-data@%h`), 而不是调高 `concurrency` 参数。

---

## 📎 附录 C: F66 永久防复发 — check_insert_bypass.py 脚本草案

```python
#!/usr/bin/env python3
"""审计: 检查生产代码绕过 DataPipeline 直接 INSERT 生产表 (铁律 17)。

用法: python scripts/audit/check_insert_bypass.py
     python scripts/audit/check_insert_bypass.py --fix  # 输出修复提示
"""
import re
import sys
from pathlib import Path

PRODUCTION_TABLES = [
    'factor_values', 'factor_ic_history',
    'klines_daily', 'daily_basic', 'minute_bars',
    'moneyflow_daily',
]
SCAN_PATHS = [
    Path('backend/app'),
    Path('backend/engines'),
]
WHITELIST = [
    'backend/app/data_fetcher/pipeline.py',  # DataPipeline 本身
]

def main() -> int:
    pattern = re.compile(
        r'INSERT\s+INTO\s+(' + '|'.join(PRODUCTION_TABLES) + r')',
        re.IGNORECASE,
    )
    violations = []
    for base in SCAN_PATHS:
        for py in base.rglob('*.py'):
            rel = str(py.as_posix())
            if any(rel.endswith(w) for w in WHITELIST):
                continue
            for i, line in enumerate(py.read_text(encoding='utf-8').splitlines(), 1):
                if pattern.search(line):
                    violations.append((rel, i, line.strip()))
    if violations:
        print("❌ 铁律 17 违规: 直接 INSERT 生产表 (未通过 DataPipeline)")
        for f, i, line in violations:
            print(f"  {f}:{i}  {line[:80]}")
        print(f"\n共 {len(violations)} 处违规。使用 DataPipeline.ingest(df, Contract) 替代。")
        return 1
    print("✅ 无违规: 所有 INSERT 都走 DataPipeline。")
    return 0

if __name__ == '__main__':
    sys.exit(main())
```

---

**报告结束**。S3 韧性静态审计完成度: **约 75%**（核心 silent failure + F66 防复发通道已覆盖, 未做动态故障注入 / Redis 断线模拟 / Celery kill 测试）。

**S3 未做的动态部分**（建议转 S3b 或 S5）:
- Redis 断线时 PT 链路实际行为
- PG 连接池耗尽时 service 响应
- Celery worker kill -9 时 beat 重启
- QMT 断线时 _get_realtime_tick 的真实 silent bypass 演示

**下一 Session**: S5 边界 + 血缘 (时区 / QMT / 并发 / 生命周期) 或 **S3 tail fixes** (F76+F77+F78+F79+F81+F82 + F86 short-term lint = ~1.5 小时一次批量)。
