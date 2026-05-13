# V3 TB-3 pgvector + BGE-M3 Prerequisite Install — Pre-Sprint Setup Runbook

**触发条件**: TB-3 sprint 起手前 user 一句话 (e.g. "应用 TB-3 prereq install" OR "verify TB-3 prerequisites") 触发本 runbook.

**关联**: V3 §5.4 RiskMemoryRAG (Tier B) + ADR-064 D2 (BGE-M3 local embedding sustained) + ADR-067 (TB-2 closure cumulative + Tier B sprint chain).

## Why this runbook exists

TB-3 sprint = RiskMemoryRAG + pgvector + BGE-M3 + 4-tier retention. Preflight 2026-05-14 surfaced 2 BLOCKING infra prerequisites:

| Prerequisite | Current state | TB-3 dependency |
|---|---|---|
| **pgvector PG extension** | ❌ NOT installed AND NOT available (`pg_available_extensions` returns 0 rows) | V3 §5.4 DDL `embedding VECTOR(1024)` + `idx_risk_memory_embedding USING ivfflat` |
| **BGE-M3 model** | ❓ Not downloaded (need ~2GB disk) | TB-3b embedding wire — 1024 维 + 中文优化 per ADR-064 D2 |

Without these, TB-3 cannot proceed. This runbook documents the manual install path so user can prepare offline / batch-install before TB-3a 起手.

## 前置检查 (CC 自动执行)

```powershell
# 1. PG running + reachable?
$env:PGPASSWORD = 'quantmind'
& "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -c "SELECT version();"

# 2. PG version (pgvector requires PG 12+, recommend 15+)
& "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -c "SHOW server_version;"

# 3. Current PG extension dir
& "D:\pgsql\bin\pg_config.exe" --sharedir
& "D:\pgsql\bin\pg_config.exe" --pkglibdir

# 4. Python venv + huggingface_hub package check
cd D:\quantmind-v2
.\.venv\Scripts\python.exe -c "import sys; print('Python:', sys.version)"
.\.venv\Scripts\python.exe -c "import huggingface_hub; print('hf_hub:', huggingface_hub.__version__)" 2>&1
.\.venv\Scripts\python.exe -c "import sentence_transformers; print('st:', sentence_transformers.__version__)" 2>&1
```

**Expected**:
- PG 16.8 (per CLAUDE.md tech stack)
- `pg_config --sharedir` → `D:\pgsql\share`
- `pg_config --pkglibdir` → `D:\pgsql\lib`
- huggingface_hub + sentence_transformers may NOT be installed yet — runbook Step 2 will install

## 资金 0 风险确认 (5/5 红线 sustained)

| 红线 | Pre-ops | Post-ops expected | 验证 |
|---|---|---|---|
| cash | ¥993,520.66 | ¥993,520.66 (unchanged) | xtquant query_asset(81001102) |
| 持仓 | 0 | 0 (unchanged) | xtquant query_position(81001102) |
| LIVE_TRADING_DISABLED | true | true (unchanged) | `Select-String "LIVE_TRADING_DISABLED" backend\.env` |
| EXECUTION_MODE | paper | paper (unchanged) | `Select-String "EXECUTION_MODE" backend\.env` |
| QMT_ACCOUNT_ID | 81001102 | 81001102 (unchanged) | `Select-String "QMT_ACCOUNT_ID" backend\.env` |

**0 broker mutation / 0 .env change** in this runbook — pure infra prereq install + verification.

## 执行步骤

### Step 1: Install pgvector PG extension (Windows binary)

**Option A: Download official binary** (推荐, 0 build dependencies):

1. Download pgvector Windows binary matching PG version:
   - GitHub releases: https://github.com/pgvector/pgvector/releases
   - File: `pgvector-X.Y.Z-pg16-windows-x86_64.zip` (match server PG version)
   - Verify SHA256 against release notes

2. Extract + copy files to PG installation:
   ```powershell
   # Assuming download extracted to D:\Downloads\pgvector\
   # Copy DLLs to lib dir
   Copy-Item D:\Downloads\pgvector\lib\vector.dll D:\pgsql\lib\
   # Copy extension files to share dir
   Copy-Item D:\Downloads\pgvector\share\extension\vector.control D:\pgsql\share\extension\
   Copy-Item D:\Downloads\pgvector\share\extension\vector--*.sql D:\pgsql\share\extension\
   ```

3. **Stop PG service** + restart (extension load requires fresh process):
   ```powershell
   # If PG running as service
   & "D:\pgsql\bin\pg_ctl.exe" -D D:\pgdata16 stop
   Start-Sleep -Seconds 5
   & "D:\pgsql\bin\pg_ctl.exe" -D D:\pgdata16 start
   ```

4. Verify extension available + install:
   ```powershell
   $env:PGPASSWORD = 'quantmind'
   & "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -c "SELECT name, default_version FROM pg_available_extensions WHERE name = 'vector';"
   & "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -c "CREATE EXTENSION IF NOT EXISTS vector;"
   & "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -c "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';"
   ```

**Expected**:
- `pg_available_extensions` row for 'vector' with default_version (e.g. 0.7.0)
- `CREATE EXTENSION` succeeds
- `pg_extension` shows vector + extversion

**Option B: Build from source** (if binary unavailable for PG16/Windows — requires MSYS2 / MSVC):
- Clone https://github.com/pgvector/pgvector
- Build per BUILDING.md
- More complex, prefer Option A.

### Step 2: Install BGE-M3 Python dependencies

```powershell
cd D:\quantmind-v2
.\.venv\Scripts\pip.exe install huggingface_hub sentence-transformers transformers torch --upgrade
```

**Note**: torch is large (~2GB Windows wheel) — already installed per CLAUDE.md tech stack PyTorch cu128 RTX 5070. If reinstalling, may take 10-15 min on slow connection.

### Step 3: Download BGE-M3 model (~2GB disk)

```powershell
cd D:\quantmind-v2
.\.venv\Scripts\python.exe -c @"
from sentence_transformers import SentenceTransformer
print('Downloading BGE-M3 (1024 dim, 中文优化)...')
model = SentenceTransformer('BAAI/bge-m3', cache_folder='./models/bge-m3')
print('Model loaded; dimension:', model.get_sentence_embedding_dimension())
# Smoke test:
emb = model.encode('A股市场今日大涨 +3.5%')
print('Smoke encode shape:', emb.shape, 'dtype:', emb.dtype)
"@
```

**Expected**:
- Model downloads to `./models/bge-m3/` (~2GB)
- `dimension: 1024` matches V3 §5.4 DDL `VECTOR(1024)`
- Smoke encode produces `(1024,) float32` numpy array

**Disk usage**: After this step expect ~2-2.5GB at `./models/bge-m3/`. Add to `.gitignore` if not already.

### Step 4: Verify pgvector + BGE-M3 end-to-end (smoke test)

```powershell
cd D:\quantmind-v2
.\.venv\Scripts\python.exe -c @"
import psycopg2
from sentence_transformers import SentenceTransformer
import os
os.environ.setdefault('PGPASSWORD', 'quantmind')

# Load model
model = SentenceTransformer('./models/bge-m3')
emb = model.encode('test sentence for vector smoke')
assert emb.shape == (1024,), f'unexpected dim {emb.shape}'

# Connect + insert smoke vector
conn = psycopg2.connect('postgresql://xin@localhost:5432/quantmind_v2')
cur = conn.cursor()

# Try create temp vector table
cur.execute('CREATE TEMP TABLE _vec_smoke (id INT, v VECTOR(1024));')
emb_str = '[' + ','.join(f'{x:.6f}' for x in emb.tolist()) + ']'
cur.execute('INSERT INTO _vec_smoke (id, v) VALUES (1, %s::vector);', (emb_str,))

# Query cosine similarity (self-match should be ~1.0)
cur.execute('SELECT 1 - (v <=> %s::vector) AS sim FROM _vec_smoke WHERE id = 1;', (emb_str,))
sim = cur.fetchone()[0]
print(f'Self-similarity (cosine): {sim:.6f} (expected ~1.0)')
assert sim > 0.99, f'Self-similarity drift: {sim}'

cur.execute('DROP TABLE _vec_smoke;')
conn.commit()
conn.close()
print('✅ pgvector + BGE-M3 end-to-end smoke PASS')
"@
```

**Expected**: `Self-similarity (cosine): 1.000000` + `✅ pgvector + BGE-M3 end-to-end smoke PASS`.

### Step 5: Record prereq satisfied + ready for TB-3a

After Step 1-4 PASS, user can ack TB-3a 起手 in next session. CC will:
1. Verify pgvector + BGE-M3 still satisfied (re-run Step 1.4 + Step 3 smoke)
2. Apply TB-3a DDL migration (creates risk_memory table with `VECTOR(1024)` column)
3. Build interface dataclasses + repository
4. Tests with mock embedding + real-PG SAVEPOINT smoke

## 失败回滚

### Rollback A: pgvector extension uninstall

```powershell
$env:PGPASSWORD = 'quantmind'
& "D:\pgsql\bin\psql.exe" -U xin -d quantmind_v2 -c "DROP EXTENSION IF EXISTS vector CASCADE;"
# Remove DLL + extension files
Remove-Item D:\pgsql\lib\vector.dll -Force
Remove-Item D:\pgsql\share\extension\vector* -Force
# Restart PG
& "D:\pgsql\bin\pg_ctl.exe" -D D:\pgdata16 restart
```

**Risk**: `DROP EXTENSION ... CASCADE` removes any vector-typed columns (no impact pre-TB-3a since risk_memory doesn't exist yet).

### Rollback B: BGE-M3 model + dependencies uninstall

```powershell
# Remove model files
Remove-Item D:\quantmind-v2\models\bge-m3 -Recurse -Force
# Uninstall deps (only if reverting)
cd D:\quantmind-v2
.\.venv\Scripts\pip.exe uninstall sentence-transformers transformers huggingface_hub -y
```

**Risk**: 0 (model files + Python packages, no production code dependency).

## TB-3 sub-PR roadmap (after prereq satisfied)

| Sub-PR | Scope | Baseline | Prereq sustained |
|---|---|---|---|
| **TB-3a** | risk_memory DDL + interface dataclasses + repository + mock-embedding tests | ~3 days | pgvector ✅ |
| **TB-3b** | BGE-M3 EmbeddingService wire + per-sentence encode + tests | ~3 days | BGE-M3 model ✅ |
| **TB-3c** | RiskMemoryRAG.retrieve(query, k=5) + 4-tier retention + retrieval API <200ms P99 | ~3 days | TB-3a/b cumulative |
| **TB-3d** | TB-3 closure + ADR-068 + LL-162 + REGISTRY amend + Plan v0.2 §A row closure marker | ~1-2 days | TB-3a/b/c cumulative |

**TB-3 baseline**: ~10-12 days cumulative (replan 1.5x = 15-18 days, sustained ADR-064 Tier B 8.5-12 周 estimate).

## STATUS_REPORT 归档

After Step 1-4 PASS, sediment to `memory/project_sprint_state.md` Session 53+19 (or next session) handoff:
- pgvector version installed: vX.Y.Z
- BGE-M3 model cached at: ./models/bge-m3 (~2GB)
- End-to-end smoke verified: self-similarity 1.000
- 0 production code touched
- 0 broker mutation / 0 .env change
- Ready for TB-3a 起手

## 关联

- **V3 spec**: §5.4 line 689-708 Risk Memory RAG DDL + §5.4 line 712-716 embedding 模型决议
- **ADR**: ADR-022 / ADR-027 / ADR-029 / **ADR-064 D2** (BGE-M3 local embedding sustained) / ADR-066 (TB-1 closure) / ADR-067 (TB-2 closure cumulative)
- **LL**: LL-097 (ops runbook explicit) / LL-098 X10 (反 forward-progress default) / LL-100 (chunked sub-PR SOP) / LL-141 (4-step post-merge ops sustained) / LL-157 / LL-159 / LL-161 (TB-2 closure 4 sub-PR pattern sustained)
- **铁律**: 22 (doc 跟随代码) / 44 X9 (post-merge ops explicit checklist for future TB-3 Beat schedule)
- **Existing pattern reference**: `docs/runbook/cc_automation/v3_tb_2c_market_regime_beat_wire.md` (post-merge ops runbook 体例)
