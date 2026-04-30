# STATUS_REPORT — D2 Live-Mode 激活路径全扫描

> **Sprint**: D2 (T1 Sprint, 2026-04-29 末)
> **Branch**: main @ `bc8bad4` (PR #151 批 1.5 merged)
> **Trigger**: 用户路径决策 A/B/C 前需扫描激活路径 + 副作用 + 安全清单
> **关联铁律**: 25 (改什么读什么) / 33 (fail-loud) / 34 (SSOT) / 36 (precondition) / 40 (test debt)
> **关联文档**: [live_mode_activation_scan_2026_04_29.md](live_mode_activation_scan_2026_04_29.md) (主产物)

---

## ✅ D2 任务交付

| # | 交付 | 状态 |
|---|---|---|
| **A** | 11 题逐答 (Q1-Q11 全 ✅) | ✅ |
| **B** | 6 大分类完整命中表 (~200 hits 跨 70+ files) | ✅ |
| **C** | 写路径漂移当前状态实测 (与上轮 STATUS_REPORT 描述一致, 批 1.5 未触动) | ✅ |
| **D** | 切 live 安全清单 (4 类) | ✅ |
| **E** | 风险等级总评 + A/B/C 推荐 | ✅ |
| **F** | 3 finding (Finding A/B/C) | ✅ |
| **G** | 主产物 docs/audit/live_mode_activation_scan_2026_04_29.md | ✅ (31611 bytes) |
| **H** | 本 STATUS_REPORT | ✅ |

**0 代码改动 / 0 commit / 0 push / 0 PR / 0 重启** — 纯诊断完成.

---

## 📊 实测数字 (硬证据基础)

### DB 命名空间状态 (2026-04-29 23:00)

| 表 | live | paper | 备注 |
|---|---|---|---|
| position_snapshot (30d) | **295** | **0** | live 全数据 |
| trade_log (30d) | **68** | **20** | paper 20 行 4-16 only (batch 3.4 历史) |
| circuit_breaker_state (latest) | L0 @ 4-28 | **L0 @ 4-20 stale 9 days** | paper L0 orphan, Finding C |
| performance_series | TBD | TBD | 未实测 (本 D2 scope 未含) |

### .env 当前值

```
EXECUTION_MODE=paper       ← 与 DB live 漂移 (启动断言会 BLOCK)
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/...  (active)
LIVE_TRADING_DISABLED=true (默认, fail-secure)
OBSERVABILITY_USE_PLATFORM_SDK=true (默认)
```

### Beat 当前激活 (实测 beat_schedule.py)

| Task | Schedule | State |
|---|---|---|
| gp-weekly-mining | 周日 22:00 | ✅ Active |
| outbox-publisher-tick | 30s | ✅ Active |
| daily-quality-report | 工作日 17:40 | ✅ Active |
| factor-lifecycle-weekly | 周五 19:00 | ✅ Active |
| risk-daily-check | (paused) | ❌ T1 sprint link-pause |
| intraday-risk-check | (paused) | ❌ 同上 |

### Schtask 当前激活 (实测 PowerShell)

**Ready (12)**: DailyIC / DailyMoneyflow / DataQualityCheck / FactorHealthDaily / IcRolling / MiniQMT_AutoStart / MVP31SunsetMonitor / PTAudit / PT_Watchdog / RiskFrameworkHealth / ServicesHealthCheck / DailyReconciliation (✗ 实测 Disabled, 上面表格修正)

**Disabled (5)**: DailyExecute / DailySignal / DailyReconciliation / IntradayMonitor / CancelStaleOrders

---

## 🔴 3 项重大新发现 (LL-XXX 教训应用 — audit 必须实测纠错)

### Finding A — scripts/intraday_monitor.py:141 hidden hardcoded override

```python
# Line 139-142:
# 设置环境让qmt_manager识别live模式
os.environ["EXECUTION_MODE"] = "live"
from engines.broker_qmt import MiniQMTBroker
```

**影响**: 此 script 强制覆盖 .env. schtask 当前 Disabled, 但**用户手工 / future schtask reenable 都会绕过 .env**.

**修法**: 留批 2/3 (删 L141 hardcoded 或改用 LIVE_TRADING_DISABLED guard).

### Finding B — pt_qmt_state.py 7 处写路径漂移仍未修

实测 grep 验证, 与上轮 STATUS_REPORT (批 1) 描述一致. 批 1 / 链路停止 / 批 1.5 全未触动.

| 行 | hardcoded 'live' 用途 |
|---|---|
| L46 | SELECT prev pos_snap |
| L55 | SELECT count current pos_snap |
| L147 | SELECT trade_log avg_cost |
| L158 | DELETE position_snapshot |
| L171 | INSERT position_snapshot VALUES literal |
| L197 | SELECT MAX(nav) perf_series |
| L214 | INSERT performance_series VALUES literal |

**影响**: 切 .env=live 后写读"碰巧对齐", **不是修复根因**. 任何回切 paper 立即重新触发漂移.

**修法**: 批 2 必修 (settings.EXECUTION_MODE 参数化 + xfail strict 4 contract tests 转 PASS).

### Finding C — circuit_breaker_state paper L0 stale orphan (4-20 16:30)

DB 实测: paper 行 stale 9 days 持续, 链路停止 PR 后无人写 paper namespace.

**影响**: 任何 ad-hoc tool 读 cb_state by execution_mode='paper' 会读 stale L0, 主链路用 settings 动态读切 live 后不再读 paper → orphan dormant.

**修法**: 留批 2/3 清理 (DELETE FROM cb_state WHERE execution_mode='paper').

---

## 🚨 风险等级总评

| 维度 | 等级 |
|---|---|
| 真金保护 (broker.place_order / cancel_order) | 🟢 0 风险 (LIVE_TRADING_DISABLED guard 默认 True + 双因素 OVERRIDE) |
| schtask 自动激活真金路径 | 🟢 0 风险 (5 关键 schtask 全 Disabled) |
| Beat 自动激活真金路径 | 🟢 0 风险 (risk Beat 2 PAUSED + 4 active 均不调 broker) |
| 启动断言 | 🟢 0 风险 (切 live 立即 pass) |
| 写路径漂移 (pt_qmt_state hardcoded 'live') | 🟡 P2 风险 (批 2 必修, 切 live 是 workaround 不根治) |
| paper namespace orphans (cb_state / trade_log 4-16) | 🟡 P3 风险 (dormant, 不影响主链路) |
| **scripts/intraday_monitor.py:141 hardcoded override** | 🟡 P2 风险 (留批 2/3) |
| API endpoint sell/buy auth gate | ⚪ 待评估 (本 D2 未实测, 留下次 audit) |

**总评**: 🟡 **可控** — 切 .env=live 后真金 0 风险, 主要风险是写路径根因未修 + intraday_monitor 隐藏 override.

---

## 🛤️ A/B/C 路径推荐 (基于实测证据)

### 推荐排序: **C > A > B**

#### 推荐 C — 等批 2 完成

**理由**:
- 当前 .env=paper + SKIP_NAMESPACE_ASSERT=1 应急 bypass, FastAPI/Worker 能启动
- 真金不会触发 (broker guard + schtask Disabled + Beat paused)
- PT 已暂停 (用户决策), 不需要 .env=live 来对齐生产
- **批 2 修写路径漂移 → 根治 ADR-008** > "切 .env=live 碰巧对齐"
- 切 live 后任何回切 paper 都会立即重新触发漂移

**反对意见 (最强)**:
- DB 已全 live, .env=paper 是"假装 paper", 误导 onboarding
- SKIP bypass 长期保留违反铁律 33 精神
- ad-hoc tool (paper_trading_status.py 等) 在 paper namespace 读 0 行

**反驳**: 临时成本可接受. 批 2 ETA ~1 周, 期间 SKIP bypass + PT 已停, 无运维事故.

#### 备选 A — 切 .env=live (仅 PT 重启场景)

**适用**: 用户决定**立即重启 PT live** + 批 2 并行进行.

**理由**:
- startup 断言立即通过, FastAPI 干净启动
- 写读路径自动对齐
- API endpoint 数据展示正确

**反对意见 (最强, 阻断单独切 live)**:
- 切 live 不修写路径漂移根因. **看起来无事 ≠ 修了**
- 任何后续 paper 测试场景都会重新触发漂移
- LL-XXX 教训: "audit 概括必须实测代码纠错". 切 live 不是修复, 是 workaround

**结论**: 仅在 PT 重启决策同步进行时才推荐.

#### 备选 B — 保 paper + SKIP_NAMESPACE_ASSERT=1

**实质**: B 是 C 的实施手段 (当前已采用此 mode), 不是独立路径.

---

## 📊 D2 实测覆盖率

| 检查项 | 覆盖 | 漏检 |
|---|---|---|
| EXECUTION_MODE 全分布 | ~200 hits 跨 70+ files | 包含 archive/tests, 实际生产路径已聚焦 |
| 6 大分类 | 主要文件已分类 | archive 16+ files 简略归类 dormant |
| 激活时序 a-f | Beat / schtask / API / 手工 / dormant 全覆盖 | API auth gate 实测留下次 |
| DB 命名空间 | position_snapshot / trade_log / cb_state | performance_series 30d 未查 |
| Beat / Schtask | 100% 实测 | — |
| broker_qmt guard | 100% 实测 | — |
| signal_service / daily_pipeline / intraday_monitor | 100% 实测 | execute_phase 仅查 hardcoded line |
| pt_qmt_state 写路径 | 100% 实测 (7 处 hardcoded 全列) | — |
| API endpoint auth gate | ❌ 未实测 | 留下次 audit / 全方位 13 维审计 |

---

## 📦 LL 候选沉淀

### LL-XXX (沿用批 1.5): audit 概括必须实测纠错

本 D2 自身就是 audit 性质. 应用了批 1.5 LL-XXX 教训:
- ✅ 不凭代码外观判定 ("看到 if mode=='live' 不代表它会跑")
- ✅ 实测 schtask state + Beat 注释 + DB SQL 查 + grep 命中
- ✅ 实测纠错: STATUS_REPORT (批 1) 描述的 "pt_qmt_state 5 处 hardcoded" 实际是 7 处 (5 SELECT/DELETE + 2 INSERT VALUES literal)

但 D2 报告自身的一阶概括 (如 "4 active Beat 均不调 broker") 在批 2 实施时仍应再 verify — D2 是当前实测快照, 非永久真理.

### LL 候选 (新): 隐藏 hardcoded override 是 .env SSOT 漂移源 (Finding A)

scripts/intraday_monitor.py:141 这种**runtime os.environ 覆盖**比 .env / settings.EXECUTION_MODE 更深一层, 任何 .env 切换决策**都被该 script 绕过**.

**全局原则候选**: 任何代码不允许 runtime 覆盖 EXECUTION_MODE / LIVE_TRADING_DISABLED 等关键 ssot 配置. 必须经 settings (Pydantic) 单一入口. 违反 → 切 .env 决策被绕过, ADR-008 漂移再发.

**升级铁律候选**: 月度 (X7) 铁律 audit 时考虑加入"配置 runtime 覆盖禁止"原则. 当前先入 LESSONS_LEARNED.md.

---

## 🚀 下一步 (用户决策点)

> **状态**: D2 ✅ 完成. main @ `bc8bad4` (无变化). 0 改动.

### 用户决策清单

1. **路径选择**: A / B / C? (推荐 **C**)
2. **批 2 启动**: 立即启? 还是先做全方位审计 13 维?
3. **PT 重启**: 是否同步评估 (paper-mode 5d dry-run 是否满足重启 gate)?
4. **4 留 fail 清理**: 与批 2 同批 还是单独清理?

### 推荐序列

**优先**: C (等批 2) → 启批 2 (写路径漂移消除 + intraday_monitor 修 + cb_state 清理) → 4 留 fail 同批清理 → 批 2 完成后再决议 PT 重启 / .env=live cutover.

**ETA**: 批 2 ~1 周 (写路径修 2-3 天 + LoggingSellBroker→QMTSellBroker 替换 2-3 天 + verify + reviewer + merge).

---

> **状态**: D2 阶段 ✅ **完整完成**.
> **关键产物**: docs/audit/live_mode_activation_scan_2026_04_29.md (31611 bytes 主产物) + 本 STATUS_REPORT.
> **风险结论**: 🟡 可控. 切 .env=live 后真金 0 风险 (guard + schtask). 主要风险是**写路径漂移根因未修** (留批 2) + **3 finding 新发现** (intraday_monitor hardcoded / pt_qmt_state 7 处 / cb_state orphan).
> **推荐路径**: C (等批 2) > A (切 live, 仅 PT 重启时) > B (保 paper + SKIP, 临时).
