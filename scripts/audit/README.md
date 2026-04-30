# scripts/audit/ — Read-only Audit Scripts

**用途**: 项目治理 / 审计 / verifier 脚本集合. 全部 read-only, 0 mutating SQL, 0 业务代码改动.

**铁律映射**:
- 铁律 X1 (Claude 边界): 审计脚本仅诊断, 不修复
- 铁律 25 (改什么读什么): 验证脚本基于实测 schema / 文件状态, 不假设
- 铁律 33 (fail-loud): 验证失败 exit 1 + stderr finding, 非 silent

**禁止 (跨脚本硬性)**:
- 任何 mutating SQL (DELETE / UPDATE / INSERT / TRUNCATE / CREATE / ALTER / DROP)
- alembic upgrade / downgrade
- xtquant.trader.order_stock / sell / buy
- 改 .env / configs/ / 业务代码

---

## 现有脚本 (Pre T0-19)

| 脚本 | 用途 | 退出码语义 |
|---|---|---|
| `audit_orphan_factors.py` | 检查 factor_registry 中无对应 factor_values 的孤儿因子 | 0=clean, 1=orphans found |
| `check_insert_bypass.py` | 检查 production code 是否绕 DataPipeline 直 INSERT (铁律 17) | 0=no bypass, 1=bypass detected |
| `phase_c_freeze_baseline.py` | Phase C factor_engine 拆分前 baseline 冻结 | 0=success |
| `phase_c_verify_split.py` | Phase C factor_engine 拆分后 verify | 0=match, 1=drift |
| `scan_future_dates.py` | 扫 DB 表是否含未来日期 (PIT 违反) | 0=clean, 1=future dates found |

---

## T0-19 Phase 1 新增 (PR #<待 merge>)

### `check_alembic_sync.py` — F-D3A-1 missing migrations verifier

**触发时点 (event-driven)**:
- 任何 `backend/migrations/*.sql` 加 / apply 后立刻跑
- 批 2 P0 修 PR (apply alert_dedup / platform_metrics / strategy_evaluations) merged 后立刻跑
- PT 重启 gate prerequisite check 时跑

**跑法**:
```bash
.venv/Scripts/python.exe scripts/audit/check_alembic_sync.py
echo $?  # 0=全 applied, 1=missing
```

**期望 (批 2 P0 修后)**:
```
✅ PASS — 全部 3 expected tables 已 applied.
   F-D3A-1 P0 阻塞已修.
```

**当前 (Phase 1 时点, 未修)**:
```
❌ FAIL — 3 table(s) missing: alert_dedup, platform_metrics, strategy_evaluations
   F-D3A-1 P0 阻塞**仍未修**, PT 重启 gate 阻塞.
```

---

### `check_t0_19_implementation.py` — T0-19 Phase 2 修法落地 verifier

**触发时点 (event-driven)**:
- T0-19 Phase 2 PR merged 后立刻跑
- emergency_close_all_positions.py 真跑前 (Phase 2 self-test)
- 批 2 P0 修启动前 / 完结后跑

**跑法**:
```bash
.venv/Scripts/python.exe scripts/audit/check_t0_19_implementation.py
echo $?  # 0=5/5 PASS, 1=1+ FAIL
```

**5 项检查**:
1. LIVE_TRADING_DISABLED 双锁守门 (config.py default True)
2. backend/app/services/t0_19_audit.py + 4 关键函数
3. backend/app/exceptions.py 3 exception 类
4. emergency_close_all_positions.py L306 后 hook 插入
5. dry-run subprocess path (LIVE_TRADING_DISABLED=true 守门)

**期望 (Phase 2 落地后)**:
```
✅ PASS — 全部 5/5 checks ✓
T0-19 修法 Phase 2 落地完整.
```

**当前 (Phase 1 时点, Phase 2 未启动)**:
```
❌ FAIL — 4/5 check(s) failed: ...
T0-19 修法 Phase 2 需补.
```

(check 1 LIVE_TRADING_DISABLED 已 PASS, check 2-5 等 Phase 2 落地)

---

### `check_pt_restart_gate.py` — SHUTDOWN_NOTICE §9 v3 7-项 prerequisite verifier

**触发时点 (event-driven)**:
- 批 2 P0 修启动前 (baseline)
- 批 2 P0 修完结后 (verify)
- PT 重启决议时 (final gate check)
- 任何 SHUTDOWN_NOTICE.md 修订后

**跑法**:
```bash
.venv/Scripts/python.exe scripts/audit/check_pt_restart_gate.py
echo $?  # 0=GATE CLEARED, 1=GATE BLOCKED
```

**7 项检查** (SHUTDOWN_NOTICE_2026_04_30 §9 v3):
1. T0-15 LL-081 v2 (QMT 断连 / fallback cover)
2. T0-16 qmt_data_service fail-loud
3. T0-18 铁律 X9 (schedule 注释后必 restart)
4. T0-19 emergency_close audit hook
5. F-D3A-1 3 missing migrations apply
6. DB 4-28 19 股 stale snapshot 清理
7. cb_state live reset ¥993,520 (实测真账户)

**注**: 另 2 项 (paper-mode 5d dry-run + .env paper→live 显式授权) 是**手工 user 决议项**, 不在本脚本 scope.

**期望 (批 2 + DB 清理 + cb_state reset 全完成后)**:
```
✅ GATE CLEARED — 全部 7/7 prerequisites ✓
PT 重启可决议 (user 仍需手工: paper-mode 5d dry-run + .env paper→live 授权).
```

**当前 (Phase 1 时点, 全未修)**:
```
❌ GATE BLOCKED — 6/7 prerequisite(s) failed:
   - T0-15 LL-081 v2 (QMT 断连/fallback cover)
   - T0-16 qmt_data_service fail-loud
   - ...
PT 重启**禁止** — user 必先修上列项目.
```

---

## 跨脚本通用规范

### 退出码协议

| 退出码 | 语义 | 适用 |
|---|---|---|
| 0 | 验证通过 | 全部 check ✓ |
| 1 | 验证失败 | 1+ check ✗ (业务层失败) |
| 2 | 脚本自身错 | DB 连接 / 配置 / FATAL exception |

### Output 格式

- stdout: human-readable 表格 + 实测证据 + 修复指引
- stderr: 仅 FATAL exception (退出码 2)
- 长 output: 不截断 (audit chain 完整性)

### 安全守门

- 全部脚本头有 docstring 标 "禁止: 任何 mutating SQL" 等
- 关键脚本 (check_t0_19_implementation) 加 `_check_live_trading_disabled` 双锁
- 任何脚本若需 DB 连接, 走 PGPASSWORD 环境变量, 不 hardcode 密码

### CI 集成 (Wave 5+ 候选)

未来 (批 2 完结后) 加 `pre-commit` hook 跑 `check_alembic_sync.py` (~1s), 防 missing migrations 重演.

---

## 关联

- T0-19 Phase 1 design: `docs/audit/STATUS_REPORT_2026_04_30_T0_19_phase_1_design.md`
- D3-A Step 1 spike (F-D3A-1 实测): `docs/audit/STATUS_REPORT_2026_04_30_D3_A_step1_step2_spike.md`
- D3-C STATUS_REPORT (F-D3C-13 实测): `docs/audit/STATUS_REPORT_2026_04_30_D3_C.md`
- SHUTDOWN_NOTICE_2026_04_30 §9 v3 prerequisite list: `docs/audit/SHUTDOWN_NOTICE_2026_04_30.md`
- LL #24 (CHECK constraint 必实测): `LESSONS_LEARNED.md`
