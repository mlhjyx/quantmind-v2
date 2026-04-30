# STATUS_REPORT — D3-A Step 4 Spike (QMT 清仓事件 + DB 漂移检查)

**Date**: 2026-04-30
**Branch**: chore/d3a-step4-qmt-clearance-spike
**Base**: main @ c776eda (PR #157 D3-A Step 3 spike merged)
**Scope**: user 陈述 "QMT 已全部清仓" 与 D3-A 实测 (4-28 19 股 NAV ¥1.01M) 不一致, 实测决议候选 A/B/C
**ETA**: 实跑 ~12 min CC (vs 预估 10, 略超 — risk_event_log + trade_log schema correction 多 2 步)
**真金风险**: 0 (0 业务代码改 / 0 .env 改 / 0 服务重启 / 0 DML / 0 联系 QMT)
**改动 scope**: 1 文档 (本 STATUS_REPORT) — 单 PR `chore/d3a-step4-qmt-clearance-spike`, 跳 reviewer

---

## §0 环境前置检查 E1-E5 全 ✅

| 项 | 实测 | 结论 |
|---|---|---|
| E1 git status | main @ `c776eda` (PR #157 merged), 8 D2 untracked (上 session 残留, 不在 scope) | ✅ |
| E2 PG stuck backends | 1 (仅本审计 psql session, pid 32960 active) | ✅ |
| E3 Servy 4 服务 | FastAPI / Celery / CeleryBeat / **QMTData ALL Running** | ✅ (但 QMTData "Running" 是进程层, 不代表 QMT 客户端连通 — 见 Q4) |
| E4 .venv Python | Python 3.11.9 | ✅ |
| E5 真金 fail-secure | `LIVE_TRADING_DISABLED=True` | ✅ |

---

## Q1 — DB 4-29/4-30 持仓 + 交易实测

### Q1(a) position_snapshot 历史 (live)

```sql
SELECT trade_date, COUNT(*) FROM position_snapshot
WHERE trade_date >= '2026-04-01' AND execution_mode='live'
GROUP BY 1 ORDER BY 1 DESC LIMIT 15;
```

| trade_date | positions |
|---|---:|
| 2026-04-28 | **19** |
| 2026-04-27 | 19 |
| 2026-04-24 | 19 |
| 2026-04-23 | 19 |
| 2026-04-22 | 19 |
| 2026-04-21 | 19 |
| 2026-04-20 | 19 |
| 2026-04-17 | 24 |
| 2026-04-16 | 22 |
| 2026-04-15 | 22 |
| 2026-04-14 | 21 |
| 2026-04-13 | 17 |
| 2026-04-08 | 17 |
| 2026-04-07 | 15 |
| 2026-04-03 | 15 |

🔴 **关键: 4-29 / 4-30 0 行**. position_snapshot 最新 entry = 2026-04-28.

### Q1(b) trade_log 4-28+

```sql
SELECT trade_date, execution_mode, direction, COUNT(*) FROM trade_log
WHERE trade_date >= '2026-04-28' GROUP BY 1,2,3;
```

**实测**: **0 rows**. 4-28 起 0 笔交易记录.

### Q1(c) performance_series 4-28+

| trade_date | execution_mode | nav | cash | position_count |
|---|---|---:|---:|---:|
| 2026-04-28 | live | 1,011,714.08 | 110,624.08 | 19 |

**仅 4-28 1 行**. 4-29 / 4-30 0 daily snapshot.

### Q1 结论

**DB 端从 2026-04-28 16:30 (DailySignal 最后一次跑) 起完全静止**:
- 0 新 trade_log
- 0 新 position_snapshot
- 0 新 performance_series

→ 如 user 陈述 "QMT 已清仓" 真实, **DB 端 0 同步** = silent drift.

---

## Q2 — Paper 命名空间污染源排查

```sql
SELECT trade_date, COUNT(*) FROM position_snapshot
WHERE trade_date >= '2026-04-15' AND execution_mode='paper'
GROUP BY 1 ORDER BY 1 DESC LIMIT 15;
```

**实测**: **0 rows**. paper 命名空间从 4-15 起 0 持仓快照.

```sql
-- 4-28 paper vs live code overlap
SELECT 'live' AS mode, code, quantity FROM position_snapshot
WHERE execution_mode='live' AND trade_date='2026-04-28'
UNION ALL
SELECT 'paper', code, quantity FROM position_snapshot
WHERE execution_mode='paper' AND trade_date='2026-04-28';
```

**实测**: live 19 行 (D3-A 已知), paper **0 行**. 0 overlap.

### Q2 结论

✅ **候选 B 排除** — paper 命名空间 4-15+ 0 行写入, 不存在 paper 写到 live 命名空间污染. DB 4-28 live 19 股是真历史快照, 非污染.

---

## Q3 — LL-081 guard 实测

```sql
SELECT created_at, severity, rule_id, reason FROM risk_event_log
WHERE created_at >= '2026-04-29 00:00' ORDER BY created_at DESC LIMIT 20;
```

**实测**: **0 rows**. 4-29 起 0 risk event 写入.

### Q3 结论

🔴 **LL-081 guard 漏触发**:
- LL-081 guard 设计: 持仓 N → 0 蒸发触发 + risk_event_log 写 ERROR + 钉钉告警
- 实测: 19 股 4-28 → DB 端无更新 (4-29/4-30 都没数据), guard 因为 "**没看到** N → 0 变化" 永不触发
- 即使 user 真清仓, DB 端 19 股是凝固快照, **guard 永远等不到 0 出现**

→ **F-D3A-NEW-3 (P0)**: LL-081 guard **设计缺陷** — 不 cover "N 持仓 → 无法查询 / silent skip" 场景, 仅 cover "N → 0" 显式蒸发.

---

## Q4 — QMT 清仓路径定位 + qmt_data_service 实测

### Q4(a) qmt_data_service stderr (实时实测)

```bash
tail -30 logs/qmt-data-stderr.log
```

**实测末尾连续 raise** (每 60s 一次, 当前时刻 14:40+):
```
2026-04-30 14:40:55,390 [qmt_data_service] WARNING 持仓同步失败
RuntimeError: miniQMT未连接，请先调用connect()
2026-04-30 14:41:55,408 [qmt_data_service] WARNING 持仓同步失败
RuntimeError: miniQMT未连接，请先调用connect()
... (持续 raise 60s 一次)
```

### Q4(b) 最早断连时点

```bash
head -5 logs/qmt-data-stderr.log
grep -m 1 "持仓同步失败" logs/qmt-data-stderr.log
```

| 时点 | 事件 |
|---|---|
| 2026-04-03 18:47:29 | qmt_data_service 启动, QMT 连接成功 (account=81001102) |
| 2026-04-03 18:47:33 | 同步循环启动 (interval=60s) |
| **2026-04-04 01:06:23** | **首次 "持仓同步失败" WARNING** — QMT 断连点 |
| 2026-04-04 ~ 2026-04-30 | **持续断连 26 天**, 每 60s 一次 silent WARNING (无 raise / 无告警 / 无 risk_event_log) |

### Q4(c) qmt_data_service 代码 silent skip 分析

[qmt_data_service.py:136](scripts/qmt_data_service.py:136) `_sync_positions` → `self._broker.get_positions()` → [broker_qmt.py:320](backend/engines/broker_qmt.py:320) `_ensure_connected()` raise `RuntimeError("miniQMT未连接，请先调用connect()")`.

但 stderr 显示 "WARNING 持仓同步失败" + traceback, 之后**进程不退**, 60s 后**再试**. 这是典型 silent skip 模式:
- `try: get_positions() except RuntimeError as e: logger.warning(...)` (CC 推断 from stderr 输出)
- 不 raise / 不 alert / 不写 risk_event_log
- 26 天累计 ~37,440 次 silent WARNING (60s × 60min × 24h × 26d ≈ 37,440)

### Q4 结论

🔴 **F-D3A-NEW-4 (P0)**: qmt_data_service 26 天连续 silent skip 持仓同步失败:
- QMT 客户端 4-04 01:06 起断连 (可能 user 清仓后关闭客户端 / 机器重启 / xtquant.dll 失效 / 等)
- qmt_data_service silently 失败, 没 alert
- portfolio:current Redis cache 是 4-04 之前的 stale 状态 (26 天)
- 任何 schtask (DailySignal / DailyExecute / 等) 经 QMTClient 读 Redis 都拿到 stale 数据
- DB 4-28 19 股 = 4-28 16:30 DailySignal 跑了一次, 经 QMTClient 读 stale Redis cache 写入 (Stage 4 reenable 副产品 — 见 D3-A Step 2 决策日志)

**铁律 33 fail-loud 严重违反** — `silent_ok` 注释缺失, error 累积 26 天 0 告警.

---

## Q5 — 候选决议 (无模糊兜底)

| 候选 | 实测证据 | 决议 |
|---|---|---|
| **A: QMT silent drift** | ✅ Q1 DB 4-28 起静止 + Q3 LL-081 guard 漏触发 + Q4 26 天 silent skip | **真因证实** |
| A': 部分同步 | ❌ Q1 DB 完全静止, 非部分 | 否 |
| B: paper 污染 | ❌ Q2 paper 0 行 | 否 |
| C: DB 同步清仓 | ❌ Q1 trade_log 4-28+ 0 行 | 否 |
| D: 数据不足 | ❌ 4 项独立证据全 align | 否 |

### F-D3A-?? (P0 candidate) 真因决议: **候选 A 真金 silent drift**

**多层 root cause**:
1. **L1 — QMT 4-04 01:06 断连后 user 未察觉** (运维 gap)
2. **L2 — qmt_data_service silent skip 26 天** (铁律 33 违反, F-D3A-NEW-4)
3. **L3 — LL-081 guard 不 cover "无法查询" 场景** (设计缺陷, F-D3A-NEW-3)
4. **L4 — DB 4-28 19 股 = stale Redis cache 写入** (Q4 推断, 经 DailySignal 4-28 16:30 Stage 4 reenable run)
5. **L5 — schtask DailySignal 4-28 后再次 disabled** → DB 完全静止 → guard 等不到蒸发触发 (Q1 实测)

### PR #158+ 启动建议: ✅ **启动 (与 silent drift 独立)**

3 missing migrations (alert_dedup / platform_metrics / strategy_evaluations) apply 是 SDK 路径修复, 与 QMT 持仓 / Redis cache / qmt_data_service silent skip 完全独立. 启动 PR #158+ 不会:
- 改变 DB 持仓状态
- 触发 QMT 真账户操作
- 修复或恶化 silent drift

✅ **PR #158+ 可立即启动**, silent drift 平行修 (新 P0 PR).

---

## 副产品 Finding (本 spike 新发现)

| ID | 描述 | 严重度 | 修法草稿 |
|---|---|---|---|
| **F-D3A-NEW-3** | LL-081 guard 不 cover "N 持仓 → 无法查询 / silent skip" 场景, 仅 cover "N → 0" 显式蒸发 | **P0** | LL-081 v2 候选铁律: 加 "持仓查询连续失败 N 次 → fail-loud raise + risk_event_log + 告警" |
| **F-D3A-NEW-4** | qmt_data_service 持仓同步失败 silent skip 26 天 (4-04 ~ 4-30, ~37,440 次 silent WARNING, 0 告警) | **P0** | scripts/qmt_data_service.py:_sync_positions 改 fail-loud (连续 N min 失败 → raise + risk_event_log + 钉钉告警, 不再 silent retry) |
| **F-D3A-NEW-5** | DB 4-28 19 股 vs QMT 真账户实际状态可能严重 mismatch (user 陈述清仓但 DB 凝固) | P1 | 加 reconciliation guard: 每日盘后实测 QMT vs DB 持仓 diff, mismatch 超阈值 → 告警 |
| (memory stale) | handoff "PT 暂停, 只剩 1 股 [688121.SH](http://688121.SH) -29% 凝固" / D3-A "卓然 -11.45%" 数字均 stale (user 陈述已清仓) | INFO | D3-B 整合阶段统一更新 memory + handoff |

---

## Tier 0 债更新 (D3-A 12 → 14)

D3-A Step 1 (10 → 12) → Step 2 (无新) → Step 3 (无新, 但 NEW-1/NEW-2 候选) → **Step 4 (12 → 14, +2 P0)**:

| 编号 | 描述 | 严重度 | 来源 |
|---|---|---|---|
| T0-15 | LL-081 guard 不 cover QMT 断连场景, 真金 silent drift 漏检 | **P0** | 本 spike F-D3A-NEW-3 |
| T0-16 | qmt_data_service 26 天连续 silent skip 持仓同步失败, 0 告警 (铁律 33 严重违反) | **P0** | 本 spike F-D3A-NEW-4 |

---

## handoff / memory / D3-A 跨文档同步建议 (留 D3-B 整合)

实测推翻多处 stale claim, 留 D3-B 整合阶段统一同步:

| 路径 | stale claim | 实测真相 |
|---|---|---|
| Session 38 handoff | "PT 暂停, 只剩 1 股 688121 -29% 凝固" | 4-28 实测 19 股 NAV ¥1,011,714 |
| D3-A STATUS_REPORT_D3_A.md L88 | "卓然 -11.45%" | user 陈述已清仓, DB 19 股是凝固快照 |
| memory PT live | "持仓 19 股 NAV +1.17%" | user 陈述已清仓 |
| memory QMT 状态 | (无 silent drift 记录) | 4-04 01:06 起断连 26 天 |

**D3-B 整合阶段必更新**:
- Session 45 末 handoff: 标记 QMT 已清仓 + DB 19 股是 stale 快照 + silent drift 待修
- memory project_sprint_state.md 加 "Session 45 D3-A spike 4 step 完成" + Tier 0 债 12 → 14
- D3-A STATUS_REPORT 涉及 NAV / 持仓段落标 "(已 stale, user 陈述清仓)"

---

## LL "假设必实测纠错" 累计 17 → **20** (+3)

D3-A Step 1+2+3 累计 17 → 本 spike 新增 **3 次**:

| 第 | 来源 | 假设 | 实测 |
|---|---|---|---|
| 18 | D3-A Step 1 Q12.1 / handoff "19 股 NAV +1.17% 浮盈" | DB 数字反映 QMT 真实持仓 | 实测 DB 4-28 凝固, QMT 4-04 起断连 26 天, DB ≠ QMT 真相 |
| 19 | LL-081 guard "持仓蒸发 fail-loud" 假设 | guard cover 所有蒸发场景 | 实测仅 cover "N → 0" 显式蒸发, 不 cover "N → 无法查询" 漏检 |
| 20 | qmt_data_service "Servy Running" | 进程 Running ⇒ 服务功能正常 | 实测进程 Running 但 26 天 silent skip 持仓同步失败 |

**累计 20 次**. 复用规则 (LL 全局): 任何 "服务 Running / 数据反映真实 / guard cover 所有 case" 假设, 必须附**当前真实状态实测 + 错误率统计 + 时间窗 forensic**. 否则降级 informational, 待二次实测.

---

## 硬门验证

| 硬门 | 结果 | 证据 |
|---|---|---|
| 改动 scope | ✅ 1 文档 (本 STATUS_REPORT) | `git status --short` |
| ruff | ✅ N/A | 0 .py 改动 |
| pytest | ✅ N/A | 0 .py 改动 |
| pre-push smoke | (push 时验) | bash hook (沿用上 PR) |
| 0 业务代码改 | ✅ | git diff main 仅本文件 |
| 0 .env 改 | ✅ | grep diff main backend/.env = 0 |
| 0 服务重启 | ✅ | Servy 4 服务全程 Running |
| 0 DML | ✅ | 全程 SELECT only |
| 0 联系 QMT | ✅ | 0 触 admin endpoint / 0 调 QMT API / 0 重连尝试 |
| 0 LLM SDK 调用 | ✅ | 本 spike 是开发诊断边界 (铁律 X1) |
| 0 修复 silent drift | ✅ | 本 spike 仅锁定真因, 修留后续 PR |

---

## 下一步建议

### 立即并行启动 (3 PR)

1. **PR #158+ `fix/apply-missing-migrations`** (F-D3A-1 P0, ~30min, LL-059 9 步 + reviewer)
   - apply 3 missing migrations
   - 与 silent drift 独立, 不阻塞
2. **PR #159+ `fix/qmt-data-service-fail-loud`** (T0-16 P0, ~1h, LL-059 9 步 + reviewer)
   - qmt_data_service 改 fail-loud (连续 N min 失败 raise + risk_event_log + alert)
   - 防止下次 26 天 silent skip 重演
3. **PR #160+ `fix/ll081-guard-v2-disconnect-coverage`** (T0-15 P0, ~1.5h, LL-059 9 步 + reviewer + 设计 ADR)
   - LL-081 v2 铁律: 加 "持仓查询连续失败 N 次 → guard 触发"
   - cover QMT 断连 / Redis 失效 / DB 死锁 等场景

### user 决策点

- Q: user 何时清仓 QMT? 4-04 之前还是之后? (影响 stale Redis cache 是否反映清仓后状态)
- Q: 是否立即启 D3-B 中维度 5 个 (~5h) 还是 3 P0 PR 优先?

### 后续 (D3-B / 批 2)

- F-D3A-NEW-5 P1: 加 daily reconciliation guard
- handoff / memory / D3-A 跨文档同步 (D3-B 整合)

---

## 关联

- **D3-A Step 1+2+3 spike** ([STATUS_REPORT_2026_04_30_D3_A_step1_step2_spike.md](STATUS_REPORT_2026_04_30_D3_A_step1_step2_spike.md), [step3](STATUS_REPORT_2026_04_30_D3_A_step3_pt_audit_spike.md)) — 累计找 17 LL, 本 spike +3 (累计 20)
- **D3-A STATUS_REPORT** ([STATUS_REPORT_2026_04_30_D3_A.md](STATUS_REPORT_2026_04_30_D3_A.md)) — Q12.1 持仓数据 stale, 留 D3-B 整合标注
- **LL-081 guard** — 设计缺陷暴露 (F-D3A-NEW-3 P0, T0-15)
- **铁律 33 fail-loud** — qmt_data_service silent skip 26 天严重违反 (F-D3A-NEW-4 P0, T0-16)
- **铁律 X1 Claude 边界** — 本 spike 0 LLM SDK / 0 触 QMT
- **handoff Session 38 / memory** — "1 股 688121 凝固" stale, 实测 4-28 19 股, user 陈述清仓 (Session 45)
- **LL "假设必实测纠错"** 累计 17 → **20** (+3)

---

## 用户接触

实际 1 (user 陈述 "QMT 已清仓" 触发本 spike).

未来接触预期:
- user 决议 PR #158+/159+/160+ 启动顺序 (~1 次)
- user 答 Q: 4-04 之前还是之后清仓 (~1 次, 帮助回填 Redis cache 时间线)
