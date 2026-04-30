# 现状快照 — LLM cost + 资源 真测 (类 14)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 2 WI 3 / snapshot/14
**Date**: 2026-05-01
**Type**: 描述性 + 真测 disk / RAM / GPU + LLM cost candidate

---

## §1 Disk 真测 (CC 5-01 实测)

实测命令:
```bash
du -sh D:/pgdata16
du -sh D:/quantmind-v2
du -sh D:/quantmind-v2/.venv
```

**真值** (背景任务 partial output):
- **D:/pgdata16 = 225 GB** (实测)
- D:/quantmind-v2 = (背景任务超时未取得真值)
- D:/quantmind-v2/.venv = (同上)

**🔴 finding**:
- **F-D78-81 [P2]** **D:/pgdata16 真测 = 225 GB**, sprint period sustained CLAUDE.md / sprint state 多次写 "60+ GB" / "172 GB" / "159 GB" / etc 数字漂移. sprint period sustained 沉淀 sprint state 数字累计实测 (4-29 ~155 GB → 5-01 真值 225 GB ≈ +70 GB 跨日, candidate disk 增长真趋势 0 sustained 监控)

---

## §2 RAM 真测 (CC 扩 — 32GB 上限)

(本审查未跑 wmic / Get-Process Memory 真测全 服务 RAM 占用. sprint period sustained CLAUDE.md "32GB 内存硬约束" sustained sustained.)

候选 finding:
- F-D78-82 [P2] RAM 真测 (32GB / Servy 4 服务 + PG / 等) 0 sustained 监控, candidate OOM 历史 (2026-04-03 PG OOM) 复发 detection 0 sustained

---

## §3 GPU 真利用率 (CC 扩 D11 / framework_self_audit §3.1)

实测真值:
- CLAUDE.md sustained "RTX 5070 12GB(PyTorch cu128)" sustained sustained
- 历史: GPU 6.2x 加速 sprint period sustained sustained
- 真期间 GPU 真利用率 0 sustained 监控

候选 finding:
- F-D78-83 [P2] GPU (RTX 5070 12GB cu128) 真利用率 0 sustained 监控, sprint period sustained "GPU 6.2x 加速" sustained sustained vs 真期间利用率 candidate 验证 (Phase 3D ML Synthesis NO-GO / Phase 3E 微结构等是否真用 GPU)

---

## §4 LLM cost 累计 (沿用 blind_spots/04 §1.6 F-D78-40)

(本审查未深查 Anthropic API 真累计 token cost. F-D78-40 沿用.)

---

## §5 跨服务资源争用 (沿用 CLAUDE.md §并发限制)

CLAUDE.md sustained sustained:
- 32GB 内存硬约束
- 最多同时运行 2 个加载全量价格数据的 Python 进程
- PG shared_buffers=2GB 固定开销
- 因子计算 / 回测 / 等重数据任务必须串行或最多 2 并发

(本审查未跑 实测真测多进程并发. 沿用 sprint period sustained sustained 铁律 9 sustained.)

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-81** | **P2** | D:/pgdata16 真测 225 GB, sprint period sustained CLAUDE.md "60+/172/159 GB" 数字漂移, sprint period 沉淀 sprint state 累计实测但 5-01 真值 225 GB (+70 GB 跨日), disk 增长趋势 0 sustained 监控 |
| F-D78-82 | P2 | RAM 真测 0 sustained 监控, OOM 复发 detection 0 sustained |
| F-D78-83 | P2 | GPU (RTX 5070 12GB cu128) 真利用率 0 sustained 监控 |
| F-D78-40 (复) | P2 | LLM cost 累计真值未深查 |

---

**文档结束**.
