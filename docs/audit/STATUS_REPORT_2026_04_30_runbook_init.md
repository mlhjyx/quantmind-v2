# STATUS_REPORT — Runbook 治理基础设施落地

**Date**: 2026-04-30
**Branch**: chore/runbook-init
**Base**: main @ 3572881 (PR #152 治理债清理 batch 1.7 merged)
**Scope**: 1 PR 创建 `docs/runbook/cc_automation/` 目录 + INDEX + 撤 setx runbook + CLAUDE.md 引用 (内容文件 3 + STATUS_REPORT 1 = 4 文件改动)
**ETA**: 30-45 min (实际 ~30 min, 纯文档 PR)
**真金风险**: 0 (0 业务代码改 / 0 .env 改 / 0 服务重启)

---

## 1. 5 题决议

| # | 答 | 证据 |
|---|---|---|
| Q1 | ✅ `docs/runbook/` 不存在 | `ls docs/runbook` → `cannot access` |
| Q2 | ✅ CLAUDE.md 插入位置: L807 `---` 后 (新 `## CC 自动化操作` 章节) | grep ^## 章节列表 |
| Q3 | ⚠️ session compact 丢失原 runbook prompt → 基于 D2.3 实测重写 | docs/audit/STATUS_REPORT_2026_04_30_D2_3.md §3-5 完整覆盖 |
| Q4 | ✅ `NN_<scenario>_runbook.md` schema 锁定 | INDEX.md §"添加新 runbook" 含模板 |
| Q5 | ✅ 3 文件 scope | git diff stat 验证: 1 修改 + 2 新增 |

---

## 2. 改动清单

### 新建 2 文件

| 文件 | 行数 | 用途 |
|------|------|------|
| `docs/runbook/cc_automation/00_INDEX.md` | ~50 | 索引 + 用途说明 + 命名 schema + runbook 模板 7 字段 |
| `docs/runbook/cc_automation/01_setx_unwind_runbook.md` | ~150 | D2.3 临时 setx 撤回 runbook (8 段: 背景/真金 0 风险/前置/执行/验证/失败回滚/STATUS_REPORT/关联) |

### 修改 1 文件

| 文件 | 改动 |
|------|------|
| `CLAUDE.md` | L807 `---` 后插入新 `## CC 自动化操作` 章节 (10 行, 含触发模式 + 与 audit/adr/mvp 区分说明) |

### 主动发现

- ✅ docs/ 不存在 runbook/ 目录冲突
- ✅ CLAUDE.md L205 仅 1 处提 `SYSTEM_RUNBOOK §7.3` (历史孤儿引用, 文件已不存在), 不冲突
- ✅ 8 D2 audit docs untracked (上 session 残留, 不属本 PR scope, 不 git add)

---

## 3. INDEX 设计要点

`00_INDEX.md` 含:
1. **用途**: 区分 runbook (可重复触发) vs audit (一次性诊断) vs adr (架构决议) vs mvp (功能设计)
2. **当前 runbook 表**: # / 文件 / 触发场景 / 真金风险
3. **添加新 runbook 命名规则**: `NN_<scenario>_runbook.md`
4. **runbook 模板 7 字段**: 触发条件 / 真金 0 风险确认 / 前置检查 / 执行步骤 / 验证清单 / 失败回滚 / STATUS_REPORT 输出

未来扩展候选 (不本 PR 创建):
- `02_admin_token_rotation_runbook.md` — ADMIN_TOKEN 轮换
- `03_pt_live_cutover_runbook.md` — paper → live cutover (含 paper-mode 5d dry-run gate)
- `04_servy_full_restart_runbook.md` — Servy 4 服务全重启序列
- `05_db_namespace_repair_runbook.md` — execution_mode hardcoded 'paper' 修

---

## 4. setx_unwind runbook 设计要点

**触发条件**: 批 2 P3 startup_assertions.py 改用 settings.SKIP_NAMESPACE_ASSERT commit merged + FastAPI 重启验证 OK 后调用.

**真金 0 风险硬门** (4 项, 任一不满足 STOP):
1. LIVE_TRADING_DISABLED=True
2. EXECUTION_MODE=paper 或 live cutover 已 user 授权
3. 批 2 P3 commit 已 merged (grep startup_assertions settings)
4. settings.SKIP_NAMESPACE_ASSERT 真 attr (hasattr 验证)

**执行 5 步**:
1. 撤 Machine env (D2.3 留)
2. 撤 User env (D2.2 user 留)
3. Servy restart QuantMind-FastAPI
4. /health 200 + Servy Running 验证
5. admin gate 401/503 验证 (PR #152 + #155 等)

**验证 6 项硬门** (任一 fail → 失败回滚):
- Machine env SKIP=NULL
- User env SKIP=NULL
- FastAPI Running PID > 0
- /health 200
- admin gate 401 (no token)
- DB 行数不变 (cb_state / approval_queue 不污染)

**失败回滚 2 场景**:
- A: Step 4 FastAPI 不起 → 立即恢复 Machine env (D2.3 配置) + STOP 报 user
- B: /health OK 但 admin gate 异常 → 不回滚 setx (env 跟 admin gate 无关) + 直接报 user

---

## 5. CLAUDE.md 引用段设计要点

放在 L807 `---` 之后, `## 文件归属规则（防腐）` 之前 — 跟 "执行类资产" 聚合, 不混 "导航类索引".

引用段含 3 句话:
1. **集中存放位置**: `docs/runbook/cc_automation/` + INDEX.md 链接
2. **触发模式**: user 一句话 → CC 加载 runbook → 自主执行 → user 0 手工操作
3. **与其他 docs/ 子目录区分**: 强调 "可重复触发" 是 runbook 唯一特性

---

## 6. 硬门验证

| 硬门 | 结果 | 证据 |
|------|------|------|
| 改动 scope | ✅ 4 文件 (3 内容 + 1 STATUS_REPORT) | git diff stat: CLAUDE.md +10 / 3 新增 (含本 STATUS_REPORT) |
| ruff | ✅ N/A | 无 .py 改动 |
| pre-push smoke | (push 时验) | bash hook 强制 55 PASS (沿用上 PR) |
| 0 业务代码改 | ✅ | git diff main --stat 仅 CLAUDE.md 1 文件 + 2 新 docs |

---

## 7. PR merge 后

- main HEAD 更新 (PR merge commit hash)
- `docs/runbook/cc_automation/` 进 main, 跨 session 持久化
- 触发场景: 批 2 P3 完成 → user 一句话 "执行 runbook 01 撤 setx" → CC 加载 `01_setx_unwind_runbook.md` 自主执行

---

## 8. 关联

- **D2.2** ([STATUS_REPORT_2026_04_29_D2_2.md](STATUS_REPORT_2026_04_29_D2_2.md)) — Finding G startup_assertions 改用 settings (批 2 P3 修法源)
- **D2.3** ([STATUS_REPORT_2026_04_30_D2_3.md](STATUS_REPORT_2026_04_30_D2_3.md)) — Servy LocalSystem env scope 实测 + Finding K (本 runbook 撤回的临时操作来源)
- **PR #152** (治理债清理 batch 1.7) — base, 6 endpoints admin gate
- **铁律 22** (文档跟随代码) — runbook 是治理资产, 入 CLAUDE.md
- **铁律 24** (文档分层) — runbook/ 单独子目录, 不混 audit/adr/mvp

---

## 9. 用户接触

0 次 (沿用 LL-059 9 步闭环, 全 AI 自主). 仅 push / merge 时 GitHub API 网络可能有 EOF, 无声 retry.
