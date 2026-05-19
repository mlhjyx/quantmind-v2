# D Decision Log SSOT Registry

**Document ID**: DECISION_LOG
**Status**: Phase 4.2 CC implementation, D72-D78 sediment 起手, D1-D71 backfill 留 Layer 2 sprint Week 2-3 candidate
**Source**: F-D78-260 (D 决议链 0 SSOT registry) + Topic 2 决议
**Created**: 2026-05-01 (Phase 4.2 CC implementation)

---

## §1 Schema

每 D 决议 entry:

```yaml
- id: D-{N}
  date: YYYY-MM-DD HH:MM (CC 实测 timestamp, 不假设)
  source: user / Claude.ai / CC / cross-source 核 verify
  context: sprint period sustained context cite (短句 sustained)
  content: 决议核内容 (sustained verbatim cite candidate)
  related: 关联 PR / ADR / Finding / 等 (sustained sprint period sustained source 核 verifiable)
  verdict: closed / sustained / superseded / overturned
  notes: optional sustained
```

---

## §2 D72-D79 sediment (Phase 4.2 CC 起手)

### D-72

- **id**: D-72
- **date**: 2026-04-30 (sprint period, CC 实测 timestamp verify)
- **source**: user 反问
- **context**: sprint period treadmill anti-pattern 反 candidate
- **content**: "为什么不一次性? 而要遗留?" 推翻 D 选项 sprint period treadmill
- **related**: ADR-022 (sprint period treadmill 反 anti-pattern, PR #180)
- **verdict**:
- **notes**: ADR-022 核 source

### D-73

- **id**: D-73
- **date**: TODO (Layer 2 sprint Week 2-3 backfill, CC sprint period 4 源 cross-validate)
- **source**: user 5-01 触发 audit prompt 反问编号 (audit governance/07 + governance/09 cite)
- **context**: sprint period 4-30/5-01 D78 audit prompt 反问编号
- **content**: TODO — user verbatim cite 待补 (Layer 2 sprint Week 2-3 candidate)
- **related**: SYSTEM_AUDIT_2026_05 / governance/07_d_decision_enumerate_real.md / governance/09_d_decision_deep_verify.md
- **verdict**: pending sediment (placeholder, Topic 2 B "D1-D71 历史 backfill 留 Layer 2 sprint Week 2-3 candidate" 同源 sequencing)
- **notes**: audit folder cite "user 5-01 触发本审查的 D 反问编号", **individual content 0 sediment**

### D-74

- **id**: D-74
- **date**: TODO (Layer 2 sprint Week 2-3 backfill)
- **source**: user 5-01 触发 audit prompt 反问编号
- **context**: sprint period D78 audit
- **content**: TODO — user verbatim cite 待补 (Layer 2 sprint Week 2-3 candidate)
- **related**: SYSTEM_AUDIT_2026_05
- **verdict**: pending sediment
- **notes**: 同 D-73 source candidate

### D-75

- **id**: D-75
- **date**: TODO (Layer 2 sprint Week 2-3 backfill)
- **source**: user 5-01 触发 audit prompt 反问编号
- **context**: sprint period D78 audit
- **content**: TODO — user verbatim cite 待补 (Layer 2 sprint Week 2-3 candidate)
- **related**: SYSTEM_AUDIT_2026_05
- **verdict**: pending sediment
- **notes**: 同 D-73 source candidate

### D-76

- **id**: D-76
- **date**: TODO (Layer 2 sprint Week 2-3 backfill)
- **source**: user 5-01 触发 audit prompt 反问编号
- **context**: sprint period D78 audit
- **content**: TODO — user verbatim cite 待补 (Layer 2 sprint Week 2-3 candidate)
- **related**: SYSTEM_AUDIT_2026_05
- **verdict**: pending sediment
- **notes**: 同 D-73 source candidate

### D-77

- **id**: D-77
- **date**: TODO (Layer 2 sprint Week 2-3 backfill)
- **source**: user 5-01 触发 audit prompt 反问编号
- **context**: sprint period D78 audit
- **content**: TODO — user verbatim cite 待补 (Layer 2 sprint Week 2-3 candidate)
- **related**: SYSTEM_AUDIT_2026_05
- **verdict**: pending sediment
- **notes**: 同 D-73 source candidate

### D-78

- **id**: D-78
- **date**: 2026-04-30 (sprint period, CC 实测 timestamp verify)
- **source**: user 反问
- **context**: 整个项目系统审查决议
- **content**: 一次性审完所有 + 不分 Phase + 不设时长 + 0 修改
- **related**: SYSTEM_AUDIT_2026_05_FRAMEWORK.md + audit Phase 1-10 + PR #182-#190
- **verdict**: closed (audit Phase 10 closed PR #190 merged)
- **notes**: audit 282 finding / 44 P0 治理 / 6 cluster cross-cluster

### D-79

- **id**: D-79
- **date**: 2026-05-01 (sprint period, ~30min 战略对话 closed)
- **source**: cross-source user + Claude.ai ~30min 战略对话
- **context**: Layer 1 sprint Week 1 closed PR #192, Layer 2 sprint Week 2 起手前 prerequisite Layer 4 协作 SOP align
- **content**: Topic 1-4 决议 closed Layer 4 SOP align (Topic 1 ex-ante prevention SOP / Topic 2 D 决议链 SSOT registry / Topic 3 4 源 SSOT cross-verify / Topic 4 alpha continuous verify)
- **related**: protocol_v1.md (docs/audit/2026_05_audit/) + DECISION_LOG.md (本文件) + Phase 4.2 CC implementation (本 PR)
- **verdict**: (Phase 4.2 CC implementation 起手, PR push)
- **notes**: Topic 1-4 决议 4 项 verbatim cite protocol_v1.md §2

---

## §3 D1-D71 backfill 留 Layer 2 sprint Week 2-3 candidate

sprint period Anthropic memory cite + Claude.ai conversation_search + sprint state cite cross-validate ~1-2 day CC cost. 核 sequencing Layer 2 sprint Week 2-3 candidate.

**已知 D-1~D-14 source candidate** (CLAUDE.md cite + sprint state frontmatter cite):
- D-1, D-2, D-3 (CLAUDE.md cite, ADR-021 编号锁定 决议 — Step 6.2)
- D-1~D-8 (memory/project_sprint_state.md frontmatter sediment)

**已知 prefix D-IDs source candidate** (T1.3 design doc cite, 沿用 governance/09_d_decision_deep_verify.md):
- D-L0, D-L1, D-L2, D-L3, D-L4, D-L5 (5+1 层 decision)
- D-T-A1~A5 / D-T-B1~B3 (Tier A + B decisions)
- D-N1~N4 (不采纳)
- D-M1~M2 (Methodology)

**21 numbered + 20 prefix = 41 D-decision** sprint period sediment but 0 SSOT (F-D78-260 根因), **本 DECISION_LOG.md 起手 reverse SSOT**.

---

## §4 D80+ ongoing update

每 D 决议新 sprint period ~30s/decision sediment.

**SOP**: 新 D 决议产生时, user OR CC OR Claude.ai 任一 source 立即 update 本文件 §2 schema entry, **不 batch defer** (Topic 2 C 决议).

---

## §5 Topic-Based Decision Narrative (Plan v8 §VIII #26 extension, 2026-05-19 起手)

> **跟 §1-4 D-numbered registry 互补**: §2 D-numbered 是 chronological 战略决议 SSOT; §5 是 **"why we chose X over Y" topic-based 叙述** — 防 future-self 6 月后忘记 stack/data/arch 选型 rationale 重复 fail (e.g. mf_divergence 重测过 5 次, Phase 2.1/2.2/3B/3D/3E 五次证伪 等). 起手日 2026-05-19 Session 58+1 evening (Plan v8 P1 closure batch, 反 LL-187/LL-190 sediment-then-forget pattern).
>
> **格式**: chronological + topic. 每条 ≤ 5 行. 详 ADR 时 link.

### §5.1 技术栈 / Stack Choice

**S1-2024Q4. PostgreSQL 16 + TimescaleDB vs ClickHouse**
- **选**: PG 16.8 + TimescaleDB 2.26.0
- **反**: ClickHouse (列存 OLAP-first)
- **理由**: ClickHouse 列存对纯 read-heavy analytics 更快, 但本项目 PT 实盘 + 因子 incremental write 是**混合 OLTP+OLAP**. PG + Timescale hypertable + chunk exclusion 已足够 (840M factor_values rows / 11M klines / 12M ssd rows 实测 query <1s). 单人维护 + Windows 部署 + 社区 PG 16.8 + Timescale 社区版组合**学习曲线最低**.
- **回头**: sediment 7 个月 0 性能瓶颈, sustained.

**S1-2026Q1. xtquant miniQMT vs OpenCTP / Easytrader**
- **选**: 国金 miniQMT
- **反**: OpenCTP (CTP 期货协议, A 股不支持), Easytrader (screen scraping, 反爬虫 ban 风险)
- **理由**: miniQMT 是国金证券**官方** Python API + 0 反爬虫风险 + 实盘 commission 真实 (万 0.854).
- **回头**: LL-098/099/180/182 sediment 5 axis integration debt, 但 root cause 全是 ad-hoc connection mgmt, 不是 broker 选择问题. sustained.

**S1-2026Q1. React 18 + Tailwind vs Svelte / Vue 3 / Solid**
- **选**: React 18 + TypeScript + Tailwind 4.1
- **反**: Svelte (smaller bundle), Vue 3 (Asia adoption), Solid (signal-based)
- **理由**: React 生态最大 (ECharts/Recharts native binding / Zustand / react-query / Tailwind native). 单人维护 + LLM 生成 React code 最强.
- **回头**: Phase H v3 W1-W6 实测 (LL-187) 0 bottleneck. sustained.

**S1-2026Q1. Celery vs Dramatiq / RQ / arq**
- **选**: Celery 5.x + Redis broker + `--pool=solo`
- **反**: Dramatiq (现代 / less features), RQ (simpler), arq (asyncio-native)
- **理由**: Celery 生态最大 (Beat schedule + canvas + django-celery-results), `--pool=solo` 是 Windows 多线程 trade-off.
- **回头**: LL-189 暴露 `--pool=solo` worker leak (28GB), root cause 是缺 nightly restart 不是 Celery 选择. ADR-086 候选周期 restart sediment. sustained, 强化运维.

**S1-2026Q2. Servy v7.6 vs NSSM**
- **选**: Servy v7.6 (cutover 2026-04-04)
- **反**: NSSM (2014 legacy, batch script 难维护)
- **理由**: Servy 是 modern Rust-written service manager, YAML 配置 / 真 service log 集中 / Windows event log 集成.
- **回头**: LL-181 暴露 schtask 硬化标准 (铁律 43) 跟 Servy 选择无关. NSSM backup 留紧急回滚. sustained.

### §5.2 数据 + 因子 / Data & Factor

**S2-2026Q1. Tushare vs Akshare / Baostock**
- **选**: Tushare (主) + Baostock (副, 5min)
- **反**: Akshare (开源 / 数据全但接口不稳, 爬虫底层), Wind (商业 / 贵)
- **理由**: Tushare API 稳定 + 5000 积分 = 全 A 股 5 年 OHLCV/财务/资金流 SSOT. Baostock 仅作 backup (5min minute_bars 190M rows).
- **回头**: 5-17 klines_daily stale 1 day 是 schtask 触发问题不是 Tushare 选择. sustained.

**S2-2026Q2. CORE3+dv_ttm 4-factor vs 5+ factor synthesis**
- **选**: 4 factor 等权 = alpha 上限
- **反**: 5+ factor ML synthesis / regime-aware switching
- **理由**: Phase 3B+3D+3E **三次独立验证** 4 因子 = 等权 alpha 上限. 8 P1 候选第 5 因子全 FAIL bootstrap p<0.05; LightGBM 4 实验全 FAIL; 微结构 16/16 ROBUST 但 WF 等权 0/6.
- **回头**: Phase 2.1 Layer 2 sim-to-real gap 282% NO-GO. sustained — 4 因子 + Partial SN b=0.50 是当前架构 alpha 上限.

**S2-2026Q1. Partial Size-Neutral b=0.50 vs Universe filter**
- **选**: PT_SIZE_NEUTRAL_BETA=0.50
- **反**: Universe filter (excl 微盘)
- **理由**: Phase 2.4 Part 1 实验 — universe filter 毁灭 alpha (alpha 100% 是微盘贡献). Partial SN b=0.50 是 barbell 平衡.
- **回头**: Step 6-H 5 次独立验证, b=0.50 唯一 effective Modifier. Vol-targeting / DD-aware 全 0 改善. sustained.

### §5.3 架构 / Architecture

**S3-2026Q2. Single Strategy vs Multi-Strategy Diversification**
- **选**: Single strategy CORE3+dv_ttm (PT 当前)
- **反**: Multi-strategy basket (momentum + reversal + 因子分层)
- **理由**: 单 user / 单设备 / Sharpe 0.8659 = 当前 stack 上限. Multi-strategy 增加治理复杂度 (correlation tracking / capital allocation / failure cascade) 但 alpha 上限**没增**. 单人项目 stage 1 应**深** > **广**.
- **回头**: 5-18 audit Top 50 §25 Strategic SPOF: single-bet risk = 真问题, mitigation 是 "**failed direction 8 项 re-eval**". sustained (under review Q3-Q4 ADR-027 §11).

**S3-2026Q2. CORE/Platform 12 Framework vs monolithic FastAPI**
- **选**: backend/qm_platform 12 framework
- **反**: 全塞 backend/app
- **理由**: backend/qm_platform 是横切 (data/factor/strategy/signal/backtest/eval/observability/config/ci/knowledge/resource/backup) 复用 across FastAPI+Celery+scripts.
- **回头**: Wave 1+2 完结, Wave 3+4 进行中. sustained.

**S3-2026Q3. Outbox publisher vs StreamBus.publish_sync for business events**
- **选**: Outbox publisher (qm_platform.observability)
- **反**: ad-hoc StreamBus.publish_sync
- **理由**: Outbox = transactional + retry + lineage. publish_sync = ops alert only.
- **回头**: 5-19 Plan v8 P1-30 closure (commit 70f9557) — DeprecationWarning for business event prefixes. sustained.

### §5.4 运维 + 治理 / Ops & Governance

**S4-2026Q1. PT Top-N=5 灰度 vs Top-N=20 标准**
- **选**: PT_TOP_N=5 (paper-mode dry-run 灰度)
- **反**: PT_TOP_N=20 (标准 PT)
- **理由**: 5-18 P0-7 root cause (commit 2357b90) — pt_live.yaml top_n=20 vs .env=5 漂移 → cascade fail. 修复后 5 灰度保留作 Path B Phase B-1 conservative baseline.
- **回头**: 5-27 Phase B-2 live flip 时 top_n 应 review (5 → 20?). sustained till 5-27 user decision (ADR-085).

**S4-2026Q2. Path B Staged Paper-Dryrun 5d vs Immediate Live Flip**
- **选**: Path B (staged paper-mode 5d dry-run then 5-27 Wed live flip)
- **反**: Path A (immediate live flip 5-20 Tue)
- **理由**: 5-19 user 决议 (ADR-085) — 5-18 LL-180~183 cascade + LL-188 sediment drift 风险 → 5d burn-in observation. User: "做完一个就接着下一个" 但 PT live 是高风险 ops, paper-mode 5d 是 burn-in 不是 5d-window 拖延.
- **回头**: 5-20 Day 1 SH preflight (cron 83e3c350) → Day 1 STATUS_REPORT sediment. sustained till 5-27.

**S4-2026Q2. Sediment-then-implement vs Audit-then-defer**
- **选**: Sediment **必带 implement** (反 LL-187/LL-190 pattern)
- **反**: Sediment-only (audit doc done = done)
- **理由**: Plan v8 §VII heuristic #17 自己 first violation — 5-18 evening 11 audit docs sediment, 但 5/30 suggestion / 5/5 strategic alt / 14/14 open Q 0 implement. LL-187 + LL-190 cross-domain recurrence.
- **回头**: 5-19 Session 58+1 evening implement 持续推进 (P0-12 closed / P0-11 FALSE ALARM / P1-30 / P1-45 / Decision Log §5). sustained.

### §5.5 研究 / Research

**S5-2025Q4. Backtest 加固自建 vs Qlib + ML Signal Layer**
- **选**: 自建 backtest 加固 + Qlib 作 ML 信号层 (route C)
- **反**: 全切 Qlib (data + signal + backtest), 全自建 (refused Qlib)
- **理由**: Qlib 三重阻断: (a) `.bin` 双份数据 (磁盘 2x); (b) Qlib backtest 没 A 股 PMS + 涨跌停; (c) RD-Agent factor proposal 学院派与 A 股 quirks 不 align.
- **回头**: Phase 3D LightGBM 4 实验 FAIL (4-14), Phase 3E-II 微结构 0/6 WF — ML 路线 CLOSED. Qlib ML 信号层无价值. sustained.

**S5-2026Q1. mf_divergence 重测 5 次 vs single-test sediment**
- **选**: 5 次独立重测 (各角度 setup) 全 negative (IC=-2.27% 非 9.1%)
- **反**: 1 次测试 + sediment (避免重复)
- **理由**: 5 次独立角度 (raw IC / neutral IC / paired bootstrap / regime split / WF) — alpha=9.1% 假说 robust 证伪. evidence 累积更强, **不**是浪费.
- **回头**: Decision Log §5 自身使命 — 记录这个 "为什么 5 次" decision 防 future-self 重复. mf_divergence research-kb sediment 后未来 6+ 月不重启. sustained.

**S5-2026Q2. Survivorship Bias P0-11 假设 vs 真值验证**
- **选**: B3 真值 SQL 验证 (5-19 commit a5276df, LL-191)
- **反**: Phase J multi-week research (Plan v8 P0-11 5d-window=NO)
- **理由**: factor_values + klines_daily + stock_status_daily 三层 sediment 含 5743 stocks (含 241/322 退市 + 12.1M ST 行 12.5 年) — Subagent G "EXCLUDES delisted" 假设可证伪. Subagent audit 必跑真值 SQL row count, 不能凭 SQL grep 推断 (LL-191).
- **回头**: 5d backtest sample run 验证残余 §3.1/§3.2/§3.3 (因子真值选股是否选退市 / look-ahead bias / universe filter). sustained, P0-11 FALSE ALARM. ADR-087 候选 (Subagent Audit Assumption Verification SOP).

### §5.6 待加入候选 (TODO)

- S2-2026Q3 PEAD vs reversal/momentum 因子优先级 (4-12 决议)
- S3-2026Q2 Bull/Bear LLM debate vs single-prompt (V3 §16 design)
- S3-2026Q3 V4-Flash vs V4-Pro routing (ADR-036)
- S4-2026Q1 GitHub Actions vs Git pre-push hooks (CI/CD path)
- S5-2026Q2 Risk Framework L1-L4 ladder vs single-tier kill switch
- S5-2026Q2 PMS 三档并入 Risk Framework vs 独立 module (ADR-010)

---

**Maintained by**: CC autonomous + user revisit (Plan v8 §VIII #26 + Topic 2 §2 SSOT)
**Last updated**: 2026-05-19 Session 58+1 evening (P0-11 FALSE ALARM + §5 起手)
**Cross-ref**: ADR Registry (`docs/adr/REGISTRY.md`) — when §5 Decision Log entry promotes to ADR, link both directions
**Reading order** (future-self onboarding): §1-4 D-numbered chronological → §5 topic-based stack/data/arch/ops/research

---

**Document end**.
