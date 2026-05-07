# ADR-027: L4 STAGED default + 反向决策权论据 + 跌停 fallback

> **Status**: Proposed (5-02 起草, 等 user 决议; user merge PR = Accept signal)
> **Date**: 2026-05-02
> **Authors**: Claude.ai+user 战略对话 sediment (V3 §20.1 #1 + #7 决议)
> **Related**:
> - [docs/QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md](../QUANTMIND_RISK_FRAMEWORK_V3_DESIGN.md) §7.1 (STAGED 设计) + §7.2 (跌停 fallback) + §13 #8 (DingTalk 未读 default execute) + §18.1 row 4 (原 ADR-024 待办 占用 factor-lifecycle, # 下移 027)
> - [docs/adr/ADR-024-factor-lifecycle-vs-registry-semantic-separation.md](ADR-024-factor-lifecycle-vs-registry-semantic-separation.md) (5-02 sprint factor task, ADR-024 主题 NOT V3 设计 § scope)
> - [docs/adr/ADR-022-sprint-treadmill-revocation.md](ADR-022-sprint-treadmill-revocation.md) (anti-pattern enforcement)

## §1 Context

### 1.1 触发背景

- **4-29 PT 暂停清仓事件**: live 真生产 (688121 -29% / 000012 -10%), 30 天 risk_event_log 0 行, user 决议全清仓暂停 PT (5-02 sprint close 红线 cash=¥993,520.66 / 0 持仓).
- **V3 §7.1 STAGED 设计**: L4 风控触发后**不立即下单**, 走 staged 流程 (T0 alert → T+30min 默认 execute / T+30min user override → cancel), 给 user 反向决策权.
- **user "很少看" 真实场景**: V3 §13 #8 sediment, user 离线 / 移动设备 DingTalk 未读 → default execute, 不元告警.
- **V3 §18.1 row 4 待办冲突**: 原 cite "ADR-024 → L4 STAGED" 被 5-02 sprint factor task `ADR-024-factor-lifecycle-vs-registry-semantic-separation` 占用. user 决议 (a-iii): # 下移 027, ADR-024 factor-lifecycle 主题 0 改动.

### 1.2 跌停 fallback 触发

4-29 case: 688121 跌停 -10%, limit -2% sell order 不成交 (跌停撮合规则 — 仅买盘, 0 卖盘成交). 后果: STAGED cancel 窗口结束后 default execute, 但 limit 单跌停日无法成交, sell 延期到次日开盘.

V3 §7.2 跌停 fallback 设计: STAGED execute 路径检测跌停 → 切换到次日开盘 limit 单 (或 user override 决议 hold). 沿用 V3 §6 broker layer xtquant 实现.

## §2 Decision

### 2.1 STAGED default 模式: (B) implement, default = OFF (短期), 5 prerequisite 后切换 default = STAGED (长期)

**短期** (Sprint 1~M, 5 prerequisite 未满足):
- L4 风控触发 → **default = OFF** (即立即 execute, 0 staged 流程)
- STAGED 代码 implement, 但 .env `STAGED_ENABLED=false` 默认关闭
- user 显式 override `.env` 才启用 (铁律 27/35 真账户保护)

**长期** (Sprint M+, 5 prerequisite 全满足):
- default = STAGED (T+30min 默认 execute / user override → cancel)
- 5 prerequisite (V3 §20.1 #5 + ADR-028 cite):
 1. LIVE_TRADING_DISABLED guard reconcile (红线)
 2. 跌停 fallback implement (4-29 case 无法成交)
 3. SOP-6 真生产下单 fail-safe sediment (5+ condition, 沿用 SOP-5 体例 LL-103 Part 2)
 4. paper-mode 5d validated (PR #210 sim-to-real gap finding)
 5. user 显式 .env governance + commit

### 2.2 user 离线 STAGED 30min 后行为: (c) hybrid 自适应窗口

仅在 STAGED default = STAGED 阶段生效 (§2.1 短期 OFF default 不触发本节).

**5 hard guardrails**:

a. **普通时段** (9:30-11:30 / 13:00-14:55): cancel 窗口固定 30 min
b. **集合竞价** (9:15-9:25): 自适应 = min(30 min, 剩余时间), 下限 2 min
c. **尾盘** (14:55-15:00): 自适应 = min(30 min, 距 14:55 剩余时间), 下限 2 min
d. **跨日保护**: cancel deadline > 14:55 强制提前到 14:55 final batch
e. **user 离线 DingTalk 未读** (V3 §13 #8 sediment): default execute, 不元告警

30 min 0 reply → execute (反向决策权).

### 2.3 L4 batched 平仓 batch interval (V3 §20.1 #8 配套)

- 普通时段: 5 min batch interval
- Critical windows (集合竞价 9:15-9:25 / 尾盘 14:55-15:00): 缩短到 1 min batch interval

(本 ADR cite, implementation 沉淀 V3 §7 broker batched 子模块.)

## §3 Consequences

### 3.1 依赖

- **Sprint 1**: STAGED 代码 implement + `STAGED_ENABLED=false` 默认 (§2.1 短期路径)
- **Sprint M-1**: 5 prerequisite verify (LIVE_TRADING_DISABLED + 跌停 fallback + SOP-6 + paper-mode 5d + .env governance)
- **Sprint M**: user 显式 `.env STAGED_ENABLED=true` + paper-mode 5d dry-run → live STAGED default
- **Sprint M+**: §2.2 5 hard guardrails 实施 + V3 §13 #8 DingTalk 未读 default execute 验证

### 3.2 反向决策权论据

- **user 反向决策权**: T+30min 0 reply → default execute (沿用 V3 §7.1, 反 N×N 同步漂移 textbook 案例 — user 离线时 system 0 阻塞)
- **critical windows 反向决策权窄化**: 集合竞价/尾盘 1-2 min 窗口, 给 user 反向决策权 (NOT 0 窗口), 但**默认 execute 优先级高于** 普通时段 (反 4-29 case 无法成交风险)
- **跨日保护**: 14:55 强制 final batch — 反 跨日 stale risk_event 累积

### 3.3 跌停 fallback 后果

- 跌停日 sell 延期 → 次日开盘 limit 单 (沿用 V3 §7.2)
- 用户 override hold 选项 — 持仓延续 (user 反向决策权)
- risk_event_log audit row 入库 (5 condition 0 资金风险, 沿用 LL-103 Part 2 SOP-5)

## §4 Anti-pattern verify (沿用 ADR-022)

- ✅ **不 fabricate**: STAGED 5 prerequisite + 5 hard guardrails sediment V3 §20.1 + Claude.ai+user 战略对话 (NOT 凭空 prompt 假设)
- ✅ **不削减 user 决议**: 沿用 user (B) sequence + (c) hybrid (NOT default = STAGED 0 prerequisite 抢跑)
- ✅ **5+1 层完整**: L4 V3 §1.2 Layer 4, NOT L0/L1/L2/L3/L5 任一层 silent overwrite
- ✅ **真账户保护**: STAGED default = OFF (短期) 沿用 LIVE_TRADING_DISABLED + EXECUTION_MODE=paper 双层

## §5 发现 sediment 候选 (P3 backlog)

- **V3 §18.1 row 3 ADR-023 drift bonus**: ADR-023 = yaml-ssot-vs-db-strategy-configs-deprecation (5-02 sprint factor task 5), V3 cite "ADR-023 → L1 实时化" drift. 候选 P3 backlog (5-02 audit Week 2 候选讨论时再决议, 沿用 LL-098 X10 + 铁律 28).
- **LL-104 sediment 候选**: "Claude.ai 写 prompt 时表格 cite 仅看 1 row 不够, 必 grep 全表 cross-verify" — 沿用 SOP-1/2/3 体例 (本 ADR # 下移 027 即 SOP-1 第 N+1 次实证 driver, 沿用 5-02 sprint close 5 SOP cluster).

## §6 实施 source

- V3 §20.1 #1 + #7 (Claude.ai+user 战略对话 sediment, 5-02)
- V3 §7.1 (STAGED 设计) + §7.2 (跌停 fallback) + §13 #8 (DingTalk 未读 default execute)
- ADR-022 (sprint period treadmill 反 anti-pattern, enforcement)
- LL-103 Part 2 SOP-5 (audit row backfill SQL 写 5 condition, 沿用 §3.3)
- 4-29 PT 暂停清仓事件 (红线 cash=¥993,520.66 / 0 持仓 / LIVE_TRADING_DISABLED=true)
