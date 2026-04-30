# SHUTDOWN_NOTICE — 2026-04-30 PT 暂停 + QMT 全清仓 audit recovery

**Date**: 2026-04-30
**Trigger**: D3-A Step 4 spike (PR #158) 修订 (PR #159) 发现 user 4-29 ~14:00 决策清仓但 Claude PR #150 软处理为 link-pause, user 4-30 GUI 手工清仓后 DB silent drift 26 天.
**Audit row**: `risk_event_log.id = 67beea84-e235-4f77-b924-a9915dc31fb2` (severity='p0', rule_id='ll081_silent_drift_2026_04_29')
**钉钉静音**: Servy restart QuantMind-CeleryBeat (本 PR Phase B), Beat 4-29 14:07→4-30 15:35:51 reload 注释后 schedule 生效, intraday-risk-check 不再触发 (实测 14:55 后 40min 0 entry, 5-5 周一前不再 trigger).

---

## §1 触发

D3-A Step 4 spike PR #158 (4-30 14:48 merged) 误判 root cause "L1: QMT 4-04 01:06 断连后 user 未察觉". user 14:50 质问 "4.29 我叫你清仓的, 你忘记了?" 触发回查. 实测 [memory/project_sprint_state.md:27](memory/project_sprint_state.md:27) Session 44 末 handoff **明确记录**: "PT live 真生产事件 (卓然 -29% / 南玻 -10%) → **用户决策"全清仓暂停 PT + 加固风控"**".

D3-A Step 4 修订 (PR #159) 重构 5 层 root cause + 责任拆解. D3-A Step 5 spike (PR #160) 4 题实测决议 ii-A (静音 + audit log 落地). 本 PR 落地.

---

## §2 真账户 ground truth (xtquant API 实测)

```python
from xtquant import xttrader
trader = xttrader.XtQuantTrader(qmt_path, session_id)
trader.start(); trader.connect()  # connect_result=0
positions = trader.query_stock_positions(StockAccount('81001102'))
asset = trader.query_stock_asset(acc)
```

**实测输出** (2026-04-30 14:54):
- positions_count = 1 (688121.SH qty=0, market_value=0 — placeholder, 已清)
- asset_total = ¥993,520.16
- cash = ¥993,520.16
- market_value = ¥0.00

→ **真账户 0 持仓 + 全 cash**, user "QMT 已全清仓" ground truth 验证.

---

## §3 DB silent drift 详细

| 维度 | DB 4-28 stale snapshot | xtquant 真账户 (4-30 14:54 实测) |
|---|---:|---:|
| NAV | ¥1,011,714.08 | ¥993,520.16 |
| Cash | ¥110,624.08 | ¥993,520.16 |
| Market value | ¥901,090.00 | ¥0.00 |
| Position count | 19 | 0 |
| Latest snapshot date | 2026-04-28 | (实时 query) |

**Diff**: -¥18,194 (-1.8%). 18 股 sell from market value ¥901,090 → cash ~¥882,896.

**DB drift 原因** (5 层 root cause):

| 层 | 描述 | 责任 |
|---|---|---|
| L1 | 2026-04-29 ~14:00 user 决策清仓 (handoff:27 ground truth) | User instruction |
| L2 | 4-29 20:39 Claude PR #150 prompt 软处理为 link-pause (commit 626d343), 紧急清仓留 user 手工 | **Claude 主责** |
| L3 | CC 收 prompt 后没主动 STOP 反问 user 真意 | CC 次责 |
| L4 | 4-30 某时 user 自己 GUI 手工 sell 18 股 (因 link-pause 不真清仓) | User 后续补救 |
| L5 | DB silent drift: position_snapshot 4-30 0 行 / trade_log 4-28+ 0 行 / risk_event_log 0 行 — schtask DailySignal 4-29+ disabled + qmt_data_service 4-04 起断连 26 天 silent skip + LL-081 guard 不 cover "无法查询" 场景 | 流程债 (T0-15/16/17/18) |

---

## §4 forensic 价格不可考

[E:/国金QMT交易端模拟/userdata_mini/log/XtMiniQmt_2026{0429,0430}.log](E:\国金QMT交易端模拟\userdata_mini\log) 实测:

| 日期 | query positions count | 含义 |
|---|---|---|
| 4-29 全天 | 1210 次, **全 19 持仓** | user 4-29 没真清仓 (虽 14:00 给指令) |
| 4-30 当天 | 仅 1 次返 1 (CC 14:54 调用) | QMT 客户端长时间关闭, user 在 GUI 操作 |

**结论**:
- **清仓时点**: 2026-04-30 某时 (forensic 不可精确)
- **清仓价格**: **不可考** — user GUI 手工 sell, **不走** xtquant API → XtMiniQmt log 主要是 query 路径, 0 send_stock_order / onStockOrder / onStockTrade pattern hit
- **损失推算**: -¥18,194 (-1.8%) by NAV diff (1,011,714 stale → 993,520 实测)
- **铁律 27 不 fabricate**: 价格 unknown 时不补 trade_log SELL × 18 行 (不 invent 数据)

---

## §5 5 层 root cause + 责任拆解 (沿用 D3-A Step 4 修订)

详见 [STATUS_REPORT_2026_04_30_D3_A_step4_qmt_clearance_spike.md](STATUS_REPORT_2026_04_30_D3_A_step4_qmt_clearance_spike.md) §"修订记录" + LL-089 + LL-090 (LESSONS_LEARNED.md).

**关键责任清单**:
- **Claude (主责)**: PR #150 prompt 把 user "全清仓" 软处理为 "link-pause", 没显式 sell + 没向 user 反问 "我理解为锁未来交易但不卖现仓, 对吗?"
- **CC (次责)**: 收 prompt 后没主动 STOP 反问 (沿用永久工作准则第 2 条 "主动找漏" 应挑战但没挑战)
- **User (上下文)**: 4-29 当晚 link-pause 落地后 user 没说 "等等你没卖", 4 方沉默接受软方案
- **流程债**: T0-15/16/17/18 (4 项 P0/P1)

---

## §6 Tier 0 债清单 (本 PR 涉及)

| ID | 描述 | 严重度 | 来源 |
|---|---|---|---|
| T0-15 | LL-081 guard 不 cover QMT 断连场景, 真金 silent drift 漏检 | **P0** | D3-A Step 4 spike F-D3A-NEW-3 |
| T0-16 | qmt_data_service 26 天连续 silent skip 持仓同步失败, 0 告警 (铁律 33 严重违反) | **P0** | D3-A Step 4 spike F-D3A-NEW-4 |
| T0-17 | Claude prompt 设计层默认软处理 user 真金指令 (4-29 "全清仓"→link-pause) | **P0** | D3-A Step 4 修订 |
| T0-18 | 注释 Beat schedule 后必 Servy restart 才生效 — 候选铁律 X9 | **P1** | D3-A Step 5 spike F-D3A-NEW-6 |

**未来修法**: 各债独立 PR, 见 D3-B 中维度 5 个 audit + 批 2 写代码阶段.

---

## §7 LL 沉淀 (累计 22 → 24, +2 自 Step 5 spike merged 后)

| 第 | LL ID | 描述 |
|---|---|---|
| 21 | LL-089 | Claude spike prompt 候选集封闭 + 不查 user 决策日志 |
| 22 | LL-090 | Claude 让 user 二次验证 ground truth (D44 减负反向违反) |
| 23 | (Step 5 候选, 待入册) | Beat schedule 注释 ≠ 服务真停, 必 Servy restart 才生效 |
| **24** | (本 PR 候选, 待入册) | **risk_event_log CHECK constraint allowed values 必实测** — Step 5 Q2(c) SQL 模板 action_taken='manual_audit_recovery' 被 CHECK 拒, 实际 allowed 'sell'/'alert_only'/'bypass' |

---

## §8 PR chain (audit recovery 触发到落地)

| PR | 内容 | 时点 |
|---|---|---|
| #150 | link-pause T1-sprint (LIVE_TRADING_DISABLED + Beat 风控暂停, 紧急清仓留 user 手工) | 4-29 20:39 |
| #153 | runbook init | (前期治理) |
| #154 | PowerShell 版本纠正 | (前期治理) |
| #155 | D3-A 全方位审计 P0 维度 5/14 | 4-30 03:20 |
| #156 | D3-A Step 1+2 spike (F-D3A-1 P0 实测确认) | 4-30 04:20 |
| #157 | D3-A Step 3 spike (F-D3A-14 真因证实) | 4-30 13:30 |
| **#158** | **D3-A Step 4 spike (QMT silent drift P0 真因 — 误判 user 未察觉)** | 4-30 14:48 |
| **#159** | **D3-A Step 4 修订 (root cause 重构 + LL-089/090)** | 4-30 15:14 |
| **#160** | **D3-A Step 5 spike (钉钉静音 + audit 落地路径 forensic)** | 4-30 15:29 |
| **本 PR** | **D3-A Step 5 落地 (钉钉静音 + audit log 补全)** | 4-30 15:38+ |

---

## §9 PT 重启 gate (剩余 prerequisite)

PT 重启前必修 (user 决策):

- [ ] T0-15 修: LL-081 v2 — 加 "持仓查询连续失败 N 次 → guard 触发 + risk_event_log + 告警"
- [ ] T0-16 修: qmt_data_service 改 fail-loud (连续 N min 失败 raise + risk_event_log + 钉钉)
- [ ] T0-17 修: ADR-021 + 候选铁律 X8 "user 真金指令必须显式确认执行方式, 不允许 prompt 设计层默认软处理"
- [ ] T0-18 修: 候选铁律 X9 "schedule / config 注释后必显式重启服务才生效, schedule 类 PR 必含 post-merge ops checklist"
- [ ] **DB 4-28 19 股 stale snapshot 清理** (本 PR 不做, 留 PT 重启 gate 时 user 授权 DELETE)
- [ ] **重置 cb_state live = ¥993,520** (实测真账户值, 留 PT 重启 gate)
- [ ] paper-mode 5 个交易日 dry-run (沿用 Session 44 末 handoff)
- [ ] `.env paper→live` 显式授权 (现 LIVE_TRADING_DISABLED=true 二级硬开关)

**当前生产状态** (本 PR 落地后):
- 真账户: 0 持仓, ¥993,520.16 cash, fail-secure
- LIVE_TRADING_DISABLED=true (broker 层硬阻 sell/buy)
- Beat 已 restart, intraday-risk-check + risk-daily-check 不再触发 (注释生效)
- DailySignal / DailyExecute / IntradayMonitor / DailyReconciliation / CancelStaleOrders schtask 全 Disabled
- DB 4-28 stale 19 股 snapshot 仍在 (audit log row 已写, stale 标记)
- risk_event_log: 1 行 P0 audit row (id=67beea84) 真因 + 责任 + ground truth 完整

---

## §10 关联

- [STATUS_REPORT_2026_04_30_D3_A.md](STATUS_REPORT_2026_04_30_D3_A.md) (D3-A 主报告)
- [STATUS_REPORT_2026_04_30_D3_A_step1_step2_spike.md](STATUS_REPORT_2026_04_30_D3_A_step1_step2_spike.md)
- [STATUS_REPORT_2026_04_30_D3_A_step3_pt_audit_spike.md](STATUS_REPORT_2026_04_30_D3_A_step3_pt_audit_spike.md)
- [STATUS_REPORT_2026_04_30_D3_A_step4_qmt_clearance_spike.md](STATUS_REPORT_2026_04_30_D3_A_step4_qmt_clearance_spike.md) (Step 4 spike + 修订记录)
- [STATUS_REPORT_2026_04_30_D3_A_step5_silence_audit_forensic.md](STATUS_REPORT_2026_04_30_D3_A_step5_silence_audit_forensic.md) (Step 5 spike forensic)
- [STATUS_REPORT_2026_04_30_D3_A_step5_landing.md](STATUS_REPORT_2026_04_30_D3_A_step5_landing.md) (本 PR Step 5 落地)
- [link_paused_2026_04_29.md](link_paused_2026_04_29.md) (PR #150 link-pause 设计稿, 含紧急清仓 user 手工指引)
- [memory/project_sprint_state.md:27](memory/project_sprint_state.md:27) (Session 44 末 handoff "用户决策'全清仓暂停 PT + 加固风控'")
- [LESSONS_LEARNED.md](LESSONS_LEARNED.md) LL-089 / LL-090 (D3-A Step 4 修订沉淀) + LL-091 候选 (Step 5) + LL-092 候选 (本 PR)
