# MVP 2.3 Backtest Parity 开源方案调研 (铁律 21 兑现)

> **目的**: MVP 2.3 Backtest Framework + U1 Parity 是 Wave 2 最后大块 (3-4 周工程, MLOps 圣杯级), 按铁律 21 "任何新功能开发前先花半天搜索成熟开源实现" 要求, 开工前必须先搜开源方案. 本文档覆盖 5 个候选 + 6 个可借鉴设计点 + 自建论据.
> **时间**: 2026-04-18 (Session 5 末, MVP 2.3 开工前)
> **决策**: 自建 `PlatformBacktestRunner` (不迁 Metaflow/Kedro), 但**吸收 6 个 pattern**
> **下一步**: MVP 2.3 Sub1 开工前 5-10 min 读本文件, 对照 `docs/mvp/MVP_2_3_backtest_parity.md` 设计稿 §D1-D6

---

## 候选方案 5 个对比

| 方案 | 厂商/社区 | 核心 pattern | 单机适用 | Parity 强度 | 借鉴价值 |
|---|---|---|---|---|---|
| **Metaflow** | Netflix | `@step` DAG + FlowSpec | ⚠️ 需 S3/metadata | 高 | 🟢 高 |
| **Kedro** | McKinsey / QuantumBlack | DataCatalog + pipelines 纯函数 | ✅ 纯 Python | 中 | 🟡 中 (DAL 已对齐) |
| **MLflow Tracking** | Databricks | `mlflow.start_run()` + log_{params,metrics,artifact} | ✅ local backend | 中 | 🟢 高 (run_id schema) |
| **Flyte** | Lyft | 强类型 typed task + Flytekit | ❌ K8s 强依赖 | 极高 (container snapshot) | 🟡 中 (typed pattern) |
| **DVC** | Iterative | `dvc.yaml` stage + git-LFS artifact | ✅ git-native | 中 | 🟡 中 (stage hash) |

---

## 各方案详解 + 借鉴 / 不借鉴理由

### 1. Metaflow (Netflix)

**核心 pattern**:
```python
from metaflow import FlowSpec, step, Parameter

class BacktestFlow(FlowSpec):
    mode = Parameter("mode", default="FULL_5Y")

    @step
    def start(self): self.next(self.load_data)

    @step
    def load_data(self):
        self.price_df = dal.read_ohlc(...)
        self.next(self.compute_signals)

    @step
    def compute_signals(self):
        self.signals = SignalPipeline().generate(...)
        self.next(self.run_backtest)
```

**优势**:
- 同一代码跑 dev (`python flow.py run`) / prod (`python flow.py run --production`)
- artifact 自动持久化 (`self.x` 写每个 step 结束时 pickle 到 S3/local)
- `run_id` 全局唯一, metadata service 可反查历史

**不直接用理由**:
- **S3 依赖**: 需要 local Datastore 或 S3, 单机单人 overkill
- **Metadata service**: 独立 daemon, 增运维负担
- **Pickle artifact**: 我们用 Parquet (factor data) / PG (metrics) 非 pickle, 重写序列化层
- **Flow 改造成本**: 现有 `run_hybrid_backtest` 函数式, 改成 FlowSpec 破坏 "包而不改" 原则 (设计稿 §D2)

**✅ 借鉴 (Pattern 1)**:
- **`run_id` UUID + artifact 路径约定**: Metaflow `s3://.../run_{id}/step_{name}/artifact.pickle`, 我们对应 `cache/backtest_artifacts/{run_id}/nav.parquet`
- **`@step` 概念暗线**: BacktestMode 各阶段 (load_data / compute_signals / run_engine / log_metrics) 概念上对应 step, 但我们不用 decorator 语法 (包而不改)

---

### 2. Kedro (McKinsey QuantumBlack)

**核心 pattern**:
```yaml
# conf/base/catalog.yaml
factor_data:
  type: pandas.ParquetDataSet
  filepath: data/01_raw/factor_values.parquet

# conf/base/parameters.yml
backtest:
  mode: FULL_5Y
  factor_pool: [turnover_mean_20, volatility_20, bp_ratio, dv_ttm]
```

```python
# src/pipelines/backtest/nodes.py (纯函数)
def compute_signals(factor_df, params):
    return SignalPipeline(params).generate(factor_df)
```

**优势**:
- DataCatalog 抽象 = 数据源/目标的 SSOT, 换数据源不改业务代码
- Pipelines 纯函数组合, 易测
- kedro-mlflow 插件对接 tracking
- Parity 天然 (同代码 dev/prod, 配置文件不同)

**不直接用理由**:
- **Plugin 生态复杂**: kedro-viz / kedro-mlflow / kedro-airflow 等多依赖, 我们项目单机
- **CLI 驱动**: `kedro run --pipeline=backtest` 与我们 `python scripts/run_backtest.py --config=...` 习惯不符
- **Directory 约定重**: `src/pipelines/` + `conf/` + `data/` 重组改动太大, 违反 "包而不改"

**✅ 借鉴 (Pattern 2)**:
- **DataCatalog 概念**: 已在 MVP 1.2a DAL 兑现 (`PlatformDataAccessLayer.read_*`), catalog.yaml 思想等价于 Platform interface.py
- **parameters.yml 配置**: 已在 MVP 1.2 ConfigLoader 兑现 (configs/pt_live.yaml 等)
- **纯函数 node**: 我们 `engines/backtest/` 已对齐 (铁律 31 Engine 纯计算)

---

### 3. MLflow Tracking (Databricks)

**核心 pattern**:
```python
import mlflow

with mlflow.start_run(experiment_id="core3_wf_validation") as run:
    mlflow.log_params({"mode": "WF_5FOLD", "top_n": 20, ...})
    # run backtest
    mlflow.log_metrics({"sharpe": 0.87, "mdd": -0.14, ...})
    mlflow.log_artifact("nav.parquet")
    # run.info.run_id is UUID
```

**优势**:
- 成熟 (2018 起, 业界广泛采用)
- 本地 backend 可用 (`mlflow.set_tracking_uri("file:./mlruns")`), 无 server 依赖
- run_id / experiment_id / metrics schema 简洁清晰
- UI (`mlflow ui`) 免费获得

**不直接用理由**:
- **ML 模型场景假设**: `log_model()` / `mlflow.pytorch.*` 等 API 对"回测"不直接
- **mlruns 目录结构**: 我们用 PG `backtest_run` 表存 metadata, 不走 mlflow 的文件系统
- **重依赖**: 引入 mlflow 包 + sqlalchemy backend, 重

**✅ 借鉴 (Pattern 3, 最强)**:
- **`run_id` UUID + `experiment_name` 两级命名**: 我们 `backtest_run.run_id UUID` 对齐, 加 `experiment_name VARCHAR(64)` 字段 (e.g. "regression_anchor_5yr" / "wf_sweep_top_n" / "pead_precondition")
- **`params` / `metrics` / `artifact_paths` JSONB 分层**: 设计稿 §D3 `backtest_run` 表已对齐 (config JSONB + metrics JSONB + artifact_json JSONB)
- **start_run / end_run context manager pattern**: Python `with BacktestRegistry().start_run(config) as run: result = runner.run(...)` 可选语法糖 (MVP 2.3 Sub2 考虑)

---

### 4. Flyte (Lyft)

**核心 pattern**:
```python
from flytekit import task, workflow
from dataclasses import dataclass

@dataclass
class BacktestInput:
    mode: str
    config_hash: str

@dataclass
class BacktestOutput:
    sharpe: float
    run_id: str

@task
def run_backtest(inp: BacktestInput) -> BacktestOutput:
    ...

@workflow
def bt_flow(inp: BacktestInput) -> BacktestOutput:
    return run_backtest(inp=inp)
```

**优势**:
- 强类型 (input/output 必须 `@dataclass`), 编译期 catch schema drift
- 容器 snapshot 保证 bit-identical 复现 (跨机器)
- Flytekit SDK 与 Python 友好

**不直接用理由**:
- **K8s 强依赖**: 需要 Flyte Admin / Propeller / DataCatalog 后端, 单机单人 overkill
- **Container runtime**: Docker 强依赖 (历史教训: RD-Agent 因 Docker + Windows 三重阻断 NO-GO)
- **生态封闭**: Flyte-native tasks 与 Python script 混用复杂

**✅ 借鉴 (Pattern 4)**:
- **强类型 input/output `@dataclass(frozen=True)`**: 已在 `backend/platform/backtest/interface.py` BacktestConfig / BacktestResult 兑现 (MVP 1.1 骨架)
- **编译期 schema 检查思路**: MVP 2.3 Sub1 `config_hash = sha256(BacktestConfig)` 依赖 frozen + sorted JSON, 变 schema 会破 hash (运行时 catch)

---

### 5. DVC (Iterative)

**核心 pattern**:
```yaml
# dvc.yaml
stages:
  backtest:
    cmd: python run_backtest.py --config configs/pt_live.yaml
    deps:
      - data/factor_values.parquet
      - src/engines/
    params:
      - configs/pt_live.yaml:
          - factor_pool
          - top_n
    outs:
      - cache/backtest/nav.parquet
    metrics:
      - cache/backtest/metrics.json
```

**优势**:
- git-native (`.dvc/` 目录 + git-LFS-like), 无 server 依赖
- stage hash 机制天然复现: deps + params 变 → stage 重跑, 否则 cache 命中
- CLI (`dvc repro`) 触发最小重算

**不直接用理由**:
- **不适合结构化 DB**: 我们 backtest_run 在 PG, DVC 适合 parquet/csv 文件
- **DVC remote 配置负担**: 需要配 S3/GCS 作 remote cache
- **git 污染**: `.dvc` 文件会污染 git history

**✅ 借鉴 (Pattern 5)**:
- **stage hash 复现锚点**: DVC stage_hash = hash(cmd + deps + params), 我们 `config_hash = sha256(BacktestConfig)` 同思想
- **deps / outs / metrics 分层**: 映射到 `backtest_run` 表: deps → lineage.inputs (MVP 2.2), outs → artifact_json, metrics → metrics JSONB
- **cache 命中跳过重算**: `PlatformBacktestRunner.run()` 先查 `registry.get_by_hash(config_hash)`, 命中直接返回 — 设计稿 §D2 已对齐

---

## 6 个具体借鉴点 (汇总 → MVP 2.3 Sub1 设计调整)

| # | 借鉴自 | 借鉴内容 | 落在 MVP 2.3 哪里 | 设计稿需调整? |
|---|---|---|---|---|
| 1 | MLflow | `run_id UUID` + `experiment_name VARCHAR(64)` 两级 | backtest_run schema `+experiment_name` 字段 | ✅ **补** (原设计稿 §D3 未含 experiment_name) |
| 2 | MLflow | params/metrics/artifact JSONB 分层 | backtest_run schema 已对齐 | 无需调整 |
| 3 | Flyte | frozen dataclass input/output | BacktestConfig/Result 已对齐 (MVP 1.1) | 无需调整 |
| 4 | DVC | config_hash stage 复现 + cache 命中跳过 | `PlatformBacktestRunner.run()` 先查 registry | 设计稿 §D2 已对齐 |
| 5 | Metaflow | artifact 路径约定 `{run_id}/{kind}.parquet` | 设计稿 §D3 artifact_json 补子路径约定 | ✅ **补** (加 artifact_path_convention §) |
| 6 | MLflow | `start_run()` context manager 语法糖 | Sub2 可选增强 | 🟡 **可选** (Sub2 考虑) |

---

## 自建 `PlatformBacktestRunner` 最终论据

**为什么不迁开源方案?**

1. **已有稳定底座**: `engines/backtest/runner.py::run_hybrid_backtest` 经过 Step 4-A 8 模块拆分 + Phase 1 加固 + 铁律 14/15/16/17/18 全验证, regression max_diff=0 Sharpe=0.6095 锚定 5 年
2. **Platform interface 已就位**: MVP 1.1 `backend/platform/backtest/interface.py` 6 abstract class 锁定, 迁开源需重签接口
3. **开源方案部署负担大**: Metaflow S3 / Kedro plugin / Flyte K8s / DVC remote 全部引入新依赖, 单机单人 overkill
4. **"包而不改" 降 blast radius**: MVP 2.3 Sub1 核心是"把函数式 runner 包成 OO"不是"重写"; 迁开源 = 重写, 违反 Blueprint 原则
5. **铁律 21 合规**: "花半天搜索成熟开源实现" 已兑现 (本文档), 确认 "借鉴 pattern 不迁代码" 结论

**借鉴 vs 迁移的边界**:
- ✅ 借鉴 **概念** (run_id / experiment_name / config_hash / cache 命中)
- ✅ 借鉴 **schema 设计** (params/metrics/artifact JSONB 分层)
- ❌ 不借鉴 **运行时库** (mlflow / kedro 不 import)
- ❌ 不借鉴 **目录约定** (`mlruns/` / `conf/` / `dvc.yaml` 不采用)

---

## MVP 2.3 Sub1 设计稿需要补的 2 处 (基于本调研)

**设计稿 `docs/mvp/MVP_2_3_backtest_parity.md` §D3 补**:

1. **`backtest_run` 表 `+experiment_name VARCHAR(64) NOT NULL DEFAULT 'default'`**
   - 支持 `regression_anchor_5yr` / `wf_sweep_top_n` / `pead_precondition` 等分组
   - 查询: `SELECT * FROM backtest_run WHERE experiment_name = 'pead_precondition' ORDER BY sharpe DESC`
   - 对齐 MLflow experiment_id 概念

2. **`artifact_path_convention §`**:
   ```
   cache/backtest_artifacts/{run_id}/
     ├── nav.parquet       # 净值曲线
     ├── holdings.parquet  # 逐日持仓
     ├── trades.parquet    # 成交记录
     └── metrics.json      # 额外指标 (与 metrics JSONB 双写)
   ```
   对齐 Metaflow 的 artifact 路径约定 + Lineage outputs 引用.

---

## 决策状态

- ✅ **自建 `PlatformBacktestRunner`** (Sub1 实施, ~2 周), 包 `run_hybrid_backtest`
- ✅ **吸收 6 借鉴点** (MVP 2.3 Sub1 开工时对齐)
- ✅ **补充 2 设计点** 入 `docs/mvp/MVP_2_3_backtest_parity.md` v1.1 (Session 6 开场)
- ❌ **不迁 Metaflow / Kedro / MLflow / Flyte / DVC**
- ❌ **不引入 mlflow / metaflow Python 包** (增依赖)

---

## 变更记录

- 2026-04-18 Session 5 末, 落盘. MVP 2.3 开工前置调研, 铁律 21 兑现.
- **下一步**: Session 6 MVP 2.3 Sub1 开工时重读本文件 + 对照设计稿 §D3 补 2 处.
