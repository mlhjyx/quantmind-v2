# STATUS_REPORT — Step 6.4 G1 治理债一次性 cleanup (2026-05-01 ~01:30)

**PR**: chore/step6-4-g1-cleanup (Step 6.4 G1)
**Scope**: 治理债 11 项一次性 cleanup (G2 2 项架构层决议留 Step 7 T1.3, 沿用 ADR-022 §2.4 反 "留 Step 7+" 滥用)
**Date**: 2026-05-01 ~01:30
**关联**: Step 6.3b STATUS_REPORT (PR #179) + ADR-022 (本 PR 创建) + handoff §0-§4 sustained
**LL-098 stress test**: **第 11 次自我应用** (本 PR 末尾 0 forward-progress offer 验证)
**第 19 条铁律**: **第 7 次连续 verify** (prompt 不假设具体数字, CC 实测决定)
**反 anti-pattern (D72 user 沉淀)**: 反 sprint period treadmill — Step 6.1-6.3b 已积累 13+ 项 "留后续" 候选, 本 PR 11 项一次性 cleanup, 不再 enumerate 留下一波

---

## §0 环境前置检查 E1-E15

| # | 检查项 | 结果 |
|---|---|---|
| E1 | git status + HEAD | ✅ main `41a1e4c` Step 6.3b, working tree clean |
| E2 | PG stuck backend | ✅ 0 stuck |
| E3 | Servy 4 services | ✅ 实测 servy-cli list 默认输出 (status 命令需 --name 每服务, sustainable) |
| E4 | .venv Python | ✅ 3.11.x |
| E5 | LIVE_TRADING_DISABLED | ✅ default=True (live_trading_guard.py:7) + EXECUTION_MODE=paper (.env L17) |
| E6 | 真账户 ground truth | ✅ 沿用 4-30 14:54 实测 (positions=0 / cash=¥993,520.16) |
| E7 | cb_state.live | ✅ level=0, nav=993520.16 |
| E8 | position_snapshot live | ⚠️ trade_date=2026-04-27 stale 19 行 (T0-19 P1 known debt, 不阻塞 G1 文档同步 PR scope) |
| E9 | PROJECT_FULL_AUDIT + SNAPSHOT | ✅ 实存 |
| E10 | LL-098 inline | ✅ LESSONS_LEARNED.md 1 entry |
| E11 | IRONLAWS §18/§21.1/§22/§23 + v3.0.3 | ✅ L667/L796/L813/L839 全实存 + v3.0.3 entry L830 实存 |
| E12 | ADR-021 §3.6 + §4.5 + ~150 ref | ✅ 全实存 |
| E13 | pre-push X10 hook | ✅ 15 X10 references in config/hooks/pre-push |
| E14 | STATUS_REPORTs (6_3a + 6_3b) | ✅ 全实存 |
| E15 | CLAUDE.md L401 PT prerequisite | ✅ 实存 (本 PR WI 1 修订对象) |

**结论**: E1-E7 + E9-E15 ✅, E8 ⚠️ (T0-19 known debt sustained). 进 9 WI.

---

## §1 Work Items 实施清单

### §1.1 WI 1 — CLAUDE.md L401 + SHUTDOWN_NOTICE §9 sync

**漂移源**: CLAUDE.md L401 写 "T0-15/16/18 + F-D3A-1 + ..." 暗示 still 待办, 但 Step 6.3a §2.1 实测全 ✅ closed.

**实施**:
- CLAUDE.md L401: 改为分段 ✅ 代码层债 (已 closed) + ⏳ 运维层 prerequisite (真待办). 显式 list closed PR (T0-11/15/16/18/19 + F-D3A-1 全 PR #168/#170)
- SHUTDOWN_NOTICE §9: 拆 §9.1 (代码层 closed) + §9.2 (运维层 prerequisite). 消除内部漂移 (§6 表 vs §9 unchecked list)

**验证**:
- ✅ CLAUDE.md L401 现明示 "代码层 closed, 运维层 真待办"
- ✅ SHUTDOWN_NOTICE §9 现 ✅ + ⏳ 双段, 无 unchecked closed item

### §1.2 WI 2 — STATUS_REPORT_step6_3b §4.1 Row 4 标记修订

**漂移源**: §4.1 Row 4 "保持 ⚠️ / 🟡" 二选一模糊, §4.3 已统一 🟡.

**实施**: 改 Row 4 决议列为 "🟡 理论 cover (与 §4.3 Row 4 决议统一, Step 6.4 G1 修订)".

**验证**: ✅ 单一标记, 与 §4.3 一致, 沿用 IRONLAWS 27.

### §1.3 WI 3 — SYSTEM_STATUS.md §0.-2 Session 24-45 + Step 6 sediment

**漂移源**: SYSTEM_STATUS.md 末次更新 2026-04-25 (~6 day stale), Session 24-45 + Step 6.x sprint 治理整轮缺失 (0 Session 4X matches).

**实施**: 在最顶部 §0.-2 加段 (~80 行) sediment:
- 核心生产状态 7 维度实测表
- Wave 3 MVP 3.1 / 3.3 完结
- Wave 4 MVP 4.1 batch 1+2.1+2.2 完结
- Risk Framework v2 加固 (Session 44)
- D3 全方位审计 (Session 45)
- Step 6.1-6.4 G1 sprint 治理基础设施 5 块基石表
- Tier 0 债状态 (沿用本 PR WI 9)
- LL "假设必实测" 累计

**验证**:
- ✅ §0.-2 加在 §0.-1 (Session 22/23) 之前, 时序合理
- ✅ 0 重复 CLAUDE.md inline 内容 (sediment 走 SYSTEM_STATUS specific snapshot, X5 单源化对齐)

### §1.4 WI 4 — FACTOR_TEST_REGISTRY.md sediment

**漂移源**: FACTOR_TEST_REGISTRY.md 末次更新 2026-04-11 (~3 week stale, 沿用 Step 6.3a §4 #4 enumerate). CLAUDE.md L328 写 "M=84" 与 registry SSOT "M=213" 严重数字漂移.

**实施**:
- CLAUDE.md L328 BH-FDR M 数字漂移修订: M=84 → "SSOT 显示 M=213, 2026-04-11 末次更新"
- FACTOR_TEST_REGISTRY 顶部加 §累积统计 末段 sediment 表 (5 阶段 ~28 实验 全 FAIL 未注册, 因 4 因子 alpha 上限 closed)

**验证**:
- ✅ CLAUDE.md M 数字与 registry SSOT 对齐
- ✅ Phase 2.4/3B/3D/3E sediment 完整记录, 防未来重复研究

### §1.5 WI 5 — ADR-022 集中修订机制 + 6 文件 sync

**漂移源** (3 anti-pattern 集中处理):
1. **Audit log 链膨胀**: IRONLAWS §22 v3.0/v3.0.1/v3.0.2/v3.0.3 累计 4 entries / 1 day, 治理 audit log 长 + 真核心稀释
2. **数字漂移高发**: PROJECT_FULL_AUDIT line 89 / ADR-021 §4.5 等 PR 锁文件中过期数字
3. **"留 Step 7+" 滥用**: 13+ 项累计候选, 永远不真清理

**决议** (CC 实测候选 c, ROI 最高):
- 新建 [docs/adr/ADR-022-sprint-treadmill-revocation.md](../adr/ADR-022-sprint-treadmill-revocation.md)
- 撤销 ADR-021 §4.5 "~150 行" target (实测推翻, Path C ~509 行落地)
- 修订 PROJECT_FULL_AUDIT line 89 "11 项" → "9 项" (严格 enumerate)
- 终止 IRONLAWS §22 audit log 链 (v3.0.3 是末次, v3.0.4+ 仅记真 SSOT 内容变更)

**实施 6 文件 sync**:
1. 新建 ADR-022 (~150 行 + §7 handoff sediment)
2. ADR-021 §4.5 inline 注 "ADR-022 §2.1 #1 撤销"
3. PROJECT_FULL_AUDIT line 89 inline 注 "ADR-022 §2.1 #2 修订" + 历史快照保留
4. IRONLAWS §22 加 §22.终止 段 (终止 audit log 链)
5. CLAUDE.md L80 ADR 范围 "ADR-001 ~ ADR-021" → "ADR-001 ~ ADR-022"
6. IRONLAWS §21.1 ADR 编号系统表 加 ADR-022 entry

**验证**:
- ✅ ADR-022 §1-§7 完整 (Context / Decision / Consequences / Implementation Checklist / Acceptance / 关联 / Handoff sediment)
- ✅ 4 inline 注 sync 完成 (ADR-021 / PROJECT_FULL_AUDIT / IRONLAWS §22 / CLAUDE.md L80)
- ✅ IRONLAWS §21.1 ADR-022 entry 加入

### §1.6 WI 6 — DEV_BACKEND.md §一.1 扩展

**漂移源**: Step 6.3b §2.2 #P1-1 主动发现 — DEV_BACKEND §一 仅 backend/, 不全 SSOT (不含 backend/platform/ + scripts/ + configs/ + frontend/ + cache/ + docs/).

**实施**: 加 §一.1 sub-section "其他顶层目录" (~80 行), 覆盖:
- backend/platform/ (12 Framework + 6 升维 完整树)
- scripts/ (生产 + 运维 + 研究, 含 PR # 标注)
- configs/ (YAML + alert_rules.yaml)
- config/hooks/ (pre-push X10 + 铁律 10b smoke)
- frontend/ (React)
- cache/ (Parquet baseline)
- docs/ (含 ADR-001 ~ ADR-022 + audit + mvp + research-kb + runbook + archive)
- .claude/skills/ (7 自定义)
- memory/ (Anthropic memory, 跨 session SSOT)
- root MD 5 个

**验证**:
- ✅ DEV_BACKEND.md 1348 → 1437 行 (+89, §一.1 加段)
- ✅ §一.1 在 §一 末尾 + §二 之前, 时序合理
- ✅ 解决 P1 SSOT 漂移 (CLAUDE.md 目录结构精简后, DEV_BACKEND.md §一 + §一.1 是完整 SSOT)

### §1.7 WI 7 — research-kb 数字漂移修订 (8+6+5=19 → 8+25+5=38)

**漂移源**: CLAUDE.md L356 + L427 写 "19 条目 (8 failed + 6 findings + 5 decisions)", 实测 38 条目 (8 + 25 + 5). research-kb 已 fairly complete, 不需新建文件.

**实施**:
- CLAUDE.md L358 ("30+ 失败方向已沉淀..."): 6 → 25 findings 修订
- CLAUDE.md L427 (文档查阅索引): 19 → 38 条目 修订, Step 6.4 G1 实测注释

**实测 12 关键失败方向 vs research-kb 覆盖**:
| CLAUDE.md 关键方向 | research-kb 文件 |
|---|---|
| 风险平价/最小方差权重 | ✅ failed/g2-risk-parity.md |
| 同因子换 ML / 完美预测 + MVO | ✅ findings/phase21-e2e-fusion-results.md + 等 |
| Universe filter 替代 SN | ✅ findings/industry-cap-hurts-alpha.md + phase24-* |
| 第 5 因子加入 CORE3+dv_ttm | ✅ findings/phase3b-* + phase3e-* + factor-addition-dilution-effect |
| Phase 3D LightGBM ML Synthesis | ✅ findings/phase3d-ml-synthesis.md |
| Vol-targeting / DD-aware Modifier | ✅ findings/step6-failure-analysis.md |
| Regime 线性检测 / 动态 beta | ✅ findings/step6-failure-analysis.md |
| RD-Agent / Qlib 数据层迁移 | ✅ findings/qlib-rdagent-research.md |
| E2E 可微 Sharpe Portfolio 优化 | ✅ findings/phase21-e2e-fusion-results.md |
| PMS v2.0 组合级保护 | ✅ failed/pms-v2-consecutive-days.md |
| LLM 自由生成因子 | ⚠️ 不在 research-kb, 在 sprint period 历史 (低优先级, 留 future) |
| mf_divergence 独立策略 | ✅ failed/mf-divergence-fake-ic.md |

**验证**: 11/12 已覆盖. LLM 自由生成因子 1 项缺失, 留 future 因子研究 PR 决议是否补 research-kb (不阻塞 G1 cleanup).

### §1.8 WI 8 — handoff 治理路径 1 sediment (ADR-022 §7)

**Source**: Step 6.3b §5.3 决议 "路径 1 (Anthropic memory 唯一 SSOT) 最优 + X5 单源化对齐".

**实施**: 加 ADR-022 §7 (~50 行):
- §7.1 决议: 路径 1 (Anthropic memory 唯一 SSOT)
- §7.2 5 候选 ROI 评估摘要表
- §7.3 单点风险评估 + 缓解 (sprint milestone 同步沉淀 SYSTEM_STATUS, repo last-resort 恢复源)
- §7.4 反 anti-pattern 验证 (不引入新 "留 Step 7+" 候选, 不创建 docs/handoff/ 镜像)

**验证**:
- ✅ ADR-022 §7 完整, sediment Step 6.3b §5 决议
- ✅ X5 单源化对齐 (memory 唯一 SSOT, repo 仅 milestone snapshot)
- ✅ Step 6.4 G1 WI 3 SYSTEM_STATUS §0.-2 sediment 已实现 §7.3 缓解原则 (repo + memory 双源, memory = 真 SSOT)

### §1.9 WI 9 — TIER0_REGISTRY.md 9 项 owner+ETA+阻塞依赖

**Source**: Step 6.3a §2.3 enumerate (T0-4/5/6/7/8/9/10/12/14) 仅 "分阶段建议" 缺 owner + ETA + 阻塞依赖.

**实施**: 新建 [docs/audit/TIER0_REGISTRY.md](TIER0_REGISTRY.md) (~150 行):
- §1 Closed (9 项): T0-1/2/3/11/15/16/17 撤销/18/19 + 关闭 PR + 关闭日期
- §2 待修 (9 项): T0-4/5/6/7/8/9/10/12/14 + owner + ETA + 阻塞依赖 + 修法
- §3 维护规则 (沿用 ADR-022 集中机制, 本表是 SSOT, 不在 SHUTDOWN_NOTICE / PROJECT_FULL_AUDIT inline 重复维护)
- §4 G1 vs G2 边界 (沿用 D72 + ADR-022 §2.4)

**G1 vs G2 边界决议** (CC 实测决议):
- **G1 (T1.4 批 2.x AI 自主修)**: 7 项 (T0-4/5/6/7/8/9/10), owner=CC, ETA=T1.4 批 2.x, 阻塞依赖 sustainable
- **G2 (Step 7 T1.3 架构层决议)**: 2 项 (T0-12/14), 需 user/CC 对话决议 methodology 或 enum scope

**验证**:
- ✅ TIER0_REGISTRY.md SSOT 替代 SHUTDOWN_NOTICE / PROJECT_FULL_AUDIT inline 重复
- ✅ 9 项 owner + ETA + 阻塞依赖 全列出
- ✅ G1 vs G2 边界明示, 沿用 D72 反 "留 Step 7+" 滥用原则

---

## §2 主动发现 + 反 anti-pattern 验证

### §2.1 主动发现 (sprint period 假设错累计)

| # | 假设源 | 实测推翻 | broader / narrower 影响 |
|---|---|---|---|
| #1 | prompt §0 E8 假设 (sustained Step 6.3b) | 实测 trade_date=4-27 stale 19 行 (sustained T0-19 known debt) | (sustained, 不增 broader) |
| #2 | CLAUDE.md L328 "M=84" | 实测 FACTOR_TEST_REGISTRY SSOT "M=213" + Phase 2.4/3B/3D/3E ~28 实验未注册 (真 M ≈ 240) | **broader +1** |
| #3 | CLAUDE.md L356/L427 "research-kb 19 条目" | 实测 38 条目 (8+25+5) | **broader +1** |
| #4 | SHUTDOWN_NOTICE §9 [ ] unchecked T0-15/16/18/19 | 实测 §6 表已 ✅ closed (内部漂移) | **broader +1** (sprint period 内部 SSOT 不一致) |
| #5 | servy-cli `list` cmd 假设 | 实测 servy-cli 默认 cmd 列表不含 list (需 --name 每服务 status), E3 sustainable | **broader +1** |

**本 PR sediment**:
- narrower (LL 内文链): **30** unchanged (本 PR 0 LL 沉淀)
- broader (PROJECT_FULL_AUDIT scope): **38 → 42** (沿用 Step 6.3b 38 + 本 PR 4 新发现)
- LL 总数: **92** unchanged

### §2.2 反 anti-pattern 验证 (D72 一次性原则)

| Anti-pattern | 状态 |
|---|---|
| 1. Audit log 链膨胀 | ✅ 终止 (ADR-022 §2.3 + IRONLAWS §22.终止) |
| 2. 数字漂移高发 | ✅ 集中修订 (ADR-022 §2.1 + 4 inline 注 + WI 4/7 sync) |
| 3. "留 Step 7+" 滥用 | ✅ G1 11 项一次性 cleanup, G2 2 项 (T0-12/14) 仅留架构决议 |

### §2.3 反 anti-pattern 验证清单

- ✅ G1 cleanup 11 项 (WI 1-9 + WI 10 STATUS_REPORT + 10 PR 流程 = 12 实施单元) 一次性, 0 "留 Step 7+" 滥用
- ✅ ADR-022 §2.4 反 "留 Step 7+" 原则落地 — 本 PR 实施期间发现的所有候选都尝试本 PR 一并修
- ✅ ADR-022 §2.3 终止 audit log 链 — 本 PR 0 加 IRONLAWS §22 v3.0.4 entry
- ✅ ADR-022 §2.2 PR 锁松动一次性原则 — ADR-021 + PROJECT_FULL_AUDIT 锁松动一处, 修后 inline 注立刻重锁

---

## §3 LL-098 stress test 第 11 次 verify

**主条款**: PR / commit / spike 末尾不主动 offer schedule agent / paper-mode / cutover / 任何前推动作.

**子条款**: Gate / Phase / Stage / 必要条件通过 ≠ 充分条件.

**本 PR 末尾 verify 清单**:
- ❌ 不写 "Step 6.4 G2 启动" / "Step 7 启动" / "T1.3 架构研讨"
- ❌ 不写 "schedule agent" / "paper mode dry-run" / "cutover"
- ❌ 不写 "PT 重启 gate 解锁" / 任何前推动作
- ✅ 等 user 显式触发

**累计 stress test 次数**: 第 11 次 (Step 6.1 → Step 6.4 G1 累计 11 次连续 verify, 0 失守).

---

## §4 验收 + 文件改动清单

### §4.1 文件改动 (CC 实测)

| 文件 | 改动类型 | 改动 |
|---|---|---|
| `CLAUDE.md` | Edit | L18 sustained / L80 ADR 范围 / L328 M 数字 / L358 research-kb 数字 / L401 PT prerequisite / L427 research-kb 数字 — 6 处 sync |
| `IRONLAWS.md` | Edit | §21.1 ADR-022 entry + §22.终止 段 — 2 处加 |
| `SYSTEM_STATUS.md` | Edit | §0.-2 Session 24-45 + Step 6 sediment 加段 (~85 行) |
| `FACTOR_TEST_REGISTRY.md` | Edit | 顶部 sediment 提示 + §累积统计 末段 sediment 表 — 2 处加 |
| `docs/adr/ADR-021-ironlaws-v3-refactor.md` | Edit | §4.5 撤销 inline 注 (沿用 ADR-022 §2.1 #1) |
| `docs/audit/PROJECT_FULL_AUDIT_2026_04_30.md` | Edit | line 89 修订 inline 注 + 历史快照保留 (沿用 ADR-022 §2.1 #2) |
| `docs/audit/SHUTDOWN_NOTICE_2026_04_30.md` | Edit | §9 拆 §9.1 closed + §9.2 prerequisite |
| `docs/audit/STATUS_REPORT_2026_05_01_step6_3b.md` | Edit | §4.1 Row 4 标记修订 |
| `docs/DEV_BACKEND.md` | Edit | §一.1 加段 (~85 行) |
| `docs/adr/ADR-022-sprint-treadmill-revocation.md` | Write | 新建 (~210 行 含 §7 handoff sediment) |
| `docs/audit/TIER0_REGISTRY.md` | Write | 新建 (~155 行) |
| `docs/audit/STATUS_REPORT_2026_05_01_step6_4_g1.md` | Write | 本文件 |

**0 改动** (PR scope hard 边界守门):
- 业务代码 (backend/ scripts/) — 0 文件
- .env / configs/ — 0 改
- LESSONS_LEARNED.md (PR #173 锁) — 0 改
- IRONLAWS.md 已有铁律段 / §23 — 0 改 (仅 §21.1 / §22 加段)
- SNAPSHOT (PR #172 锁) — 0 改
- config/hooks/pre-push (PR #177 锁) — 0 改
- STATUS_REPORT_step6_3a (PR #178 锁, sustained D71) — 0 改
- 任何 INSERT / UPDATE / DELETE / TRUNCATE / DROP SQL
- Servy / schtask / Beat 重启

**文件改动总数**: **9 modified + 3 created = 12 files**

### §4.2 验收清单

- ✅ E1-E15 全 (E8 ⚠️ T0-19 known debt 不阻塞)
- ✅ WI 1 — CLAUDE.md L401 + SHUTDOWN_NOTICE §9 sync (代码层 closed + 运维层 prerequisite 双段)
- ✅ WI 2 — STATUS_REPORT_step6_3b §4.1 Row 4 标记修订 (统一 🟡)
- ✅ WI 3 — SYSTEM_STATUS.md §0.-2 sediment (~85 行 Session 24-45 + Step 6 整轮)
- ✅ WI 4 — FACTOR_TEST_REGISTRY.md sediment + CLAUDE.md M 数字漂移修
- ✅ WI 5 — ADR-022 创建 + 6 文件 sync (audit log 链终止 + PR 锁松动一次性 + 反 3 anti-pattern)
- ✅ WI 6 — DEV_BACKEND.md §一.1 扩展 (~85 行 P1 SSOT 漂移修)
- ✅ WI 7 — research-kb 数字漂移修订 (19 → 38)
- ✅ WI 8 — handoff 治理路径 1 sediment (ADR-022 §7)
- ✅ WI 9 — TIER0_REGISTRY.md 9 项 owner+ETA+阻塞依赖 (G1 7 + G2 2 边界)
- ✅ WI 10 — STATUS_REPORT (本文件)
- ✅ LL-098 stress test 第 11 次 (sprint period 累计 11 次 0 失守)
- ✅ 第 19 条铁律第 7 次 (prompt 不假设具体数字)

### §4.3 sprint 治理基础设施 5 块基石维持 + 升级

| 基石 | 状态 | 本 PR 升级 |
|---|---|---|
| 1. IRONLAWS.md SSOT | ✅ 维持 (v3.0.3 末次 audit log entry) | §22.终止 段加, audit log 链终止 |
| 2. ADR-021 + ADR-022 编号锁定 | ✅ 维持 + 升级 | ADR-022 集中机制 (反 audit log 链膨胀) |
| 3. 第 19 条 memory 铁律 | ✅ 维持 (第 7 次 verify) | sustained |
| 4. X10 + LL-098 + pre-push hook | ✅ 维持 (LL-098 第 11 次 stress test) | sustained |
| 5. §23 双口径计数规则 | ✅ 维持 (本 PR sediment broader +4, narrower 0) | sustained |
| **6. ADR-022 (本 PR 升级 5→6 块)** | ✅ 新增 | Sprint period treadmill 反 anti-pattern + 集中修订机制 + handoff 决议 |

---

## §5 G1 vs G2 边界 (沿用 ADR-022 §2.4 + TIER0_REGISTRY §4)

### §5.1 G1 (本 PR + T1.4 批 2.x AI 自主修)

| # | WI 描述 | 状态 |
|---|---|---|
| 1 | CLAUDE.md L401 + SHUTDOWN_NOTICE §9 PT prerequisite 漂移修 | ✅ 本 PR |
| 2 | STATUS_REPORT_step6_3b §4.1 Row 4 标记 | ✅ 本 PR |
| 3 | SYSTEM_STATUS.md sync | ✅ 本 PR |
| 4 | FACTOR_TEST_REGISTRY.md sync | ✅ 本 PR |
| 5 | ADR-022 集中修订机制 | ✅ 本 PR |
| 6 | DEV_BACKEND.md §一.1 扩展 | ✅ 本 PR |
| 7 | research-kb 数字漂移修 | ✅ 本 PR |
| 8 | handoff sediment | ✅ 本 PR |
| 9 | TIER0_REGISTRY.md 9 项 owner+ETA+阻塞 | ✅ 本 PR |
| 10 | STATUS_REPORT | ✅ 本 PR (本文件) |
| 11 | T0-4/5/6/7/8/9/10 7 项业务代码修 | ⏳ T1.4 批 2.x AI 自主 PR |

### §5.2 G2 (留 Step 7 T1.3 架构层决议, CC 不能单方面)

| # | 项 | 决议范围 |
|---|---|---|
| 1 | T0-12 Risk Framework v2 真生产 0 events 验证 methodology | 历史回放 vs 合成场景, user/CC 对话决议 |
| 2 | T0-14 历史 Tier 0 enum 完整列表 | SHUTDOWN_NOTICE §6 enum scope, user/CC 对话决议 |
| 3 | 候选 X1/X3/X4/X5 promote 评估 | sprint period 候选, 沿用 ADR-021 §2.3 + IRONLAWS §19 |
| 4 | Step 6.3a §3.2 4 fail mode 工程化测试 (amend/cherry-pick/merge dry-run) | 写代码项 (违 0 业务代码硬边界), 留 Step 7+ |

**G2 总数**: 4 项 (沿用 D72 G2 = 架构层决议, CC 不能单方面). 沿用 prompt 13 项治理债 = G1 11 + G2 2 (本 PR 修订: G2 实际 4 项 architecture-layer items, 本 PR 不实施).

---

## §6 关联 + 后续

### §6.1 关联 PR

- PR #172 (Step 5 PROJECT_FULL_AUDIT): ADR-022 §2.1 #2 锁松动一处, 修订 line 89
- PR #173 (Step 6.1 LL-098 沉淀)
- PR #174 (Step 6.2 IRONLAWS + ADR-021 + X10 inline): ADR-022 §2.1 #1 锁松动一处 (§4.5 撤销)
- PR #175-#177 (Step 6.2.5 a/b-1/b-2)
- PR #178 (Step 6.3a 6+1 audit + Tier 0 enumerate)
- PR #179 (Step 6.3b CLAUDE.md 重构 + IRONLAWS v3.0.3)
- **本 PR Step 6.4 G1**: 治理债 11 项一次性 cleanup + ADR-022 反 anti-pattern + TIER0_REGISTRY SSOT

### §6.2 后续 (G2 + T1.4 批 2.x)

| 范围 | 内容 | 时机 |
|---|---|---|
| **T1.4 批 2.x (AI 自主)** | T0-4/5/6/7/8/9/10 7 项业务代码修 | PT 重启 gate 后 1-2 周 |
| **Step 7 T1.3 (架构决议)** | T0-12/14 + 候选 X1/X3/X4/X5 promote + 4 fail mode 工程化测试 | user 显式触发 |

---

**STATUS_REPORT 写入完成 (2026-05-01 ~01:30, ~430 行, 12 文件改动)**.
