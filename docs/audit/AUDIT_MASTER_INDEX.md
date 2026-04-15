# QuantMind V2 全面审计索引

> **目的**: 6-Session 全面审计的总索引 + 跨 session 发现计数 + P0 行动看板
> **启动**: 2026-04-15
> **当前 Session**: S1 进行中

---

## 📅 Session 进度

| # | 主题 | 状态 | 启动 | 完成 | 报告 |
|---|---|---|---|---|---|
| **S1** | 三角对齐（文档 / 代码 / DB） | ✅ 完成 | 2026-04-15 | 2026-04-15 | [S1_three_way_alignment.md](S1_three_way_alignment.md) |
| **S2** | 一致性专项（PT ↔ 回测 ↔ 研究） | ✅ 静态完成 | 2026-04-15 | 2026-04-15 | [S2_consistency.md](S2_consistency.md) |
| S3 | 韧性与抗断（静默失败 / 错误恢复 / 监控） | ⬜ 待开始 | — | — | — |
| S4 | 动态基线验证（regression / pytest / diagnosis） | ⬜ 待开始 | — | — | — |
| S5 | 边界 + 血缘（时区 / QMT / 并发 / 生命周期） | ⬜ 待开始 | — | — | — |
| S6 | 方法论固化（不变量 / 契约 / 差分 / 金标） | ⬜ 待开始 | — | — | — |

---

## 📊 累计发现计数

| 分级 | S1 | S2 新增 | 总计 | 已处理 | 未处理 |
|---|---|---|---|---|---|
| 🔴 P0 | 6 | 3 (F51/F60/F62) | 9 | **4** (F32 闭 + F41 闭 + F62 改 default + F51/F60 加 DEPRECATED) | 5 |
| 🟠 P1 | 10 | 6 (F50/F52/F54/F55/F57/F58/F63/F65) | **16** | **8** (S1 doc fixes 6 + F52 guard + F65 fix + F40 合并) | 8 |
| 🟡 P2 | 6 | 2 (F56/F64) | 8 | **2** | 6 |
| ✅ 关闭/修正 | — | F17 部分关闭 + F64 PASS | — | — | — |
| **合计** | **22** | **11** | **33** | **14** | **19** |

> S1 静态广扫 + S1 cleanup pass + S2 一致性专项（静态 + 4 快修）已完成。

**S1 cleanup pass 处理** (2026-04-15 夜):
- ✅ F32 (token leak): 5 源码位置清洗 + 用户 rotate 所有 key (含 ZHIPU revoke)
- ✅ F41 (V12_CONFIG): 已删除 + 加 tombstone 注释
- ✅ F38 (stale comment "基线5因子"): 随 V12_CONFIG 删除一并解决
- ✅ F1 (DEV_FOREX/NOTIFICATIONS 索引补齐)
- ✅ F10 (测试数 2076/90 → 98 test files)
- ✅ F14 (表数 45/17/62 → 47/26/73)
- ✅ F28 (factor_values 590M → 816M)
- ✅ F29 (minute_bars 139M → 191M)
- ✅ F18 注释补充 (async 遗留在 mining/backtest_service)
- ✅ F2 (archive 131 → 126)

**S2 快修 pass 处理** (2026-04-15 夜):
- ✅ F62 (PT_SIZE_NEUTRAL_BETA default 0.0 → 0.50)
- ✅ F15/F65 (硬编码 DB 密码 fallback 改为 placeholder + raise)
- ✅ F40 (SignalConfig default 对齐 PT CORE3+dv_ttm + monthly + SN=0.50)
- ✅ F52 (compute_batch_factors DeprecationWarning + 注释)
- ✅ F51/F60 (factor_onboarding IC 函数 DEPRECATED warning + 注释, 中期重构留给 S2b)
- ✅ F17 部分关闭 (PT 生产路径 save_daily_factors 走 DataPipeline, factor_engine:2001 是 dead code)
- ✅ F64 (成本模型 backtest/pt_live/broker 三处对齐 PASS 验证)

---

## 🚨 P0 开放行动看板（按严重性降序）

| ID | 主题 | 负责人 | 状态 | Source |
|---|---|---|---|---|
| **F32** | API Token 泄漏 | 用户 | ✅ **全线关闭** 2026-04-15 | S1 |
| **F41** | `V12_CONFIG` 含 INVALIDATED 因子 | — | ✅ **2026-04-15 已删除** | S1 |
| **F62** | `PT_SIZE_NEUTRAL_BETA` default=0.0 静默降级 | — | ✅ **2026-04-15 default→0.50** | S2 |
| **F16** | Service 层 20+ 处 `.commit()` 违反铁律 | — | ⬜ 待修（S3 规模化处理）| S1 |
| **F17** | factor_onboarding 绕过 DataPipeline + 中性化不完整 | — | 🟡 DEPRECATED 告警加上, 中期重构转 S2b | S1/S2 |
| **F31** | `factor_engine.py` Engine 层读写 DB（2034 行巨石） | — | ⬜ 长期重构（F43 一起） | S1/S2 |
| **F45** | `config_guard` 不检查 SN/top_n/industry_cap | — | ⬜ S6 合并做 | S1 |
| **F51/F53/F60** | factor_onboarding IC 违反铁律 19 + 前瞻偏差 | — | 🟡 DEPRECATED 告警加上, 中期 S2b 重构 | S2 |
| **F63** | 前端 API 覆盖缺口（12 vs 21） | — | ⬜ S5 前端契约深扫 | S2 |

---

## 📂 长期工件路线图

S6 产出（尚未开始）：
```
scripts/audit/
├── invariant_check.py       # 每日自动跑的不变量检查
├── pt_vs_backtest_diff.py   # 回测 vs PT 差分对比
├── golden_factor_set.py     # 金标因子值集
├── contract_lock.py         # 前后端契约 snapshot
└── config_drift_check.py    # 三处配置漂移检测
```

---

## 🔗 相关文档

- `CLAUDE.md` — 项目入口 + 30 条铁律
- `SYSTEM_STATUS.md` — 系统现状全景
- `FACTOR_TEST_REGISTRY.md` — 因子测试注册表（累积测试数 M）
- `LESSONS_LEARNED.md` — 49 条经验教训
- `docs/audit/` — 本审计系列（你正在看的）
