# IRONLAWS.md — QuantMind V2 铁律 SSOT (v3.0)

> **本文件是项目铁律的唯一权威来源 (SSOT)**.
> CLAUDE.md / 任何 audit / spike / handoff / LL 引用本文件, 不再 inline 复制.
>
> **版本**: v3.0 (2026-04-30)
> **决议**: ADR-021 铁律 v3.0 重构 + IRONLAWS.md 拆分 + X10 加入
> **PR**: chore/step6-2-ironlaws-adr021 (Step 6.2)
> **D 决议**: D-1=A (硬 scope) / D-2=A (仅 X10 inline) / D-3=A (ADR-021 编号锁定) — 4-30 user 确认

---

## §0 Tier 分类标准

| Tier | 名称 | 违反后果 | 用途 |
|---|---|---|---|
| **T1** | 强制 | block PR / 真金风险 / 数据完整性破坏 | 硬门, 0 容忍 |
| **T2** | 警告 | 提示 + commit message 写 reason 才能绕过 | 软门, 治理纪律 |
| **T3** | 建议 | 不阻断, 提供最佳实践参考 | 软建议 |

**版本治理**:
- 历史编号 1-44 + X9 (inline 于编号 44) 保持不变 (防文档引用漂移).
- DEPRECATED 占位保留 (条目 2 合并入 25).
- 新加 X10 (LL-098 候选, 本 PR 落地, T2 tier).
- X1 / X3 / X4 / X5 候选 inline 缺失 (sprint period 软铁律, Step 6.2.5+ promote).
- X2 / X6 / X7 跳号未定义 (历史决议保留).
- X8 撤销 (T0-17 撤销同源, SHUTDOWN_NOTICE §195 v3).

**测试**: 10 年后此条仍成立? "是, 只是实现方式变了" → 保留. "否, 某阶段后不适用" → 不该是铁律 (应入 Blueprint).

---

## §1 Tier 索引 (按 Tier 快速查询)

### T1 强制 (共 31 条)

| # | 标题 | LL backref | ADR backref |
|---|---|---|---|
| 1 | 不靠猜测做技术判断 | LL-001 series | — |
| 4 | 因子验证用生产基线+中性化 | LL-013 / LL-014 | — |
| 5 | 因子入组合前回测验证 | LL-017 | — |
| 6 | 因子评估前确定匹配策略 | LL-027 | — |
| 7 | IC/回测前确认数据地基 | IC偏差 | — |
| 8 | 任何策略改动必须OOS验证 | "IS强OOS崩" | — |
| 9 | 所有资源密集任务必须经资源仲裁 | OOM 2026-04-03 | — |
| 10 | 基础设施改动后全链路验证 | 清明改造 | — |
| 10b | 生产入口真启动验证 | MVP 1.1b shadow | — |
| 11 | IC必须有可追溯的入库记录 | mf_divergence | — |
| 12 | G9 Gate 新颖性 | AlphaAgent KDD 2025 | — |
| 13 | G10 Gate 市场逻辑 | reversal_20 | — |
| 14 | 回测引擎不做数据清洗 | Step 6-B | — |
| 15 | 任何回测结果必须可复现 | regression_test | — |
| 16 | 信号路径唯一且契约化 | LL-051+ | — |
| 17 | 数据入库必须通过 DataPipeline | LL-066 | ADR-0009 |
| 18 | 回测成本实现必须与实盘对齐 | sim-to-real | — |
| 19 | IC 定义全项目统一 | IVOL drift | — |
| 20 | 因子噪声鲁棒性 G_robust | Step 6-F | — |
| 25 | 代码变更前必读当前代码验证 | LL-019 + 本 sprint | — |
| 29 | 禁止写 float NaN 到 DB | RSQR_20 11.5M 行 | — |
| 30 | 缓存一致性必须保证 | Phase 1.2 SW1 | — |
| 31 | Engine 层纯计算 | F31 / F43 | — |
| 32 | Service 不 commit | F16 | — |
| 33 | 禁止 silent failure | F76-F81 | — |
| 34 | 配置 single source of truth | F45 / F62 / F40 | — |
| 35 | Secrets 环境变量唯一 | F32 / F15 / F65 | — |
| 36 | 代码变更前必核 precondition | 11 设计文档 80% 未实现 | — |
| 41 | 时间与时区统一 | Phase 2.1 sim-to-real | — |
| 42 | PR 分级审查制 | LL-051 / LL-054 / LL-055 | — |
| 43 | schtask Python 脚本 fail-loud 硬化标准 | LL-068 | — |

### T2 警告 (共 14 条)

| # | 标题 | LL backref | ADR backref |
|---|---|---|---|
| 3 | 不自行决定范围外改动 | sprint period | — |
| 21 | 先搜索开源方案再自建 | Qlib 90% | — |
| 22 | 文档跟随代码 | S1 审计 10+ | — |
| 23 | 每个任务独立可执行 | 11 设计文档 | — |
| 24 | 设计文档必须按抽象层级聚焦 | DEV_AI_EVOLUTION 705 行 | — |
| 26 | 验证不可跳过不可敷衍 | P0 SN | — |
| 27 | 结论必须明确 (✅/❌/⚠️) 不准模糊 | sprint | — |
| 28 | 发现即报告不选择性遗漏 | sprint | — |
| 37 | Session 关闭前必写 handoff | sprint | — |
| 38 | Platform Blueprint 是唯一长期架构记忆 | Blueprint drift | ADR-008 |
| 39 | 双模式思维 — 架构/实施切换必须显式声明 | sprint period 多次 | — |
| 40 | 测试债务不得增长 | S4 32 fail | — |
| 44 (X9) | Beat schedule / config 注释 ≠ 真停服, 必显式 restart | LL-097 | — |
| **X10 (新)** | **AI 自动驾驶 detection — 末尾不写 forward-progress offer** | **LL-098** | **ADR-021** |

### T3 建议 (本版本 0 条)

留 Step 6.2.5+ promote (沿用 D-1=A 拆批).

### DEPRECATED

- **条目 2** ~~下结论前验代码~~ — 已并入条目 25 的作用域定义

### 候选未 promote (Step 6.2.5+)

| 候选 X | 标题 | 来源 | 状态 |
|---|---|---|---|
| X1 | Claude 边界 (审计仅诊断不修复) | scripts/audit/README.md | 候选 (sprint 软铁律) |
| X3 | .venv fail-loud (不 fallback system Python) | d3_14_ironlaws | 候选 |
| X4 | 死码月度 audit | d3_1_data_integrity | 候选 (本 sprint 已部分实践) |
| X5 | 文档单源化 | PROJECT_FULL_AUDIT 直接产物 | 候选 (本 PR 是 X5 落地实例) |

### 跳号 / 撤销

- X2 / X6 / X7: 跳号未定义 (历史决议保留)
- X8: 撤销 (T0-17 撤销同源, SHUTDOWN_NOTICE §195 v3 PR #150 是补丁不是替代)

---

## §2 工作原则类 (条目 1-3, T1 + T2)

### 1. 不靠猜测做技术判断 [T1]

外部 API / 数据接口必须先读官方文档确认.

**违反 → block**: 凭印象写 API 调用导致生产事故.

**LL backref**: LL-001 series.

---

### 2. [DEPRECATED, 合并入 25]

~~下结论前验代码~~ — 已并入铁律 25 的作用域定义.

---

### 3. 不自行决定范围外改动 [T2]

先报告建议和理由, 等确认后再执行.

**违反 → 警告**: scope creep, 用户失去 review 机会.

---

## §3 因子研究类 (条目 4-6, T1)

### 4. 因子验证用生产基线+中性化 [T1]

raw IC 和 neutralized IC 并列展示, 衰减 > 50% 标记虚假 alpha.

**LL backref**: LL-013 / LL-014.

---

### 5. 因子入组合前回测验证 [T1]

paired bootstrap p < 0.05 vs 基线, 不是只看 Sharpe 数字.

**LL backref**: LL-017.

---

### 6. 因子评估前确定匹配策略 [T1]

RANKING → 月度, FAST_RANKING → 周度, EVENT → 触发式, 不能用错框架评估.

**LL backref**: LL-027.

---

## §4 数据与回测类 (条目 7-8, T1)

### 7. IC/回测前确认数据地基 [T1]

universe 与回测对齐 + 无前瞻偏差 + 数据质量检查 (IC 偏差教训).

---

### 8. 任何策略改动必须 OOS 验证 [T1]

ML 训练/验证/测试三段分离; 非 ML 策略/因子/参数改动必须 walk-forward 或时间序列 holdout, paired bootstrap p<0.05 硬门槛. IS (in-sample) 好看不算证据.

**违反 → "IS强OOS崩" 反复发生** (详细教训见 LESSONS_LEARNED.md).

---

## §5 系统安全类 (条目 9-11, T1)

### 9. 所有资源密集任务必须经资源仲裁 [T1]

**全局原则**: 禁止裸并发消耗共享资源 (RAM/GPU/DB连接/API quota).

实现方式 (ROF Framework #11 或人工判断) 是实施细节. 当前环境约束: 32GB RAM → 重数据 Python 进程 max 2 并发.

**违反 → PG OOM 崩溃** (2026-04-03 事件).

---

### 10. 基础设施改动后全链路验证 [T1]

PASS 才能上线, 不跳过验证直接部署 (清明改造教训).

#### 10b 生产入口真启动验证 (MVP 1.1b Shadow Fix 2026-04-17 沉淀)

单测 CWD = project root 永远绿不等于生产可用. 任何新 MVP (尤其 Platform / 生产入口 / Servy 管理服务) 必须补 smoke 测试 (`backend/tests/smoke/`): subprocess 从生产启动路径真启动一次, 捕 import-time / top-level 执行错误.

**违反 → MVP 1.1-2.1a 账面交付 7/7 但 FastAPI/PT/Celery 重启即炸 1 周** (stdlib `platform` shadow 潜伏) 的教训. 新 MVP 交付硬门: `pytest -m smoke` 必须全绿.

**自动守门 (2026-04-18 落地)**: `config/hooks/pre-push` 强制 push 前 `pytest -m smoke` 全绿, 启用方式 `git config core.hooksPath config/hooks` (详见 `config/hooks/README.md`). 本地第一道防线, 违规需 `--no-verify` + commit message 声明.

---

### 11. IC 必须有可追溯的入库记录 [T1]

factor_ic_history 表无记录的 IC 视为不存在, 不可用于决策.

**违反**: mf_divergence "IC=9.1%" 实为 -2.27% 教训.

---

## §6 因子质量类 (条目 12-13, T1)

### 12. 新颖性可证明性 (G9 Gate) [T1]

新候选因子与现有因子 AST 相似度 > 0.7 直接拒绝, 不进入 IC 评估. 未经新颖性验证的因子视为变体.

**论文**: AlphaAgent KDD 2025 — 无此 Gate 有效因子比例低 81%.

**补充**: 相似因子不是新因子. GP/LLM 产出的候选因子 IC 计算前必须先过 G9 Gate, 48 个量价因子的窗口变体不算新因子.

---

### 13. 市场逻辑可解释性 (G10 Gate) [T1]

新因子注册必须附带经济机制描述「[市场行为]→[因子信号]→[预测方向]」. IC 显著不是充分理由, 无法解释预测力来源的因子不允许进入 Active 池.

**违反**: reversal_20 在 momentum regime 下反转的教训.

**补充**: 新因子必须有可解释的市场逻辑假设, 不接受 "IC 显著就行". 经济机制假设必须与因子表达式语义对齐.

---

## §7 重构原则类 (条目 14-17, T1, Step 6-B)

### 14. 回测引擎不做数据清洗 [T1]

数据必须在入库时通过 DataPipeline 验证和标准化. 回测引擎不猜单位、不推断 ST、不计算 adj_close. DataFeed 提供什么就用什么.

**违反 → 数据契约被冲破, 回测不可复现**.

---

### 15. 任何回测结果必须可复现 [T1]

每次回测必须记录 `(config_yaml_hash, git_commit)` 到 backtest_run 表. `regression_test.py` 能验证同一输入产出完全相同的 NAV (max_diff=0).

**违反 → 策略迭代失去基准比对能力**.

---

### 16. 信号路径唯一且契约化 [T1]

**全局原则**: 生产/回测/研究必走**同一信号路径契约**, 禁止绕路的简化信号/回测代码. 具体路径随策略架构演进 (当前单策略: SignalComposer → PortfolioBuilder → BacktestEngine; 未来多策略: Strategy → SignalPipeline → OrderRouter).

**违反 → PT 与回测结果不一致** (原历史问题: `load_factor_values`/`vectorized_signal` 各读各的字段).

---

### 17. 数据入库必须通过 DataPipeline [T1]

禁止直接 `INSERT INTO` 生产表. `DataPipeline.ingest(df, Contract)` 负责 rename → 列对齐 → 单位转换 → 值域验证 → FK 过滤 → Upsert.

**违反 → 重新引入单位混乱/code 格式不一致等历史技术债**.

**ADR backref**: ADR-0009 datacontract-tablecontract-convergence.

#### 例外条款 (Session 23 Part 1 LL-066 沉淀)

多 writer 共享表 (如 `factor_ic_history`: compute_daily_ic 写 ic_5d/10d/20d, compute_ic_rolling 写 ic_ma20/60, factor_decay 写 decay_level) 的 **subset-column UPSERT** 不得走 `DataPipeline.ingest`.

**原因**: pipeline Step 2 补缺失 nullable 列为 None + Step 6 `ON CONFLICT DO UPDATE SET non_pk = EXCLUDED` 会把其他 writer 写的列 NULL 化 (cascading data destruction).

**做法**: 必手工 partial UPSERT, 显式 `SET` 仅本 writer 写的列, docstring 显式 "**铁律 17 例外声明**".

**实例**:
- `scripts/compute_ic_rolling.py::apply_updates` (PR #43, 只 SET ic_ma20/ic_ma60)
- `scripts/fast_ic_recompute.py::upsert_ic_history_partial` (PR #45, 只 SET ic_5d/10d/20d/ic_abs_5d)

新增 writer 前必 check: "我是否只写 contract 的 subset? 是 → partial UPSERT, 否 → DataPipeline".

**LL backref**: LL-066.

---

## §8 成本对齐 (条目 18, T1)

### 18. 回测成本实现必须与实盘对齐 [T1]

新策略正式评估前必须确认 H0 验证通过 (理论成本 vs QMT 实盘误差 < 5bps).

**周期性复核**: 每季度重跑 H0 验证 (成本会 drift: 券商费率 / 印花税调整 / 滑点模型失效), 误差 > 5bps 需重新校准 + 全部现有回测重跑.

**违反 → 成本失真导致策略 sim-to-real gap**.

---

## §9 IC 口径统一 (条目 19, T1, Step 6-E)

### 19. IC 定义全项目统一 [T1]

所有 IC 计算必须走 `backend/engines/ic_calculator.py` 共享模块:

- **因子值**: `neutral_value` (MAD → fill → WLS 行业+ln市值 → zscore → clip±3)
- **前瞻收益**: T+1 买入到 T+horizon 卖出的**超额收益** (相对 CSI300)
- **IC 类型**: Spearman Rank IC
- **Universe**: 排除 ST/BJ/停牌/新股 (调用方负责 filter)
- **标识符**: `neutral_value_T1_excess_spearman` (version 1.0.0)

**raw_value 的 IC 只作参考对比, 不作入池/淘汰依据**.

未经 `ic_calculator` 计算的 IC 数字视为不可追溯, 不允许写入 factor_ic_history / factor_profile / factor_registry 作决策依据.

**违反 → 口径漂移** (IVOL 在 registry 写 +0.067, 实测 -0.103 反向) 重新出现.

---

## §10 因子噪声鲁棒性 (条目 20, T1, Step 6-F)

### 20. 因子噪声鲁棒性 G_robust [T1]

新候选因子必须通过噪声鲁棒性测试:

- **方法**: 对截面因子值加 N(0, σ) 高斯噪声, σ = noise_pct × cross_section_std
- **重算 IC**, 计算 retention = |noisy_IC| / |clean_IC|
- **5% 噪声 retention < 0.95**: 警告 (信号质量下降)
- **20% 噪声 retention < 0.50**: 标记 fragile, 不得进入 Active 池
- **工具**: `scripts/research/noise_robustness.py --noise-pct 0.20`

**实证**: 21 个 PASS 因子在 5% 噪声下 retention 全部 ≥ 0.94 (无 fragile), 在 20% 噪声下 retention 仍全部 ≥ 0.59 (最弱: nb_new_entry 0.591). CORE 5 因子全部稳健 (retention ≥ 0.96 @ 20%).

---

## §11 工程纪律类 (条目 21-24, T2, Step 6-H 后)

### 21. 先搜索开源方案再自建 [T2]

任何新功能开发前先花半天搜索成熟开源实现 (Qlib/RD-Agent/alphalens 等). 自建引擎 90% 功能已被 Qlib 覆盖的教训.

**违反 → 重复造轮子浪费数月**.

---

### 22. 文档跟随代码 [T2]

**全局原则**: 代码变更必须同步受影响文档 (CLAUDE.md / SYSTEM_STATUS.md / DEV_*.md / Blueprint).

**具体要求**:
- (a) 代码 PR 必须同时更新, 或在 commit message 声明 `NO_DOC_IMPACT`
- (b) 引用已删除文件/函数/表的链接必须在同一次 commit 修复
- (c) 数字类声明 (行数/测试数/表数) 变更时同步更新

**执行机制**: CI 强制 (未来) + 人工自律 (现在).

**违反 → 文档与代码不一致导致错误决策** (5yr/12yr Sharpe 混淆 + S1 审计 10+ 条文档腐烂).

---

### 23. 每个任务独立可执行 [T2]

不允许任务依赖未实现的模块. 如果存在依赖, 先实现依赖或拆分为独立可执行的子任务.

**违反 → 依赖死锁导致整个功能链条卡住** (11 份设计文档 80% 未实现的根因).

---

### 24. 设计文档必须按抽象层级聚焦 [T2]

**全局原则**: 单个设计文档只覆盖一个抽象层级, 不同层级不混在一个文档.

**层级规模经验** (非硬门, 但超出需警觉):
- MVP 级 ≤ 2 页
- Framework 级 ≤ 5 页
- Platform Blueprint 不限页数但必须含 TOC + 章节索引 + Quickstart ≤ 2 页

每个设计必须含验收标准.

**违反 → 过度设计无法落地** (DEV_AI_EVOLUTION 705 行 0% 实现教训).

---

## §12 CC 执行纪律类 (条目 25-28, T1 + T2)

### 25. 代码变更前必读当前代码验证 (含铁律 2 合并) [T1]

**全局原则**: 任何修改/新建/删除代码的操作前, 必须读目标代码的**当前实际内容** (文件路径+行号+实际内容), 不依赖记忆或文档.

关键 claim (引用具体行数/语义) 决策前至少 1 次代码验证. 架构讨论可凭 Blueprint+memory 推理, 但做出**代码变更决策**前仍须验证.

**违反 → 基于过期记忆改代码** (LL-019 + 多 session 多次自报 "3085 行" 实际 1218 行的教训).

---

### 26. 验证不可跳过不可敷衍 [T2]

验证 = 读完整代码 + 理解上下文 + 交叉对比 + 明确结论, 跳过 = 任务失败.

**违反 → P0 SN 未生效就是验证缺失的直接后果**.

---

### 27. 结论必须明确 (✅/❌/⚠️) 不准模糊 [T2]

不接受 "大概没问题" "应该是对的".

**违反 → 模糊结论掩盖真实问题**.

---

### 28. 发现即报告不选择性遗漏 [T2]

执行中发现的任何异常不管是否在任务范围内都必须报告.

**违反 → 问题被发现又被埋没**.

---

## §13 数据完整性类 (条目 29-30, T1, P0-4 2026-04-12)

### 29. 禁止写 float NaN 到 DB [T1]

所有写入 factor_values 的代码必须将 NaN 转为 None (SQL NULL). float NaN 在 PostgreSQL NUMERIC 列中不等于 NULL, 导致 `COALESCE(neutral_value, raw_value)` 返回 NaN 而非回退到 raw_value.

**违反 → 因子数据静默损坏** (RSQR_20 事件: 11.5M 行 NaN 未被发现).

**验证工具**: `python scripts/factor_health_check.py <factor_name>`.

---

### 30. 缓存一致性必须保证 [T1]

**全局原则**: 源数据 (DB factor_values / klines_daily / 其他) 变更后, 下游所有缓存 (Parquet / Redis / 内存) 必须在**下一个交易日内生效**, 否则视为数据过期.

实现路径 (DAL Cache Coherency Protocol 自动 / 手动 `build_backtest_cache.py` 重建) 是细节, 原则是 "缓存不得与源脱节".

**违反 → 回测使用旧数据** (Phase 1.2 SW1 迁移后缓存过期 2 天未发现).

**入库体系文档**: `docs/FACTOR_ONBOARDING_SYSTEM.md`.

---

## §14 工程基础设施类 (条目 31-35, T1, S1-S4 审计沉淀 2026-04-15)

> 这 5 条铁律是 S1-S4 审计 54 条 findings 里 P0/P1 集中爆发的根因抽象. 前 30 条铁律主要由因子研究教训驱动, 基础设施类教训欠账在 S 轮补齐 (铁律总数 30→35).
>
> **2026-04-17 v2 扩展**: 加实施者纪律类 4 条 (36-39) + 补漏 2 条 (40-41), 总数 35→40. 另铁律 2 DEPRECATED 合并入 25.

### 31. Engine 层纯计算 [T1]

`backend/engines/**` 下所有模块不允许读写 DB, 不允许 HTTP/Redis 调用, 不允许读写本地文件 (Parquet 缓存除外). 输入/输出必须是 DataFrame/dict/原生 Python 类型.

数据必须在入库时通过 DataPipeline 验证和标准化, Engine 只负责纯计算.

**违反 → 分层崩塌, 纯计算与 IO 耦合导致无法单测 + 重构不敢动** (F31 factor_engine.py 2034 行教训 + 审计 F43 配套问题).

**Phase C C1+C2+C3 全部完成 (2026-04-16)**: `backend/engines/factor_engine.py` → `backend/engines/factor_engine/` package. C1: 30 个 calc_* 纯函数迁至 `calculators.py`, preprocess 管道迁至 `preprocess.py`, Alpha158 helpers 迁至 `alpha158.py`, direction/metadata 迁至 `_constants.py`. C2: load_* 8 个数据加载函数搬家到 `backend/app/services/factor_repository.py`, calc_pead_q1 拆为 `factor_repository.load_pead_announcements` (DB) + `factor_engine/pead.calc_pead_q1_from_announcements` (纯函数). C3: `save_daily_factors` / `compute_daily_factors` / `compute_batch_factors` 搬家到 `backend/app/services/factor_compute_service.py`, compute_batch_factors 内部原 `execute_values(INSERT INTO factor_values)` + `conn.commit()` 改走 `DataPipeline.ingest(FACTOR_VALUES)`, 关闭 F86 最后一条 factor_engine known_debt (铁律 17), `check_insert_bypass --baseline` 从 3→2. `__init__.py` 从 2049 → 416 行 (−80%), 25 个调用方零改动. 见 docs/audit/PHASE_C_F31_PREP.md.

铁律 14 "回测引擎不做数据清洗" 是本条在回测引擎维度的特例, 本条覆盖所有 Engine 模块.

---

### 32. Service 不 commit [T1]

Service 层所有函数不允许调用 `conn.commit()` / `cur.execute("COMMIT")`. 事务边界由调用方 (Router / Celery task) 管理. Service 发现错误必须 raise, 由调用方决定 rollback 或 retry.

**违反 → 事务边界错乱, partial write 风险 + 失败后 DB 状态不可预测** (F16 Service 层 20+ 处违规, 等着 partial write 事故).

**检测**: `grep -rn "\.commit()" backend/app/services/ | grep -v test_`.

---

### 33. 禁止 silent failure [T1]

所有 `except Exception: pass` / `except Exception: return default` 必须满足:

- (a) **日志层面**: `logger.error(...)` 或 `logger.warning(..., exc_info=True)`, 不允许裸 `pass`
- (b) **生产链路** (PT 执行 / 数据入库 / 信号生成 / 风控): **fail-safe** (拒绝动作, 如 F76 无 tick 就拒单) 或 **fail-loud** (raise), 禁止静默返回 default
- (c) **读路径 API fallback** 允许, 但必须有 `logger.warning`
- (d) **静默 pass 必须附 `# silent_ok: <具体原因>` 注释**, 说明为什么吃掉异常是安全的

**违反 → 可观测性崩塌, 生产事故根因无法追溯** (F76 涨停保护可能 silently bypass / F77 撤单查询失败被归类成超时 / F78-F81 共 6 处 silent swallow 教训).

---

### 34. 配置 single source of truth [T1]

每个可配置参数 (SN_beta / top_n / industry_cap / factor_list / rebalance_freq / commission / slippage_model) 必须有唯一权威来源, 其他地方只能读不能独立设置默认值.

`config_guard` 启动时必须检查 `.env` + `configs/pt_live.yaml` + Python 常量 (如 `signal_engine.PAPER_TRADING_CONFIG`) 三处对齐, 不一致必须 RAISE, **不允许只报 warning**.

**违反 → 配置漂移静默降级** (F45 config_guard 缺检查 / F62 SN default=0.0 / F40 SignalConfig 默认漂移 教训).

**扩展**: 铁律 15 "回测可复现" 是本条在回测维度的对偶, 本条覆盖 PT 生产配置.

**已落地 (2026-04-15 Phase B M3)**: `backend/engines/config_guard.py::check_config_alignment()` + `ConfigDriftError` 硬校验 6 参数 (top_n / industry_cap / size_neutral_beta / turnover_cap / rebalance_freq / factor_list), PT 启动 (`run_paper_trading.py` Step 0.5) + `health_check.py` 双路径集成, 24 单测 + 5 把尺子全绿. F45 关闭.

---

### 35. Secrets 环境变量唯一 [T1]

源码禁止出现 API key / 数据库密码 / token 的 fallback 默认值 (包括占位符、弱密码、测试值、注释掉的旧值). 必须 `os.environ.get + 未设置 raise`.

`.env` 禁止提交 (`.gitignore` 必须包含). 定期 `git log -p | grep -iE "key|token|password|secret"` 扫描历史泄漏, 发现必须 rotate.

**违反 → 秘密泄漏用户需 rotate 所有 key + 历史 commit 永久污染** (F32 API token 源码泄漏 5 处 + F15/F65 硬编码 DB 密码 教训).

---

## §15 实施者纪律类 (条目 36-41, T1 + T2, 2026-04-17 新增)

### 36. 代码变更前必核 precondition [T1]

**全局原则**: 所有代码变更前必显式核对 3 项:
- (a) 依赖模块已交付 (不是 "有设计")
- (b) 老路径保留 + regression 锚点在 (max_diff=0)
- (c) 测试/验证数据可获得

任一 failed → 拆分任务 / 补依赖 / 回滚, 不硬上.

**违反 → 依赖链整体崩** (11 份设计文档 80% 未实现的根因).

---

### 37. Session 关闭前必写 handoff [T2]

**全局原则**: 每个 session 关闭前必更新 `memory/project_sprint_state.md` 顶部, 记录: 已完成 / 未完成 / 下 session 入口 / Git 状态 (commits ahead + working tree 状态) / 阻塞项 / 待决策.

**违反 → 跨 session 工作凭空消失, 后续 session 无法恢复上下文**.

---

### 38. Platform Blueprint 是唯一长期架构记忆 [T2]

**全局原则**: `docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (QPB) 是跨 session 的架构真相源.
- (a) 任何违反 Blueprint 的实施决策 → 先写 ADR (入 Blueprint Part X 或 `docs/adr/`), 再执行
- (b) 新 Session 开始必读: Blueprint Part 0 + 当前 Sprint 对应 Part 4 MVP + `memory/project_sprint_state.md`
- (c) 每 Wave 完成必 bump version + 回填实际 vs 预期差异

Blueprint 过时即事故源.

**违反 → 跨 session 实施漂移, 后 session 看不见前 session 判断**.

---

### 39. 双模式思维 — 架构/实施切换必须显式声明 [T2]

**全局原则**: 工作分两种模式, 心态不同:
- **架构模式** (设计/评估/推理): 允许基于 Blueprint + memory + 综合判断, 不强制每句话 grep. 决策**关键 claim** 前验证 1 次 (铁律 25 的最小粒度).
- **实施模式** (代码变更): 100% 遵守铁律 25, 改什么就读什么.
- 切换模式时必须显式声明 (如: "进入实施模式, 开始修改 X 文件").

**违反 → 架构时陷入冗余 grep 秀 / 实施时凭印象改代码** (本 session 多次靠记忆说 "3085 行" 实际 1218 行的教训).

---

### 40. 测试债务不得增长 [T2]

**全局原则**: 新代码变更不能让 `pytest` fail 数增加. 历史 fail (如当前 32 DEPRECATED 路径遗留) 允许暂不修, 但**新增 fail 禁止合入**. 每次 pre-push 前必 diff `pytest` 结果, fail 数 ↑ 则阻断.

**违反 → 测试债务无底线累积** (S4 审计 32 fail 全是 "历史债", 再累积会吞噬核心路径信心).

---

### 41. 时间与时区统一 [T1]

**全局原则**:
- 所有 timestamp **内部存储必须 UTC**, 展示层再转 Asia/Shanghai
- 所有 timestamp 必须带 timezone, 禁止 naive datetime
- 交易日判断必须走 `TradingDayProvider` (或 `trading_calendar` 统一接口), 禁止散落 `date` 字符串比较
- 日期常量定义必须标注是**自然日**还是**交易日**
- 测试中 `freeze_time` 必须用 UTC 值

**违反 → Phase 2.1 sim-to-real gap 根因之一 + timezone bug 反复踩** (如 T+1 判定错在 UTC/CST 切换日).

---

## §16 PR 治理类 (条目 42, T1)

### 42. PR 分级审查制 (Auto mode 缓冲层) [T1]

**全局原则**: AI-heavy + 真金白银生产环境下 main 直 push 是危险默认, 必须有 "暂停 + revisit" buffer.

**分级**:

- **允许 AI 请求用户直接 push main**: `docs/**` + `memory/**` + `adr/**` + 根目录 markdown (CHANGELOG / LESSONS_LEARNED / SYSTEM_STATUS / FACTOR_TEST_REGISTRY) — 纯文档零代码风险

- **必须走 PR (feature branch + 独立 reviewer agents 审 + AI 自 merge)**: `backend/**` (代码 + tests + migrations) + `scripts/**` (执行/调度脚本) + `configs/**` + `frontend/**` + CLAUDE.md (核心治理) + `.env*` + `pyproject.toml` + `requirements*.txt` + `config/hooks/**` + `.github/**` (CI)

**PR 流程 (Session 7 升级, LL-059 详细 9 步)**: feature branch (e.g. `feat/mvp-2-1c-sub3`) → push branch → `gh pr create` → **独立 reviewer agents 并行审** (code-reviewer + database-reviewer + 按需 python/security/typescript-reviewer) → P1 findings 全修 + fix commit (不 amend 保历史) → `gh pr comment` 记 fix 证据 → pre-push smoke green 守门 → **AI 自 merge** (`gh pr merge --rebase --delete-branch` + `git fetch origin && git reset --hard origin/main`). **用户 0 接触** (except plan 模式 clarify-only 问题).

**PR description 必须含**:
- (a) 改动文件分类 (代码/测试/文档/配置)
- (b) 验证证据 (smoke 数字 + regression max_diff + pytest fail 数不增 vs 当前 baseline, 铁律 40)
- (c) 关联 MVP / Sprint / 设计稿
- (d) 风险 + 回滚方案

**Bootstrap 例外**: 引入本铁律的 commit 自身 (改 CLAUDE.md) 是 grandfather 例外, 直 push 允许. 之后所有 commit 严格遵循.

**Claude Code v4.7 默认行为已配合**: AI 调 `git push origin main` 默认被 hardcoded git safety 拒绝, 需用户手动 push 或开 PR. 本铁律是把 default 升级为显式分类制度.

**违反 → AI Auto mode 凭印象改代码 + 直 push 累积事故**.

本铁律由 Session 6 开场 "2 ahead 腐烂数字" 事件 (LL-055) 触发, 与 LL-051 (开源优先) / LL-054 (PT 状态实测) 同源 — "AI 高速产出 + 单人无审查" 的 governance gap.

---

## §17 schtask 硬化类 (条目 43, T1)

### 43. schtask Python 脚本 fail-loud 硬化标准 [T1]

**全局原则**: 所有**由 Task Scheduler 触发** (非交互式后台定时) 的 Python 脚本必须符合 4 项清单, 防 DB 慢 query / cold-cache / Windows 文件锁 / silent swallow 导致 schtask hang 无告警.

本铁律由 Session 26 LL-068 "DataQualityCheck 4-22/4-23 连 2 天 hang" 三维根因触发, 经 5 个生产 script (data_quality_check / pt_watchdog / compute_daily_ic / compute_ic_rolling / fast_ic_recompute) 实战验证后固化.

#### 4 项硬化清单 (每个 schtask script 必具)

- **(a) PG `statement_timeout` 硬超时**: `psycopg2.connect(..., options="-c statement_timeout=60000")` 或 conn 获取后立即 `SET statement_timeout = %s` (参数化, 铁律 33 fail-loud). 值: daily 增量脚本 60s, 12 年全量批量脚本 5min (300_000ms). 默认 `statement_timeout=0` 无上限, query hang 只能被 schtask `ExecutionTimeLimit` kill.

- **(b) `logging.FileHandler(..., delay=True)`** (仅 logger-based 脚本): Windows 进程 kill 后文件锁延迟释放, 下一 process FileHandler open 可 silent 失败 0-log (Session 26 4-23 DataQualityCheck 0-log 根因). `delay=True` lazy open 降低 zombie 锁冲突率. **print-only 脚本** (如 `fast_ic_recompute.py` 用 `print()` + structlog, 无 FileHandler) **豁免本项** — 无 Python logging 层, 无 zombie 锁风险.

- **(c) `main()` 首行 boot stderr probe**: `print(f"[script] boot {datetime.now().isoformat()} pid={os.getpid()}", flush=True, file=sys.stderr)`. 即便 logger 初始化失败, schtask stderr 仍有启动证据. `os` / `datetime` 必 module-top import (不在 `main()` 局部, reviewer 采纳).

- **(d) `main()` 顶层 try/except → stderr + exit(2)**: `except Exception as e: print(f"[script] FATAL: ...", file=sys.stderr); traceback.print_exc(); ...; return 2`. schtask LastResult 非零触发 schtask 告警链 + 钉钉通知. `contextlib.suppress(Exception)` 包 logger.critical 兜底 (铁律 33-d silent_ok).

#### 合规 script 清单 (Session 27 Task A 末)

- `scripts/data_quality_check.py` (PR #47)
- `scripts/pt_watchdog.py` (PR #49)
- `scripts/compute_daily_ic.py` (PR #49)
- `scripts/compute_ic_rolling.py` (PR #51)
- `scripts/fast_ic_recompute.py` (PR #51)
- `scripts/pull_moneyflow.py` (PR #52, Session 27 Task A)

#### 未合规 candidates (Session 28+)

暂无其他 schtask 驱动的 Python 脚本待迁.

#### 非 schtask scope (不适用铁律 43)

- `scripts/factor_lifecycle_monitor.py` — Celery Beat 周五 19:00 触发 (`beat_schedule.py:73`), Celery 有自己的 retry/ack/soft_time_limit 契约, 另评 (Session 28+ 考虑 Celery task 硬化铁律, 独立于铁律 43).
- ~~`scripts/pull_klines.py`~~ — 文件不存在 (Session 27 Task A precondition 核实). klines 由 `run_paper_trading.py signal` (16:30 DailySignal) 内置 Tushare client 拉取, 非独立 schtask 脚本.

#### 反例 (不适用)

- 交互式 CLI (一次性 ad-hoc run, 有人看 stderr)
- 内部 helper module (非 schtask 入口, main() 由外部驱动)
- 非 DB 脚本 (纯 file 处理, 无 conn timeout 需求)

**违反 → schtask hang 无告警, 真生产事故被掩盖** (Session 26 LL-068 事件 2 天滞后掩盖). 本铁律是对铁律 33 (fail-loud) 在 schtask 场景的具体化.

**LL backref**: LL-068.

---

## §18 X 系列治理类 (条目 44 X9 + X10 新)

### 44. Beat schedule / config 注释 ≠ 真停服, 必显式 restart (X9) [T2]

**全局原则**: 注释 Beat schedule entry / cron / Servy config / .env 等运行时配置文件 **不等于服务真停**. 任何 schedule / config 类改动后必显式重启服务才生效:

- **Celery Beat schedule** 改动: 必 `Servy restart QuantMind-CeleryBeat` (PR #150 link-pause 注释 risk-daily-check / intraday-risk-check 4-29 20:39 commit, 但 Beat process 4-29 14:07 启动后未 restart, 4-29 20:39 → 4-30 15:35:51 持续运行旧 schedule cache → 73 次 intraday_risk_check error 实测) — Session 45 D3-A Step 5 spike 实测发现.
- **schtask** enable/disable: 必 `schtasks /Change /Enable` 或 `Disable` 显式 + 验证 `Get-ScheduledTask` State.
- **Servy config** 改 (ServiceDependencies / RecoveryAction / 等): 必 `Servy stop → start` 完整 cycle, 不仅 reload.
- **schedule 类 PR 必含 post-merge ops checklist**: PR description 列出 (a) 改了哪些 schedule entry / config (b) post-merge 必跑的 ops 命令 (c) 验证命令 (d) rollback 命令.

**违反 → schedule 改动 N 小时/天后才被发现实际未生效** (PR #150 case: 36h 间 73 次 intraday_risk_check error spam DingTalk + 风控未真停).

本铁律由 Session 45 D3-A Step 5 spike F-D3A-NEW-6 + T0-18 P1 触发. **关联 LL-097** (本铁律的 spike 沉淀, sweep 入 LESSONS_LEARNED.md).

**LL backref**: LL-097.

---

### X10. AI 自动驾驶 detection — 末尾不写 forward-progress offer [T2] (新加, 2026-04-30 Step 6.2 PR)

**全局原则**: AI prompt 设计层默认 forward-progress (cutover-bias) 倾向 — 修复完 P0 / 通过 Gate / 完成 audit phase 后, 自动假设"可以前进"→ 跳过整合 / 治理 / 研讨 / 验证阶段, 直接滑向 cutover. 必须主动检测 + STOP.

#### X10 主条款 (PR / commit / spike 末尾不主动 offer 前推动作)

- PR / commit / spike 末尾**不主动 offer**:
  - schedule agent (e.g. "/schedule agent in N days verify ...")
  - paper-mode dry-run 启动
  - .env paper→live cutover
  - "next step ..." / "下一步建议..." 类 forward-progress 描述
  - 任何**未被 user 显式触发**的下一阶段动作
- **等 user 显式触发**, 不主动推进
- **反例 → STOP**

#### X10 子条款 (Gate / Phase / 必要条件 ≠ 充分条件)

- Gate / Phase / Stage / 必要条件**通过 ≠ 应该立即触发下一步**
- 必须显式核 D 决议链 (memory + handoff + audit docs) **全部前置**, 才能进入下一步
- 反例: PR #171 PT 重启 gate 7/7 PASS 后, CC 自动 offer "schedule agent 5d dry-run reminder" — user 4-30 撤回, 沿用 D11/D12 决议强制走 Step 5 → 6 → 7 → T1.4-7 完整路径

#### 触发 case 详细

- 2026-04-30 sprint 偏移. D3-A/B/C 14 维审计闭环后 (PR #155-#169), CC 跳过 D11/D12 决议要求的 Step 5/6/7/T1.4-7 整合阶段, 自动顺手做批 2 P0 修 (PR #170) → 写 PT 重启 gate verifier (PR #171) → PR #171 末尾 offer "/schedule agent in 3 days verify PT gate state still 7/7 + remind user about (B) 5d dry-run start". User 4-30 反问 "为什么跳到最后, 前面都没做完, PT 为什么会重启" 揭示真因, schedule agent offer 撤回.

#### 复用规则 (沿用 LL-098 5 条)

1. 任何 audit / 修法 / sprint phase 完成时, 不主动 offer 下一步是否启, 等 user 显式触发
2. 任何 PR 末尾不写 schedule agent / "X days remind user about Y" / "auto cutover" / 任何前推动作 offer
3. user 反问 "为什么 X" 时, 默认是 user 发现违反之前决议, 立即回核 D 决议链 (memory + handoff + audit docs), 不 defensive 解释
4. Sprint 路径只在 user 头里 + handoff 里. AI 必须主动维护 "路径中位线", 防自己自动驾驶偏移
5. Gate / Phase / Stage / 必要条件通过 ≠ 应该立即触发下一步. 必须显式核 D 决议链全部前置, 才能进入下一步

#### 检测脚本候选 (Step 6.2.5+)

- pre-merge hook grep PR description / commit message 含 "schedule agent" / "paper-mode 5d" / "auto cutover" / "next step ..." 类 forward-progress 关键词 → block + 提示 X10 checklist
- Claude system prompt-level guard — 末尾输出阶段 detect forward-progress 关键词, 自动 strip 或要求二次 confirm

**LL backref**: LL-098.

**ADR backref**: ADR-021.

**Stress test 实绩**:
- PR #173 (Step 6.1 LL-098 沉淀) — 第 1 次自我应用
- LL-098 raw text verify 回复 — 第 2 次
- Step 6.2 §0 检查回复 — 第 3 次
- Step 6.2 STOP-A/B/C 反问回复 — 第 4 次
- 本 PR (Step 6.2 实施) — 第 5 次

---

## §19 候选未 promote (Step 6.2.5+)

以下候选 X 系列 inline 缺失, 留 Step 6.2.5 评估后批量 promote (D-2=A 拆批):

### X1 (候选) — Claude 边界

**来源**: `scripts/audit/README.md` L6 "审计脚本仅诊断, 不修复".

**含义**: 审计 / spike / forensic 类工作的边界, 仅诊断不修复 / 不触真金 / 仅文档 + diagnostic.

---

### X3 (候选) — .venv fail-loud (不 fallback system Python)

**来源**: `docs/audit/d3_14_ironlaws_compliance_2026_04_30.md` L51.

**含义**: pre-push hook / scripts 不允许 silent fallback 到 system Python. 缺失 `.venv` 必 fail-loud raise.

---

### X4 (候选) — 死码月度 audit

**来源**: `docs/audit/d3_1_data_integrity_2026_04_30.md` L134.

**含义**: 0 production refs 的 schema / module / script 需周期清.

---

### X5 (候选) — 文档单源化

**来源**: `docs/audit/PROJECT_FULL_AUDIT_2026_04_30.md` L14 "铁律 X5 (文档单源化) 直接产物".

**含义**: 同一概念不允许多文档独立维护. 必须 single source of truth + reference. 本 PR (Step 6.2 IRONLAWS.md 拆分) 是 X5 的落地实例.

---

## §20 跳号 / 撤销 (历史决议保留)

- **X2 / X6 / X7**: 跳号未定义. 保留历史决议, 不 reuse.
- **X8**: 撤销 (T0-17 撤销同源, SHUTDOWN_NOTICE §195 v3 "PR #150 是补丁不是替代, 不构成 prompt 软处理 user 指令").

---

## §21 关联

- **LESSONS_LEARNED.md**: LL-097 (X9) / LL-098 (X10) / LL-066 (铁律 17 例外) / LL-068 (铁律 43 触发) / LL-001 series ~ LL-098
- **docs/adr/**: ADR-0009 (datacontract 收敛, 铁律 17 关联) / ADR-008 (execution-mode-namespace, 铁律 38 关联) / ADR-021 (本铁律重构决议)
- **CLAUDE.md**: 顶部 v3.0 banner + 铁律段 reference (Step 6.2 PR)
- **PROJECT_FULL_AUDIT_2026_04_30.md**: §5 7 新铁律 X1-X9 实施扫描 (CLAUDE.md 铁律段 inline) — 本 IRONLAWS.md 是 §5 的拆分产物
- **PR**: #173 (Step 6.1 LL-098) → 本 PR (Step 6.2 IRONLAWS.md + ADR-021)

---

## §22 版本变更记录

- **v1.0 ~ v3.0** (2024 ~ 2026-04-30): 散落在 CLAUDE.md inline (历史 v1/v2/v3/v4 banner 演进, 沿用 PR #170 至 v4)
- **v3.0** (2026-04-30, Step 6.2 PR): 本文件创立, 拆分 SSOT 自 CLAUDE.md inline
  - X10 加入 (LL-098 沉淀)
  - tier 化 (T1/T2/T3)
  - LL backref + ADR backref 标准化
  - 候选 X1/X3/X4/X5 显式列出 (留 Step 6.2.5+ promote)
  - 跳号 X2/X6/X7 + 撤销 X8 历史决议保留
- **v3.x+** (Step 6.2.5+): 候选 X1/X3/X4/X5 promote / Tier 重新 calibration / 等
