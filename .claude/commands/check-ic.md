# /check-ic

快速检查一个因子的IC和基本统计量。

## 使用方式
```
/check-ic <factor_name>
```

## 执行步骤

1. 从factor_ic_history查询该因子的最新IC记录:
```sql
SELECT factor_name, trade_date, ic_1d, ic_5d, ic_10d, ic_20d, decay_level
FROM factor_ic_history
WHERE factor_name = '<factor_name>'
ORDER BY trade_date DESC LIMIT 5;
```

2. 从factor_profile查询画像数据:
```sql
SELECT factor_name, recommended_template, ic_20d, ic_20d_tstat,
       monotonicity, coverage, max_corr_with, regime_sensitivity,
       cost_feasible, keep_recommendation
FROM factor_profile
WHERE factor_name = '<factor_name>';
```

3. 输出汇总:
- IC_20d + t统计量 (t>2.5=Active, 2.0-2.5=Marginal, <2.0=Weak)
- 推荐模板 (1=月度, 2=周度, 7=事件, 11=Modifier, 12=Regime)
- 与核心因子的最大相关性 (max_corr_with)
- Regime敏感性 + 方向是否反转
- 成本可行性
- 是否在Active池中 (keep_recommendation)

4. 如果factor_ic_history无记录 -> 警告"铁律11: IC无可追溯记录"
