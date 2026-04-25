# cache/ 目录生命周期文档

> Session 36 (2026-04-25) 整理后建立. 任何新增 cache/ 子目录必须更新本文件 (铁律 22).

## 当前结构 (post-cleanup, ~5GB)

### ✅ 生产/活跃 (保留, 不可删)

| 路径 | 大小 | 用途 | Owner | Lifecycle |
|---|---|---|---|---|
| `baseline/` | 1.3 GB | regression_test.py 锚点 (5yr/12yr factor_data + nav + benchmark) | `scripts/regression_test.py` + `scripts/build_12yr_baseline.py` | 永久, 重建走 build_12yr_baseline |
| `backtest/{YEAR}/` | 814 MB | 12yr WF + 月度回测主 cache (factor_data + price_data + benchmark per year) | `scripts/build_backtest_cache.py` + `engines/backtest/runner.py` | 重建走 `python scripts/build_backtest_cache.py` |
| `factor_values/` | 340 MB | FactorCache 因子 Parquet 快照 (P0-2 DATA_SYSTEM_V1) | `backend/data/factor_cache.py` + `scripts/precompute_cache.py` | 重建走 precompute_cache |
| `neutral_values.parquet` | 271 MB | fast_neutralize 中性化输出 | `engines/fast_neutralize.py` + `factor_profiler.py` | 重建走 fast_neutralize batch |
| `fwd_excess_*.parquet` | ~388 MB (6 files) | forward returns precomputed (1d/5d/10d/20d/60d/120d) | `scripts/monitor_factor_ic.py` + research scripts | 重建走 precompute_cache |
| `close_pivot.parquet` | 49 MB | close 价格 wide-format pivot | `engines/factor_profiler.py` | 重建走 factor_profiler |
| `earnings_sue.parquet` | 2.2 MB | PEAD earnings surprise | research scripts | research artifact |
| `industry_map.parquet` | 44 KB | 行业 mapping (SW1) | research scripts | small reference |
| `csi300_close.parquet` / `csi_monthly.parquet` | < 50 KB | benchmark cache | research scripts | small reference |
| `phase_c_baseline/` | 1.9 GB | Session 16 Phase C F31 重构 baseline (CLOSED but kept for verify_split audit) | `scripts/audit/phase_c_*` | 历史保留 (Phase C audit 闭环参考) |
| `phase3b_checkpoints/` | 424 KB | Phase 3B 32 因子 WF checkpoints (research artifact) | `scripts/research/phase3b_*` | 研究保留, 小 |
| `phase24/`, `phase24_audit/` | < 100 KB | Phase 2.4 audit JSON (research) | `scripts/research/phase24_*` | 研究保留 |
| `phase3b/` | 88 KB | Phase 3B output JSON (research) | `scripts/research/phase3b_*` | 研究保留 |
| `phase3e_ml/` | 8 KB | Phase 3E micro-ML 微 (research) | research | 研究保留 |
| `cache_meta.json` | 4 KB | cache 元信息 | various | 自动维护 |

### ❌ 已清理 (Session 36, NO-GO research artifacts)

| 路径 | 大小 | 删除原因 |
|---|---|---|
| ~~`phase22/`~~ | 81 MB | Phase 2.2 Gate verification NO-GO (CLAUDE.md L502) |
| ~~`phase23/`~~ | 160 KB | Phase 2.3 mcap diagnostic 完成 |
| ~~`phase3e/`~~ | 605 MB | Phase 3E micro-structure WF 0/6 PASS NO-GO |
| ~~`minute_bars/`~~ | 2.8 GB | 老 cache, PG `minute_bars` 表 36GB 已有, 重 build 30 分钟 |
| ~~`ml/*` (keep phase3d_results.json)~~ | 1.8 GB | Phase 3D LightGBM ML Synthesis 4 实验全 FAIL CLOSED |

## 重建命令 (若需要)

```bash
# 全部 backtest cache (12yr 主 cache, ~30-60min)
python scripts/build_backtest_cache.py

# Baseline (regression 锚点, 5yr+12yr, ~10-30min)
python scripts/build_12yr_baseline.py

# Factor values cache + neutral + close_pivot + fwd_excess
python scripts/precompute_cache.py

# Minute bars cache (重 build 走 baostock SDK, MVP 2.1c)
# 已经存 PG minute_bars 表 (190M 行), 一般不需重 build cache/minute_bars
```

## .gitignore 规则

- 大部分 cache 子目录已 .gitignore (见 .gitignore L70-86)
- 例外: `cache/ml/phase3d_results.json` 是 Phase 3D NO-GO 历史 reference, **明确 commit** (`!cache/ml/phase3d_results.json`)
- 新增 cache 子目录默认走 .gitignore, 需同步更新本 README

## 维护周期

- **每 Session 末**: 检查是否有新增 NO-GO research 子目录, 加 .gitignore + 删除
- **每月**: 实测 `du -sh cache/*` 是否有 surprise 增长
- **半年**: 评估 `phase_c_baseline/` 等 closed-but-kept 是否仍需 (可移 docs/archive/)
