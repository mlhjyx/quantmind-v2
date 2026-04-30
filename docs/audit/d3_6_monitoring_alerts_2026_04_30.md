# D3.6 监控告警审计 — 2026-04-30

**Scope**: DingTalk 路径完整性 / Servy log 覆盖 / alert_dedup / dashboard / **D3-A Step 4 narrative 推翻 + D3-B F-D3B-6 修订**
**0 改动**: 纯 read-only grep + curl + redis-cli + log forensic

---

## 1. Q6.1 DingTalk 路径完整性 (沿用 D3-A Step 5 扩)

D3-A Step 5 仅识别 1 主路径 (`risk_wiring.py:85`), 本 D3-C 扩 grep 全 codebase.

```bash
grep -rE "DINGTALK_WEBHOOK_URL" backend/ scripts/ --include="*.py"
```

**实测 7+ 路径** (D3-A Step 5 漏 6+):

| # | 路径 | 用途 |
|---|---|---|
| 1 | `backend/app/security/live_trading_guard.py` | 真金 boundary 触发告警 (LIVE_TRADING_DISABLED 异常) |
| 2 | `backend/app/services/notification_service.py` (3 invocations) | 主路径 (general purpose: send_dingtalk + publish_alert) |
| 3 | `backend/app/services/risk_control_service.py` | Risk Framework v1 PMS / CB 告警 |
| 4 | `backend/app/services/risk_wiring.py` (D3-A Step 5 唯一识别) | Risk Framework v2 (PR #143-#148 9 PR) |
| 5 | `backend/app/services/signal_service.py` (3 invocations) | signal_phase 告警 (factor coverage / Beta / overlap / etc) |
| 其他 | `backend/qm_platform/observability/` (PostgresAlertRouter + DingTalkChannel) | MVP 4.1 batch 1 SDK (Wave 4 主路径) |

→ **F-D3C-12 (P1 cross-link D3-A Step 5)**: D3-A Step 5 F-D3A-NEW-6 仅识别 1 钉钉路径, 实测 7+, **D3-A Step 5 spike scope 严重不全**. 修法: D3 整合 PR 加 grep 全 DINGTALK_WEBHOOK_URL 完整 enum + 每路径 audit log 设计.

---

## 2. F-D3C-13 (P0 真金 cross-link D3-A Step 4 narrative 推翻) — emergency_close 4-29 实战清仓 18 股

**重大发现** (D3-A Step 4 修订 v1+v2 narrative 全错):

`logs/emergency_close_20260429_*.log` 5 文件, 实测 timeline:

| 时间 | 文件 | 事件 |
|---|---|---|
| 4-29 10:38:25 | emergency_close_20260429_103825.log (669 B) | `ImportError: cannot import name 'QMTBroker' from 'engines.broker_qmt'` (FAIL) |
| 4-29 10:39:36 | emergency_close_20260429_103936.log (644 B) | `ModuleNotFoundError: No module named 'xtquant'` (FAIL) |
| 4-29 10:40:22 | emergency_close_20260429_104022.log (317 B) | `query_positions: 18 持仓` (dry-run / connect verify) |
| 4-29 10:41:14 | emergency_close_20260429_104114.log (317 B) | `query_positions: 18 持仓` (dry-run #2) |
| **4-29 10:43:54** | **emergency_close_20260429_104354.log (13,992 B)** | **ACTUAL EXECUTION — 18 stocks sold via QMT API** |

实测 4-29 10:43:54 ~ 10:43:59 全部 18 股 sell 完成 (含 600028 / 600900 / 600938 / 600941 / 601088 / 000507 / 002282 / 002623 / 300750 等):

```
2026-04-29 10:43:54,921 [WARNING] [Confirm] --confirm-yes flag bypass interactive prompt (chat-driven 授权)
2026-04-29 10:43:54,921 [INFO] [QMT] 下单: 600028.SH sell 8600股 @0.000 type=market remark=emergency_close_s44
2026-04-29 10:43:55,153 [INFO] [QMT] 成交回报: order_id=1090551138, code=600028.SH, price=5.39, volume=8600
...
2026-04-29 10:43:59,800 [INFO] [QMT] 委托回报: order_id=1090551165, code=300750.SZ, status=56, traded=100/100
```

`--confirm-yes flag bypass interactive prompt (chat-driven 授权)` — **CC 4-29 上午 ~10:43 通过 chat 授权后用 emergency_close_all_positions.py 实际清仓 18 股**.

### 推翻 D3-A Step 4 修订 v1+v2 narrative (PR #159 + PR #163)

| 项 | 原 narrative (PR #159 + PR #163) | 实测 (本 D3-C) |
|---|---|---|
| 时间 | user 4-29 ~14:00 决策"全清仓" | user 4-29 上午 ~10:40 chat 授权 (memory frontmatter 也 stale) |
| 执行 | Claude PR #150 软处理为 link-pause + user 4-30 GUI 手工 sell 18 股 | **CC 4-29 10:43 已用 emergency_close_all_positions.py 实际清仓 18 股** |
| L1 NEW | "user 4-29 ~14:00 决策'全清仓暂停 PT'" (handoff 明确记录) | **时间错** — 实测 4-29 上午 ~10:40 chat 授权 (4-29 14:00 是 handoff 写入时间, 非 user 给指令时间) |
| L2 NEW (Claude 主责 prompt 软处理) | 4-29 20:39 Claude PR #150 主动软处理 link-pause | **不成立** — CC 上午已执行实际清仓, 下午 PR #150 link-pause 是补丁 (锁未来真金), 不是替代 |
| L3 NEW (CC 次责未挑战) | 收 PR #150 prompt 后没反问真意 | 仍部分成立 (PR #150 之前应反问"既然清仓已执行, 为何还要 link-pause?") |
| L4 NEW v2 (DB self-loop) | QMTClient fallback 直读 DB self-loop | **仍成立** (4-29 emergency_close 后, DB 4-28 stale snapshot 仍存, 4-30 fallback 路径仍读 stale, F-D3B-7 实测推翻 stale Redis cache 推论) |
| L5 NEW (流程债 T0-15/16/17) | DB 4-30 silent drift | **仍成立** (但 root cause 应是 4-29 emergency_close 后没刷新 DB snapshot, 不是 4-30 GUI sell) |

### Tier 0 债 (16 → 17, +1)

新增:
- **T0-19 (P1)**: emergency_close_all_positions.py 实战清仓后**没**自动刷新 DB position_snapshot / cb_state / performance_series. 修法: emergency_close 脚本加 post-execution DB sync hook (清空 live position_snapshot 当天 + 写 risk_event_log 行) + 触发 reconciliation. 真金事故 audit log 完整性必备.

→ **F-D3C-13 (P0 真金 cross-link)**: D3-A Step 4 修订 v1+v2 整体 narrative 错, 真因 4-29 上午 emergency_close 已执行 18 股清仓, 不是 4-30 GUI sell. 修法: D3 整合 PR 修订 SHUTDOWN_NOTICE + memory + L4 修订 v3.

---

## 3. F-D3C-14 (P1 cross-link D3-B F-D3B-6) — Streams 全 dead 推翻

D3-B Q5.1 实测称 7/8 streams TYPE=none + TTL=-2 dead. 本 D3-C 重新实测 (~30min 后):

```bash
redis-cli KEYS "qm:*"
# qm:ai:monitoring
# qm:execution:order_filled
# qm:health:check_result
# qm:order:routed
# qm:qmt:status
# qm:quality:alert
# qm:signal:generated

redis-cli TYPE qm:health:check_result
# stream  ← 非 D3-B 称的 none
redis-cli XLEN qm:health:check_result
# 126     ← 非 dead

curl -s http://localhost:8000/api/system/streams
# {"streams":[
#   {"stream":"qm:execution:order_failed","length":0,...},
#   {"stream":"qm:factor:computed","length":0,...},
#   {"stream":"qm:health:check_result","length":126,"last_published_at":"2026-04-29T17:24:45.751637+00:00"},
#   {"stream":"qm:schedule:task_completed","length":0,...},
#   {"stream":"qm:qmt:status","length":5038,"last_published_at":"2026-04-29T06:11:17.584531+00:00"},
#   {"stream":"qm:qmt:request","length":0,...},
#   {"stream":"qm:pms:position_update","length":0,...},
#   {"stream":"qm:pms:protection_triggered","length":0,...}]}
```

**真实状况**:
- redis-cli `KEYS "qm:*"` 返回 7 entries — 与 D3-B 一致
- TYPE qm:health:check_result = **stream** (非 D3-B 称的 none)
- XLEN qm:health:check_result = **126** (非 dead)
- /api/system/streams 显示 **8 streams** 含 length=126 (qm:health) + length=5038 (qm:qmt:status)

D3-B Q5.1 finding F-D3B-6 "1/8 alive (qm:order:routed only)" **可能错**:
- 推测 D3-B 时点 redis-cli TYPE 命令使用错 / 或读了不同 DB index
- 推测 redis-cli 选择不同的 redis instance (本 audit 默认 6379, D3-B 可能其他)
- 或 D3-B 30min 前 vs 现在的真状态变化 (新 publisher 写入)

→ **F-D3C-14 (P1 cross-link D3-B F-D3B-6)**: D3-B F-D3B-6 stream "7/8 dead" 可能错判. 修法: 重新 audit 确定 D3-B Q5.1 redis-cli 使用方式 + 真状态 alive 比率.

**注**: F-D3C-14 仅推翻 D3-B 部分 finding, **不推翻** D3-A Step 4 修订 v2 L4 NEW v2 (portfolio:current = 0 keys 仍正确, L4 修订仍成立).

---

## 4. Q6.2 alert_dedup / platform_metrics / strategy_evaluations 仍 missing

```bash
SELECT EXISTS (FROM information_schema.tables WHERE table_name='alert_dedup'/...);
# alert_dedup: False
# platform_metrics: False
# strategy_evaluations: False
```

→ **F-D3C-15 (P0 cross-link D3-A F-D3A-1, 仍未修)**: 3 missing migrations 自 D3-A Step 1 (~6h 前) 起仍 missing. PT 重启 gate prerequisite. 阻塞 Risk Framework v2 PostgresAlertRouter cross-process dedup + MetricExporter + DBStrategyRegistry.

---

## 5. Q6.3 dashboard / health endpoint

```bash
curl -s http://localhost:8000/health
# {"status":"ok","execution_mode":"paper"}
```

✅ 健康端点活. `execution_mode=paper` (正确, LIVE_TRADING_DISABLED=true).

→ **F-D3C-16 (INFO)**: 健康端点 OK, 但 `/api/system/streams` 显示的 streams (8 个) 与 redis-cli (7 个) 不完全一致 — F-D3C-14 cross-link.

---

## 6. Q6.4 钉钉 token 暴露评估

实测:
```bash
grep -nE "\.env" .gitignore
# 12: .env
# 13: .env.*
# 14: .env.local
# 15: .env.*.local
git ls-files backend/.env backend/.env.bak.20260420-session20-cutover
# (empty - 不在 git tracked)
```

→ **F-D3C-17 (P3)**: DingTalk webhook token + access_token (`94f75fcb...`) 在 `backend/.env` + `backend/.env.bak.20260420-session20-cutover` 明文存储. **铁律 35 局部合规** (.env 不在 git tracked, 不在 git history). **本地 FS 暴露**仍存 (其他 user / malware / 其他进程读 .env). 修法: 加 secret manager (Wave 5+) 或至少 .env 文件权限 600.

---

## 7. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3C-12 | D3-A Step 5 仅识别 1 钉钉路径, 实测 7+, scope 严重不全 | P1 cross-link |
| **F-D3C-13** | **D3-A Step 4 修订 v1+v2 narrative 错, 真因 4-29 上午 emergency_close 实战清仓 18 股** | **P0 真金 cross-link** |
| F-D3C-14 | D3-B F-D3B-6 stream "1/8 alive" 可能错判 (本 D3-C 实测 stream + length 都活) | P1 cross-link |
| F-D3C-15 | F-D3A-1 仍 missing (alert_dedup / platform_metrics / strategy_evaluations) | P0 cross-link |
| F-D3C-16 | /api/system/streams 与 redis-cli 不一致 (8 vs 7), F-D3C-14 cross-link | INFO |
| F-D3C-17 | DingTalk token 在 .env 明文 (gitignored 但本地 FS 暴露) | P3 |

---

## 8. 处置建议

- **F-D3C-13 (P0)**: D3 整合 PR 修订 SHUTDOWN_NOTICE + memory + L4 修订 v3 + 加 T0-19
- **F-D3C-14 (P1)**: 重新 audit 确定 D3-B 错判源 + 真 alive 比率
- **F-D3C-12 (P1)**: D3 整合 PR 加 7 钉钉路径 enum + audit log 设计
- **F-D3C-15 (P0)**: 与 T0-15/16/17/18/19 一起 batch 2 P0 修
- INFO / P3 留 Wave 5+

---

## 9. 关联

- D3-A Step 4 修订 v1 PR #159 + 修订 v2 PR #163 (本 finding F-D3C-13 推翻 narrative)
- D3-A Step 5 spike PR #160 (F-D3A-NEW-6 仅 1 钉钉路径)
- D3-B PR #162 F-D3B-6 (stream 1/8 alive, 本 finding F-D3C-14 推翻)
- D3-B PR #162 F-D3B-7 (portfolio:current 0 keys, **仍成立** 不被推翻)
- T0-15/16/17/18 + T0-19 (新)
- LL-091/092 (D3-B 跨文档同步 PR #164)
