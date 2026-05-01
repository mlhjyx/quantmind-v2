# Operations Review — Servy 4 service 真状态

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / operations/08
**Date**: 2026-05-01
**Type**: 评判性 + Servy 4 service 真测

---

## §1 真测 (CC 5-01 servy-cli status 实测)

实测 cmd:
```
D:/tools/Servy/servy-cli.exe status -n QuantMind-FastAPI
D:/tools/Servy/servy-cli.exe status -n QuantMind-Celery
D:/tools/Servy/servy-cli.exe status -n QuantMind-CeleryBeat
D:/tools/Servy/servy-cli.exe status -n QuantMind-QMTData
```

**真值**:
| 服务 | status |
|---|---|
| QuantMind-FastAPI | **Service status: Running** ✅ |
| QuantMind-Celery | **Service status: Running** ✅ |
| QuantMind-CeleryBeat | **Service status: Running** ✅ |
| QuantMind-QMTData | **Service status: Running** ✅ |

Servy CLI version: **7.6.0+60664ef2dd081071b983b3b337dc81d7b6ef9795**

---

## §2 真生产意义 sustained verify

**真证据**: 4 service 全 Running ✅. 沿用 sprint state Session 35 LL-074 ServicesHealthCheck 验证 sustained 真生产 sustained 4 service 全 RUNNING 真 verify.

但**真深 verify**: ServicesHealthCheck (sustained services_healthcheck.log) 5-01 15:30 实测:
```
Status: degraded
  QuantMind-FastAPI: RUNNING
  QuantMind-Celery: RUNNING
  QuantMind-CeleryBeat: RUNNING
  QuantMind-QMTData: RUNNING
  Beat heartbeat: 1.9min ago (fresh)
Alert decision: send=True reason=no prior alert timestamp
[AlertRouter] sent key=services_healthcheck:degraded:2026-05-01 severity=p0 suppress=5min
ServicesHealthCheck: DEGRADED + ALERTED:
  ['redis:portfolio:nav STALE (key 不存在 (QMTData 未运行 OR LL-081 SETEX expire))']
```

**真测**: 4 service 真 Running ✅ **but** redis portfolio:nav STALE alert sustained! sustained F-D78-236 sustained "qmt-data-stdout 0 byte 28 day" 同源 — QMTData 真在 Running 但**真 SETEX redis:portfolio:nav** sustained 失效 = 真**部分 silent failure** sustained (service Running ≠ functional).

**🔴 finding**:
- **F-D78-245 [P1]** Servy 4 service 全 RUNNING ✅ **but** ServicesHealthCheck 5-01 15:30 真 DEGRADED + ALERTED `redis:portfolio:nav STALE`, 真证据 QMTData service 在 Running 但**真 SETEX 失效** sustained — 真生产 service status ≠ functional sustained 真案例 (沿用 LL-081 sustained "service Running ≠ data 通畅" 真证据 reverify), sustained sustained F-D78-236 同源加深

---

## §3 ServicesHealthCheck dedup 真测

**实测真证据 (5-01 15:30 / 15:45 / 16:00)**:
- 15:30: send=True (no prior timestamp) → DingTalk sent ✅
- 15:45: send=False (dedup, 15min < 60min, same failures) → silent dedup ✅
- 16:00: 再次启动 ✅

**真值**: alert dedup 60min sustained ✅ enforce sustained, sustained sprint period sustained PR #100/101/102/103 LL-081 闭合 sustained verify ✅.

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-245** | **P1** | Servy 4 service 全 RUNNING ✅ but redis:portfolio:nav STALE sustained = service status ≠ functional |

---

**文档结束**.
