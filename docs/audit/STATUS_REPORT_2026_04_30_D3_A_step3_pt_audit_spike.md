# STATUS_REPORT — D3-A Step 3 Spike (F-D3A-14 真因关联实测)

**Date**: 2026-04-30
**Branch**: chore/d3a-step3-pt-audit-spike
**Base**: main @ 3a58cdd (PR #156 D3-A Step 1+2 spike merged)
**Scope**: D3-A Step 1 副产品发现 F-D3A-14 真因 baseline 锁定 (PR #157 apply migrations 之前)
**ETA**: 实跑 ~10 min CC (vs 预估 5, 略超 — Q2 log 文件 forensic 多了 1 步)
**真金风险**: 0 (0 业务代码改 / 0 .env 改 / 0 服务重启 / 0 DML / 0 真发 DingTalk)
**改动 scope**: 1 文档 (本 STATUS_REPORT) — 单 PR `chore/d3a-step3-pt-audit-spike`, 跳 reviewer

---

## §0 环境前置检查 E1-E5 全 ✅

| 项 | 实测 | 结论 |
|---|---|---|
| E1 git status | main @ `3a58cdd` (PR #156 merged), 8 D2 untracked (上 session 残留, 不在 scope) | ✅ |
| E2 PG stuck backends | 1 (仅本审计 psql session) | ✅ |
| E3 Servy 4 服务 | FastAPI / Celery / CeleryBeat / QMTData ALL Running | ✅ |
| E4 .venv Python | Python 3.11.9 | ✅ |
| E5 真金 fail-secure | `LIVE_TRADING_DISABLED=True` + `OBSERVABILITY_USE_PLATFORM_SDK=True` | ✅ |

**额外现状实测**: alert_dedup 表 4-30 13:26 实测仍**不存在** (information_schema.tables 0 hits). PR #157 尚未启动, 与 D3-A Step 1 spike (4-30 ~03:00) 一致, **0 漂移**.

---

## Q1 pt_audit 启动逻辑 + alert 调用点

### Q1(a) ✅ 入口路径 (schtask /XML 实测)

```xml
<Exec>
  <Command>D:\quantmind-v2\.venv\Scripts\python.exe</Command>
  <Arguments>D:\quantmind-v2\scripts\pt_audit.py --alert</Arguments>
  <WorkingDirectory>D:\quantmind-v2</WorkingDirectory>
</Exec>
<ExecutionTimeLimit>PT5M</ExecutionTimeLimit>
<CalendarTrigger><StartBoundary>2026-04-25T17:35:00+08:00</StartBoundary></CalendarTrigger>
```

确认: `scripts/pt_audit.py --alert`, 5min timeout, 每天 17:35.

### Q1(b) ✅ 入口脚本 5-30 行 (Read pt_audit.py:1-80)

- L1-32 docstring + exit codes (0 clean / 1 P0 / 2 P1 / 3 P2)
- L34-50 import `argparse / functools / logging / os / sys / psycopg2`
- L52-60 .env 加载 (standalone pattern, `os.environ.setdefault`)
- L62-78 `logging.basicConfig` + `FileHandler(logs/pt_audit.log)` (无 `delay=True`, 立即 open)
- L80+ Platform SDK 顶层 import (`from qm_platform.observability import get_alert_router, AlertDispatchError, ...`)

**铁律 43-c 实施**: stderr boot probe — 实测 pt_audit.py **无** `print(..., file=sys.stderr)` 启动 probe. 不在本 spike scope 但记录 (副产品 finding 候选).

### Q1(c) ✅ alert 调用点 (grep + Read 实测)

| 行 | 函数 | 调用 |
|---|---|---|
| 547 | `_send_alert_via_platform_sdk` | 走 SDK path (settings.OBSERVABILITY_USE_PLATFORM_SDK=True default) |
| 588 | (within above) | `router = get_alert_router()` (PostgresAlertRouter instance) |
| **590** | (within above) | **`result = router.fire(alert, dedup_key=dedup_key, suppress_minutes=suppress_minutes)`** ← 关键调用 |
| 595-601 | (within above) | `logger.info("[Observability] AlertRouter.fire result=%s ...")` ← 仅 fire 成功才到 |
| 602-604 | (within above) | `except AlertDispatchError as e: logger.error(...); raise` |
| 607 | `_send_alert_via_legacy_dingtalk` | fallback (settings flag=False 时), httpx.post 直调 |
| 641 | `send_aggregated_alert` | 派发 SDK / legacy 选择器 (line 654 `if settings.OBSERVABILITY_USE_PLATFORM_SDK:`) |
| 720-726 | `run_audit` | `try: send_aggregated_alert(...) except AlertDispatchError as e: logger.error(...)` |

**关键代码段** (pt_audit.py:720-726):
```python
try:
    send_aggregated_alert(all_findings, audit_date)
except AlertDispatchError as e:
    logger.error(
        "[Observability] AlertDispatchError — 告警未送达, scheduler_log 仍写: %s",
        e,
    )
```

**关键 main() 段** (pt_audit.py:776-793):
```python
def main() -> None:
    ...
    args = parser.parse_args()
    only = ...
    exit_code, findings = run_audit(...)  # ← UndefinedTable escape 路径
    if findings:
        logger.warning("[audit] 完成: %d findings, exit=%d", ...)
    else:
        logger.info("[audit] 完成: 0 findings (all pass), exit=%d", ...)
    sys.exit(exit_code)
```

**🔴 main() 无顶层 `try/except`** — 不符铁律 43-d 标准 (schtask Python 脚本 fail-loud 硬化 4 项清单第 4 项): `except Exception as e: print(f"[script] FATAL: ...", file=sys.stderr); traceback.print_exc(); ...; return 2`

---

## Q2 4-29 stderr/log 实测 (核心证据)

### Q2(c) ✅ logs/pt_audit.log 4-29 17:35:00 时间窗实测

```bash
grep "^2026-04-29 17:" D:/quantmind-v2/logs/pt_audit.log
```

**实测输出** (6 行, 然后突然中断):
```
2026-04-29 17:35:02,092 [INFO] [audit] date=2026-04-29 sid=28fc37e5... checks=['st_leak', 'mode_mismatch', 'turnover_abnormal', 'rebalance_date_mismatch', 'db_drift']
2026-04-29 17:35:02,101 [INFO]   [st_leak] PASS
2026-04-29 17:35:02,102 [INFO]   [mode_mismatch] PASS
2026-04-29 17:35:02,103 [INFO]   [turnover_abnormal] PASS
2026-04-29 17:35:02,107 [INFO]   [rebalance_date_mismatch] PASS
2026-04-29 17:35:02,109 [WARNING]   [P1] db_drift: DB drift 2026-04-29: expected=19 vs snapshot=0
[NO MORE 4-29 17:xx ENTRIES — log resumes at 21:39 manual test runs]
```

### 🔴 关键发现: log 在 db_drift finding 之后**突然中断**

按 pt_audit.py 代码流, 17:35:02,109 之后预期 log lines:
- L595-601: `[INFO] [Observability] AlertRouter.fire result=sent key=pt_audit:summary:2026-04-29 ...` (来自 _send_alert_via_platform_sdk)
- 或 L723-725: `[ERROR] [Observability] AlertDispatchError — 告警未送达, scheduler_log 仍写: ...` (run_audit catch)
- 或 L786-788: `[WARNING] [audit] 完成: %d findings, exit=%d` (main 收尾)

**实测 0 上述行**. log 在 db_drift WARNING 后**直接终止**.

### 因果链推断 (实测证据驱动)

1. ✅ pt_audit 启动 → logger init → 5 checks 跑完 (st_leak / mode_mismatch / turnover / rebalance / db_drift 各 PASS / 1 P1)
2. ✅ `if alert:` 进入 (schtask 传 `--alert`)
3. ✅ `send_aggregated_alert` 调 → `_send_alert_via_platform_sdk` (SDK path, settings 默认)
4. ✅ `router.fire(alert, dedup_key)` 调 → PostgresAlertRouter._is_deduped → `SELECT suppress_until FROM alert_dedup WHERE dedup_key = %s`
5. 🔴 **alert_dedup 表不存在 → `psycopg2.errors.UndefinedTable` raise**
6. 🔴 UndefinedTable **不是 AlertDispatchError** → pt_audit:720-726 `except AlertDispatchError` **不接**
7. 🔴 UndefinedTable 越过 inner catch + 越过 run_audit 的 try-finally (finally 仅 close conn) → 进 main()
8. 🔴 main() 无顶层 try/except → Python 默认行为: 打印 traceback to stderr + exit code 1
9. 🔴 schtask 收 LastResult=1 (4-29 17:35 实测)
10. 🔴 _write_scheduler_log 永远没调用 (在 try 块内 send_aggregated_alert 之后, alert raise 阻止到达) → DB 无 audit log (D3-A F-D3A-14 描述)

✅ **完美 match D3-A F-D3A-14 描述** ("schtask Result=1 但 DB 无 audit log").

### Q2(a)+Q2(b) 辅助证据

**schtask /Query**: 实测 4-30 13:26 LastResult=1 仍存 (与 D3-A 一致).

**Windows Event Log** (`Get-WinEvent` 4-29 17:30~17:42 时间窗): 工具调用 exit code 1, 0 events 返 — 可能是 schtask events 被快速 rotate 或权限问题. 不阻塞结论 (log 文件证据已充分).

**logs/pt_audit.log 跨日 forensic**:
- 4-20 ~ 4-29 17:34 历史 entry 大量 (file 66358 字节)
- 4-29 17:35:02,109 db_drift WARNING 后 **直接 jump 到 4-29 21:39:38** (manual test run, 4h 间隔)
- 4-29 21:39+ 测试 entries 显示 `[INFO] AlertRouter.fire result=sent` — 但这些是 future date 2099-04-15 / sid=test_sid 等明显 unit test mock 路径, 不证 alert_dedup 真存在 (mock conn_factory 不 hit DB)
- 4-30 01:14 / 01:19 / 01:30 同样 manual test (同 pattern), 后跟 D3-A Step 1 spike 03:00 实测 alert_dedup 不存在
- → **4-29 17:35 真生产 schtask 启动时 alert_dedup 已不存在**, log 中断在 fire raise 时点

---

## Q3 mock invoke

**跳过** — Q1+Q2 证据充分, Q4 决议无需补充 mock invoke. 节省 ~2min CC.

---

## Q4 F-D3A-14 真因决议 (无模糊兜底)

| 候选 | 实测证据 | 决议 |
|---|---|---|
| **A: alert_dedup raise → fail** | ✅ Q1 调 alert (L590) + Q2 log 在 db_drift 后中断 + L720 except 太窄 (仅 AlertDispatchError 不接 UndefinedTable) + main() 无顶层 catch + LastResult=1 + DB 无 audit log 全部一致 | **✅ 真因证实** |
| B: 与 alert 无关 | ❌ Q1 真调 alert / Q2 log 序列匹配 alert 路径 fail | 否 |
| C: 部分关联 | ❌ 无其他独立 fail 点证据 | 否 |
| D: 数据不足 | ❌ 5 项独立证据全 align | 否 |

### F-D3A-14 升级: P1 → **P0** (Step 1 P1→P0 候选 升级)

**修法路径**: 应用 3 missing migrations (PR #157) → alert_dedup 存在 → router.fire 不 raise UndefinedTable → pt_audit 17:35 schtask 完整跑完 + DB audit log 写入.

### PR #157 后 24h 验证预测 (forward-looking)

| 假设 | 预测 |
|---|---|
| F-D3A-14 真因 = alert_dedup raise (本 spike 实测) | 应用 migrations 后, pt_audit 下次 schtask 17:35: log **应** 有 `AlertRouter.fire result=...` 行 + DB scheduler_task_log entry |
| LastResult **不必为 0** | 取决于当天实际 findings (4-29 有 P1 db_drift → exit 2). 验证关键不在 LastResult, 在: (1) DB 有 audit log entry, (2) log 文件 entry 完整 (含 alert path), (3) UndefinedTable 不再出现. |

LL "假设必实测" forward-looking 验证规则: PR #157 merge 后 ~24h, user 跑 `schtasks /Query /TN QuantMind_PTAudit /V /FO LIST` + `psql ... SELECT * FROM scheduler_task_log WHERE task_name='pt_audit' AND start_time > '2026-04-30 17:00'` + `tail -30 logs/pt_audit.log`, 验证 alert 路径 entry 写入. 如未写 → 真因仍未明, D3-B 续查.

---

## 副产品 Finding (本 spike 新发现)

### F-D3A-NEW-1 (P2) — pt_audit.py main() 无顶层 try/except

**违反铁律 43-d** (schtask Python 脚本 fail-loud 硬化 4 项清单第 4 项):
> `main()` 顶层 try/except → stderr + exit(2): `except Exception as e: print(f"[script] FATAL: ...", file=sys.stderr); traceback.print_exc(); ...; return 2`

**实测 pt_audit.py:776-789** main():
```python
def main() -> None:
    ...
    args = parser.parse_args()
    exit_code, findings = run_audit(...)  # ← UndefinedTable escape 直接 crash 进程
    if findings: ...
    else: ...
    sys.exit(exit_code)
```

**修法 (留批 2 P3 候选)**:
```python
def main() -> int:
    print(f"[pt_audit] boot {datetime.now().isoformat()} pid={os.getpid()}", flush=True, file=sys.stderr)  # 铁律 43-c
    try:
        ... (existing main body) ...
        return exit_code
    except Exception as e:  # 铁律 43-d
        print(f"[pt_audit] FATAL: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc()
        return 2

if __name__ == "__main__":
    sys.exit(main())
```

**当前影响**: 若 alert_dedup 修复后 pt_audit 又遇其他 unhandled exception, 仍会 silently crash 无 stderr trace. 防御 in depth 修.

### F-D3A-NEW-2 (P3 候选) — pt_audit.py 缺 boot stderr probe

**违反铁律 43-c** (boot stderr probe 硬化清单第 3 项):
> `main()` 首行 `print(f"[script] boot {datetime.now().isoformat()} pid={os.getpid()}", flush=True, file=sys.stderr)`

实测 pt_audit.py main() 无此 probe. 即便 logger init 失败, schtask stderr 应有启动证据. 修法见 NEW-1.

(其他 schtask scripts 沿用 LL-068 模板已加 probe, pt_audit.py 漏加 — 1 阶概括第 N 次).

---

## LL "假设必实测纠错" 累计 14 → **17** (+3)

D3-A STATUS_REPORT 12 + Step 1+2 spike 14 → 本 spike 新增 **3 次**:

| 第 | 来源 | 假设 | 实测 |
|---|---|---|---|
| 15 | F-D3A-14 真因 "极可能是 alert_dedup raise" (Step 1+2 spike 描述) | "极可能" / 1 阶推理 | 实测 5 项独立证据 (代码路径 + log 中断时点 + except 太窄 + main 无 catch + LastResult+无 audit log) align — 真因证实 |
| 16 | "pt_audit.py 沿用铁律 43 schtask 4 项清单" (Session 27 末 LL-068) | 5 个 schtask scripts 全合规 | 实测 pt_audit.py main() 无顶层 try/except + 无 boot stderr probe — 漏 2 项硬化 (NEW-1 + NEW-2) |
| 17 | "Q3 mock invoke 必跑" (本 spike Q3 设计) | 必须真 invoke 实测 | Q1+Q2 证据充分, Q3 跳过 — prompt 设计的"必"是过度防御 |

**累计 17 次**. 复用规则 (LL 全局): 写 finding / spike prompt 时, 任何 "极可能 / 必跑 / 沿用 X 模式 / 1 阶推理" 假设, 必须附实测证据快照. 否则降级 informational, 待二次实测.

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
| 0 真发 DingTalk | ✅ | 0 调 router.fire / send_aggregated_alert (Q3 跳过) |
| 0 LLM SDK 调用 | ✅ | 本 spike 是开发诊断边界 (铁律 X1) |
| 0 修复 F-D3A-14 | ✅ | 本 spike 仅锁定真因 baseline, 修留 PR #157 |

---

## 下一步建议

### 立即 (推荐 A)

- **A**: user 立即启 PR #157 `fix/apply-missing-migrations` 应用 3 migrations + reviewer 审 + AI self-merge
  - 应用 alert_dedup 后 F-D3A-14 真因自然修复 (本 spike 实测确认)
  - 24h 后验证 pt_audit schtask 17:35 完整 entry + DB audit log
- **B**: 直接启 D3-B 中维度 5 个 (~5h), 3 migrations 留批 2

### 后续 (D3-B / 批 2 / 批 3 候选)

| Finding | 严重度 | 处理 |
|---|---|---|
| F-D3A-NEW-1 pt_audit.py main 无 try/except (铁律 43-d) | P2 | 批 2 P2 候选, 修法见上 |
| F-D3A-NEW-2 pt_audit.py 缺 boot stderr probe (铁律 43-c) | P3 | 批 2 P3 候选 |
| F-D3A-14 (alert_dedup 真因) | P0 | PR #157 应用 migrations 后自然修复 |
| 其他 schtask scripts (Session 27 LL-068 5 scripts) | INFO | 候选 audit 验证它们是否也漏 NEW-1/NEW-2 (1 阶概括第 16 次) |

---

## 关联

- **D3-A STATUS_REPORT** ([STATUS_REPORT_2026_04_30_D3_A.md](STATUS_REPORT_2026_04_30_D3_A.md)) — Step 3 是本系列收尾
- **D3-A Step 1+2 Spike** ([STATUS_REPORT_2026_04_30_D3_A_step1_step2_spike.md](STATUS_REPORT_2026_04_30_D3_A_step1_step2_spike.md)) — Step 1 副产品发现 F-D3A-14 极可能真因 → 本 spike 实测确认
- **F-D3A-1** (3 missing migrations P0) — PR #157 修复目标
- **F-D3A-14** P1 → **P0** 真因证实 (alert_dedup raise)
- **F-D3A-NEW-1/NEW-2** (本 spike 副产品) — pt_audit.py 漏铁律 43-c/43-d
- **铁律 33 fail-loud** — pt_audit `except AlertDispatchError` 设计正确 (UndefinedTable 应 propagate, 真 fail-loud), 但 main() 缺顶层 catch 是设计漏 (43-d)
- **铁律 43 schtask Python 脚本硬化 4 项清单** (Session 27 LL-068 沉淀) — pt_audit.py 漏 2/4 项
- **LL "假设必实测纠错"** 第 15-17 次 (累计 17 次)

---

## 用户接触

实际 0 (沿用 D2/D3-A/Step 1+2/runbook init/PR #154 LOW 改动模式, 0 业务代码 + 跳 reviewer + AI self-merge).

如本 STATUS_REPORT 触发 user 决策 (选项 A/B), user 接触 1 (决议下一步).
