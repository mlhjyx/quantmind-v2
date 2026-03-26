# QuantMind V2 — LightGBM Walk-Forward 训练框架设计文档

> **文档版本**: Sprint 1.4b
> **创建日期**: 2026-03-25
> **作者**: ML Agent (Sprint 1.4b)
> **关联文档**: DEV_BACKTEST_ENGINE.md, DEV_FACTOR_MINING.md, QUANTMIND_V2_DDL_FINAL.sql
> **硬性约束**: 铁律7 — OOS Sharpe < 基线1.03不上线；训练IC/OOS IC > 3倍 = 过拟合

---

## 0. 设计决策索引（本文档新增）

| # | 决策项 | 选择 | 理由 |
|---|--------|------|------|
| ML-01 | Walk-Forward模式 | 扩展窗口(expanding)首轮+固定窗口后续 | 早期数据不足时扩展，稳定后固定24月避免regime变化污染 |
| ML-02 | 目标变量 | T+20日vs沪深300超额收益(对数) | 月度调仓对齐，与基线Sharpe可比 |
| ML-03 | Purge gap | 训练集末尾到验证集开始留5交易日 | 防20日forward return信息泄露 |
| ML-04 | Embargo gap | 验证集末尾到测试集额外留0天 | Purge已足够，fold边界已对齐 |
| ML-05 | GPU策略 | device_type=gpu + max_bin=63 + gpu_use_dp=false | RTX 5070 VRAM 12GB，单精度快5-10倍 |
| ML-06 | 过拟合判定 | 训练IC/验证IC > 2.0警告, > 3.0强制停止 | 宽松一档，2倍阈值给early stopping余地 |
| ML-07 | Optuna目标函数 | validation set RankIC均值 | 比IC更稳定，抗异常值 |
| ML-08 | 特征数量 | 50-80个（不用Alpha158全集，选与现有5因子正交的新特征） | 减少噪声，控制VRAM |
| ML-09 | 上线条件(两级) | 上线: p<0.05 + Sharpe≥1.10 + 6红线; 优秀: Sharpe≥1.30 + p<0.01 | 用户确认 |
| ML-10 | 预测聚合 | 所有fold预测按时间拼接，不平均 | 保留时序连续性，与SimBroker回测对齐 |

---

## 1. 数据范围与时间分割

### 1.1 全量数据窗口

```
数据可用范围: 2020-07-01 → 2026-03-24
总长度: ~68个月

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
                                                              OOS Sharpe vs 基线1.03

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

### 2.2 特征分组（50-80个）

**组A：基线5因子（直接复用，共5个）**

```
A1. turnover_mean_20       - 换手率均值
A2. volatility_20          - 20日波动率
A3. reversal_20            - 20日反转
A4. amihud_20              - Amihud非流动性
A5. bp_ratio               - 账面市值比
```

**组B：基线因子的多尺度变体（捕捉非线性，共12个）**

```
B1.  turnover_mean_5       - 短期换手率（5日）
B2.  turnover_mean_60      - 长期换手率（60日）
B3.  turnover_trend_20     - 换手率趋势（20日均值/60日均值）
B4.  volatility_5          - 短期波动率（5日）
B5.  volatility_60         - 长期波动率（60日）
B6.  vol_regime            - 波动率regime（5日/60日比）
B7.  reversal_5            - 短期反转（5日）
B8.  reversal_60           - 长期反转（60日，动量因子）
B9.  amihud_5              - 短期非流动性（5日）
B10. amihud_60             - 长期非流动性（60日）
B11. bp_ratio_change_60    - BP变化率（60日delta）
B12. size_factor           - 市值因子（log总市值，控制因子）
```

**组C：资金流向维度（Sprint 1.3已验证IC=9.1%，共8个）**

```
C1.  mf_divergence         - 大单vs小单背离度（核心）
C2.  net_lg_ratio_5        - 大单净流入/成交额 5日
C3.  net_lg_ratio_20       - 大单净流入/成交额 20日
C4.  buy_sell_ratio_lg     - 大单买卖比（买/(买+卖)）
C5.  mf_acceleration       - 资金流入加速度（5日变化率）
C6.  lg_md_divergence      - 大单vs中单分歧
C7.  northbound_ratio_20   - 北向资金持股比例20日均值（如有）
C8.  margin_net_change_20  - 融资净变化率20日
```

**组D：价格行为特征（共10个）**

```
D1.  price_level           - 价格水平（Sprint 1.3已验证IC=8.42%）
D2.  high_low_range_20     - 20日高低价幅度
D3.  open_gap_20           - 20日平均跳空幅度（回测可信度规则5）
D4.  close_to_high_ratio   - 收盘相对最高价位置 20日均值
D5.  volume_price_trend    - 量价背离指标
D6.  up_down_vol_ratio     - 上涨日vs下跌日成交量比
D7.  rsi_20                - RSI（20日，检测超买超卖）
D8.  macd_signal           - MACD信号线方向
D9.  bollinger_position    - 布林带相对位置
D10. intraday_strength_20  - 日内强度（(close-open)/range）20日均值
```

**组E：财务基本面（季频，需PIT对齐，共8个）**

```
E1.  roe_ttm               - ROE（滚动12月）
E2.  roe_change_yoy        - ROE同比变化
E3.  gross_margin_ttm      - 毛利率（滚动）
E4.  revenue_yoy           - 营收同比增长
E5.  profit_yoy            - 净利润同比增长
E6.  debt_to_asset         - 资产负债率
E7.  current_ratio         - 流动比率
E8.  earnings_surprise_std - 盈利惊喜标准化（PEAD候选）
```

**组F：市场状态特征（宏观regime，共8个）**

```
F1.  csi300_return_20      - 沪深300近20日收益（市场方向）
F2.  csi300_vol_20         - 沪深300近20日波动（市场风险）
F3.  market_breadth_20     - 市场涨跌家数比（市场情绪）
F4.  industry_momentum_20  - 行业动量（所属行业vs全市场）
F5.  cross_stock_corr_20   - 截面相关性（高=系统性风险上升）
F6.  vix_proxy             - 隐含波动率代理（历史波动率的历史分位）
F7.  bull_bear_regime      - 牛熊状态（MA120判定，二值）
F8.  month_of_year         - 月份（季节性，用sin/cos编码）
```

**总特征数: 5+12+8+10+8+8 = 51个（在50-80范围内）**

### 2.3 特征预处理流水线（严格遵守铁律顺序）

```python
# 预处理顺序（与CLAUDE.md因子计算规则完全一致）:
# 1. MAD去极值（基于训练集的中位数和MAD）
# 2. 缺失值填充（截面中位数填充）
# 3. 中性化（回归掉市值+行业，保留残差）
# 4. zscore标准化（使用训练集的均值和标准差）

# 关键：所有预处理参数在train set上fit，
# 用fit后的参数transform valid set和test set
# 这是防止数据泄露的核心！

class FeaturePreprocessor:
    def fit(self, train_df: pd.DataFrame) -> 'FeaturePreprocessor':
        # 1. 计算每个特征的中位数和MAD（用于去极值）
        # 2. 计算行业哑变量和市值（用于中性化）
        # 3. 计算zscore参数（均值、std，中性化后）
        pass

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        # 按fit好的参数依次执行4步
        pass
```

### 2.4 目标变量定义

```
target = log(1 + r_stock_t+20) - log(1 + r_csi300_t+20)

其中:
  r_stock_t+20  = 股票T到T+20交易日的复权收益率
  r_csi300_t+20 = 沪深300同期收益率

计算约束:
  - 使用复权价格（close × adj_factor）
  - 停牌期间（volume=0）：目标变量设为NaN，从训练集中删除该行
  - 退市前5日：目标变量设为实际退市收益，包含在训练集
  - T+20不满（接近当前日期）：整行删除，不预测未来
```

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
  特征数: 51
  float32精度: 4字节
  原始数据: 211万 × 51 × 4字节 = ~430MB
  LightGBM直方图(max_bin=63): 数据量约压缩到原始的20%→~90MB
  GPU VRAM使用: 数据 + 模型 + 梯度 ≈ 1-2GB（远低于12GB上限）

结论: RTX 5070 12GB VRAM完全满足，每fold训练预计<15分钟
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
  F1训练集: 211万行 × 51特征
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

层3 - OOS最终评估（Sharpe比较）:
  所有fold预测拼接 → SimBroker回测
  OOS Sharpe < 基线1.03 → 不上线（铁律7）
  paired bootstrap p >= 0.05 → 不上线（不显著）
  2x成本Sharpe < 0.5 → 不上线（成本敏感性）
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
│  ├─ FeatureLoader（从PG factor_values读取）                  │
│  ├─ FeatureBuilder（计算B/C/D/E/F组新特征）                  │
│  └─ FeaturePreprocessor（MAD→填充→中性化→zscore）            │
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
│  ├─ 预测值 → 月底截面排名 → Top15持仓                        │
│  ├─ SimBroker回测（涨跌停/整手约束/T+1）                      │
│  └─ OOS Sharpe vs 基线1.03（铁律7）                         │
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

Step 1: 特征构建
  ├─ 从factor_values表加载5个基线因子（A组）
  ├─ 从klines_daily/moneyflow/fina_indicator计算B-F组特征
  ├─ 合并形成完整特征矩阵（约4000股×68月×51特征）
  ├─ 计算目标变量（T+20日超额收益）
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
  ├─ 月底截面：按预测值排名，选Top15
  ├─ 传入SimBroker回测（2021-07 ~ 2026-03）
  ├─ 应用完整交易规则（涨跌停/整手/T+1/成本）
  └─ 生成回测报告（含所有CLAUDE.md要求的指标）

Step 5: 上线判断（两级标准）
  上线标准: paired bootstrap p < 0.05 + OOS Sharpe ≥ 1.10 + 6条红线全过
  优秀标准: OOS Sharpe ≥ 1.30 + p < 0.01
  检验1: OOS Sharpe ≥ 1.10？
    └─ NO → 不上线，记录到LESSONS_LEARNED
  检验2: paired bootstrap p < 0.05？
         （ML策略 vs 等权基线的Sharpe差异显著性）
    └─ NO → 不上线，记录原因
  检验3: 2x成本下Sharpe > 0.5？
    └─ NO → 不上线，成本敏感性不足
  ALL PASS → 提交approval_queue，等待人工审批
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
    "n_features": 51,
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
| OOS Sharpe < 1.019（铁律7）| 中 | ML方案失败 | LESSONS_LEARNED记录失败原因；不强行上线 |
| 所有fold过拟合 | 中 | 等权天花板也适用于ML | 分析哪类特征过拟合；尝试更强正则 |
| A股2024年风格剧变影响OOS | 高 | F6/F7 fold IC差 | 在报告中单独分析2024年fold；考虑regime-aware训练 |
| ML信号换手率远超等权 | 中 | 成本吃掉Alpha | 计算年化换手率；如>300%需加换手率约束项 |

### 8.3 Go/No-Go决策树

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
    OOS Sharpe ≥ 1.019?
    NO → 不上线，记录失败 → 复盘因子工程
    YES → 继续检验

    paired bootstrap p < 0.05?
    NO → 样本不足或效果不稳定，继续Paper Trading观察
    YES → 继续检验

    2x成本Sharpe > 0.5?
    NO → 实盘成本会吃掉Alpha，不上线
    YES → 提交人工审批 → approval_queue
```

---

## 9. 与现有系统的集成点

### 9.1 复用的模块

```
SimBroker: 直接复用，ML策略传入的是月底截面的预测值排名
           SimBroker不需要知道是ML预测还是等权因子

因子预处理: 复用FactorService的中性化和zscore逻辑
           不重写，确保与等权基线完全一致的预处理方式

回测报告: 复用PerformanceService，生成CLAUDE.md要求的全部指标
          新增：按fold分解的IC时序图

Task Scheduler: Walk-Forward训练作为新的Celery task
               与现有每日信号生成task共享GPU但时间错开
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

这与现有strategy_configs版本管理机制一致
```

---

## 10. 执行检查表（实现前验证）

在开始代码实现前，以下前置条件必须满足：

```
□ factor_values表数据确认（2020-07-01开始，5因子均有记录）
□ klines_daily/moneyflow/fina_indicator表数据完整（用于B-F组特征）
□ RTX 5070 GPU驱动确认（nvidia-smi可见，CUDA版本检查）
□ LightGBM GPU版本安装验证（import lightgbm; lgb.Dataset.__module__）
□ Optuna安装（pip install optuna optuna-integration）
□ 交易日历完整（2020-07 ~ 2026-03，用于Purge gap计算）
□ SimBroker与等权基线跑通（有参照Sharpe=1.03可以比较）
□ ml_predictions表创建（本文档7.1节DDL）
□ CLAUDE.md铁律7确认（OOS Sharpe<1.019不上线，无例外）
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

## 附录B：关键数值速查

```
基线Sharpe:          1.019（Windows环境，2021-2025全期）
ML上线阈值:          OOS Sharpe ≥ 1.10 + p < 0.05（优秀: ≥1.30 + p<0.01）
过拟合预警:          trainIC/validIC > 2.0
过拟合硬停:          trainIC/validIC > 3.0（CLAUDE.md铁律7）
Fold总数:            7个（F1~F7）
有效OOS月数:         57个月（2021-07 ~ 2026-03）
训练样本/fold:       ~211万行（4000股×528天）
特征数:              51个（A~F六组）
GPU VRAM预估:        1-2GB（远低于12GB上限）
单fold训练时间:      <15分钟（满足30分钟约束）
Optuna总预算:        200轮（预计~5小时，分次运行）
bootstrap次数:       1000次（CLAUDE.md回测可信度规则4）
```
