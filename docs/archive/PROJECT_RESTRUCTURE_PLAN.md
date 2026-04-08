# 项目结构整理方案

> 日期: 2026-04-07
> 目的: 一次性清理项目积累的结构性混乱，建立防止再次混乱的规则

---

## 1. 当前问题全景

### 根目录散落（18个.md + 9个.txt + 1个tar.gz）
- 8个历史审计报告（AUDIT_RESULTS/BACKEND_FULL_AUDIT/...）→ 应归档
- 3个研究报告（G1/G2/G25）→ 应移到docs/research/
- 9个回测输出.txt（共8.7MB）→ 应删除或移到output/
- 1个compass临时artifact → 应删除
- 1个backup tar.gz → 应移到备份目录
- PHASE_1_PLAN.md → 历史计划，应归档

### docs/目录混乱
- 旧总设计DESIGN_V5（76KB）仍在根目录 → 应标注或归档
- DEVELOPMENT_BLUEPRINT（46KB）→ 与IMPLEMENTATION_MASTER重叠
- SOP_DISASTER_RECOVERY → 可能引用NSSM
- 7个旧版ROADMAP在archive/ → 正常

### CLAUDE.md数字错误（6处）
1. DDL表数: "62张表" → DDL文件45个，DB 62个（差17张是代码动态建的，应说明）
2. DEPRECATED因子: "8个" → 实际5个
3. FULL池: "14个" → 无明确定义，示例momentum_20已DEPRECATED
4. RESERVE: "1个vwap_bias" → 30个PASS因子，RESERVE概念不清
5. BH-FDR M值: "M=202" → FACTOR_TEST_REGISTRY实际用M=69
6. Skills数: "6个" → 实际7个

### .claude/配置过期（3处）
1. `_charter_context.md:22` — 路径指向不存在的根目录TEAM_CHARTER
2. `iron_law_enforce.py` — 铁律编号与_charter_context不匹配
3. `risk-guardian.md:13` — 引用已归档的DEV_NOTIFICATIONS.md

---

## 2. 目标结构

```
quantmind-v2/
├── CLAUDE.md                    ← 入口（数字修正后）
├── SYSTEM_RUNBOOK.md            ← 运行手册
├── PROGRESS.md                  ← 进度跟踪
├── LESSONS_LEARNED.md           ← 经验教训
├── FACTOR_TEST_REGISTRY.md      ← 因子注册表
├── pyproject.toml
├── .gitignore
│
├── docs/
│   ├── design/                  ← 活跃设计文档
│   │   ├── QUANTMIND_V2_FIX_UPGRADE_ROADMAP_V3.md  (总设计)
│   │   ├── DEV_BACKEND.md
│   │   ├── DEV_BACKTEST_ENGINE.md
│   │   ├── DEV_FACTOR_MINING.md
│   │   ├── DEV_FRONTEND_UI.md
│   │   ├── DEV_SCHEDULER.md
│   │   ├── DEV_PARAM_CONFIG.md
│   │   ├── DEV_AI_EVOLUTION.md
│   │   ├── GP_CLOSED_LOOP_DESIGN.md
│   │   ├── RISK_CONTROL_SERVICE_DESIGN.md
│   │   ├── ML_WALKFORWARD_DESIGN.md
│   │   └── QUANTMIND_V2_FOREX_DESIGN.md
│   │
│   ├── reference/               ← 参考文档（不频繁更新）
│   │   ├── QUANTMIND_V2_DDL_FINAL.sql
│   │   ├── TUSHARE_DATA_SOURCE_CHECKLIST.md
│   │   ├── DESIGN_DECISIONS.md
│   │   ├── TECH_DECISIONS.md
│   │   ├── IMPLEMENTATION_MASTER.md
│   │   └── SOP_DISASTER_RECOVERY.md
│   │
│   ├── research/                ← 研究报告（保持现有）
│   │   ├── R1-R7 + 专题报告
│   │   ├── G1_PREPARATION_REPORT.md      (从根目录移入)
│   │   ├── G2_RISK_PARITY_REPORT.md      (从根目录移入)
│   │   └── G25_DYNAMIC_POSITION_REPORT.md (从根目录移入)
│   │
│   ├── research-kb/             ← 研究知识库（保持现有）
│   │
│   ├── reports/                 ← 审计/盘点报告（从根目录移入）
│   │   ├── AUDIT_RESULTS.md
│   │   ├── BACKEND_FULL_AUDIT.md
│   │   ├── BACKEND_FUNCTIONALITY_AUDIT.md
│   │   ├── COMPREHENSIVE_AUDIT_REPORT.md
│   │   ├── DATA_QUALITY_AUDIT.md
│   │   ├── FACTOR_ASSET_INVENTORY.md
│   │   ├── FRONTEND_BACKEND_INTEGRATION_AUDIT.md
│   │   ├── FRONTEND_INVENTORY.md
│   │   ├── FACTOR_PROFILE_REPORT.md      (从docs/移入)
│   │   ├── NORTHBOUND_*_REPORT.md        (从docs/移入)
│   │   ├── ALPHA158_IMPORT_REPORT.md     (从docs/移入)
│   │   └── ARCHITECTURE_AUDIT_2026Q1.md  (从docs/移入)
│   │
│   └── archive/                 ← 历史归档（保持+补充）
│       ├── (现有23个文件)
│       ├── QUANTMIND_V2_DESIGN_V5.md     (从docs/移入，旧总设计)
│       ├── DEVELOPMENT_BLUEPRINT.md      (从docs/移入，与IMPL_MASTER重叠)
│       ├── PHASE_1_PLAN.md               (从根目录移入)
│       └── PROJECT_RESTRUCTURE_PLAN.md   (本文件完成后归档)
│
├── scripts/                     ← 13个生产脚本（已清理）
│   ├── archive/                 ← 131+孤儿脚本+5个register_*.ps1
│   └── research/                ← 8个活跃研究脚本
│
├── output/                      ← 新建：回测输出（不进git）
│   └── (MDD_LAYERS_OUTPUT.txt等从根目录移入)
│
├── backend/                     ← 保持现有
├── frontend/                    ← 保持现有
├── cache/                       ← 保持现有
├── config/                      ← 保持现有
└── logs/                        ← 保持现有
```

---

## 3. 具体迁移清单

### A. 根目录 → docs/reports/（8个审计报告）
- AUDIT_RESULTS.md
- BACKEND_FULL_AUDIT.md
- BACKEND_FUNCTIONALITY_AUDIT.md
- COMPREHENSIVE_AUDIT_REPORT.md
- DATA_QUALITY_AUDIT.md
- FACTOR_ASSET_INVENTORY.md
- FRONTEND_BACKEND_INTEGRATION_AUDIT.md
- FRONTEND_INVENTORY.md

### B. 根目录 → docs/research/（3个研究报告）
- G1_PREPARATION_REPORT.md
- G2_RISK_PARITY_REPORT.md
- G25_DYNAMIC_POSITION_REPORT.md

### C. 根目录 → output/（9个回测输出）
- MDD_LAYERS_OUTPUT.txt (5.6MB)
- MDD_SUPPLEMENT_OUTPUT.txt (2.7MB)
- PMS_A_BASELINE.txt
- PMS_G1_TIERED.txt
- PMS_G2_CLOSE.txt
- P0_ATR_OUTPUT.txt
- P0_FACTORS_OUTPUT.txt
- P0_GAP_OUTPUT.txt
- P0_IVOL_OUTPUT.txt

### D. 根目录 → 删除
- compass_artifact_wf-*.md（临时artifact）

### E. 根目录 → docs/archive/
- PHASE_1_PLAN.md

### F. docs/ → docs/reports/（5个报告类文档）
- FACTOR_PROFILE_REPORT.md
- NORTHBOUND_MARKET_FACTORS_REPORT.md
- NORTHBOUND_MODIFIER_REPORT.md
- NORTHBOUND_RANKING_FACTORS_REPORT.md
- ALPHA158_IMPORT_REPORT.md
- ARCHITECTURE_AUDIT_2026Q1.md

### G. docs/ → docs/archive/（2个过期文档）
- QUANTMIND_V2_DESIGN_V5.md（旧总设计，被ROADMAP_V3替代）
- DEVELOPMENT_BLUEPRINT.md（与IMPLEMENTATION_MASTER重叠）

### H. .gitignore追加
- output/（回测输出不进git）
- *.tar.gz（备份文件不进git）

---

## 4. CLAUDE.md数字修正

| 位置 | 当前值 | 修正为 |
|------|--------|--------|
| 因子池DEPRECATED | 8 | 5 (momentum_5/momentum_10/momentum_60/volatility_60/turnover_std_20) |
| 因子池FULL | 14 | 移除此行（FULL池无明确定义，与PASS状态混淆） |
| 因子池RESERVE | 1 vwap_bias | 改为"PASS候选 30" |
| DDL注释 | "62张表" | "45张表(DDL定义) + 17张动态建表(shadow_portfolio等) = DB实际62张" |
| BH-FDR M值 | M=202 | M=69（FACTOR_TEST_REGISTRY.md实际值） |
| Skills数 | 6个 | 7个 |

---

## 5. .claude/配置修正

| 文件 | 修正内容 |
|------|---------|
| `_charter_context.md:22` | `TEAM_CHARTER_V3.3.md` → `docs/archive/TEAM_CHARTER_V3.3.md` |
| `risk-guardian.md:13` | `DEV_NOTIFICATIONS.md` → `docs/archive/DEV_NOTIFICATIONS.md` |
| `iron_law_enforce.py` | 铁律编号注释对齐_charter_context |

---

## 6. 防止再次混乱的规则（写入CLAUDE.md）

### 规则1: 文件归属制度
- 根目录只允许: CLAUDE.md / SYSTEM_RUNBOOK.md / PROGRESS.md / LESSONS_LEARNED.md / FACTOR_TEST_REGISTRY.md / pyproject.toml / .gitignore
- 新的审计报告 → docs/reports/
- 新的研究报告 → docs/research/
- 回测输出 → output/（不进git）
- 临时文件用完即删

### 规则2: 文档引用完整性
- 引用其他文件必须用完整路径
- 归档文件后，grep全项目更新引用
- 每个Sprint结束检查: `grep -r "TEAM_CHARTER\|DESIGN_V5" --include="*.md" --include="*.py"`

### 规则3: 数字同步制度
- CLAUDE.md中的统计数字（表数/因子数/测试数）每次变更后同步
- 不确定的数字标注"约"或"截至YYYY-MM-DD"
- 因子池状态以FACTOR_TEST_REGISTRY.md为唯一真相

### 规则4: 记忆文件维护
- 每个session结束前审查：记忆是否引用了过期的文件/概念
- project类记忆标注日期，超过14天的标记为"需验证"
- 每月做一次记忆文件全量审计
