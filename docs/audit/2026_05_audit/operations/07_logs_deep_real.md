# Operations Review — logs/ 全文件 deep 真测

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / operations/07
**Date**: 2026-05-01
**Type**: 评判性 + logs/ 真读 deep + risk-health ImportError 真发现

---

## §1 logs/ 真盘点 (CC 5-01 ls -lh 实测)

实测 cmd: `ls -lh D:/quantmind-v2/logs/ | head -50`

**真值**: 47 files / ~52 MB total. 重点文件:

| 文件 | size | 末次 modified | 含义 |
|---|---|---|---|
| **app.log** | 3.4M | 5-01 15:52 | FastAPI app sustained ✅ |
| **fastapi-stderr.log** | 8.9M | 4-30 00:36 | FastAPI stderr (1.5d 未滚动 = 4-30 后没新错? OR 已 rotate 过) |
| **qmt-data-stderr.log** | 8.9M | 5-01 15:52 | QMTData sustained ✅ (但 stderr 累 8.9M = 长期 stderr 输出, 待深查) |
| **qmt-data-stdout.log** | 0 (空) | 4-3 18:47 | **真证据 sustained F-D78-? QMTData stdout 真无输出 sustained** |
| **celery-beat-stderr.log** | 1.1M | 5-01 16:06 | Celery Beat scheduler sustained ✅ |
| **emergency_close_20260429_104354.log** | **14K** | **4-29 10:43** | **Session 44 真 emergency_close 17/18 sell** ✅ |
| **emergency_close_*** (4 早些) | 644~669 bytes | 4-29 10:38-10:41 | 4 次 abort/early-stop sustained 早 attempts |
| **risk_framework_health.log** | 1.5K | 4-30 18:45 | **🔴 sustained ImportError 4-29+4-30 18:45 sustained** |
| services_healthcheck.log | 582K | 5-01 16:00 | LL-074 ServicesHealthCheck sustained ✅ |
| services_healthcheck_state.json | 211 | 5-01 15:45 | dedup state ✅ |
| pt_watchdog.log | 8.6K | 4-30 20:00 | ✅ |
| compute_daily_ic.log | 91K | 4-30 18:00 | ✅ DailyIC schtask sustained |
| compute_ic_rolling.log | 3.3M | 4-30 18:15 | ✅ IcRolling sustained |
| paper_trading.log | 392K | 4-28 16:31 | **3 day stale (4-29 PT 暂停后 0 update)** sustained F-D78-89 加深 |

---

## §2 🔴 重大 finding — risk_framework_health.log ImportError sustained

**真实测内容** (5-01 cat 实测):

```
2026-04-29 18:45:02,203 [ERROR] [risk-health] DingTalk send failed:
ImportError: cannot import name 'get_notification_service' from
'app.services.notification_service' (D:\quantmind-v2\backend\app\services\notification_service.py)

2026-04-30 18:45:01,850 [ERROR] [risk-health] DingTalk send failed (sustained):
ImportError: cannot import name 'get_notification_service' from ...
```

**真根因**:
- `scripts/risk_framework_health_check.py:295` 真 import `from app.services.notification_service import get_notification_service`
- `app/services/notification_service.py` 真**无 get_notification_service** export
- → DingTalk 报警通道 4-29+4-30 sustained 2 次完全 silent (stdout finding 仍写, 但**真告警 0 reach user**)

**真生产意义**: 真 risk-framework health 报警 2 天连续断 + sustained F-D78-115 73 error sustained sustained "alert routing 部分 enforce 但 silent failure cluster 漏告警" 加深

**🔴 finding**:
- **F-D78-235 [P0 治理]** risk_framework_health.log 真 ImportError sustained 2 天 (4-29+4-30 18:45) — get_notification_service 真**不存在** in notification_service.py, DingTalk 真 silent failure sustained 2 days. **真告警通道断**, sustained F-D78-115 + LL-094 sustained "RiskFrameworkHealth 自身 silent failure" sustained 真 root cause 真证据 (sustained sprint period sustained "Beat dead-man's-switch 18:45" PR #145+146 自身 broken).
- **F-D78-236 [P1]** qmt-data-stdout.log 真**0 byte sustained 4-3 至今 ~28 day**, 仅 stderr 8.9M 增长. **QMTData service 真 stdout 0 输出 sustained 28 day** (sustained F-D78-? stdout suppress sustained, 沿用 LL-081 sustained "qmt_data_service 26 day silent skip" 真证据 28 day 加深).
- **F-D78-237 [P2]** paper_trading.log 真**4-28 16:31 后 0 update sustained 3 day** (sustained F-D78-89 PT 4-29 暂停后 0 paper trade sustained 真证据).

---

## §3 logs/ 总数据真测

实测 du -sh logs/ ~52 MB / 47 files. 大头 fastapi-stderr (8.9M) + qmt-data-stderr (8.9M) + app.log (3.4M) + compute_ic_rolling (3.3M) + factor_lifecycle (458K) + ServicesHealthCheck (582K).

**finding**:
- F-D78-238 [P3] logs 真无 rotate strategy 真证据, qmt-data-stderr 8.9M sustained 28 day = 永远累积无 rotate (sustained F-D78-? log rotate 配置缺真根因 candidate)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-235** | **P0 治理** | risk_framework_health.log ImportError sustained 2 天, get_notification_service 不存, 真告警通道断 sustained |
| F-D78-236 | P1 | qmt-data-stdout.log 0 byte 28 day, QMTData stdout 真 0 输出 sustained |
| F-D78-237 | P2 | paper_trading.log 4-28 后 0 update 3 day, sustained F-D78-89 PT 暂停加深 |
| F-D78-238 | P3 | logs 真无 rotate strategy, qmt-data-stderr 8.9M 永远累 |

---

**文档结束**.
