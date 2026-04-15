# QuantMind V2 全面审计索引

> **目的**: 6-Session 全面审计的总索引 + 跨 session 发现计数 + P0 行动看板
> **启动**: 2026-04-15
> **当前 Session**: S1 进行中

---

## 📅 Session 进度

| # | 主题 | 状态 | 启动 | 完成 | 报告 |
|---|---|---|---|---|---|
| **S1** | 三角对齐（文档 / 代码 / DB） | 🟡 进行中 | 2026-04-15 | — | [S1_three_way_alignment.md](S1_three_way_alignment.md) |
| S2 | 一致性专项（PT ↔ 回测 ↔ 研究） | ⬜ 待开始 | — | — | — |
| S3 | 韧性与抗断（静默失败 / 错误恢复 / 监控） | ⬜ 待开始 | — | — | — |
| S4 | 动态基线验证（regression / pytest / diagnosis） | ⬜ 待开始 | — | — | — |
| S5 | 边界 + 血缘（时区 / QMT / 并发 / 生命周期） | ⬜ 待开始 | — | — | — |
| S6 | 方法论固化（不变量 / 契约 / 差分 / 金标） | ⬜ 待开始 | — | — | — |

---

## 📊 累计发现计数

| 分级 | 数量 | 已处理 | 未处理 |
|---|---|---|---|
| 🔴 P0 | 6 | **2** | 4 |
| 🟠 P1 | 10 | **6** (doc fixes) | 4 |
| 🟡 P2 | 6 | **1** | 5 |
| **合计** | **22** | **9** | **13** |

> 仅基于 S1 静态广扫 + S1 cleanup pass. S2-S6 会继续累加。

**S1 cleanup pass 处理** (2026-04-15 夜):
- ✅ F32 (token leak): 5 源码位置清洗 + 用户 rotate 4 组 key (**ZHIPU 待补**)
- ✅ F41 (V12_CONFIG): 已删除 + 加 tombstone 注释
- ✅ F38 (stale comment "基线5因子"): 随 V12_CONFIG 删除一并解决
- ✅ F1 (DEV_FOREX/NOTIFICATIONS 索引补齐)
- ✅ F10 (测试数 2076/90 → 98 test files)
- ✅ F14 (表数 45/17/62 → 47/26/73)
- ✅ F28 (factor_values 590M → 816M)
- ✅ F29 (minute_bars 139M → 191M)
- ✅ F18 注释补充 (async 遗留在 mining/backtest_service)
- ✅ F2 (archive 131 → 126)

---

## 🚨 P0 开放行动看板（按严重性降序）

| ID | 主题 | 负责人 | 状态 | Source |
|---|---|---|---|---|
| **F32** | API Token 泄漏 — **主线已清洗 + 4 key rotate 完成** | 用户 | 🟡 **ZHIPU_API_KEY 待补 rotate** | S1 |
| **F16** | Service 层 20+ 处 `.commit()` 违反"Service 不 commit"铁律 | — | ⬜ 待修（规模大，S3 处理）| S1 |
| **F17** | `factor_onboarding.py:538` + `factor_engine.py:2001` 绕过 DataPipeline 直接 INSERT | — | ⬜ 待修（S2 处理）| S1 |
| **F31** | `factor_engine.py:2001` Engine 层直接读写 DB | — | ⬜ 长期重构 | S1 |
| **F41** | `V12_CONFIG` 含 INVALIDATED 因子 | — | ✅ **2026-04-15 已删除** | S1 |
| **F45** | `config_guard` 不检查 SN/top_n/industry_cap | — | ⬜ S6 合并做 | S1 |

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
