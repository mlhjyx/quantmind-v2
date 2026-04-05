---
name: quantmind-overnight-experiment
description: 过夜批量实验框架。参数网格自动串行回测，生成对比报告，内置反过拟合检查。
---

# QuantMind Overnight Experiment Framework

## 触发条件
- 用户给定参数网格要求批量回测
- 用户说"过夜跑"、"跑一批实验"、"参数搜索"

## 实验流程

### Step 1: 实验定义
接收参数网格定义（base_config + grid + metrics + train/OOS期）

### Step 2: 反过拟合检查（自动）
- 参数组合 > 30 → 警告过拟合风险
- 参数组合 > 100 → 拒绝执行
- 必须有train/OOS分割，OOS >= 12个月

### Step 3: 串行执行（自动）
- 逐个参数组合回测
- 每组完成后记录到CSV
- 打印进度: "实验 15/27 完成, 预计剩余 2小时"
- 串行执行不并行（铁律9）
- 每组间sleep 5秒

### Step 4: 结果分析（自动）
- 训练期最优 vs OOS最优差距 > 20% → 标注过拟合
- Sharpe改善但MDD恶化 → 标注trade-off

### Step 5: 报告（自动）
- docs/EXPERIMENT_<name>_<YYYYMMDD>.md
- 全部组合按OOS Sharpe排序
- 推荐最稳定参数（不是最高）
- 不自动部署到.env

## 约束
- 总时间 > 8小时 → 询问是否继续
- 某组报错 → 记录跳过继续
- 不自动部署最优参数
