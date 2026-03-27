# QuantMind V2 — 前端 UI 详细开发文档

> 文档级别：实现级（供 Claude Code / Figma 设计执行）
> 创建日期：2026-03-19，更新：2026-03-20
> 关联文档：DEV_BACKTEST_ENGINE.md, DEV_AI_EVOLUTION.md, DEV_PARAM_CONFIG.md, DEV_BACKEND.md
> Figma原型：figma.com/make/tU2hHxkJ2nQSWeIumwZAGc
> 页面总数：12个导航页面（总览含A股/外汇详情子视图 + 回测5 + 因子4 + AI 2 + 系统设置1）
> API 端点：~57个（A股48 + 外汇9）| WebSocket通道：5个
> 章节：§一-十三(设计规范) + §十四(Figma审查改进清单,15项)

---

## 一、前端技术选型与 UI 风格

### 1.1 技术栈

| 项 | 选型 | 理由 |
|----|------|------|
| 框架 | React 18+ | 组件化、生态成熟 |
| 样式 | Tailwind CSS + shadcn/ui | 快速开发 + 高质量组件 |
| 图表(复杂) | ECharts | K线/热力图/树状图全支持 |
| 图表(简单) | Recharts | React原生、指标卡迷你图 |
| 代码编辑器 | Monaco Editor | VS Code同款 |
| 状态管理 | Zustand | 轻量 |
| 路由 | React Router v6 | — |
| 请求 | Axios + React Query | 缓存+自动重试 |
| WebSocket | socket.io-client | 回测/挖掘进度推送 |

### 1.2 UI 风格: Glassmorphism 毛玻璃金融风

设计稿来源: Figma（独立设计，本文档提供功能规格）

核心视觉特征:
- 深色底色 + 毛玻璃卡片(backdrop-filter: blur)
- 微渐变背景光晕（蓝紫色系点缀）
- 卡片半透明边框 + 内发光
- 圆角 12-16px
- 数据密集但不拥挤

### 1.3 涨跌颜色: 可配置

| 模式 | 涨 | 跌 | 适用 |
|------|----|----|------|
| A股惯例(默认) | 红 #ef4444 | 绿 #22c55e | 国内用户 |
| 国际惯例 | 绿 #22c55e | 红 #ef4444 | 海外用户 |

注意: 指标卡"达标"始终绿、"预警"始终红，不跟随涨跌色。

### 1.4 图表库分工

| 场景 | 库 |
|------|----|
| K线/热力图/相关性矩阵/IC时序/分组净值 | ECharts |
| 指标卡迷你图/行业分布柱状图/饼图/GP进化曲线 | Recharts |

### 1.5 全局布局

左侧导航栏(固定) + 右侧内容区(自适应)
- 展开态: 图标+文字 180px, 折叠态: 仅图标 56px
- 导航项: 📊总览 / ⚡策略工作台 / 🔬回测分析 / 🧬因子库 / ⛏️因子挖掘 / 🤖AI闭环 / ⚙️系统设置

### 1.6 主题: 深色为主，支持切换浅色（CSS变量方案）

---

## 二、回测模块页面（5个）

> 后端架构详见 DEV_BACKTEST_ENGINE.md

### 2.1 页面①: 策略工作台 (Strategy Workspace)

布局: 左中右三栏

左栏(200px) — 因子面板:
- 34因子按类别折叠(价量12/流动性6/资金流6/基本面8/市值1/行业1)
- checkbox勾选启用，悬浮迷你摘要(IC/IR/方向)
- 拖拽排序，底部"+ 自定义因子"入口，顶部搜索框

中央(flex-1) — 策略编辑区(双模式):
- 顶部切换: [可视化模式] [代码模式]
- 可视化: 流程图(因子选择→预处理→合成→过滤→持仓构建)，节点可点击配置
- 代码: Monaco Editor, Python语法高亮+自动补全+策略模板
- 顶部操作: [保存] [▶ 运行回测]

底部 — 资金量约束提示:
- 条件: initial_capital / holding_count < max_stock_price × 100
- 黄色警告条: "⚠️ 初始资金¥100,000/持仓30只=单只约¥3,333，部分高价股无法买满1手"
- 动态计算，配置变更时实时更新

右栏(260px) — AI助手:
- 对话式交互，功能: 生成策略/优化/解释/诊断
- [应用建议] [解释策略] [优化建议] 快捷按钮
- API: POST /api/ai/strategy-assist

### 2.2 页面②: 回测配置面板 (Backtest Config)

布局: 6个Tab + 底部 [取消] [▶ 运行回测]

Tab 1 — 市场/股票池:
- 市场(radio): A股 / 外汇(Phase 2, disabled)
- 股票池(radio): 全A股/沪深300/中证500/中证1000/创业板/科创板/按行业/自定义
- 按行业→多选下拉(申万31行业), 自定义→上传CSV/手动输入
- 预估股票数实时显示

Tab 2 — 时间段:
- 快捷: [近1年] [近3年] [近5年] [全部] [自定义]
- 排除特殊时期(checkbox): 2015股灾/2020疫情/自定义
- 市场状态分析开关 + 判定方法(均线法/回撤法)

Tab 3 — 执行参数:
- 成交价(radio): 次日开盘/次日VWAP
- 调仓频率+信号日, 持仓数量(滑块10-50), 权重方式

Tab 4 — 成本模型:
- 佣金/印花税/过户费输入框
- 滑点模型(radio)+Volume-impact参数(折叠), 成交量上限

Tab 5 — 风控/高级:
- 行业/单股上限(滑块), 未成交处理(radio)
- Walk-Forward开关+窗口参数
- 配置模板: [保存] [加载] [恢复默认], 预估耗时

Tab 6 — 动态仓位(新增):
- ☑ 启用动态仓位
- 仓位信号(下拉): 指数20d均值动量/中位数/breadth
- 满仓/半仓/空仓阈值, 信号平滑天数
- 仓位切换成本预估

### 2.3 页面③: 回测运行监控 (Backtest Runner)

- 进度条+百分比+预估剩余时间
- WF模式显示当前窗口
- 实时指标+净值曲线(ECharts动态追加)
- 运行日志(时间戳+事件)
- WS: /ws/backtest/{run_id}
- [取消回测] [后台运行]

### 2.4 页面④: 回测结果分析 (Backtest Results)

顶部指标卡(横排): 年化/Sharpe/DSR/MDD/Calmar/年换手/扣费收益/WF-OOS Sharpe
阈值色标: 🟢达标 🟡注意 🔴预警

8个Tab:
1. 净值曲线: 策略vs基准+超额+回撤+时间选择器+仓位水位线(动态仓位时)
2. 月度归因: 热力图+分年度表+行业归因+因子归因
3. 持仓分析: 持仓列表+集中度+行业分布时序+市值分布
4. 交易明细: 交易列表(可筛选)+成本分解+拒单记录+导出CSV
5. WF分析: 窗口OOS Sharpe+全量vs WF+因子稳定性+过拟合评估
6. 参数敏感性: 选参数→批量回测→折线图(Sharpe/MDD vs参数值)
7. 实盘对比: 回测vs实盘双线+衰减率+衰减归因+持仓差异+衰减>30%警告
8. 仓位分析(新增): 切换时间表+各仓位状态收益+切换成本+水位时序

底部: [修改重跑] [复制策略] [导出PDF] [部署到模拟盘]

### 2.5 页面⑤: 策略库 (Strategy Library)

- 策略列表(卡片/表格切换): 名称/Sharpe/MDD/因子/★收藏
- 筛选/排序/搜索
- 对比模式: 勾选2个→双栏对比(指标+净值+因子重叠+月度胜负)
- 回测历史(时间倒序), [+ 新建策略]

---

## 三、因子挖掘模块页面（4个）

> 后端详见 DEV_AI_EVOLUTION.md, DEV_FACTOR_MINING.md

### 3.1 页面⑥: 因子实验室 (Factor Lab)

顶部5模式Tab + 中央工作区 + 右侧AI助手(260px)

模式A — 手动编写: 元信息+Monaco Editor+可用字段参考+[语法检查][快速预览][提交评估]
模式B — 表达式构建: 拖拽字段+算子连线→实时生成表达式
模式C — GP遗传编程: 搜索空间配置+进化参数+过滤约束+[启动进化]
模式D — LLM生成: 生成模式(自由/定向/改进)+投资逻辑描述+Prompt配置+候选列表
模式E — 暴力枚举: 枚举模板+字段/窗口/函数范围+预估数+[启动枚举]

AI助手: 因子设计建议/解释/诊断/推荐, API: POST /api/ai/factor-assist

### 3.2 页面⑦: 挖掘任务中心 (Mining Task Center)

- 运行中: 进度条+实时指标+GP进化曲线(Recharts)+[暂停][终止]
- 已完成: ✅/❌标记, 生成→通过→入库数统计
- 任务统计: GP/LLM/枚举命中率
- WS: /ws/factor-mine/{task_id}

### 3.3 页面⑧: 因子评估报告 (Factor Evaluation)

单因子视图 — 顶部元信息+指标卡, 6+6增强Tab:
1. IC分析: IC时序+分布+累计+多周期对比 + **Newey-West t值**
2. 分组收益: 5组净值+多空+年化柱状图 + **换手率统计+扣费年化** + **拥挤度/容量**
3. IC衰减: 衰减曲线+半衰期+建议频率
4. 相关性: 热力图+增量评估 + **行业暴露(饼图+IC行业热力图)**
5. 分年度: 年度IC/IR/多空/胜率+稳定性
6. 分市场状态: 牛/熊/震荡IC对比

页面级增强:
- **因子对比模式**: 选两个因子→左右对比视图
- **PDF导出**: [导出PDF报告] 按钮

底部: [✓入库] [✗丢弃] [编辑重评] [添加到策略]

批量视图: 表格排序by IC_IR, checkbox勾选→[批量入库][导出CSV]

### 3.4 页面⑨: 因子库 (Factor Library)

- 顶部统计: 活跃N/新入库N/衰退N/淘汰N
- 操作: [因子体检] [相关性裁剪] [导出] [+添加]
- 因子表格: 状态(✅🆕⚠️❌)/名称/类别/IC/IR/来源/操作([详情][对比])
- 健康度面板: 相关性热力图(ECharts)+分类饼图(Recharts)+IC趋势监控

---

## 四、AI闭环模块页面（2个）

> 后端详见 DEV_AI_EVOLUTION.md

### 4.1 页面⑩: Pipeline控制台

- 自动化级别: [L0][L1✓][L2][L3] 四按钮
- Pipeline状态流程图: 8节点(发现→评估→入库→构建→回测→诊断→风控→部署)+状态色
- 待审批队列: 因子[批准/拒绝] + 策略[部署/拒绝]
- 调度配置: 频率+下次执行时间
- 运行历史: 轮次→发现→入库→策略更新→Sharpe
- AI决策日志: 时间+Agent+内容, 可按Agent/时间筛选
- [手动触发Pipeline] [暂停] [查看Agent配置]

### 4.2 页面⑪: Agent配置

4个Agent Tab: [因子发现] [策略构建] [诊断优化] [风控监督]
每个: 决策规则阈值+LLM/GP配置+入库/风控阈值+自动修复权限
[保存配置] [恢复默认]

---

## 五、系统设置页面（新增，1个）

### 5.1 页面⑫: 系统设置 (System Settings)

5个Tab:

Tab 1 — 数据源: Tushare/AKShare/DeepSeek状态+积分+最后更新+[测试连接][手动更新]
Tab 2 — 通知: 钉钉Webhook配置+P0/P1/P2级别开关+告警模板+[测试发送]
Tab 3 — 调度: cron任务表(名称/频率/上次/下次/状态)+[暂停][立即执行][查看日志]
Tab 4 — 健康: PG/磁盘/内存/数据新鲜度/Celery/miniQMT状态卡片
Tab 5 — 偏好: 主题(深/浅/系统)+涨跌色+数据密度+语言+时区

---

## 六、全局交互规范

### 6.1 资金量约束提示
- 条件: capital/holding_count < max_price × 100 → 黄色警告条
- 位置: 策略工作台底部 + 回测配置面板

### 6.2 错误处理
- API失败: 自动重试3次(1s/3s/8s) → 错误提示+[重试]
- WS断开: 指数退避重连(1→2→4→8→max30s)
- LLM超时(90s): 超时提示+[重试]+记录日志

### 6.3 数据导出/导入
- 导出: 配置JSON/结果PDF/因子库CSV/交易CSV/策略JSON
- 导入: 配置JSON→填充面板 / 策略JSON→加载工作台 / 股票池CSV

### 6.4 参数变更30天冷却期
- 修改已部署策略参数时弹窗确认
- 观察期内顶部提示条 + 参数旁🔒图标
- 再次修改时冷却期重置

### 6.5 FDR多重检验显示
- 因子评估: IC旁显示"原始t=3.2, FDR校正后t=2.8"
- FDR校正后t<2.0时黄色警告
- 因子库增加"FDR t值"列

### 6.6 移动端适配
- 不做完整移动端，确保总览+结果页手机可读
- 响应式: ≥1280px完整 / 768-1279px折叠侧栏 / <768px核心信息

---

## 七、后端API汇总(前端视角, ~48端点)

### 回测模块(14个)
POST /api/strategy, GET /api/strategy, GET/PUT/DELETE /api/strategy/{id}
GET /api/factors/summary, POST /api/ai/strategy-assist
POST /api/backtest/run, GET /api/backtest/{run_id}/result
GET /api/backtest/{run_id}/trades, GET /api/backtest/{run_id}/holdings/{date}
POST /api/backtest/{run_id}/sensitivity, GET /api/backtest/{run_id}/live-compare
POST /api/backtest/compare, GET /api/backtest/history
WS /ws/backtest/{run_id}

### 因子挖掘模块(15个)
POST /api/factor/create, POST /api/factor/validate
POST /api/factor/mine/gp, POST /api/factor/mine/llm, POST /api/factor/mine/brute
POST /api/ai/factor-assist
GET /api/factor/tasks, GET/DELETE /api/factor/tasks/{id}
GET /api/factor/{id}/report, POST /api/factor/evaluate/batch
GET /api/factor/library, POST /api/factor/{id}/archive
POST /api/factor/health-check, POST /api/factor/correlation-prune
WS /ws/factor-mine/{task_id}

### AI闭环模块(10个)
GET /api/pipeline/status, POST /api/pipeline/trigger, POST /api/pipeline/pause
GET /api/pipeline/history, GET /api/pipeline/pending
POST /api/pipeline/approve/{id}, POST /api/pipeline/reject/{id}
GET/PUT /api/agent/{name}/config, GET /api/agent/{name}/logs
WS /ws/pipeline/{run_id}

### 系统设置(8个)
GET /api/system/datasources, POST /api/system/datasources/{name}/test
GET /api/system/health, GET /api/system/scheduler
POST /api/system/scheduler/{task}/trigger
GET/PUT /api/system/preferences
GET/PUT /api/system/notifications/config, POST /api/system/notifications/test

---

## 八、总览页详细设计（新增）

### 8.1 架构：方案C（总组合为主 + 点击展开单市场）

默认视图显示跨市场总组合，点击A股/外汇卡片进入对应详情视图。

### 8.2 默认视图（总组合）信息架构

```
[系统异常横幅] — 仅异常时显示(数据未更新/PG断连等)，红色全宽

第一层: 策略选择器 + 核心指标卡(7个,含趋势箭头) + 市场快照
  指标卡: 组合净值/今日收益/累计收益/Sharpe(+DSR)/MDD/仓位/下次调仓
  每个带vs昨日变化箭头(↑↓→)
  部署后新增: 实盘衰减率/预估实盘Sharpe
  市场快照(右侧紧凑): 沪深300/两市成交/北向/仓位信号

第二层: 待处理事项(分类折叠，无待办时隐藏)
  ⏳审批(N) / ⚠️预警(N) / ✅完成(N) / ⏳冷却期(N)
  运行中任务(如GP挖掘/回测进度条)
  每类只显示计数+最紧急一条，展开看全部

第三层: 分市场卡片(可点击) + 跨市场风控
  A股卡片: 收益/Sharpe/仓位/持仓/策略名/迷你净值曲线/[查看详情→]
  外汇卡片: 同上(Phase 0显示"Phase 2即将开放"占位)
  跨市场: 资金配比A70%/外30% | 相关性0.15 | 总敞口80.5%

第四层: 总组合净值曲线(含关键事件标注) + 月度收益
  时间切换[1M][3M][1Y][ALL]
  事件标注: 自动从backtest_run/pipeline_run表提取
  底部仓位水位线(A股动态仓位启用时)

第五层(右侧或底部): 因子库状态 + AI闭环 + 快速操作
  因子库: ✅34 🆕2 ⚠️2 ❌8 | IC趋势→
  AI闭环: L1半自动 | 上次03-18 | 下次03-24
  快速操作: [▶运行回测] [🔍因子体检] [📊周报]
```

### 8.3 A股详情视图

点击A股卡片"查看详情→"后展开，路由/dashboard/astock:
- 顶部: ←返回总览 + 策略选择器[动量反转v3 ▾]
- 完整指标卡(7个) + 完整净值曲线(仓位水位+事件标注)
- 行业分布 + 因子库状态 + AI闭环状态 + 月度热力图
- 快速操作栏

### 8.4 外汇详情视图

点击外汇卡片"查看详情→"后展开，路由/dashboard/forex:

第一层: 6个指标卡(账户净值/今日盈亏/累计收益/Sharpe+DSR/保证金使用率/活跃订单)
第二层: 当前持仓表(实时，3-8笔，含浮盈/SL/TP/Swap) + 可用保证金/保证金水平
第三层: 左(2/3)账户净值曲线(含夜盘) | 右(1/3)货币敞口分布+交易统计(近30日)
第四层: 风控状态(单笔/保证金/限仓/周五/GARCH止损) + 隔夜Swap预估 + 经济日历(今日+明日)
第五层: 月度收益 + Swap成本
底部: [📋交易历史] [⚙️策略参数] [📊月报] [⏸暂停策略]

### 8.5 总览页API

GET /api/dashboard/summary — 净值/收益/Sharpe/MDD/仓位(每日)
GET /api/dashboard/nav-series — 净值曲线(每日)
GET /api/dashboard/pending-actions — 待处理事项(WS推送)
GET /api/dashboard/industry-distribution — 行业分布(每日)
GET /api/dashboard/monthly-returns — 月度收益(每日)
GET /api/pipeline/status — AI闭环状态(轮询30s)
GET /api/forex/account — 外汇账户(实时WS)
GET /api/forex/positions — 外汇持仓(实时WS)
GET /api/forex/risk-status — 外汇风控5项(实时)
GET /api/forex/swap-estimate — Swap预估(每日)
GET /api/forex/calendar — 经济日历(每日)

---

## 九、导航与路由设计（新增）

### 9.1 路由表

```
/                                → 重定向 /dashboard
/dashboard                       → 总览(总组合,不分市场)
/dashboard/astock                → A股详情
/dashboard/forex                 → 外汇详情

/strategy                        → 策略工作台(market参数切换)
/strategy/:id                    → 编辑策略
/strategy/new                    → 新建策略

/backtest/config                 → 回测配置
/backtest/:runId                 → 回测监控
/backtest/:runId/result          → 回测结果
/backtest/history                → 策略库

/factors                         → 因子库
/factors/:id                     → 因子评估报告
/factors/compare/:id1/:id2       → 因子对比

/mining                          → 因子实验室
/mining/tasks                    → 挖掘任务中心
/mining/tasks/:taskId            → 任务详情

/pipeline                        → AI Pipeline控制台
/pipeline/agents                 → Agent配置

/settings                        → 系统设置
/settings/:tab                   → 指定Tab
```

### 9.2 市场切换策略: 查询参数?market=forex

受影响: strategy, backtest/*, factors/*, mining/*
不受影响: dashboard, pipeline, settings

全局市场切换器在导航栏Logo下方: [A股✓] [外汇]
切换时所有链接market参数同步更新，记入localStorage

### 9.3 导航栏结构

```
[QuantMind Logo]      ← 点击回/dashboard
─────────────────
[A股 | 外汇]          ← 全局市场切换器
─────────────────
📊 总览
─────── 策略 ───────
⚡ 策略工作台
🔬 回测分析
─────── 因子 ───────
🧬 因子库
⛏️ 因子挖掘
─────── AI ─────────
🤖 AI闭环
─────── 系统 ───────
⚙️ 系统设置
─────────────────
[版本 v2.0 | ● 正常]
```

### 9.4 面包屑

深层页面显示面包屑: 回测分析>策略名>运行#047>结果, 因子库>因子名>评估报告 等

### 9.5 页面间数据传递

策略→回测: strategy_id(URL); 回测→结果: run_id(URL); 因子→评估: factor_id(URL)

### 9.6 浏览器行为

后退前进支持(push history), Tab状态写入URL query, 刷新保持(URL完全表达状态)

### 9.7 外汇路由差异

回测结果Tab: A股8个 / 外汇9个(+TCA+品种分析, -仓位分析)
因子评估Tab: A股6个(IC系) / 外汇6个(Sharpe/胜率/PF系)
组件内部根据market渲染不同Tab列表

---

## 十、组件设计规范（新增，给Figma输入）

### 10.1 通用组件清单

高频: GlassCard(4变体), MetricCard(4变体), Button(5变体), TabBar(3变体), Input(5变体), Select(3变体), Slider(3变体), Table(5变体), Badge/Pill(5色), Loading(4变体)
中频: Sidebar(2态), Breadcrumb, Modal(3变体), Toast(4类型), Tooltip(2变体), Switch, Radio/Checkbox, DatePicker(2变体), Progress(4变体), EmptyState(4类型)
低频: CodeEditor(2态), FlowNode, ChatBubble(3变体), ChartWrapper, ApprovalCard(3态), StrategyCard(3态)

### 10.2 毛玻璃卡片(GlassCard)规格

背景rgba(15,20,45,0.65), blur(24px), 边框rgba(100,120,200,0.12), 内发光rgba(255,255,255,0.05)
圆角16px大/12px小/8px内嵌, 内边距20/16/12px
变体: 默认/发光(外发光)/可点击(hover边框亮)/选中(accent边框+左条)

### 10.3 色彩系统

背景: bg-0(#06081a) → bg-1(#0f1428) → bg-2(#1a2035) → bg-3(#243049)
文字: primary(#eef0ff) / secondary(#7a82a6) / dim(#454d6e)
强调: accent(#6c7eff), accent-soft(rgba(108,126,255,0.15))
语义: success(#34d399) / warning(#fbbf24) / danger(#f87171) / info(#22d3ee)
涨跌(可配置): A股红涨绿跌 / 国际绿涨红跌(不影响语义色)
渐变: linear-gradient(135deg, #6c7eff, #a78bfa, #ec79f2)

### 10.4 字体系统

标题/正文: 'SF Pro Display', -apple-system, 'Noto Sans SC', sans-serif
数据/数值: 'SF Mono', 'JetBrains Mono', monospace
字号: H1(20px)/H2(16px)/H3(13px)/正文(12.5px)/辅助(11px)/微型(10px)/指标(22-26px)

### 10.5 间距系统

基础4px, 阶梯: xs(4)/sm(8)/md(12)/lg(16)/xl(20)/2xl(24)
圆角: xs(4)/sm(6)/md(10)/lg(12)/xl(16)

### 10.6 图表规范

ECharts: 透明背景, 网格线rgba(255,255,255,0.05), 色序列7色(蓝紫绿黄红青粉)
Recharts迷你图: 线宽1.5px, 无轴线, 渐变填充, 高度40-48px
tooltip: 毛玻璃背景, 12px, 圆角8px

### 10.7 动效规范

默认过渡all 0.2s, 卡片hover边框+20%亮度, 按钮点击scale(0.97), 数据更新flash(绿/红100ms)
列表stagger delay 30ms, 不做3D/弹跳/大面积动画

### 10.8 响应式断点

≥1440px完整, 1280-1439收窄, 1024-1279侧栏折叠单列, 768-1023紧凑, <768仅核心指标

### 10.9 外汇专属组件(8个)

① ForexPositionCard — 持仓卡片(盈利绿条/亏损红条/实时更新/止盈进度条)
② CurrencyExposureChart — 货币暴露横向柱(正蓝/负红)
③ EconomicCalendar — 经济日历(🔴高/🟡中/⚪低 + 倒计时)
④ MarginGauge — 保证金仪表盘(环形/线性, 绿黄红分段)
⑤ ForexSignalCard — 交易信号卡(宏观✅+D1✅+H4信号+ML+风控5项)
⑥ SwapPanel — Swap成本面板(每笔/今日/月累计/周三预警)
⑦ CorrelationMatrix — 品种相关性矩阵热力图(>0.7红/0.5-0.7黄/<0.5绿)
⑧ FridayClosePanel — 周五减仓面板(保留/建议平仓/自动执行)

### 10.10 A股专属组件

StockPositionTable, IndustryPieChart, FactorICChart, LimitUpDownBadge, DynamicPositionBar

### 10.11 Figma交付物清单

组件库(全部变体) + 12页面完整设计 + 深浅主题对比 + 关键交互流程

---

## 十一、实时数据更新策略（新增）

### 11.1 三种更新方式

A-静态加载(一次请求), B-轮询(定时), C-WebSocket推送(实时)

### 11.2 各页面更新方式

总览A股: 静态+WS(待办)
总览外汇: WS(持仓/报价/保证金1-5秒)
策略工作台: 静态+WS(AI流式)
回测监控: WS(进度/净值/日志)
回测结果: 静态
因子库/评估: 静态
挖掘任务: WS(GP进度/候选)
AI Pipeline: 轮询10s+WS(审批/日志)
系统设置: 轮询30s(数据源/健康)

### 11.3 WebSocket通道

已有: /ws/backtest/{runId}, /ws/factor-mine/{taskId}, /ws/pipeline/{runId}
新增: /ws/notifications(全局), /ws/forex/realtime(外汇实时)
消息格式: {type, payload, timestamp}

### 11.4 前端WS管理

app级(始终连接): /ws/notifications
page级(进出页面连接/断开): /ws/forex/realtime, /ws/backtest/*, /ws/factor-mine/*
指数退避重连: 1→2→4→8→15→30秒

### 11.5 轮询配置

React Query: refetchInterval 10-30s, staleTime 60s, 页面不可见暂停, 手动刷新按钮

### 11.6 外汇实时节流

MT5 tick→Adapter端每3秒聚合→推送前端, 非每tick推送

---

## 十二、空状态/加载态/错误态（新增）

### 12.1 加载态

骨架屏(首次加载): 灰色占位块脉冲动画, 用于总览/结果/因子库
旋转器(局部刷新): 小圆形+文字, 用于按钮提交/Tab切换

### 12.2 空状态

每页面定义: 图标(64px)+主标题(14px)+副标题(12px)+引导按钮
关键场景: 无策略→[创建], 无回测→[前往工作台], 无因子→[前往实验室], 外汇Phase 2→🔒占位, 审批全处理→✅

### 12.3 错误态三级

Level 1局部: 红色边框+[重试](组件内)
Level 2页面: 居中错误描述+[重试]+[返回]
Level 3全局: 顶部红色横幅(不遮挡内容)
错误消息用户友好, [查看详情]展开技术信息

### 12.4 WebSocket断连态

全局WS: 导航栏"⚠连接中..."→"✗离线"
外汇WS: 顶部横幅"实时数据中断"+数值旁⏱
回测WS: "连接中断，后台继续运行..."

### 12.5 特殊状态

回测运行中离开: 确认弹窗
策略未保存离开: 确认弹窗
外汇市场关闭: 提示条+[开仓]禁用
数据过期: 黄色提示+[手动更新]
Paper/Live标识: 右上角🟡模拟盘/🟢实盘

### 12.6 状态优先级(高→低)

全局错误横幅 > WS断连 > 数据过期 > 页面错误 > 局部错误 > 空状态 > 加载态

---

## 十三、通知系统前端（新增）

### 13.1 三种站内通知形式

Toast弹窗(即时3-5秒) + 通知铃铛+通知中心(持久) + 页面内横幅(全局)

### 13.2 Toast规格

右上角, 最多3条堆叠, 毛玻璃背景
✅成功(绿,3秒) / ⚠️警告(黄,5秒) / ❌错误(红,不消失) / ℹ️信息(蓝,3秒)
进入: 右侧滑入200ms, 退出: fadeOut+上移150ms

### 13.3 通知铃铛+通知中心

导航栏Logo右侧🔔, 未读时红色圆点+数字
点击展开380px面板(毛玻璃), 最大70vh, 点击外部关闭
通知项: 颜色圆点+标题(13px)+内容(12px,2行)+时间(11px)+操作链接
未读: 左侧accent色条, 已读: 无色条略暗
按天分组, [全部已读]按钮

### 13.4 通知分级

P0紧急🔴: 系统故障/风控熔断/数据异常 → Toast不消失+置顶+横幅+站外
P1重要🟡: 预警/衰退/衰减/冷却期 → Toast5秒+通知中心+站外
P2通知🔵: 审批/回测完成/闭环完成 → Toast3秒+通知中心+站外可选
P3信息🟢: 操作成功 → 仅Toast3秒

### 13.5 通知→页面跳转映射

回测完成→/backtest/{runId}/result, 因子审批→/pipeline, 因子衰退→/factors/{id}
风控预警→/dashboard, MT5断连→/settings?tab=health

### 13.6 外汇专属通知

开仓/平仓(P2), 保证金预警(P1), 周五减仓(P1), Margin Call(P0), 经济事件(P1), MT5断连(P0)

### 13.7 通知偏好

系统设置→通知配置Tab: Toast级别开关 + 通知中心级别 + 声音(P0) + 钉钉Webhook + 推送级别 + 静默时段(23:00-07:00, P0不受限)

### 13.8 通知数据

notifications表: id/level/category/market/title/content/link/is_read/is_acted/created_at
API: GET /api/notifications, PUT /{id}/read, PUT /read-all, GET /unread-count
WS: /ws/notifications实时推送

### 13.9 notifications表DDL

```sql
CREATE TABLE notifications (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    level           VARCHAR(2) NOT NULL,
    category        VARCHAR(20) NOT NULL,
    market          VARCHAR(10) DEFAULT 'system',
    title           VARCHAR(100) NOT NULL,
    content         TEXT,
    link            VARCHAR(200),
    is_read         BOOLEAN DEFAULT FALSE,
    is_acted        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_notifications_unread ON notifications(is_read, created_at DESC);
```

全系统表数: A股41 + 外汇7 + 通知1 = **49张**(Phase 3预留+2=51张)

### 13.9 与总览待办的关系

待处理 = notifications WHERE is_acted=FALSE AND level IN(P0,P1,P2) AND created_at>7天前
分类: 审批/预警/完成/冷却, 处理后从待办消失

---

## 十四、Figma审查改进清单（V5.1补充）

> 基于2026-03-20 Figma Make原型审查，对照本文档设计规范的偏差和补充。

### 14.1 因子面板组件改进（策略工作台+因子库共用）

```
问题1: IC值颜色逻辑
  当前: 所有IC都是绿色(误导！负IC也是绿色)
  修正:
    IC > 0     → #4ade80(绿色,正向因子有效)
    IC < 0     → #fb923c(橙色,反向因子,不是"坏",是方向相反)
    |IC| < 0.02 → #6b7280(灰色,信号太弱)

问题2: 选中/未选中状态
  当前: 蓝色checkbox+微弱背景
  修正:
    选中: 左侧3px竖线accent(#6c7eff) + bg-1背景 + 因子名font-medium
    未选中: 无竖线 + 透明背景 + 因子名font-normal + 文字opacity-60

问题3: 缺因子方向标识
  修正: 因子名右侧加方向Tag
    正向因子: [↑正向] 绿色小标签
    反向因子: [↓反向] 橙色小标签
    (方向来自factor_registry表的direction字段)

问题4: 信息密度不足
  修正: 每个因子项增加IC_IR值
    格式: [☑ reversal_5  IC:+0.038  IR:0.89  ↓反向]
    紧凑模式可选: 单行显示(设置项)

问题5: 分类badge太暗
  修正: "价量技术 12" 的12用accent色圆形背景(#6c7eff)
```

### 14.2 回测结果详情页（缺失页面，必须补）

> 这是用户使用最频繁的页面。从回测列表点击策略卡片进入。

**路由**: `/backtest/{run_id}/result`

**顶部摘要栏**:
```
┌─────────────────────────────────────────────────────────────────────┐
│ ← 返回列表   动量反转 v3   [已部署]   2024-01-01 ~ 2026-03-20      │
│                                                                      │
│ 年化收益    Sharpe    DSR     MDD      Calmar   WF-OOS   换手率     │
│ +28.47%    1.82     0.92✅  -8.23%    3.46     1.71     34%/月     │
│ (绿)      (绿)    (绿)    (绿)     (绿)    (绿)    (黄)        │
│                                                                      │
│ [↗ 部署到模拟盘]  [📋 导出报告]  [⚖️ 对比]  [🔄 重新回测]         │
└─────────────────────────────────────────────────────────────────────┘

颜色阈值:
  年化: >15%绿, 5-15%黄, <5%红
  Sharpe: >1.0绿, 0.5-1.0黄, <0.5红
  DSR: >0.8绿, 0.5-0.8黄, <0.5红
  MDD: >-15%绿, -15~-25%黄, <-25%红
```

**8个Tab内容**:

```
Tab 1: 净值曲线
  ├─ 策略净值 vs CSI300基准 双线图(ECharts)
  ├─ 超额收益面积图(策略-基准)
  ├─ 回撤水下图(drawdown underwater chart)
  ├─ 时间范围选择器(1M/3M/1Y/ALL + 自定义拖拽)
  ├─ Hover显示: 日期+净值+日收益率+基准收益率+超额
  └─ 右侧: 月度/季度/年度收益率表格

Tab 2: 月度归因
  ├─ 月度收益热力图(12月×N年, 同Dashboard)
  ├─ 因子贡献分解柱状图(每月每个因子贡献多少收益)
  ├─ 行业归因饼图(超额收益来自哪个行业)
  ├─ 选股贡献 vs 行业配置贡献 分解
  └─ Brinson归因模型结果表

Tab 3: 持仓分析
  ├─ 当前持仓列表(股票/权重/盈亏/持有天数/所属行业)
  ├─ 持仓集中度图(Top5/Top10占比)
  ├─ 行业分布饼图
  ├─ 市值分布直方图(大/中/小盘)
  ├─ 持仓热力图(时间轴×股票, 颜色=权重)
  └─ 历史持仓数量折线图

Tab 4: 交易明细
  ├─ 交易记录表(日期/股票/方向/价格/数量/佣金/滑点/盈亏)
  ├─ 筛选: 按日期范围/买入卖出/盈亏/股票
  ├─ 统计: 总交易笔数/胜率/平均盈亏比/平均持有天数
  ├─ 盈亏分布直方图(每笔交易的盈亏%)
  └─ 导出CSV按钮

Tab 5: Walk-Forward
  ├─ 窗口列表(训练期Sharpe/验证期Sharpe/测试期Sharpe/参数)
  ├─ OOS拼接净值曲线(所有测试期连接)
  ├─ 训练vs测试Sharpe散点图(对角线=完美一致)
  ├─ DSR校正值 + PBO过拟合概率
  ├─ 每窗口的因子权重变化折线图
  └─ 窗口稳定性评分(Sharpe方差)

Tab 6: 敏感性分析
  ├─ 参数敏感性热力图(持仓N × 调仓频率 → Sharpe颜色矩阵)
  ├─ 成本敏感性: 佣金从万1到万5, Sharpe变化曲线
  ├─ 滑点敏感性: 滑点倍数0.5x-3x, Sharpe变化曲线
  └─ 结论: "策略对成本不敏感(佣金万3→万5, Sharpe仅降0.05)"

Tab 7: 实盘对比(有实盘数据时显示)
  ├─ 回测净值 vs 实盘净值 双线
  ├─ 每日偏差(实盘-回测)折线图
  ├─ 偏差统计: 均值/标准差/最大偏差
  ├─ 偏差归因: 滑点占比/成交失败占比/数据差异占比
  └─ 空状态: "尚无实盘数据，部署到模拟盘后自动对比"

Tab 8: 仓位分析
  ├─ 仓位使用率时间线(已用仓位/总仓位)
  ├─ 现金占比时间线
  ├─ 调仓日标记(垂直虚线)
  ├─ 每次调仓: 买入N只/卖出M只/换手率
  └─ 调仓成本累计曲线
```

### 14.3 回测配置面板（缺失，必须补）

> 从策略工作台点击"运行回测"后弹出，或独立页面。

**路由**: `/backtest/new` 或 Modal弹窗

```
6个Tab配置:

Tab 1: 市场与股票池
  ├─ 市场: A股(默认) / 外汇(Phase 2锁定)
  ├─ 股票池: 全A / 沪深300 / 中证500 / 中证1000 / 自定义
  ├─ 排除: ST / 新股 / 停牌 / 涨跌停(各有开关)
  └─ 行业限制: 排除特定行业(多选)

Tab 2: 时间段
  ├─ 回测起止日期(日期选择器)
  ├─ 预设: 近1年 / 近3年 / 近5年 / 2015至今 / 自定义
  └─ Walk-Forward: 开关 + 训练月/验证月/测试月/步进月

Tab 3: 执行参数
  ├─ 初始资金: 输入框(默认50万)
  ├─ 调仓频率: 周/双周/月(单选)
  ├─ 持仓数量: 滑块(10-50, 默认30)
  ├─ 权重方案: 等权/IC加权/风险平价(单选)
  └─ 买入时机: 收盘价/次日开盘价(单选)

Tab 4: 成本模型
  ├─ 佣金率: 输入框(默认万1.5)
  ├─ 印花税率: 输入框(默认万5, 仅卖出)
  ├─ 滑点模型: 固定/Volume-Impact(单选)
  ├─ 滑点系数: 滑块(0.5-3.0)
  └─ 最低佣金: 输入框(默认5元)

Tab 5: 风控参数
  ├─ 单股上限: 滑块(3%-15%)
  ├─ 行业上限: 滑块(15%-40%)
  ├─ 换手率上限: 滑块(30%-100%/月)
  ├─ 止损线: 开关+阈值(-10%~-25%)
  └─ 回撤熔断: 开关+阈值(-15%~-30%)

Tab 6: 高级(折叠)
  ├─ 基准指数: CSI300/CSI500/CSI1000(下拉)
  ├─ 复权方式: 后复权(默认,不可改)
  ├─ 确定性种子: 数字输入(默认42)
  └─ 并行窗口: 1-4(WF模式下)

底部: [取消]  [▶ 开始回测]
```

### 14.4 各页面改进明细

```
═══ Dashboard ═══
D1: 指标卡"总仓位"替换为"今日超额收益"(仓位放入A股详情卡)
D2: 月度热力图色块加大，正负色对比度增强
D3: 外汇锁定卡加"Phase 2设计已完成"进度条
D4: 净值曲线加hover tooltip(日期+净值+收益率)
D5: AI闭环流程图缩减为: 当前步骤+前后各1步(8步太挤)
D6: "查看详情"按钮改为accent色带箭头按钮

═══ 策略工作台 ═══
S1: 因子面板(见§14.1完整改进)
S2: Alpha合成区加因子权重饼图/条形图
S3: 中间参数区卡片字体加大(当前太小)
S4: AI助手面板宽度从~250px增加到~300px
S5: "+自定义因子"移到搜索框右侧

═══ 回测分析 ═══
B1: 补完整结果详情页(见§14.2)
B2: 补配置面板(见§14.3)
B3: 列表加排序(点Sharpe/MDD列头排序)
B4: 列表加DSR列
B5: 策略卡片更紧凑(改表格视图选项)
B6: 加策略对比功能(选2个并排)

═══ 因子库 ═══
F1: 方向列加↑↓图标(不只是文字)
F2: 加Gate评分列("8/8通过"或"87/100")

═══ 因子挖掘 ═══
M1: 候选因子卡加Gate通过明细(8项✅/❌)
M2: 暴力枚举结果加通过率百分比
M3: GP进化曲线区域高度增加50%
M4: 候选因子加max_corr显示(与现有因子相关性)

═══ AI闭环 ═══
P1: Pipeline当前步骤加脉冲动画效果
P2: 运行历史Sharpe列加颜色编码(>1.0绿, <1.0红)
P3: AI决策日志加Agent类型筛选下拉

═══ 系统设置 ═══
ST1: 补通知Tab(钉钉配置+测试+静默时段+级别开关)
ST2: 补调度Tab(任务链时间线+执行历史+手动触发)
ST3: 补健康检查Tab(DB/Redis/Celery状态+磁盘+内存)
ST4: 补偏好Tab(涨跌色方案/语言/时区)
ST5: DeepSeek余额加月预算进度条(¥87.5/¥500)
ST6: 数据源区域加"数据更新历史"折叠表格

═══ 全局 ═══
G1: Glassmorphism增强(卡片加transparency+backdrop-blur+微光边框)
G2: 底部Ticker加间距或改滚动模式
G3: 侧边栏分组标签颜色改为accent色
G4: 通知铃铛加下拉面板(最近5条+查看全部链接)
```

### 14.5 优先级排序（给Figma迭代）

```
🔴 P0 必须做（影响核心体验）:
  1. 回测结果详情页8Tab — §14.2
  2. 回测配置面板6Tab — §14.3
  3. 因子面板IC颜色+方向标签 — §14.1

🟡 P1 建议做（提升专业感）:
  4. Glassmorphism效果增强
  5. 系统设置其他4个Tab内容
  6. 净值曲线hover交互
  7. 因子库Gate评分列
  8. AI闭环步骤高亮动画

🟢 P2 可以后做:
  9. 策略对比功能
  10. 候选因子Gate明细展开
  11. AI日志筛选
  12. 移动端适配
```

---

## 十四、Figma审查改进清单（V5.1补充）

> 基于Figma Make原型(tU2hHxkJ2nQSWeIumwZAGc)审查，对照§一-§十三设计规范

### 14.1 全局视觉改进

**G1: Glassmorphism效果增强**
```
当前: 卡片为纯实色深蓝(#0f172a)，无透明度
目标(§十规范):
  background: rgba(15, 23, 42, 0.6)    ← 需要0.6透明度
  backdrop-filter: blur(12px)           ← 毛玻璃模糊
  border: 1px solid rgba(255,255,255,0.08) ← 微光边框
  
  背景层需要渐变光斑或噪点纹理，毛玻璃才能"透"出来
  参考: Linear App / Vercel Dashboard 的暗色毛玻璃效果
```

**G2: 侧边栏分组标签太暗**
```
当前: "策略""因子""AI""系统"分组标签用极暗灰色，几乎不可见
修改: 用 text-secondary(#94a3b8) 或 accent色(#6c7eff)，字号10px→11px
```

**G3: 底部市场行情Ticker太挤**
```
当前: 沪深300/上证/创业板/成交额/北向/仓位 挤在一行
修改: 
  方案A: 加间距(gap: 24px→40px)
  方案B: 改为滚动Ticker(marquee效果)
  方案C: 只显示核心3个(沪深300/成交额/北向)，hover展开全部
```

### 14.2 因子面板组件改进（策略工作台+因子库通用）

**F-UI1: IC值颜色逻辑修正（🔴 信息传达错误）**
```
当前: 所有IC值统一绿色 — 误导用户
修正规则:
  IC > +0.02  → 绿色(#22c55e)  正向信号有效
  IC < -0.02  → 橙色(#f59e0b)  反向信号有效(不是"坏"，只是方向相反)
  |IC| < 0.02 → 灰色(#64748b)  信号太弱

注意: IC为负的因子(如reversal)不是差因子，是反转因子
  reversal_20 IC=-0.041 → 橙色(有效的反向因子)
  current_ratio IC=+0.018 → 灰色(信号太弱)
```

**F-UI2: 因子方向标签**
```
当前: 只有因子名+IC值，用户不知道IC负值意味着什么
添加: 因子名后加方向tag
  reversal_5    IC=+0.038  [↓反向]
  momentum_60   IC=+0.045  [↑正向]
  volatility_20 IC=-0.036  [↓反向]
  
  tag样式: 微型badge, 10px, 半透明背景
  正向: text-green + bg-green/10
  反向: text-orange + bg-orange/10
```

**F-UI3: 选中/未选中状态增强**
```
当前: 选中=蓝色checkbox+微弱高亮，暗色主题下区分度不够
修改:
  选中项:
    左侧加3px竖线 accent色(#6c7eff)
    背景: bg-1(#0d1526) → bg-2(#162032)
    因子名: font-weight 400→500
  未选中项:
    无竖线
    背景: 透明
    因子名: font-weight 400, text-secondary色
```

**F-UI4: 信息密度优化**
```
当前: 每个因子两行(名称+IC)，12个价量因子占满面板
改进:
  紧凑模式(默认): 单行 [☑ reversal_5  IC:+0.038 ↓  IR:0.89]
  详细模式(切换): 两行(当前样式)
  面板顶部加 [紧凑|详细] 切换按钮
```

**F-UI5: 因子库表格补充列**
```
当前列: 因子名/类别/IC均值/IC_IR/方向/IC趋势/状态/操作
添加列:
  Gate评分: "87/100" 或 "8/8 ✅" (综合评分一目了然)
  方向标签: ↑正向/↓反向 (代替纯文字"反向")
  IC趋势迷你图: ✅已有，非常好
```

### 14.3 总览页(Dashboard)改进

**D1: 指标卡调整**
```
当前7卡: 净值/今日P&L/累计收益/Sharpe+DSR/MDD/总仓位/下次调仓
建议调整: 将"总仓位85.5%"替换为"今日超额+0.12%"
  仓位信息放到A股详情卡里(不是核心关注指标)
  超额收益是每日最关注的数字
```

**D2: 月度热力图改进**
```
当前: 色块偏小，红绿区分度不够
修改:
  色块最小尺寸: 24px×20px → 28px×24px
  正收益: #22c55e (亮绿) 深浅按幅度分3级(0-1%/1-3%/>3%)
  负收益: #ef4444 (亮红) 深浅按幅度分3级
  零附近: #334155 (暗灰)
```

**D3: 外汇占位卡改进**
```
当前: 只有🔒图标和"Phase 2"文字，空间浪费
改进: 加进度提示
  "外汇模块设计已完成 ✅"
  "等待Phase 2开发启动"
  或显示外汇10个子模块的完成度进度条
```

**D4: 净值曲线交互**
```
当前: 静态曲线，无hover效果
添加:
  hover: 十字线 + tooltip显示(日期/净值/收益率/基准/超额)
  click: 可选时间范围(已有1M/3M/1Y/ALL按钮 ✅)
  双线: 策略线(accent色) + 基准线(灰色虚线) ✅已有
```

**D5: AI闭环流程图简化**
```
当前: 8个步骤挤在一行，文字太小
修改:
  方案A: 只显示当前步骤+前后各1步(3步可见，左右箭头切换)
  方案B: 缩减为5步(发现→评估→构建→回测→部署)，合并相似步骤
```

**D6: "查看详情"按钮增强**
```
当前: A股卡片底部"查看详情>"太弱，像灰色链接
修改: 改为 ghost button样式(border + hover高亮)，或整个卡片可点击
```

### 14.4 策略工作台改进

**S1: 因子权重预览**
```
当前: 勾选因子后看不到权重分配
添加: 在流程图"Alpha合成"卡片内加小型条形图
  reversal_5:  ████████ 22%
  reversal_20: ███████  19%
  momentum_60: ██████   17%
  ...
  或饼图(占用空间更小)
```

**S3: 中间区域参数卡片增大**
```
当前: Alpha合成/选股参数/风控约束三个卡片太小，参数值看不清
修改: 
  流程图高度从200px→140px(缩小)
  参数卡片区域增大，改为2×2网格布局(4个卡片)
  或改为可展开的Accordion(默认折叠只显示标题，点击展开参数)
```

**S4: AI助手面板宽度**
```
当前: 右侧AI面板约240px，文字被截断
修改: 宽度280px→320px，或改为可拖拽调整宽度
```

**S5: "+自定义因子"按钮位置**
```
当前: 因子列表最底部，需要滚动才能看到
修改: 放到搜索框右侧(与搜索框同行)，或因子列表顶部
```

### 14.5 回测分析页改进（🔴 最大缺口）

**B1-B2: 需要补充的子页面**

```
当前: 只有策略列表页
缺失: 3个关键子页面

① 回测配置面板(点击"运行回测"后弹出):
  6个Tab: 市场股票池 / 时间段 / 执行参数 / 成本模型 / 风控约束 / 动态仓位
  底部: [取消] [运行回测] 按钮
  参考: §二② 回测配置面板设计

② 回测运行监控(回测执行中):
  实时净值曲线(逐日更新)
  进度条(Day 580/1200 = 48%)
  当前指标: Sharpe/MDD/持仓数
  [暂停] [取消] 按钮

③ 回测结果详情(点击策略卡片进入):
  8个Tab:
    [净值曲线] 策略vs基准，超额收益带，回撤水位线
    [月度归因] 热力图(月×年)，超额收益分解
    [持仓分析] 行业分布饼图，持仓集中度，持仓周期分布
    [交易明细] 全部买卖记录表格，胜率/盈亏比统计
    [Walk-Forward] WF窗口对比(训练Sharpe vs OOS Sharpe)，DSR/PBO
    [敏感性] 参数网格热力图(持仓N × 调仓频率 → Sharpe)
    [实盘对比] Paper Trading vs 回测偏差(Phase 1)
    [仓位时间线] 每日仓位变化瀑布图
  顶部: 策略名+核心指标摘要
  右上: [导出PDF] [部署到模拟盘] 按钮
```

**B3: 列表页DSR显示**
```
当前: 年化/Sharpe/MDD/Calmar/WF-OOS
添加: DSR列(Deflated Sharpe Ratio)
  DSR > 0.95: 绿色 ✅
  DSR 0.5-0.95: 黄色 ⚠️
  DSR < 0.5: 红色 🔴
```

**B5: 策略列表排序+搜索**
```
当前: 无排序无搜索，4个策略占全屏
添加:
  列头点击排序(按Sharpe/MDD/年化)
  搜索框(按策略名搜索)
  视图切换: [卡片] [表格] 
```

### 14.6 因子挖掘页改进

**M1: 候选因子Gate明细**
```
当前: 候选因子卡片只有IC和IR
添加: 点击"详情"展开后显示:
  Gate 1 IC均值:     0.039 > 0.02   ✅
  Gate 2 IC_IR:      0.82  > 0.3    ✅
  Gate 3 IC胜率:     61%   > 55%    ✅
  Gate 4 单调性:     0.78  > 0.7    ✅
  Gate 5 半衰期:     12天  > 5天    ✅
  Gate 6 相关性:     0.45  < 0.7    ✅
  Gate 7 覆盖率:     92%   > 80%    ✅
  Gate 8 综合评分:   83/100 ≥ 70    ✅
```

**M3: GP进化曲线增大**
```
当前: 曲线高度约150px，趋势细节看不清
修改: 高度250px，加hover tooltip显示具体代数+最佳IC
```

**M4: 候选因子加相关性显示**
```
当前: 缺"与现有因子最大相关性"
添加: 每个候选因子卡片加一行:
  "与现有最相似: turnover_20 (corr=0.42)" 绿色
  或 "与现有最相似: momentum_60 (corr=0.71)" 红色⚠️
```

### 14.7 AI闭环页改进

**P1: Pipeline当前步骤高亮增强**
```
当前: "诊断优化"是当前步骤但视觉不够突出
修改:
  当前步骤: accent色边框(2px) + 脉冲动画(pulse) + 图标放大
  已完成步骤: 绿色勾号 + 半透明
  未到达步骤: 灰色 + 虚线边框
```

**P2: Sharpe列颜色编码**
```
当前: 运行历史的Sharpe列全为白色
修改:
  Sharpe > 1.5: 亮绿
  Sharpe 1.0-1.5: 绿色
  Sharpe 0.5-1.0: 黄色
  Sharpe < 0.5: 红色
```

**P3: AI决策日志筛选**
```
添加: 日志区域顶部加Agent类型筛选
  [全部] [Idea Agent] [Factor Agent] [Eval Agent] [GP Engine]
  点击筛选，只显示对应Agent的日志条目
```

### 14.8 系统设置页改进

**ST1: 补充其他4个Tab内容**

```
通知Tab:
  钉钉Webhook配置(URL输入框+测试按钮)
  通知级别开关(P0/P1/P2/P3各一个toggle)
  静默时段(23:00-07:00时间选择器)
  声音开关

调度Tab:
  A股任务链时间线(参考DEV_SCHEDULER §11设计)
  ✅ 06:00 数据更新 完成 06:22 (22min)
  ✅ 06:35 质量检查 完成 06:38
  ⏳ 07:45 信号生成 运行中...
  ⬜ 08:00 调仓决策 等待中
  底部: [手动触发] [暂停调度] [执行日志]

健康检查Tab:
  PostgreSQL: 🟢 连接正常 | 表数51 | 磁盘4.2GB
  Redis: 🟢 连接正常 | 内存128MB
  Celery: 🟢 4个Worker活跃 | 队列0任务
  MT5 Adapter: 🔴 未连接 (Phase 2)
  最近错误日志(最近5条)

偏好设置Tab:
  涨跌色方案: [红涨绿跌(中国)] [绿涨红跌(国际)]
  默认基准: [沪深300] [中证500] [中证1000]
  默认回测时间范围: [3年] [5年] [全部]
  语言: [中文] [English]
```

**ST2: 数据源卡片补充**
```
当前: 卡片下方空白
添加: "最近数据更新历史"表格
  2026-03-20 06:22 ✅ 全量更新 3,241只股票
  2026-03-19 06:18 ✅ 全量更新 3,238只股票
  2026-03-18 06:25 ⚠️ 部分失败(3只ST退市)
```

**ST5: DeepSeek预算进度条**
```
当前: 显示¥87.5余额
添加: 月预算进度条
  本月预算: ¥500
  已使用: ¥412.5 (82.5%)
  剩余: ¥87.5
  预计本月: ¥490 (在预算内 ✅)
  进度条: ████████████████░░░ 82.5%
  余额<¥50时变红色预警
```

### 14.9 Figma改进优先级

```
🔴 必须做(影响功能理解):
  1. F-UI1: IC值颜色逻辑修正 — 当前会误导用户
  2. B1-B2: 回测结果详情页(8Tab) — 核心使用场景完全缺失
  3. B1-B2: 回测配置面板(6Tab) — 回测入口缺失

🟡 建议做(提升体验):
  4. G1: Glassmorphism效果增强
  5. F-UI2: 因子方向标签
  6. F-UI3: 选中/未选中状态增强
  7. ST1: 系统设置其他Tab内容
  8. D4: 净值曲线hover交互
  9. M1: 候选因子Gate明细
  10. P1: Pipeline当前步骤高亮

🟢 可以后做(锦上添花):
  11. F-UI4: 因子面板紧凑模式
  12. D2: 月度热力图色块增大
  13. S1: 因子权重预览
  14. P3: AI决策日志筛选
  15. B5: 策略列表排序+搜索
```

---

## ⚠️ Review补丁（2026-03-20，以下内容覆盖本文档中的旧版设计）

> **Claude Code注意**: 本章节的内容优先级高于文档其他部分。如有冲突，以本章节为准。

### P1. 回测报告页新增指标（扩展回测分析页面）

原有指标保留，新增以下内容:

**统计摘要Tab（新增）**: 一页展示所有关键指标
| 指标 | 展示格式 |
|------|---------|
| Calmar Ratio | 数字，>2.0绿色 <1.0红色 |
| Sortino Ratio | 数字 |
| 最大连续亏损天数 | 数字+天，>20天红色 |
| 胜率 | 百分比 |
| 盈亏比 | X:1 格式 |
| Beta | 数字，绝对收益应<0.3 |
| 信息比率(IR) | 数字，>0.5绿色 |
| 年化换手率 | 百分比 + "≈年成本X%"估算 |
| Bootstrap Sharpe CI | `1.21 [0.43, 1.98]` 格式，下界<0标红 |
| 开盘跳空统计 | 百分比，>1%黄色警告 |
| 实际vs理论仓位偏差 | 百分比，>3%标红 |

**成本敏感性Tab（新增）**:
表格展示0.5x/1x/1.5x/2x成本下的年化收益/Sharpe/MDD。
2倍成本下Sharpe<0.5标红警告。

**年度分解表（新增）**:
每年一行: 年份 | 收益 | Sharpe | MDD | 超额收益
最差年度所在行标红高亮。

**市场状态分段（新增）**:
自动分牛市/熊市/震荡三段，每段独立展示绩效。
展示方式: 三列卡片（牛/熊/震荡），每卡片内含收益/Sharpe/MDD。

**月度收益热力图（新增）**:
X轴=月份(1-12), Y轴=年份, 颜色深浅=月收益。红色=亏损，绿色=盈利。

### P2. Paper Trading状态展示

Dashboard页面新增Paper Trading运行状态:
- 当前execution_mode标识（Paper/Live）
- Paper Trading已运行天数 / 60天目标
- 实际Sharpe vs 回测Sharpe × 70%对比进度条
- 毕业标准5项达标状态（✓/✗）
