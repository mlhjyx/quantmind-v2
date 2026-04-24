# MVP 3.1 批 2 · Intraday Portfolio Rules + QMT Disconnect (详细 Plan)

> **父文档**: `docs/mvp/MVP_3_1_risk_framework.md`
> **ADR**: `docs/adr/ADR-010-pms-deprecation-risk-framework.md` D5 表 (批 2 行)
> **批次**: 批 2 (批 0 spike + 批 1 ✅ Session 27-29, 批 3 CB adapter 后续)
> **耗时**: ~0.5-0.7 周 (~450 行 platform + tests ≈ 2 PR)
> **创建**: 2026-04-24 Session 30, Opus (架构模式)
> **状态**: plan 待用户确认后进入实施模式

---

## 1 · 批 2 目标 (批 3 另立)

**In-scope**:
1. `backend/platform/risk/rules/intraday.py`: 4 规则 class
   - `IntradayPortfolioDrop3PctRule` (severity=P2, action=alert_only)
   - `IntradayPortfolioDrop5PctRule` (severity=P1, action=alert_only)
   - `IntradayPortfolioDrop8PctRule` (severity=P0, action=alert_only)
   - `QMTDisconnectRule` (severity=P0, action=alert_only)
2. 独立 Celery Beat `intraday-risk-check` 5min cron Mon-Fri 09:35-15:00 (54 次/日)
3. `daily_pipeline.intraday_risk_check_task` 新 task (批 1 daily_risk_check 姊妹)
4. 新增 `build_intraday_risk_engine()` factory (复用 batch 1 `build_risk_engine(extra_rules=...)`)
5. `RiskContext.prev_close_nav` 字段填充 (批 1 预留, 批 2 激活)
6. ~25 新 L1 tests + 1 L4 smoke

**Out-of-scope** (不做):
- ❌ 真实盘卖出 (LoggingSellBroker 继续用, 批 3+ 统一升级)
- ❌ 删 `scripts/intraday_monitor.py` (个股 -8% 独立保留, ADR-010 D5 迁移表明示不含)
- ❌ 删 `intraday_monitor_log` 表 (ADR-010 Consequences 稳定 2 周后评估)
- ❌ CB adapter (批 3, ADR-010 addendum 方案 C Hybrid)
- ❌ 前端 /risk dashboard (Wave 4)

---

## 2 · 文件结构 (批 2 交付物)

```
backend/platform/risk/rules/
├── pms.py                                     [批 1 已有]
├── intraday.py                                ⭐ NEW ~180 行: 3 Portfolio Drop + QMTDisconnect
└── __init__.py                                ⚠️ MODIFY: 导出 4 新规则

backend/app/services/risk_wiring.py            ⚠️ MODIFY (~30 行 delta):
    + `build_intraday_risk_engine()` factory (批 2 专用, 复用批 1 core)
    + `QMTConnectionReader` Protocol + wire (QMTClient.is_connected)

backend/app/tasks/daily_pipeline.py            ⚠️ MODIFY (~60 行 new task):
    + `intraday_risk_check_task` (name="daily_pipeline.intraday_risk_check")
    - max_retries=0 (5min 下次会再跑, 不 retry 积压)
    - time_limit=60 (5min 周期硬超时)

backend/app/tasks/beat_schedule.py             ⚠️ MODIFY (+1 entry):
    + `intraday-risk-check` crontab(minute='*/5', hour='9-14', day_of_week='1-5')
    - 对齐市场 09:30-15:00, expires=240 (4min 防积压)

backend/tests/
├── test_risk_rules_intraday.py                ⭐ NEW ~200 行 ~20 tests
├── test_risk_wiring.py                        ⚠️ EXTEND (~80 行 delta): intraday factory + extra rules
└── smoke/test_mvp_3_1_batch_2_live.py         ⭐ NEW ~80 行 1 smoke
```

**代码体量核算**: rules ~180 + wiring +30 + daily_pipeline +60 + beat_schedule +15 + tests ~280 = **~565 行**

---

## 3 · 关键接口契约

### 3.1 `IntradayPortfolioDropRule` base (抽象父类)

```python
class IntradayPortfolioDropRule(RiskRule):
    """组合级盘中跌幅规则基类.

    触发逻辑: (current_nav - prev_close_nav) / prev_close_nav <= -threshold
    - prev_close_nav: 昨日 15:00 收盘 NAV (批 1 已在 RiskContext 预留)
    - current_nav: RiskContext.portfolio_nav (Redis portfolio:nav 实时)

    子类只覆盖 `threshold` + `rule_id` + `severity`.
    """

    threshold: float  # 0.03 / 0.05 / 0.08
    action = "alert_only"

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        if context.prev_close_nav is None or context.prev_close_nav <= 0:
            return []  # silent skip: 首日开户 / 数据缺失
        drop = (context.portfolio_nav - context.prev_close_nav) / context.prev_close_nav
        if drop <= -self.threshold:
            return [RuleResult(
                rule_id=self.rule_id, code="",  # 组合级用 ""
                shares=0, reason=..., metrics={"drop_pct": drop, ...},
            )]
        return []
```

### 3.2 `QMTDisconnectRule`

```python
class QMTDisconnectRule(RiskRule):
    """QMT Data Service 断连告警 (盘中每 5min check).

    触发: qmt_reader.is_connected() == False
    Action: alert_only (断连无法下单, 只能人工介入)
    """

    rule_id = "qmt_disconnect"
    severity = Severity.P0
    action = "alert_only"

    def __init__(self, qmt_reader: QMTConnectionReader):
        self._reader = qmt_reader

    def evaluate(self, context: RiskContext) -> list[RuleResult]:
        if self._reader.is_connected():
            return []
        return [RuleResult(
            rule_id="qmt_disconnect", code="", shares=0,
            reason="QMT Data Service disconnected (is_connected=False)",
            metrics={"checked_at_utc": context.timestamp.timestamp()},
        )]
```

### 3.3 `RiskContext.prev_close_nav` 批 1 预留激活

批 1 engine.build_context 设 `prev_close_nav=None` (批 2 占位). 批 2 在 `build_intraday_risk_engine` 对应 context builder 内查 DB `performance_series WHERE trade_date = prev_trading_day` 填充.

---

## 4 · Scheduler 架构决策 (铁律 39 显式声明)

**方案对比** (3 候选):

| 方案 | 优 | 缺 |
|---|---|---|
| A. Task Scheduler 5min | 现 `intraday_monitor.py` 模式熟悉 | 需新建 Python 入口脚本, 多 1 条调度配置 |
| B. Celery Beat intraday-risk-check | 复用 Celery infra, 与 batch 1 daily_risk_check 对称 | Celery Beat 需激活 (用户 Servy restart, 现行 PT 主链走 Task Scheduler 非 Beat) |
| **C. 重构 intraday_monitor.py 内走 PlatformRiskEngine** | 单点调度, 个股+组合规则合并 | 改现有生产脚本, 回归风险 |

**决策**: **方案 B** (新 Celery Beat entry). 理由:
- 铁律 23 独立可执行 (方案 C 回归风险 + 改生产脚本)
- 批 1 Celery Beat 已增 daily_pipeline.risk_check 14:30 (虽未 Servy 激活, 但 infra 已通)
- 激活一次 Beat 同时生效 daily + intraday 2 个 risk task (批 1 + 批 2)
- `scripts/intraday_monitor.py` 个股 -8% 与批 2 组合 3/5/8% 并存正交 (D5 迁移表明示)

---

## 5 · 规则交互 + 触发防泛滥

**5min × 55 次 × 4 规则 = 220 evaluation/日**. 触发条件严格:
- 3%/5%/8% 只在真组合跌幅达到时触发, 非触发 `return []` 不写 log (ADR-010 D4 retention 仅触发入库)
- QMTDisconnect 若持续断连会每 5min 触发 → **需 dedup**: `risk_event_log` 查近 30min 同 rule_id 若有记录则 skip (防钉钉告警 DoS)
- 3% 触发后 5% 也触发? 同日同 rule_id 只告警 1 次 (Redis 24h TTL dedup, 对齐 intraday_monitor -8% 模式)

实现层 dedup (铁律 31 纯规则, 铁律 33 fail-loud):
- Rule 本身不做 dedup (保持纯计算)
- Engine execute 前调 `_should_alert(rule_id, strategy_id, mode)` 查 `risk_event_log WHERE trade_date=today AND rule_id=?`
- 或简化: intraday_risk_check task 级 Redis lock (`qm:risk:dedup:{rule_id}:{date}` 24h TTL)

**选**: Redis 24h TTL 方案 (与 scripts/intraday_monitor.py 成熟模式一致, 无 DB 压力)

---

## 6 · 测试策略

| 层 | 文件 | tests | 覆盖 |
|---|---|---|---|
| L1 Unit (intraday rules) | test_risk_rules_intraday.py | ~20 | 3 drop rules (触发/边界/未达/prev_close 缺失) + QMTDisconnect (connected/disconnected/首次) |
| L1 Unit (wiring) | test_risk_wiring.py extend | ~8 | build_intraday_risk_engine + QMTConnectionReader Protocol |
| L4 smoke | test_mvp_3_1_batch_2_live.py | 1 | subprocess import Platform + intraday_risk_check_task + Beat schedule */5 hour=9-14 day=1-5 验证 |

**验收**: 29 新 tests, baseline fail 不增 (铁律 40), pre-push smoke 32+ PASS.

---

## 7 · 实施顺序 (2 PR 拆分)

| PR | 内容 | 行数 | 硬门 | 预 reviewer |
|---|---|---|---|---|
| **PR 1** | rules/intraday.py (4 规则) + test_risk_rules_intraday.py + RuleResult metrics schema | ~380 | pytest 20+ PASS + ruff | code + python |
| **PR 2** | wiring (build_intraday_risk_engine) + daily_pipeline intraday_risk_check_task + beat_schedule + L4 smoke + dedup Redis | ~185 | pre-push smoke PASS + Beat inspect 注册 + dedup unit | code + architect |

PR 1 独立可 merge (规则本身可单测), PR 2 依赖 PR 1.

---

## 8 · Precondition 硬门 (进实施模式前必 ✅)

- [x] ADR-010 D5 迁移表 + D6 Part 2 intraday 设计决策已读
- [x] 批 1 PR #55/#57/#58 已 merged (Platform risk + wiring + Beat daily entry)
- [x] scripts/intraday_monitor.py 现有实现已 explored (个股 -8% 独立保留)
- [x] RiskContext.prev_close_nav 字段已预留 (批 1 interface.py)
- [x] risk_wiring extra_rules 参数已预留 (批 1 架构 reviewer P2-1)
- [ ] QMTClient.is_connected 契约 (PR 2 前核: 现行实现)
- [ ] Celery Beat 激活方式 (需 Servy restart? 用户确认)
- [ ] Redis `qm:risk:dedup:*` key space 无冲突 (PR 2 前 grep)

---

## 9 · 风险 & 缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| Celery Beat 未激活 = intraday 规则不跑 | 生产价值 0 | PR 2 明确 Servy restart 步骤 + 手工 `celery beat inspect` 验证 |
| 5min × 54 次 QMT 连接查询放大 QMT 压力 | QMT API quota 风险 | QMTClient.is_connected 走 Redis `qm:qmt:status` event 非直连 (批 1 已模式化) |
| prev_close_nav 数据源缺失 (T+1 首日 / 节后) | 3 drop 规则 silent skip | evaluate return [] + log warning (非 raise), 首日开户不触发 |
| 钉钉告警 DoS (QMT 断连持续) | 5min × N 告警刷屏 | Redis 24h TTL dedup + rule-level throttle |
| risk_event_log 写入压力 (最坏 4 rule × 触发 × 54 次) | DB 压力 | ADR-010 D4 仅触发写入, 非触发不写 |
| IntradayPortfolioDrop3/5/8 同日多次触发冲突 | 重复告警 | Redis 24h TTL dedup (同 rule_id 同日 1 次) |

---

## 10 · Non-goals 重申

- ❌ 不升级 LoggingSellBroker (批 3 统一)
- ❌ 不删老 intraday_monitor.py (D7 明示不删)
- ❌ 不做 CB adapter (批 3)
- ❌ 不动 PMS 老代码 (批 1 已 alias 保留)
- ❌ 不改 RiskContext interface 新增字段 (批 1 prev_close_nav 已预留, 够用)

---

**END of MVP 3.1 批 2 详细 Plan**
