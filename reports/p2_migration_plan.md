# P2 SQL 迁移方案 — 13 production 文件 → FactorCache

**Date**: 2026-04-17
**Scope**: 将 13 production 文件中的 `SELECT ... FROM factor_values` 迁移到 FactorCache / DataOrchestrator，将 `§5.4` 统一化率从 25% → 95%+
**参考**: `reports/p2_sql_audit.md`（审计）, `backend/data/factor_cache.py`（目标 API）

## 目标 API 速查

```python
from backend.data.factor_cache import FactorCache

cache = FactorCache()
df = cache.load(
    factor_name="turnover_mean_20",
    column="neutral_value",          # raw_value / neutral_value / zscore
    start=date(2021, 1, 1),
    end=date(2025, 12, 31),
    conn=conn,                       # 用于增量刷新 DB check
    auto_refresh=True,               # 默认 True，落后 > N 天会自动 refresh
)
# 返回: columns=[code, trade_date, value], dtype=[str, datetime64, float64]
```

**注意**: FactorCache 当前只支持**单因子 + 单 column**。跨因子/跨 column 需循环调用。

## SQL 模式分类

| Pattern | 频次 | 迁移路径 | 难度 |
|---|---|---|---|
| A. 单因子长区间 (`factor_name=X AND date BETWEEN`) | 8 处 | `FactorCache.load(factor, column, start, end)` | 🟢 直接替换 |
| B. 截面快照 (`trade_date=X AND factor_name IN (...)`) | 4 处 | 循环 `cache.load` 取 tail / 新增 `get_cross_section` | 🟡 需小工具函数 |
| C. 因子列表 (`DISTINCT factor_name`) | 5 处 | 读 `factor_registry` (首选) 或保留 DB 查询（查询本身轻） | 🟢 轻量 |
| D. MAX(trade_date) | 1 处 | FactorCache `_meta.json` 或保留 DB 查询 | 🟢 轻量 |
| E. JOIN registry (async) | 1 处 | 改 sync + 两次查询 | 🟠 需重写 |

---

## 文件级迁移计划

### 1. `backend/engines/ml_engine.py` L715/L725 ⭐ 顶优

**现况:**
```python
cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")  # Pattern C
feature_names = [r[0] for r in cur.fetchall()]
...
sql_factors = f"""SELECT code, trade_date, factor_name, neutral_value
                  FROM factor_values
                  WHERE trade_date BETWEEN %s AND %s
                    AND factor_name IN ({placeholders})
                    AND neutral_value IS NOT NULL"""           # Pattern A (多因子)
```

**迁移:**
```python
from backend.data.factor_cache import FactorCache

# Pattern C: 优先读 factor_registry (一致性), 降级直连 DB
if not feature_names:
    cur.execute("SELECT name FROM factor_registry WHERE status IN ('active','warning') ORDER BY name")
    feature_names = [r[0] for r in cur.fetchall()]
    if not feature_names:
        cur.execute("SELECT DISTINCT factor_name FROM factor_values ORDER BY factor_name")
        feature_names = [r[0] for r in cur.fetchall()]

# Pattern A (多因子): 循环 cache.load + concat
cache = FactorCache()
dfs = []
for f in feature_names:
    df = cache.load(f, column="neutral_value", start=start_date, end=end_date, conn=conn)
    if not df.empty:
        df["factor_name"] = f
        dfs.append(df)
factor_df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
```

**风险 🟡**:
- ML training 数据量大 (101 因子 × 5 年), cache 首次加载会 refresh 全量 → 40GB+ Parquet IO
- 当前单次大 SQL 有数据库聚合优势, 改循环后可能变慢（需 benchmark）
- 建议: 保留 fallback 路径（若 cache miss 太多则回退 SQL）

**单测**: 确认 feature_names 自动发现 + factor_df shape 与旧实现一致
**Effort**: 2-3h

---

### 2. `backend/engines/factor_analyzer.py` L219/L244/L434 ⭐ 顶优

**现况:** 3 处查询
- L219: Pattern B — 跨因子截面 corr matrix (单日, N 因子)
- L244: Pattern A — 单因子区间
- L434: Pattern B — 单日全量截面 (corr vs 所有其他)

**迁移:**
```python
# L244 Pattern A: 直接替换
cache = FactorCache()
df = cache.load(factor_name, "neutral_value", start_date, end_date, conn=self.conn)

# L219 Pattern B: 循环取单日 tail
dfs = []
for f in factor_names:
    df = cache.load(f, "neutral_value", start=trade_date, end=trade_date, conn=self.conn)
    if not df.empty:
        df["factor_name"] = f
        dfs.append(df[["code", "factor_name", "value"]].rename(columns={"value": "neutral_value"}))
wide = pd.concat(dfs) if dfs else pd.DataFrame()

# L434 Pattern B (全因子截面): 读 factor_registry 得全量因子列表 → 循环
# 或保留 DB 查询 — 单日查询即便全表扫描也很快 (<1s with index)
```

**风险 🟢**:
- factor_analyzer 非热路径 (研究用), IC corr matrix 每次重算可接受 cache miss
- L434 单日全因子查询保留 DB 方式更高效（cache 需 101 次 load）→ **建议部分保留**

**建议**:
- L244 必须迁移（区间查询大, cache 收益明显）
- L219 迁移
- L434 **保留 DB 查询** + 在 audit 报告 🟢 Sanctioned 里加注释说明"单日 cross-section 查询保留"

**Effort**: 2h

---

### 3. `backend/engines/mining/pipeline_utils.py` L99/L125/L186 ⭐ 顶优

**现况:** 3 处
- L99: Pattern C — `DISTINCT factor_name`
- L125: Pattern A — 单因子全量 neutral_value
- L186: Pattern E — **asyncpg + JOIN factor_registry** 取 latest date active 因子

**迁移:**
```python
# L99 Pattern C: 读 factor_registry 优先
# L125 Pattern A: cache.load
# L186 Pattern E: 改 sync + 两步查询
#   Step 1: SELECT name FROM factor_registry WHERE status='active'
#   Step 2: 对每个 name, cache.load(f, "neutral_value", start=latest_date, end=latest_date)
```

**风险 🟠**:
- L186 当前是 asyncpg 路径（legacy async），改 sync 可能影响 GP pipeline 调用链
- 需先确认 GP 是否仍依赖 asyncpg（检查调用方）
- 建议: 保持 async 接口签名, 内部改 `asyncio.to_thread` 跑 sync cache.load

**Effort**: 3h（含 GP 集成测试）

---

### 4. `backend/engines/factor_profiler.py` L538/L556/L838/L898/L908 🔥 Loop query

**现况:** 关键问题在 **L556/L908 loop 内 read_sql**（每因子一次 DB round-trip）

```python
# L553-560 (跨因子 corr 循环内):
for other in all_factor_names:
    other_fv = pd.read_sql(
        "SELECT code, neutral_value FROM factor_values "
        "WHERE factor_name=%s AND trade_date=%s ...", ...)
```

**迁移:**
```python
# 预加载 last_d 当日所有因子的截面 (一次 cache 循环)
cache = FactorCache()
snapshot = {}
for f in all_factor_names:
    df = cache.load(f, "neutral_value", start=last_d, end=last_d, conn=conn)
    if not df.empty:
        snapshot[f] = dict(zip(df["code"], df["value"]))

# 循环内改读 dict (O(1) lookup 替代 DB query)
for other in all_factor_names:
    other_vals = snapshot.get(other, {})
    # ... corr 计算
```

**风险 🟢**:
- factor_profiler 目前按因子串行跑, 无并发
- snapshot dict 内存占用: 101 因子 × 5K 股票 × float = ~4MB, 可接受
- **性能提升显著**: N² DB query → N cache load + O(1) lookup

**Effort**: 2h

---

### 5. `scripts/batch_gate.py` L99 / `batch_gate_v2.py` L109/L402

**现况:**
- batch_gate L99: Pattern C DISTINCT
- batch_gate_v2 L109: Pattern A 单因子全量 (含 raw_value + neutral_value)
- batch_gate_v2 L402: Pattern C

**迁移:**
```python
# L109 需要两个 column, 循环两次
cache = FactorCache()
df_raw = cache.load(f, "raw_value", start, end, conn)
df_neu = cache.load(f, "neutral_value", start, end, conn)
df = df_raw.merge(df_neu, on=["code", "trade_date"], suffixes=("_raw", "_neu"))
```

**风险 🟢**: 批量 gate 非热路径，可接受 merge 开销
**Effort**: 1.5h

---

### 6. `backend/scripts/compute_factor_ic.py` + `scripts/fast_ic_recompute.py` L115/L219

**现况:** Pattern A + Pattern C 组合, 标准迁移
**迁移:** 参考 #5 模板
**风险 🟢**: 纯批处理脚本，已有降级路径
**Effort**: 1h each

---

### 7. Research scripts (phase3b_factor_characteristics, phase3e_noise_robustness, neutralize_minute_factors_fast)

**迁移优先级** 🟡 较低：
- phase3b_factor_characteristics: 活跃研究脚本，值得迁移
- phase3e_noise_robustness: 活跃 G_robust 工具，值得迁移
- neutralize_minute_factors_fast: 已有 `scripts/data/neutralize_minute_batch.py` 替代，建议标 DEPRECATED 而非迁移

**Effort**: 1-2h each

---

## 建议迁移顺序（基于风险 + 收益）

| 优先级 | 文件 | 收益 | 风险 | Effort |
|---|---|---|---|---|
| P0 | `factor_profiler.py` L556/L908 | **消除 N² DB loop** | 🟢 | 2h |
| P1 | `ml_engine.py` L725 | ML 训练大区间, 100 因子 | 🟡 benchmark | 2-3h |
| P1 | `pipeline_utils.py` L186 | GP 关键路径 | 🟠 async→sync | 3h |
| P2 | `factor_analyzer.py` L244 | IC 分析 | 🟢 | 2h |
| P2 | `batch_gate_v2.py` L109 | Gate 批处理 | 🟢 | 1.5h |
| P3 | `fast_ic_recompute.py` / `compute_factor_ic.py` | IC 重算工具 | 🟢 | 1h each |
| P3 | Research scripts | 研究工具 | 🟢 | 1-2h each |

**保留不迁移 (建议新增 🟢 Sanctioned 分类):**
- `factor_analyzer.py` L434 — 单日全因子截面，DB 查询 <1s，cache N 次 load 反而慢
- 所有 Pattern C DISTINCT 查询 — DB 查询本身 <50ms，cache 无收益

---

## 前置工作（迁移前必须做）

1. **benchmark FactorCache 首次 refresh 成本**
   - 101 因子 × 12 年 raw+neutral = ~20GB Parquet
   - 首次构建时间 / 磁盘占用 / DB 负载
   - 决定: 是否需要先离线跑 cache warmup

2. **factor_registry 回填**（依赖任务 A1）
   - 不然 Pattern C 迁移到 registry 路径会失效
   - 当前 registry 只有 5 行

3. **DataOrchestrator API 扩展** (可选)
   - 新增 `get_cross_section(trade_date, factor_names)` 封装 Pattern B
   - 避免每个调用方重复写循环

---

## 迁移后验证命令

```bash
# §5.4 统一化率验证 (期望 <3 违规)
grep -rn "SELECT.*FROM factor_values" backend scripts --include='*.py' \
    | grep -v test_ | grep -v archive | grep -v factor_cache.py \
    | grep -v factor_repository.py | grep -v data_orchestrator.py \
    | grep -v fast_neutralize.py | wc -l

# 回归测试
cd backend && python -m pytest tests/ -q
```

---

## 风险总览

| 风险 | 影响面 | 缓解 |
|---|---|---|
| FactorCache 循环 vs SQL IN 性能回退 | ml_engine, batch_gate | 先 benchmark, 必要时 fallback |
| asyncpg → sync 改动 | GP pipeline | 保留 async 签名, 内部 to_thread |
| factor_registry 空表导致 Pattern C 回退 | 多处 | 迁移前回填, 加降级逻辑 |
| Parquet cache 占用 ~20GB | 磁盘 | 已预留 20GB cap (max_total_size_gb) |
| 迁移后 Cache miss 风暴 | 首次 ML 训练 | 离线 warmup 全部因子 |

## 建议不一次性全迁移

**分 2 sprint:**
- **Sprint 1** (现在, 5-6h): P0 factor_profiler + P1 ml_engine — 解决性能瓶颈 + 核心路径统一
- **Sprint 2** (GP 空闲期, 10h): P1 pipeline_utils (async→sync 重写) + P2/P3 批处理脚本

不建议在 PT 运行期间迁移 `pipeline_utils.py`（GP 核心路径，改动风险高）。
