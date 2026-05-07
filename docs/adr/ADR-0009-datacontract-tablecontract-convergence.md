---
adr_id: ADR-0009
title: DataContract (Platform) vs TableContract (App) — 延迟收敛策略
status: accepted
related_ironlaws: [17, 23, 24, 38]
recorded_at: 2026-04-18
---

## Context

当前项目存在**双 Contract 并轨**, 职责重叠但 schema 表达力不同:

| Contract | 所在 | 行数 | schema 表达 | 用途 |
|---|---|---|---|---|
| `DataContract` (Platform) | `backend/platform/data/interface.py` | MVP 1.1 frozen ABC, 字段少 | `{"close": "float64 元"}` 字符串编码 | `DataSource.fetch/validate` 签名, 外部拉取契约 |
| `TableContract` (App) | `backend/app/data_fetcher/contracts.py` | 12 实例 + 1 registry | `ColumnSpec(dtype, nullable, min/max, unit)` 强类型 | `DataPipeline.ingest` 入库管道, FK 过滤, 单位转换 |

**调用点矩阵** (MVP 2.1b 交付后, 2.1c Sub3 开工前):

- 新 DataSource (Platform) 侧: `BaostockDataSource` / `QMTDataSource` / `TushareDataSource` 各带自己的 `DataContract` (Platform ABC 要求)
- 老 fetcher (App) 侧: 3 生产脚本 `fetch_base_data.py` / `fetch_minute_bars.py` / `qmt_data_service.py` **直接调** `DataPipeline.ingest(df, KLINES_DAILY_TABLE_CONTRACT)` (App 侧 TableContract)
- 桥接层: MVP 2.1b 3 DataSource 内部**同时持有**两份 Contract (Platform DataContract for `fetch` 签名 + 内部 rename/validate 调 App TableContract for ingest)

**Contract 调用点总数**: 8 个生产 path 混合两套, 代码重复 rename_map + schema 定义.

## Decision

**延迟收敛 — 本 ADR 只决议方向 + 触发条件, 不实施**.

具体:
1. **MVP 2.2 Data Lineage 期间**: 继续双 Contract 并轨, 不动. Lineage 写入的 `outputs: list[LineageRef]` 用 `LineageRef(table=str, pk_values=dict)` 最弱耦合表达, **不依赖任一 Contract**.
2. **MVP 2.1c Sub3 完结后** (预计 2026-04-25+): 老 3 fetcher 退役, Contract 调用点从 8 → 3 (仅新 3 DataSource). **此时重新评估收敛**.
3. **触发条件** (以下任一满足 → 启动 Contract 收敛专项):
 - (a) MVP 2.3 Backtest Parity 设计时, `backtest_run` 表 schema 引入 UUID/JSONB/TEXT[]/DECIMAL[] 混合类型, 两套 Contract 表达能力差异造成重复
 - (b) MVP 3.0 ROF 启动时, 资源声明需要绑定 Contract 元数据 (e.g. contract × resource_profile 映射)
 - (c) 触发新增第 4 条数据管道 (e.g. JoinQuant / WindDF), 发现每次必须同步两套 Contract 成本显化

## Alternatives Considered

| 选项 | 代价 | 优点 | 为何不选 |
|---|---|---|---|
| **D. 延迟收敛 ⭐** | 0 (本 MVP) + ~800 行 (触发后) | 不阻塞 MVP 2.2 Data Lineage; 调用点从 8→3 减少后收敛成本 halving; 触发条件清晰 | — (选此) |
| A. 立即合 Platform DataContract → App TableContract | ~400 行, 改 MVP 1.1 ABC 签名 | Platform 侧强类型 | **MVP 1.1 ABC 已锁 (铁律 38 SSOT)**, 破坏 Wave 1 稳定. 且 Platform 层不应依赖 App 层 ColumnSpec 数据类型 |
| B. 立即合 App TableContract → Platform DataContract | ~600 行, 弱化 ColumnSpec 表达力 | Platform SSOT | 丢失 ColumnSpec 的 dtype/min/max/unit 元数据 → DataPipeline 失去 validation 能力 → 铁律 17 降级 |
| C. 新建统一 `UnifiedContract` 替换两者 | ~1200 行, 全链路替换 | 干净, 一套 schema | 工程量最大; 2.1b 3 DataSource 刚交付, 替换造成 regression 风险; 违反铁律 23 独立可执行 |

## Consequences

**正面**:
- MVP 2.2 Data Lineage scope 纯净 (不被 Contract 收敛拖累, 保铁律 24 ≤ 2 页)
- 收敛时间推到 MVP 2.1c Sub3 完结后, 调用点基数从 8 → 3, 收敛成本 halving
- 保留双轨 interim period 让 2.1c Sub3 真实退役过程暴露隐藏耦合, 再做收敛决策信息更足
- ADR-0009 入 knowledge_registry.adr_records, Wave 3 启动时自动 surface 为触发条件检查项

**负面**:
- MVP 2.2 及之后的 `Lineage.inputs/outputs` 类型表达最弱 (dict + str), 未来收敛后若想让 Lineage 直接引用 Contract 需要 migration
- 双 Contract 并轨期间任何 schema 变更 (新加字段) 必须改两处, 遗漏风险
- 新加入项目的开发者 (单人项目无此风险但架构纪律仍适用) 需要理解双轨原因

**缓解**:
- 双 Contract 变更清单加到 `memory/project_sprint_state.md` 下一个 handoff "Wave 2 遗留技术债 allocation" 段落
- MVP 2.3 / MVP 3.0 开工前 checklist 强制 review 本 ADR 触发条件

## References

- `backend/platform/data/interface.py::DataContract` (MVP 1.1 Platform ABC)
- `backend/app/data_fetcher/contracts.py::TableContract` (App layer, 12 实例 + CONTRACT_REGISTRY)
- `docs/mvp/MVP_2_2_data_lineage.md` §D1/D2 (`Lineage` 用最弱耦合 `dict + str`, 不依赖任一 Contract)
- `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` Part 4 L1204-1217 (MVP 2.2/2.3 范围)
- ADR-006 (Data Framework 3 fetcher 策略, Template method) — 本 ADR 是其延伸决策
- 铁律 17 (DataPipeline 入库) / 23 (独立可执行) / 24 (MVP ≤ 2 页) / 38 (Blueprint SSOT)
- `memory/project_sprint_state.md` "Wave 2 遗留技术债 allocation" Session 4 段
