# Code Review — Import graph 真测 backend/

**Audit ID**: SYSTEM_AUDIT_2026_05 / Phase 9 WI 4 / code/04
**Date**: 2026-05-01
**Type**: 评判性 + import graph 真测 (Python import statement scan)

---

## §1 真测 (CC 5-01 真 scan)

实测 Python script: walk backend/ 全 .py file, 真 regex `^(from|import)\s+([a-zA-Z_][\w.]*)` 真 count.

**真值 Top 25 imports**:

| 序 | module | imports count | 含义 |
|---|---|---|---|
| 1 | **app** | **604** | sustained sustained sprint period sustained "FastAPI app" 真主入 |
| 2 | engines | 362 | sustained sprint period sustained "engines/ 纯计算" 真使用 |
| 3 | __future__ | 341 | annotations sustained 沉淀 ✅ |
| 4 | datetime | 298 | ✅ |
| 5 | pytest | 218 | 测试 import sustained |
| 6 | **backend** | **210** | **真证据 Wave 1+ "包名 backend.platform" 决议沉淀** ✅ |
| 7 | pandas | 168 | 数据处理 ✅ |
| 8 | typing | 165 | type annotations sustained |
| 9 | pathlib | 159 | ✅ |
| 10 | sys | 133 | ✅ |
| 11 | unittest | 127 | unittest sustained (sustained pytest 218 同) |
| 12 | structlog | 110 | log 真使用 ✅ |
| 13 | numpy | 106 | 数值 ✅ |
| 14 | dataclasses | 94 | ✅ |
| 15 | sqlalchemy | 88 | sustained sprint period sustained "sync psycopg2" but **sqlalchemy 88 imports** = ORM mixed |
| 16 | json | 67 | ✅ |
| 17 | logging | 65 | (log 真有 logging + structlog 双 source 真 candidate) |
| 18 | uuid | 64 | ✅ |
| 19 | **qm_platform** | **56** | **真证据 Wave 1+2+3 "qm_platform 12 framework" 真使用** ✅ |
| 20 | subprocess | 51 | ✅ |
| 21 | psycopg2 | 35 | sustained sprint period sustained "sync psycopg2" 真使用 ✅ |
| 22 | wrappers | 33 | dataclass wrappers sustained |
| 23 | os | 32 | ✅ |
| 24 | fastapi | 32 | FastAPI imports ✅ |
| 25 | math | 31 | ✅ |

---

## §2 🔴 finding — log 真双 source (logging vs structlog)

**真测**: logging (65 imports) + structlog (110 imports) 真**双 source sustained sprint period sustained**.

**真根因 candidate**: sprint period sustained 沉淀 structlog 主, 但 **logging 真 sustained 沉淀 65 imports** = 真**渐进迁移未完成** sustained.

**finding**:
- F-D78-254 [P2] backend/ 真 logging (65) + structlog (110) **双 log source sustained sprint period sustained** = 真**渐进迁移未完成 sustained**, sustained 铁律 16 信号路径唯一 同源 反 anti-pattern (log 路径不唯一)

---

## §3 🔴 finding — sqlalchemy + psycopg2 真混用 (sustained sprint period 沉淀 "sync psycopg2" 与真测矛盾)

**真测**: sqlalchemy (88 imports) > psycopg2 (35 imports). sprint period sustained CLAUDE.md 沉淀 "sync psycopg2" + Service 内部不 commit 但 真**sqlalchemy 88 imports** = 真生产 ORM 真**仍重 sustained**.

**finding**:
- F-D78-255 [P1] backend/ 真 sqlalchemy 88 imports vs psycopg2 35 imports = 真**ORM 重 sustained**, sustained CLAUDE.md "sync psycopg2" 真定位与真生产真**矛盾** sustained, 真生产 ORM 真路径 + 直 SQL 路径 真两套 sustained sustained (沿用 LL-034 sustained "SQLAlchemy text() :param 与 ::type 不混用" 同源加深)

---

## §4 真证据 — Wave 1+2+3 包名沉淀真 verify

| 包名 | imports | sustained sprint period |
|---|---|---|
| **app** | 604 | FastAPI app sustained ✅ |
| **backend** | 210 | Wave 1 决议 "包名 backend.platform" 沉淀 ✅ verify |
| **qm_platform** | 56 | Wave 1+2+3 "qm_platform 12 framework" 真使用 ✅ verify |

**真证据**: Wave 1+2+3 包名决议真**全沉淀 verify** ✅, 真使用率 backend 210 + qm_platform 56 = 真生产**真 platform 真在用** (sustained 沿用 sprint period sustained 沉淀 "platform 12 Framework + 6 升维" 真证据 verify).

---

## §5 真发现 — pytest + unittest 双 framework 真混用

**真测**: pytest (218 imports) + unittest (127 imports) 真**双 test framework**.

**finding**:
- F-D78-256 [P3] backend/ 真 pytest 218 + unittest 127 imports = 真**双 test framework sustained**, sustained sprint period sustained 真**渐进迁移真未完成** sustained 候选 (sustained 铁律 23 任务独立可执行 同源)

---

## §6 finding 汇总

| ID | 严重度 | 描述 |
|---|---|---|
| F-D78-254 | P2 | logging (65) + structlog (110) 双 log source sustained, 铁律 16 反 anti-pattern |
| **F-D78-255** | **P1** | sqlalchemy 88 vs psycopg2 35 真混用, CLAUDE.md "sync psycopg2" 与真生产矛盾 |
| F-D78-256 | P3 | pytest 218 + unittest 127 双 test framework sustained |

---

**文档结束**.
