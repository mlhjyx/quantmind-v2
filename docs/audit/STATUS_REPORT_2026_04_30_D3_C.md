# STATUS_REPORT — D3-C 全方位审计低维度 4/14 (2026-04-30)

**Date**: 2026-04-30
**Branch**: chore/d3c-audit-low-priority
**Base**: main @ 2914878 (PR #164 D3-B 跨文档同步 merged)
**Scope**: D3.2 测试覆盖度 + D3.4 Servy 服务依赖图 + D3.6 监控告警 + D3.8 性能/资源
**改动**: 5 文档 (4 finding + 本 STATUS_REPORT) — 单 PR `chore/d3c-audit-low-priority`, 跳 reviewer

---

## §0 环境前置检查

| 项 | 实测 | 结论 |
|---|---|---|
| E1 git status | main @ `2914878` (PR #164 merged), 8 D2 untracked | ✅ |
| E2 PG stuck | 0 active non-idle | ✅ |
| E3 Servy 4 服务 | FastAPI / Celery / CeleryBeat / QMTData ALL Running | ✅ |
| E4 .venv Python | 3.11.9 | ✅ |
| E5 真金 fail-secure | LIVE_TRADING_DISABLED default True (config.py:44) + EXECUTION_MODE=paper | ✅ |
| E6 真账户 ground truth | 沿用 D3-A Step 4 (4-30 14:54: 0 持仓 + cash ¥993,520) — 同日无 trading 仍 hold (xtquant import 路径 issue 跳重测) | ⚠️ 沿用 |
| E7 pytest collect | backend/tests/ 4027 tests cleanly. **项目根 pytest 段错误** — F-D3C-1 finding (testpaths 配置漂移) | ⚠️ Finding |
| E8 Beat LocalTime | celery-beat-stderr.log last 4-30 16:52 (本 audit 时点, 活), restart 自 4-30 15:35:51 起 stderr 0 spam | ✅ |

§0 整体: 5 ✅ + 2 ⚠️ + 1 finding (F-D3C-1).

---

## 1. 维度 finding 摘要

### D3.2 测试覆盖度 ([d3_2_test_coverage_2026_04_30.md](d3_2_test_coverage_2026_04_30.md))

- **F-D3C-1 (P2)**: pytest config drift `testpaths=["tests"]` vs 真路径 `backend/tests/`, 直接跑 pytest 段错误
- F-D3C-2 (INFO): 7 xfail/skip 待标注 by design vs 待修复
- F-D3C-3 (P3): MVP 4.1 batch 1-3 + pt_audit 缺 smoke
- **F-D3C-4 (P1)**: emergency_close_all_positions.py 是真金 P0 入口 (4-29 实战清仓 18 股), 0 smoke 守门
- **F-D3C-5 (P1 cross-link D3-A F-D3A-1)**: contract test mocks schema vs 真生产 schema (3 missing migrations) 不一致
- F-D3C-6 (INFO): conftest.py ~430 行 8 主 fixture, 24 fail baseline 与 fixture 漂移相关

### D3.4 Servy 服务依赖图 ([d3_4_servy_dependency_2026_04_30.md](d3_4_servy_dependency_2026_04_30.md))

- **F-D3C-7 (P1)**: Celery + QMTData 缺 PostgreSQL16 依赖声明, 开机/PG-restart race 潜在 silent fail
- F-D3C-8 (P2): 开机启动顺序 race condition, F-D3C-7 修后自愈
- **F-D3C-9 (P1 cross-link T0-16)**: QMTData Servy heartbeat 仅检测进程 alive, 不检测连接性, 4-04 起 26 天 silent skip 根因之一
- F-D3C-10 (INFO): Beat restart 0 副作用 (沿用 PR #161)
- F-D3C-11 (INFO): Servy 配置健康整体 ✅

### D3.6 监控告警 ([d3_6_monitoring_alerts_2026_04_30.md](d3_6_monitoring_alerts_2026_04_30.md))

- **F-D3C-12 (P1 cross-link D3-A Step 5)**: 实测 7+ 钉钉路径 (D3-A Step 5 仅识别 1)
- 🔴 **F-D3C-13 (P0 真金 cross-link)**: D3-A Step 4 修订 v1+v2 narrative 错, 真因 4-29 上午 emergency_close 实战清仓 18 股
- F-D3C-14 (P1 cross-link D3-B F-D3B-6): D3-B "stream 1/8 alive" 可能错判 (本 D3-C 实测 stream 活 + length=126/5038)
- **F-D3C-15 (P0 cross-link D3-A F-D3A-1, 仍未修)**: 3 missing migrations 仍 missing
- F-D3C-16 (INFO): /api/system/streams (8) 与 redis-cli (7) 不一致
- F-D3C-17 (P3): DingTalk token 在 .env 明文 (gitignored, 但本地 FS 暴露)

### D3.8 性能 / 资源 ([d3_8_performance_resource_2026_04_30.md](d3_8_performance_resource_2026_04_30.md))

- F-D3C-18 (INFO): DB 224 GB 健康
- F-D3C-19 (P2): Redis 0 maxmemory 限制
- F-D3C-20 (INFO): Redis 内存利用率 0.01% 极低
- F-D3C-21 (INFO): RAM 53.7% 健康, 铁律 9 max 2 并发安全
- F-D3C-22 (INFO): D drive 702 GB free 健康
- F-D3C-23 (INFO): 关键路径性能基线沿用 memory baseline
- F-D3C-24 (P3): app.log rotation 26 天未触发
- 🔴 **F-D3C-25 (P0 cross-link)**: emergency_close 4-29 logs 真金 audit 唯一证据, 没自动入 risk_event_log + 没 backup
- F-D3C-26 (P3 cross-link D3-B F-D3B-8): celery-task-meta 2961 keys 性能影响 ~0

---

## 2. 🔴 重大 cross-link 修订

### F-D3C-13 (P0 真金) — D3-A Step 4 narrative 整体推翻

**背景**: D3-A Step 4 修订 v1 (PR #159) + 修订 v2 (PR #163) narrative:
- L1 NEW: user 4-29 ~14:00 决策"全清仓暂停 PT"
- L2 NEW: Claude PR #150 主动软处理为 link-pause
- L4 NEW v2: QMTClient fallback 直读 DB self-loop
- 假设 user 4-30 GUI 手工 sell 18 股

**实测推翻** (`logs/emergency_close_20260429_*.log` 5 文件):

| 时间 | 事件 |
|---|---|
| 4-29 10:38:25 | emergency_close ImportError attempt #1 (FAIL) |
| 4-29 10:39:36 | ModuleNotFoundError xtquant attempt #2 (FAIL) |
| 4-29 10:40:22 | query_positions: 18 持仓 (dry-run) |
| 4-29 10:41:14 | query_positions: 18 持仓 (dry-run #2) |
| **4-29 10:43:54** | **18 stocks sold via QMT API** (chat-driven 授权 --confirm-yes flag) |

→ **CC 4-29 上午 ~10:43 通过 chat 授权后用 emergency_close_all_positions.py 实际清仓 18 股**, 不是 4-30 GUI 手工 sell.

**新 5 层 root cause v3** (取代 PR #159 v1 + PR #163 v2):

| 层 | 描述 | 责任 |
|---|---|---|
| **L1 NEW v3** | 4-29 上午 ~10:40 user chat 授权 emergency_close_all_positions.py 实际清仓 | User instruction (ground truth) |
| **L2 NEW v3** | 4-29 10:43:54 CC 用 emergency_close 脚本实际 sell 18 股 (chat-driven 授权 --confirm-yes flag) | CC 主体执行 (合规) |
| **L3 NEW v3** | 4-29 14:00 handoff 入 memory 时 frontmatter 时间漂移 (写"~14:00") | 流程债 (handoff 时点 ≠ 真实指令时点) |
| **L4 NEW v3** | 4-29 20:39 PR #150 link-pause 是补丁 (锁未来真金), 不是替代清仓 | Claude 设计层正确 (但 D3-A spike narrative 误读为"软处理替代清仓") |
| **L5 NEW v3** | DB 4-30 silent drift 真因: emergency_close 后**没**自动刷新 DB position_snapshot / cb_state / performance_series → DB 4-28 stale snapshot 仍存 → QMTClient fallback 直读 stale (T0-19 新) | 流程债 (T0-15/16/17/18/19) |

**Tier 0 债 (16 → 17, +1)**:
- **T0-19 (P1)**: emergency_close_all_positions.py 实战清仓后没自动刷新 DB position_snapshot / cb_state / performance_series. 修法: 加 post-execution DB sync hook + 触发 reconciliation + 写 risk_event_log 真金事故 audit.

**LL 累计 26 → 27 (+1)**:

> **LL-093 候选**: D3-A Step 4 spike forensic 漏查 logs/emergency_close_*.log 是因为 D3-A Step 4 仅查 XtMiniQmt query log (`E:/国金QMT交易端模拟/userdata_mini/log/`), 没查项目本地 `logs/emergency_close_*.log`. 复用规则 (forensic 类 spike 必查): (a) 项目 logs/ 全文件 (含 emergency_close_* / pt_audit_* / etc); (b) 项目历史 commit log (含 emergency_close 脚本 chat-driven 调用证据); (c) DB risk_event_log + scheduler_task_log; (d) Redis Streams XRANGE; (e) QMT 客户端 query / order / trade log 全 3 类. 本 LL 第 27 次同质 LL.

### F-D3C-14 (P1) — D3-B F-D3B-6 stream "1/8 alive" 可能错判

**实测推翻** (本 D3-C ~17:00, 距 D3-B audit ~30min 后):

```bash
redis-cli KEYS "qm:*"  # 7 hits (与 D3-B 一致)
redis-cli TYPE qm:health:check_result  # stream (非 D3-B 称的 none)
redis-cli XLEN qm:health:check_result  # 126 (非 dead)
curl -s http://localhost:8000/api/system/streams
# {"streams":[..."qm:health:check_result","length":126,...,"qm:qmt:status","length":5038,...]}
```

**推测 D3-B Q5.1 错判源**: TYPE 命令使用错 / 不同 redis DB index / 30min 内新 publisher 写入. 本 D3-C 不再 STOP, 仅 cross-link 标注. 真实 alive 比率待 D3-D / 批 2 重新 audit.

**注**: F-D3C-14 仅推翻 D3-B 部分 finding, **不推翻** D3-A Step 4 修订 v2 L4 NEW v2 (portfolio:current = 0 keys 仍正确, F-D3B-7 仍成立).

---

## 3. Tier 0 债更新 (16 → 17)

| 编号 | 描述 | 严重度 | 来源 |
|---|---|---|---|
| T0-15 | LL-081 guard 不 cover QMT 断连 / fallback 触发 | P0 | D3-A Step 4 + 修订 v2 范围扩 |
| T0-16 | qmt_data_service 26 天 silent skip (~37,440 次 silent WARNING) | P0 | D3-A Step 4 |
| T0-17 | Claude prompt 软处理 user 真金指令 | P0 | D3-A Step 4 修订 v1 |
| T0-18 | Beat schedule 注释式 link-pause 失效 (PR #150 73 次 error) | P0 | D3-A Step 5 |
| **T0-19 (新)** | **emergency_close_all_positions.py 实战清仓后没自动刷新 DB / cb_state / performance_series + 没自动入 risk_event_log audit** | **P1** | **D3-C F-D3C-13/25** |

---

## 4. LL 累计 (26 → 27)

| 第 | 来源 | 描述 |
|---|---|---|
| 27 (LL-093 候选) | D3-A Step 4 spike forensic 漏查 logs/emergency_close_*.log | 复用规则: forensic 类 spike 必查 (a) 项目 logs/ 全 (b) git commit log (c) DB risk_event_log/scheduler_task_log (d) Redis Streams (e) QMT 全 3 类 log |

---

## 5. 处置建议

### 立即并行启动 (3 P0/P1)

1. **批 2 P0 修启动 (T0-15/16/17/18/19 + F-D3A-1)**:
   - F-D3A-1 apply 3 missing migrations (~30min)
   - T0-16 qmt_data_service fail-loud (~1h)
   - T0-15 LL-081 v2 candidate 铁律 X9 设计 + ADR-021 (~2h)
   - T0-19 emergency_close DB sync hook + audit log (~1h)
   - T0-18 Beat schedule comment auto-restart guard (~30min)
2. **F-D3C-13 D3-A Step 4 修订 v3 单 PR**:
   - SHUTDOWN_NOTICE.md 修订 4-29 emergency_close 时间线 + 5 层 root cause v3
   - memory frontmatter 修订 (Session 45 末 narrative 改 4-29 上午 chat 授权)
   - LESSONS_LEARNED.md 加 LL-093 (~30min)
3. **F-D3C-7 单 PR Servy import**: Celery + QMTData 加 PostgreSQL16 依赖声明 (~5min)

### user 决策点

- 是否立即启批 2 P0 修 (5 P0 PR 串行 ~5h, 阻塞 PT 重启 gate)?
- F-D3C-13 D3-A Step 4 修订 v3 是否独立 PR 还是 D3 整合 PR 一起?
- F-D3C-14 D3-B F-D3B-6 是否值得重新 audit 确认错判源?

### 后续 (Wave 5+)

- F-D3C-19 Redis maxmemory 限制
- F-D3C-17 secret manager 替换 .env 明文
- F-D3C-26 celery-task-meta TTL 配置审计

---

## 6. 硬门验证

| 硬门 | 结果 | 证据 |
|---|---|---|
| 改动 scope | ✅ 5 文档 (4 finding + 本 STATUS_REPORT) | git status |
| ruff | ✅ N/A | 0 .py 改动 |
| pytest | ✅ N/A | 0 .py 改动 |
| pre-push smoke | (push 时验) | bash hook 沿用 PR #163/#164 |
| 0 业务代码改 | ✅ | git diff main 仅 5 docs |
| 0 .env 改 | ✅ | grep diff main backend/.env = 0 |
| 0 服务重启 | ✅ | Servy 4 服务全程 Running |
| 0 DML | ✅ | 全程 SELECT only |
| 0 触 LLM SDK | ✅ | 0 调用 |
| 0 触 QMT write API | ✅ | 0 调 admin endpoint / 0 重连尝试 / 0 sell |
| 0 修复 finding | ✅ | 本 PR 仅诊断, 修留后续 PR |

---

## 7. 关联

- D3-A 全闭环 (5 P0 维度审 + 4 spike Step 1-5 + 修订 v1+v2)
- D3-B PR #162 (5 中维度 24 finding, F-D3B-6 被 F-D3C-14 推翻)
- D3-A Step 4 修订 v2 PR #163 (L4 NEW v2 仍成立, L1-L3 narrative 被 F-D3C-13 推翻)
- D3-B 跨文档同步 PR #164 (LL-091/092 入册, narrative 待 F-D3C-13 修订 v3)
- SHUTDOWN_NOTICE_2026_04_30 (待 F-D3C-13 修订 4-29 timeline)

---

## 8. 用户接触

实际 0 (本 D3-C 是 D3-A/B 后续诊断 audit, 自驱动).

未来接触预期:
- user 决议批 2 P0 修启动 / D3-A Step 4 修订 v3 / D3-D 重新 audit (~3 项决策)

---

## 9. 维度覆盖统计

| 阶段 | 维度数 | 累计 |
|---|---:|---|
| D3-A | 5/14 | 5/14 (36%) |
| D3-B | 5/14 | 10/14 (71%) |
| **D3-C** | **4/14** | **14/14 (100%)** |

✅ **D3 全方位审计 14/14 维度全闭环**.
