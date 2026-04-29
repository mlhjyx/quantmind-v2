# CC Automation Runbook 索引

各场景的 CC 自动化操作指令存档. 触发时 user 一句话 → CC 加载对应 runbook → 自主执行 → user 0 手工操作.

## 用途

存放**可重复触发**的运维操作 prompt. 跟 `docs/audit/` (一次性诊断报告) / `docs/adr/` (架构决议) / `docs/mvp/` (功能设计) 区分.

适合放这里的内容:
- 撤回某项临时配置 (e.g. setx env / Servy override)
- 标准化的服务重启 / 状态检查序列
- 紧急止血操作 (PT 全清仓 / Beat schedule 全停 / 等)
- DB 命名空间修复 / cb_state 清理 / 等定型操作

不适合放这里的内容:
- 一次性诊断报告 → `docs/audit/`
- 架构决议 → `docs/adr/`
- MVP 设计 → `docs/mvp/`
- 代码逻辑文档 → `docs/DEV_*.md`

## 当前 runbook

| # | 文件 | 触发场景 | 真金风险 |
|---|------|---------|---------|
| 01 | [`01_setx_unwind_runbook.md`](01_setx_unwind_runbook.md) | 撤回 D2.3 临时 setx (Machine `SKIP_NAMESPACE_ASSERT=1`), 批 2 P3 startup_assertions 改用 settings 后调用 | 0 (paper mode + LIVE_TRADING_DISABLED=True) |

## 添加新 runbook

按命名 `NN_<scenario>_runbook.md` 加入. 同时更新本索引表 (新增行).

**命名规则**:
- `NN`: 2 位序号, 按时间顺序递增, 不复用
- `<scenario>`: snake_case, 简短描述触发场景
- 后缀必须是 `_runbook.md` (区分于 `_audit.md` / `_design.md`)

**runbook 模板必含字段**:
1. **触发条件** (何时调用 — 前置依赖)
2. **真金 0 风险确认** (LIVE_TRADING_DISABLED guard / paper mode / Beat 状态)
3. **前置检查清单** (实测命令 + 期望输出)
4. **执行步骤** (每步含命令 + 期望输出 + 失败回滚路径)
5. **验证清单** (每个 ok/fail 判定)
6. **失败回滚** (任意步骤失败如何还原)
7. **STATUS_REPORT 输出** (`docs/audit/STATUS_REPORT_<date>_<scenario>.md` 路径)
