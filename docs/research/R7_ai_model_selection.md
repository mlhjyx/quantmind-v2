# R7: AI模型选型研究报告 — AI闭环核心依赖

> **研究日期**: 2026-03-28
> **研究员**: QuantMind V2 Research
> **状态**: 完成
> **依赖**: R2(因子挖掘前沿), AI闭环设计(DESIGN_V5 Phase 1)

---

## 1. 问题定义: AI闭环的LLM需求

### 1.1 AI闭环架构回顾

QuantMind V2的AI闭环由4个Agent组成，每个Agent的LLM需求截然不同:

| Agent | 核心任务 | 关键LLM能力 | 调用频率 |
|-------|---------|-------------|---------|
| **Idea Agent** | 生成有经济学逻辑的因子假设 | 创造性推理、金融领域知识、中文理解 | 低(每轮1-3次) |
| **Factor Agent** | 将假设翻译为精确的pandas/numpy代码 | 代码生成准确性、一次通过率 | 中(每轮5-10次，含debug迭代) |
| **Eval Agent** | 统计评估(IC/t值/中性化/bootstrap) | 数值推理、统计学知识 | 中(每轮3-5次) |
| **Diagnosis Agent** | 分析失败原因，调整搜索方向 | 长上下文利用、根因分析、模式识别 | 低(每5-10轮1次) |

### 1.2 量化场景的特殊需求

与通用代码生成不同，量化因子代码有独特挑战:
- **pandas时间序列操作**: `groupby().apply()`, `rolling()`, `shift()`, `rank()` 的正确组合
- **截面 vs 时序操作混淆**: `cs_rank` vs `ts_rank` 是因子代码最常见的bug
- **中性化/标准化顺序**: MAD去极值 -> 填充 -> 中性化 -> zscore，顺序不可调
- **A股特殊规则**: 涨跌停板(10%/20%/5%/30%)、T+1、整手约束100股
- **中文金融术语**: "资金流向分歧度"、"RSRS标准分"等概念需要中文理解

### 1.3 Token消耗估算

典型因子挖掘单轮的prompt构成:

| 组件 | Token量 | 说明 |
|------|--------|------|
| 系统prompt(DSL+规则) | ~2,000 | 因子计算DSL、预处理规则 |
| 因子知识库(已有因子) | ~3,000 | 5个Active因子 + Reserve池描述 |
| 失败历史(避免重复) | ~4,000 | 近20轮失败因子摘要 |
| 搜索方向指令 | ~1,000 | Diagnosis Agent输出的方向 |
| 代码模板 | ~500 | 输出格式要求 |
| **总计(Input)** | **~10,500** | 单次调用 |
| **Output(因子代码+解释)** | **~1,500** | 含代码+经济学解释 |

每月200轮 x 每轮~150次LLM调用 = **30,000次调用/月**。
按平均10.5K input + 1.5K output tokens/次计算:
- **月Input**: ~315M tokens
- **月Output**: ~45M tokens

---

## 2. 候选模型详细评估

### 2.1 DeepSeek系列 (R1 / V3 / V3.1 / V3.2)

**基本信息**:
- V3: 671B参数(MoE), 164K上下文, HumanEval 82.6%
- V3.1: 推理增强版, 与GPT-5同级别性能
- V3.2: 2025年12月发布, 速度优化版
- R1: 专用推理模型, 数学/逻辑强项
- 公司背景: 幻方量化出身，天然具备金融领域基因

**定价(2026年3月)**:
- V3(deepseek-chat): $0.14/M input, $0.28/M output
- V3.2 Speciale: $0.40/M input, $1.20/M output
- R1: $0.55/M input, $2.19/M output

**量化场景评估**:
- 中文金融知识: **5/5** — DeepSeek在Chinese SimpleQA上超越GPT-4o和Claude Sonnet，中文事实性知识最强
- 代码生成: **4/5** — HumanEval 82.6%，Python/numpy/pandas操作准确
- 推理能力: **5/5**(R1) / **4/5**(V3) — R1在AIME数学推理中顶尖
- 金融领域: **5/5** — 幻方量化背景，论文"When DeepSeek-R1 meets financial applications"验证了金融场景表现
- 成本效率: **5/5** — 价格仅为GPT-5的1/10到1/50

**月度成本估算(V3)**:
- Input: 315M x $0.14/M = **$44.10**
- Output: 45M x $0.28/M = **$12.60**
- **月总计: ~$57**

**月度成本估算(R1, 用于Idea Agent)**:
- 假设Idea Agent占总调用10%: 31.5M input x $0.55 + 4.5M output x $2.19 = **$27.18**

**关键发现**: QuantaAlpha研究证实，DeepSeek-V3.2在因子挖掘中达到IC=0.1338，仅比GPT-5.2的0.1501低10.9%，但成本低10-50倍。**每个有效因子的成本是所有模型中最低的**。

### 2.2 Claude系列 (Opus 4.6 / Sonnet 4.6 / Haiku 4.5)

**基本信息**:
- Opus 4.6: 最强能力, 1M上下文
- Sonnet 4.6: 平衡性能与成本, 1M上下文
- Haiku 4.5: 快速响应, 成本最低

**定价(2026年3月)**:
- Opus 4.6: $5/M input, $25/M output
- Sonnet 4.6: $3/M input, $15/M output
- Haiku 4.5: $1/M input, $5/M output
- Prompt Caching可节省90%, Batch API再省50%

**量化场景评估**:
- 中文金融知识: **3/5** — 中文能力逊于DeepSeek/Qwen，但仍然可用
- 代码生成: **5/5** — 代码质量业界公认最高，逻辑严谨
- 推理能力: **5/5**(Opus) / **4/5**(Sonnet) — 深度分析能力极强
- 金融领域: **4/5** — 统计学/风控逻辑理解深刻，但A股特殊规则需要prompt引导
- 成本效率: **2/5** — Opus月成本>$1,000，即使Sonnet也需$500+

**月度成本估算(Sonnet 4.6, 无缓存)**:
- Input: 315M x $3/M = **$945**
- Output: 45M x $15/M = **$675**
- **月总计: ~$1,620**

**月度成本估算(Sonnet 4.6, 带Prompt Caching 90%)**:
- Input: 315M x $0.30/M = **$94.50**
- Output: 45M x $15/M = **$675**
- **月总计(优化后): ~$770**

**关键发现**: Claude的代码生成质量和深度分析能力无可比拟，但成本显著高于DeepSeek。适合用在需要最高精度的环节(Eval/Diagnosis)，不适合做高频调用的Factor Agent。

### 2.3 GPT系列 (GPT-5 / GPT-5.4 / GPT-5-mini)

**基本信息**:
- GPT-5.4: 当前旗舰, Intelligence Index 57.2(并列第一)
- GPT-5: 2025年8月发布, 1M上下文
- GPT-5-mini: 轻量版

**定价(2026年3月)**:
- GPT-5.4: $2.50/M input, $15/M output (Batch: $1.25/$7.50)
- GPT-5: $1.25/M input, $10/M output
- GPT-5-mini: $0.25/M input, $1/M output

**量化场景评估**:
- 中文金融知识: **3/5** — 中文能力可用但不是强项
- 代码生成: **5/5** — HumanEval/SWE-bench顶尖
- 推理能力: **5/5** — 全能型，工具调用最成熟
- 金融领域: **4/5** — 通用金融知识广泛，A股特定知识需补充
- 成本效率: **3/5** — 中等偏高

**月度成本估算(GPT-5)**:
- Input: 315M x $1.25/M = **$393.75**
- Output: 45M x $10/M = **$450**
- **月总计: ~$844**

**月度成本估算(GPT-5-mini)**:
- Input: 315M x $0.25/M = **$78.75**
- Output: 45M x $1/M = **$45**
- **月总计: ~$124**

**关键发现**: QuantaAlpha用GPT-5.2达到IC=0.1501是所有模型最高，但成本也是DeepSeek的10倍以上。GPT-5-mini的性价比值得关注(AlphaAgent论文表明GPT-3.5级即可做因子挖掘)。

### 2.4 Gemini 2.5 (Pro / Flash)

**基本信息**:
- 2.5 Pro: 1M上下文, 推理增强
- 2.5 Flash: 速度优先, 成本低

**定价(2026年3月)**:
- 2.5 Pro: $1.25/M input, $10/M output (>200K context加价)
- 2.5 Flash: $0.30/M input, $2.50/M output
- Context Caching可节省90%

**量化场景评估**:
- 中文金融知识: **3/5** — 中文一般
- 代码生成: **4/5** — 表现良好但不是最强项
- 推理能力: **4/5** — Pro推理能力强
- 金融领域: **3/5** — 通用知识，金融专精不足
- 成本效率: **4/5**(Flash) / **3/5**(Pro)

**月度成本估算(2.5 Flash)**:
- Input: 315M x $0.30/M = **$94.50**
- Output: 45M x $2.50/M = **$112.50**
- **月总计: ~$207**

**关键发现**: Gemini 2.5 Flash在AlphaLogics研究中被用作因子生成器之一，表现稳定。Flash的价格接近DeepSeek V3.2，但中文金融知识不如DeepSeek。Pro的1M上下文对Diagnosis Agent有价值。

### 2.5 Qwen3系列 (235B-A22B / 32B / 30B-A3B)

**基本信息**:
- 235B-A22B: 旗舰MoE模型, 60%激活参数超越DeepSeek-R1
- 32B: 密集模型, 性能=Qwen2.5-72B
- 30B-A3B: 小MoE, 仅3.3B激活参数, 超越QwQ-32B
- Qwen3-Coder-30B-A3B: 代码专精版, SWE-bench 50.3%

**定价(API, 2026年3月)**:
- 235B-A22B: 约$0.50/M input, $2/M output (通义千问/SiliconFlow)
- 32B/30B-A3B: 约$0.10-0.20/M input, $0.30-0.60/M output
- **本地部署: 边际成本趋近于零**(仅电费+硬件折旧)

**量化场景评估**:
- 中文金融知识: **5/5** — 中文原生训练, A股知识最全面
- 代码生成: **4/5** — 235B在LiveCodeBench v5达70.7
- 推理能力: **5/5**(235B) / **4/5**(32B) — AIME'25达81.5
- 金融领域: **4/5** — 中文金融语料丰富，但专用金融benchmark数据有限
- 成本效率: **5/5**(本地) / **4/5**(API) — 本地部署近乎免费

**本地部署评估(RTX 5070 12GB)**:
- Qwen3-32B(密集): Q4_K_M量化 ~18GB, **超出12GB VRAM, 需CPU offload, 不推荐**
- Qwen3-30B-A3B(MoE): 仅3.3B激活参数, Q4量化~8-10GB, **可在12GB内运行**
- Qwen3-Coder-30B-A3B: 同上, Q4量化可装入12GB VRAM
- 推理速度: ~12 tok/s(6-bit量化, 12GB VRAM, 类似规格GPU实测)

**关键发现**: Qwen3-30B-A3B是RTX 5070 12GB上的最佳本地选择 -- MoE架构仅激活3.3B参数，Q4量化可完全装入VRAM。Qwen3-Coder-30B-A3B是本地Factor Agent的理想选择。

### 2.6 Llama 4 (Scout / Maverick)

**基本信息**:
- Scout: 16专家MoE, 10M token上下文(!), 开源
- Maverick: 128专家MoE, 代码/推理接近GPT-5.3

**定价(API)**:
- Maverick: ~$0.20-0.50/M input (各平台不同)
- Scout: ~$0.10-0.25/M input
- 本地部署: Scout需要大量资源(10M context), Maverick需多卡

**量化场景评估**:
- 中文金融知识: **2/5** — Meta模型中文训练数据较少
- 代码生成: **4/5** — Maverick在HumanEval/SWE-bench接近GPT-5.3
- 推理能力: **4/5**(Maverick) / **3/5**(Scout)
- 金融领域: **2/5** — 西方市场偏向，A股规则理解弱
- 成本效率: **4/5**(API) — 开源，价格有竞争力

**关键发现**: Llama 4在中文金融领域的短板使其不适合作为QuantMind的主力模型。Maverick的代码能力值得关注，但中文因子假设生成不如DeepSeek/Qwen。

### 2.7 Grok 4系列 (Grok 4 / 4.1 Fast)

**基本信息**:
- Grok 4: 旗舰推理模型, 2M token上下文
- Grok 4.1 Fast: 性价比版, 质量接近Grok 4

**定价(2026年3月)**:
- Grok 4: $3/M input, $15/M output
- Grok 4.1 Fast: $0.20/M input, $0.50/M output

**量化场景评估**:
- 中文金融知识: **2/5** — 中文能力是短板
- 代码生成: **4/5** — HumanEval表现良好
- 推理能力: **5/5** — Grok 4达到frontier级别(quality=65)
- 金融领域: **3/5** — 一般水平
- 成本效率: **5/5**(4.1 Fast) — 价格极低

**月度成本估算(4.1 Fast)**:
- Input: 315M x $0.20/M = **$63**
- Output: 45M x $0.50/M = **$22.50**
- **月总计: ~$86**

**关键发现**: Grok 4.1 Fast的价格几乎与DeepSeek V3持平，但中文金融知识远逊。不推荐作为主力，但可作为代码生成的备选。

---

## 3. 横向对比矩阵

### 3.1 评分表(1-5分, 5=最优)

| 模型 | 因子代码生成(25%) | 金融领域知识(20%) | 推理/假设生成(15%) | 成本效率(20%) | 上下文窗口(10%) | 延迟(5%) | 本地部署(5%) | **加权总分** |
|------|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| **DeepSeek V3** | 4 | 5 | 4 | 5 | 4 | 4 | 1 | **4.30** |
| **DeepSeek R1** | 3 | 5 | 5 | 4 | 4 | 3 | 1 | **3.95** |
| **DeepSeek V3.2** | 4 | 5 | 4 | 5 | 4 | 5 | 1 | **4.35** |
| Claude Sonnet 4.6 | 5 | 4 | 4 | 2 | 5 | 4 | 1 | **3.65** |
| Claude Opus 4.6 | 5 | 4 | 5 | 1 | 5 | 3 | 1 | **3.45** |
| GPT-5 | 5 | 4 | 5 | 3 | 5 | 4 | 1 | **4.00** |
| GPT-5-mini | 3 | 3 | 3 | 4 | 4 | 5 | 1 | **3.30** |
| Gemini 2.5 Flash | 4 | 3 | 3 | 4 | 5 | 5 | 1 | **3.60** |
| Gemini 2.5 Pro | 4 | 3 | 4 | 3 | 5 | 3 | 1 | **3.45** |
| **Qwen3-235B** | 4 | 5 | 5 | 4 | 4 | 3 | 1 | **4.15** |
| Qwen3-32B | 4 | 5 | 4 | 4 | 3 | 3 | 2 | **3.90** |
| **Qwen3-30B-A3B** | 4 | 4 | 4 | 5 | 3 | 4 | 5 | **4.15** |
| Qwen3-Coder-30B | 5 | 3 | 3 | 5 | 3 | 4 | 5 | **4.00** |
| Llama 4 Maverick | 4 | 2 | 4 | 4 | 5 | 4 | 1 | **3.35** |
| Grok 4.1 Fast | 4 | 2 | 4 | 5 | 5 | 5 | 1 | **3.60** |

### 3.2 Top 5 模型(按加权总分)

1. **DeepSeek V3.2** (4.35) — 综合最优，成本极低，中文金融知识最强
2. **DeepSeek V3** (4.30) — 与V3.2接近，价格更低
3. **Qwen3-235B-A22B** (4.15) — 推理最强的开源模型，中文一流
4. **Qwen3-30B-A3B** (4.15) — 本地部署加分，MoE架构高效
5. **GPT-5** (4.00) — 综合能力最强，成本中等偏高

---

## 4. Agent角色-模型匹配推荐

### 4.1 推荐方案: 混合模型架构

```
┌─────────────────────────────────────────────────────────┐
│                    AI闭环 — 模型分配                       │
├──────────────┬──────────────────────┬───────────────────┤
│ Idea Agent   │ DeepSeek-R1          │ 创造性推理+中文金融  │
│              │ (备选: Qwen3-235B)    │ 知识最强组合        │
├──────────────┼──────────────────────┼───────────────────┤
│ Factor Agent │ Qwen3-Coder-30B     │ 本地部署零API成本    │
│  (代码生成)   │ (本地RTX 5070)       │ 代码专精+中文理解    │
│              │ 退化: DeepSeek-V3    │ 复杂代码API兜底     │
├──────────────┼──────────────────────┼───────────────────┤
│ Eval Agent   │ DeepSeek-V3.2       │ 统计分析+成本平衡    │
│  (统计评估)   │                      │ 金融统计理解准确     │
├──────────────┼──────────────────────┼───────────────────┤
│ Diagnosis    │ DeepSeek-R1          │ 需要深度推理+长上下文 │
│  Agent       │ (备选: Claude Sonnet) │ 根因分析能力关键     │
└──────────────┴──────────────────────┴───────────────────┘
```

### 4.2 各Agent的模型特性需求详解

**Idea Agent (创造性假设生成)**
- 需要: 创造性推理 > 代码准确性
- 关键: 能否提出**有经济学逻辑**的新因子(不只是组合已有算子)
- 推荐: **DeepSeek-R1** — 推理能力顶尖 + 中文金融知识无敌组合
- 理由: R1的chain-of-thought推理让它能从经济学第一性原理出发思考
- 备选: Qwen3-235B(推理同级别，中文同样强)

**Factor Agent (精确代码生成)**
- 需要: 代码一次通过率 > 其他一切
- 关键: pandas groupby/rolling/shift操作不出错，dtype处理正确
- 推荐: **Qwen3-Coder-30B-A3B (本地部署)** — 零API成本 + 代码专精
- 理由: MoE架构仅3.3B激活参数，RTX 5070可流畅运行；SWE-bench 50.3%
- 退化策略: 复杂逻辑(多表join/复杂时序操作)退化到DeepSeek-V3 API
- 本地推理速度: ~12 tok/s，生成一段因子代码(~500 tokens)约需40秒，可接受

**Eval Agent (统计评估分析)**
- 需要: 数值推理准确性 + 统计学知识
- 关键: IC解读、t检验、bootstrap CI、过拟合判断
- 推荐: **DeepSeek-V3.2** — 速度快 + 统计理解 + 极低成本
- 理由: Eval调用频率中等，V3.2的速度优化减少pipeline延迟
- 备选: DeepSeek-V3(更便宜，速度稍慢)

**Diagnosis Agent (根因分析)**
- 需要: 长上下文利用 + 深度推理
- 关键: 综合多轮失败历史，识别系统性问题，调整搜索方向
- 推荐: **DeepSeek-R1** — 推理深度 + 合理成本
- 理由: Diagnosis是低频高价值调用，R1的推理深度在此发挥最大价值
- 备选: Claude Sonnet 4.6(分析能力更强，但成本高5-10倍)

### 4.3 为什么不全用最强模型？

| 方案 | 月成本 | IC(估) | 每有效因子成本 |
|------|--------|--------|--------------|
| 全GPT-5.4 | ~$2,700 | 0.1501 | $270/因子 |
| 全Claude Sonnet | ~$1,620 | ~0.14 | $162/因子 |
| 全DeepSeek V3 | ~$57 | 0.1338 | $5.7/因子 |
| **推荐混合方案** | **~$95** | **~0.13-0.14** | **$9.5/因子** |

推荐方案的IC预期仅比全GPT-5.4低~10%，但成本低28倍。考虑到因子挖掘是概率游戏(每10个因子可能只有1个通过t>2.5的门槛)，**降低每次尝试的成本远比微幅提升单次IC更有价值**。

---

## 5. 本地部署方案评估

### 5.1 RTX 5070 12GB + 32GB系统内存

| 模型 | 量化 | VRAM占用 | 推理速度 | 可行性 |
|------|------|---------|---------|--------|
| Qwen3-8B | Q4_K_M | ~5GB | ~30 tok/s | 完全可行，余量充足 |
| **Qwen3-30B-A3B** | Q4_K_M | ~8-10GB | ~12 tok/s | **推荐 — MoE仅3.3B激活** |
| **Qwen3-Coder-30B-A3B** | Q4_K_M | ~8-10GB | ~12 tok/s | **推荐 — 代码专精版** |
| Qwen3-32B(密集) | Q4_K_M | ~18GB | 需CPU offload | 不推荐，性能严重下降 |
| Qwen2.5-Coder-32B | Q4_K_M | ~18GB | 需CPU offload | 不推荐 |
| DeepSeek-R1(671B) | - | >200GB | - | 不可能本地运行 |

### 5.2 推荐本地部署架构

```
工具链: Ollama + Qwen3-Coder-30B-A3B (Q4_K_M)
VRAM: ~9GB (剩余~3GB给系统+偶发峰值)
系统RAM: ~16GB模型缓存 + 8GB给OS + 8GB给Python/PG/Redis
Context: 建议限制在8K tokens以内(避免VRAM溢出到RAM)
吞吐: ~12 tok/s, 生成500 token代码约40秒
```

**部署步骤**:
1. 安装Ollama for Windows
2. `ollama pull qwen3-coder:30b-a3b-q4_K_M`
3. 通过Ollama HTTP API (`localhost:11434`) 集成到Factor Agent
4. 设置超时: 120秒/请求(防止卡死)
5. 退化逻辑: 本地生成代码 -> 运行测试 -> 失败2次 -> 切换DeepSeek-V3 API

### 5.3 本地 vs API的决策矩阵

| 场景 | 选择 | 理由 |
|------|------|------|
| 简单因子代码(单因子/单算子) | 本地Qwen3-Coder | 零成本，40秒可接受 |
| 复杂因子代码(多表join/条件逻辑) | DeepSeek-V3 API | 精度更高，避免本地量化损失 |
| 创造性假设 | DeepSeek-R1 API | 本地模型推理能力不足 |
| 统计分析解读 | DeepSeek-V3.2 API | 需要完整模型精度 |
| 深度诊断 | DeepSeek-R1 API | 推理链长，本地模型无法胜任 |

---

## 6. 成本分析

### 6.1 月度预算对比(200轮 x 150次调用/轮)

| 方案 | Idea Agent | Factor Agent | Eval Agent | Diagnosis Agent | **月总计** |
|------|-----------|-------------|-----------|----------------|-----------|
| **A: 全DeepSeek V3** | $6 | $28 | $17 | $6 | **$57** |
| **B: 混合推荐** | $14(R1) | $5(本地)+$8(API退化) | $17(V3.2) | $7(R1) | **$51** |
| C: DeepSeek R1 + V3 | $27(R1) | $28(V3) | $17(V3) | $14(R1) | **$86** |
| D: 全GPT-5 | $79 | $394 | $236 | $79 | **$788** |
| E: 全Claude Sonnet | $95 | $472 | $283 | $95 | **$945** |
| F: 全GPT-5.4 | $158 | $787 | $472 | $158 | **$1,575** |

### 6.2 推荐方案(B)成本明细

```
Idea Agent:
  DeepSeek-R1, 占总调用5% (1,500次/月)
  Input: 15.75M x $0.55/M = $8.66
  Output: 2.25M x $2.19/M = $4.93
  小计: $13.59

Factor Agent:
  本地Qwen3-Coder-30B, 占总调用60% (18,000次/月)
  成本: 电费约$3/月 (RTX 5070 TDP 250W, 每天2小时推理)
  API退化(20%请求失败后切DeepSeek-V3): 3,600次
  Input: 37.8M x $0.14/M = $5.29
  Output: 5.4M x $0.28/M = $1.51
  小计: $9.80

Eval Agent:
  DeepSeek-V3.2, 占总调用25% (7,500次/月)
  Input: 78.75M x $0.14/M = $11.03
  Output: 11.25M x $0.28/M = $3.15
  小计: $14.18 (V3.2 Speciale价格略高则~$42)

Diagnosis Agent:
  DeepSeek-R1, 占总调用10% (3,000次/月)
  Input: 31.5M x $0.55/M = $17.33
  Output: 4.5M x $2.19/M = $9.86
  小计: $27.19
  注: 实际Diagnosis频率低于10%, 这里按上限估算

总计: ~$65-95/月 (取决于V3 vs V3.2选择和退化比例)
```

### 6.3 成本敏感性分析

| 变量 | 基准 | 乐观 | 悲观 |
|------|------|------|------|
| 月轮次 | 200 | 100 | 400 |
| 本地退化率 | 20% | 10% | 40% |
| R1使用比例 | 15% | 5% | 25% |
| **月成本** | **$75** | **$30** | **$180** |

即使在悲观情况下(400轮/月, 40%退化), 月成本仍<$200, 远低于纯API方案。

---

## 7. 推荐方案: 分层混合模型架构

### 7.1 架构总览

```
                        ┌──────────────────┐
                        │  Orchestrator    │
                        │  (Python逻辑)     │
                        └────────┬─────────┘
                 ┌───────────────┼───────────────┐
                 │               │               │
         ┌───────┴──────┐ ┌─────┴──────┐ ┌──────┴──────┐
         │ 创造性层      │ │ 执行层     │ │ 分析层      │
         │ DeepSeek-R1  │ │ 本地Qwen3  │ │ DeepSeek    │
         │ API          │ │ -Coder     │ │ V3/V3.2 API │
         │              │ │ RTX 5070   │ │             │
         │ Idea Agent   │ │ Factor     │ │ Eval Agent  │
         │ Diagnosis    │ │ Agent      │ │             │
         └──────────────┘ └────────────┘ └─────────────┘
```

### 7.2 模型选择决策树

```python
def select_model(agent_role: str, task_complexity: str) -> str:
    if agent_role == "idea":
        return "deepseek-r1"  # 创造性推理

    elif agent_role == "factor":
        if task_complexity == "simple":
            return "local:qwen3-coder-30b-a3b"  # 本地零成本
        else:
            return "deepseek-chat"  # V3 API兜底

    elif agent_role == "eval":
        return "deepseek-chat"  # V3/V3.2 统计分析

    elif agent_role == "diagnosis":
        if task_complexity == "deep":
            return "deepseek-reasoner"  # R1深度推理
        else:
            return "deepseek-chat"  # V3常规诊断
```

### 7.3 关键设计原则

1. **DeepSeek作为主力生态**: 幻方量化背景决定了其在金融场景的天然优势，中文知识最强，成本最低
2. **本地模型降低边际成本**: Factor Agent是调用量最大的角色(60%)，本地部署将最大头成本降为零
3. **按需升级而非默认最强**: R1仅用于需要深度推理的场景(Idea/Diagnosis)，不浪费在常规任务上
4. **退化策略保证质量下限**: 本地模型失败自动切API，不牺牲因子质量
5. **避免供应商锁定**: DeepSeek API兼容OpenAI SDK，可无缝切换到其他模型

### 7.4 与R2结论的一致性验证

R2研究结论: QuantaAlpha用DeepSeek-V3.2达IC=0.1338(vs GPT-5.2的0.1501)，成本低10-50倍。

本方案验证:
- IC预期: 0.13-0.14(与R2一致，混合方案可能通过R1的推理能力略微提升Idea质量)
- 成本: $65-95/月 vs 全GPT-5的$788/月 = **成本低8-12倍**
- 每有效因子成本: ~$6.5-9.5(假设10%通过率，每月产出~10个有效因子)

---

## 8. 落地计划: Benchmark实验设计

### 8.1 Phase 1: 模型基准测试 (1周)

**实验1: 因子代码生成质量测试**
```
测试集: 5个已验证因子(turnover_mean_20/volatility_20/reversal_20/amihud_20/bp_ratio)
方法: 给每个模型相同的因子描述prompt，评估生成代码的:
  - 一次通过率(代码能否直接运行)
  - 正确性(与已有实现的输出值相关性>0.99)
  - 代码质量(类型注解/边界处理/效率)
模型: DeepSeek-V3, DeepSeek-R1, Qwen3-Coder-30B(本地), GPT-5-mini
每个模型跑3次取平均
```

**实验2: 因子假设生成质量测试**
```
测试集: 给定知识库(5 Active因子 + 失败历史)，要求生成新因子假设
评估:
  - 经济学逻辑合理性(人工评审1-5分)
  - 与已有因子正交性(相关性<0.5)
  - 可实现性(能否用现有数据计算)
模型: DeepSeek-R1, Qwen3-235B, Claude Sonnet 4.6, GPT-5
每个模型生成10个假设
```

**实验3: 统计分析准确性测试**
```
测试集: 给定因子IC/t统计量/回测结果，要求模型判断:
  - 因子是否显著(t>2.5?)
  - 是否过拟合(IS vs OOS差异?)
  - 建议下一步动作
评估: 与人工判断的一致性
模型: DeepSeek-V3.2, Claude Sonnet 4.6, GPT-5
```

### 8.2 Phase 2: 端到端Pipeline测试 (2周)

```
目标: 用推荐混合方案跑完整因子挖掘pipeline
  - 20轮因子挖掘(每轮~150次LLM调用)
  - 记录: 每轮耗时/成本/生成因子数/通过Gate的因子数
  - 对比基线: 同样20轮用纯DeepSeek-V3的结果

成功标准:
  - 通过率 >= 纯DeepSeek-V3方案的80%
  - 总成本 <= 纯DeepSeek-V3方案的150%
  - 无pipeline中断(本地模型退化正常工作)
```

### 8.3 Phase 3: 长期运行验证 (持续)

```
月度Review:
  - 各模型调用量/成本追踪
  - 本地模型退化率监控(目标<20%)
  - 有效因子产出率(目标>5%通过t>2.5)
  - API价格变动追踪(2026年降价频繁)

季度Review:
  - 重评模型选择(新模型发布后)
  - 调整本地/API比例
  - 评估是否需要升级GPU(5070 Ti 16GB?)
```

---

## 9. 风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| DeepSeek API服务不稳定 | 中 | 高 | 备选: Qwen3-235B API(SiliconFlow/阿里云) |
| 本地Qwen3-Coder代码质量不足 | 中 | 中 | 退化到DeepSeek-V3 API，监控退化率 |
| RTX 5070 VRAM不够(模型更新变大) | 低 | 中 | Qwen3-8B作为降级选项；或升级5070 Ti |
| DeepSeek大幅涨价 | 低 | 中 | 切换Qwen3-235B API或增加本地部署比例 |
| 因子挖掘IC低于预期 | 中 | 高 | 增加R1使用比例，尝试AlphaLogics市场逻辑约束 |
| 中国AI政策变化影响API可用性 | 低 | 高 | 保留GPT-5-mini / Gemini Flash作为国际备选 |
| 量化损失导致本地模型幻觉 | 中 | 中 | 所有本地生成代码必须通过自动化测试Gate |

### 9.1 单点故障防护

```
主力(DeepSeek) 不可用 → 备选1(Qwen3 API) → 备选2(Gemini Flash) → 备选3(GPT-5-mini)
本地模型崩溃 → 全切API模式(成本增加~$30/月)
```

---

## 10. 参考文献

1. **QuantaAlpha**: "An Evolutionary Framework for LLM-Driven Alpha Mining" — [arXiv 2602.07085](https://arxiv.org/abs/2602.07085) — DeepSeek-V3.2 IC=0.1338, GPT-5.2 IC=0.1501
2. **AlphaLogics**: "A Market Logic-Driven Multi-Agent System for Scalable and Interpretable Alpha Factor Generation" — [arXiv 2603.20247](https://arxiv.org/abs/2603.20247) — 多Agent因子生成，测试GPT-3.5/DeepSeek-V3/Gemini-Flash
3. **AlphaBench**: "Benchmarking Large Language Models in Formulaic Alpha Factor Mining" — [OpenReview](https://openreview.net/forum?id=d97Q8r7ZKZ) — 首个LLM因子挖掘系统评测
4. **AlphaAgent**: "LLM-Driven Alpha Mining with Regularized Exploration" — [arXiv 2502.16789](https://arxiv.org/html/2502.16789v2) — GPT-3.5级LLM即可做因子挖掘
5. **DeepSeek金融评测**: "When DeepSeek-R1 meets financial applications" — [Springer](https://link.springer.com/article/10.1631/FITEE.2500227)
6. **Qwen3技术报告**: [arXiv 2505.09388](https://arxiv.org/pdf/2505.09388) — 235B-A22B在17/23 benchmark超越DeepSeek-R1
7. **DeepSeek API定价**: [pricepertoken.com](https://pricepertoken.com/pricing-page/provider/deepseek) — V3 $0.14/$0.28, R1 $0.55/$2.19
8. **Claude API定价**: [Anthropic官方](https://platform.claude.com/docs/en/about-claude/pricing) — Sonnet 4.6 $3/$15, Opus 4.6 $5/$25
9. **GPT-5定价**: [OpenAI官方](https://openai.com/api/pricing/) — GPT-5 $1.25/$10, GPT-5.4 $2.50/$15
10. **Gemini定价**: [Google AI](https://ai.google.dev/gemini-api/docs/pricing) — Flash $0.30/$2.50, Pro $1.25/$10
11. **Grok定价**: [xAI Docs](https://docs.x.ai/developers/models) — Grok 4.1 Fast $0.20/$0.50
12. **Llama 4性能**: [Meta AI Blog](https://ai.meta.com/blog/llama-4-multimodal-intelligence/) — Maverick接近GPT-5.3
13. **Qwen3本地部署**: [Ollama VRAM Guide](https://localllm.in/blog/ollama-vram-requirements-for-local-llms) — 30B-A3B可在12GB运行
14. **DeepSeek-V3.2对比GPT-5**: [Introl Blog](https://introl.com/blog/deepseek-v3-2-open-source-ai-cost-advantage) — 性能匹配GPT-5，成本低10倍

---

## 附录A: 快速决策参考

**如果只看一个结论**: 用DeepSeek(R1推理+V3执行)作为API主力 + Qwen3-Coder-30B作为本地Factor Agent，月成本$65-95，预期IC~0.13-0.14。

**如果预算无限**: 全用Claude Opus 4.6 + GPT-5.4交叉验证，但实证表明IC提升仅10-15%，不改变因子挖掘的根本概率游戏性质。

**如果要最低成本**: 全用DeepSeek-V3($57/月) + 本地Qwen3-Coder(Factor Agent零成本)，月成本可压到$30-40。

## 附录B: 2026年3月API价格速查表

| 模型 | Input ($/M tok) | Output ($/M tok) | 上下文 |
|------|:-:|:-:|:-:|
| DeepSeek-V3 | 0.14 | 0.28 | 164K |
| DeepSeek-V3.2 | 0.40 | 1.20 | 164K |
| DeepSeek-R1 | 0.55 | 2.19 | 164K |
| Claude Haiku 4.5 | 1.00 | 5.00 | 1M |
| Claude Sonnet 4.6 | 3.00 | 15.00 | 1M |
| Claude Opus 4.6 | 5.00 | 25.00 | 1M |
| GPT-5-mini | 0.25 | 1.00 | 1M |
| GPT-5 | 1.25 | 10.00 | 1M |
| GPT-5.4 | 2.50 | 15.00 | 1M |
| Gemini 2.5 Flash | 0.30 | 2.50 | 1M |
| Gemini 2.5 Pro | 1.25 | 10.00 | 1M |
| Grok 4.1 Fast | 0.20 | 0.50 | 2M |
| Grok 4 | 3.00 | 15.00 | 2M |
| Qwen3-235B (API) | ~0.50 | ~2.00 | 128K |
| Qwen3-30B-A3B (API) | ~0.15 | ~0.50 | 128K |
| Qwen3-Coder-30B (本地) | 0 | 0 | 8-32K |
