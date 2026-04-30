# STATUS_REPORT — D3 整合 PR + narrative v4 hybrid 定论 (2026-04-30)

**Date**: 2026-04-30 ~18:30+
**Branch**: chore/d3-integration-v4-narrative
**Base**: main @ fb256c0 (PR #168 T0-19 Phase 2 merged)
**Scope**: D3 系列 narrative v3 → v4 hybrid 定论 + LL-095/096 入册 + 跨文档同步
**0 业务代码 / 0 真金 / 0 DML**

---

## §0 触发

PR #168 Phase 2 实测 + user 2026-04-30 confirm 真因 = D3-A Step 4 narrative 第 4 轮修订必要.

---

## §1 v4 narrative 真相 (定论)

**18 股清仓 = 17 + 1 hybrid**:

### 17 股 CC 4-29 10:43:54 emergency_close success (status=56)

`logs/emergency_close_20260429_104354.log` 实测 (LL-093 forensic 5 类源 (a)):
- SZ: 000333, 000507, 002282, 002623, 300750
- SH: 600028, 600900, 600938, 600941, 601088, 601138, 601398, 601857, 601988, 688211, 688391, 688981

### 1 股 [688121.SH](https://github.com) (卓然新能 4500 股) hybrid 路径

```
2026-04-29 10:43:57,400 [INFO] [QMT] 下单: 688121.SH sell 4500股 @0.000 type=market
2026-04-29 10:43:57,506 [ERROR] [QMT] 下单失败: order_id=1090551149,
    error_id=-61, error_msg=最优五档即时成交剩余撤销卖出 [SH688121]
    [251005][证券可用数量不足]
2026-04-29 10:43:57,506 [INFO] [QMT] 委托回报: order_id=1090551149,
    code=688121.SH, status=57, traded=0/4500
```

→ 4-29 跌停 cancel (status=57, error_id=-61) → 4-30 跌停解除 user QMT GUI 手工 sell

### 真因 (user 2026-04-30 confirm)

**跌停撮合规则**:
- 4-29 卓然 -29% 跌停 (Session 44 handoff "卓然 -29%" + D3-A 4-28 实测 -11.45% recovery 时序佐证)
- emergency_close_all_positions.py 用 `xtconstant.MARKET_SH_CONVERT_5_CANCEL` (42, 最优五档即时成交剩余撤销卖出)
- 跌停板**无买盘对手方** → broker 视可用数量=0 → cancel
- 4-30 跌停解除 → user QMT GUI 手工 sell 4500 股成功

### T+1 假设撤销 (实测推翻)

```sql
SELECT trade_date, quantity, avg_cost FROM position_snapshot
WHERE code='688121.SH' AND execution_mode='live' AND trade_date >= '2026-04-20';
```

| trade_date | quantity | avg_cost |
|---|---:|---:|
| **2026-04-20** | 4500 | ¥10.8800 |
| 2026-04-21~28 | 4500 | ¥10.8979 |

→ [688121.SH](https://github.com) 4-20+ 持仓 ≥ 9 天, T+1 早已解除. error_id=-61 真因不是 T+1.

---

## §2 narrative 演进 4 轮历史

| 版本 | PR | 主张 | 推翻原因 |
|---|---|---|---|
| v1 | #158 | "user 未察觉 + L1 QMT 4-04 断连后运维 gap" | user 4-30 14:50 质问 "4.29 我叫你清仓的, 你忘记了?" |
| v1 修订 | #159 | "user 4-29 ~14:00 决策 + Claude 软处理 link-pause + user 4-30 GUI sell 18 股" | D3-C F-D3C-13 实测 logs/emergency_close_20260429_104354.log |
| v2 (L4 因果链) | #163 | "stale Redis cache → DailySignal 写 DB stale" | D3-B F-D3B-7 实测 portfolio:current 0 keys, 真因 QMTClient fallback DB self-loop |
| v3 | #166 | "CC 4-29 emergency_close 18 股全 status=56" | PR #168 实测 17 fills + 1 cancel |
| **v4** | **#169 (本 PR)** | **17 CC 4-29 + 1 user 4-30 GUI sell hybrid + 跌停撮合真因** | **(本 PR 定论)** |

**4 轮修订 50 小时** (4-30 13:30 PR #158 → 18:30 PR #169) — 暴露 forensic 类 spike 单次结论易漏 (沿用 LL-096 复用规则).

---

## §3 5 文件改

| 文件 | 改动 | 关键内容 |
|---|---|---|
| `docs/audit/SHUTDOWN_NOTICE_2026_04_30.md` | +95 行 (新 §12) | v4 修订记录 + v3→v4 关键修订表 + 18 股 ticker 完整 v4 分类 |
| `LESSONS_LEARNED.md` | +95 行 (LL-095 + LL-096) | LL-095 status=57 真因 4 维度判定 + LL-096 forensic 修订不可一次性结论 |
| `memory/project_sprint_state.md` (user-local) | description 更新 | Session 45 末 17+1 hybrid + 跌停真因 |
| `CLAUDE.md` | L629 + L669 v4 标记 | xtquant 真账户实测段 + 历史快照说明段 |
| `docs/audit/STATUS_REPORT_2026_04_30_D3_integration_v4_narrative.md` (本文件) | 新建 | D3 整合 PR 总结报告 |

---

## §4 LL 累计 (28 → 30, +2)

| LL | 入册 PR | 描述 |
|---|---|---|
| LL-091 | #164 | 推断必标 P3-FOLLOWUP, 实测验证 (D3-A stale Redis cache 推论被推翻) |
| LL-092 | #164 | 文档 N ≠ 实测 N alive (StreamBus 8/10 streams, 1 alive) |
| LL-093 | #166 | forensic 类 spike 必查 5 类源 (D3-A Step 4 漏查 logs/emergency_close_*.log) |
| LL-094 | #167 | risk_event_log CHECK constraint 必先 pg_get_constraintdef 实测 |
| **LL-095** | **#169 (本 PR)** | **emergency_close status=57 cancel 真因综合判定 (4 维度: market / broker / holding age / position state)** |
| **LL-096** | **#169 (本 PR)** | **forensic 类 spike 修订不可一次性结论, 必留 P3-FOLLOWUP 尾巴 + v_N 修订标记 + 4 维度 self-check** |

LL "假设必实测" 累计 28 → **30**.

---

## §5 Tier 0 债 (16 项不变)

| ID | 描述 | 状态 |
|---|---|---|
| T0-15 | LL-081 guard 不 cover QMT 断连/fallback | P0 (待批 2) |
| T0-16 | qmt_data_service 26 天 silent skip | P0 (待批 2) |
| ~~T0-17~~ | Claude 软处理 user 指令 | v3 撤销 |
| T0-18 | Beat schedule 注释式 link-pause 失效 | P1 (待批 2) |
| **T0-19** | **emergency_close audit hook** | ✅ **PR #168 落地 (业务代码 + 21 unit tests)** |
| F-D3A-1 | 3 missing migrations (alert_dedup / platform_metrics / strategy_evaluations) | P0 (待批 2) |

T0-19 修法范围**不变** (PR #168 Phase 2 已正确处理 17 fills backfill, 失败单 688121 不 fabricate, 沿用铁律 27 ✅).

---

## §6 PR 链回顾 (#155-#169 共 14 PR merged)

| PR | 内容 |
|---|---|
| #155 | D3-A 全方位审计 P0 维度 5/14 |
| #156 | D3-A Step 1+2 spike (F-D3A-1 P0) |
| #157 | D3-A Step 3 spike (F-D3A-14) |
| #158 | D3-A Step 4 spike (v1, 误判) |
| #159 | D3-A Step 4 修订 v1 |
| #160 | D3-A Step 5 spike |
| #161 | D3-A Step 5 落地 + SHUTDOWN_NOTICE |
| #162 | D3-B 全方位审计中维度 5/14 |
| #163 | D3-A Step 4 L4 修订 v2 (Redis cache 推翻) |
| #164 | D3-B 跨文档同步 + LL-091/092 |
| #165 | D3-C 全方位审计低维度 4/14 + F-D3C-13 |
| #166 | D3-A Step 4 narrative v3 修订 |
| #167 | T0-19 Phase 1 design + audit scripts + LL-094 |
| #168 | T0-19 Phase 2 业务代码 + 21 tests + 17 fills 实测 |
| **#169** | **D3 整合 v4 narrative + LL-095/096 (本 PR)** |

---

## §7 验证

| 硬门 | 结果 |
|---|---|
| 改动 scope | ✅ 5 文件 (4 docs + 1 memory) |
| 0 业务代码 | ✅ |
| 0 .env / configs/ / scripts/ | ✅ |
| 0 真金 / 0 DML / 0 alembic | ✅ |
| pre-push smoke | (push 时验) |
| ruff | (0 .py 改动, N/A) |

---

## §8 下一步 (user 决议)

1. **批 2 P0 修启动** (T0-15/16/18 + F-D3A-1, T0-19 已落地) — 解锁 PT 重启 gate 5/7 prerequisite
2. **scripts/audit/check_pt_restart_gate.py** — PT 重启决议时跑
3. **Session 46 handoff** — 停, 等明日决议

---

## §9 用户接触

实际 1 (user 2026-04-30 confirm 跌停撮合真因 + GUI sell 时点). 0 其他 user 决议必要.
