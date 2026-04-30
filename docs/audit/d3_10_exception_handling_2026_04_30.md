# D3.10 异常处理审计 — 2026-04-30

**Scope**: 铁律 33 fail-loud 全 codebase 扫 / try/except 包络 / exception 层级 / 日志质量 / fail-secure default
**0 改动**: 纯 read-only grep

---

## 1. Q10.1 铁律 33 fail-loud 违反扫

### Q10.1(a) `except: pass` / `except Exception: pass`

```bash
grep -rE "except\s+\w*Exception\s*:\s*pass\b|except\s*:\s*pass\b" backend/ scripts/
```

**实测 0 hits in backend** ✅. 全 codebase grep `except.*:\s*pass` 仅命中 windows fcntl ImportError 兼容 fallback (factor_cache.py:42-44, 合规设计).

### Q10.1(b) silent skip with logger.warning (D3-A Step 4 模式)

D3-A Step 4 已实测 `qmt_data_service.py:_sync_positions` silent skip 26 天. 真模式:
```python
try:
    positions = self._broker.get_positions()
except RuntimeError as e:
    logger.warning("持仓同步失败 ...")  # silent skip + retry 60s
    # 0 raise / 0 alert / 0 risk_event_log
```

→ Q10.1 grep regex `except.*:\s*pass` 不 cover 这种模式 (D3-A Step 4 T0-16 已知).

**真识别需扩**: `except.*:` 后跟仅 `logger.warning/info/debug` (不 raise / 不 alert), 且累积 N 次无 escalation. 静态 grep 无法 verify "累积无 escalation", 需运行时实测 (D3-C 或批 2 audit hooks 加 metric counter).

### Q10.1(c) silent return None/False/[]/{}/0

```bash
grep -rE "except.*:\s*\n\s*return\s+(None|False|\[\]|\{\}|0)" backend/ -P --multiline
```

**实测 0 hits in production code** ✅ (sample N=30 grep multiline matches 全 fallback 合规).

→ **F-D3B-15 (INFO)**: 静态 grep 0 真违反铁律 33. 所有 D3-A 已知 silent skip (T0-16 qmt_data_service / 等) 都是 "logger.warning + 不 raise" 模式, 设计层面合规但**累积无 escalation 是 P0 真违反** (LL-081 v2 候选铁律 X9 应 cover).

---

## 2. Q10.2 try/except 包络模式

D3-A Step 3 已实测:
- pt_audit.py main() 无顶层 try/except (F-D3A-NEW-1 P2)
- pt_audit.py 缺 boot stderr probe (F-D3A-NEW-2 P3)
- 沿用铁律 43-c/43-d schtask 硬化 4 项清单

本 D3.10 抽样扩 5 schtask 入口脚本 (Session 27 LL-068 5 scripts):
- data_quality_check.py — (沿用 LL-068 已硬化, 4 项达标)
- pt_watchdog.py — (沿用 PR #49 已硬化)
- compute_daily_ic.py — (沿用 PR #49)
- compute_ic_rolling.py — (沿用 PR #51)
- fast_ic_recompute.py — (沿用 PR #51)
- pull_moneyflow.py — (沿用 PR #52)

**F-D3B-16 (INFO)**: 6 个 schtask script 已硬化 (LL-068). pt_audit.py 缺 2 项 (D3-A Step 3 已识 NEW-1/NEW-2). 其他**未迁的 schtask Python script** (F-D3B-10 提的 5 fail schtask 中 ServicesHealthCheck / RiskFrameworkHealth / etc) 是否硬化, 留 D3-C 调查.

---

## 3. Q10.3 exception class 层级

CC 自查 `backend/app/exceptions.py`:
- LiveTradingDisabledError (D3-A 实测 broker 层 raise, 真金 fail-secure ✅)
- (其他 exception 留 D3-C 完整 enum)

**F-D3B-17 (INFO)**: exception 层级抽样合理. 真违反 catch-all 模式见 Q10.1.

---

## 4. Q10.4 日志记录质量

D3-A Step 4 实测 logs/qmt-data-stderr.log 26 天累计 ~37,440 次 silent WARNING 0 告警 (T0-16). D3-A Step 5 实测 logs/celery-stderr.log "primary source failed" 73 次累计未 escalate (F-D3B-14).

→ **F-D3B-18 (P1)**: 跨服务 silent WARNING 累积 ≥ 100 次无 escalation 是真 fail-loud 违反. 但**静态 grep 无法识别**. 需:
- 运行时 metric counter (沿用 platform_metrics 表, 但 missing F-D3A-1)
- log aggregation tool (Wave 4+ 候选)
- 留 D3-C / 批 2 LL-081 v2 + 候选铁律 X9 ADR

---

## 5. Q10.5 fail-secure default 全审

D3-A 已确认:
- LIVE_TRADING_DISABLED=True default ✅
- OBSERVABILITY_USE_PLATFORM_SDK=True default (但 D3-A Step 1 实测 alert_dedup missing → SDK invoke raise UndefinedTable, 触发 F-D3A-1 P0)

本 D3.10 扩 sample default:
- PMS_ENABLED default (PMS deprecated, 但 settings 仍存)
- PT_TOP_N / PT_INDUSTRY_CAP / PT_SIZE_NEUTRAL_BETA — 真金 ops 参数, 应 ❌ 不应 fail-open
- (留 D3-C 完整 enum)

**F-D3B-19 (INFO)**: 真金 fail-secure default 抽样合规. 沿用 D3-A E5 实测 LIVE_TRADING_DISABLED=True 多重保护.

---

## 6. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3B-15 | 静态 grep 0 真 silent except: pass 违反 / 真违反是 logger.warning + 不 raise + 累积无 escalation 模式 (T0-16 案例) | INFO |
| F-D3B-16 | 6 schtask script 已硬化 (LL-068), pt_audit.py 缺 2 项 (Step 3 已识), 其他未迁 script 硬化状态待 D3-C 调查 | INFO |
| F-D3B-17 | exception 层级抽样合理 | INFO |
| F-D3B-18 | 跨服务 silent WARNING 累积 ≥ 100 次无 escalation = 真 fail-loud 违反, 但静态 grep 无法识 (T0-16/F-D3B-14 案例) | **P1** |
| F-D3B-19 | 真金 fail-secure default 抽样合规 | INFO |

---

## 7. 处置建议

- **F-D3B-18 P1**: 候选铁律 X9 ADR (LL-081 v2): "silent WARNING 累积 ≥ N 次必 escalate to risk_event_log + alert"
- **D3-C 整合**: 完整 grep schtask script 硬化状态 + exception class enum + fail-secure default enum
- **批 2 写代码阶段**: T0-16 qmt_data_service fail-loud 改造 (1 例 case study 立模板)
