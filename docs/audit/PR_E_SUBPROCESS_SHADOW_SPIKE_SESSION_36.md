# PR-E SUBPROCESS_SHADOW Spike — `backend/platform/` stdlib shadow 修复方案分析

**作者**: Session 36 (2026-04-25 19:30, 周六超产 spike)
**关联**: docs/audit/PYTEST_BASELINE_DRIFT_SESSION_35_36.md §3.5 SUBPROCESS_SHADOW (3 fail)
**状态**: 🟡 Spike 完成 — 推荐 **Option 1 (全量重命名)** for Session 37+, 本 session 不实施

---

## 1. 问题回顾

3 pytest fail 来自跨进程 stdlib `platform` 被 `backend/platform/` shadow:

```
File "D:\quantmind-v2\backend\engines\mining\__init__.py" line 16, in <module>
  from .ast_dedup import ASTDeduplicator
File "D:\quantmind-v2\backend\engines\mining\ast_dedup.py" line 20, in <module>
  import pandas as pd
File "...numpy/_utils_impl.py" line 3, in <module>
  import platform   # ← 找到 backend/platform/__init__.py 而非 stdlib
File "D:\quantmind-v2\backend\platform\__init__.py" line 33, in <module>
  from .backtest.interface import (
... → AttributeError: partially initialized module 'pandas' (circular)
```

**生产影响**:
- ✅ PT 信号生成路径不触 (PT 不调 `multiprocessing.Process`)
- 🟡 GP weekly mining (Sun 22:00 Beat) `FactorSandbox.execute_safely()` 100% silent fail
- 测试 fail: test_mining_engine, test_mining_engines (3 total)

## 2. 三选一方案对比

### Option 1: 全量重命名 `backend/platform/` → `backend/qm_platform/`

**优点**:
- 永久修复 — 清除 stdlib shadow 根因
- 零运行时分支逻辑 — 直接消除潜在 bug 类
- 跨进程 + 进程内一致

**缺点**:
- **Blast radius: 82 Python 文件** import `backend.platform`
- 1 个边缘 case: `backend/tests/smoke/test_mvp_3_2_batch_1_live.py` 用 `from platform.` (相对导入, 应纠正为 `from backend.platform.`)
- 还需更新: `pyproject.toml` 包路径 / `.venv/Lib/site-packages/quantmind.pth` (.pth 文件指向 backend, 重命名 sub-package 不影响 .pth 但需验证)
- Migration risk: 漏改某处 → ImportError

**工作量估算**: 2-4 hours mechanical sed + 手动 review + pytest 全跑验证

### Option 2: 子进程 spawn-target 隔离 (sandbox refactor)

**思路**: 把 `_subprocess_worker` 移出 `backend.engines.mining.factor_sandbox`, 放到无 module-level pandas import 的 isolated 文件 (e.g., `_qm_sandbox_worker.py` at project root).

**问题**:
- multiprocessing.spawn 必再 import worker 函数所在模块 — 即使移到 isolated 文件, 该文件本身也得在 sys.path
- worker 内部 `import pandas` 仍会触发 numpy → `import platform` → shadow (因为 backend/ 仍在 sys.path 通过 .pth 文件)
- 唯一逃避: `multiprocessing.set_executable(...)` 用 venv Python 但去掉 .pth — 需要 maintain 第二个 venv

**结论**: ❌ **Option 2 不可行** — 子进程必须 backend 在 sys.path 才能跑 mining engine, 但只要在 sys.path, `import platform` 必中 shadow

### Option 3: 暂不修复 + 接受 silent fail

**理由**:
- GP weekly mining 当前不影响 PT 生产
- Phase 3D ML synthesis NO-GO 后 GP 价值不明
- Sunday 22:00 silent fail 产生 forensic 证据, 反推 Option 1 紧迫性

**缺点**:
- pytest baseline 永留 3 fail
- 未来若 GP / 任何 multiprocessing-based 模块需要恢复 → 必须修

## 3. 推荐 (Session 37+ 决策)

🎯 **推荐 Option 1 (全量重命名)** for Session 37+:

1. **Spike 阶段**: 已完成 (本文档)
2. **POC 阶段**: 创建 git worktree, 跑 sed 全量替换:
   ```bash
   git worktree add .qm-platform-rename
   cd .qm-platform-rename
   git mv backend/platform backend/qm_platform
   grep -rln "backend\.platform" --include="*.py" | xargs sed -i 's/backend\.platform/backend.qm_platform/g'
   grep -rln "from \.platform" backend --include="*.py" | xargs sed -i 's/from \.platform/from .qm_platform/g'
   pytest backend/tests/ --tb=line | tail -20  # 验证
   ```
3. **PR 阶段**: 如果 POC pytest 通过 (新 baseline ≤ 5 fail), 提交 PR-E1 with 完整 diff
4. **Reviewer 阶段**: 至少 2 reviewer (code + python), 关注:
   - import 路径 100% 覆盖 (无残留 `backend.platform` 字符串)
   - .pth 文件 / pyproject.toml 包路径配置
   - worktree 测试 + 主 repo regression 测试
5. **Merge + 监控阶段**: GP weekly Sun 22:00 应改产生真 mined factor (而非 silent fail)

**预期工作量**: 2-4 hours (含 reviewer + fix iteration), 1 PR.

## 4. 不在本 session 做的理由

- 本 session 已交付 7 PR (Session 35+36 累计), 边际效用递减
- Option 1 需要相对独立时段 + 高度集中 (82 文件 mechanical edit + 全量 pytest 验证), 适合 Session 37 早晨清醒时做
- 风险管理: 周末改大量 import 路径若引入 regression, Monday 09:00 真生产前发现已晚

## 5. 后续 verification 路径

Session 37+ 完成 PR-E 后, 验证清单:

- [ ] pytest 重跑: 期望 8 fail → ~5 fail (-3 SUBPROCESS_SHADOW)
- [ ] GP weekly mining (Sun 22:00) 首跑实测产生 > 0 mined factor
- [ ] LL-070 跨进程变体闭环 (现 LL-070 仅修了 `sys.path.insert` 模式, 未修 package shadow 根因)
- [ ] CLAUDE.md 铁律 10b 例外条款更新 (本是 LL-070 衍生)

## 6. 关联

- **LL-070** (Session 32): backend/platform shadow stdlib via `sys.path.insert(0, BACKEND_DIR)` — 当前 LL 仅 cover scripts 单进程路径, 未 cover 跨 multiprocessing
- **候选铁律 45** (LL-070 沿伸): "multiprocessing 子进程 sys.path 隔离防 shadow" — 本 spike 实证 Option 2 不可行 → 该候选铁律应改为 "namespace 命名禁与 stdlib 包冲突" 或 "Python package 命名规范"
- **Audit §3.5 SUBPROCESS_SHADOW**: 3 fail 待 Option 1 修
- **Phase 3D ML CLOSED**: 不影响 PT 决策, 但若 Phase 3F+ AI evolution 需要重启 GP, Option 1 必先于 GP 恢复

## 7. 关闭条件

本 spike 报告完成即可关闭. Option 1 实施 = Session 37+ 独立 PR-E1.
