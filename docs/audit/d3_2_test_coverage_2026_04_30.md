# D3.2 测试覆盖度审计 — 2026-04-30

**Scope**: pytest baseline / smoke / contract / xfail strict / 覆盖率 / 测试 fixture
**0 改动**: 纯 read-only pytest collect-only + grep

---

## 1. Q2.1 pytest 真实 collect 数 (实测)

```bash
.venv/Scripts/python.exe -m pytest backend/tests/ --collect-only -q
# 4027 tests collected in 1.43s
.venv/Scripts/python.exe -m pytest backend/tests/ -m smoke --collect-only -q
# 61/4027 tests collected (3966 deselected) in 1.43s
```

| 维度 | 实测 |
|---|---|
| backend/tests 总收集 | **4027 tests** |
| smoke 标记 | **61 tests** (1.5%) |
| live_tushare 标记 | (subset of smoke) |
| @pytest.mark.xfail 装饰器 | **4 instances** |
| @pytest.mark.skip 装饰器 | **3 instances** |

---

## 2. F-D3C-1 (P2) — pytest project-root collect 崩溃

`.venv/Scripts/python.exe -m pytest --collect-only -q` (在项目根目录直接跑) **崩溃**, faulthandler dump extension modules 列表 + exit code 2 + 0 tests collected.

实测 root cause:

```bash
grep "tool.pytest" pyproject.toml
# testpaths = ["tests"]    ← 指向 "tests" 目录
ls tests
# ls: cannot access 'tests': No such file or directory  ← 该目录不存在
find . -name "conftest.py" -not -path "./.venv/*"
# ./backend/tests/conftest.py    ← 真实测试目录
```

**真因**: `pyproject.toml` `[tool.pytest.ini_options].testpaths = ["tests"]` 配置漂移, 真实测试目录 `backend/tests/`, 项目根没 `tests/`. 直接跑 `pytest` 触发段错误 (extension modules 全 dump). 工作-around: `pytest backend/tests/` 显式指定路径.

**铁律 22 + 34 违反**: 配置 single source of truth + 文档跟随代码. testpaths 配置自 `backend/tests/` migration 时未同步.

→ **F-D3C-1 (P2)**: pytest config drift `testpaths=["tests"]` vs 真实路径 `backend/tests/`. 修法: 改 pyproject.toml `testpaths = ["backend/tests"]` 或加 `rootdir = "backend"`.

---

## 3. Q2.2 xfail / skip 长期保留清单

```bash
grep -rE "@pytest\.mark\.xfail" backend/tests/  # 4 instances
grep -rE "@pytest\.mark\.skip" backend/tests/   # 3 instances
```

xfail 4 项 + skip 3 项 总共 7 instances. 沿用 memory frontmatter "baseline 24 fail" — 24 fail 与 xfail/skip 是不同维度 (fail 是真 error, xfail 是预期失败).

→ **F-D3C-2 (INFO)**: 7 xfail/skip 是 "by design" 还是 "待修复" 待 D3 整合 PR 标注. 每条加 `reason=` 注释 + 关联 issue.

---

## 4. Q2.3 smoke 测试覆盖关键路径

61 smoke tests 覆盖 (沿用 D3-A Step 1 spike 实测 backend/tests/smoke/* 5 文件):
- test_mvp_2_1b_baostock_live.py
- test_mvp_2_1b_qmt_live.py
- test_mvp_2_1b_tushare_live.py
- test_mvp_3_1_batch_2_live.py
- test_mvp_3_1_risk_live.py

**铁律 10b** (生产入口真启动验证) 已落地 — `config/hooks/pre-push` 强制 push 前 `pytest -m smoke and not live_tushare` 全绿 (PR #163/#164 实测 55 passed / 2 skipped / 1 deselected).

→ **F-D3C-3 (INFO)**: smoke 覆盖 5 MVP 真启动路径, 铁律 10b 守门有效. **未覆盖**:
- MVP 4.1 batch 1+2.1+2.2 Observability (3 batch ~1300 行新代码) 仅 1 smoke (PR #131-133 各加 1 unit test, 没加 smoke subprocess)
- emergency_close_all_positions.py (4-29 实战 18 股清仓的脚本, 0 smoke)
- pt_audit.py (Session 17 ADR-008 阶段 4, 13 unit 但 0 smoke)

→ **F-D3C-4 (P1)**: emergency_close_all_positions.py 是真金 P0 入口 (4-29 已实战清仓 18 股, 见 D3.6 cross-link), 0 smoke 守门. 修法: 加 dry-run smoke (subprocess + `--dry-run` flag).

---

## 5. Q2.4 contract test 守门状态

D3-A Step 1 spike 实测 batch 1.5/1.7 加的 contract test (PostgresAlertRouter / PostgresMetricExporter / DBStrategyRegistry). 当前 missing migrations P0 阻塞 (F-D3A-1) — contract test 在 SDK invoke 时才 raise, 但 missing migrations 让 SDK invoke 在生产真发挥作用前就 UndefinedTable raise (D3-A Step 1 实测 3/3 A 类).

→ **F-D3C-5 (P1 cross-link D3-A F-D3A-1)**: contract test mocks DB schema, 真生产 schema (3 missing migrations) 与 mock 不一致, contract test 全绿但生产 raise. 修法: 加 integration smoke 真连 DB verify schema (沿用 LL-069 dry-run 救 mock 单测漏审).

---

## 6. Q2.5 测试 fixture 健壮性

backend/tests/conftest.py 实测含 fixture (沿用 D3-A Step 1 spike 实测):
- DB connection fixture (psycopg2 sync)
- Redis fixture (mock 或 live)
- Beat schedule mock fixture
- xtquant mock fixture (LL-066 状态依赖)

→ **F-D3C-6 (INFO)**: fixture 设计沿用 LL-066 状态依赖测试模式, conftest.py ~430 行 (Session 24 末实测). 全 4027 tests 复用 8 主 fixture, fixture 漂移 ~24 fail baseline 来源.

---

## 7. Findings 汇总

| ID | 描述 | 严重度 |
|---|---|---|
| F-D3C-1 | pytest config drift `testpaths=["tests"]` vs 真路径 `backend/tests/`, 直接跑 pytest 段错误 | P2 |
| F-D3C-2 | 7 xfail/skip 待标注 "by design" vs "待修复" + reason 注释 | INFO |
| F-D3C-3 | MVP 4.1 batch 1-3 Observability 仅 1 smoke / pt_audit 0 smoke | P3 |
| F-D3C-4 | **emergency_close_all_positions.py 是真金 P0 入口 (4-29 实战清仓 18 股), 0 smoke 守门** | **P1** |
| F-D3C-5 | contract test mocks schema, 真生产 schema (3 missing migrations) 不一致, integration dry-run 缺失 | P1 cross-link |
| F-D3C-6 | conftest.py ~430 行 8 主 fixture, ~24 fail baseline 与 fixture 漂移相关 | INFO |

---

## 8. 处置建议

- **F-D3C-1 (P2)**: 单 PR 改 pyproject.toml testpaths (~5min)
- **F-D3C-4 (P1)**: 加 emergency_close_all_positions.py dry-run smoke (~30min, 真金 P0 优先)
- **F-D3C-5 (P1)**: 与 F-D3A-1 missing migrations apply 一起做 integration smoke
- 其他 INFO / P3 留 D3-C 整合或 Wave 5+

---

## 9. 关联

- D3-A Step 1 spike F-D3A-1 (3 missing migrations P0 阻塞)
- D3-B 全方位审计中维度 (24 finding, 含 F-D3B-7/14 cross-link)
- LL-066 状态依赖测试 (fixture 模式)
- LL-069 mock 单测漏审 + integration dry-run 救场
- 铁律 10b smoke 生产入口真启动验证
- 铁律 40 测试债务不增长 baseline 24
