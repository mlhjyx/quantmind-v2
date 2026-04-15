# QuantMind V2 全面审计索引

> **目的**: 6-Session 全面审计的总索引 + 跨 session 发现计数 + P0 行动看板
> **启动**: 2026-04-15
> **当前 Session**: S4 完成，待 S3 / S5

---

## 📅 Session 进度

| # | 主题 | 状态 | 启动 | 完成 | 报告 |
|---|---|---|---|---|---|
| **S1** | 三角对齐（文档 / 代码 / DB） | ✅ 完成 | 2026-04-15 | 2026-04-15 | [S1_three_way_alignment.md](S1_three_way_alignment.md) |
| **S2** | 一致性专项（PT ↔ 回测 ↔ 研究） | ✅ 静态完成 | 2026-04-15 | 2026-04-15 | [S2_consistency.md](S2_consistency.md) |
| **S3** | 韧性与抗断（静默失败 / 错误恢复 / 监控） | ✅ 静态完成 | 2026-04-15 | 2026-04-15 | [S3_resilience.md](S3_resilience.md) |
| **S4** | 动态基线验证（regression / pytest / diagnosis） | ✅ 完成 | 2026-04-15 | 2026-04-15 | [S4_baseline.md](S4_baseline.md) |
| S5 | 边界 + 血缘（时区 / QMT / 并发 / 生命周期） | ⬜ 待开始 | — | — | — |
| S6 | 方法论固化（不变量 / 契约 / 差分 / 金标） | ⬜ 待开始 | — | — | — |

---

## 📊 累计发现计数

| 分级 | S1 | S2 新增 | S4 新增 | **S3 新增** | 总计 | 已处理 | 未处理 |
|---|---|---|---|---|---|---|---|
| 🔴 P0 | 6 | 3 (F51/F60/F62) | 1 (F72) | **2** (F76/F77) | **12** | **5** (含 F72 闭环) | **7** |
| 🟠 P1 | 10 | 8 (F50/F52/F54/F55/F57/F58/F63/F65) | 3 (F66/F71/F74) | **4** (F78/F82/F85/F86) | **25** | **9** (含 F66 闭环) | **16** |
| 🟡 P2 | 6 | 2 (F56/F64) | 6 (F67/F68/F69/F70/F73/F75) | **3** (F79/F80/F81) | **17** | **3** (含 F73 闭环) | **14** |
| ✅ 关闭/修正 | — | F17 部分关闭 + F64 PASS | F66/F72/F73 闭环 | — | — | — | — |
| **合计** | **22** | **13** | **10** | **9** | **54** | **17** | **37** |

> S1 静态广扫 + S1 cleanup pass + S2 一致性专项（静态 + 4 快修）+ S4 动态基线验证 + S3 韧性静态审计已完成。

**S3 韧性静态审计关键发现** (2026-04-15 夜):
- 🔴 **F76 (P0)**: `qmt_execution_adapter.py:85-94 _get_realtime_tick` xtdata 异常 silent swallow → `_check_buy_protection` 可能 silently bypass 涨停保护 → 实盘风险
- 🔴 **F77 (P0)**: `qmt_execution_adapter.py:669-680` 撤单确认 query_orders 异常 silent pass → "查询失败" 被归类成 "撤单超时", 监控无法区分
- 🟠 **F78 (P1)**: `daily_pipeline.py:91-92` health_check stream publish silent (无 logger.warning)
- 🟠 **F82 (P1)**: Celery 配置漂移 — `celery_app.py:47 worker_concurrency=4` (Mac prefork 遗留) vs Windows `--pool=solo --concurrency=1` 实际运行
- 🟠 **F85 (P1)**: Rollback 覆盖率 15% — 20+ commit 只有 3 个 service 有 rollback, 异常时 partial state 悬挂
- 🟠 **F86 (P1)**: **F66 防复发缺失** — 4 条生产 INSERT 路径绕过 DataPipeline (factor_onboarding:544/756 + fetch_base_data:327/412), 铁律 17 仅文档级, 无代码强制
- 🟡 F79/F80/F81 (P2): pms/realtime/factors 三处 API silent fallback

**S3 积极发现** (反面证据, 作为良好基线):
- ✅ 熔断 L1-L4 实际落地 — `execution_service.py:92-115` 对 cb_level ∈ {2,3,4} 有真实分支, 非文档玩具
- ✅ execution_service StreamBus publish 有正确的 try/except + logger.warning(exc_info=True) — 可作全项目 publish 模板
- ✅ DataPipeline 本身合规 — `pipeline.py` 做完整的 rename→列对齐→单位转换→值域验证→FK→Upsert→fillna(None)

**S3 未做的动态部分** (建议转 S3b/S5 故障注入):
- Redis 断线时 PT 链路实际行为, PG 连接池耗尽, Celery worker kill -9 + beat 重启, QMT 断线时 _get_realtime_tick 真实 silent bypass 演示

**S4 基线验证关键结果** (2026-04-15 夜):
- ✅ **regression_test 5yr PASS**: max_diff=0.0, Sharpe 0.6095=0.6095, MDD -50.75%=-50.75%, 1212 days (铁律 15 验证, F66 前后两次独立复测完全一致)
- ⚠️ regression 12yr 不支持: 脚本仅 5yr 入口, 12yr 仅静态 metrics_12yr.json (F75)
- ✅ **factor_health 4 因子全 HEALTHY**: CORE3+dv_ttm 各 11.71M 行, neutral_value 99.2% 有效, 0 float NaN (铁律 29 CORE PASS)
- ✅ **system_diagnosis 37 PASS / 7 WARN / 0 FAIL** → S4 tail fix 后 Layer 1 复测 **17/17 PASS / 0 WARN** (F66 关闭后)
- ⚠️ **pytest 2057 pass / 32 fail / 9 error** → S4 tail fix 后 **2066 pass / 32 fail / 0 error** (F72 关闭后), 98.4% pass 率, 无 CORE 路径回归

**S4 tail fixes — 3 条 finding 单 session 闭环**:
- ✅ **F72 (P0)**: test_opening_gap_check import 从 `run_paper_trading._check_opening_gap` → `pt_monitor_service.check_opening_gap` → 9/9 pass in 0.05s
- ✅ **F66 (P1)**: 扩展扫描发现 12 个非 CORE 因子 1665 行 + 初始 28 行 = **1693 行 float NaN**, 一次 UPDATE → NULL, system_diag Layer 1 WARN→PASS, regression 5yr 复测 max_diff=0.0
- ✅ **F73 (P2)**: CLAUDE.md line 561 "2115 tests" → "2100 tests collected / 2066 pass / 32 fail / pass 率 98.4%"

**S4 未处理转 S3/S5/S6** (7 条):
- 🟠 **F71 (P1)**: 因子列表硬编码在 parquet_cache + health_check (对应 S1 F45 config drift) → S5
- 🟠 **F74 (P1)**: 11 个"未知"pytest 失败需逐一排查 (总 2-3 小时) → S5
- 🟡 F67/F68/F69/F70: Redis/Stream/execution 血缘 → S3 韧性 session
- 🟡 F75: regression_test 12yr 入口 → S6 金标工件

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
| **F72** | test_opening_gap_check 9 errors (Step 6-A refactor 遗留) | — | ✅ **2026-04-15 机械修复** | S4 |
| **F76** | `_get_realtime_tick` silent swallow → 涨停保护可能 bypass | — | ⬜ S3b 方案 A fail-safe (~45 min) | S3 |
| **F77** | 撤单确认 silent swallow → "查询失败" 归类成 "超时" | — | ⬜ S3b 加 logger.error 区分 (~15 min) | S3 |
| **F16** | Service 层 20+ 处 `.commit()` 违反铁律 | — | ⬜ 待修（S3 F85 配对扫出）| S1 |
| **F17** | factor_onboarding 绕过 DataPipeline + 中性化不完整 | — | 🟡 DEPRECATED 告警加上, 中期重构转 S2b | S1/S2 |
| **F31** | `factor_engine.py` Engine 层读写 DB（2034 行巨石） | — | ⬜ 长期重构（F43 一起） | S1/S2 |
| **F45** | `config_guard` 不检查 SN/top_n/industry_cap | — | ⬜ S6 合并做（配合 S3 F82）| S1 |
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
