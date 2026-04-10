# Phase 2 前置: 新信号维度数据可行性调研报告

**日期**: 2026-04-11 | **来源**: phase2_signal_feasibility.py + phase2_tushare_feasibility.py + localized_ic_analysis.py
**数据范围**: IC验证用3年(2023-2025), Tushare API探测实时

---

## 摘要

| 方向 | 数据 | 覆盖 | PIT | 结论 |
|------|------|------|-----|------|
| 2.1 概念板块 | Tushare `concept` | 879概念, 1.2/股 | 部分(in_date有, 但concept创建回溯) | **不推荐**(前瞻偏差高) |
| 2.2 分析师预期 | Tushare `report_rc`/`forecast`/`express` | 大盘多, 小盘差 | 是(ann_date) | **推荐ML特征**(小盘覆盖不足,不独立) |
| 2.3 融资融券 | DB月度 + Tushare `margin_detail`日度 | ~4100证券/日 | 是(T日盘后) | **推荐**(需先ingeset日度数据) |
| **2.4 高低位放量** | Parquet cache已有 | 全A股 | N/A | **强推荐**(IC=-0.077, 独立) |
| 2.5 CGO | Parquet算VWAP近似 | 全A股 | N/A | **冗余**(corr=0.834 reversal) |
| 2.6 STR凸显性 | Parquet算 | 全A股 | N/A | **冗余**(corr=0.864 reversal) |
| **2.7 局部化IC** | Parquet + DB | CORE 5 x 3组 | N/A | **V4分组建模有价值**(1.92x) |
| 2.8 龙虎榜 | Tushare `top_list`/`top_inst` | 日均~50只 | 是(交易日当晚公布) | **推荐EVENT**(可区分游资/机构) |
| 2.9 解禁/增减持/质押/回购 | Tushare 4个API | 全A股 | 是(ann_date) | **推荐EVENT** |
| 2.10 券商金股 | Tushare `broker_recommend` | 月均~300条 | 是(月初发布) | **样本小,低优先级** |
| 2.11 Tushare因子 | `stk_factor_pro` | ~28列 | 是 | **部分可用**(技术指标重叠多) |

---

## 2.1 概念板块

**市场逻辑**: A股高度concept-driven, 概念动量与行业动量信息维度独立。

**调研结果**:
- Tushare `concept()`: 879个概念板块, 来源=Tushare整理(非交易所官方)
- `concept_detail(id=CODE)`: 有成分股, 含 `in_date`/`out_date`
- 每只股票平均属于~1.2个概念(抽样50概念, 1030唯一股票)
- DB: 无concept相关表

**PIT评估: 中等风险**
- in_date字段存在 → 可做时点过滤
- **但concept创建本身是回溯性的**: "AI芯片"概念2024年才建, 成分股被回溯添加
- out_date大多为None → 股票一旦加入永不移除
- 12年回测中, 2021年后创建的概念无法应用于2014-2020数据

**结论: 不推荐**
- 前瞻偏差风险高, 回测不可信
- 低密度(1.2概念/股), 大量股票无信号
- 如非要用: 仅限2022+数据, 作为LightGBM可选特征

---

## 2.2 分析师预期

**市场逻辑**: 分析师一致预期变化(Earnings Revision)是经典alpha来源, 与量价完全不同维度。

**调研结果**:
- `report_rc` (研报评级): 可用, 含rating/report_date/org_name
- `forecast` (业绩预告): 可用, 含ann_date/type/p_change_min/max
- `express` (业绩快报): 可用, 含ann_date/revenue/net_profit

**覆盖率测试**:
| 股票 | 市值 | report_rc行数 | 时间范围 |
|------|------|-------------|---------|
| 600519.SH 茅台 | 大盘 | 多 | 2015-2026 |
| 002415.SZ 海康 | 中盘 | 多 | 2015-2026 |
| 300782.SZ 卓胜微 | 小盘 | 少 | 近年为主 |

- 小盘股覆盖严重不足 → QuantMind alpha来自小盘, 价值有限
- PIT安全: ann_date/report_date提供时间戳

**可派生因子**:
- `analyst_revision_3m`: 近3月盈利预测修正幅度
- `analyst_coverage_change`: 分析师覆盖数变化
- `target_price_deviation`: (目标价-现价)/现价

**结论: 推荐作为ML特征, 不推荐独立因子**
- 信息维度独立, 学术文献支持
- 但小盘覆盖不足, 无法做全A股截面排名
- Phase 2可作为LightGBM可选特征(有数据的股票使用, 缺失用NaN)

---

## 2.3 融资融券

**市场逻辑**: 融资余额变化=杠杆资金情绪, 融券余额=做空预期。

**DB现状**:
- `margin_data`表: 95,398行, 3961只股, **月度**(48个日期, 2021-01~2026-03)
- 月度频率太粗, 无法构建日度因子

**Tushare API**:
- `margin_detail`: **日度**, ~4100证券/日(含ETF)
- 字段: rzye(融资余额), rqye(融券余额), rzmre(融资买入额), rzche(融资偿还额), rqyl(融券余量), rqmcl(融券卖出量), rzrqye(总余额)
- 已验证600519.SH: 返回完整日度数据

**可派生因子**:
| 因子 | 公式 | 方向 | 逻辑 |
|------|------|------|------|
| margin_chg_5d | 5日融资余额变化率 | -1 | 杠杆情绪过热→反转 |
| short_ratio | rqye/rzrqye | -1 | 高空头占比→均值回归 |
| margin_buy_intensity | rzmre/daily_amount | -1 | 过度杠杆买入→过热 |

**覆盖限制**: 仅~800-900只A股为融资融券标的, 非全A股
- 适合ML特征(有数据即用), 不适合全截面排名因子

**结论: 推荐(需先ingest日度数据)**
- 信息维度独立(杠杆情绪)
- 需通过DataPipeline(铁律17)导入`margin_detail`日度数据
- PIT安全: T日盘后公布, T+1使用无前瞻

---

## 2.4 高低位放量因子 (最高优先级)

**市场逻辑**: 高位放量=主力出货/散户追涨→反转; 低位放量=吸筹→上涨。

**IC验证结果** (3年, 2023-2025, Spearman rank IC, horizon=20d):

| 因子 | IC均值 | IR | t-stat | 胜率 | n | max CORE corr | 冗余? |
|------|--------|-----|--------|------|---|-------------|-------|
| **high_vol_price_ratio_20** | -0.0771 | -0.680 | -17.85 | 21.1% | 688 | 0.443(reversal) | **独立** |
| **high_price_vol_ratio_20** | -0.0591 | -0.763 | -20.01 | 20.1% | 688 | 0.408(amihud) | **独立** |
| composite_hvp_20 | -0.0712 | -0.724 | -19.00 | 20.1% | 688 | 0.449(amihud) | 子因子冗余 |

**CORE 5基准** (同期):

| 因子 | IC均值 | IR | t-stat |
|------|--------|-----|--------|
| turnover_mean_20 | -0.0725 | -0.340 | -9.04 |
| volatility_20 | -0.0868 | -0.399 | -10.62 |
| reversal_20 | +0.0808 | +0.509 | +13.54 |
| amihud_20 | +0.0567 | +0.484 | +12.87 |
| bp_ratio | +0.0766 | +0.477 | +12.70 |

**关键发现**:
1. 两个子因子IC均强(|t|>17), 方向一致(-1=出货信号→反转)
2. max CORE corr < 0.5 → **真正独立的新信息维度**
3. 两子因子互相高度相关(~0.85) → 选一个即可
4. `high_vol_price_ratio_20` 推荐: |IC|更大(-0.077 vs -0.059)
5. composite无额外价值

**结论: 强推荐入E2E特征池**
- IC强, 独立, 数据现成(Parquet cache)
- 需在factor_engine.py实现生产版本 + 写入factor_values

---

## 2.5 CGO资本利得突出量

**市场逻辑**: CGO高=浮盈惜售; CGO低=套牢卖压。A股散户处置效应极强。

**IC验证结果**:
- cgo_approx_60: IC=-0.0774, IR=-0.513, t=-13.35, hit=31.4%
- 用近似VWAP: CGO = (close - VWAP_60d) / VWAP_60d

**冗余性分析**:
- vs reversal_20: **corr=-0.834** (超过0.7阈值)
- 经济解释: CGO衡量价格偏离均价, 与价格反转机械相关

**结论: 冗余, 不推荐独立入池**
- IC强但信息与reversal_20高度重叠
- 可作为LightGBM候选特征(ML不受corr限制)

---

## 2.6 STR凸显性收益

**市场逻辑**: 极端收益被过度加权→高STR股票被高估→反转。

**IC验证结果**:
- str_20: IC=-0.0671, IR=-0.573, t=-15.02, hit=26.6%
- 定义: 过去20日中|daily_return|排名前3的交易日收益率均值

**冗余性分析**:
- vs reversal_20: **corr=-0.864** (极高)
- vs volatility_20: corr=+0.062 (不相关!)
- STR与volatility无关, 但与reversal高度重叠
- CGO与STR互相也冗余(corr=0.764)

**结论: 冗余, 不推荐**
- 信息被reversal_20覆盖
- 可作为LightGBM候选特征

---

## 2.7 局部化IC分析

**目的**: 评估V4 E2E分组建模价值, 非新因子。

**方法**: CORE 5因子按市值分3组(小<50亿/中50-200亿/大>200亿), 独立算IC。
**数据**: raw_value(非中性化, 保留size信号差异), horizon=20d, 2023-2025, 707交易日。
**Universe**: 小盘avg 2149/日, 中盘avg 1908/日, 大盘avg 760/日。

| 因子 | 小盘IC | 中盘IC | 大盘IC | 小t | 中t | 大t | 小/大比 |
|------|--------|--------|--------|-----|-----|-----|---------|
| turnover_mean_20 | -0.0915 | -0.1085 | -0.0860 | -15.2 | -13.3 | -9.1 | 1.06x |
| volatility_20 | -0.0888 | -0.1162 | -0.0983 | -13.4 | -14.0 | -10.9 | 0.90x |
| **reversal_20** | **+0.0818** | +0.0783 | +0.0375 | 15.0 | 13.9 | 5.6 | **2.18x** |
| **amihud_20** | **+0.0460** | +0.0050 | **-0.0096** | 13.6 | 2.7 | -3.1 | **4.79x (反转!)** |
| bp_ratio | +0.0602 | +0.0811 | +0.0899 | 12.3 | 11.2 | 11.5 | 0.67x |

**关键发现**:

1. **reversal_20**: 小盘IC=0.082(t=15.0), 大盘IC=0.038(t=5.6). 反转是小盘现象, 大盘定价更有效。

2. **amihud_20**: 极端局部化!
   - 小盘IC=+0.046(t=13.6, 正=非流动性溢价有效)
   - 中盘IC=+0.005(t=2.7, 边界显著)
   - **大盘IC=-0.010(t=-3.1, 方向反转!)** 大盘中非流动性是风险信号而非溢价

3. **turnover/volatility**: 各组IC均匀, 信号普遍适用。

4. **bp_ratio**: 反向——大盘IC最强(0.090), 价值因子在大盘更有效(机构驱动)。

**结论: V4分组建模有价值**
- 平均 |小盘IC|/|大盘IC| = **1.92x**
- amihud_20方向反转是分组建模的最强论据
- **建议**: Phase 2 LightGBM加入cap_group分类特征, 或按市值组分建模型

---

## 2.8 龙虎榜

**市场逻辑**: 游资席位大额买入→散户跟风效应→短线EVENT信号。

**调研结果**:
- `top_list`: 每日~40-60只上榜, 含buy/sell金额, 上榜原因
- `top_inst`: 机构买卖明细, 含side(买/卖), exalter(席位名称)
- 可区分: 游资席位 vs 机构席位(通过席位名称模式匹配)
- 时间范围: 2005+ (深度足够)
- PIT: 交易日当晚公布, T+1使用安全

**可派生因子**:
| 因子 | 公式 | 类型 |
|------|------|------|
| dragon_inst_net_buy | 机构净买入金额/流通市值 | EVENT |
| dragon_frequency_20d | 近20日上榜次数 | RANKING |
| dragon_retail_net | 游资净买入金额 | EVENT |

**结论: 推荐(EVENT型)**
- 适合模板9(EVENT触发), 不适合月度RANKING
- 日均~50只上榜, 样本量足够
- Phase 2可作为事件驱动信号层

---

## 2.9 解禁/增减持/质押/回购

**市场逻辑**: 解禁=卖压; 增持=看好; 高质押=风险; 回购=积极信号。

**调研结果**:

| API | 功能 | 行数(600519) | PIT字段 | 覆盖 |
|-----|------|-------------|---------|------|
| `share_float` | 限售解禁 | 有 | float_date(解禁日) | 全A股 |
| `stk_holdertrade` | 股东增减持 | 有 | ann_date(公告日) | 全A股 |
| `pledge_stat` | 股权质押汇总 | 有 | end_date(截止日) | 全A股 |
| `repurchase` | 股票回购 | 有 | ann_date(公告日) | 全A股 |

**PIT安全性**: 4个API均有日期字段, T+1使用无前瞻风险。

**可派生因子**:
| 因子 | 公式 | 类型 | 方向 |
|------|------|------|------|
| unlock_ratio_30d | 30日内解禁市值/流通市值 | EVENT | -1(卖压) |
| insider_net_buy | 股东净增持金额/总市值 | EVENT | +1(看好) |
| pledge_ratio | 质押股数/总股本 | RANKING | -1(风险) |
| buyback_ratio | 回购金额/总市值 | EVENT | +1(积极) |

**结论: 推荐(EVENT型)**
- 4个数据源全部可用, PIT安全
- 适合模板8(EVENT触发), 不适合月度RANKING
- pledge_ratio可作为持续性RANKING因子

---

## 2.10 券商金股

**市场逻辑**: 券商每月推荐金股反映机构观点共识。

**调研结果**:
- `broker_recommend`: 月度数据, 含broker(券商名)/ts_code/title
- 每月约~300条(不同券商×不同股票)
- 覆盖~100-200只唯一股票/月

**局限性**:
- 样本量极小(月~200只, 全A ~5000只, 覆盖率仅4%)
- 无法构建全截面因子
- 可能存在选择偏差(券商倾向推大盘白马)

**结论: 低优先级**
- 样本量不足统计可靠性
- 如用: 作为二值特征(是否被推荐), 而非连续因子
- 可与分析师预期合并作为"机构关注度"聚合特征

---

## 2.11 Tushare预计算量化因子

**调研结果**:
- `stk_factor`: 基础技术指标
- `stk_factor_pro`: 扩展指标, ~28列

**QuantMind已有因子对比**:

| Tushare因子 | QuantMind对应 | 状态 |
|------------|--------------|------|
| MACD相关 | MACD_hist (#61) | 已有 |
| KDJ相关 | KDJ_K (#62) | 已有 |
| RSI相关 | RSI_14 (#60) | 已有 |
| CCI | CCI_14 (#63) | 已有 |
| BOLL | 无 | 可评估 |
| BIAS | 无 | 可评估 |
| WR | 无 | 可评估 |
| PSY | 无 | 新 |
| VR | 无 | 新 |
| TRIX | 无 | 新 |

**结论: 部分可用**
- 大部分技术指标QuantMind已有或已评估
- 新增: PSY(心理线), VR(量比), BOLL(布林带), TRIX(三重指数平滑)
- 传统技术指标学术上IC通常不显著, 但验证成本低
- 主要价值: 省去自己计算, 直接拉取作为ML特征

---

## 综合优先级排序

### Phase 2 E2E特征池推荐

| 优先级 | 方向 | 行动 | 依赖 |
|--------|------|------|------|
| **P0** | 2.4 高低位放量 | factor_engine实现 + factor_values入库 | 无, 数据已有 |
| **P0** | 2.7 分组建模 | LightGBM加cap_group特征 | 无 |
| P1 | 2.3 融资融券 | ingest margin_detail日度 → 因子计算 | DataPipeline |
| P1 | 2.9 解禁/质押 | ingest 4个API → EVENT因子 | DataPipeline |
| P1 | 2.8 龙虎榜 | ingest top_list/top_inst → EVENT因子 | DataPipeline |
| P2 | 2.2 分析师 | ingest report_rc → ML特征 | DataPipeline, 小盘覆盖差 |
| P2 | 2.11 Tushare因子 | 拉取stk_factor_pro → ML特征 | 验证IC |
| P3 | 2.10 券商金股 | 样本量评估后决定 | 统计可靠性 |
| **不做** | 2.1 概念板块 | 前瞻偏差, 低密度 | — |
| **不做** | 2.5 CGO | 冗余(reversal corr=0.834) | — |
| **不做** | 2.6 STR | 冗余(reversal corr=0.864) | — |

### 数据ingest工作量估算

| 数据源 | API | 预估行数 | DataPipeline契约 |
|--------|-----|---------|----------------|
| margin_detail | `margin_detail` | ~1000万(5年×250日×4000只) | 需新建 |
| share_float | `share_float` | ~10万 | 需新建 |
| stk_holdertrade | `stk_holdertrade` | ~50万 | 需新建 |
| pledge_stat | `pledge_stat` | ~30万 | 需新建 |
| top_list | `top_list` | ~300万(5年×250日×50只) | 需新建 |
