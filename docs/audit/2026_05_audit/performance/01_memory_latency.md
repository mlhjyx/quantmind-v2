# Performance Review — Memory + Latency + Throughput

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 4 / performance/01
**Type**: 评判性 + APM (Memory profiling + Latency / Throughput)

---

## §1 Memory profiling 真测

### 1.1 32GB RAM sustained 上限

实测 sprint period sustained sustained:
- 32GB DDR5 (R9-9900X3D)
- PG shared_buffers=2GB 固定开销
- 因子计算 / 回测 max 2 并发 (铁律 9 sustained)

实测真值 (本审查 partial):
- D:/pgdata16 = 225 GB disk (snapshot/14 §1) — disk 增长但 RAM 真占用 0 sustained 监控 (F-D78-82)

### 1.2 OOM 历史 (2026-04-03 PG OOM)

实测 sprint period sustained:
- 2026-04-03 PG OOM 事件 sustained (CLAUDE.md §并发限制)
- 复发 detection 0 sustained (F-D78-82 同源)

candidate finding:
- F-D78-100 [P2] OOM 复发 detection + memory monitoring 0 sustained 自动化, 沿用 sprint period sustained 铁律 9 sustained sustained 但 enforcement 真测 candidate

---

## §2 Latency critical paths

实测 sprint period sustained sustained:
- factor_engine: Phase C F31 sustained sustained (factor_engine.py 2049→416 行)
- backtest Phase A: 841s(12yr) → ~15s (sprint period sustained sustained 60x 加速)
- L1 实时 (PMSRule 14:30 Beat) PAUSED 4-29 后

candidate finding:
- F-D78-101 [P3] latency critical paths 真 last-measure timestamp 0 sustained sustained (sprint period sustained "841s→15s" sustained 但 真期间 latency 漂移 detection 0 sustained)

---

## §3 Throughput

实测真值 (本审查 partial):
- Tushare API: schtask 17:30 daily DailyMoneyflow sustained ✅
- DB write: DataPipeline (铁律 17 sustained)
- Parquet read: 1000x 加速 sprint period sustained sustained

candidate finding:
- F-D78-102 [P3] throughput 真测 (Tushare API rate limit / DB write throughput / Parquet read 真 measure) 0 sustained sustained

---

## §4 资源争用 + 并发约束 (沿用 CLAUDE.md §并发限制)

实测 sprint period sustained sustained 铁律 9 sustained sustained:
- 最多 2 并发 加载全量价格数据 Python 进程
- 32GB 上限
- 因子计算 / 回测 串行或 max 2 并发

candidate finding:
- F-D78-103 [P3] 真生产并发约束 enforce 度 (CC 实测 多进程并发) 0 sustained sustained

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-100 | P2 | OOM 复发 detection + memory monitoring 0 sustained 自动化 (沿用 F-D78-82) |
| F-D78-101 | P3 | latency critical paths 真 last-measure timestamp 0 sustained |
| F-D78-102 | P3 | throughput 真测 0 sustained sustained |
| F-D78-103 | P3 | 真生产并发约束 enforce 度 0 sustained sustained |

---

**文档结束**.
