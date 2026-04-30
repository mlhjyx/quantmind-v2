# STATUS_REPORT — D2.1 API Auth Gate + Broker 实例链路实测

> **Sprint**: D2.1 (T1 Sprint, 2026-04-29 末)
> **Branch**: main @ `bc8bad4` (PR #151 批 1.5 merged) — 0 改动 / 0 commit / 0 PR
> **Trigger**: D2 报告 ⚪ 待评估项 (API endpoint sell/buy auth gate + broker 实例链路) 必须 close
> **关联铁律**: 25 / 33 / 34 / 35 / 36
> **关联文档**: [api_auth_gate_2026_04_29.md](api_auth_gate_2026_04_29.md) (主产物 24KB) / [live_mode_activation_scan_2026_04_29.md](live_mode_activation_scan_2026_04_29.md) / [STATUS_REPORT_2026_04_29_D2.md](STATUS_REPORT_2026_04_29_D2.md)

---

## ✅ D2.1 任务交付

| # | 交付 | 状态 |
|---|---|---|
| **A** | 8 题逐答 (Q1-Q8 全 ✅) | ✅ |
| **B** | API endpoint 完整清单 (22 router files / 13 含 POST/PUT/DELETE / 1 含 admin) | ✅ |
| **C** | broker 实例链路实测 (qmt_manager.broker = MiniQMTBroker, guard 覆盖) | ✅ |
| **D** | 4 broker 类清单 (BaseBroker / MiniQMTBroker / PaperBroker / SimBroker) | ✅ |
| **E** | 风险分级 + finding 清单 (3 新 finding D/E/F) | ✅ |
| **F** | A/B/C 路径影响补充 (D2 推荐 C 仍成立, 批 2 scope 扩 3 项) | ✅ |
| **G** | 主产物 docs/audit/api_auth_gate_2026_04_29.md (24307 bytes) | ✅ |
| **H** | 本 STATUS_REPORT | ✅ |

**0 代码改动 / 0 commit / 0 push / 0 PR / 0 重启** — 纯诊断完成.

---

## 📊 关键实测数字

### API 全清单
- **22 router files** in backend/app/api/
- **13 files** with POST/PUT/DELETE endpoints
- **1 file** (execution_ops.py) with admin token gate
- **9 sensitive endpoints** in execution_ops.py 全 `Depends(_verify_admin_token)`
- **12 files** without admin gate (P1: risk + approval; P2: strategies + params; P3: 其他)

### Broker 链路
- **qmt_manager.broker** = `MiniQMTBroker` (qmt_connection_manager.py:118 实测)
- **xtquant chokepoint**: 仅 `broker_qmt.py:463 _trader.order_stock` + `L508 _trader.cancel_order_stock`
- **LIVE_TRADING_DISABLED guard**: place_order:412-416 + cancel_order:482+
- **SAST 守门**: test_live_trading_disabled.py:222-252 全 codebase 扫描

### Auth Gate
- **ADMIN_TOKEN**: config.py:90 default `""`, .env **未配置** → fail-secure 500
- **CORS**: 严格白名单 `["http://localhost:3000"]`
- **Rate limit**: per-action only (4 sensitive ops, 1-5 次/日), 无全局
- **WebSocket**: 仅 backtest progress, 0 真金通道

---

## 🔴 3 项重大新发现

### Finding D — MiniQMTBroker.sell / .buy 方法不存在 (P2 dead API)

**实测**: `grep "def sell|def buy" backend/engines` 0 match. MiniQMTBroker 仅有 `place_order(code, direction='buy'|'sell', volume, ...)` 接口.

但 execution_ops.py:115/118 调 `qmt_manager.broker.sell(code, volume, price)` 和 `.buy(code, volume, price, amount)` → **运行时 AttributeError**.

**受影响 endpoint**:
- POST /api/execution/fix-drift/execute (L682, 701)
- POST /api/execution/emergency-liquidate (L772)

**影响**: P2 dead API. Admin-gated + AttributeError fail-fast → 0 P0 真金风险, 但**紧急清仓 API 不可用**, 只能用 `scripts/emergency_close_all_positions.py` 手工脚本.

**修法**: 留批 2/3 (加 sell/buy wrapper 或重写 execution_ops.py).

### Finding E — risk.py /force-reset + 6 关键 endpoints 无 admin auth (P1 审计绕过)

**实测**: 12 文件含 POST/PUT/DELETE 但**仅 execution_ops.py 含 `_verify_admin_token`**.

**P1 风险 endpoints** (破坏审计/状态完整性, 但仍受 LIVE_TRADING_DISABLED guard 盖):
- `risk.py:188` POST /l4-recovery (写 approval_queue)
- `risk.py:222` POST /l4-approve (审批 L4 恢复, flip cb 状态)
- `risk.py:255` POST /force-reset (force reset cb 到 NORMAL, **运维紧急用**)
- `approval.py:258, 288, 318` POST /queue/{id}/{approve,reject,hold} (gates L4 recovery)

**配合 P1 风险链**:
- /force-reset 重置 cb_state 到 L0 NORMAL → /l4-approve 审批通过 → /params PUT 改 PT 配置 → 看似激活了 trading 路径

**但 LIVE_TRADING_DISABLED guard 仍是 chokepoint**: 实际下单仍被拦 → 不构成 P0 真金风险, 仅破坏审计链.

**修法** (留批 2): risk.py 3 + approval.py 3 = 6 endpoints 加 `Depends(_verify_admin_token)`.

### Finding F — ADMIN_TOKEN 当前未配置 (.env 无 ADMIN_TOKEN line)

**实测**: `grep ADMIN_TOKEN backend/.env` 无 match. config.py:90 default `""`.

**影响**:
- ✅ Fail-secure: sensitive endpoint 调时返 500 "ADMIN_TOKEN未配置", 不可滥用
- ⚠️ 切 .env=live 前必须**生成强 token** (≥ 32 chars random) 写入 `.env: ADMIN_TOKEN=<...>`
- 否则紧急清仓 / 撤单 API 全 500, 紧急 ops 不可用 (虽 5 schtask 真金 disabled, 但 sensitive ops 是 fallback)

**修法** (留 PT 重启前):
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# 复制到 backend/.env: ADMIN_TOKEN=<paste>
# Servy restart QuantMind-FastAPI
```

铁律 35: secrets 不入 git history, 仅 .env 落盘 (已 gitignore).

---

## 🚨 风险等级总评

| 维度 | 等级 |
|---|---|
| 真金保护 (broker.place_order/cancel_order) | 🟢 0 (LIVE_TRADING_DISABLED guard, single chokepoint, SAST 守门) |
| API → broker 链路 (execution_ops.py 9 sensitive POST) | 🟢 0 (admin-gated + ADMIN_TOKEN fail-secure 500 + per-action rate limit) |
| qmt_manager.broker 实例 (MiniQMTBroker) | 🟢 0 (guard 100% 覆盖) |
| WebSocket / SSE / RPC 真金通道 | 🟢 0 (仅 backtest progress) |
| CORS 跨域 | 🟢 0 (严格白名单 localhost:3000) |
| 手工脚本 broker 实例 (4 scripts) | 🟢 0 (全走 MiniQMTBroker, guard 覆盖) |
| **risk.py + approval.py 6 endpoints 无 admin auth** | 🟡 **P1** (force-reset / l4-approve, 破坏审计但不绕 guard) |
| strategies.py / params.py 无 auth | 🟡 P2 (改运行时配置) |
| **MiniQMTBroker.sell/.buy 不存在** | 🟡 P2 (dead API claim, fix-drift/execute + emergency-liquidate 不可用) |
| **ADMIN_TOKEN 未配置** | 🟡 P2 (切 live 前必须配, 否则 ops endpoint 全不可用) |
| pms.py / factors.py / mining.py / pipeline.py / backtest.py / notifications.py / system.py / report.py 无 auth | ⚪ P3 (DoS / 噪音 / 资源消耗) |

**总评**: 🟢 **真金 P0 风险 0** — chokepoint LIVE_TRADING_DISABLED guard + admin-gated + SAST 三重保护, API 切 .env=live 后无法绕过盖网下单.

**但有 P1 治理债 2 件 + P2 治理债 2 件 + P3 治理债 1 类 (8 files)**.

---

## 🛤️ A/B/C 路径影响 (D2 + D2.1 综合)

D2 推荐 **C (等批 2)** 仍成立. D2.1 补:

- **A (.env→live)** 前置: 必先配 ADMIN_TOKEN (Finding F) + 修 risk.py 3 endpoints auth (Finding E). 否则 ops endpoint 不可用 + 审计漏洞.
- **B (paper + SKIP)** 不受 D2.1 影响 (admin token 与 mode 无关).
- **C (等批 2)** 顺带在批 2 修 Finding D/E/F.

---

## 📋 批 2 scope (合并 D2 + D2.1, 按优先级)

### P0 (真金漂移根因 — D2 Finding B)

1. pt_qmt_state.py 7 处 hardcoded 'live' → settings.EXECUTION_MODE 参数化
2. xfail strict 4 contract tests 转 PASS (test_execution_mode_isolation.py:471, 573-578)

### P1 (审计/安全 — D2.1 Finding E)

3. risk.py /l4-recovery / /l4-approve / /force-reset 加 `Depends(_verify_admin_token)`
4. approval.py /queue/{id}/{approve, reject, hold} 加 admin gate

### P2 (dead API + 治理 — D2.1 Finding D/F + D2 Finding A/C)

5. MiniQMTBroker.sell/.buy 加 wrapper 或重写 execution_ops.py (Finding D)
6. ADMIN_TOKEN 生成 + 写 .env + Servy User env (Finding F)
7. scripts/intraday_monitor.py:141 删 hardcoded override (D2 Finding A)
8. cb_state paper L0 stale orphan 清理 (D2 Finding C)

### P3 (低优先治理)

9. strategies.py / params.py / pms.py / factors.py / mining.py / pipeline.py / backtest.py / notifications.py / system.py / report.py 等 10 files POST/PUT/DELETE 加 auth gate
10. LoggingSellBroker → QMTSellBroker (Risk Framework 真 broker, 走 guard)

**ETA**: 批 2 ~1 周 (P0+P1 = 3-4 天, P2+P3 = 2-3 天).

---

## 📦 LL 候选沉淀

### LL-XXX (沿用批 1.5 + D2): audit 概括必须实测纠错

D2 报告原写 "API endpoint sell/buy auth gate ⚪ 待评估". 本 D2.1 实测发现:
- ✅ sell/buy endpoint 全 admin-gated (D2 概括 "未实测" → 实测 "已盖")
- ⚠️ MiniQMTBroker.sell/.buy 方法不存在 → endpoint dead (D2 概括 "需 verify auth gate" → 实测 "API 是 dead, auth gate 多余但仍存在")
- ⚠️ risk.py 3 endpoints 无 auth (D2 概括 "API 层风险待评估" → 实测 "P1 审计绕过债")

3 项实测验证全部修正了 D2 一阶概括, **再次实证 audit 概括 30%+ 偏离真因**, 加固批 1.5 LL-XXX 教训.

### LL 候选 (新): API endpoint 必含 auth gate 一致性原则

12 文件无 auth 是历史增量 (随各 MVP 加 endpoint, 无统一 lint 守门). 建议:
- 每个 POST/PUT/DELETE endpoint 必含明确 auth (admin token / read-only allow / 测试 fixture)
- 引入 lint rule (custom AST checker): grep `@router\.(post|put|delete)` 必伴随 `Depends(_verify_admin_token)` 或显式 `# AUTH_NONE: <reason>` 注释
- 现有 12 files 评级修补 (P1 立修 / P2 批 2 / P3 批 3)

**升级铁律候选**: 月度 (X7) 铁律 audit 时考虑加入"FastAPI 写操作 endpoint 必含 auth gate"原则. 当前先入 LESSONS_LEARNED.md.

### LL 候选 (新): broker 类接口契约不一致 (Finding D)

execution_ops.py 假设 broker 实例有 `.sell` / `.buy` 方法, 但 MiniQMTBroker 仅有 `.place_order`. 这是 BaseBroker 抽象不全 + 历史 API 增量 + 无类型守门 (broker 是 `Any` 类型).

**全局原则候选**: BaseBroker 抽象必须涵盖所有调用方需求 (sell/buy/cancel/place_order/query_*). 任何 broker 子类必须实现完整接口. 调用方 type-annotate 为 `BaseBroker` 而非 `Any`, 让 mypy 拦截缺失方法.

**修法**: 批 2 同步把 `qmt_manager.broker: Any` 改为 `BaseBroker` + 在 BaseBroker abstract method 中声明 sell/buy/cancel/place_order/query_*.

---

## 🚀 下一步建议

### (a) 路径决策

D2 推荐 **C (等批 2)** 仍成立. D2.1 补充: 批 2 scope 扩 3 项 Finding (D/E/F), 共 10 子任务 (P0×2 + P1×2 + P2×4 + P3×2).

### (b) 启批 2

按 P0/P1/P2/P3 优先级实施. ETA ~1 周.

### (c) 4 留 fail 清理同批

(批 1.5 STATUS_REPORT 已建议) — 批 2 同批清测试债 + 状态依赖类 fail 4 个.

### (d) 全方位审计 13 维 (D2/D2.1 是子集)

D2/D2.1 已覆盖: 激活路径维度 + API auth 维度 (2/13).

13 维其他 11 维 (留批 2 后启): 数据完整性 / 测试覆盖 / 文档腐烂 / Servy 服务依赖 / Redis 缓存 / 监控告警 / 调度链路 / 性能基线 / 配置 SSOT / 异常处理 / 安全 (SQL injection / secret rotation).

---

## 📂 附产物清单

- [docs/audit/api_auth_gate_2026_04_29.md](api_auth_gate_2026_04_29.md) — 本任务主产物 (24,307 bytes)
- [docs/audit/STATUS_REPORT_2026_04_29_D2_1.md](STATUS_REPORT_2026_04_29_D2_1.md) — 本 STATUS_REPORT
- 0 commit / 0 push / 0 PR (纯诊断, 0 改动)

---

> **状态**: D2.1 阶段 ✅ **完整完成** — 8 题诊断 + 22 API files + 13 含 POST/PUT/DELETE + 9 admin-gated + 12 unauth + 4 broker 类 + 3 finding (D/E/F).
> **真金 P0 风险**: 🟢 **0** (chokepoint guard + admin-gated + SAST 三重保护).
> **P1 治理债**: 🟡 2 件 (risk.py + approval.py 6 endpoints 无 auth, 破坏审计但不绕 guard).
> **P2 治理债**: 🟡 2 件 (MiniQMTBroker.sell/.buy dead API + ADMIN_TOKEN 未配置).
> **P3 治理债**: ⚪ 1 类 (8 files POST/PUT/DELETE 无 auth, DoS/噪音风险).
> **批 2 scope 扩**: D2 Finding A/B/C + D2.1 Finding D/E/F = 6 子任务, 加 P0/P1/P3 共 ~10 子任务.
> **D2 推荐路径 C (等批 2) 仍成立**.
