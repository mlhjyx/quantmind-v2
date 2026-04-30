# D3.13 战略进度审计 — 2026-04-30

**Scope**: QPB v1.16 / 17 MVP / Wave 1-5 / Phase 3-4 真实进度 vs 文档 vs 代码
**0 改动**: 纯 read-only Read + grep

---

## 1. Q13.1 QPB v1.16 真实状态

`docs/QUANTMIND_PLATFORM_BLUEPRINT.md` (Read L1-80) 实测:

**QPB v1.16 状态 (Session 42 末 2026-04-28 22:00)**:
- **Wave 1 ✅ 完结 7/7** (MVP 1.1-1.4 + Platform Skeleton)
- **Wave 2 ✅ 完结** (Data Lineage U3 / MVP 2.1a-2.3)
- **Wave 3 ✅ 完结 5/5**:
  - MVP 3.1 Risk Framework ✅ (Session 30, PR #55-#61, 6 PR + Risk v2 #143-#148 9 PR)
  - MVP 3.2 Strategy Framework ✅
  - MVP 3.3 Signal-Exec Framework ✅ (Session 37-40, PR #107-#118)
  - MVP 3.4 Event Sourcing Outbox ✅ (Session 41)
  - MVP 3.5 Evaluation Gate Framework ✅ (Session 42, PR #123-#125)
- **Wave 4 进行中** (Observability + Performance Attribution + CI/CD + Backup & DR):
  - MVP 4.1 Observability ✅ batch 1+2.1+2.2 完结 (Session 43, PR #131-#133)
  - MVP 4.1 batch 3.x SDK migration ✅ 13/17 (Session 44 Part 1)
  - Risk Framework v2 ✅ Phase 1+0+2+0a+1.5a+1.5b (Session 44 Part 2, PR #143-#148)
  - **MVP 4.2 / 4.3 / 4.4 待启**

→ **Q13.1 ✅ 验证 QPB v1.16 frontmatter claim**: Wave 3 5/5 完结 + Wave 4 启动. CLAUDE.md L841 stale ("QPB v1.4" 12 versions 漂移, F-D3B-1).

---

## 2. Q13.2 Wave 1-5 进度

| Wave | 描述 | 文档 % | 实测代码 % | 状态 |
|---|---|---|---|---|
| Wave 1 | Skeleton + Config + DAL + Registry + Knowledge | 100% | 100% | ✅ 完结 |
| Wave 2 | Data Framework + DataSource + DAL + Lineage | 100% | 100% | ✅ 完结 |
| Wave 3 | Risk + Strategy + Signal-Exec + Outbox + Eval | 100% | 100% | ✅ 完结 5/5 (但 MVP 3.1 Risk Framework v2 9 PR + Step 4-5 实测发现 silent drift = T0-15/16/17/18 P0 残留) |
| Wave 4 | Observability + Perf Attribution + CI/CD + Backup | ~25% | ~20% | 🟡 进行中 (MVP 4.1 batch 1-3 ✅, **4.1 missing migrations P0 阻塞** F-D3A-1) |
| Wave 5+ | (UI Dashboard / DuckDB / etc) | 0% | 0% | 待启 |

→ **F-D3B-20 (P1 cross-link)**: Wave 3 标 ✅ 完结但 Risk Framework v2 P0 真生产 silent drift 暴露 (T0-15/16/17/18) — **完结 ≠ 健康**. 文档 100% 但生产真金保护有 4 项 P0/P1 债. 留 PT 重启 gate prerequisite (沿用 SHUTDOWN_NOTICE §9).

---

## 3. Q13.3 17 MVP 真实状态

QPB v1.16 frontmatter 称 "17 MVP". 实测 enum:

| MVP | 状态 | 备注 |
|---|---|---|
| MVP 1.1 Platform Skeleton | ✅ | Wave 1 |
| MVP 1.1b Shadow Fix | ✅ | LL-068 沉淀 |
| MVP 1.2 Config | ✅ | Wave 1 |
| MVP 1.2a DAL | ✅ | Wave 1 |
| MVP 1.3a Registry Backfill | ✅ | Wave 1 |
| MVP 1.3b Direction DB 化 | ✅ | Wave 1 (含 wiring) |
| MVP 1.3c Factor Framework 收尾 | ✅ | Wave 1 |
| MVP 1.4 Knowledge Registry | ✅ | Wave 1 |
| MVP 2.1a-c Data Source | ✅ | Wave 2 |
| MVP 2.2 Data Lineage | ✅ | Wave 2 (U3 升维) |
| MVP 2.3 Backtest SDK | ✅ | Wave 2 (Sub1+2+3) |
| MVP 3.1 Risk Framework | ✅ + 🟡 Risk v2 | Wave 3 (P0 残留 T0-15/16/17/18) |
| MVP 3.2 Strategy Framework | ✅ | Wave 3 |
| MVP 3.3 Signal-Exec | ✅ | Wave 3 (Stage 3.0 真切换 PR #116) |
| MVP 3.4 Event Sourcing | ✅ | Wave 3 |
| MVP 3.5 Evaluation Gate | ✅ | Wave 3 |
| MVP 4.1 Observability | 🟡 batch 1+2.1+2.2 + 3.x | Wave 4 (含 F-D3A-1 P0 missing migrations) |

**实测 17 MVP**: 16 ✅ + 1 🟡 (4.1) = **94% completion (按 MVP 数), 但实质 P0 残留 5 项** (F-D3A-1 missing migrations + T0-15/16/17/18)

→ **F-D3B-21 (P2)**: MVP 数完成度 ≠ 真实健康度. QPB frontmatter 100% 完结 claim 与 D3-A 实测 5 P0 残留矛盾, 是定义层面不同 (frontmatter 看 PR merged, 实测看 silent drift / missing migration).

---

## 4. Q13.4 DEV_AI_EVOLUTION + Phase 3/4 进度

### DEV_AI_EVOLUTION

memory + CLAUDE.md L184 引用 DEV_AI_EVOLUTION.md (V2.1, 705 行 0% 实现). LL-068 已沉淀 "设计文档大于实施 = 反模式".

CC 自查 `backend/engines/mining/`:
- gp_engine.py / pipeline_utils.py / factor_dsl.py — GP 实施有 (沿用 Wave 1 / Phase 3 MVP A factor lifecycle)
- LLM 因子生成器 / 4 Agent / Hermes Agent — 0 实施 (仅设计稿)

**F-D3B-22 (P3)**: DEV_AI_EVOLUTION V2.1 705 行 80% 仍 0% 实现 (LL-068 沉淀已 22 天, 无新进展). 留 D3-C 整合 / 批 2 决议简化模板.

### Phase 3 / Phase 4 (V4 路线图, CLAUDE.md L15)

实测 V4 路线图状态:
- Phase 1.1 ✅
- Phase 1.2 ✅
- Phase 2.1 ❌ NO-GO
- Phase 2.2 ❌ NO-GO
- Phase 2.3 ✅ 诊断
- Phase 2.4 ✅ 探索 + WF PASS
- PT 配置更新 ✅
- **Phase 3 自动化** — Wave 3 已替代 (MVP 3.1-3.5 全 ✅)
- **Phase 4 PT 重启** — 待 user 决议 (Step 4 修订 + Step 5 落地后, 真账户 0 持仓 ground truth 已 align 到"暂停" 状态)

→ **F-D3B-23 (INFO)**: V4 路线图与 QPB Wave 设计**双轨**, V4 Phase 3 实质被 Wave 3 替代. CLAUDE.md L15 V4 路线图未反映 Wave 1-5 真实进度 (沿用 F-D3B-1 doc rot).

---

## 5. Q13.5 整体战略与现实差距

| 维度 | 文档 ambitious | 实测真相 | 差距 |
|---|---|---|---|
| MVP 完成数 | 17/17 (94%, ✅ 16 + 🟡 1) | ✅ frontmatter 准确 | 0 |
| 真金生产保护 | "Risk Framework v2 5 维度全覆盖 + 9 PR 全闭环" (Session 44 末 handoff) | 实测 T0-15/16/17/18 4 P0/P1 债 + F-D3A-1 P0 missing migrations + 真账户已清仓 | **🔴 严重** (生产 4 P0 / 1 阻塞) |
| PT 状态 | "PT 重启 gate 剩 2 项" (memory frontmatter) | 真账户 0 持仓 + cash ¥993,520 + LIVE_TRADING_DISABLED + Beat restart 后静音 | 🟡 已超 "重启 gate" 范畴 |
| Wave 5+ | "0% 待启" | ✅ 一致 | 0 |
| 文档同步 | "QPB v1.16" / "Wave 3 ✅ 5/5" | CLAUDE.md L841 stale "QPB v1.4" + memory frontmatter 没 D3-A 全 | ⚠️ 文档同步层 stale |

→ **F-D3B-24 (P1)**: Wave 3 标 ✅ 完结但 5 P0 真生产残留 (silent drift + missing migration). 战略层 frontmatter "100% 完结" 是 PR merged 层面准确, 但生产健康层面有 5 P0 阻塞 PT 重启. **真健康度 ~75%** (战略 PR ✅ 100% × 生产 ✅ 75%).

---

## 6. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3B-20 | Wave 3 标完结但 Risk Framework v2 真生产 silent drift = T0-15/16/17/18 + F-D3A-1 missing migrations 5 P0 残留 | P1 cross-link |
| F-D3B-21 | MVP 17/17 完成度 ≠ 真实健康度 (frontmatter 看 PR merged, 实测看 silent drift / missing migration) | P2 |
| F-D3B-22 | DEV_AI_EVOLUTION V2.1 705 行 80% 仍 0% 实现 (LL-068 沉淀 22 天无新进展) | P3 |
| F-D3B-23 | V4 路线图与 QPB Wave 双轨, CLAUDE.md L15 未反映 Wave 1-5 真实进度 | INFO |
| F-D3B-24 | 战略层 PR ✅ 100% × 生产 ✅ 75% = 真健康度 ~75%, 5 P0 阻塞 PT 重启 | P1 |

---

## 7. 处置建议

- **PT 重启 gate prerequisite** (沿用 SHUTDOWN_NOTICE §9): 修 T0-15/16/17/18 + F-D3A-1 + DB stale 清 + paper-mode 5d dry-run
- **D3-C 整合 PR**: CLAUDE.md L15 V4 路线图与 Wave 1-5 双轨同步
- **批 2 决议**: DEV_AI_EVOLUTION 简化或归档 (沿用 LL-068 V2.1 简化模板)
- **战略层文档真健康度**: frontmatter 加 "P0 残留" 字段, 区分 "PR merged" 与 "生产健康"
