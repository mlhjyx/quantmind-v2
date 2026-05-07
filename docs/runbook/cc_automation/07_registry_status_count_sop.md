# 07 — ADR REGISTRY Status Count Automation SOP

> **Why**: sub-PR 8b-cadence-A PR #256 reviewer HIGH finding catch — `docs/adr/REGISTRY.md` 真**status distribution count** 真**stale post-PR #255 ADR-039 + 本 PR ADR-040/041/042/043 add** sustained → committed 28 → 30 / reserved 6 → 9 / total 38 → 43 真**反自动同步**. **Frame drift sediment**.
> **触发**: 任 PR add/promote/deprecate ADR row → 真**REGISTRY.md status distribution 必同步 update**.

## 真**REGISTRY.md status distribution structure**

```markdown
## 真状态分布

- **committed (真 file 真在 docs/adr/)**: N 个 (ADR-XXX/YYY/...)
- **reserved (V3 §18.1 真预约 + ADR-DRAFT informal reservation)**: M 个 (ADR-XXX/YYY/...)
- **gap (0 file, 0 reserve)**: K 个 (ADR-XXX/YYY/..., 历史跳号 sustained)

总 (N+M+K) # space (含 gap), 真活跃 (N+M) (committed N + reserved M).
```

## 真**SOP-Registry-1 — PR add row** (committed / reserved)

### 真步骤
1. PR add 真**ADR row** to `docs/adr/REGISTRY.md`
2. PR **必同步 update** §真状态分布 section:
   - 真 committed count +1 (沿用 add committed row)
   - OR 真 reserved count +1 (沿用 add reserved row, e.g. ADR-DRAFT informal reservation)
   - 真 total # space +1
3. PR `# 下移体例` reserve sustained ADR-022 反 silent overwrite 沿用 ADR-024/027/023 case 1/2/3 sediment

### 真**自动 verify candidate** (chunk C-SOP-B 真预约 implementation)
- python script `scripts/verify_adr_registry_count.py` 真**count enumerate 沿用 grep `^| ADR-\d+ |` rows + state column** sustained 反 manual count drift

## 真**SOP-Registry-2 — PR promote ADR-DRAFT row → committed**

### 真步骤
1. ADR-DRAFT row N status 真 candidate → `→ ADR-XXX (committed)` mark
2. REGISTRY.md add `| ADR-XXX | <title> | committed | <source cite> |` row
3. Status distribution count update (committed +1 / reserved 真**反 change** 沿用 informal reservation 沉淀 stays reserved 真**multi-row reservation 体例**)
4. ADR file create `docs/adr/ADR-XXX-<slug>.md` (frontmatter + Context + Decision + Alternatives + Consequences + References)

## 真**SOP-Registry-3 — N×N drift cross-verify (LL-105 SOP-6)**

### 真**4 source cross-verify** (沿用 ADR-024/027/023 case 1/2/3 体例)
1. **REGISTRY.md** rows + status distribution section
2. **ADR-DRAFT.md** rows (informal reservation cite ADR-XXX)
3. **V3 §18.1** ADR # cite (sprint state cite)
4. **LL backlog** sediment (LL-105 SOP-6 cite)

### 真**冲突 detect 体例**
- ADR-DRAFT row N cite ADR-XXX 反 in REGISTRY → REGISTRY.md +reserved row 沉淀 sustained sub-task scope (e.g. sub-PR 8b-cadence-A REGISTRY drift fix +ADR-040/041/042 reserved sustained)
- V3 cite ADR-XXX 反 in REGISTRY + ADR-DRAFT → STOP + escalate user

## 真**反 anti-pattern** sediment

- ❌ PR add ADR row 反 update status distribution count → 沉淀 stale count drift sustained sub-PR 8b-cadence-A reviewer HIGH 体例
- ❌ ADR # silent overwrite 沿用 ADR-DRAFT informal reservation cite → 真**N×N 同步漂移** 沿用 ADR-024/027/023 case 1/2/3 体例 sediment
- ❌ Status distribution section "TBD" / "approx" 假设 sustained — 真**精确 count** sustained 反 estimate

## 真生产真值 evidence (5-07 cumulative)

- ADR-024 case 1 (V3§18.1 row 4 silent overwrite, # 下移)
- ADR-027 case 2 (4 audit docs Layer 4 SOP silent overwrite, # 下移)
- ADR-023 case 3 (V3§18.1 row 3 silent overwrite, # 下移)
- ADR-043 case 4 (sub-PR 8b-cadence-A ADR-040 silent overwrite ADR-DRAFT row 8, # 下移 sustained)
- sub-PR 8b-cadence-A reviewer HIGH (REGISTRY status count stale 28→30 / 6→9)

## 真关联

- ADR-022 反 silent overwrite governance
- ADR-037 SOP-6 4 source cross-verify
- LL-105 SOP-6 4 source cross-verify SOP
- 真讽刺 #10 ADR-040 silent overwrite reverse case (本 SOP 真**实证 fix path** sustained)
- chunk C-SOP-B 真预约 `scripts/verify_adr_registry_count.py` automation
