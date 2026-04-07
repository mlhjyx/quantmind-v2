---
name: quantmind-factor-discovery
description: 自主因子发现pipeline。从学术论文提取alpha因子，自动计算+中性化+IC分析+画像，生成报告。内循环自主，外循环需人确认。
---

# QuantMind Factor Discovery Pipeline

## 触发条件
- 用户要求搜索/发现新因子、过夜跑因子研究、提供论文URL/关键词

## Pipeline流程

### Phase 1: 文献搜索（自动）
- web_search: "alpha factor" "stock selection" "cross-sectional" "A-share"
- 来源: arXiv q-fin > SSRN > 知网
- 提取因子构造公式和经济机制

### Phase 2: 可行性评估（自动）
- 检查所需数据: klines_daily(OHLCV), daily_basic(市值/PE/PB), northbound_holdings, minute_bars(部分)
- 不可用 → 记录到 docs/research-kb/failed/ 并跳过

### Phase 3: 因子计算（自动）
- 写入factor_values表(raw_value), 串行执行(铁律9)
- 数据范围: 2021-01-01 ~ 2025-12-31
- 脚本保存: scripts/research_discovery_<name>.py

### Phase 4: 中性化（自动）
- 调用 fast_neutralize_batch() (backend/engines/fast_neutralize.py)
- Pipeline: MAD 5sigma → WLS行业+市值 → z-score clip +-3

### Phase 5: IC分析+画像（自动）
- IC写入factor_ic_history（铁律11不可跳过）
- forward return从T+1入场
- 跑factor_profiler.profile_factor()

### Phase 6: 质量检查（自动）
- factor_values行数验证(~350万/因子)
- factor_ic_history有记录
- 与现有因子corr > 0.7 → 标注冗余

### Phase 7: 报告+决策（自动生成，人工决策）
- 报告: docs/FACTOR_DISCOVERY_<YYYYMMDD>.md
- IC t>2.5 且 max_corr<0.3 → 强烈推荐(需人确认)
- IC t>2.0 且 max_corr<0.5 → 建议入池(需人确认)
- IC t<2.0 → 不通过，记录到 docs/research-kb/failed/

### Phase 8: 归档（自动）
- 成功: docs/research-kb/findings/
- 失败: docs/research-kb/failed/

## 开始前检查
- 查 docs/research-kb/failed/ 是否已有类似失败方向
- factor_values的distinct factor_name > 80 → 警告因子池膨胀

## 禁止事项
- 不自动加入Active核心池（必须人确认）
- 不修改.env或信号引擎
- 不跳过IC写入factor_ic_history
- 不用close[T]做forward return
