---
name: quantmind-performance
description: QuantMind性能优化最佳实践。向量化计算、数据加载、内存控制。
trigger: 性能|慢|优化|内存|OOM|加速
---

# QuantMind Performance Skill

## 数据加载
- 大表(factor_values ~3.5亿行)按factor_name分批读取，不SELECT *
- klines_daily(~700万行)一次加载到内存pivot，不在循环内查
- daily_basic ffill填充缺失日期
- 北向数据(3.88M行)按需加载，不预加载全量

## 计算向量化
- 用pandas/numpy向量化而非Python for循环
- IC计算用scipy.stats.spearmanr而非手工排名
- rolling计算用pandas .rolling() 而非逐窗口切片
- 中性化用numpy.linalg.lstsq而非statsmodels.WLS

## 内存控制（32GB系统）
- 最多2个重数据Python进程同时运行（铁律9）
- 每个进程估计3-4GB（加载全量price_data）
- PG shared_buffers=2GB固定开销
- 因子计算完成后del大DataFrame释放内存

## forward return
- 从T+1入场（A股T+1制度）
- 预计算fwd_return pivot一次，多因子复用
- 不在循环内重复计算forward return

## 因子写入
- execute_values批量写入，每批5000行
- 写完一个因子commit一次，不累积大事务
- ON CONFLICT DO UPDATE保证幂等
