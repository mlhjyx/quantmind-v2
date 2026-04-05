# QuantMind V2 — LightGBM Walk-Forward 训练框架设计文档

> **文档版本**: v2.1（对齐Roadmap V3.8）
> **创建日期**: 2026-03-25（Sprint 1.4b）
> **更新日期**: 2026-04-05（v2.1: 特征池扩充+GPU+数据层升级）
> **关联文档**: QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md(v3.8), DEV_BACKTEST_ENGINE.md
> **硬性约束**: V3.4 fail-fast决策树（三分支）; 铁律11（特征IC必须入库可追溯）
> **v2.0→v2.1核心变化**: 特征池48→63+(15北向因子入库), GPU cupy→PyTorch cu128(RTX 5070 Blackwell), 数据层TimescaleDB hypertable+Parquet缓存(1000x加速), neutral_value存储迁移到cache/neutral_values.parquet

---

## 0. 设计决策索引（本文档新增）

| # | 决策项 | 选择 | 理由 |
|---|--------|------|------|
| ML-01 | Walk-Forward模式 | 扩展窗口(expanding)首轮+固定窗口后续 | 早期数据不足时扩展，稳定后固定24月避免regime变化污染 |
| ML-02 | 目标变量 | T+20日vs沪深300超额收益(对数) | 月度调仓对齐，与基线Sharpe可比。⚠️ T+1开始计算（不含信号日T） |
| ML-03 | Purge gap | 训练集末尾到验证集开始留5交易日 | 防20日forward return信息泄露 |
| ML-04 | Embargo gap | 验证集末尾到测试集额外留0天 | Purge已足够，fold边界已对齐 |
| ML-05 | GPU策略 | device_type=gpu + max_bin=63 + gpu_use_dp=false | RTX 5070 12GB. GPU运算用PyTorch cu128(cupy不支持Blackwell sm_120). Benchmark: matmul 6.2x加速 |
| ML-06 | 过拟合判定 | 训练IC/验证IC > 2.0警告, > 3.0强制停止 | 宽松一档，2倍阈值给early stopping余地 |
| ML-07 | Optuna目标函数 | validation set RankIC均值 | 比IC更稳定，抗异常值 |
| ML-08 | 特征数量 | **63+个（48核心+15北向RANKING因子, DB自动发现）** | v2.1: 北向因子已入库factor_values(5400万行), 后续盈利公告/分钟聚合因子将继续扩充至80+ |
| ML-09 | 评估标准(v2.0) | **V3.4 fail-fast三分支决策树（见§8.3）** | v2.0变更：替换旧两级标准，增加"方向对但特征不够"分支 |
| ML-10 | 预测聚合 | 所有fold预测按时间拼接，不平均 | 保留时序连续性，与SimBroker回测对齐 |
| ML-11 | 特征来源(v2.0新增) | factor_values表自动查询 + 覆盖率/相关性筛选 | 不依赖手动维护的特征清单，新因子入库后自动纳入 |
| ML-12 | Top-N(v2.0新增) | **Top-20**（新最优配置） | v3.3确认Top-20+无行业约束+PMS阶梯保护 → Sharpe=1.15 |
| ML-13 | 基线(v2.0新增) | **Sharpe=1.15（新配置）/ 0.70-0.85（保守DSR校正后）** | v2.0变更：基线从1.03更新，fail-fast用保守基线 |
| ML-14 | 代码起点(v2.0新增) | **复用Sprint 1.3b的ml_engine.py框架** | 已有Walk-Forward+Optuna+20测试，不从头写 |
| ML-15 | 串行执行(v2.0新增) | 数据密集任务串行，不并行 | PostgreSQL OOM风险（3进程×3.5GB≈10.5GB接近32GB RAM上限） |

---

## 0.5 Sprint 1.3b教训与Benchmark（v2.0新增）

> G1 v2.0不是从零开始——Sprint 1.3b已经跑过一次LightGBM Walk-Forward，结果未通过上线门槛但有重要发现。

### Sprint 1.3b结果（作为G1 v2.0的参照基准）

| 指标 | Sprint 1.3b值 | 说明 |
|------|-------------|------|
| 特征数 | 26 | 5基线+12多尺度+9衍生 |
| OOS IC | 0.0823 | 7/7 fold全正 |
| OOS RankIC | 0.0989 | — |
| ICIR | 0.982 | 非常稳定 |
| OOS Sharpe | 0.869 | 未达1.10门槛 |
| paired bootstrap p | 0.073 | 未达0.05门槛 |
| 连续亏损月 | 4 | 超过<3红线 |
| Optuna改进 | +2.5% IC | 几乎无提升 |

### 关键教训

| # | 教训 | 对G1 v2.0的影响 |
|---|------|---------------|
| 1 | **SHAP显示5基线因子完胜** — 12个多尺度扩展特征的SHAP贡献很小 | v2.0需要Ablation实验确认：48特征的信息增量在哪里？ |
| 2 | **Optuna仅+2.5%** — 超参不是瓶颈 | v2.0不需要更多Optuna轮数，200轮足够 |
| 3 | **p=0.073差一点没过** — 效果方向对但统计功效不足 | 48特征可能提供足够的信息增量让p<0.05 |
| 4 | **2024年fold表现差** — 小盘危机期间模型失效 | v2.0需要按年度分解分析，特别关注2022/2024熊市 |
| 5 | **同期等权基线=-0.125** — LightGBM相对大幅跑赢 | 绝对门槛vs相对门槛的讨论。V3.4用fail-fast决策树解决 |

### G1 v2.0 vs Sprint 1.3b的主要差异

| 维度 | Sprint 1.3b | G1 v2.0 | 预期影响 |
|------|-----------|---------|---------|
| 特征数 | 26 | 48+ | +85%特征空间，更多信息维度 |
| 特征来源 | 手动列表 | DB自动发现 | 不遗漏、可复现 |
| 数据质量 | Phase A修复前 | Phase A修复后(WLS/涨跌停/clip) | 更干净的训练数据 |
| 基线配置 | Top-15+行业约束 | Top-20+无行业约束 | 更优的比较基准 |
| Alpha158因子 | 无 | 8个新因子(STD60/VSUMP60/CORD30等) | 新信息维度 |
| 评估标准 | 固定门槛 | V3.4 fail-fast三分支 | 更务实的判断 |

---

## 1. 数据范围与时间分割

### 1.1 全量数据窗口

```
数据可用范围: 2020-07-01 → 2026-04-03（v2.0更新）
总长度: ~69个月

分配方案:
  热身期(不用作任何fold测试): 2020-07-01 → 2021-06-30 (12个月)
  有效实验期:                  2021-07-01 → 2026-03-24 (~57个月)
```

热身期的作用：让早期fold有24个月完整训练数据可用，避免第一个fold只有12个月训练集。

### 1.2 Walk-Forward参数定义

```
训练窗口 (train_months):      24个月
验证窗口 (valid_months):       6个月
测试窗口 (test_months):        6个月（每fold向前推进步长）
步长     (step_months):        6个月（测试窗口=步长，无overlap）
Purge gap:                     5个交易日（约7个自然日）
```

设计选择说明：
- 24个月训练足够捕捉2个市场周期（牛熊交替），不会过拟合单一regime
- 6个月测试窗口与月度调仓对齐（每fold含约6次调仓机会）
- 5日purge gap = forward return周期(20日)的25%，保守但不浪费数据
- 步长=测试窗口，确保测试期不overlap，OOS评估无数据污染

### 1.3 完整Fold时间表

下表的日期均为月初第一个交易日，实际执行时映射到交易日历。

| Fold | 训练开始 | 训练结束 | Purge | 验证开始 | 验证结束 | 测试开始 | 测试结束 |
|------|----------|----------|-------|----------|----------|----------|----------|
| F1   | 2020-07-01 | 2022-06-30 | 5日 | 2022-07-07 | 2022-12-31 | 2023-01-01 | 2023-06-30 |
| F2   | 2020-07-01 | 2022-12-31 | 5日 | 2023-01-07 | 2023-06-30 | 2023-07-01 | 2023-12-31 |
| F3   | 2020-07-01 | 2023-06-30 | 5日 | 2023-07-07 | 2023-12-31 | 2024-01-01 | 2024-06-30 |
| F4   | 2021-01-01 | 2023-12-31 | 5日 | 2024-01-07 | 2024-06-30 | 2024-07-01 | 2024-12-31 |
| F5   | 2021-07-01 | 2024-06-30 | 5日 | 2024-07-07 | 2024-12-31 | 2025-01-01 | 2025-06-30 |
| F6   | 2022-01-01 | 2024-12-31 | 5日 | 2025-01-07 | 2025-06-30 | 2025-07-01 | 2025-12-31 |
| F7   | 2022-07-01 | 2025-06-30 | 5日 | 2025-07-07 | 2025-12-31 | 2026-01-01 | 2026-03-24* |

*F7测试窗口不满6个月，截止当前日期，保留但标记为partial fold。

说明：
- F1-F3: 扩展窗口（expanding window），训练集共用2020-07起始点
- F4-F7: 固定窗口（fixed 24个月），训练集起始随步长后移
- 切换点在F4，此时扩展窗口训练集超过24个月，改为固定窗口防止早期regime污染

### 1.4 数据流向图

```
PostgreSQL factor_values表
        │
        ▼
FeatureBuilder (按fold时间切分)
        │
        ├──► [Train Set] → MAD去极值 → 填缺失 → 中性化 → zscore → LightGBM训练
        │                                                              │
        │         [Purge gap: 5交易日，行丢弃不用于任何集合]           │
        │                                                              ▼
        ├──► [Valid Set] → 同预处理（用Train集参数归一化！） → Early Stopping评估
        │                                                              │
        └──► [Test Set]  → 同预处理（用Train集参数归一化！） → OOS IC / 预测信号
                                                                       │
                                                                       ▼
                                                              预测值存入 ml_predictions表
                                                                       │
                                                                       ▼
                                                              SimBroker回测（月度调仓）
                                                                       │
                                                                       ▼
                                                              OOS Sharpe → V3.4 fail-fast决策树

重要：预处理参数（MAD中位数、中性化系数、zscore均值/std）
      必须在训练集上fit，然后transform验证集和测试集
      绝不能在全量数据上fit（数据泄露！）
```

---

## 2. 特征工程设计

### 2.1 特征选择原则

当前系统已有5个等权因子（基线）：
- turnover_mean_20
- volatility_20
- reversal_20
- amihud_20
- bp_ratio

ML模型的特征需要包含这5个因子 + 新的正交特征。
目标是让ML找到5因子的非线性组合关系，同时引入这5因子没有覆盖的信息维度。

### 2.2 特征池：DB自动发现 + 覆盖筛选 + 相关性预检（v2.0重写）

> **v1.0→v2.0核心变化**: 从手动列举51个特征改为从factor_values表自动发现。
> 原因: 手动列表容易过时（如mf_divergence IC=9.1%已证伪为-2.27%），自动发现确保特征池与DB实际状态一致。

**Step 1: 自动发现**
```sql
SELECT factor_name, COUNT(*) as rows, 
       MIN(trade_date) as start_date, MAX(trade_date) as end_date,
       COUNT(DISTINCT symbol) as stocks, COUNT(DISTINCT trade_date) as dates
FROM factor_values 
GROUP BY factor_name
HAVING COUNT(*) > 100000  -- 排除极少数据的因子
ORDER BY factor_name;
```

**Step 2: 覆盖率筛选**
- 时间覆盖: 起始日期 ≤ 2021-07-01（保证F1训练集有数据）
- 股票覆盖: ≥ 2000只/月（排除覆盖太窄的因子，如北向资金只覆盖~2000只可以保留）
- 缺失率: 截面缺失率 ≤ 30%（超过的降级为WARNING，不排除但记录）
- 短覆盖因子（如Alpha158 2021起）: 在早期fold(F1-F3)中设为NaN，LightGBM原生支持缺失值

**Step 3: 相关性预检**
```python
# 月底截面做48×48相关矩阵
corr_matrix = feature_df.corr(method='spearman')
# corr > 0.85的对标记为"高相关"
# 高相关对中保留IC更高的那个（IC从factor_ic_history查，铁律11）
# 不自动删除，只标记——让LightGBM自己学权重，但SHAP分析时重点关注
```

**Step 4: 输出特征就绪报告**
```
因子名 | 行数 | 起止日期 | 股票数 | 缺失率 | 高相关对 | 就绪状态
-------|------|---------|--------|--------|---------|--------
turnover_mean_20 | 5.3M | 2021-01~2025-12 | 5405 | 2% | vol_20(0.72) | ✅ READY
...
mf_divergence | 5.3M | 2021-01~2025-12 | 5405 | 3% | — | ⚠️ IC=-2.27%(弱)
```

**当前预期特征池组成（48+个，以DB实际为准）:**

| 组 | 来源 | 预计数量 | 说明 |
|---|------|---------|------|
| A: 基线5因子 | factor_values(历史) | 5 | turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio |
| B: 多尺度变体 | factor_values(历史) | ~12 | 5/10/60日窗口衍生 |
| C: 资金流 | factor_values(历史) | ~8 | mf_divergence等。⚠️ mf_divergence IC=-2.27%但保留让ML判断 |
| D: 价格行为 | factor_values(历史) | ~10 | high_low_range_20等 |
| E: 基本面 | factor_values(历史) | ~2-4 | Sprint 1.5证明大部分无效，只保留bp_ratio衍生 |
| F: Alpha158新增 | factor_values(v3.3新增) | 8 | STD60/VSUMP60/CORD30/RANK5/CORR5/VSTD30/VSUMP5/VMA5 |
| G: 北向个股RANKING | factor_values(v2.1新增) | 15 | 持仓变化/持续性/金额口径/交互条件类因子（2026-04-05入库，5400万行） |
| 合计 | — | **63+** | 以DB实际查询为准 |

**v2.1新增: 组G 北向个股RANKING因子（15个）:**
- 持仓变化类: nb_ratio_change_5d/20d, nb_change_rate_20d
- 持续性类: nb_consecutive_increase, nb_increase_ratio_20d, nb_trend_20d
- 相对市场类: nb_change_excess, nb_rank_change_20d, nb_concentration_signal
- 金额口径类: nb_net_buy_ratio, nb_net_buy_5d_ratio, nb_net_buy_20d_ratio
- 交互条件类: nb_contrarian, nb_acceleration, nb_new_entry
- 关键发现: IC方向全部为负（外资一致性增持→跑输=反向信号）
- 中性化后3个Active因子t均<2.0，作为独立因子不显著，但ML非线性组合可能贡献增量alpha
- neutral_value存储在cache/neutral_values.parquet（不在factor_values表的neutral_value列）

**与v1.0的51个特征对比:**
- 组E(基本面)从8个缩减为2-4个（Sprint 1.5证明ROE/营收增速等无效）
- 组F(市场状态)移除（csi300_return等宏观特征不在factor_values表，需额外数据源，暂不纳入）
- 新增Alpha158的8个因子
- mf_divergence保留但不再标记为"核心"（IC=-2.27%，v1.0错误标注IC=9.1%）
- earnings_surprise_std(PEAD)移除（DB中无此因子数据）
- **v2.1新增15个北向因子（组G），特征池从48→63**

### 2.3 特征预处理流水线（严格遵守铁律顺序，Phase A对齐）

```python
# 预处理顺序（与CLAUDE.md因子计算规则完全一致，Phase A修复后）:
# 1. MAD去极值（基于训练集的中位数和MAD）
# 2. 缺失值填充（截面中位数填充）
# 3. WLS中性化（回归掉市值+行业，√market_cap加权，Phase A修复）
# 4. zscore标准化（±3 clip，Phase A修复）

# 关键：所有预处理参数在train set上fit，
# 用fit后的参数transform valid set和test set
# 这是防止数据泄露的核心！

class FeaturePreprocessor:
    def fit(self, train_df: pd.DataFrame) -> 'FeaturePreprocessor':
        # 1. 计算每个特征的中位数和MAD（用于去极值）
        # 2. 计算行业哑变量和√market_cap（用于WLS中性化）
        # 3. 计算zscore参数（均值、std，中性化后，±3 clip）
        pass

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        # 按fit好的参数依次执行4步
        # ⚠️ 中性化用WLS（非OLS），与生产代码一致
        # ⚠️ zscore后clip到±3，与Phase A修复一致
        pass
```

### 2.4 目标变量定义

```
target = log(1 + r_stock_t+20) - log(1 + r_csi300_t+20)

其中:
  r_stock_t+20  = 股票T+1到T+21交易日的复权收益率（⚠️ 从T+1开始，不含信号日T）
  r_csi300_t+20 = 沪深300同期收益率

计算约束:
  - 使用复权价格（close × adj_factor）
  - ⚠️ 从T+1开始计算，不是T+0（之前有bug导致~6.5% IC膨胀，已修复）
  - 停牌期间（volume=0）：目标变量设为NaN，从训练集中删除该行
  - 退市前5日：目标变量设为实际退市收益，包含在训练集
  - T+20不满（接近当前日期）：整行删除，不预测未来
```

### 2.5 Universe定义（v2.0新增，确保训练=回测=PT一致）

```
训练/回测/PT共用同一Universe筛选条件:
  - 排除ST/*ST（当月有ST标记的股票）
  - 排除上市不满60个交易日的新股
  - 排除当月停牌>10个交易日的股票
  - 排除退市前最后5个交易日外的退市股票（保留前5日用于退出）
  - 不排除微盘股（SMB beta=0.83，alpha主要来自小盘，排除会损害策略）

⚠️ 这个Universe必须与回测引擎(run_backtest.py)和PT(run_paper_trading.py)使用的完全一致。
如果不一致，会导致训练时学到的模式在回测/实盘中不存在（mf_divergence事件的教训之一）。
```

### 2.6 Ablation实验计划（v2.0新增）

> Sprint 1.3b SHAP显示5基线因子完胜。G1 v2.0必须证明48特征的信息增量在哪里。

**三个tier对比（同一Walk-Forward框架，只改特征集）:**

| Tier | 特征集 | 特征数 | 目的 |
|------|--------|--------|------|
| Tier-A | 5基线因子 | 5 | 纯基线，作为ML vs 等权的直接对比 |
| Tier-B | 基线+最强扩展 | ~20 | 加入SHAP重要性>1%的非基线因子 |
| Tier-C | 全集 | 48+ | 所有factor_values有数据的因子 |

**预期结果解读:**
```
Tier-C > Tier-B > Tier-A → 最好情况：更多特征=更多信息
Tier-C ≈ Tier-B > Tier-A → 好：扩展因子有用但不需要全部
Tier-C ≈ Tier-B ≈ Tier-A → 差：所有扩展因子都是噪声，ML增量来自非线性组合
Tier-C < Tier-A           → 最差：噪声特征严重干扰模型
```

**执行顺序:** 先跑Tier-C（全集），如果通过fail-fast则成功。如果未通过，跑Tier-A和Tier-B做诊断——定位是特征问题还是模型问题。

---

## 3. LightGBM模型配置

### 3.1 基础配置（对标Qlib Alpha158 YAML）

```yaml
# 参照 workflow_config_lightgbm_Alpha158.yaml，针对A股月度截面调整
model:
  class: LGBMRegressor
  objective: regression          # 回归，预测连续收益率
  metric: mse                    # 训练损失：均方误差
  boosting_type: gbdt

# GPU配置（RTX 5070 12GB VRAM）
gpu:
  device_type: gpu
  gpu_platform_id: 0
  gpu_device_id: 0
  gpu_use_dp: false              # 单精度（float32），速度5-10倍于双精度
  max_bin: 63                    # GPU优化关键：63 vs 255速度差异显著

# 训练控制
training:
  num_boost_round: 500           # 最大迭代轮数
  early_stopping_rounds: 50      # 验证集IC不提升50轮停止
  verbose_eval: 50               # 每50轮打印一次

# 初始超参数（Optuna搜索的起点）
hyperparams_init:
  learning_rate: 0.05            # 保守（Qlib用0.2，我们更慢防止过拟合）
  num_leaves: 63                 # Qlib用210，我们保守
  max_depth: 6                   # 限制树深防止过拟合
  min_child_samples: 50          # A股截面~4000股，50保证叶节点稳定
  reg_alpha: 1.0                 # L1正则
  reg_lambda: 5.0                # L2正则（Qlib用580，过大；月度截面用较小值）
  subsample: 0.8                 # 每次训练用80%样本
  colsample_bytree: 0.8          # 每棵树随机选80%特征
  subsample_freq: 1              # 每轮随机
  n_jobs: -1                     # 使用全部CPU核心（配合GPU）
  seed: 42                       # 确定性训练（铁律：同参数bit-identical）
```

### 3.2 VRAM估算

```
训练样本量估算:
  截面股票数: ~4000只
  训练天数: ~24个月 × 22交易日 = 528天
  调仓只在月底生成信号，但训练集包含所有日期的截面
  实际训练样本 = 4000 × 528 = ~211万行

内存占用估算:
  特征数: 63+（v2.1: 48核心+15北向）
  float32精度: 4字节
  原始数据: 211万 × 63 × 4字节 = ~532MB
  LightGBM直方图(max_bin=63): 数据量约压缩到原始的20%→~81MB
  GPU VRAM使用: 数据 + 模型 + 梯度 ≈ 1-2GB（远低于12GB上限）

结论: RTX 5070 12GB VRAM完全满足，每fold训练预计<15分钟
⚠️ 注意PostgreSQL查询内存: 48因子×5年×5000股的factor_values查询可能占3-5GB RAM，串行执行
```

### 3.3 评估指标定义

```python
def ic_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    Spearman IC（截面）
    在每个交易日的截面上计算rank相关，然后取时间序列均值
    """
    pass

def rank_ic_score(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    """
    RankIC = Spearman(rank(pred), rank(true))
    与IC的区别：先double-rank，对异常值更鲁棒
    """
    pass

def icir_score(daily_ics: List[float]) -> float:
    """
    ICIR = mean(IC) / std(IC)
    稳定性指标，> 0.3 算可以，> 0.5 算好
    """
    return np.mean(daily_ics) / (np.std(daily_ics) + 1e-8)

# 评估目标：
#   训练集 IC > 0.05 才算模型学到了东西
#   验证集 RankIC > 0.03 作为Optuna优化目标
#   OOS IC > 0.02（Harvey Liu Zhu标准）
#   ICIR > 0.3
```

---

## 4. Optuna超参搜索设计

### 4.1 搜索空间定义

```python
def optuna_search_space(trial: optuna.Trial) -> dict:
    return {
        # 学习率：对数均匀分布（小值更重要）
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.3, log=True),

        # 叶节点数：决定模型复杂度
        "num_leaves": trial.suggest_int("num_leaves", 15, 127),

        # 树深：-1为不限，这里限制防止过拟合
        "max_depth": trial.suggest_int("max_depth", 3, 8),

        # 叶节点最小样本：防止在小子集过拟合
        # 截面4000股，min_child=20意味着叶节点至少代表0.5%股票
        "min_child_samples": trial.suggest_int("min_child_samples", 20, 100),

        # L1正则化
        "reg_alpha": trial.suggest_float("reg_alpha", 0.0, 10.0),

        # L2正则化
        "reg_lambda": trial.suggest_float("reg_lambda", 0.0, 10.0),

        # 行采样（bagging）
        "subsample": trial.suggest_float("subsample", 0.5, 1.0),

        # 列采样（特征随机）
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),

        # 最小增益（控制树的生长）
        "min_split_gain": trial.suggest_float("min_split_gain", 0.0, 1.0),

        # 固定参数（不纳入搜索）
        "device_type": "gpu",
        "max_bin": 63,
        "gpu_use_dp": False,
        "objective": "regression",
        "num_boost_round": 500,
        "early_stopping_rounds": 50,
        "seed": 42,
    }
```

### 4.2 200轮预算分配策略

```
总预算: 200轮
分配方案:
  第1-20轮:   随机采样（TPE需要初始点探索）
  第21-200轮: TPE（贝叶斯优化，Tree-structured Parzen Estimator）

Optuna配置:
  sampler: TPESampler(n_startup_trials=20, seed=42)
  pruner: MedianPruner(n_startup_trials=5, n_warmup_steps=20)

  # Pruner含义：每个trial训练到20轮early stopping时，
  # 如果验证集IC低于同期trial的中位数，提前终止
  # 效果：约40-50%的trial被剪枝，实际完整训练约100-120轮
  # 节省时间：200轮从预计40小时缩减到约8小时

并行策略:
  n_jobs=1（GPU独占，同一时间只训练一个trial）
  使用SQLite存储Optuna结果（支持断点续跑）
  storage: "sqlite:///optuna_lgbm.db"
```

### 4.3 Optuna目标函数

```python
def optuna_objective(trial: optuna.Trial) -> float:
    """
    目标：最大化验证集RankIC均值
    在F1 fold上搜索（训练最快的fold），搜到最优参数后所有fold重新训练

    返回: validation set RankIC（越大越好，Optuna默认minimize，返回负值）
    """
    params = optuna_search_space(trial)

    # 使用F1 fold的训练集和验证集
    # 不用测试集！测试集在Optuna阶段完全封闭
    model = lgb.train(
        params,
        train_data,        # F1训练集
        valid_sets=[valid_data],
        callbacks=[
            lgb.early_stopping(50, verbose=False),
            lgb.log_evaluation(0),
            optuna.integration.lightgbm.LightGBMPruningCallback(trial, "l2"),
        ],
    )

    # 计算验证集RankIC
    valid_preds = model.predict(X_valid)
    daily_rank_ics = compute_daily_rank_ic(valid_preds, y_valid, dates_valid)

    # 过拟合检测：如果训练IC/验证IC > 2.0，惩罚目标函数
    train_preds = model.predict(X_train)
    train_ic = compute_ic(train_preds, y_train)
    valid_ic = np.mean(daily_rank_ics)

    if train_ic > 0 and valid_ic > 0:
        overfit_ratio = train_ic / valid_ic
        if overfit_ratio > 2.0:
            # 轻微惩罚（2-3倍区间警告但不终止）
            penalty = min((overfit_ratio - 2.0) * 0.1, 0.5)
            return -(valid_ic - penalty)
        elif overfit_ratio > 3.0:
            # 强制返回极差值（3倍以上直接淘汰）
            return -999.0

    return -np.mean(daily_rank_ics)  # 负值（Optuna minimize）
```

### 4.4 超参搜索时间预算

```
单轮trial时间估算:
  F1训练集: 211万行 × 48+特征（v2.0更新）
  GPU训练500轮: ~5分钟（RTX 5070，max_bin=63）
  Pruner剪枝率: ~50%（被剪trial平均只跑100轮，约2.5分钟）

200轮总时间估算:
  完整trial(约100轮): 100 × 5分钟 = 500分钟
  被剪trial(约100轮): 100 × 2.5分钟 = 250分钟
  总计: ~750分钟 ≈ 12.5小时

处理方案:
  分2天运行（每天<30分钟的约束指单次fold训练，不是搜索总时长）
  或者：只用24个月训练数据的随机50%子集做超参搜索，
        搜到最优参数后再用完整数据全fold训练
  推荐后者：搜索时间降到~4小时，全fold训练用最优参数
```

---

## 5. 过拟合检测体系

### 5.1 三层检测机制

```
层1 - 训练过程中（Early Stopping）:
  监控验证集loss（MSE）
  连续50轮不下降 → 自动停止
  返回最优轮数的模型（best_iteration）

层2 - Fold评估时（IC比率检测）:
  计算 overfit_ratio = train_IC / valid_IC
  > 2.0: WARNING（记录到实验日志）
  > 3.0: CRITICAL（该fold标记为过拟合，不纳入预测拼接）
  > 5.0: 铁律7触发（强制停止所有fold，不上线）

层3 - OOS最终评估（V3.4 fail-fast决策树）:
  所有fold预测拼接 → SimBroker回测
  V3.4 fail-fast三分支判断（见§8.3）
  附加红线: trainIC/validIC>3.0 / 2x成本Sharpe<0.3 / 连续亏损月>4
```

### 5.2 过拟合检测流程图

```
训练完成
    │
    ├─► 计算 train_IC（训练集，样本内）
    ├─► 计算 valid_IC（验证集，样本外）
    │
    ▼
overfit_ratio = train_IC / valid_IC
    │
    ├─ ratio < 2.0 → ✅ 正常，继续
    ├─ ratio ∈ [2.0, 3.0) → ⚠️ 警告，记录，继续（有时合理）
    ├─ ratio ∈ [3.0, 5.0) → ❌ 该fold过拟合，跳过测试集预测
    └─ ratio ≥ 5.0 → 🚨 铁律7触发，整个实验停止

统计报告（每fold）:
    训练样本数 | 验证样本数 | 测试样本数
    训练IC | 验证IC | OOS IC（测试集）
    overfit_ratio | early_stopping轮数
    是否过拟合（布尔）
```

### 5.3 SHAP特征重要性分析计划

```
目的：
  1. 验证模型依赖的特征是否有经济学逻辑（不是噪声拟合）
  2. 识别跨fold稳定的重要特征 vs 不稳定的特征
  3. 发现意外重要的特征 → 新因子候选

执行时机：
  每个fold训练完成后，对测试集样本计算SHAP值
  Fold结束后汇总所有fold的feature importance

分析维度：
  a) 全局特征重要性：SHAP值绝对值的均值，按fold排列
  b) 跨fold稳定性：各fold top10特征的Jaccard相似度（> 0.6算稳定）
  c) 特征组贡献：A/B/C/D/E/F六组各自贡献多少%
  d) 时间稳定性：重要特征的SHAP值均值是否随时间飘移

警告信号：
  - 某特征在训练集SHAP很大，测试集很小 → 过拟合该特征
  - 组F（市场状态）特征SHAP占比>40% → 模型变成市场择时，不是Alpha选股
  - 财务特征（E组）SHAP占比<5% → 基本面信息没有被有效利用

SHAP计算开销估算:
  测试集: ~4000股 × 6个月 × 22天 = ~52.8万行
  SHAP计算: 约1-2分钟/fold（tree SHAP，线性复杂度）
  可接受，加入标准流程
```

---

## 6. Walk-Forward完整执行流程

### 6.1 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│              Walk-Forward ML Pipeline                        │
│                                                             │
│  配置层                                                      │
│  ├─ WFConfig（窗口参数、fold定义）                            │
│  ├─ LGBMConfig（模型参数、GPU设置）                           │
│  └─ OptunaConfig（搜索空间、轮数、存储）                      │
│                                                             │
│  数据层                                                      │
│  ├─ FeatureLoader（从PG factor_values自动发现48+因子）        │
│  ├─ FeaturePreprocessor（MAD→填充→WLS中性化→zscore±3clip）   │
│  └─ AblationManager（Tier-A/B/C三组对比，§2.6）              │
│                                                             │
│  训练层                                                      │
│  ├─ OptunaSearcher（200轮超参搜索，基于F1 fold）              │
│  ├─ FoldTrainer（逐fold训练，GPU加速）                        │
│  └─ OverfitDetector（三层过拟合检测）                        │
│                                                             │
│  评估层                                                      │
│  ├─ ICCalculator（每日截面IC/RankIC/ICIR）                   │
│  ├─ SHAPAnalyzer（特征重要性分析）                            │
│  └─ PredictionAggregator（fold预测拼接）                     │
│                                                             │
│  回测层（复用已有SimBroker）                                  │
│  ├─ 预测值 → 月底截面排名 → Top20持仓（V3.4新配置）           │
│  ├─ SimBroker回测（涨跌停/整手约束/T+1）                      │
│  └─ V3.4 fail-fast决策树（三分支判断）                        │
│                                                             │
│  存储层（PostgreSQL）                                        │
│  ├─ model_registry（每fold保存模型元信息）                    │
│  ├─ experiments（整个WF实验记录）                             │
│  └─ ml_predictions（每fold的OOS预测值）                      │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 逐步执行流程

```
Step 0: 初始化
  ├─ 验证数据库连接（PG/Redis）
  ├─ 检查factor_values表数据范围（2020-07-01 ~ 当前）
  ├─ 确认GPU可用（nvidia-smi检查RTX 5070）
  ├─ 创建实验记录（experiments表，status='running'）
  └─ 初始化Optuna study（SQLite存储，支持断点续跑）

Step 1: 特征构建（v2.0更新：DB自动发现）
  ├─ 运行§2.2 Step 1 SQL查询factor_values表所有可用因子
  ├─ 运行§2.2 Step 2-3覆盖率筛选+相关性预检
  ├─ 从factor_values表加载通过筛选的48+因子
  ├─ 合并形成完整特征矩阵（约4000股×68月×48+特征）
  ├─ 计算目标变量（T+1到T+21日超额收益，⚠️不含信号日T）
  └─ 保存到本地Parquet（加速后续fold读取，防止重复查DB）

Step 2: Optuna超参搜索（使用F1 fold，不碰测试集）
  ├─ F1 Train/Valid分割（Purge gap处理）
  ├─ 预处理（在F1 Train上fit参数）
  ├─ 200轮Optuna搜索
  ├─ 记录best_params到实验日志
  └─ 保存Optuna study到SQLite（可视化分析）

Step 3: Walk-Forward训练（F1→F7，使用best_params）
  FOR each fold in [F1, F2, F3, F4, F5, F6, F7]:
    ├─ 切分Train/Valid/Test（按时间）
    ├─ 应用Purge gap（删除gap期间行）
    ├─ 在Train上fit预处理器，transform全部集合
    ├─ LightGBM训练（GPU，early stopping）
    ├─ 计算训练IC、验证IC、overfit_ratio
    ├─ IF overfit_ratio > 5.0: 触发铁律7，停止
    ├─ 对Test集生成预测（OOS预测值）
    ├─ 计算Test集IC/RankIC/ICIR
    ├─ 计算SHAP特征重要性
    ├─ 保存模型到model_registry（status='candidate'）
    └─ 保存预测值到ml_predictions表

Step 4: 预测聚合与回测
  ├─ 按时间顺序拼接所有fold的测试集预测
  ├─ 检查时间连续性（无gap、无overlap）
  ├─ 月底截面：按预测值排名，选Top20（v2.0更新，V3.4新配置）
  ├─ 传入SimBroker回测（2021-07 ~ 2026-03）
  ├─ 应用完整交易规则（涨跌停/整手/T+1/成本）
  └─ 生成回测报告（含所有CLAUDE.md要求的指标）

Step 5: V3.4 fail-fast判断（v2.0重写，替换旧两级标准）
  基线 = 当前等权配置OOS Sharpe（预期~1.15，以实际回测确认值为准）

  分支1: OOS Sharpe ≥ 基线×1.2 且 paired bootstrap p<0.05
    → 成功 → 上线影子PT → Gate G8升级为ML评估 → 继续G1.1-G1.4
  
  分支2: OOS Sharpe ≥ 基线 但 p>0.05
    → 方向对但特征不够 → GA5 code gen扩展特征池后重跑
    → 同时做Ablation(§2.6)定位瓶颈
  
  分支3: OOS Sharpe < 基线
    → ML在当前数据上无增量
    → 诊断路径: 是因子质量不够? 数据量不够? A股月频信噪比根本不支持ML?
    → 尝试Tier-A(5因子)确认: 如果Tier-A也差→信噪比问题; 如果Tier-A还行→特征噪声问题

  附加红线（任何一条不过则不上线）:
    - trainIC/validIC > 3.0 → 过拟合
    - 2x成本Sharpe < 0.3 → 成本敏感
    - 连续亏损月 > 4 → 不稳定
```

### 6.3 每fold时间预算

```
特征加载（Step 1，仅首次）: 5-10分钟（PG查询+特征计算）
Optuna搜索（Step 2，仅一次）: 4-6小时（200轮×剪枝后约3分钟/轮）
单fold训练（Step 3，每fold）:
  预处理: 1分钟
  GPU训练(early stopping后约200-300轮实际): 3-8分钟
  SHAP计算: 1-2分钟
  合计: 5-11分钟/fold

7个fold总训练时间: 7 × 10分钟 = ~70分钟 (满足<30分钟/fold约束)
回测（Step 4）: 2-5分钟（SimBroker已有的向量化回测）

总流程时间（首次完整运行）:
  Optuna搜索: ~5小时
  7 fold训练: ~70分钟
  回测评估: ~5分钟
  合计: ~6.5小时（分2天运行，每天3-4小时后台任务）
```

---

## 7. 数据库表扩展需求

现有的`model_registry`和`experiments`表已经覆盖基本需求，但Walk-Forward需要新增一张预测值表：

### 7.1 新表：ml_predictions

```sql
-- Walk-Forward每fold的OOS预测值（用于回测和后续分析）
CREATE TABLE ml_predictions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id   UUID REFERENCES experiments(id),
    model_id        UUID REFERENCES model_registry(id),
    fold_id         INT NOT NULL,                   -- 1-7对应F1-F7
    symbol_id       INT REFERENCES symbols(id),
    trade_date      DATE NOT NULL,                  -- 预测生成日期（信号日）
    target_date     DATE NOT NULL,                  -- 目标日期（trade_date+20交易日）
    predicted_return DECIMAL(10, 6) NOT NULL,       -- 预测的T+20超额收益
    actual_return   DECIMAL(10, 6),                 -- 实际发生的超额收益（事后填入）
    feature_set_version VARCHAR(20),               -- 特征版本号（特征有变更时记录）
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mlpred_date_symbol ON ml_predictions(trade_date, symbol_id);
CREATE INDEX idx_mlpred_experiment ON ml_predictions(experiment_id, fold_id);
COMMENT ON TABLE ml_predictions IS 'Walk-Forward OOS预测值，每fold测试集的每日截面预测';
```

### 7.2 experiments表扩展字段（JSONB存储，无需加列）

```json
{
  "experiment_type": "walk_forward_lgbm",
  "parameters": {
    "n_folds": 7,
    "train_months": 24,
    "valid_months": 6,
    "test_months": 6,
    "purge_gap_days": 5,
    "n_features": "48+ (DB auto-discovered)",
    "optuna_trials": 200,
    "best_hyperparams": { ... },
    "lgbm_version": "4.x"
  },
  "results": {
    "fold_metrics": [
      {
        "fold": 1,
        "train_period": "2020-07 ~ 2022-06",
        "test_period": "2023-01 ~ 2023-06",
        "train_ic": 0.085,
        "valid_ic": 0.042,
        "oos_ic": 0.038,
        "overfit_ratio": 2.02,
        "early_stopping_round": 187,
        "status": "ok"
      }
    ],
    "aggregate": {
      "mean_oos_ic": 0.040,
      "mean_oos_rank_ic": 0.038,
      "icir": 0.41,
      "oos_sharpe": 1.15,
      "oos_sharpe_ci_95": [0.72, 1.54],
      "paired_bootstrap_p": 0.03,
      "sharpe_2x_cost": 0.71,
      "vs_baseline_sharpe_improvement": 0.096,
      "overfit_folds": 0
    }
  }
}
```

---

## 8. 关键风险与缓解措施

### 8.1 技术风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| GPU OOM（超12GB VRAM）| 低 | 训练失败 | max_bin=63已降内存，监控nvidia-smi；备用：降至max_bin=31 |
| 单fold训练超30分钟 | 低 | 违反约束 | num_boost_round上限500+early stopping，预计不超过15分钟/fold |
| 数据泄露（预处理参数）| 中 | OOS虚高 | 预处理器强制在train上fit，代码审查验证 |
| Optuna搜索崩溃 | 中 | 浪费时间 | SQLite持久化，断点续跑；每20轮checkpoint |
| factor_values表数据不完整 | 低 | 样本量不足 | Step 0数据检查；缺失率>20%的特征降级警告 |

### 8.2 研究风险

| 风险 | 可能性 | 影响 | 缓解措施 |
|------|--------|------|---------|
| OOS Sharpe < 基线（V3.4 fail-fast分支3）| 中 | ML方案需诊断 | §8.4诊断预案；Ablation定位瓶颈 |
| 所有fold过拟合 | 中 | 等权天花板也适用于ML | 分析哪类特征过拟合；尝试更强正则 |
| A股2024年风格剧变影响OOS | 高 | F6/F7 fold IC差 | 在报告中单独分析2024年fold；考虑regime-aware训练 |
| ML信号换手率远超等权 | 中 | 成本吃掉Alpha | 计算年化换手率；如>300%需加换手率约束项 |

### 8.3 V3.4 fail-fast决策树（v2.0重写）

```
Optuna完成后 (Step 2结束):
    验证集RankIC > 0.03?
    NO → 停止，特征工程需要重做
    YES → 继续全fold训练

全fold训练后 (Step 3结束):
    过拟合fold数量 < 3（7个fold中）?
    NO → 停止，模型过于复杂，减少特征或增加正则
    YES → 继续回测

回测后 (Step 4结束):
    ┌─ OOS Sharpe ≥ 基线×1.2 且 p<0.05
    │    → 成功 → 影子PT → Gate G8升级为ML评估
    │    → 继续G1.1(LambdaRank) → G1.3(XGB+Cat) → G1.4(Ensemble)
    │
    ├─ OOS Sharpe ≥ 基线 但 p>0.05
    │    → 方向对但特征不够
    │    → 做Ablation(§2.6)定位瓶颈
    │    → GA5 LLM code gen扩展特征池后重跑
    │
    └─ OOS Sharpe < 基线
         → ML无增量，诊断:
         → 跑Tier-A(5因子)确认信噪比 vs 特征噪声
         → 尝试线性模型(Lasso/Ridge)确认是否需要非线性

    附加红线（任何一条不过则不上线）:
    - trainIC/validIC > 3.0 → 过拟合
    - 2x成本Sharpe < 0.3 → 成本敏感
    - 连续亏损月 > 4 → 不稳定
```

### 8.4 "48特征仍不如等权"的诊断预案（v2.0新增）

> 这是G1最大的风险。Sprint 1.3b用26特征已经差一点(Sharpe=0.869/p=0.073)。
> 如果48特征也未通过，需要有系统的诊断路径而非盲目重试。

**诊断路径:**

| 步骤 | 检查 | 如果是 | 如果否 |
|------|------|--------|--------|
| 1 | Ablation: Tier-A(5因子) Sharpe如何？ | ≈等权→信噪比不支持ML | >等权→5因子非线性有增量，问题在扩展特征 |
| 2 | SHAP: 扩展因子贡献占比？ | <10%→扩展因子是噪声 | >10%→有信息但被其他因素抵消 |
| 3 | 换手率对比: ML vs 等权 | ML换手率>>等权→成本吃掉alpha | 换手率相近→不是成本问题 |
| 4 | 年度分解: 哪年拉低了整体？ | 2022/2024→熊市regime问题 | 全年均差→基础alpha不够 |
| 5 | 线性对比: Lasso/Ridge用48特征 | Lasso>等权→非线性不需要，线性即可 | Lasso≈等权→特征本身无增量 |

---

## 9. 与现有系统的集成点

### 9.1 复用的模块

```
SimBroker: 直接复用，ML策略传入的是月底截面的预测值排名
           SimBroker不需要知道是ML预测还是等权因子

因子预处理: 复用FactorService的WLS中性化和zscore(±3 clip)逻辑（Phase A修复后）
           不重写，确保与等权基线完全一致的预处理方式

回测报告: 复用PerformanceService，生成所有指标
          新增：按fold分解的IC时序图 + 年度分解

Sprint 1.3b代码: 复用ml_engine.py框架（Walk-Forward+Optuna+20测试）
                重构特征加载（从手动列表改为DB查询）
```

### 9.2 信号生成逻辑（上线后）

```python
# 上线后，每月底的信号生成流程变为：

# 旧流程（等权基线）：
scores = equal_weight(factor_values)  # 5个因子等权求和

# 新流程（LightGBM，条件上线）：
if ml_model.status == 'active':
    scores = ml_model.predict(current_features)  # 用最新fold的模型
    # 每6个月重新训练一个fold（与Walk-Forward步长一致）
else:
    scores = equal_weight(factor_values)  # fallback到等权基线

# 两个模式共用同一SimBroker/MiniQMTBroker，只有scores来源不同
# Top-N = 20（V3.4新配置）
```

### 9.3 模型更新机制（上线后）

```
每6个月（与test窗口对齐）:
  1. 新增一个fold（滑动窗口，训练集前进6个月）
  2. 使用上次的best_params（不重跑Optuna，除非性能显著下降）
  3. 在新fold的验证集上评估：IC是否下降>30%？
     YES → 触发重新搜索Optuna（≤200轮）
     NO → 直接用新fold模型更新model_registry
  4. 新模型status='candidate'，通过OOS评估后→'active'
  5. 旧模型status='retired'
```

### 9.4 影子PT部署方案（v2.0新增）

> Sprint 1.3b已实现影子PT机制——每月调仓时同步生成影子选股，记录到DB但不影响主策略。

**G1通过fail-fast后的部署步骤:**

```
1. 最新fold模型写入model_registry (status='shadow')
2. 每月调仓时:
   a. 等权策略正常执行（主PT不受影响）
   b. LightGBM用当月截面特征生成预测值
   c. 预测值排名Top-20写入shadow_signals表
   d. shadow_signals不传入QMT执行
3. 每月对比: 等权实际收益 vs LightGBM影子收益
4. 观察期30-60天后:
   如果LightGBM影子Sharpe > 等权实际Sharpe → 评估升级为主策略
   如果LightGBM影子Sharpe ≤ 等权实际Sharpe → 不升级，继续观察或放弃
```

### 9.5 与清明改造后架构的集成（v2.0新增）

```
ML训练是研究任务，不走生产调度（Servy/Celery/CeleryBeat）:
- 手动触发或cron触发，不纳入Servy管理的4个服务
- 训练结果写入PostgreSQL（model_registry/experiments/ml_predictions）
- 影子PT信号生成可以作为Celery task（轻量，每月一次）

数据读取(v2.1更新):
- raw_value从factor_values表读取（TimescaleDB hypertable, 71月chunks, 查询2.2ms）
- neutral_value优先从cache/neutral_values.parquet读取（不读factor_values的neutral_value列）
- 价格/forward return优先从cache/close_pivot.parquet + cache/fwd_excess_*d.parquet读取
- 不从Redis读取（Redis是实时数据总线，ML训练用历史数据）
- ⚠️ 串行执行，不并行多个数据密集查询（PostgreSQL OOM风险）

GPU资源(v2.1更新):
- RTX 5070 Blackwell (sm_120, 12GB VRAM)
- LightGBM GPU: device_type=gpu（CUDA Toolkit 12.6）
- 矩阵运算: PyTorch cu128（cupy不支持Blackwell）
- Benchmark: matmul(5000×5000) CPU 117ms → GPU 19ms (6.2x)
- 训练时段建议：收盘后18:00-次日08:00（不与盘中监控冲突）
```

---

## 10. 执行检查表（v2.0更新）

在开始代码实现前，以下前置条件必须满足：

```
□ factor_values表数据确认（63+因子, 含15北向因子, TimescaleDB hypertable）
□ neutral_values.parquet确认（cache/neutral_values.parquet存在, 含北向因子）
□ 特征就绪报告生成（§2.2 Step 4，每个因子的覆盖率/缺失率/就绪状态）
□ 相关性预检完成（§2.2 Step 3，63×63相关矩阵，标记高相关对）
□ RTX 5070 GPU驱动确认（nvidia-smi可见，CUDA 12.6, PyTorch cu128）
□ LightGBM GPU版本安装验证（import lightgbm; lgb.Dataset.__module__）
□ Optuna安装（pip install optuna optuna-integration）
□ 交易日历完整（2020-07 ~ 2026-04，用于Purge gap计算）
□ 等权基线回测确认（Top-20+无行业约束配置，记录Sharpe作为fail-fast分母）
□ ml_predictions表创建（本文档7.1节DDL）
□ Sprint 1.3b代码审查（ml_engine.py可复用程度评估）
□ Universe定义确认（§2.5，训练=回测=PT一致）
□ 目标变量T+1起算确认（不含信号日T，防止~6.5% IC膨胀bug复发）
□ 铁律11确认（所有参考的IC值必须有factor_ic_history入库记录）
□ 内存预估（48因子×5年×5000股×4字节≈目标<8GB RAM，串行执行）
```

---

## 附录A：参考文献与实现来源

- Qlib RollingGen机制: [microsoft/qlib Task Management](https://qlib.readthedocs.io/en/latest/advanced/task_management.html)
- Qlib LightGBM Alpha158配置: [workflow_config_lightgbm_Alpha158.yaml](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml)
- LightGBM GPU调优: [GPU Performance Guide](https://lightgbm.readthedocs.io/en/latest/GPU-Performance.html)
- LightGBM GPU教程: [GPU Tutorial](https://lightgbm.readthedocs.io/en/latest/GPU-Tutorial.html)
- Harvey, Liu, Zhu (2016): ... and the Cross-Section of Expected Returns（t > 2.5标准）
- Purge/Embargo设计参考: Lopez de Prado (2018) Advances in Financial Machine Learning, Chapter 7

---

## 附录B：关键数值速查（v2.0更新）

```
等权基线Sharpe:      1.15（Top-20+无行业约束新配置，V3.4确认）
保守基线Sharpe:      0.70-0.85（DSR校正后，V3.4确认）
fail-fast成功线:     OOS Sharpe ≥ 基线×1.2 且 p<0.05
过拟合预警:          trainIC/validIC > 2.0
过拟合硬停:          trainIC/validIC > 3.0
Fold总数:            7个（F1~F7）
有效OOS月数:         ~57个月（2021-07 ~ 2026-04）
训练样本/fold:       ~211万行（4000股×528天）
特征数:              48+个（factor_values表自动发现，v2.0更新）
GPU VRAM预估:        1-2GB（远低于12GB上限）
单fold训练时间:      <15分钟
Optuna总预算:        200轮（预计~5小时）
bootstrap次数:       1000次
Top-N:               20（V3.4新配置，v1.0为15）
Sprint 1.3b参照:     26特征/Sharpe=0.869/p=0.073/未通过
```

---

## 附录C：Sprint 1.3b完整结果（v2.0新增，历史对比基准）

```
实验配置:
  特征数: 26（5基线+12多尺度+9衍生）
  Walk-Forward: 7-fold，与本文档§1.3相同
  Optuna: 200轮，F1 fold
  基线: 等权5因子Top-15（Sharpe=1.03当时基线）

Fold-by-fold OOS IC:
  F1: 0.071  F2: 0.072  F3: 0.109  F4: 0.086
  F5: 0.100  F6: 0.044  F7: 0.095
  均值: 0.0823  一致性: 7/7正（100%）

Optuna最优超参:
  num_leaves=17, lr=0.033, min_child=74
  subsample=0.54, colsample=0.57, n_est=272
  改进: 仅+2.5%（默认超参已足够好）

最终评估:
  OOS Sharpe: 0.869  → FAIL（门槛1.10）
  p-value: 0.073     → FAIL（门槛0.05）
  连续亏损月: 4      → FAIL（门槛<3）
  trainIC/validIC: 1.51 → PASS
  MDD: -39.51%       → PASS
  Fold一致性: 100%   → PASS

SHAP发现:
  Top-5特征全部是基线因子
  扩展特征SHAP贡献很小
  结论: 26特征中21个扩展特征被基线因子信息覆盖

决策: NOT JUSTIFIED for go-live，部署为影子PT观察
```

---

## 附录D：G1.1-G1.7扩展路径提要（v2.0新增，详见V3.4 roadmap）

```
G1:   LightGBM Walk-Forward（本文档）
G1.1: 预测目标升级 → 回归→LambdaRank排名优化（1天）
G1.2: 时序特征增强 → 因子delta/delta2/3月堆叠（1天）
G1.3: XGBoost + CatBoost同架构训练（1-2天）
G1.4: 三模型Ensemble → 简单平均 → OOS加权（半天）
G1.5: 分位数回归 → 输出收益分布，不确定性调仓位（2天）
G1.6: MLP基线 + 四模型Stacking（特征池80+后，5天）
G1.7: Regime感知模型切换（5-7天）

前沿论文参考:
  QuantaAlpha(2026): GPT-5.2+LightGBM, CSI300 IC=0.1501, ARR=27.75%
  AlphaAgent(KDD 2025): AST去重+正则化探索, hit ratio+81%
  Dynamic GP+LightGBM(2026): GP三目标+滚动窗口, CSI300 Sharpe=1.59
```

---

> **版本历史**
> - v1.0 (2026-03-25): 初版，51特征，基线1.03
> - v2.0 (2026-04-04): 特征池48+(DB自动发现), 基线1.15, V3.4 fail-fast
> - v2.1 (2026-04-05): 特征池63+(15北向), GPU PyTorch cu128, TimescaleDB hypertable+Parquet缓存
