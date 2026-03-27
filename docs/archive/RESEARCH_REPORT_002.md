# QuantMind V2 — 合伙人研究报告 #2

> 研究者：Claude（项目合伙人）
> 日期：2026-03-23
> 服务阶段：Sprint 1.3b + Sprint 1.8预研
> 3个课题全部完成

---

## 课题1：A股月度调仓的最优执行方式

### 核心问题

我们的策略月末生成信号，T+1日执行。当前Paper Trading用开盘价一次性下单。实盘100万资金+Top15（每只约6.5万），是否需要TWAP/VWAP拆单？

### 研究结论

**100万规模不需要TWAP/VWAP。直接用限价单即可。**

理由：
- TWAP/VWAP的核心场景是大资金避免市场冲击——单笔6.5万（约1000-5000股），对A股日均成交额数千万到数亿的股票完全无冲击
- BigQuant实测：使用TWAP/VWAP价格回测 vs 使用开盘价回测，各项指标变化极小，"一定程度上表明单一策略的资金容量比想象的大很多"
- VWAP需要分钟级数据预测日内成交量分布——我们当前只有日频数据，且miniQMT的委托接口不支持原生TWAP/VWAP算法
- 拆单增加了工程复杂度（需要日内定时器、分钟级行情、部分成交处理），但100万级别收益极小

**但有两个执行优化值得做（成本低收益确定）：**

**优化1：避开开盘集合竞价，改用9:35-9:45限价单**
- 开盘集合竞价(9:15-9:25)波动大、spread大，用开盘价买入可能吃到较大滑点
- 9:30开盘后5-15分钟市场消化了隔夜信息，价格更稳定
- 实现简单：crontab的execute阶段从09:00改为09:35，用前一分钟收盘价作为限价

**优化2：涨跌停封板检查+补单机制**
- 调仓日某只目标股票涨停→买不进去→当日跳过→次日补单
- 某只持仓股票跌停→卖不出去→当日跳过→次日补单
- Sprint 1.3b已经在做封板补单机制（#5），方向正确

**优化3（资金>500万后再考虑）：简单TWAP**
- 将6.5万的单子拆成3笔，分别在9:35/10:30/13:30下单
- 只需要3个定时器，不需要分钟级行情
- 实现简单但100万级别改善<5bps（约50元/月）

### 对QuantMind的建议

| 行动 | 什么时候 | 优先级 |
|------|---------|--------|
| execute改为09:35限价单（不用开盘价） | Sprint 1.5 miniQMT对接时 | P1 |
| 封板补单机制 | Sprint 1.3b（已在做） | P0 |
| TWAP三笔拆单 | 资金>500万后 | P3 |
| 完整VWAP | 不需要 | — |

---

## 课题2：因子池扩展后的多重检验校正（BH-FDR）

### 核心问题

我们的因子池从5个扩展到20+个，alpha_miner已经测试了40+候选。测试越多，发现"假阳性因子"的概率越大。怎么控制？

### 学术背景

Harvey, Liu & Zhu (2016) "...and the Cross-Section of Expected Returns"（RFS, 被引2783次）是因子多重检验的奠基论文。核心结论：

- 到2012年已有316个因子被学术界"发现"
- 用传统t>2.0标准，大量因子是假阳性（数据挖掘结果）
- 考虑多重检验后，新因子需要t>3.0才算显著
- "金融经济学中大多数声称的研究发现可能是假的"

**但Andrew Chen (2021) 反驳**：用更精确的FDR估计方法发现，实际FDR可能只有12%（不是Harvey声称的50%+）。Jensen, Kelly & Pedersen (2023)也发现FDR约1%。

**实操结论**：Harvey的t>3.0过于严格，但传统t>2.0过于宽松。实际操作应该用BH-FDR方法控制在FDR<5-10%。

### BH-FDR在我们项目中怎么做

**Benjamini-Hochberg (BH) 程序——quant已经在用，但需要规范化：**

```python
import numpy as np
from scipy import stats

def bh_fdr_correction(p_values, alpha=0.05):
    """
    BH-FDR多重检验校正
    输入：所有候选因子的p值列表
    输出：哪些因子通过校正后仍然显著
    """
    m = len(p_values)
    # 1. 将p值从小到大排序
    sorted_indices = np.argsort(p_values)
    sorted_p = p_values[sorted_indices]
    
    # 2. 计算BH阈值：p(k) <= k/m * alpha
    bh_thresholds = np.arange(1, m+1) / m * alpha
    
    # 3. 找到最大的k使得p(k) <= 阈值
    significant = sorted_p <= bh_thresholds
    
    # 4. k及之前的所有因子都显著
    if significant.any():
        max_k = np.max(np.where(significant))
        results = np.zeros(m, dtype=bool)
        results[sorted_indices[:max_k+1]] = True
        return results
    return np.zeros(m, dtype=bool)
```

**实际操作——对我们项目的具体规则：**

1. **每批因子审批时**：alpha_miner提交N个候选，quant对所有N个的t统计量做BH-FDR校正（alpha=0.05），只有校正后仍显著的才通过
   - 这quant已经在做了（reversal_60就是被BH-FDR否决的）

2. **累积测试惩罚**：alpha_miner已经测试了40+候选，未来会更多。每增加一个测试，所有因子的显著性阈值都应该上升
   - 实操：维护一个FACTOR_TEST_REGISTRY（所有曾经测试过的因子，不管通过还是否决）
   - 每次审批时，用累积测试总数M作为BH-FDR的分母，不只是当批N个
   - 这样测试越多，阈值越严——防止alpha_miner通过"多试几次"来碰运气

3. **t>3.0作为硬性下限**：
   - Harvey的建议是t>3.0（考虑到整个金融学的因子zoo有300+因子）
   - 我们项目的因子zoo目前约40个，不需要那么严格
   - 折中方案：t>2.5作为硬性下限（不管BH-FDR结果如何），t>2.0但<2.5的需要额外的经济学解释支撑

4. **DSR作为策略级别的校正**：
   - BH-FDR是因子级别的多重检验（每个因子独立测试）
   - DSR是策略级别的校正（考虑了你测试过的所有策略配置）
   - 两者互补：因子过BH-FDR + 策略过DSR = 双重保护
   - 我们的DSR=0.591"可疑"——正是因为测试了多个配置（Top15/20, 5/6/7/8因子, 对冲/无对冲）

### 对QuantMind的建议

| 行动 | 什么时候 | 负责 |
|------|---------|------|
| 创建FACTOR_TEST_REGISTRY.md（记录所有测试过的因子） | 立刻 | alpha_miner |
| 每次审批用累积M做BH-FDR | 立刻 | quant |
| t>2.5硬性下限写入CLAUDE.md | Sprint 1.3b | quant |
| DSR在每次配置变更后重新计算 | Sprint 1.2b（已做） | quant |

---

## 课题3：LightGBM在A股选股的特征工程最佳实践

### 核心问题

Sprint 1.8要引入LightGBM替代/增强等权合成。用什么特征、怎么训练、怎么避免过拟合？

### Qlib Alpha158 benchmark

微软Qlib在A股CSI300上的官方benchmark：
- LightGBM + Alpha158（158个因子）：IC=0.0399, ICIR=0.4065, 年化12.84%, MDD -6.35%
- 这是"工业级基线"——我们的目标是达到或超过这个水平

### 特征工程最佳实践（综合Qlib+券商研报+学术论文）

**特征维度（4大类，约50-80个特征）：**

```
维度1：量价特征（30-40个）——我们已有
- 收益率类：ret_5/10/20/60, reversal_5/10/20
- 波动率类：volatility_20/60, ivol_20
- 换手率类：turnover_mean_20, turnover_surge
- 流动性类：amihud_20, relative_volume
- 量价关系：price_volume_corr, mf_divergence
- 技术指标：RSI_14, MACD_diff, KDJ_K（通过TA-Lib）
- KBAR形态：body_ratio, amplitude, upper_shadow

维度2：基本面特征（10-15个）——Sprint 1.3扩展
- 估值类：bp_ratio, ep_ratio, ps_ratio
- 盈利类：roe_ttm, gross_margin
- 成长类：revenue_yoy, profit_yoy（需PIT对齐）
- 质量类：debt_to_asset, current_ratio
- 股息类：dv_ttm

维度3：资金流特征（5-8个）——data刚拉了moneyflow
- 大单净流入/总成交：net_mf_amount_20 / total_amount
- 资金流动量背离：mf_momentum_divergence
- 主力资金占比变化

维度4：截面排名特征（衍生）
- 对上述所有特征做cs_rank（截面排名0-1标准化）
- LightGBM对排名特征比原始值更鲁棒（不受极端值影响）
```

**训练标签：**

```
标签 = 未来20日超额收益（相对沪深300）
- 不用绝对收益——绝对收益包含Beta，不是选股Alpha
- 20日 = 与月度调仓频率匹配
- 用超额收益 = 沪深300日收益率之差的20日累积
```

**训练方式：Walk-Forward滚动训练**

```
窗口配置（A股推荐）：
- 训练窗口：24个月（~500个交易日）
- 验证窗口：6个月（Optuna超参搜索用）
- 测试窗口：1个月（纯OOS）
- 每月滚动一次

为什么不用更长训练窗口：
- A股市场结构变化快（注册制/北向资金/量化崛起）
- 太长的历史数据可能包含"已过时"的模式
- 24个月足够LightGBM学到当前regime的特征
```

**LightGBM超参推荐（A股选股场景）：**

```python
params = {
    'objective': 'regression',     # 回归预测超额收益
    'metric': 'mse',
    'boosting_type': 'gbdt',
    'num_leaves': 63,              # 不要太大，防过拟合
    'max_depth': 7,                # 限制树深度
    'learning_rate': 0.05,         # 小学习率+多轮
    'n_estimators': 500,           # 配合early_stopping
    'min_child_samples': 100,      # A股3000+股，每叶至少100样本
    'subsample': 0.8,              # 行采样
    'colsample_bytree': 0.8,      # 列采样
    'reg_alpha': 0.1,              # L1正则
    'reg_lambda': 1.0,             # L2正则
    'early_stopping_rounds': 50,   # 验证集连续50轮不改善就停
}
```

**关键：用Optuna做超参搜索，不要手动调**

```python
import optuna

def objective(trial):
    params = {
        'num_leaves': trial.suggest_int('num_leaves', 31, 127),
        'max_depth': trial.suggest_int('max_depth', 5, 10),
        'learning_rate': trial.suggest_float('lr', 0.01, 0.1, log=True),
        'min_child_samples': trial.suggest_int('min_child', 50, 200),
        'subsample': trial.suggest_float('subsample', 0.6, 1.0),
        'colsample_bytree': trial.suggest_float('colsample', 0.6, 1.0),
        'reg_alpha': trial.suggest_float('reg_alpha', 0.01, 1.0, log=True),
        'reg_lambda': trial.suggest_float('reg_lambda', 0.1, 10.0, log=True),
    }
    # 用验证集IC作为优化目标
    val_ic = train_and_evaluate(params)
    return val_ic

study = optuna.create_study(direction='maximize')
study.optimize(objective, n_trials=200)
```

**防过拟合三重保护：**

1. **Walk-Forward**：每月重训，OOS评估，不用未来数据
2. **特征重要性过滤**：训练后看feature_importance，重要性<1%的特征在下轮删除
3. **与等权基线对比**：LightGBM选股的OOS Sharpe必须>等权合成的OOS Sharpe才有价值。如果LightGBM还不如等权（很常见！），说明过拟合了

**Stacking融合（进阶，Phase 1C后期）：**

学术论文和券商研报都推荐Stacking融合：
- 第一层：LightGBM + XGBoost + RandomForest各自独立预测
- 第二层：用AdaBoost或简单线性回归融合三个模型的预测值
- 融合后通常比单模型提升5-15% IC

但这增加了3倍训练时间和复杂度。建议先用单LightGBM做到stable positive OOS IC，再考虑Stacking。

### 对QuantMind的建议

| 行动 | 什么时候 | 负责 |
|------|---------|------|
| 确认特征集（4维度50-80个）| Sprint 1.8规划时 | factor+ml |
| 训练标签用20日超额收益 | Sprint 1.8 | ml+quant |
| Walk-Forward 24m/6m/1m配置 | Sprint 1.8 | ml+arch |
| Optuna超参搜索200轮 | Sprint 1.8 | ml |
| 与等权基线A/B对比 | Sprint 1.8验收标准 | quant |
| Stacking融合 | Phase 1C后期 | ml |
| 特征做cs_rank预处理 | Sprint 1.8 | ml+factor |

---

## 总结——研究报告#2行动项

| # | 行动项 | 优先级 | Sprint | 负责 |
|---|--------|--------|--------|------|
| 1 | execute改为09:35限价单 | P1 | 1.5 miniQMT | arch |
| 2 | 封板补单机制 | P0 | 1.3b（已在做） | arch |
| 3 | 创建FACTOR_TEST_REGISTRY.md | P1 | 立刻 | alpha_miner |
| 4 | BH-FDR用累积测试总数M | P1 | 立刻 | quant |
| 5 | t>2.5硬性下限写入CLAUDE.md | P1 | 1.3b | quant |
| 6 | LightGBM特征集4维度规划 | P2 | 1.8规划 | factor+ml |
| 7 | 训练标签=20日超额收益 | P2 | 1.8 | ml+quant |
| 8 | A/B对比：LightGBM vs 等权 | P2 | 1.8验收 | quant |

---

## 下一期研究预告（研究报告#3）

服务Sprint 1.5（miniQMT对接）和Sprint 1.6（AI因子挖掘）：

1. **miniQMT对接实战**：Windows VM桥接方案、Mac↔VM通信、API限制和踩坑
2. **LLM因子挖掘的真实效果**：RD-Agent论文复现了吗？DeepSeek做因子假设生成的prompt最佳实践
3. **A股因子生命周期管理**：因子从发现→入池→衰减→退出的完整管理框架
