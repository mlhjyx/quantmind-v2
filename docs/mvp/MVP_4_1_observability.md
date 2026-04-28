# MVP 4.1 Observability Framework (Wave 4 启动)

> **状态**: 🟡 批 1 进行中 (PR #131 待开)
> **ADR**: Platform Blueprint §Framework #7 / 铁律 28 (发现即报告) / 铁律 33 (禁 silent failure) / 铁律 34 (config SSOT) / 铁律 43 (schtask fail-loud)
> **Sprint**: Wave 4 1/4 (Wave 3 ✅ 5/5 完结后启动)
> **前置 (铁律 36 实测复核, Session 43 2026-04-28)**:
>   - ✅ MVP 1.1 Platform Skeleton: `qm_platform/observability/interface.py` MetricExporter / AlertRouter / EventBus ABC 已存
>   - ✅ MVP 3.4 Event Sourcing: `qm_platform/observability/outbox.py` OutboxWriter concrete (event_outbox 表 + publisher worker), batch 4+5 sunset 全 outbox 化
>   - ✅ NotificationService (`backend/app/services/notification_service.py`): async + sync_wrappers (`send_alert` / `send_daily_report`), 铁律 32 Class C 例外审过
>   - ✅ DingTalk dispatcher (`backend/app/services/dispatchers/dingtalk.py`): HMAC 签名 + 10s 超时 + send_markdown / send_markdown_sync
>   - ✅ `notifications` 表已存 (level / category / market / title / content / link)
>   - ✅ NotificationThrottler (`backend/app/services/notification_throttler.py`): in-memory dict, **声明 "Phase 0 单进程, 多 worker 改 Redis"** — schtask 跨进程内存版永久失效, MVP 4.1 解决
> **耗时**: 1.5-2 周 (4 批串行)
> **关联 Framework**: #7 (本) / #8 Config (settings.DINGTALK_*) / #11 ROF (Prometheus 替代复用) / #9 CI Layer 3 (告警走 MetricExporter)
> **关联 Future Spec**: B6 `.health()` endpoint 规范 (本 MVP 落地) / B10 OpenTelemetry correlation_id (本 MVP 评估, 视实施)
> **设计文档**: 本文 (≤ 2 页, 铁律 24)

## Context (实测 precondition)

**问题**: **17 个生产 schtask + Celery 脚本** 散落 DingTalk webhook + 各自 dedup 实现 (Blueprint 字面 6 个低估 3x):

| 散落维度 | 实测 |
|---|---|
| `DINGTALK_WEBHOOK_URL` 调用方 | 17 scripts (`grep DINGTALK_WEBHOOK_URL -l scripts/` Session 43 实测) |
| dedup 实现 | 3 套并存: `intraday_monitor` Redis 24h key (line 260-290) / `services_healthcheck` 文件 1h (line 140-147) / 其余 13+ scripts **无 dedup** (告警风暴风险) |
| Throttler | `notification_throttler.py:28` 自带 disclaimer "Phase 0 单进程内存, 多 worker 改 Redis" — schtask 跨进程**永久失效** |
| 配置入口 | 12 scripts 走 `settings.DINGTALK_WEBHOOK_URL`, 5 scripts 走 `os.environ.get("DINGTALK_WEBHOOK_URL")` (铁律 34 SSOT 漂移) |
| Metric 概念 | **完全不存在** — 全是 alert/notification 单一类型, 无 gauge/counter/histogram, 趋势分析只能 grep log |
| Health endpoint | `/health` 仅返回 execution_mode + 简单 ping, 无 Framework `.health()` 规范 (B6 缺) |

## Scope (~1.5-2 周, **4 批串行**, MVP 串行交付)

### 批 1: PlatformAlertRouter concrete + cross-process PG dedup (~0.5 周, PR #131) ← 当前批

**交付物**:
1. `backend/qm_platform/observability/alert.py` ⭐ 新 ~200 行
   - `PostgresAlertRouter(AlertRouter)` concrete: wrap `dingtalk.send_markdown_sync` + cross-process PG dedup
   - **Interface 双签名兼容**: 保留 `interface.py` 的 `fire(Alert)`, 新增 Blueprint 字面 `alert(severity, payload)` 同语义包装 (Application SDK 偏好简洁签名)
   - `AlertDispatchError` 异常 (interface 契约: 所有 channel 都失败 fail-loud, 铁律 33)
   - `Channel` Protocol: DingTalk 实施, **SMS stub** (Blueprint P0→SMS 要求, V1 stub 返 NotImplementedError 不静默, 真 SMS 留 Wave 5+ 视成本)
   - sync API (主用例: schtask scripts), async wrapper 留批 4
   - dedup_key = caller 提供 (例: `f"factor_lifecycle:{factor_name}:warning"`), suppress_minutes per severity
2. `backend/migrations/alert_dedup.sql` + `alert_dedup_rollback.sql` ⭐ 新
   - 表 `alert_dedup(dedup_key TEXT PK, last_fired_at TIMESTAMPTZ NOT NULL, suppress_until TIMESTAMPTZ NOT NULL, severity TEXT, source TEXT, fire_count BIGINT DEFAULT 1)` + idx on suppress_until (cleanup)
   - 不入 TimescaleDB hypertable (量小, 千行级 / 天)
3. `backend/qm_platform/observability/__init__.py` ⚠️ MODIFY: 导出 `PostgresAlertRouter` + `AlertDispatchError` + factory `get_alert_router()`
4. `backend/tests/test_platform_alert_router.py` ⭐ 新 ~280 行 ~18 tests (合约 + dedup 行为 + DingTalk failover + 配置 SSOT + cross-process simulation)
5. `backend/tests/smoke/test_mvp_4_1_batch_1_live.py` ⭐ 新 (铁律 10b subprocess import 验证)
6. 不动 17 scripts (后续批迁移), 不动 NotificationService (并存)

### 批 2: PlatformMetricExporter + AlertRulesEngine yaml + B6 `.health()` (~0.5 周, PR #132)

- `backend/qm_platform/observability/metric.py`: `PostgresMetricExporter` concrete, **三档签名兼容** — Blueprint `emit(metric, value, labels)` + interface.py `gauge/counter/histogram` 全暴露
- `backend/migrations/platform_metrics.sql`: TimescaleDB hypertable `platform_metrics(name, value, labels JSONB, timestamp_utc)` + 30 天 retention policy (Wave 5 UI dashboard 数据源)
- `configs/alert_rules.yaml` (Blueprint MVP 范围): rule-driven routing, severity 阈值 + dedup 窗口 + channel
- `backend/qm_platform/health.py`: B6 `Framework.health() -> HealthReport` 规范, MetricExporter / AlertRouter 各自实现 `.health()`
- 单测 + smoke

### 批 3+: 17 scripts 串行迁 SDK (每 PR 2-4 scripts, ~0.7 周 总, 3 PR)

**优先级 P0** (silent fail 风险): `data_quality_check` / `pt_audit` / `ic_monitor` / `monitor_factor_ic`
**优先级 P1**: `factor_lifecycle_monitor` / `factor_health_daily` / `pt_daily_summary` / `pt_watchdog` / `intraday_monitor` / `daily_reconciliation`
**优先级 P2**: `rolling_wf` / `run_gp_pipeline` / `services_healthcheck` / `monitor_mvp_3_1_sunset` / `approve_l4` (互动 CLI 慎迁)
- 每脚本: 删 webhook hardcode, 改 `from qm_platform.observability import get_alert_router; router.fire(Alert(...))`
- backward compat 保留 1 周双写后删旧路径
- **铁律 43 4 项硬化清单复核** (statement_timeout / FileHandler delay / boot probe / fatal trap) — 保持已合规, 迁移不破坏
- **新增 schtask: `scripts/audit/audit_orphan_factors.py` 周期化** (Blueprint 451 行建议, factor_registry vs factor_values SSOT drift CI gate)

### 批 4 (可选, 时间窗允许): PlatformEventBus wrap StreamBus + B10 评估 (~0.3 周, PR #137)

- `backend/qm_platform/observability/event_bus.py`: wrap `app.core.stream_bus.StreamBus` 为 EventBus contract (Blueprint #7 "EventBus 升级自 StreamBus")
- 不重写 StreamBus (MVP 3.4 outbox publisher 已用), 仅 Platform 抽象暴露给 Application 层
- B10 correlation_id: Application 调 SDK 时透传 trace_id, 评估是否值得引 OpenTelemetry SDK (单机环境 ROI 有限, 决议 ADR 入 Blueprint)

## Platform-App 分工 (Part 1 红线复核)

**AlertRouter 属 Platform 4 特征复核** (Blueprint Part 1 line 235-239):
- ✅ **多 App 共享**: PaperTrading + GP Mining + Research + Forex (未来) + AI 闭环 (Wave 3+) 全要告警, 远超 2 App 阈值
- ✅ **业务无关**: alert.py 0 行 `if strategy_id == "S1"` / `if factor_name == "xxx"` 业务判断 (红线复核)
- ✅ **接口稳定**: fire(Alert, dedup_key) + alert(severity, payload) 双签名兼容 interface.py 和 Blueprint #7, V1 锁定不破坏
- ✅ **契约化价值**: interface.py ABC + Channel Protocol + AlertDispatchError + 18 unit tests + smoke 已具备

**红线复核** (Part 1 line 264-268): alert.py 不含 `if strategy_id == ...` / 不含 `if factor_name == ...` / 不裸访问 PG bypass conn_factory 注入. ✅ 全过.

## 双角色心态切换 (Part 1 line 256-263)

| 阶段 | 角色 | 关键 |
|---|---|---|
| 批 1 (本 PR) — 写 alert SDK | **平台工程师** | 契约化 + 单测 ≥ 18 + 版本化 + 拒绝业务泄漏 + SDK 稳定至上 |
| 批 2 — Metric SDK | **平台工程师** | 同上 |
| 批 3 — 17 scripts 迁 SDK | **业务工程师** | 快迭代 + 经 SDK 消费 Platform + 不破坏 SDK 稳定 |
| 批 4 — EventBus 包装 | **平台工程师** | wrap 现有 StreamBus, 不重写 |

切换检查清单: 平台工程师角色提交 PR 必含契约化 (interface + ABC) + 单测 + 版本化标记; 业务工程师角色提交 PR 不允许引 Platform internal module (`from qm_platform.observability.alert import _internal` 禁), 必走 SDK __init__ 导出面.

## Application Usage Patterns (Blueprint Part 2 顶部 4 Pattern, 批 3 迁移目标)

**Pattern A — 因子研究 / GP Mining (优先级 P1)**:
```python
from qm_platform.observability import get_alert_router, Alert, Severity

router = get_alert_router()
# Pattern A.1 GP Mining 失败告警 (run_gp_pipeline.py 批 3)
router.fire(
    Alert(
        title="GP weekly mining failed",
        severity=Severity.P1, source="run_gp_pipeline",
        details={"phase": "evolve", "exception": "OOM at gen 42"},
        trade_date="2026-04-28",
        timestamp_utc="2026-04-28T22:00:00+00:00",
    ),
    dedup_key="gp_mining:weekly:failed",
)

# Pattern A.2 Research 因子衰减告警 (factor_lifecycle_monitor.py 批 3, 当前已散落)
router.fire(
    Alert(
        title="dv_ttm IC ratio < 0.8 → warning",
        severity=Severity.P1, source="factor_lifecycle_monitor",
        details={"factor": "dv_ttm", "ratio": 0.517, "transition": "active→warning"},
        trade_date="2026-04-28",
        timestamp_utc="2026-04-28T19:00:00+00:00",
    ),
    dedup_key="factor_lifecycle:dv_ttm:warning",  # 同 factor 同 transition 5/30/60min dedup
)
```

**Pattern C — PaperTrading (优先级 P0, 真金风险)**:
```python
# Pattern C.1 intraday 跳水熔断 (intraday_monitor.py 批 3, 当前用 Redis dedup)
router.fire(
    Alert(
        title="组合 intraday drop > 8% → CB L2",
        severity=Severity.P0, source="intraday_monitor",
        details={"nav": 920_000, "drop": -0.087, "cb_level": 2},
        trade_date="2026-04-28",
        timestamp_utc="2026-04-28T13:35:00+00:00",
    ),
    dedup_key="intraday:portfolio_drop8:cb_l2",  # 同事件 P0=5min dedup
    suppress_minutes=5,  # 显式覆盖 (P0 默认 5min, 此 alert 也用 5min)
)

# Pattern C.2 数据质量预检失败 (data_quality_check.py 批 3, 当前 schtask 17:45)
router.fire(
    Alert(
        title="盘后数据质量预检失败 (klines_daily 缺 30+ rows)",
        severity=Severity.P0, source="data_quality_check",
        details={"missing_rows": 32, "expected": 5180, "table": "klines_daily"},
        trade_date="2026-04-28",
        timestamp_utc="2026-04-28T17:45:00+00:00",
    ),
    dedup_key="data_quality:klines_daily:missing",
)
```

**Pattern D — Research/AI 长任务 (优先级 P2)**:
```python
# Pattern D.1 rolling WF 异常 (rolling_wf.py 批 3 P2)
router.fire(
    Alert(
        title="rolling WF Sharpe regression detected",
        severity=Severity.P2, source="rolling_wf",
        details={"sharpe_drop": 0.18, "baseline": 0.87, "current": 0.69},
        trade_date="2026-04-28",
        timestamp_utc="2026-04-28T20:00:00+00:00",
    ),
    dedup_key="rolling_wf:sharpe_drop:weekly",
    suppress_minutes=24*60,  # 周度任务, 24h dedup 避免重复
)
```

**导入规则 (Part 1 line 222-227 强制)**:
- ✅ Application 必走 SDK __init__: `from qm_platform.observability import get_alert_router, Alert, Severity, AlertDispatchError`
- ❌ 禁止: `from qm_platform.observability.alert import PostgresAlertRouter` 跳层访问 internal (绕开 SDK 控制)
- ❌ 禁止: 自定义 subclass `class MyAlertRouter(AlertRouter)` 旁路 — 修改需走 Platform 评审 (本 MVP 升级路径)

## Out-of-scope (明确排除, 铁律 23)

- ❌ **Prometheus + Grafana 安装** (Blueprint #7 字面 "装好") — **偏离原因 (铁律 38 ADR)**: 单机 Windows 维护 Prometheus stack 成本 > 价值 + UI 5.x 蓝图已规划自建 dashboard. **替代方案**: PG sink + 30d retention + Wave 5 UI dashboard 接 (UI 5.x 数据源前置). ROF (#11) 也可用此 PG sink 替代 Prometheus exporter (Blueprint line 1250 已允许 "Wave 4 前用日志替代"). **决议入 Blueprint Part 8 决策记录 (待 commit)**.
- ❌ **真 SMS 渠道实施** (Blueprint P0 → SMS+DingTalk) — V1 stub return NotImplementedError 不静默 (铁律 33), 真接入留 Wave 5+ 视成本. P0 触达 < 30s 验收用 DingTalk 单 channel 满足 (DingTalk push 实测 < 5s).
- ❌ **OpenTelemetry distributed tracing** (B10) — 批 4 评估, ROI 单机有限可能拒
- ❌ **Email / Slack channel** (DingTalk 已覆盖, 多 channel 留 future)
- ❌ **告警 ML 异常检测** (规则告警足够, ML 留 Wave 6)
- ❌ **NotificationService 替换** (并存, AlertRouter wrap 一层即可, 不破坏 async router 分发)

## 关键架构决策 (铁律 39 显式)

### PG-backed cross-process dedup (vs Redis)
- **选择**: PG `alert_dedup` 表, ON CONFLICT (dedup_key) DO UPDATE
- **理由**: schtask 跨进程必须持久化 / PG 重启不丢 / 量小无压力 / 已是真相源
- **拒绝 Redis**: flush 后下次启动可能瞬间发 17 条告警风暴
- **拒绝文件锁**: services_healthcheck 文件 dedup 已踩坑 (Windows 文件锁不可靠)

### dedup 窗口: severity 驱动短窗 + 7d 上限 (Blueprint 对齐)
- **选择**: 默认 `{P0: 5min, P1: 30min, P2: 60min}`, caller override; 任何 dedup 窗口最大 7 天 (Blueprint #7 "7 天内同 key 自动 dedup" 解读为最大窗口非默认值)
- **理由**: P0 触达 < 30s (Blueprint 验收) 与 5min dedup 不冲突 — 触达指首次触发, dedup 是后续抑制
- **隐含 caller 契约**: dedup_key 字符串显式 (`f"factor_lifecycle:{factor}:{transition}"`), 避免 title 微小变化导致 miss

### AlertRouter.fire() return 枚举 (vs bool)
- **选择**: return `Literal["sent", "deduped", "sink_failed"]`
- **理由**: bool 模糊 (deduped 算 True 还是 False?), 调用方根据语义决定 retry / log
- **fail-loud**: sink_failed 同时 raise `AlertDispatchError` (铁律 33 + interface 契约)

### Webhook 配置统一走 settings (vs os.environ)
- **选择**: PostgresAlertRouter 内部仅读 `settings.DINGTALK_WEBHOOK_URL` + `settings.DINGTALK_SECRET`
- **理由**: 铁律 34 SSOT (5 scripts 用 os.environ 是漂移)
- **17 scripts 迁移时同步消除** os.environ 直读

### 不替换 NotificationService (并存)
- **选择**: AlertRouter 是 SDK-level 包装, NotificationService 在 FastAPI 路由内处理 notifications 表 (UI 可见)
- **理由**: NotificationService 已审 (铁律 32 Class C 例外), async 路由依赖, 替换风险高
- **17 scripts 仍可经 send_alert 写 notifications 表 (兼容路径)**, 渐进退役

### 批 1 仅做 AlertRouter (不带 MetricExporter)
- **选择**: 拆分 4 批串行, 批 1 仅 AlertRouter (痛点最大, ROI 最高)
- **理由**: 17 scripts dedup 风暴是当前可观测痛点, MetricExporter 是新增能力但无即刻痛点; 串行降低单 PR 风险

## LL-059 9 步闭环 (**4 批 = 4 PR**, 串行)

批 1 `feat/mvp-4-1-batch-1-alert-router` → 批 2 `feat/mvp-4-1-batch-2-metric-exporter-rules` → 批 3.x `feat/mvp-4-1-batch-3-scripts-{p0,p1,p2}` (3 PR) → 批 4 `feat/mvp-4-1-batch-4-event-bus`

## 验证 (硬门, 铁律 10b + 40 + 33)

- 批 1: 18 unit + 1 smoke + ruff clean + 实 DB upsert 验证 + dedup 跨"进程"模拟 (子进程 spawn 2 次, 第 2 次必 deduped) + **P0 触达 < 30s 实测** (DingTalk send → ack)
- 批 2: TimescaleDB hypertable 创建 + 1k row insert + 30d retention policy + alert_rules.yaml schema validation + `.health()` endpoint 返 5 Framework 状态
- 批 3.x: 每脚本迁移后 grep 老 webhook 直调归零 + 真发 1 条告警 verify + 铁律 43 4 项清单 unchanged
- 批 4: StreamBus 旧路径 + EventBus 新路径双写 1 条 event verify 一致

## 验收 (Blueprint Wave 4 完结条件)

- ✅ **告警去重率 ≥ 80%** (Blueprint #7 line 629)
- ✅ **P0 触达 < 30s** (Blueprint #7 line 629, 实测 DingTalk push 5s + dedup 不影响首次)
- ✅ 17 scripts 全走 PlatformAlertRouter, 0 散落 webhook 直调 (铁律 34)
- ✅ Cross-process dedup 工作 (跨 schtask 进程同 dedup_key 5min 内必 dedup)
- ✅ 铁律 33 0 silent swallow (sink_failed 必 raise + 必 log ERROR)
- ✅ 铁律 28 alert.fire() 失败必 raise + 必 log (发现即报告)
- ✅ 铁律 43 17 scripts 迁移后 4 项硬化清单 unchanged
- ✅ MetricExporter 2+ 脚本接入 (PT signal_count + factor_health), DB 可查 30 天序列
- ✅ Framework `.health()` endpoint 5 个 Framework 状态 (B6)
- ⚠️ Grafana dashboard: **替代为 Wave 5 UI 自建 dashboard (PG metrics 表为数据源)** — 偏离 Blueprint, ADR 决议
