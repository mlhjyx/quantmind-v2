# STATUS_REPORT — D3-A Step 5 Spike (钉钉静音 + audit 落地路径 forensic)

**Date**: 2026-04-30
**Branch**: chore/d3a-step5-silence-audit-forensic
**Base**: main @ 9265bf9 (PR #159 D3-A Step 4 修订 merged)
**Scope**: user 决议 ii-A 后 4 处不确定 forensic — 钉钉源 / audit 触发 / 静音候选 / PR 独立性
**ETA**: 实跑 ~15 min CC (vs 预估 15-20)
**真金风险**: 0 (0 改代码 / 0 改 .env / 0 服务重启 / 0 DML / 0 真发钉钉)
**改动 scope**: 1 文档 (本 spike) — 单 PR `chore/d3a-step5-silence-audit-forensic`, 跳 reviewer

---

## §0 环境前置检查 全 ✅

| 项 | 实测 |
|---|---|
| E1 git | main @ `9265bf9` (PR #159 merged), 8 D2 untracked (expected) |
| E2 PG | 0 stuck (仅本 spike psql session) |
| E3 Servy | FastAPI / Celery / CeleryBeat / QMTData ALL Running |
| E4 .venv | Python 3.11.9 |
| E5 真金 | LIVE_TRADING_DISABLED=True |

---

## Q1 — 钉钉刷屏真因路径 (4 项实测证据)

### Q1(a) 文本生成点

[backend/qm_platform/risk/engine.py:142-150](backend/qm_platform/risk/engine.py:142):

```python
def _load_positions(self, strategy_id: str, execution_mode: str) -> list[Position]:
    try:
        return self._primary.load(strategy_id, execution_mode)
    except PositionSourceError as e:
        logger.warning(
            "[risk-engine] primary source failed, switching to fallback: %s", e
        )
        self._notifier.send(
            title="[risk] primary position source failed",
            text=f"{type(self._primary).__name__} raised {type(e).__name__}: {e}. ...",
            severity="p1",
        )
        return self._fallback.load(strategy_id, execution_mode)
```

### Q1(b) 调用链

`engine.py:_load_positions` → `engine.py:154 build_context` → 调用方:
- [app/tasks/daily_pipeline.py:343](backend/app/tasks/daily_pipeline.py:343) `risk_daily_check_task`
- [app/tasks/daily_pipeline.py:568](backend/app/tasks/daily_pipeline.py:568) `intraday_risk_check_task`

### Q1(c) Beat schedule 当前状态 (重大反驳!)

[backend/app/tasks/beat_schedule.py:59-83](backend/app/tasks/beat_schedule.py:59) 实测:

```python
# ── [PAUSE T1_SPRINT_2026_04_29] risk-daily-check 暂停 ──
# 撤销见: docs/audit/link_paused_2026_04_29.md
# "risk-daily-check": {
#     "task": "daily_pipeline.risk_check",
#     "schedule": crontab(hour=14, minute=30, day_of_week="1-5"),
# },

# ── [PAUSE T1_SPRINT_2026_04_29] intraday-risk-check 暂停 ──
# "intraday-risk-check": {
#     "task": "daily_pipeline.intraday_risk_check",
#     "schedule": crontab(minute="*/5", hour="9-14", day_of_week="1-5"),
# },
```

→ Beat schedule 源代码层面**已注释** (PR #150 link-pause).

### Q1(d) 真因 — Beat 未重启, 跑旧 schedule cache

[logs/celery-stderr.log](logs/celery-stderr.log) 实测最末尾 (4-30 14:55:00):

```
[2026-04-30 14:55:00,149: WARNING/MainProcess] [risk-engine] primary source failed, 
  switching to fallback: QMT Data Service disconnected (is_connected=False)
[2026-04-30 14:55:00,532: WARNING/MainProcess] [DingTalk] sync发送成功: 
  title='[P1] [risk] primary position source failed'
[2026-04-30 14:55:00,548: ERROR/MainProcess] [IntradayRisk] strategy=28fc37e5... 
  异常: position_snapshot no rows for strategy=28fc37e5... mode=paper
```

[logs/celery-beat-stdout.log](logs/celery-beat-stdout.log) 实测启动时间:
```
LocalTime -> 2026-04-29 14:07:35
celery beat v5.6.3 (recovery) is starting.
```

**Beat 进程自 4-29 14:07:35 启动后没重启**. PR #150 link-pause merge 在 4-29 20:39, **晚于 Beat 启动时点 6.5h**. Beat 持有内存里的旧 schedule, 仍每 5min 触发 `intraday-risk-check`. `celerybeat-schedule.dat` 4-30 15:20 modified 证明 Beat 仍 active.

### Q1(e) 钉钉发送真路径 (绕过 PostgresAlertRouter)

[backend/qm_platform/risk/__init__.py:24](backend/qm_platform/risk/__init__.py:24): `notifier=dingding_notifier`

[backend/app/services/risk_wiring.py:85-115](backend/app/services/risk_wiring.py:85) DingTalkRiskNotifier:

```python
class DingTalkRiskNotifier:
    def send(self, title: str, text: str, severity: str = "warning") -> None:
        send_alert(
            level=level,
            title=title,
            content=text,
            webhook_url=settings.DINGTALK_WEBHOOK_URL,  # ← 直 POST, 绕 alert_dedup
            secret=settings.DINGTALK_SECRET,
            conn=None,  # 不写 alert_dedup, risk_event_log 由 engine._log_event 处理
        )
```

→ **解释 D3-A Step 1 谜题**: alert_dedup 表不存在但钉钉仍发, 因为这条路径 `conn=None` 直 POST DingTalk webhook, **完全绕过** PostgresAlertRouter / alert_dedup. send_alert 内部 try/except silent 失败 (铁律 33-c 读路径合规).

### Q1 结论 — 钉钉源 = Beat 未重启 (单源, 不是多源)

**唯一源**: Celery Beat 持有 4-29 14:07 启动时的旧 schedule cache, 每 5min 触发 intraday_risk_check_task → engine._load_positions raise → DingTalkRiskNotifier.send 直 POST webhook.

**LIVE_TRADING_DISABLED 不阻**: 真金 guard 在 broker.sell/buy, 不阻 risk engine evaluate / notify.

---

## Q2 — audit log 写入是否触发钉钉

### Q2(a) risk_event_log INSERT 路径

[backend/qm_platform/risk/engine.py:275-359](backend/qm_platform/risk/engine.py:275) `_log_event`:
- L307 `INSERT INTO risk_event_log` (rule trigger 命中时写)
- L327-359 outbox enqueue (`aggregate_type="risk"` event_outbox 表)
- L387 第 3 处 `_notifier.send` (rule trigger 时直发钉钉)

### Q2(b) outbox consumer 实测

```bash
grep -rE "qm:risk:|risk_outbox|XREAD.*risk|consumer.*risk_event" backend/
```

实测: **0 risk events 消费者** in production code (除 test_outbox_4domain_integration.py).

[backend/app/tasks/beat_schedule.py:92](backend/app/tasks/beat_schedule.py:92) outbox-publisher-tick 30s 周期 publish 到 `qm:risk:*` Redis Streams, 但**无下游 consumer 转发**.

### Q2(c) Q-B (ii) audit log 落地方式

CC 计划: **手工 INSERT INTO risk_event_log** (绕过 engine._log_event):

```sql
INSERT INTO risk_event_log (
  strategy_id, execution_mode, rule_id, severity, triggered_at,
  code, shares, reason, context_snapshot, action_taken, action_result, created_at
) VALUES (
  '28fc37e5-2d32-4ada-92e0-41c11a5103d0', 'live',
  'll081_silent_drift_2026_04_29', 'p0', NOW(),
  NULL, NULL,
  'D3-A Step 4 spike: user 4-29 ~14:00 决策清仓, Claude PR #150 软处理为 link-pause, '
  || 'user 4-30 GUI 手工 sell 18 股. DB 4-28 stale snapshot (NAV ¥1,011,714 / 19 持仓) '
  || 'vs xtquant 实测真账户 (NAV ¥993,520 / 0 持仓, -¥18,194 / -1.8%). '
  || 'forensic 价格不可考 (GUI 不走 API). T0-15/16/17 流程债.',
  '{"db_nav": 1011714.08, "qmt_actual_nav": 993520.16, "diff": -18194, ...}'::jsonb,
  'manual_audit_recovery', 'logged_only', NOW()
);
```

→ **不调** `engine._log_event` (避 outbox enqueue + 第 3 处 _notifier.send).
→ **不触发钉钉** (Q2 实测确认).
→ 配 `docs/audit/SHUTDOWN_NOTICE_2026_04_30.md` 记录 audit context.

### Q2 结论

✅ **audit log 手工 INSERT 不触发钉钉** (绕过 engine + outbox consumer 0 production code).

副作用: outbox 表不会有对应 row (audit row 仅 risk_event_log 单表). 这是预期 — Q-B (ii) 仅补 audit, 不模拟 rule trigger.

---

## Q3 — 4 静音候选 scope 实测

| 候选 | 改动文件 | 行数 | 静音效果 | 副作用 | T1.4 恢复成本 | 推荐 |
|---|---|---|---|---|---|---|
| **(a) Servy restart CeleryBeat** | 0 (仅 ps1 命令) | 0 | ✅ 立即 — Beat 重新 load 注释后 schedule, intraday_risk_check 不再触发 | 30s 中断 outbox-publisher-tick (event_outbox backlog ≤30 行可接受) / daily-quality 17:40 / factor-lifecycle 周五 19:00 不影响 (cron 时间未到) | 0 (重 Servy restart 即恢复, 但需先取消注释 schedule) | ⭐ **强推荐** |
| (b) settings RISK_BEAT_ENABLED flag | beat_schedule.py + config.py + .env | ~20 | ✅ — 但需 Beat restart 才生效 = 同 (a) 但多代码 | 引入新 SSOT 字段 (铁律 34) | ~10min | ❌ 多余 |
| (c) Servy stop QMTData | 0 | 0 | ❌ — Q1 实测真因不在 QMTData (QMTData silent skip 26 天 0 告警) | qmt_data_service 全停, Redis cache 完全 stale | 重启 | ❌ 不解决 |
| (d) qmt_data_service fail-loud 改 | scripts/qmt_data_service.py | ~30 | ❌ — user 已撤回方向 B | (撤回) | (撤回) | ❌ user 拒 |

### Q3 (a) restart 副作用详细评估

| Beat 任务 | crontab | restart 时影响 |
|---|---|---|
| outbox-publisher-tick | 30s | ≤30s 中断, event_outbox backlog ≤数十行可接受 |
| daily-quality-report | 17:40 周一-五 | 不影响 (当前 15:30, restart 即恢复, 17:40 仍跑) |
| factor-lifecycle-weekly | 周五 19:00 | 不影响 (今 4-30 周四, 24h 后才跑) |
| **risk-daily-check** | (已注释) | ✅ **重新 load 后停** |
| **intraday-risk-check** | (已注释) | ✅ **重新 load 后停** |
| pms-daily-check | (已 deprecated) | 不影响 |

### Q3 推荐: (a) Servy restart QuantMind-CeleryBeat

**论据**:
- ✅ 0 代码改动
- ✅ 立即静音 (Q1 真因直接 fix)
- ✅ 副作用 30s outbox-publisher 中断可接受
- ✅ 沿用 PR #150 link-pause 设计意图 (注释了但未真生效, restart 就生效)

**反对论据**: 30s outbox backlog. 但实测 event_outbox 当前低 throughput (Beat 周五因子+周日 GP+17:40 quality, 当下 0 事件), restart 时点选交易日盘后 (15:00+) 几乎 0 backlog 风险.

---

## Q4 — audit log PR 与静音 PR 真独立性

### Q4(a) 文件 / 表 / connection / Redis key 重叠

| 维度 | audit log PR | 静音 PR (Q3 (a)) | 重叠 |
|---|---|---|---|
| 改文件 | `docs/audit/SHUTDOWN_NOTICE_2026_04_30.md` (新加) | 0 (仅 ps1 命令) | 0 |
| DB 表 | risk_event_log (1 行 INSERT) | 0 | 0 |
| connection | psycopg2 短连接 | 0 | 0 |
| Redis key | 0 | 0 | 0 |
| Servy 服务 | 0 | restart QuantMind-CeleryBeat (30s) | 0 |

### Q4(b) 决议

**两 PR 真独立**, 0 文件 / 表 / connection / Redis key 重叠.

### Q4(c) 推荐顺序: **静音先, audit log 后** (反向)

**论据**:
1. ✅ Q1 钉钉源在持续触发 (~5min 一次), 静音先停损
2. ✅ Q2 实测 audit log INSERT 不触钉钉, 但万一意外 (outbox 未来加 consumer / engine 内部 trigger 改动) 也只 1 次, 静音后**0 风险**
3. ✅ user 体验: 钉钉先静音 → user 立即看到效果 → audit log 慢慢补
4. ✅ 反向顺序与 PR 描述自然顺序对齐 (修后果 → 补审计)

**反对**:
- audit log 单 PR 可与静音 PR 单 commit ship, 减 ceremony — 但 user prompt 拆 2 PR 是有意 (静音是 ops, audit log 是 docs+SQL, 关注点分离)

### Q4 结论

✅ **真独立**, 推荐**反向顺序** (静音 PR 先, audit log PR 后).

---

## 关键 Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3A-NEW-6 | **PR #150 link-pause 失效** — Beat 未重启加载新 schedule, 旧 cache 仍跑 risk-daily-check / intraday-risk-check 触发钉钉刷屏 | **P0** (本 spike Q3 (a) 修) |
| (info) | 钉钉源单条路径 (Beat → engine._notifier.send → DingTalkRiskNotifier 直 POST), 不是多源 | INFO |
| (info) | DingTalkRiskNotifier 完全绕过 PostgresAlertRouter / alert_dedup, 解释 D3-A Step 1 谜题 | INFO |
| (info) | risk_event_log outbox 0 production consumer, audit log INSERT 不触钉钉 | INFO |

## Tier 0 债更新 (15 → 16, +1)

新增:
- **T0-18 (P1)**: 注释 Beat schedule 后必 Servy restart 才生效 — 候选铁律 X9 "schedule / config 注释后必显式重启服务才生效, 不允许 'comment-only' 无效 commit"

---

## LL "假设必实测纠错" 累计 22 → 23 (+1)

| 第 | 来源 | 假设 | 实测 |
|---|---|---|---|
| 23 (LL-091 候选) | Step 5 prompt "钉钉源是 Beat / schtask / service 三选一" + "PR #150 link-pause 真生效" | Beat schedule 注释 = Beat 真停 | 实测 Beat 4-29 14:07 启动后未重启, 持有旧 schedule cache, intraday_risk_check 仍每 5min 触发. **commit 注释 schedule ≠ 服务真停**. 复用规则: schedule / config 类改动 PR description 必声明 "需 Servy restart" + post-merge ops checklist |

---

## 硬门验证

| 硬门 | 结果 | 证据 |
|---|---|---|
| 改动 scope | ✅ 1 文档 (本 spike) | git status |
| ruff | ✅ N/A | 0 .py |
| pytest | ✅ N/A | 0 .py |
| pre-push smoke | (push 时验) | 沿用上 PR |
| 0 业务代码改 | ✅ | git diff main 仅本文件 |
| 0 .env 改 | ✅ | 0 |
| 0 服务重启 | ✅ | 本 spike 仅诊断, restart 留下个 PR |
| 0 DML | ✅ | SELECT only |
| 0 真发钉钉 | ✅ | 0 调 _notifier.send |
| 0 LLM SDK | ✅ | 开发诊断边界 |

---

## 下一步建议

### 立即 ship (推荐反向顺序)

1. **PR #161+** `chore/silence-celerybeat-restart` (~5 min)
   - 改动: 0 代码
   - ops: `Restart-Service QuantMind-CeleryBeat`
   - PR description 含 post-merge ops 步骤 + verify 30s 后 stderr 0 钉钉
   - 跳 reviewer (sysop only)

2. **PR #162+** `fix/d3a-step4-audit-log-recovery` (~15 min)
   - 改动: 1 SQL INSERT (1 行 risk_event_log P0) + 1 markdown (`SHUTDOWN_NOTICE_2026_04_30.md`)
   - 含 SHUTDOWN_NOTICE 引用 D3-A Step 4 修订 + xtquant 实测 ground truth + forensic 损失推算
   - 跳 reviewer (audit recovery only)

### 后续 (T1.4 批 2 写代码阶段)

- 取消注释 risk-daily-check / intraday-risk-check Beat schedule 之前: 必先修 T0-4 hardcoded 'live' (27+ 处) → ADR-008 写路径漂移彻底解决 → 重启 Beat 验证 0 ALL_SKIPPED ERROR
- T0-18 候选铁律 X9 写 ADR

---

## 关联

- **D3-A Step 4 修订** ([STATUS_REPORT_2026_04_30_D3_A_step4_qmt_clearance_spike.md](STATUS_REPORT_2026_04_30_D3_A_step4_qmt_clearance_spike.md)) — Step 4 决议 ii-A, 本 spike 解锁 ii-A 落地
- **PR #150 link-pause** ([link_paused_2026_04_29.md](link_paused_2026_04_29.md)) — 设计正确但 Beat 未重启, T0-18 真因
- **F-D3A-NEW-6 P0** (本 spike) — Q3 (a) Servy restart 修
- **LL-091 候选** (本 spike +1, 累计 23) — schedule 注释 ≠ 服务真停
- **Q-B 落地路径**: ii (audit log only) 推荐, 顺序反向 (静音先)

## 用户接触

实际 0 (本 spike 全 forensic, 不需 user 决议).

下一步 user 接触: 决议是否启 PR #161+ (静音) + PR #162+ (audit log) 两 PR.
