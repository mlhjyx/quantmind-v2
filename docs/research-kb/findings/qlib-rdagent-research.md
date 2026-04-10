# Qlib + RD-Agent 技术调研报告

> **日期**: 2026-04-10
> **环境**: Windows 11 Pro, Python 3.11.9, RTX 5070 12GB, 32GB RAM, PG 16.8+TimescaleDB
> **方法**: 实际安装 + 源码分析 + 因子对比 (非纯文档调研)
> **结论**: **路线C（混合）— 自建核心 + Alpha158因子借鉴 + riskfolio-lib**

---

## 1. Qlib 调研结果

### 1.1 安装验证 (实测)

| 项目 | 结果 | 证据 |
|------|------|------|
| 包版本 | pyqlib 0.9.7 (2025-08-15) | PyPI |
| Python 3.11.9 | ✅ 兼容 | 官方支持 3.8-3.12 |
| Windows wheel | ✅ `cp311-cp311-win_amd64.whl` (877KB) | 实测安装成功 |
| `import qlib` | ✅ 成功 | 需手动装 joblib/pydantic-settings/redis |
| Alpha158DL import | ✅ 成功 | 158个因子定义全部可读取 |
| 完整依赖 | ⚠️ mlflow SSL超时 | 网络问题, 非兼容性 |
| Source build | ❌ Cython链接错误 | Issue #1769, 不需要 |

### 1.2 数据格式评估

- Qlib 使用自有 **二进制 .bin 格式**, 三层缓存 (Mem/Expression/Dataset)
- 转换路径: PG → Parquet → CSV → `dump_bin.py` → .bin
- **结论**: 需维护双份数据, 集成成本高, 不值得迁移

### 1.3 Alpha158 因子完整分析 (源码提取)

**158个纯OHLCV因子**, 28个滚动类别 × 5窗口(5/10/20/30/60) + 9 KBAR + 4 Price + 5 RANK:

| 类别 | 数量 | 公式 | 含义 |
|------|------|------|------|
| KBAR | 9 | (close-open)/open 等 | K线形态 |
| Price | 4 | OPEN/HIGH/LOW/VWAP 比率 | 价格特征 |
| ROC | 5 | Ref(close,d)/close | 动量 |
| MA | 5 | Mean(close,d)/close | 均线偏离 |
| STD | 5 | Std(close,d)/close | 波动率 |
| BETA | 5 | Slope(close,d)/close | 趋势斜率 |
| RSQR | 5 | Rsquare(close,d) | **趋势线性度** |
| RESI | 5 | Resi(close,d)/close | **偏离趋势** |
| MAX/MIN | 10 | Max(high,d)/close | 区间极值 |
| QTLU/QTLD | 10 | Quantile(close,d,0.8/0.2) | **分位数** |
| RANK | 5 | Rank(close,d) | 百分位 |
| RSV | 5 | (close-min)/(max-min) | 随机振荡 |
| IMAX/IMIN/IMXD | 15 | IdxMax/IdxMin/差值 | **Aroon时间** |
| CORR/CORD | 10 | Corr(close,vol) / Corr(ret,vol_chg) | 量价相关 |
| CNTP/CNTN/CNTD | 15 | Mean(close>prev) | 涨跌天数比 |
| SUMP/SUMN/SUMD | 15 | Sum(gains)/Sum(|changes|) | RSI类 |
| VMA/VSTD | 10 | Mean(vol,d)/vol | 量均值/标准差 |
| WVMA | 5 | Std(|ret|×vol,d) | **量价联动波动** |
| VSUMP/VSUMN/VSUMD | 15 | 量RSI | 成交量RSI |

### 1.4 Alpha158 vs 我们因子对比

**重叠 (15个)**: momentum↔ROC, reversal↔-ROC, volatility↔STD, volume_std↔VSTD, pv_corr↔CORR, hl_range↔KLEN, kbar_kmid↔KMID, kbar_ksft↔KSFT, kbar_kup↔KUP, relative_volume↔VMA, up_days_ratio↔CNTP, stoch_rsv↔RSV, maxret↔MAX, beta_market↔BETA, gain_loss_ratio↔SUMP/SUMN

**Alpha158有我们没有的新类别 (6个)**:

| 因子 | 公式 | 经济逻辑 | 优先级 |
|------|------|---------|--------|
| RSQR_20 | Rsquare(close, 20) | 趋势线性度, 高→强趋势 | ⭐ P0 |
| RESI_20 | Resi(close, 20)/close | 偏离趋势, 均值回归信号 | ⭐ P0 |
| IMAX_20 | IdxMax(high, 20)/20 | 距最高点天数, Aroon上行 | ⭐ P0 |
| IMIN_20 | IdxMin(low, 20)/20 | 距最低点天数, Aroon下行 | P1 |
| QTLU_20 | Quantile(close, 20, 0.8)/close | 80%分位, 价格分布 | P1 |
| CORD_20 | Corr(ret, vol_change, 20) | 收益-量变相关 | P2 |

**我们有Alpha158没有的 (独特价值)**: 换手率因子(4), 流动性amihud(1), 基本面(4), 资金流(5+), 北向(15), TA-Lib(5), PEAD(1), vwap_bias/rsrs_raw(2)

**关键结论**: Alpha158=纯量价窗口变体库。CLAUDE.md已记录"量价因子窗口变体IC天花板0.05-0.06"。**真正新的类别仅6个**, 其余与我们现有因子重叠或为窗口变体。

### 1.5 兼容性总结

| 问题 | 答案 |
|------|------|
| Windows 11 | ✅ pip wheel OK (实测) |
| Python 3.11 | ✅ (实测) |
| 替代SimpleBacktester | ❌ 无PMS/涨跌停/历史税率/三因素滑点 |
| 自定义因子 | ✅ 通过CSV列扩展 |
| Size-neutral | ❌ 无内置 |
| Portfolio优化 | ⚠️ 仅EnhancedIndexing |
| factor_values集成 | 🔴 高—需维护双份数据 |

### 1.6 Qlib 结论: ⚠️ 部分可用

- ✅ 提取6个新因子类别在factor_engine实现 (不需要Qlib运行时)
- ❌ 数据层/回测引擎/信号层不迁移

---

## 2. RD-Agent 调研结果

### 2.1 安装验证 (实测)

| 项目 | 结果 |
|------|------|
| 包版本 | rdagent 0.8.0 (含RD-Agent(Q)) |
| pip install | ✅ 包本身可装 |
| 依赖数 | 79个, 含 **docker**/langchain/litellm/streamlit/mlflow |
| Docker依赖 | ❌ **硬依赖** (requires列表, 非optional) |

### 2.2 Docker硬依赖确认 (源码证据)

`rdagent/scenarios/qlib/developer/factor_runner.py`:
- L36-41: `class QlibFactorRunner` — "Docker run, Everything in a folder"
- L77: "passing the combined data to Docker for backtest results"
- L119: "rdagent and qlib docker image"
- L28-29: `DockerEnv().run(local_path=self.ws_path, entry="qrun conf_baseline.yaml")`

**所有因子回测都通过Docker容器执行, 无本地运行选项。**

### 2.3 三重阻断

1. **Docker硬依赖** — 我们无Docker, 安装需WSL2+Hyper-V
2. **Windows 11已知bug** — Issue #1064: 硬编码`/tmp/full`路径导致mount失败
3. **LLM backend** — 仅文档记录OpenAI/Azure/DeepSeek, Claude未验证 (Issue #1016)

### 2.4 RD-Agent 结论: ❌ 不适用

---

## 3. 综合决策

### 路线推荐: 路线C（混合）— 自建核心 + 选择性借鉴

| 组件 | 决策 | 来源 |
|------|------|------|
| 回测/信号/执行 | **自建维护** | 我们SimpleBacktester有A股特化, Qlib无法替代 |
| 因子计算 | **自建 + 6个Alpha158新类别** | 在factor_engine实现, 不需Qlib运行时 |
| Portfolio优化 | **引入riskfolio-lib** | MVO/RP/BL, Windows原生 |
| 向量化回测 | **评估VectorBT** | 841s→<60s目标 |
| 因子分析 | **评估alphalens-reloaded** | 补充profiler分析 |

### 下一步行动

1. 在factor_engine.py实现6个Alpha158新因子 (RSQR/RESI/IMAX/IMIN/QTLU/CORD)
2. 走正常因子评估流程 (铁律4/5/13/14)
3. riskfolio-lib评估 (阶段2 Portfolio优化)
4. 清理.venv-qlib/.venv-rdagent

### 风险

1. Alpha158新因子可能与现有因子高相关 — 需IC+corr检查
2. riskfolio-lib小样本(20只)不稳定 — 需实测
3. VectorBT不支持PMS/涨跌停 — 仅适合初筛

---

## 4. 附录: 替代开源工具

| 工具 | 用途 | Windows | 状态 |
|------|------|---------|------|
| VectorBT | 向量化回测 | ✅ | 待评估 |
| alphalens-reloaded | 因子分析 | ✅ | 待评估 |
| riskfolio-lib | Portfolio优化 | ✅ | 安装验证中 |
| zipline-reloaded | 回测框架 | ⚠️ conda | 优先级低 |
