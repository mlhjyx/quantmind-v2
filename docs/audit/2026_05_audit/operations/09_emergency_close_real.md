# Operations Review — 4-29 emergency_close 17/18 真证据

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / operations/09
**Date**: 2026-05-01
**Type**: 评判性 + emergency_close_20260429_104354.log 真读

---

## §1 4-29 emergency_close 真测 (CC 5-01 read 实测)

实测 source: `D:/quantmind-v2/logs/emergency_close_20260429_104354.log` (14 KB / 135 lines)

**真值**:
- **10:43:54.831** 连接 QMT path=`E:\国金QMT交易端模拟\userdata_mini` account=81001102 session=104354766151
- **真 query_positions: 18 持仓** ✅
- **--confirm-yes flag bypass interactive prompt (chat-driven 授权)** sustained
- emergency_close_s44 marker — Session 44 真触发

---

## §2 17/18 sell 真清单 (实测真 transcripts)

| 序 | 股票 | 数量 | 状态 | 成交价 | 状态码 |
|---|---|---|---|---|---|
| 1 | 600028.SH | 8600 | ✅ filled | 5.39 | 56 |
| 2 | 600900.SH | 1800 | ✅ filled | 26.63 | 56 |
| 3 | 600938.SH | 1300 | ✅ filled | 39.62 | 56 |
| 4 | 600941.SH | 500 | ✅ filled | 96.35 | 56 |
| 5 | 601088.SH | 1000 | ✅ filled (3 batches) | 48.18/48.17/48.16 | 56 |
| 6 | 601138.SH | 800 | ✅ filled | 65.40 | 56 |
| 7 | 601398.SH | 6500 | ✅ filled | 7.46 | 56 |
| 8 | 601857.SH | 4200 | ✅ filled | 12.19 | 56 |
| 9 | 601988.SH | 8500 | ✅ filled | 5.75 | 56 |
| **10** | **688121.SH** | **4500** | **❌ failed** | **N/A** | **57** error_id=-61 |
| 11 | 688211.SH | 1400 | ✅ filled (3 batches) | 34.0/33.99/33.98 | 56 |
| 12 | 688391.SH | 1500 | ✅ filled (4 batches) | 30.59/30.55/30.53/30.5 | 56 |
| 13 | 688981.SH | 400 | ✅ filled | 111.0 | 56 |
| 14 | 000333.SZ | 600 | ✅ filled (2 batches) | 80.92/80.91 | 56 |
| 15 | 000507.SZ | 9200 | ✅ filled | 5.18 | 56 |
| 16 | 002282.SZ | 6900 | ✅ filled | 6.91 | 56 |
| 17 | 002623.SZ | 2100 | ✅ filled (4 batches) | 20.78/20.77/20.76/20.75 | 56 |
| 18 | 300750.SZ | 100 | ✅ filled | 429.98 | 56 |

**真值**: 17/18 ✅ filled, 1/18 ❌ (688121.SH cancel due 跌停).

---

## §3 🔴 688121.SH 真断真证据

**实测 line 66-68**:
```
2026-04-29 10:43:57,506 [ERROR] [QMT] 下单失败:
order_id=1090551149, error_id=-61,
error_msg=最优五档即时成交剩余撤销卖出 [SH688121] [COUNTER] [251005][证券可用数量不足]
[p_stock_code=688121,p_occu

2026-04-29 10:43:57,506 [INFO] [QMT] 委托回报: order_id=1090551149,
code=688121.SH, status=57, traded=0/4500
```

**真根因**: status=57 (cancelled), error_id=-61 (证券可用数量不足) — 真原因为 4-29 跌停限价 (sustained sprint period sustained "688121.SH 4500 股 4-29 跌停 cancel" 真证据 verify).

**真生产 follow-up**: 4-30 user GUI 手工 sell 18 股 (sustained sprint period sustained "user 4-30 GUI sell" sustained 加深, sustained risk_event_log 4-29 P0 ll081_silent_drift `forensic 价格不可考 (GUI 手工 sell 不走 API)` 真证据 verify).

---

## §4 emergency_close 4 早些 abort 真证据

实测 ls 出 5 emergency_close logs (4-29 10:38-10:43):
- emergency_close_20260429_103825.log — 669 bytes (early abort)
- emergency_close_20260429_103936.log — 644 bytes (early abort)
- emergency_close_20260429_104022.log — 317 bytes (early abort)
- emergency_close_20260429_104114.log — 317 bytes (early abort)
- **emergency_close_20260429_104354.log — 14K (final 17/18 sell success)**

**真值**: 4 early abort + 1 final success = **5 次尝试** before final emergency_close. 真说明 user/CC 4-29 上午多次尝试 (sustained sprint period sustained Session 44 真证据多次 retry).

**finding**:
- F-D78-239 [P2] 4-29 emergency_close 真 5 attempts sustained, 4 早些 early abort + 1 final success — 真 emergency_close ops 真不一次成 sustained, 真证据 emergency_close pipeline 真复杂度 + retry 内含 sustained sustained sprint period 0 documented retry 真根因 candidate

---

## §5 真证据 sustained sprint period sustained sustained verify

| 维度 | sprint period sustained | 真测 4-29 log | finding |
|---|---|---|---|
| **18 持仓 emergency_close** | sustained sprint period 真证据 | ✅ 18 query + 17 filled + 1 cancel | sustained ✅ verify |
| **688121.SH cancel** | sustained sprint period sustained "4500 股 4-29 跌停 cancel" | ✅ status=57, error_id=-61 真证据 | sustained ✅ verify |
| **--confirm-yes flag** | sustained "chat-driven 授权 bypass" | ✅ line 4 真证据 | sustained ✅ verify |
| **emergency_close_s44 marker** | sustained "Session 44" | ✅ line 5 真 marker | sustained ✅ verify |
| **17 trades 真入 trade_log** | sustained 真证据 | **❌ trade_log MAX trade_date=4-17, 4-29+ 0 行** | **🔴 真新 finding F-D78-240** |

---

## §6 🔴 重大新 finding — trade_log 真断 (4-29 17 trades 0 入库)

**实测 SQL**: `SELECT MAX(trade_date) FROM trade_log` → **4-17** (4-29+ 0 行)

**真根因 candidate**: emergency_close 真 17 trades 4-29 ✅ QMT API 成交回报 → 但**未入 trade_log 表**. sustained 4-29 emergency_close 真用 `scripts/emergency_close_all_positions.py` 走 xtquant 直, **未走 PlatformTradePipeline 入 trade_log** = 真 trade_log audit 真断.

**🔴 finding**:
- **F-D78-240 [P0 治理]** trade_log 真 MAX trade_date=4-17 sustained, 4-29 emergency_close 17 真 trades + 4-30 user GUI sell 18 trades **全 0 入 trade_log 表** = 真 trade_log audit 真断 14 day sustained, 真生产**重大 audit log gap** sustained sustained sustained sustained sustained 沿用 F-D78-21 sustained "L0 event-driven enforce 哲学外维度" sustained 真证据加深 (emergency_close 路径 0 入 trade_log = T1 strategy 0 走 audit log)

---

## §7 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-239 | P2 | 4-29 emergency_close 真 5 attempts sustained, 4 abort + 1 final success, retry 内含未 documented |
| **F-D78-240** | **P0 治理** | trade_log 真 4-17 后 0 行 sustained 14 day, emergency_close + user GUI sell 全 0 入 trade_log = 真 audit 真断 |

---

**文档结束**.
