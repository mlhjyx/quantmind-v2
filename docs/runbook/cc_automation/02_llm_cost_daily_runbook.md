# Runbook 02 — LLM Cost Daily Aggregate (S2.3 PR #224)

**触发场景**: Mon-Fri 20:30 schtask `QuantMind_LLMCostDaily` 自动跑, 或 user 一句话 "跑 LLM 成本日报" → CC 加载本 runbook → 自主执行.

**真金 0 风险**:
- 0 broker call (LLM 路径 0 真发单)
- 0 SQL DML (仅 SELECT 真聚合查询, INSERT 走 BudgetAwareRouter 真生产 path)
- LIVE_TRADING_DISABLED guard 沿用
- DingTalk push 沿用 stub if webhook_url='' (反 .env 真值 leak)

---

## 前置依赖

1. PR #221 LiteLLM SDK + config/litellm_router.yaml ✅ (Sprint 1)
2. PR #222 LiteLLMRouter core + 7 task enum ✅ (Sprint 1)
3. PR #223 BudgetGuard + BudgetAwareRouter + llm_cost_daily 表 ✅ (Sprint 1)
4. PR #224 LLMCallLogger + llm_call_log 表 + scripts/llm_cost_daily_report.py ✅ (本 runbook)
5. migration 2026_05_03_llm_cost_daily.sql + llm_call_log.sql 真生产 apply (manual ops, 反 auto wire)
6. setup_task_scheduler.ps1 Section 16 register (manual ops, 沿用 X10)

---

## 前置检查清单

```bash
# 1. main HEAD 含 PR #224
git log --oneline -5 | grep "S2.3"

# 2. 表存在 (PG 实测, 反 silent missing)
psql -d quantmind_v2 -U xin -c "\d llm_call_log"
psql -d quantmind_v2 -U xin -c "\d llm_cost_daily"

# 3. schtask 已注册 (manual ops 后)
Get-ScheduledTask -TaskName "QuantMind_LLMCostDaily"

# 4. .env DINGTALK_WEBHOOK_URL 状态确认 (空 → 沿用 stub noop)
grep "^DINGTALK_WEBHOOK_URL" backend/.env || echo "0 set, 反 push (沿用决议 (I))"

# 5. .env DINGTALK_ALERTS_ENABLED=true (生产开 true, paper 真测沿用 false)
grep "^DINGTALK_ALERTS_ENABLED" backend/.env
```

期望:
- (1) 含 c5d29ad 之后的 S2.3 commit
- (2) 2 表全 \d 真返 schema
- (3) schtask State=Ready
- (4) webhook_url 0 set 时**真 noop noop**, 反 push (沿用决议 (I))
- (5) ALERTS_ENABLED=False 时真**反 push** (沿用 .env 双锁体例)

---

## 执行步骤

### Step 1: 本地 verify 真 dry-run (0 push)

```bash
cd D:/quantmind-v2
.venv/Scripts/python.exe scripts/llm_cost_daily_report.py --no-dingtalk --verbose
```

期望输出:
- exit 0 真合法 (含 0 calls 真月初空真值)
- markdown payload 真完整 print (title + sum + breakdown)
- DB conn 真连 quantmind_v2 + 0 SQL fail

### Step 2: 历史日回填 verify (--date)

```bash
.venv/Scripts/python.exe scripts/llm_cost_daily_report.py --date 2026-05-15 --no-dingtalk
```

### Step 3: 真 push verify (DINGTALK_ALERTS_ENABLED=true 时)

```bash
.venv/Scripts/python.exe scripts/llm_cost_daily_report.py --verbose
```

期望:
- DingTalk 真**markdown push** 入群 (含 cost / breakdown / state label)
- 群可见消息 + errcode=0 (沿用 dispatchers/dingtalk.py 真返)

### Step 4: schtask 真 manual register (沿用 X10 + LL-098)

```powershell
# user 显式触发 (NOT auto, 反 X10 forward-progress)
powershell -ExecutionPolicy Bypass -File scripts\setup_task_scheduler.ps1
```

期望:
- Section 16 真 Register 成功 + Write-Host "[OK] QuantMind_LLMCostDaily registered"
- Get-ScheduledTask 真返 State=Ready
- 实测下次 NextRunTime 真**Mon-Fri 20:30** (含跨周末跳过)

---

## 验证清单

| # | 项 | ok 标准 | fail 处置 |
|---|---|---|---|
| 1 | --no-dingtalk verbose 真生成 markdown | exit 0 + markdown payload 完整 | 检查 PG conn / SQL syntax / migration 真 apply |
| 2 | DingTalk push errcode=0 (生产真测) | 群消息可见 + dispatchers log "成功" | 检查 webhook_url + secret + keyword 真值 |
| 3 | schtask Mon-Fri 20:30 NextRunTime 真值 | NextRunTime 真**Mon-Fri 20:30** | 重跑 setup_task_scheduler.ps1 + 实 Get-ScheduledTask |
| 4 | 1 周后真 schtask 真触发 (历史 LastRunTime) | LastRunTime 真**Mon-Fri 20:30 内** | 反 schtask Disabled / 反真生产 silent skip |
| 5 | llm_call_log 真生产含 row (BudgetAwareRouter wire 后) | row count > 0 | 检查 BudgetAwareRouter wire (audit param 真传) |

---

## 失败回滚

### Migration 失败 (Step 1 表不存在)

```bash
# 重 apply migration (沿用 risk_event_log_rollback.sql 体例)
psql -d quantmind_v2 -U xin -f backend/migrations/2026_05_03_llm_call_log_rollback.sql
psql -d quantmind_v2 -U xin -f backend/migrations/2026_05_03_llm_call_log.sql
```

### schtask 失败 (Step 4 Register error)

```powershell
# 单 task delete 重注册 (反整 ps1 重跑导致 16 task 全 Force overwrite)
schtasks /delete /tn "QuantMind_LLMCostDaily" /f
# 再跑 setup_task_scheduler.ps1
```

### DingTalk push spam (Step 3 push 触发 P0 群消息洪水)

```bash
# .env 紧急关 ALERTS_ENABLED 双锁
echo "DINGTALK_ALERTS_ENABLED=False" >> backend/.env
# 沿用 dingtalk.py:65-67 stub if 0 set 体例 → 自动 noop
```

---

## STATUS_REPORT

完成后归档到:
- `docs/audit/STATUS_REPORT_<date>_llm_cost_daily.md`
- 含: 真生产 wire 时间 / 首次 schtask 触发 LastRunTime / 1 周累计 row 数 / DingTalk 群消息真测截图

---

## 关联

- [backend/qm_platform/llm/audit.py](../../../backend/qm_platform/llm/audit.py)
- [backend/migrations/2026_05_03_llm_call_log.sql](../../../backend/migrations/2026_05_03_llm_call_log.sql)
- [scripts/llm_cost_daily_report.py](../../../scripts/llm_cost_daily_report.py)
- [docs/LLM_IMPORT_POLICY.md §10.7](../../LLM_IMPORT_POLICY.md)
- ADR-031 §6 / V3 §16.2 / V3 §20.1 #6 / 决议 6 (a) S5 退役合并
