# D3.8 性能 / 资源审计 — 2026-04-30

**Scope**: DB 大小 / Redis 利用率 / RAM / 关键路径耗时 / 性能基线 / 磁盘
**0 改动**: 纯 read-only psql + redis-cli + psutil

---

## 1. Q8.1 DB 总大小 + 各表 (实测)

```sql
SELECT pg_size_pretty(pg_database_size('quantmind_v2'));
-- DB total: 224 GB
SELECT relname, pg_size_pretty(pg_total_relation_size(c.oid)) FROM pg_class ... ORDER BY size DESC LIMIT 8;
```

| 表 | 大小 |
|---|---:|
| minute_bars | 36 GB |
| moneyflow_daily | 4363 MB |
| daily_basic | 3805 MB |
| stock_status_daily | 1247 MB |
| margin_detail | 902 MB |
| northbound_holdings | 648 MB |
| balance_sheet | 230 MB |
| cash_flow | 222 MB |

**与历史对比** (memory 痕迹):
- Session 36 末: 263 GB → Sunday maintenance Phase 1 (drop_covering -45GB) + Phase 2 (idx_fv_factor_date 重建 +10GB) 后估 218 GB
- D3-B Session 45 实测 factor_values hypertable = 172 GB (本 D3-C 沿用)
- 当前 224 GB 与预估 ~218 GB 接近 (+6 GB 自然增长 Sunday→今 ~5 天)

→ **F-D3C-18 (INFO)**: DB 224 GB 健康, 与 Sunday maintenance 后基线一致, 自然增长 ~1 GB/day 在预期范围.

---

## 2. Q8.2 Redis 利用率 (实测)

```bash
redis-cli INFO memory | grep -E "used_memory_human|peak|maxmemory"
# used_memory_human: 3.00M
# used_memory_peak_human: 4.00M
# maxmemory_human: 0B  ← 无上限!
redis-cli DBSIZE
# 2970 (与 D3-B 实测 2971 - 1 一致, 无显著变化)
```

| 维度 | 实测 |
|---|---:|
| used_memory | 3 MB |
| used_memory_peak | 4 MB |
| **maxmemory** | **0 (无上限)** |
| DBSIZE | 2970 |

→ **F-D3C-19 (P2)**: Redis 0 maxmemory 限制. 当前 RAM 富裕 (32GB total / 14.4GB available), 短期无风险, 但 burst 场景 (e.g. Beat schedule 误配 + Celery worker 积压 + Streams 无 maxlen 严守) 理论可吞 RAM. 修法: `redis.conf` 加 `maxmemory 1gb` + `maxmemory-policy allkeys-lru` (Wave 5+).

→ **F-D3C-20 (INFO)**: Redis 内存利用率极低 (3 MB / 32 GB = 0.01%), DBSIZE 2970 (其中 2961 是 celery-task-meta-*, D3-B F-D3B-8 已识别). 健康度 ✅.

---

## 3. Q8.3 RAM + 磁盘 + 关键进程 (实测)

```python
psutil.virtual_memory()
# total=31.1GB used=16.7GB pct=53.7% avail=14.4GB
psutil.disk_usage('D:/')
# total=1000GB used=297.3GB pct=29.7% free=702.7GB
```

**Top procs by RSS** (实测):

| 进程 | RSS |
|---|---:|
| claude.exe | 1123.0 MB |
| MemCompression (Windows) | 1050.7 MB |
| claude.exe (#2) | 589.9 MB |
| MsMpEng (Windows Defender) | 589.4 MB |
| chrome.exe | 564.7 MB |
| explorer.exe | 411.5 MB |
| claude.exe (#3) | 358.1 MB |
| miniquote.exe | 281.0 MB |

→ **F-D3C-21 (INFO)**: RAM 53.7% 健康, 14.4 GB available 富裕. 32 GB 硬约束铁律 9 (重数据 max 2 并发) 当前未触发 — 4 Servy 服务 + claude.exe (3 instances) + Chrome + 系统 = ~5 GB, 留 ~14 GB 给重数据任务 (单回测 3-4 GB, max 2 并发安全).

→ **F-D3C-22 (INFO)**: D drive 29.7% used / 702 GB free 健康. DB 224 GB + 项目 65 GB (Session 36 实测) ≈ 290 GB, 与 297 GB used 一致. 磁盘空间充裕.

---

## 4. Q8.4 关键路径耗时 (历史 baseline 沿用)

memory + CLAUDE.md 历史 baseline:
- 数据加载 `_load_shared_data`: 30min(DB) → **1.6s** (Parquet 1000x 加速)
- 因子中性化 `fast_neutralize_batch`: **15因子 / 17.5min** (4-17 后 broadcast 替代 diag 29ms→0.21ms 141x)
- GPU matmul: 6.2x (PyTorch cu128, RTX 5070 12GB)
- Pipeline Step1 三 API 并行: klines+daily_basic+moneyflow
- 回测 Phase A 信号生成: 841s(12yr) → **~15s** (groupby+bisect O(logN))

→ **F-D3C-23 (INFO)**: 关键路径性能基线已优化, 沿用 memory frontmatter 数字. 本 D3-C 不重测 (耗时 15-30 min, 不在 scope).

---

## 5. Q8.5 logs/ 目录大小 + rotation (实测)

```bash
du -sh logs/  # 51 MB
ls -la logs/  # ...
```

**关键发现**:
- 总大小 **51 MB** (低)
- `app.log.1` 10 MB last update **2026-04-04 17:30** (26 天前最后 rotation)
- `app.log` 3.4 MB 仍当前
- `celery-stderr.log` 1.6 MB last update **4-30 14:55** (PR #161 Beat restart 之前的 spam tail)
- `celery-beat-stderr.log` 725 KB last update **4-30 16:52** (本 audit 时点, 活)
- `emergency_close_20260429_*.log` 5 文件 (D3.6 F-D3C-13 真金 case study)
- `data_quality_check.log` 57 KB last update **4-29 18:30** (Sunday DataQualityCheck)

→ **F-D3C-24 (P3)**: app.log rotation 26 天未触发 (4-04 后 0 rotation). RotationSize=100 MB 但 app.log 仅 3.4 MB, 距离触发还远. 但 EnableDateRotation=false (Servy export 实测) → 长期 app.log.1 stale. 修法: 加 weekly rotation cron 或 EnableDateRotation=true.

→ **F-D3C-25 (P0 cross-link D3.6 F-D3C-13)**: emergency_close_20260429_*.log 5 文件是真金 audit 唯一证据, **没**自动入 risk_event_log + 没自动 backup. 修法: 加 audit log archive cron + post-execution risk_event_log 写入 (T0-19 修法范围).

---

## 6. Q8.6 D3-B F-D3B-8 (celery-task-meta 2961 累积) 重新评估

D3-B F-D3B-8 (P3) 称 celery-task-meta-* 2961 keys 累积. 本 D3-C 实测:
- DBSIZE 2970 (vs D3-B 2971, -1)
- 2961 / 2970 = **99.7%** keyspace 都是 celery-task-meta

**性能影响**:
- Redis used_memory 仅 3 MB → 2961 keys 平均 ~1 KB/key, 极小
- DBSIZE 不影响 Redis 查询性能 (hash table O(1))
- celery-task-meta 默认 24h TTL (Celery 内置), 自然清理
- 但实测 2961 累积 → 可能 Celery 配置 result_backend_persistent=True 或 TTL 漂移

→ **F-D3C-26 (P3 cross-link D3-B F-D3B-8)**: celery-task-meta 2961 keys 性能影响 ~0 (3 MB / 32 GB). 修法低优, 留 Wave 5+ 配置审计.

---

## 7. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3C-18 | DB 224 GB 健康, Sunday maintenance 后基线一致 | INFO |
| F-D3C-19 | Redis 0 maxmemory 限制, burst 场景理论风险 | P2 |
| F-D3C-20 | Redis 内存利用率 0.01% (3 MB / 32 GB) 极低 | INFO |
| F-D3C-21 | RAM 53.7% 健康, 14.4 GB available, 铁律 9 max 2 并发安全 | INFO |
| F-D3C-22 | D drive 702 GB free 健康 | INFO |
| F-D3C-23 | 关键路径性能基线沿用 memory + CLAUDE.md | INFO |
| F-D3C-24 | app.log rotation 26 天未触发, 长期 app.log.1 stale | P3 |
| **F-D3C-25** | **emergency_close 4-29 logs 真金 audit 唯一证据, 没自动入 risk_event_log + 没 backup** | **P0 cross-link** |
| F-D3C-26 | celery-task-meta 2961 keys 性能影响 ~0, 修法低优 | P3 cross-link |

---

## 8. 处置建议

- **F-D3C-25 (P0)**: 与 T0-19 一起做 — emergency_close 脚本加 post-execution audit log 写入 + log archive cron
- **F-D3C-19 (P2)**: redis.conf maxmemory 1gb + LRU eviction (Wave 5+)
- **F-D3C-24 (P3)**: Servy import EnableDateRotation=true (~5min) 或 weekly rotation cron
- INFO 留 D3 整合 / Wave 5+

---

## 9. 关联

- T0-19 emergency_close 后 DB sync + audit log (新增, F-D3C-13/25)
- D3-B F-D3B-8 (celery-task-meta 累积, F-D3C-26 cross-link)
- Sunday PG maintenance Session 36 (Phase 1+2)
- 铁律 9 (32 GB RAM 重数据 max 2 并发)
