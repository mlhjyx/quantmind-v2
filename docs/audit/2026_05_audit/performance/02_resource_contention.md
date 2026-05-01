# Performance Review — 资源争用 + 并发约束

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 5 WI 4 / performance/02
**Date**: 2026-05-01
**Type**: 评判性 + 资源争用真深查 (sustained performance/01 + CLAUDE.md §并发限制)

---

## §1 32GB RAM 上限 + 并发约束 (CLAUDE.md sustained)

实测 sprint period sustained sustained:
- 32GB DDR5 (R9-9900X3D)
- PG shared_buffers=2GB 固定开销
- 因子计算 / 回测 max 2 并发 (铁律 9 sustained sustained sustained)
- 2026-04-03 PG OOM 教训 (CLAUDE.md sustained §并发限制)

---

## §2 真生产并发 真测

实测 sprint period sustained sustained:
- Servy 4 服务 sustained sustained Running (E3 sustained)
- Celery worker --pool=solo (CLAUDE.md sustained sustained "Solo executor 单进程")
- intraday_risk_check 5min 周期 sustained sustained 73 error/7 day (F-D78-115 P0 治理 sustained)
- DB active backend = 0 (E2 sustained, 真 0 sustained 并发争用)

**真测 finding** (sustained):
- F-D78-103 (复) [P3] 真生产并发约束 enforce 度 (CC 实测多进程并发) 0 sustained sustained 度量

---

## §3 GPU 资源争用

实测 sprint period sustained sustained:
- RTX 5070 12GB cu128 sustained sustained
- 真利用率 0 sustained sustained 监控 (F-D78-83 P2 sustained snapshot/14 §3)
- Phase 3D ML / Phase 3E 微结构 真 GPU usage 0 sustained sustained 度量

候选 finding:
- F-D78-189 [P3] GPU 资源争用真测 0 sustained sustained 度量, sprint period sustained "GPU 6.2x 加速" sustained sustained 但 真期间 utilization 真测 candidate

---

## §4 DB 资源 (TimescaleDB hypertable + chunks)

实测 sprint period sustained sustained:
- D:/pgdata16 = **225 GB** 真测 (snapshot/14 §1 F-D78-81 P2 sustained sustained)
- TimescaleDB hypertable 真 chunks 200+ (snapshot/02 §1.3 F-D78-9 sustained sustained)
- 跨表 join 性能 0 sustained sustained 度量 (F-D78-96 P2 sustained data/01 §2)

候选 finding:
- F-D78-190 [P3] TimescaleDB hypertable + chunks 真 query latency 0 sustained sustained 度量 (sprint period sustained sustained "TimescaleDB chunk exclusion 自动分区" sustained sustained 但 真生效 vs 真 query latency candidate verify)

---

## §5 OOM 复发 detection (sustained F-D78-100 sustained)

详 [`performance/01_memory_latency.md`](01_memory_latency.md) §1.2 sustained F-D78-100 P2

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-189 | P3 | GPU 资源争用真测 0 sustained 度量, GPU 6.2x 加速 sprint period sustained 但真期间 utilization candidate verify |
| F-D78-190 | P3 | TimescaleDB hypertable + chunks 真 query latency 0 sustained 度量 |

---

**文档结束**.
