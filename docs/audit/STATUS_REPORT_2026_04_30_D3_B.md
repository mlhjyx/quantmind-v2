# STATUS_REPORT — D3-B 全方位审计中维度 (5/14, 纯诊断 0 改动)

**Date**: 2026-04-30 15:50 ~ 16:30
**Branch**: chore/d3b-audit-docs
**Base**: main @ 5548498 (PR #161 D3-A Step 5 落地 merged)
**Scope**: 5 中维度 (D3.3 文档腐烂 / D3.5 Redis / D3.7 调度 / D3.10 异常处理 / D3.13 战略进度)
**ETA**: 实跑 ~40 min (vs 预估 5h, **大幅提前因 D3-A 已覆盖大量基础数据**)
**真金风险**: 0 (0 业务代码改 / 0 .env / 0 服务重启 / 0 DML / 0 真发钉钉)
**改动 scope**: 6 文档 (5 维度 + 本 STATUS_REPORT)

---

## §0 环境检查 8/8 ✅

| 项 | 实测 |
|---|---|
| E1 git | main @ `5548498`, 8 D2 untracked (expected) |
| E2 PG | 0 stuck (only my own psql) |
| E3 Servy | 4 ALL Running |
| E4 .venv | Python 3.11.9 |
| E5 真金 | LIVE_TRADING_DISABLED=True / OBSERVABILITY_USE_PLATFORM_SDK=True |
| E6 Beat | LocalTime 4-30 15:35:51 (PR #161 落地仍生效, 0 漂移) |
| E7 pytest | **4027 tests collected** (D3-A 一致) |
| E8 zombie | 0 真 zombie (9 python 全 Servy-managed) |

---

## 24 题逐答 (汇总)

### D3.3 文档腐烂 ✅ (Q3.1-Q3.5)

- Q3.1 CLAUDE.md 7 处严重数字漂移 (L29 / L188-191 / L628 / L721 / L841)
- Q3.2 memory frontmatter Session 45 D3-A 全 0 反映 + main hash stale
- Q3.3 9 DEV_*.md 集体 stale (4-10/16 后未更新)
- Q3.4 SYSTEM_RUNBOOK 老 stale 巧合对齐当前 0 持仓
- Q3.5 ADR-014 / ADR-021 待写但 QPB 已 reference

**5 finding F-D3B-1 ~ F-D3B-5**

### D3.5 Redis 健康 ✅ (Q5.1-Q5.4)

- Q5.1 DBSIZE=2971 / 99.7% celery-task-meta-* / **8 streams 仅 1 alive** (qm:order:routed)
- Q5.2 portfolio:current cache **0 keys** (D3-A Step 4 root cause L4 修订)
- Q5.3 celery-task-meta-* 2961 累积
- Q5.4 CLAUDE.md L249 "QMT Data Service 60s 同步" 与实测 26 天 0 SET 漂移

**4 finding F-D3B-6 ~ F-D3B-9 (含 P0 cross-link F-D3B-7)**

### D3.7 调度健康 ✅ (Q7.1-Q7.5)

- Q7.1 16 schtask: 5 Disabled (PT 暂停包络) / 11 Ready / **5/11 Ready LastResult ≠ 0** (45% fail)
- Q7.2 Beat 4 active, 4-30 15:35:51 restart 后健康度待 18:00+ 观察
- Q7.3 Beat schedule 注释 36h+ T1 sprint 正常
- Q7.4 schtask vs Beat 0 重复, 7 ops/audit 5 fail
- Q7.5 scheduler_task_log **intraday_risk_check error 73 次** (PR #150 link-pause 失效真证)

**5 finding F-D3B-10 ~ F-D3B-14 (含 P0 cross-link F-D3B-14)**

### D3.10 异常处理 ✅ (Q10.1-Q10.5)

- Q10.1 静态 grep 0 真 `except: pass` 违反, 真违反是 logger.warning + 累积无 escalation 模式
- Q10.2 6 schtask script 已硬化 (LL-068), pt_audit.py 缺 2 项 (D3-A Step 3)
- Q10.3 exception 层级抽样合理
- Q10.4 跨服务 silent WARNING 累积 ≥ 100 次无 escalation = 真 fail-loud 违反 (T0-16 / F-D3B-14)
- Q10.5 真金 fail-secure default 抽样合规

**5 finding F-D3B-15 ~ F-D3B-19 (含 P1 F-D3B-18)**

### D3.13 战略进度 ✅ (Q13.1-Q13.5)

- Q13.1 QPB v1.16 frontmatter "Wave 3 ✅ 5/5" 实测验证
- Q13.2 Wave 1+2+3 ✅ / Wave 4 进行中 (~25%) / Wave 5+ 0%
- Q13.3 17 MVP: 16 ✅ + 1 🟡 (4.1) = 94% 完成度
- Q13.4 V4 路线图 Phase 3 被 Wave 3 替代 (CLAUDE.md L15 未反映)
- Q13.5 战略层 PR ✅ 100% × 生产 ✅ 75% = 真健康度 ~75%

**5 finding F-D3B-20 ~ F-D3B-24 (含 P1 F-D3B-20+24)**

---

## 关键 Findings 汇总 — 24 项 (P0 cross-link / P1 / P2 / P3 / INFO 分级)

### 🔴 P0 cross-link (2 项, 关联 D3-A 修订)

| ID | 描述 | 关联 |
|---|---|---|
| **F-D3B-7** | portfolio:current cache **0 keys** — D3-A Step 4 root cause L4 应修订 ("DB 4-28 stale 不是 stale Redis cache, 是 QMTClient fallback 直读 stale DB position_snapshot") | D3-A Step 4 PR #158/#159 |
| **F-D3B-14** | scheduler_task_log intraday_risk_check error 73 次 = D3-A Step 5 F-D3A-NEW-6 PR #150 link-pause 失效**真生产证据** | D3-A Step 5 PR #160 |

### 🟡 P1 (5 项)

| ID | 描述 |
|---|---|
| F-D3B-1 | CLAUDE.md 7 处严重数字漂移 |
| F-D3B-2 | memory frontmatter Session 45 D3-A 全 0 反映 |
| F-D3B-9 | CLAUDE.md L249 "QMT Data Service 60s 同步" 26 天 0 SET 漂移 (T0-16 同源) |
| F-D3B-10 | 5/11 Ready schtask LastResult ≠ 0 (D3-A Step 3 仅识 PTAudit 1 例, 33% scope 漂移) |
| F-D3B-18 | 跨服务 silent WARNING 累积 ≥ 100 次无 escalation = 真 fail-loud 违反 (静态 grep 无法识) |
| F-D3B-20 | Wave 3 完结 ≠ 健康 (T0-15/16/17/18 + F-D3A-1 = 5 P0 残留) |
| F-D3B-24 | 战略层 PR ✅ 100% × 生产 ✅ 75% (5 P0 阻塞 PT 重启) |

### 🟢 P2 (4 项)

| ID | 描述 |
|---|---|
| F-D3B-3 | DEV_*.md 9 文档集体 stale |
| F-D3B-4 | SYSTEM_RUNBOOK 老 stale 巧合对齐当前 0 持仓 |
| F-D3B-5 | ADR-014 / ADR-021 待写 |
| F-D3B-21 | MVP 17/17 完成度 ≠ 真健康度 |

### ⚪ P3 / INFO (10 项)

| ID | 描述 |
|---|---|
| F-D3B-6 | 8 streams 仅 1 alive (qm:order:routed) |
| F-D3B-8 | celery-task-meta backlog 2961 keys |
| F-D3B-11 | Beat 4 active 待 18:00+ 观察 |
| F-D3B-12 | Beat schedule 注释 36h+ T1 sprint 正常 |
| F-D3B-13 | PT 主链 schtask 仅 2 active 真路径 |
| F-D3B-15 | 0 真 silent except: pass 违反 |
| F-D3B-16 | 6 schtask script 已硬化 + pt_audit.py 缺 2 项 (Step 3) |
| F-D3B-17 | exception 层级抽样合理 |
| F-D3B-19 | 真金 fail-secure default 抽样合规 |
| F-D3B-22 | DEV_AI_EVOLUTION V2.1 0% 实现 22 天无进展 |
| F-D3B-23 | V4 路线图与 QPB Wave 双轨, CLAUDE.md L15 未反映 |

---

## Tier 0 债更新 (16 → 16, +0 但 1 项修订)

D3-B 不新增 Tier 0 债 (5 维度 finding 多是 P1/P2 doc/observation, 非 P0 真金风险). **修订 D3-A Step 4 root cause L4**:
- 原: "DB 4-28 19 股 = stale Redis cache + DailySignal Stage 4 reenable run 4-28 16:30 写入"
- 新 (F-D3B-7): "DB 4-28 19 股 = QMTClient fallback 直读 stale position_snapshot (Redis cache 已 expired 不存在)"

留 D3-C 整合 PR 回填 D3-A Step 4 spike + Step 4 修订 文档.

---

## LL "假设必实测纠错" 累计 24 → **26** (+2)

| 第 | 来源 | 假设 | 实测 |
|---|---|---|---|
| 25 (LL-093 候选) | D3-A Step 4 推断 "Redis cache 26 天 stale" | 推断 stale Redis cache 是 DB 4-28 19 股的源 | 实测 portfolio:current 0 keys (cache TTL 已 expire), DB 4-28 stale 是 QMTClient fallback 直读 DB 路径 — 推断错 (未实测 Redis 直接, 走"silent skip 26 天"+"DB 4-28 stale snapshot"双前提推) |
| 26 (LL-094 候选) | D3-A Step 5 + Step 1 "钉钉 8 streams 是文档 10 streams 的子集" | 文档 10 streams 与实测对齐 | 实测仅 7 qm:* + 1 qmt:*, 其中 7/8 expired (TTL=-2). 真 alive 仅 1 (qm:order:routed). 与文档 "10 streams" 严重漂移 |

**累计 26 次**. 复用规则统一升级: 任何"推断"必明示"基于 N 项前提推论, 推论=不实测, 应留 P3-FOLLOWUP 标 + 真实测验证".

---

## D3-C 维度 4 个 scope 调整建议

D3-A 5 + D3-B 5 = 10/14 已覆盖. D3-C 剩 4 维:
- D3.2 测试覆盖度
- D3.4 Servy 依赖图
- D3.6 监控告警 (大部分已 D3-A Step 1+5 / D3-B 5+7 覆盖, 留 dashboard 维度)
- D3.8 性能 / 资源使用

基于 D3-B finding **建议 D3-C 优先级**:
1. **D3.6 监控告警**: F-D3B-18 P1 跨服务 silent WARNING 累积 escalation = LL-081 v2 候选铁律 X9, D3-C 详查
2. **D3.4 Servy 依赖图**: 4 服务依赖关系 + restart 冲击 (沿用 PR #161 Beat restart 0 副作用 case study)
3. **D3.2 测试覆盖度**: 4027 tests 真覆盖率 (line / branch) + smoke 关键路径
4. **D3.8 性能 / 资源**: PG 263GB / Redis 2971 keys / 32GB RAM 利用率

---

## 硬门验证

| 硬门 | 结果 |
|---|---|
| 改动 scope | ✅ 6 文档 (5 finding + STATUS_REPORT) |
| ruff | ✅ N/A |
| pytest | ✅ N/A |
| pre-push smoke | (push 时验) |
| 0 业务代码 | ✅ |
| 0 .env | ✅ |
| 0 服务重启 | ✅ |
| 0 DML | ✅ (read-only SQL + read-only redis-cli + read-only schtasks) |
| 0 真发钉钉 | ✅ |
| 0 LLM SDK | ✅ |

---

## 下一步建议

### 立即 (推荐)

1. **D3-C 启动** (~3-4h, 留下个 session): D3.2/3.4/3.6/3.8 4 个低维度
2. **D3-A Step 4 spike L4 修订** (~10min, 沿用 F-D3B-7): 单 PR 加 "L4 修订" 段
3. **D3-C 整合 PR** (~30min, 沿用 D3-B 推荐): CLAUDE.md / memory frontmatter / DEV_*.md 跨文档统一更新

### 后续 (D3-C 后 / 批 2)

- T0-15/16/17/18 + F-D3A-1 5 P0 修 (PT 重启 gate prerequisite)
- ADR-021 候选铁律 X8 (Claude prompt 软处理 user 真金指令) + ADR 候选 X9 (silent WARNING 累积 escalation)
- DEV_*.md 9 文档简化 (沿用 LL-068 V2.1 简化模板)

---

## 关联

- D3-A 全方位审计 (PR #155 / #156 / #157 / #158 / #159 / #160 / #161)
- 本 D3-B PR `chore/d3b-audit-docs`
- F-D3B-7 cross-link D3-A Step 4 root cause L4 修订 (沿用 PR #159 修订模板)
- F-D3B-14 cross-link D3-A Step 5 F-D3A-NEW-6 真生产 73 次 error 证据
- LL-093 / LL-094 候选 (累计 26 次, 待入册)

---

## 用户接触

实际 0 (本 D3-B 沿用 D3-A 系列纯诊断 LOW 模式).

下一步 user 接触: 决议 D3-C 启动顺序 / 批 2 P0 修优先级 (~1 次).
