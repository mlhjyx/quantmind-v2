# 系统架构过时度评估

**日期**: 2026-04-10 | **来源**: Step 6 系列审计 + Qlib/RD-Agent对标

---

## 10维度过时度评估

| 维度 | 过时度 | 当前状态 | 设计 vs 代码差距 | 现代方法 |
|------|--------|---------|----------------|---------|
| **信号层** | 低 | 5因子等权+SN b=0.50, SignalComposer已实现 | 设计有CompositeSignalEngine但未实现 | Qlib Alpha158+IC加权/MV优化 |
| **回测层** | 低 | Phase 1.1完成: 841s→14.6s(Phase A索引优化), 8模块拆分 | VectorizedBacktester归档(Phase B非瓶颈) | 当前~15s满足需求 |
| **数据层** | 低 | PG+TimescaleDB+Parquet缓存, DataPipeline统一 | 基本按设计实现 | Qlib bin格式更快但迁移成本高 |
| **ML层** | 高 | LightGBM可用但验证无效(Sharpe=0.09) | 设计了完整ML pipeline但效果不佳 | Qlib Model Zoo, RD-Agent联合优化 |
| **风控层** | 中 | PMS v1.0 + L1-L4状态机设计但只L1在用 | L2-L4未实现 | 实时风控+组合级VaR |
| **执行层** | 低 | QMT Paper Trading + Servy管理 | 基本按设计实现 | 已够用, 不需要升级 |
| **前端层** | 高 | 12页面设计但实现未确认 | 设计精良但大部分可能未实现 | 优先级低, 后端稳定后再投入 |
| **外汇层** | N/A | 0%实现 | 完整设计但未启动 | A股未成熟前不启动 |
| **基础设施** | 低 | Servy+Redis+StreamBus+调度链路 | 清明改造后基本对齐 | 当前架构满足需求 |
| **研究工作流** | 中 | scripts/research/ 手动执行 | 无自动化pipeline | RD-Agent自动因子挖掘 |

---

## 优先级排序

### 高优先级（直接影响Sharpe）
1. **ML层**: 需要End-to-End方法或RD-Agent替代，当前predict-then-optimize失败
2. **信号层**: 需要新信号维度(行业动量/PEAD/北向)降低regime依赖

### 中优先级（提升效率）
3. **回测层**: ✅ Phase 1.1已完成(841s→14.6s)，不再是瓶颈
4. **研究工作流**: RD-Agent可自动化因子挖掘+评估

### 低优先级（当前够用）
5. **风控层**: PMS v1.0 + 基本风控满足当前需求
6. **前端层**: 后端稳定后再投入
7. **数据层/执行层/基础设施**: 当前方案满足需求
