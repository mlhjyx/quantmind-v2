# Phase B M3 Handoff — F45 config_guard 扩展

> **状态**: M1+M2 完成, M3 待做
> **建立时间**: 2026-04-15 夜 (audit session 4 个 commit 后)
> **目的**: 让下一个 fresh session 无缝接管 M3, 无需重读本 session 上下文
> **接管 bootstrap**: 读本文档 + `docs/audit/AUDIT_MASTER_INDEX.md` 即可开工

---

## Session 状态快照

- **Git HEAD**: `7f54613 audit(b-m2): F75 full closure - regression_test --years 12`
- **Branch**: main
- **PT 状态**: 暂停中 (自 2026-04-10)
- **Sharpe 基线**: CORE3+dv_ttm WF OOS=0.8659 (不变)
- **Iron-law count**: 35 (1-30 原 + 31-35 工程基础设施类 S2b-session 新增)
- **Findings**: 54 total / 29 closed / 25 open
- **P0 剩余**: 4 条 (F16 / F31 / F45 / F63) — 原为 5 条, S2b 根治 F17/F51/F53/F60 四条, M1 关闭 F86, M2 关闭 F75

---

## 本 session 累计成果 (4 个 commit)

| # | Commit | 主题 | 闭环 findings |
|---|---|---|---|
| 1 | `dfcb473` | 铁律扩展 30→35 (工程基础设施类 31-35 + 扩展 8/22) | — (建立 5 条硬约束) |
| 2 | `e82eb36` | factor_onboarding 彻底重构 (async→sync + DataPipeline + ic_calculator) | F17 / F51 / F53 / F60 / F86 部分 |
| 3 | `0608879` | F86 pre-commit hook (full closure + baseline 机制) | F86 |
| 4 | `7f54613` | F75 regression 12yr 入口 + 意外发现 12yr drift 根因分析 | F75 |

---

## 待做: M3 F45 config_guard 扩展 (P0)

### 目标

扩展 `backend/engines/config_guard.py`, 使其在 PT 启动前检查以下参数的**三处对齐** (铁律 34):

| 参数 | `.env` key | `pt_live.yaml` key | Python 常量 key |
|---|---|---|---|
| SN_beta | `PT_SIZE_NEUTRAL_BETA` | `signal_composer.size_neutral_beta` (或类似, 以实际 YAML 为准) | `signal_engine.PAPER_TRADING_CONFIG['size_neutral_beta']` |
| top_n | `PT_TOP_N` | `portfolio.top_n` | `PAPER_TRADING_CONFIG['top_n']` |
| industry_cap | `PT_INDUSTRY_CAP` | `portfolio.industry_cap` | `PAPER_TRADING_CONFIG['industry_cap']` |
| factor_list | — (不在 .env) | `signal_composer.factors` 或 `factors` (list of dict) | `PAPER_TRADING_CONFIG['factors']` |
| rebalance_freq | `PT_REBALANCE_FREQ` 或类似 | `portfolio.rebalance_freq` | `PAPER_TRADING_CONFIG['rebalance_freq']` |

**硬要求 (铁律 34)**: 不一致 → **RAISE**, 不允许只报 warning. 违反此条等于铁律 34 没落地.

### 验收标准 (5 把尺子)

1. ✅ 扩展 `backend/engines/config_guard.py`, 实现 `check_config_alignment()` 函数 + `ConfigDriftError` 异常类
2. ✅ 集成到 PT 启动流程 (`scripts/run_paper_trading.py` 的 bootstrap 早期, 在 import 生产模块前)
3. ✅ 新建 `backend/tests/test_config_guard.py` 单元测试: mock 三个配置源, 故意让一个不一致, 验证 `check_config_alignment()` 抛 `ConfigDriftError` + 错误消息明确指出哪一项漂移
4. ✅ 集成到 `scripts/health_check.py` (若该脚本存在), 让日常体检也跑这一项
5. ✅ 5 把尺子全绿:
   - pytest test_config_guard (新建) → 全绿
   - pytest test_factor_onboarding (不回归) → 28/28 PASS
   - regression_test --years 5 → max_diff=0.0
   - pre-commit hook 通过 (无新 INSERT 违规)
   - 故意改坏 `.env` 里一个值, `python scripts/run_paper_trading.py` 应立即 RAISE + 明确错误

### 设计决策 (M3 开始前先定)

#### D1: factor_list 对齐策略

- `.env` 没有 factor_list (env var 不适合表达 list)
- `configs/pt_live.yaml` 有完整 factors 列表 + 方向
- `PAPER_TRADING_CONFIG` 应该**从 YAML 读, 不独立定义默认值**

**建议**: factor_list 的权威来源是 YAML. Python 常量运行时从 YAML 加载. `.env` 不参与此项对齐. config_guard 检查的是 "Python 常量和 YAML 是否一致" (YAML 是 truth source).

#### D2: 对齐检查发生在哪一层

- **Option A**: `config_guard.py` 独立函数, PT 启动时调用
- **Option B**: `app/config.py` pydantic settings 做类型层面强制 (但 YAML 不走 pydantic)
- **Option C**: 两层 — pydantic 管 .env 类型, config_guard 管跨源对齐

**建议**: Option A (独立函数) + 在 `health_check.py` 也调一次. 最小侵入, 快速落地.

#### D3: 回测是否也走 config_guard

- `run_backtest.py` 只从 YAML 读, 不从 .env 读, 所以不存在"漂移"
- **建议**: 只 PT 启动 + health_check 走; 回测豁免

#### D4: ConfigDriftError 设计

```python
class ConfigDriftError(RuntimeError):
    """铁律 34: 配置 single source of truth 违反."""
    def __init__(self, param: str, sources: dict[str, Any]):
        self.param = param
        self.sources = sources  # {".env": ..., "yaml": ..., "python": ...}
        msg = f"参数 '{param}' 在三个配置源中不一致: " + "; ".join(
            f"{k}={v!r}" for k, v in sources.items()
        )
        super().__init__(msg)
```

---

## 推荐的 Scout reading (依此顺序)

```
1. backend/engines/config_guard.py          # 当前实现, 看扩展点
2. configs/pt_live.yaml                      # YAML 配置结构 (SN_beta/top_n 的确切 key 路径)
3. grep PAPER_TRADING_CONFIG backend/        # Python 常量定义位置 + 读取位置
4. backend/app/config.py                     # pydantic settings (.env 入口)
5. scripts/run_paper_trading.py             # PT bootstrap 顺序, 找 config_guard 调用点
6. scripts/health_check.py                   # health_check 是否已有 config 相关检查
```

**不用读的** (避免 context 污染):
- factor_onboarding.py (S2b 已重构完成)
- ic_calculator.py
- DataPipeline / Contracts (M3 不涉及入库)

---

## 工作量预估

| 步骤 | 时间 |
|---|---|
| Scout 现有 config_guard.py + 4 个配置源 | ~20 min |
| 设计 + Plan 写给用户 (铁律 3: 范围外改动先报告) | ~15 min |
| 实现 `check_config_alignment()` + `ConfigDriftError` | ~40 min |
| 新建 test_config_guard.py + 5-8 个测试用例 | ~25 min |
| 集成到 run_paper_trading / health_check | ~15 min |
| 验证 5 把尺子 (pytest + regression + hook) | ~15 min |
| commit + 更新 CLAUDE.md F45 状态 + AUDIT_MASTER_INDEX | ~15 min |
| **总计** | **~2.5 小时** |

---

## 已知风险

1. **Config 加载顺序敏感**: config_guard 必须在 `.env` 加载后、Python 常量初始化时 or 之前运行. 如果顺序错, 会得到错误的参数值. **Mitigation**: 在 `run_paper_trading.py` 开头 `from app.config import settings` 之后立即 call config_guard, 保证 settings 已加载.

2. **Test fixture 隔离**: 测试 config_guard 需要 mock 三个配置源, 避免污染真实 `.env`. **Mitigation**: 用 `monkeypatch` + 临时 yaml 文件, 不写任何持久状态.

3. **12yr drift 的后续调查** (独立议题, 不在 M3 范围):
   - M2 发现 12yr Sharpe 从 0.5309 → 0.3594 (根因: cache/backtest/* 2026-04-15 15:20 重建覆盖了 Step 6-D 时代的快照)
   - **接受新 baseline** 0.3594 作为当前真相 (M2 已更新 CLAUDE.md + metrics_12yr.json)
   - 用户可能希望单独调查 "为什么下降这么多" — **建议另起 session**, 不在 M3 里做
   - 可疑路径: F66 NaN 清理是否涉及 CORE5 因子的 2014-2020 段 / build_backtest_cache.py 本次 rebuild 的细节日志

4. **铁律 34 的落地考验**: M3 是**铁律 34 的第一个实战实现**. 如果 config_guard 扩展不够严格 (比如漏检某个参数, 或把不一致降级成 warning), 未来 F45 类问题会再次复发. **Mitigation**: test case 必须覆盖"每一个参数单独不一致"的情形 (5 个参数 → 至少 5 个 fail test).

---

## 启动下一个 session 的 bootstrap 句子

复制下面这段发给新 session 即可接管:

```
继续 QuantMind V2 审计. 读 docs/audit/PHASE_B_M3_HANDOFF.md + docs/audit/AUDIT_MASTER_INDEX.md,
按 Phase B M3 handoff 执行 F45 config_guard 扩展 (铁律 34 第一个实战实现).

当前 git HEAD=7f54613. 本 session 已完成 M1+M2 (4 个 commit), 待做 M3.
不要重读 factor_onboarding 或 IC 路径代码 — S2b 已闭环. 只读 config_guard / pt_live.yaml /
signal_engine / config.py / run_paper_trading 这 5 个文件.

按 handoff §验收标准 执行 5 把尺子验证, commit 后评估是否进入 Phase C (F31 factor_engine 拆分).
```

---

## 附录: 相关铁律 (M3 落地时必须遵守)

- **铁律 34** (配置 single source of truth) — M3 是此铁律的第一个实战落地
- **铁律 22(d)** (数字类声明同步更新) — 新参数默认值变更时 CLAUDE.md 同步
- **铁律 26/27** (验证不可跳过 + 结论明确) — 5 把尺子必须全绿
- **铁律 33** (禁止 silent failure) — config_guard RAISE, 不允许 warning
- **铁律 3** (范围外改动先报告) — Scout 后先给用户 plan, 等 ACK 再动手
- **铁律 25** (不靠记忆靠代码) — 每一个配置源的 key 路径必须有代码证据

---

**本 hand-off 文档由 `7f54613` 之后的 audit session 编写**. 如果未来重构删除/重命名 config_guard.py, 本文档的引用必须在同一个 commit 里修复 (铁律 22(c)).
