# Code Review — Engine 层 铁律 31 真 violation cluster

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 4 / code/02
**Date**: 2026-05-01
**Type**: 评判性 + 真测 推翻 sprint period sustained "Phase C F31 全部完成" 假设

---

## §1 真测 (CC 5-01 实测)

实测命令:
```bash
grep -rlE "import psycopg|psycopg2|conn\.cursor|engine\.execute" backend/engines/
```

**真值** (engine 层含 DB import 的文件):
1. `base_strategy.py`
2. `beta_hedge.py`
3. `config_guard.py`
4. `datafeed.py`
5. `factor_analyzer.py`
6. `factor_engine/__init__.py`
7. `factor_gate.py`
8. `factor_profile.py`
9. `factor_profiler.py`

**真值**: **9 文件含 psycopg/conn.cursor/engine.execute import 在 engine 层**

---

## §2 🔴 sprint period sustained sustained "Phase C F31 全部完成" 假设 推翻

### 2.1 sprint period sustained 沉淀

sprint state Session 16a (2026-04-16) 沉淀:
> Phase C F31 全部完成 (C0+C1+C2+C3): factor_engine.py 2049→416 行, 新 package + factor_repository + factor_compute_service, F86 factor_engine 条目关闭 (3→2), 25 调用方零改动, 铁律 31 落地

**真测真值**:
- factor_engine.py 重构 ✅ (factor_engine/ package + repository + service)
- **但 9 engine 层文件仍 import DB** = 铁律 31 真 violation cluster sustained

### 2.2 真测 verify

铁律 31 sustained: "Engine 层纯计算 — backend/engines/** 不读写 DB/HTTP/Redis (Phase C 落地)"

**真 violation 9 文件**:
- `base_strategy.py` (策略基类, 沿用 sprint period sustained sustained 设计 candidate)
- `beta_hedge.py` (beta 对冲)
- `config_guard.py` ✅ (config_guard 是启动校验 sustained, candidate 铁律 31 例外)
- `datafeed.py` (数据源 — candidate 铁律 31 例外)
- `factor_analyzer.py`
- `factor_engine/__init__.py` ⚠️ (Phase C 重构后 sustained 仍 import DB, candidate 重构残留)
- `factor_gate.py`
- `factor_profile.py`
- `factor_profiler.py`

**真违反 vs 真例外**:
- 候选真违反: factor_analyzer / factor_gate / factor_profile / factor_profiler / factor_engine/__init__.py / base_strategy / beta_hedge (~7 文件)
- 候选铁律 31 例外 (sprint period sustained sustained 默认): config_guard (启动校验) / datafeed (数据源) (~2 文件)

**🔴 finding**:
- **F-D78-150 [P2]** engine 层 9 文件含 DB import — 铁律 31 真 violation cluster sustained. sprint period sustained sustained "Phase C F31 全部完成" 假设 部分推翻 — factor_engine.py 重构 ✅ 但其他 7+ engine 层文件 sustained DB import 未清理. F-D78-67 候选验证

---

## §3 候选解决路径 (本审查 0 决议)

(沿用 EXECUTIVE_SUMMARY §4 战略候选 仅候选 0 决议)
- ✅ 维持: config_guard / datafeed (铁律 31 例外 sustained sustained sustained sustained)
- ⚠️ 修复: factor_analyzer / factor_gate / factor_profile / factor_profiler / factor_engine/__init__.py / base_strategy / beta_hedge (重构 → repository pattern, 沿用 Phase C factor_engine 路径)

---

## §4 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| **F-D78-150** | **P2** | engine 层 9 文件含 DB import — 铁律 31 真 violation cluster, sprint period sustained "Phase C F31 全部完成" 部分推翻 (factor_engine.py 重构 ✅ but 7+ engine 文件 sustained DB import 未清理) |

---

**文档结束**.
