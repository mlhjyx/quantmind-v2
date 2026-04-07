---
name: quantmind-factor-research
description: QuantMind因子研究标准流程。新因子从构思到入库的完整pipeline。
trigger: factor|因子|IC|alpha|因子研究|因子计算
---

# QuantMind Factor Research Skill

## 标准流程（必须按顺序）

### Step 1: 因子设计
- 明确因子的经济机制描述: [市场行为] -> [因子信号] -> [预测方向]（铁律13）
- 确认数据源和可用性（先查DB再设计计算）
- 设计因子计算公式，确认direction(+1/-1)

### Step 2: 因子计算
- 写入factor_values表（code, trade_date, factor_name, raw_value）
- 串行执行，不并行（铁律9，PG OOM教训）
- 数据范围: 2021-01-01 ~ 2025-12-31，2020年做rolling warmup
- 批量写入用psycopg2.extras.execute_values，每批5000行

### Step 3: 中性化
- 预处理顺序固定不可变: 去极值(MAD 5sigma) -> 填充(行业中位数) -> 中性化(行业+市值WLS) -> z-score clip +/-3
- 结果写入factor_values的neutral_value列

### Step 4: IC计算
- 写入factor_ic_history表（铁律11，不可跳过）
- IC必须附带t统计量
- forward return从T+1入场（A股T+1制度）
- t > 2.5 硬性下限（Harvey Liu Zhu 2016）
- BH-FDR校正: M = FACTOR_TEST_REGISTRY.md累积测试总数

### Step 5: 因子画像
- 调用 factor_profiler.profile_factor() 需传入shared data
- 结果写入factor_profile表
- 关注: 行业中性IC、单调性、regime敏感性、成本可行性、冗余

### Step 6: 与核心因子相关性
- 计算与5核心因子(turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio)的截面Spearman相关性
- corr < 0.3 = 独立新维度
- corr > 0.7 = 冗余，不入Active池

### 禁止事项
- 不跳过中性化直接用raw_value做画像
- 不允许IC不写factor_ic_history
- 不默认月度等权评估所有因子（先确认匹配策略）
- forward return必须从T+1开始
