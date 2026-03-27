# Deep Research: Qlib Factor Mining & GP-Based Alpha Generation

> Research Date: 2026-03-28
> Scope: Qlib Alpha158, RollingGen, Expression Engine, GP Libraries, Island Model, Anti-Crowding
> Purpose: Inform QuantMind V2 Phase 1 factor mining architecture decisions

---

## 1. Qlib Alpha158 Factor Taxonomy

### 1.1 Factor Categories (158 total)

Alpha158 organizes factors into 3 major groups plus rolling expansions:

**Group A: KBAR Factors (9 factors)** -- Single candlestick analysis
| Factor | Formula | Economic Meaning |
|--------|---------|-----------------|
| KMID | (close - open) / open | Body midpoint ratio |
| KLEN | (high - low) / open | Total bar length |
| KMID2 | (close - open) / (high - low) | Body vs bar ratio |
| KUP | (high - max(open,close)) / open | Upper shadow |
| KUP2 | (high - max(open,close)) / (high-low) | Upper shadow ratio |
| KLOW | (min(open,close) - low) / open | Lower shadow |
| KLOW2 | (min(open,close) - low) / (high-low) | Lower shadow ratio |
| KSFT | (2*close - high - low) / open | Center-of-gravity shift |
| KSFT2 | (2*close - high - low) / (high-low) | Normalized COG shift |

**Group B: Price Factors (4 base x window)** -- Relative price positions
- OPEN/close, HIGH/close, LOW/close, VWAP/close at windows [0]

**Group C: Rolling Factors (29 indicators x 5 windows = 145 factors)**
Windows: [5, 10, 20, 30, 60] days

| Sub-Category | Factors | Count per Window |
|-------------|---------|-----------------|
| Trend | ROC, MA, BETA, RSQR, RESI | 5 |
| Volatility | STD, MAX, MIN, QTLU, QTLD, RSV | 6 |
| Timing (Aroon) | IMAX, IMIN, IMXD | 3 |
| Price-Volume Correlation | CORR, CORD, CNTP, CNTN, CNTD, SUMP, SUMN, SUMD | 8 |
| Volume Trend | VMA, VSTD | 2 |
| Volume Weighting | WVMA, VSUMP, VSUMN, VSUMD | 4 |
| **RANK** | percentile rank of price | 1 |

Total: 9 (KBAR) + 4 (Price) + 29*5 (Rolling) = 158

### 1.2 Overlap Analysis with QuantMind V2 34-Factor Design

| QuantMind Factor | Alpha158 Equivalent | Overlap Status |
|-----------------|---------------------|---------------|
| **turnover_mean_20** | VMA(20) | PARTIAL -- Alpha158 normalizes by current vol |
| **volatility_20** | STD(20) | DIRECT OVERLAP |
| **reversal_20** | ROC(20) | DIRECT OVERLAP (sign-flipped) |
| **amihud_20** | No direct equivalent | UNIQUE to QuantMind |
| **bp_ratio** | No equivalent (fundamental) | UNIQUE -- Alpha158 is pure price-volume |
| momentum_5/10 | ROC(5), ROC(10) | DIRECT OVERLAP |
| reversal_5/10/60 | ROC variants | DIRECT OVERLAP |
| volatility_60 | STD(60) | DIRECT OVERLAP |
| turnover_std_20 | VSTD(20) | PARTIAL |
| ep_ratio | No equivalent | UNIQUE (fundamental) |
| ln_market_cap | No equivalent | UNIQUE (fundamental) |
| price_volume_corr_20 | CORR(20) | DIRECT OVERLAP |
| high_low_range_20 | MAX(20) - MIN(20) proxy | PARTIAL |
| dv_ttm | No equivalent | UNIQUE (fundamental) |
| IVOL | RESI-related | PARTIAL |
| mf_divergence | No equivalent | UNIQUE (moneyflow) |
| price_level | No equivalent | UNIQUE |
| RSI_14 | SUMP/SUMN ratio | CONCEPTUAL OVERLAP |
| MACD_hist | No direct equivalent | UNIQUE formulation |
| ATR_norm | STD variant | PARTIAL |
| vwap_bias | VWAP price factor | PARTIAL |
| rsrs_score | No equivalent | UNIQUE |

**Key Finding**: Alpha158 is purely price-volume technical. Our system's unique advantages are:
1. **Fundamental factors** (bp_ratio, ep_ratio, dv_ttm) -- Alpha158 has zero
2. **Moneyflow factors** (mf_divergence) -- Alpha158 has zero
3. **Microstructure factors** (amihud_20, vwap_bias, rsrs_score) -- Alpha158 has zero
4. ~60% of our technical factors have Alpha158 equivalents

### 1.3 Alpha158 Performance on A-Share (Community Reports)

- LightGBM + Alpha158 on CSI300: ~24% annualized return, ~10% drawdown (optimistic, likely in-sample)
- Single-factor analysis: STD, CORR, SUMP/SUMN families show strongest IC on A-share
- KBAR factors individually weak (IC < 2%), but contribute in ensemble ML models
- Volume-related factors (VMA, VSTD, WVMA) generally stronger on A-share than on US markets
- Alpha158's T+2 label design accounts for A-share T+1 settlement rule

---

## 2. Qlib RollingGen: Temporal Cross-Validation

### 2.1 Mechanism

RollingGen generates a sequence of train/valid/test tasks by rolling a time window forward:

```
Task 1: Train [2018-01 to 2020-12] | Valid [2021-01 to 2021-06] | Test [2021-07 to 2021-12]
Task 2: Train [2018-07 to 2021-06] | Valid [2021-07 to 2021-12] | Test [2022-01 to 2022-06]
Task 3: Train [2019-01 to 2021-12] | Valid [2022-01 to 2022-06] | Test [2022-07 to 2022-12]
...
```

### 2.2 Key Parameters

- **step**: Rolling step size (how far the window moves each iteration)
- **rtype**: Rolling type -- `ROLL_SD` (rolling start date) vs `ROLL_EX` (expanding window)
- Market calendar aware: rolls on trading days, not calendar days

### 2.3 Integration Pattern

```python
from qlib.workflow.task.gen import RollingGen

rg = RollingGen(step=20, rtype=RollingGen.ROLL_SD)
tasks = rg.generate(task_template)
# Each task has independent train/valid/test segments
# TrainerRM handles execution via TaskManager
```

### 2.4 Relevance to QuantMind V2

Our LightGBM experiments (Sprint 1.4b) used manual 7-fold rolling validation. RollingGen would automate this, but:
- Requires Qlib data format (bin files) or adapter
- Our PostgreSQL-based pipeline would need a bridge
- **Recommendation**: Implement our own RollingGen equivalent using pandas DatetimeIndex, which is simpler and doesn't require Qlib dependency

---

## 3. Qlib Expression Engine

### 3.1 Syntax

Qlib's expression engine uses a DSL (domain-specific language):

```python
# Basic operators
"$close"                     # Raw field reference
"Ref($close, 5)"            # Lag by 5 periods
"Mean($close, 20)"          # 20-day moving average
"Std($close, 20)"           # 20-day standard deviation
"Corr($close, $volume, 20)" # 20-day correlation
"Rank($close)"              # Cross-sectional rank
"Max($high, 20)"            # Rolling max
"Min($low, 20)"             # Rolling min

# Compound expressions
"Mean($close, 5) / Mean($close, 20)"  # MA5/MA20 ratio
"Ref($close, -2) / Ref($close, -1) - 1"  # T+1 to T+2 return
```

### 3.2 Extensibility

Custom operators can be registered:

```python
from qlib.data.ops import ExpressionOps

class MyCustomOp(ExpressionOps):
    def _load_internal(self, instrument, start_index, end_index, freq):
        # Custom computation logic
        pass

# Register via qlib.config or test_register_ops.py pattern
```

### 3.3 Available Operators

**Element-wise**: Abs, Log, Sign, Power, Mask, If
**Rolling (time-series)**: Ref, Mean, Sum, Std, Var, Skew, Kurt, Max, Min, Med, Mad, Rank, Count, Slope, Rsquare, Resi, WMA, EMA, Corr, Cov
**Cross-sectional**: CSRank, CSZscore

### 3.4 Integration Assessment for QuantMind V2

**Pros of using Qlib expression engine**:
- Battle-tested operator set covering most technical indicators
- Expression strings are portable and version-controllable
- GP can generate expressions in Qlib syntax directly

**Cons**:
- Requires Qlib's binary data format (D.features() reads from bin cache)
- Heavy dependency -- Qlib installs 20+ packages
- Data pipeline coupling -- our PostgreSQL pipeline would need an adapter layer
- Expression evaluation not easily extractable as standalone

**Recommendation**: Do NOT use Qlib expression engine directly. Instead:
1. Reference Alpha158 formulas as a design catalog
2. Implement equivalent operators in our own `factor_engine.py` using pandas/numpy
3. Use the **quantbai/alpha158** standalone library as reference implementation
4. Build a lightweight expression parser if GP integration requires it

---

## 4. GP-Based Factor Mining: Library Comparison

### 4.1 gplearn

| Aspect | Assessment |
|--------|-----------|
| **Maturity** | Stable, scikit-learn compatible API |
| **Operators** | Limited: add, sub, mul, div, sqrt, log, abs, neg, max, min, sin, cos, tan |
| **Financial operators** | None built-in (no ts_mean, ts_std, ts_corr, rank, etc.) |
| **Data format** | 2D only (samples x features) -- cannot handle 3D panel data (date x stock x feature) |
| **Constants** | Random uniform only [-1, 1] -- no gradient optimization |
| **Parallelism** | Single-threaded evolution, only fitness eval parallelized |
| **Bloat control** | Max depth/size limits, parsimony coefficient |
| **Verdict** | **Insufficient for financial factor mining** -- 2D limitation is a dealbreaker for cross-sectional factors |

### 4.2 DEAP (Distributed Evolutionary Algorithms in Python)

| Aspect | Assessment |
|--------|-----------|
| **Maturity** | Very mature, highly flexible framework |
| **Operators** | Fully customizable -- define any primitive set |
| **Financial operators** | Must implement yourself, but full freedom |
| **Data format** | Any -- you control the fitness evaluation |
| **Constants** | Ephemeral constants with any distribution |
| **Parallelism** | Built-in multiprocessing, island model via `tools.migRing` |
| **Bloat control** | Static/dynamic depth limits, double tournament, lexicographic parsimony |
| **Multi-objective** | NSGA-II, SPEA2 built-in |
| **Verdict** | **Best framework choice** -- maximum flexibility, island model native, custom operator support |

### 4.3 PySR (SymbolicRegression.jl)

| Aspect | Assessment |
|--------|-----------|
| **Maturity** | Active development, backed by academic research |
| **Backend** | Julia (JIT compiled) -- 10-100x faster than Python GP |
| **Island model** | Built-in multi-population with migration |
| **Constants** | Gradient-free optimization (Nelder-Mead) -- finds optimal constants |
| **Operators** | Customizable but Julia-native (Python wrapper) |
| **Financial operators** | Would need Julia implementation of ts_mean, ts_rank, etc. |
| **Data format** | 2D regression focus -- not designed for panel data |
| **Simplification** | Automatic expression simplification via SymbolicUtils.jl |
| **Verdict** | **Fastest engine** but Julia dependency is friction. Best for pure regression, harder for panel financial data |

### 4.4 Comparison Matrix

| Feature | gplearn | DEAP | PySR |
|---------|---------|------|------|
| Speed | Slow | Medium | Fast (10-100x) |
| Custom operators | Limited | Full | Julia-side |
| Panel data (3D) | No | Yes (custom) | No |
| Island model | No | Yes (migRing) | Yes (native) |
| Multi-objective | No | Yes (NSGA-II) | No |
| Bloat control | Basic | Advanced | Advanced |
| Constants optimization | No | Manual | Auto (NM) |
| Python ecosystem | scikit-learn | Standalone | Julia bridge |
| Financial community | Common (券商研报) | Growing | Rare |
| Maintenance | Low activity | Active | Very active |

### 4.5 Recommendation for QuantMind V2

**Primary: DEAP** -- for the following reasons:
1. Full control over fitness function (can use IC, ICIR, or multi-objective IC + turnover)
2. Native island model support via `tools.migRing` / `tools.migBest`
3. Can implement financial time-series operators as custom primitives
4. Multi-objective optimization (NSGA-II) for simultaneously optimizing IC and novelty
5. Active Chinese quant community support (华泰/申万研报均用DEAP)

**Secondary: PySR** -- as a fast pre-screener:
1. Use PySR for rapid exploration of simple factor expressions
2. Feed promising structures to DEAP for refinement with financial operators

**Not recommended: gplearn** -- 2D limitation and lack of financial operators make it unsuitable

---

## 5. State-of-the-Art GP for Alpha Generation

### 5.1 Classical GP Improvements

1. **Semantic GP (SGP)**: Uses program behavior (output vectors) rather than syntax to guide search. Geometric semantic crossover guarantees semantic interpolation.

2. **Equality Graph GP**: Stores all visited expressions and their equivalent forms in an e-graph data structure. Filters combinations that would create already-visited expressions. Competitive with PySR without increasing cost.

3. **GPU-Accelerated GP (Beagle)**: Fuses operators into SIMD kernels. Distributes populations across GPU cores. 100x speedup for large populations.

### 5.2 LLM-Guided GP (Frontier, 2025-2026)

Three major frameworks have emerged:

**AlphaAgent (Feb 2025, KDD 2025)**
- Three specialized LLM agents: Idea Agent, Factor Agent, Eval Agent
- Anti-decay: AST-based originality enforcement (similarity measure against existing alphas)
- Complexity control via AST structural constraints
- Results: Outperforms traditional GP on CSI500 and S&P500 over 4 years

**Navigating the Alpha Jungle (May 2025)**
- LLM + Monte Carlo Tree Search (MCTS) hybrid
- UCT criterion for node selection, LLM for expansion
- Backtesting feedback guides MCTS exploration
- Outperforms GP baselines in predictive accuracy and interpretability

**QuantaAlpha (Feb 2026, Tsinghua/PKU/CMU)**
- Evolutionary framework with trajectory-level mutation and crossover
- Uses GPT-5.2 backbone: IC=0.1501, ARR=27.75%, MDD=7.98% on CSI300
- CSI300 factors transfer to CSI500 (160% cumulative excess) and S&P500 (137%)
- Semantic consistency enforcement across hypothesis-factor-code
- Self-evolving trajectories with localized revision

### 5.3 Implications for QuantMind V2

The LLM-guided approaches are state-of-the-art but require:
- LLM API costs (DeepSeek V3 is cost-effective)
- Complex multi-agent orchestration
- Backtesting infrastructure for feedback loops

**Recommended phased approach**:
1. **Phase 1 (immediate)**: DEAP-based GP with classical improvements (island model, anti-crowding)
2. **Phase 1+ (after GP baseline)**: Add LLM warm-start for initial population (like EvoSpeak)
3. **Phase 3 (AI integration)**: Full AlphaAgent/QuantaAlpha-style framework with DeepSeek

---

## 6. Island Model Implementation

### 6.1 Architecture

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Island 1 │    │ Island 2 │    │ Island 3 │    │ Island 4 │
│ Pop: 200 │    │ Pop: 200 │    │ Pop: 200 │    │ Pop: 200 │
│ Fitness:  │    │ Fitness:  │    │ Fitness:  │    │ Fitness:  │
│  IC_mean  │    │  ICIR     │    │  IC+Novel │    │  IC_decay │
└────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬─────┘
     │               │               │               │
     └───────────────┼───────────────┼───────────────┘
                     │  Migration    │
                     │  every 50 gen │
                     ▼               ▼
              ┌─────────────────────────┐
              │   Global Hall of Fame   │
              │   (Pareto front of      │
              │    IC x Novelty x       │
              │    Simplicity)          │
              └─────────────────────────┘
```

### 6.2 DEAP Implementation Sketch

```python
from deap import tools, algorithms

# Create 4 islands with different fitness objectives
islands = [toolbox.population(n=200) for _ in range(4)]

# Different fitness functions per island (speciation)
fitness_fns = [
    lambda ind: (ic_mean(ind),),           # Island 1: Pure IC
    lambda ind: (icir(ind),),              # Island 2: IC Information Ratio
    lambda ind: (ic_mean(ind), novelty(ind)),  # Island 3: IC + Novelty (NSGA-II)
    lambda ind: (ic_decay_ratio(ind),),    # Island 4: Decay resistance
]

# Migration topology: ring
for gen in range(500):
    for i, island in enumerate(islands):
        # Evolve each island independently
        island = algorithms.varAnd(island, toolbox, cxpb=0.5, mutpb=0.3)
        fitnesses = map(fitness_fns[i], island)
        for ind, fit in zip(island, fitnesses):
            ind.fitness.values = fit
        island = toolbox.select(island, len(island))
        islands[i] = island

    # Migration every 50 generations
    if gen % 50 == 0:
        tools.migRing(islands, k=5, selection=tools.selBest)
```

### 6.3 Key Configuration Parameters

| Parameter | Recommended | Rationale |
|-----------|-------------|-----------|
| Num islands | 4 (= CPU cores / 3) | R9-9900X3D has 12 cores, leave headroom |
| Pop per island | 200-500 | Balance diversity vs evaluation cost |
| Migration interval | 50 generations | Too frequent = premature convergence |
| Migration size | 5 individuals | Top-5 elitist migration |
| Migration topology | Ring | Simple, prevents over-mixing |
| Total generations | 300-500 | With early stopping on IC plateau |
| Crossover rate | 0.5-0.7 | Standard GP settings |
| Mutation rate | 0.2-0.3 | Slightly higher for exploration |
| Max tree depth | 6-8 | Deeper trees rarely generalize |

---

## 7. Anti-Crowding Measures

### 7.1 Problem Statement

GP tends to converge to variations of the same expression. In factor mining, this means:
- 50 slightly different volatility factors instead of 50 diverse factors
- High correlation between GP-discovered factors (crowding)
- No incremental value when adding to an existing factor portfolio

### 7.2 Techniques

**A. Fitness Sharing / Niching**
- Penalize fitness proportional to how many similar individuals exist
- Similarity metric: Spearman correlation of factor values (cross-sectional, per date)
- If corr(factor_i, factor_j) > 0.7, both get fitness penalty

```python
def shared_fitness(individual, population, sigma=0.7):
    raw_ic = evaluate_ic(individual)
    niche_count = sum(1 for other in population
                      if correlation(individual, other) > sigma)
    return raw_ic / niche_count
```

**B. Novelty Search (Lehman & Stanley 2011)**
- Replace or augment IC-based fitness with a novelty score
- Novelty = average distance to k-nearest neighbors in behavior space
- Behavior = factor value vector across cross-section
- Maintains an archive of novel individuals seen historically

```python
def novelty_score(individual, archive, k=15):
    behavior = compute_factor_values(individual)
    distances = [1 - abs(spearman_corr(behavior, a)) for a in archive]
    distances.sort()
    return np.mean(distances[:k])
```

**C. MAP-Elites / Quality-Diversity**
- Discretize a behavior space (e.g., IC x turnover x complexity)
- Each cell in the grid maintains only the best individual
- Guarantees diversity across behavioral dimensions
- Especially relevant for factors: want high-IC factors at DIFFERENT turnover levels

**D. AST-Based Deduplication (AlphaAgent approach)**
- Parse expression trees and compute structural similarity
- Reject new factors that are AST-similar to existing ones
- More robust than correlation-based (catches `A*B` vs `B*A`)

**E. Semantic Hashing**
- Hash the output vector of each factor (binned)
- Identical hashes = identical behavior = reject
- Fast O(1) deduplication check

### 7.3 Recommended Approach for QuantMind V2

Use a layered anti-crowding strategy:

1. **Layer 1 (Fast)**: Semantic hashing -- reject exact duplicates in O(1)
2. **Layer 2 (Medium)**: Spearman correlation check against factor pool -- reject if max_corr > 0.7
3. **Layer 3 (Slow)**: Novelty score as secondary fitness objective (NSGA-II with IC + novelty)
4. **Layer 4 (Post-hoc)**: After GP run, cluster all discovered factors, select diverse representatives

This matches our existing CLAUDE.md design: "反拥挤阈值降到0.5-0.6（0.8太高，相关性0.79本质是同一因子变体）"

---

## 8. Integration Path: Qlib as Library vs Our Pipeline

### 8.1 Option A: Full Qlib Pipeline (NOT Recommended)

```
Qlib bin data → Alpha158 Handler → LightGBM/DNN → RollingGen → Backtest
```
- Requires converting our PostgreSQL data to Qlib bin format
- Replaces our entire pipeline
- Vendor lock-in to Qlib's design choices

### 8.2 Option B: Qlib Expression Engine Only (NOT Recommended)

```
Our PostgreSQL → Qlib data adapter → Qlib ExpressionOps → Our pipeline
```
- Requires maintaining a data format bridge
- Expression engine tightly coupled to Qlib internals
- Overhead not justified for our factor count (<100)

### 8.3 Option C: Alpha158 as Design Reference + Standalone Impl (RECOMMENDED)

```
Our PostgreSQL → Our factor_engine.py (Alpha158-inspired) → Our pipeline
```
- Reference Alpha158 factor catalog for design completeness
- Implement in our own pandas/numpy code (already partially done)
- Use quantbai/alpha158 (MIT license) as reference for formula correctness
- Zero additional dependencies

### 8.4 Option D: Hybrid for GP (RECOMMENDED for Phase 1)

```
Our PostgreSQL → DEAP GP engine (with Qlib-style expression syntax) → Our factor_engine.py
```
- GP generates factor expressions using Qlib-compatible operator names
- Expression parser translates to pandas operations
- Discovered factors feed into our existing validation pipeline (IC, t-stat, FACTOR_TEST_REGISTRY)

---

## 9. Recommended Architecture for QuantMind V2

### 9.1 Phase 1 Factor Mining Architecture

```
┌─────────────────────────────────────────────────────┐
│                  GP Factor Mining Engine             │
│                                                     │
│  ┌───────────┐  ┌───────────┐  ┌───────────┐       │
│  │ DEAP Core │  │ Operator  │  │ Expression │       │
│  │ Island    │  │ Library   │  │ Parser     │       │
│  │ Model     │  │ (TS/CS)   │  │            │       │
│  └─────┬─────┘  └─────┬─────┘  └─────┬─────┘       │
│        │              │              │              │
│  ┌─────▼──────────────▼──────────────▼─────┐        │
│  │          Fitness Evaluator               │        │
│  │  - IC calculation (5d fwd excess ret)    │        │
│  │  - Correlation check vs existing pool    │        │
│  │  - Novelty score                         │        │
│  │  - Complexity penalty                    │        │
│  └─────────────────┬───────────────────────┘        │
│                    │                                │
│  ┌─────────────────▼───────────────────────┐        │
│  │          Anti-Crowding Layer             │        │
│  │  L1: Semantic hash dedup                 │        │
│  │  L2: Spearman corr < 0.6                │        │
│  │  L3: Novelty as fitness objective        │        │
│  │  L4: Post-hoc clustering                 │        │
│  └─────────────────────────────────────────┘        │
└─────────────────────┬───────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────┐
│          Existing Validation Pipeline               │
│  Factor Registry → IC/t-stat → SimBroker Backtest   │
│  → Bootstrap CI → FACTOR_TEST_REGISTRY.md           │
└─────────────────────────────────────────────────────┘
```

### 9.2 GP Primitive Set (Financial Operators)

```python
# Time-series operators (applied per-stock along time axis)
TS_OPERATORS = {
    'ts_mean':   lambda x, d: x.rolling(d).mean(),
    'ts_std':    lambda x, d: x.rolling(d).std(),
    'ts_max':    lambda x, d: x.rolling(d).max(),
    'ts_min':    lambda x, d: x.rolling(d).min(),
    'ts_rank':   lambda x, d: x.rolling(d).rank(pct=True).iloc[-1],
    'ts_corr':   lambda x, y, d: x.rolling(d).corr(y),
    'ts_delta':  lambda x, d: x.diff(d),
    'ts_decay':  lambda x, d: (x * np.arange(1, d+1)).rolling(d).sum() / np.arange(1, d+1).sum(),
    'ts_argmax': lambda x, d: x.rolling(d).apply(np.argmax),
    'ts_argmin': lambda x, d: x.rolling(d).apply(np.argmin),
    'ts_sum':    lambda x, d: x.rolling(d).sum(),
    'ts_skew':   lambda x, d: x.rolling(d).skew(),
    'ts_kurt':   lambda x, d: x.rolling(d).kurt(),
}

# Cross-sectional operators (applied across stocks per date)
CS_OPERATORS = {
    'cs_rank':   lambda x: x.rank(pct=True),
    'cs_zscore': lambda x: (x - x.mean()) / x.std(),
    'cs_demean': lambda x: x - x.mean(),
    'cs_winsor': lambda x: x.clip(x.quantile(0.01), x.quantile(0.99)),
}

# Arithmetic operators
ARITH_OPERATORS = {
    'add': operator.add,
    'sub': operator.sub,
    'mul': operator.mul,
    'div': protected_div,     # div by zero -> 0
    'abs': np.abs,
    'log': protected_log,     # log(|x| + 1e-8)
    'sign': np.sign,
    'neg': operator.neg,
    'inv': lambda x: 1.0 / (x + 1e-8),
    'sqrt': lambda x: np.sqrt(np.abs(x)),
    'square': lambda x: x ** 2,
}

# Terminal set (input features from our PostgreSQL)
TERMINALS = ['open', 'high', 'low', 'close', 'volume', 'amount',
             'turnover_rate', 'vwap']

# Window constants
WINDOWS = [5, 10, 20, 30, 60]
```

### 9.3 Resource Budget (R9-9900X3D + 32GB)

| Component | Allocation |
|-----------|-----------|
| GP evolution (DEAP) | 8 cores, ~8GB RAM |
| Factor evaluation (pandas) | 4 cores, ~4GB RAM |
| PostgreSQL | ~5GB (data + indexes) |
| OS + other | ~8GB |
| **Total** | **~25GB / 32GB** |

Estimated runtime:
- 4 islands x 200 pop x 500 gen = 400,000 evaluations
- Each evaluation: ~0.5s (rolling IC on 5yr x 5000 stocks)
- With 8-core parallelism: ~25,000 seconds = ~7 hours
- **Optimization**: Pre-compute base features, cache rolling windows -> reduce to ~2-3 hours

---

## 10. Alpha158 Factors NOT in Our System (Gap Analysis)

The following Alpha158 factors have no equivalent in our current 74-test registry and may be worth implementing:

| Factor | Category | Economic Meaning | Priority |
|--------|----------|-----------------|----------|
| BETA (5/10/20/30/60) | Trend | Linear regression slope of log-price | Medium -- we have reversal, not trend slope |
| RSQR (5/10/20/30/60) | Trend | R-squared of price trend | Medium -- trend linearity |
| RESI (5/10/20/30/60) | Trend | Regression residual | Low -- related to IVOL |
| QTLU/QTLD (5/10/20/30/60) | Volatility | 80th/20th percentile of returns | Medium -- quantile-based vol |
| RSV (5/10/20/30/60) | Volatility | (close-min)/(max-min) position | Medium -- Williams %R equivalent |
| IMXD (5/10/20/30/60) | Timing | Days between max and min | Low -- Aroon oscillator |
| CORD (5/10/20/30/60) | Correlation | Rank correlation close-volume | High -- we have CORR but not CORD |
| CNTP/CNTN/CNTD | Directional | Up/down day percentage | Medium -- sentiment |
| WVMA (5/10/20/30/60) | Volume | Volume-weighted moving average | Medium |

**Recommendation**: Implement BETA, RSV, CORD, CNTP/CNTD as they fill gaps in our factor taxonomy. These 5 families (x5 windows = 25 factors) would bring our coverage to ~85% of Alpha158's conceptual space.

---

## 11. Key References

### Academic Papers
- AlphaAgent: LLM-Driven Alpha Mining (KDD 2025) -- https://arxiv.org/abs/2502.16789
- Navigating the Alpha Jungle: MCTS Framework (May 2025) -- https://arxiv.org/abs/2505.11122
- QuantaAlpha: Evolutionary LLM Alpha Mining (Feb 2026) -- https://arxiv.org/abs/2602.07085
- PySR: High-Performance Symbolic Regression -- https://arxiv.org/abs/2305.01582
- Improving GP with Equality Graphs (GECCO 2025) -- https://arxiv.org/html/2501.17848v2

### Industry Research (券商研报)
- 华泰证券: 基于遗传规划的选股因子挖掘 (系列二十一)
- 申银万国: 基于遗传规划算法的ALPHA101再扩展

### Open Source
- Microsoft Qlib: https://github.com/microsoft/qlib
- DEAP: https://github.com/DEAP/deap
- PySR: https://github.com/MilesCranmer/PySR
- gplearn: https://github.com/trevorstephens/gplearn
- quantbai/alpha158 (standalone pandas impl): https://github.com/quantbai/alpha158
- QuantaAlpha: https://github.com/QuantaAlpha/QuantaAlpha
- AlphaAgent: https://github.com/RndmVariableQ/AlphaAgent
- KunQuant (Alpha101+158 compiler): https://github.com/Menooker/KunQuant
- 券商研报复现: https://github.com/hugo2046/QuantsPlaybook

### Community Resources
- Qlib Alpha158 复现 (CSDN): https://blog.csdn.net/weixin_38175458/article/details/135751721
- DEAP多股票因子挖掘 (知乎): https://zhuanlan.zhihu.com/p/701313282
- Qlib数据层文档: https://qlib.readthedocs.io/en/latest/component/data.html

---

## 12. Executive Summary & Actionable Recommendations

### For Immediate Implementation (Phase 1)

1. **Factor Library Expansion**: Add 25 Alpha158-inspired factors (BETA, RSV, CORD, CNTP/CNTD families) to fill taxonomy gaps. Estimated effort: 2-3 days.

2. **GP Engine with DEAP**: Build a DEAP-based GP factor mining engine with:
   - 4-island model with heterogeneous fitness functions
   - Financial operator primitive set (ts_mean, ts_std, cs_rank, etc.)
   - 4-layer anti-crowding (hash + correlation + novelty + clustering)
   - Expression parser that outputs pandas code
   - Estimated effort: 2-3 weeks.

3. **Rolling Validation**: Implement our own RollingGen equivalent (simple pandas DatetimeIndex roller) rather than importing Qlib's. Estimated effort: 2-3 days.

4. **Do NOT adopt Qlib as a dependency**. Use Alpha158 as a design reference only. Our PostgreSQL-based pipeline is sufficient and avoids vendor lock-in.

### For Future Integration (Phase 3)

5. **LLM-Guided Evolution**: When AI module is ready, add DeepSeek-powered warm-start population generation (AlphaAgent pattern) to the DEAP GP engine.

6. **QuantaAlpha-style Trajectory Evolution**: Implement trajectory mutation/crossover once the basic GP pipeline is validated.

7. **MCTS Factor Search**: Consider the "Alpha Jungle" MCTS approach as an alternative to GP for structured factor space exploration.
