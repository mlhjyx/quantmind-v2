# 现状快照 — 配置 deep (类 4 deep, sustained snapshot/04+05+06)

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 4 WI 3 / snapshot/04
**Date**: 2026-05-01
**Type**: 描述性 + 实测真值 deep (sustained snapshot/04+05+06 §1.1 + §1.3)

---

## §1 .env 真清单 deep (CC 5-01 实测)

实测 backend/.env (20 keys / 37 lines, snapshot/01 §1 sustained):

```
DATABASE_URL=postgresql://...
REDIS_URL=redis://...
TUSHARE_TOKEN=<truncated>
DEEPSEEK_API_KEY=<truncated>
ADMIN_TOKEN=<truncated>
QMT_PATH=E:/国金QMT交易端模拟
QMT_ACCOUNT_ID=81001102
QMT_ALWAYS_CONNECT=true
QMT_EXE_PATH=E:/国金QMT交易端模拟/bin.x64/XtMiniQmt.exe
EXECUTION_MODE=paper
LOG_LEVEL=INFO
LOG_MAX_FILES=10
PAPER_STRATEGY_ID=28fc37e5-2d32-4ada-92e0-41c11a5103d0
PAPER_INITIAL_CAPITAL=1000000
PT_TOP_N=20
PT_INDUSTRY_CAP=1.0
PT_SIZE_NEUTRAL_BETA=0.50
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=<truncated>
DINGTALK_SECRET=
DINGTALK_KEYWORD=xin
```

**注**: LIVE_TRADING_DISABLED 0 in .env, 默认 True (config.py:44, sustained E5).

---

## §2 配置 真 enforce verify (sustained snapshot/04+05+06 §1.3)

实测 sprint period sustained sustained:
- config_guard 启动硬 raise (铁律 34 sustained sustained sustained)
- F-D78-108 P2 候选 sustained: config_guard 真启动 raise 历史 0 sustained
- 候选 finding sustained sustained

候选 finding:
- F-D78-174 [P2] .env 关键字段 (PAPER_STRATEGY_ID / EXECUTION_MODE / PT_TOP_N / etc) 真 调用方 grep 0 sustained sustained sustained 度量, 候选 死字段 detection candidate

---

## §3 configs/*.yaml 真清单

实测 sprint period sustained sustained:
- configs/pt_live.yaml (sustained PT 配置 SSOT, 沿用 铁律 15 YAML 驱动 sustained sustained sustained)
- configs/backtest_5yr.yaml (sustained baseline)
- configs/backtest_12yr.yaml (sustained baseline)

候选 finding:
- F-D78-175 [P3] configs/*.yaml 真清单 deep + 字段 + 调用方 + 死字段 candidate 0 sustained sustained 度量, 沿用 F-D78-107 sustained sustained

---

## §4 真金保护双锁 sustained verify (sustained E5 + security/01)

实测 sprint period sustained sustained:
- 锁 1: LIVE_TRADING_DISABLED=True (config.py:44 默认, .env 0 override) ✅
- 锁 2: EXECUTION_MODE=paper (.env sustained) ✅
- DingTalk: secret 空 (1 锁 keyword sustained, F-D78-3)

---

## §5 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-174 | P2 | .env 关键字段真调用方 grep 0 sustained 度量, 死字段 detection candidate |
| F-D78-175 | P3 | configs/*.yaml 真清单 deep 0 sustained 度量, 沿用 F-D78-107 sustained |

---

**文档结束**.
