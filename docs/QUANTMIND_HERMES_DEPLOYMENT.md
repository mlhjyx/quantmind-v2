# QuantMind × Hermes Agent 全栈部署方案

**日期**: 2026-04-12 | **版本**: v1.0
**目标**: 将QuantMind从"人驱动量化系统"升级为"Agent驱动自进化量化系统"
**消息通道**: 微信(个人微信iLink协议)

---

## 一、战略定位

### 1.1 当前痛点 → Hermes解决方案

| 痛点 | 现状 | Hermes解决方案 |
|------|------|---------------|
| PT监控靠人 | 每天手动查日志 | Cron自动检查→微信告警 |
| 数据过期2天才发现 | P0-2 Parquet事故 | 每日自动一致性校验 |
| CC无跨session记忆 | 每次重喂上下文 | MEMORY.md持久记忆 |
| 长任务无人看结果 | 中性化4.5h | SubAgent跑完→微信通知 |
| 因子IC退化无感知 | 策略默默失效 | 每周IC趋势→退化告警 |
| 因子研究纯手动 | 你写prompt→CC执行→你审阅 | Agent自主发现→你审批 |
| 知识碎片化 | 散落文档/memory/对话 | Skills自动积累+FTS5搜索 |
| DEV_AI_EVOLUTION 0行代码 | RD-Agent三重阻断 | Hermes原生实现全部设计 |

### 1.2 工具分层——每层用最合适的工具

| 层 | 工具 | 职责 | 改变 |
|----|------|------|------|
| 决策层 | Claude.ai + 你 | 方向决策/审批 | 不变 |
| 开发层 | Claude Code | 代码编写/调试/回测 | 不变 |
| **运维层** | **Hermes Agent** | **24/7监控/告警/自动化** | **新增** |
| **研究层** | **Hermes Agent** | **因子发现/评估/进化** | **新增** |
| **通信层** | **微信Gateway** | **随时随地交互** | **新增** |
| 基础设施 | PG+Redis+QMT+Tushare | 数据/交易/存储 | 不变 |

---

## 二、技术架构

### 2.1 全栈架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                      你（微信）                                  │
│                  随时随地查看/指令/审批                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │ 腾讯iLink协议(合法官方API)
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Hermes Agent (WSL2)                            │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                  Weixin Gateway                             │  │
│  │  • Long-poll(不需公网IP/域名)                               │  │
│  │  • QR码扫码登录                                             │  │
│  │  • 私聊+群聊 / 语音+图片+文件                               │  │
│  │  • Markdown→微信格式自动转换                                │  │
│  │  • 长消息自动分段 / 断线自动重连                             │  │
│  └────────────────────────┬───────────────────────────────────┘  │
│                           ▼                                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │               AIAgent Core (claude-sonnet-4)               │  │
│  │  • Prompt: SOUL.md + MEMORY.md + USER.md + Skills          │  │
│  │  • 48个内置工具 + MCP扩展                                   │  │
│  │  • execute_code (Python RPC, 零context成本)                │  │
│  │  • SubAgent delegation (并行任务)                           │  │
│  └──────┬──────────┬──────────┬──────────┬───────────────────┘  │
│         │          │          │          │                       │
│  ┌──────▼───┐ ┌────▼────┐ ┌──▼─────┐ ┌─▼──────────┐           │
│  │ Memory   │ │ Skills  │ │  Cron  │ │ SubAgents  │           │
│  │          │ │         │ │        │ │            │           │
│  │MEMORY.md │ │因子入库  │ │PT监控  │ │Factor      │           │
│  │ 铁律1-30 │ │IC评估   │ │IC监控  │ │Researcher  │           │
│  │ 基线数字 │ │WF验证   │ │数据守护│ │Data        │           │
│  │ 关闭方向 │ │画像分析  │ │磁盘告警│ │Engineer    │           │
│  │          │ │健康检查  │ │        │ │Risk        │           │
│  │USER.md   │ │论文搜索  │ │        │ │Manager     │           │
│  │ 中文交流 │ │         │ │        │ │            │           │
│  │ 不说跳过 │ │自动创建  │ │自然语言│ │独立终端    │           │
│  │ 串行执行 │ │自我改进  │ │设定    │ │独立记忆    │           │
│  │          │ │         │ │        │ │零context   │           │
│  │SQLite    │ │         │ │        │ │            │           │
│  │FTS5搜索  │ │         │ │        │ │            │           │
│  └──────────┘ └─────────┘ └────────┘ └────────────┘           │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                    MCP Layer                                │  │
│  │                                                             │  │
│  │  quantmind-db ──→ PostgreSQL (只读查询)                     │  │
│  │  quantmind-tushare ──→ Tushare API                         │  │
│  │  quantmind-system ──→ 日志/文件系统/进程                    │  │
│  │  quantmind-github ──→ Git操作                               │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                  自进化引擎 (Phase E)                       │  │
│  │  GEPA: 遗传进化优化Agent的prompt和行为                      │  │
│  │  Atropos: 导出轨迹→微调量化专用模型                         │  │
│  │  Plugin Hooks: pre/post_llm_call + session事件             │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────┬──────────────┬──────────────┬────────────────────────┘
           │              │              │
     ┌─────▼─────┐  ┌────▼────┐  ┌─────▼──────┐
     │PostgreSQL │  │ Tushare │  │QuantMind   │
     │quantmind  │  │ AKShare │  │项目文件    │
     │_v2        │  │ BaoStock│  │logs/cache  │
     │           │  │         │  │scripts     │
     │factor_val │  │         │  │CLAUDE.md   │
     │klines     │  │         │  │configs     │
     │signals    │  │         │  │            │
     └───────────┘  └─────────┘  └────────────┘
```

### 2.2 与DEV_AI_EVOLUTION.md的完整对应

| DEV_AI_EVOLUTION设计 | Hermes实现 | 状态 |
|---------------------|-----------|------|
| HypothesisAgent(假设生成) | Factor Researcher Profile + web_search | 原生支持 |
| CodeAgent(代码生成) | execute_code + terminal_tool调CC | 原生支持 |
| EvaluationAgent(评估验证) | IC/WF skill + Portfolio Builder | 通过Skills |
| FeedbackAgent(反馈学习) | Risk Manager Profile + MEMORY.md | 原生支持 |
| Pipeline闭环 | Cron + SubAgent + Hooks | 原生支持 |
| 知识积累 | MEMORY.md + Skills自动生成 + FTS5 | 原生支持 |
| 模型进化 | Atropos轨迹导出 → RL微调 | 原生支持 |
| **总计: 0行代码→全部可实现** | | |

---

## 三、分阶段部署

### Phase A: 基础安装 + 微信连接（半天）

#### A.1 WSL2安装Hermes

```bash
# 进入WSL2
wsl

# 一键安装
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash

# 验证
hermes --version
hermes doctor  # 诊断环境
```

#### A.2 配置LLM Provider

```bash
hermes setup
# 或单独配模型：
hermes model
```

推荐配置（DeepSeek日常 + GLM-5复杂研究，月成本~$5-10）：
```yaml
# ~/.hermes/config.yaml
provider: deepseek
model: deepseek-chat                    # 日常主力（最便宜）

fallback_providers:
  - provider: openai_compatible         # 复杂研究任务
    model: glm-5-turbo
    api_key: ${ZHIPU_API_KEY}
    base_url: https://open.bigmodel.cn/api/paas/v4
```

环境变量 `~/.hermes/.env` 添加：
```bash
DEEPSEEK_API_KEY=sk-xxx          # https://platform.deepseek.com/api_keys
ZHIPU_API_KEY=your_zhipu_api_key_here                # https://open.bigmodel.cn (GLM-5)
```

成本对比：
| 模型 | 输入$/M tokens | 输出$/M tokens | 适用 |
|------|---------------|---------------|------|
| DeepSeek V3 | $0.27 | $1.10 | 日常监控/查询/简单分析(85%) |
| GLM-5-Turbo | $0.96 | $3.20 | 复杂因子研究/策略分析/论文解读(15%) |

选择理由：
- DeepSeek：最便宜，日常Cron/查询绰绰有余
- GLM-5-Turbo：中文能力断档领先(C-Eval 92.1%)，专为Agent长链路优化，
  SWE-bench Pro(GLM-5.1)全球第一(58.4%)，价格仅Claude的1/5
- 两者都是国内API，网络稳定无墙
- 不占本地GPU资源（RTX 5070留给Kronos/PyTorch）

#### A.3 微信Gateway连接

```bash
# 交互式配置
hermes gateway setup
# 选择: Weixin
# 手机微信扫二维码
# 自动保存凭证
```

扫码后微信连接自动完成，无需手动配置。如需加安全限制，可选配 `~/.hermes/.env`：
```bash
# 微信安全（可选，不设也能用，扫码即连）
# WEIXIN_DM_POLICY=allowlist           # 限制谁能跟Agent对话
# WEIXIN_ALLOWED_USERS=your_wechat_id  # 只允许你的微信ID
# WEIXIN_HOME_CHANNEL=chat_id          # Cron通知发到哪个聊天窗口

# LLM配置（必填）
DEEPSEEK_API_KEY=sk-xxx                # https://platform.deepseek.com
ZHIPU_API_KEY=xxx                      # https://open.bigmodel.cn
```

#### A.4 启动Gateway（systemd持久化）

```bash
# 创建systemd服务
sudo tee /etc/systemd/system/hermes-gateway.service << 'EOF'
[Unit]
Description=Hermes Agent WeChat Gateway
After=network.target

[Service]
Type=simple
User=xin
WorkingDirectory=/home/xin
ExecStart=/home/xin/.hermes/venv/bin/hermes gateway
Restart=always
RestartSec=10
Environment=HOME=/home/xin

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable hermes-gateway
sudo systemctl start hermes-gateway

# 检查状态
sudo systemctl status hermes-gateway
```

#### A.5 验证微信通信

在微信里发消息测试：
```
你：你好
Hermes：你好！我是Hermes Agent。有什么可以帮你的？

你：今天是几号？
Hermes：今天是2026年4月13日，星期一。

你：帮我搜索一下最新的A股量化因子论文
Hermes：[web_search执行] 找到以下相关论文...
```

**Phase A 验收标准：**
- [ ] WSL2 Hermes安装成功
- [ ] LLM对话正常(CLI测试)
- [ ] 微信扫码连接成功
- [ ] 微信双向消息正常
- [ ] Gateway systemd服务稳定运行

---

### Phase B: MCP连接QuantMind基础设施（半天）

#### B.1 PostgreSQL MCP Server（只读）

创建自定义MCP Server：

```python
# ~/.hermes/mcp_servers/quantmind_db_server.py
"""QuantMind DB MCP Server — 只读查询，限制表范围"""

import json
import asyncio
import psycopg2
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quantmind-db")

DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "dbname": "quantmind_v2",
    "user": "xin",
}

ALLOWED_TABLES = [
    'factor_values', 'klines_daily', 'stock_status_daily',
    'signals', 'position_snapshot', 'performance_series',
    'trade_log', 'earnings_announcements', 'daily_basic',
    'fina_indicator', 'moneyflow_daily',
]

@mcp.tool()
def query_db(sql: str) -> str:
    """执行只读SQL查询。只允许SELECT，禁止INSERT/UPDATE/DELETE。"""
    sql_upper = sql.strip().upper()
    if not sql_upper.startswith("SELECT"):
        return "错误：只允许SELECT查询"
    
    # 检查表名是否在白名单
    for table in ALLOWED_TABLES:
        if table in sql.lower():
            break
    else:
        return f"错误：查询的表不在白名单中。允许的表: {ALLOWED_TABLES}"
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description] if cur.description else []
        rows = cur.fetchmany(100)  # 最多100行
        conn.close()
        
        if not rows:
            return "查询返回0行"
        
        result = {"columns": columns, "rows": [list(r) for r in rows], "total": len(rows)}
        return json.dumps(result, default=str, ensure_ascii=False)
    except Exception as e:
        return f"查询错误: {str(e)}"

@mcp.tool()
def db_table_info(table_name: str) -> str:
    """获取表的列信息和行数"""
    if table_name not in ALLOWED_TABLES:
        return f"表不在白名单中。允许的表: {ALLOWED_TABLES}"
    
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # 列信息
        cur.execute(f"""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = %s ORDER BY ordinal_position
        """, (table_name,))
        columns = cur.fetchall()
        
        # 行数（近似值，快速）
        cur.execute(f"SELECT reltuples::bigint FROM pg_class WHERE relname = %s", (table_name,))
        row_count = cur.fetchone()[0]
        
        conn.close()
        return json.dumps({
            "table": table_name,
            "columns": [{"name": c[0], "type": c[1]} for c in columns],
            "approximate_rows": row_count
        }, ensure_ascii=False)
    except Exception as e:
        return f"错误: {str(e)}"

@mcp.tool()
def factor_health_summary() -> str:
    """获取因子健康状态概要"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("""
            SELECT factor_name, 
                   COUNT(*) as total_rows,
                   COUNT(CASE WHEN neutral_value IS NOT NULL THEN 1 END) as neutral_rows,
                   MAX(trade_date) as latest_date
            FROM factor_values 
            GROUP BY factor_name 
            ORDER BY factor_name
        """)
        rows = cur.fetchall()
        conn.close()
        
        result = []
        for r in rows:
            result.append({
                "factor": r[0], "total": r[1], 
                "neutralized": r[2], "latest": str(r[3]),
                "neutral_pct": f"{r[2]/r[1]*100:.1f}%" if r[1] > 0 else "0%"
            })
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        return f"错误: {str(e)}"

if __name__ == "__main__":
    mcp.run()
```

#### B.2 系统状态MCP Server

```python
# ~/.hermes/mcp_servers/quantmind_system_server.py
"""QuantMind System MCP Server — 日志/进程/磁盘状态"""

import subprocess
import json
import os
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("quantmind-system")

QUANTMIND_DIR = "/mnt/c/Users/xin/quantmind-v2"  # Windows路径通过WSL访问
LOG_DIR = f"{QUANTMIND_DIR}/logs"

@mcp.tool()
def check_pt_signal_log(date: str = "") -> str:
    """检查PT信号生成日志。date格式: 2026-04-13，留空=今天"""
    if not date:
        from datetime import datetime
        date = datetime.now().strftime("%Y-%m-%d")
    
    log_file = f"{LOG_DIR}/paper_trading_{date}.log"
    if not os.path.exists(log_file):
        return f"日志文件不存在: {log_file}"
    
    with open(log_file, 'r') as f:
        content = f.read()
    
    # 提取关键信息
    lines = content.split('\n')
    signal_lines = [l for l in lines if 'signal' in l.lower() or 'factor' in l.lower() or 'error' in l.lower()]
    return '\n'.join(signal_lines[-50:])  # 最后50行相关日志

@mcp.tool()
def check_disk_usage() -> str:
    """检查磁盘和数据库空间使用"""
    result = {}
    
    # 项目目录大小
    try:
        output = subprocess.check_output(['du', '-sh', QUANTMIND_DIR], text=True)
        result['project_dir'] = output.strip().split('\t')[0]
    except:
        result['project_dir'] = 'unknown'
    
    # DB大小
    try:
        import psycopg2
        conn = psycopg2.connect(host="localhost", dbname="quantmind_v2", user="xin")
        cur = conn.cursor()
        cur.execute("SELECT pg_size_pretty(pg_database_size('quantmind_v2'))")
        result['db_size'] = cur.fetchone()[0]
        conn.close()
    except:
        result['db_size'] = 'unknown'
    
    return json.dumps(result, ensure_ascii=False)

@mcp.tool()
def check_services() -> str:
    """检查QuantMind相关服务状态"""
    services = {}
    
    # FastAPI
    try:
        import urllib.request
        response = urllib.request.urlopen('http://localhost:8000/health', timeout=5)
        services['fastapi'] = json.loads(response.read())
    except:
        services['fastapi'] = 'DOWN'
    
    return json.dumps(services, ensure_ascii=False)

if __name__ == "__main__":
    mcp.run()
```

#### B.3 Hermes配置MCP

```yaml
# ~/.hermes/config.yaml 添加
mcp_servers:
  quantmind-db:
    command: python
    args: ["~/.hermes/mcp_servers/quantmind_db_server.py"]
  
  quantmind-system:
    command: python
    args: ["~/.hermes/mcp_servers/quantmind_system_server.py"]
```

#### B.4 验证MCP

微信里测试：
```
你：factor_values现在多少行了？
Hermes：[调用quantmind-db] factor_values当前约708,600,729行，241个因子。

你：PT今天正常吗？
Hermes：[调用quantmind-system] 
  FastAPI: ✅ 200 OK, all_pass=True
  最新信号日期: 2026-04-13
  持仓: 20只, 总市值约¥100万

你：磁盘还有多少空间？
Hermes：项目目录: 28GB, 数据库: 159GB
```

**Phase B 验收标准：**
- [ ] quantmind-db MCP Server运行正常
- [ ] quantmind-system MCP Server运行正常
- [ ] 微信里可以查DB数据
- [ ] 微信里可以查系统状态
- [ ] 只读查询，无写入权限

---

### Phase C: 自主学习 + Cron（30分钟）

**核心理念：不手动搬运知识，让Hermes自己读文档、自己学习、自己积累。**

#### C.1 放置项目入口文件（2分钟）

在quantmind-v2项目根目录创建`.hermes.md`：

```markdown
# quantmind-v2/.hermes.md
这是QuantMind V2量化交易系统。
核心文档在以下位置，你需要自己阅读和学习：
- CLAUDE.md — 铁律和编码规范（最重要，必须完整阅读）
- SYSTEM_STATUS.md — 当前系统状态
- docs/FACTOR_ONBOARDING_SYSTEM.md — 因子入库体系
- docs/QUANTMIND_PHASE3_ROADMAP.md — 当前执行计划
- docs/QUANTMIND_V5_UPGRADE_PLAN.md — 升级方案总览
- configs/pt_live.yaml — PT策略配置
- .claude/hooks/ — 4个自动化hook脚本，理解其逻辑
```

Hermes进入项目目录时自动加载此文件，知道去哪里找信息。

#### C.2 入职对话 — 让Hermes自主学习（20分钟）

在微信里跟Hermes对话：

```
你：请进入 /mnt/c/Users/xin/quantmind-v2 目录，
    阅读.hermes.md中列出的所有文档，完整学习项目知识。
    学完后给我一个总结，并把关键信息写入你的MEMORY.md。

Hermes：[read_file .hermes.md]
        [read_file CLAUDE.md]          → 学习30条铁律
        [read_file SYSTEM_STATUS.md]    → 学习当前PT状态
        [read_file docs/FACTOR_ONBOARDING_SYSTEM.md] → 学习9步入库流程
        [read_file docs/QUANTMIND_PHASE3_ROADMAP.md] → 学习Phase 3计划
        [read_file docs/QUANTMIND_V5_UPGRADE_PLAN.md] → 学习升级方案
        [read_file configs/pt_live.yaml] → 学习策略配置
        [read_file .claude/hooks/]       → 学习hook逻辑
        
        我已完整阅读。总结：
        - 系统运行CORE3+dv_ttm配置，OOS Sharpe=0.8659
        - 铁律30条，最关键：29(禁NaN) 30(中性化后重建缓存)
        - Phase 3进行中，3A完成(241因子)，3B数据拉取中
        - PT已重启，4因子等权+SN b=0.50+Top-20+月度
        ...
        
        [自动更新MEMORY.md — 写入所有学到的关键信息]
        [自动更新USER.md — 从文档推断用户偏好]
```

#### C.3 让Hermes做几个任务来学会流程（10分钟）

不需要写Skills——让Hermes做一次，它自动学会并创建skill：

```
你：帮我检查PT今天的信号日志

Hermes：[第一次做，自己找日志位置]
        [自动创建skill: pt_daily_check.md]
        ✅ 结果...
```

```
你：帮我对dv_ttm跑factor_health_check

Hermes：[第一次做，自己找脚本和参数]
        [自动创建skill: factor_health_check.md]
        ✅ 结果...
```

```
你：帮我查一下CORE4因子最近3个月的IC趋势

Hermes：[第一次做，自己学ic_calculator接口]
        [自动创建skill: ic_trend_check.md]
        ✅ 结果...
```

**之后这些任务Hermes就不需要重新摸索了——直接调用已有skill执行。**

#### C.4 设定Cron定时任务

在微信里用自然语言设定（Hermes已经知道怎么做了，因为C.3刚学过）：

```
你：每天17:30检查PT信号生成日志，结果发微信
你：每天09:45检查PT执行日志，结果发微信
你：每天22:00检查factor_values和klines_daily最新日期是否是今天，异常告警
你：每周日20:00对CORE4因子跑IC趋势分析，下降超30%告警
你：每月1号检查fina_indicator是否有新季报数据
```

#### C.5 自动持续学习机制

设定后，Hermes会自动：

| 机制 | 触发 | 效果 |
|------|------|------|
| MEMORY.md自更新 | 每次session结束 | 新学到的事实写入持久记忆 |
| Skills自动创建 | 完成复杂任务后 | 提取步骤→生成可复用skill |
| Skills自我改进 | 下次执行同类任务 | 对比上次→优化流程 |
| FTS5搜索 | 被问到历史问题 | 搜索所有过去session找答案 |
| Memory nudge | 定期自触发 | Agent自己检查"有什么该记住的" |
| CLAUDE.md同步 | 每周Cron | 检查CLAUDE.md是否更新→同步到MEMORY.md |

**不需要手动维护任何知识文档。Hermes自己学、自己记、自己改进。**

**Phase C 验收标准：**
- [ ] .hermes.md放置到项目根目录
- [ ] Hermes完成入职学习，MEMORY.md自动填充
- [ ] 至少做3个任务，Skills自动创建
- [ ] 5个Cron任务设定成功
- [ ] Cron首次触发并通过微信通知

---

### Phase D: 多Profile研究团队（1周）

#### D.1 创建专家Profiles

每个Profile只需要告诉它角色，让它自己去学习对应的知识：

```bash
# 因子研究专家
hermes -p factor_researcher
# 微信里说："你是QuantMind的因子研究专家，负责因子发现/评估/画像。
#  请阅读项目的CLAUDE.md和docs/，学习因子评估标准和已有结果。"
# → Hermes自己读文档，自己构建MEMORY.md

# 数据工程专家
hermes -p data_engineer
# 微信里说："你是QuantMind的数据工程专家，负责数据拉取/入库/中性化/缓存。
#  请阅读FACTOR_ONBOARDING_SYSTEM.md，学习9步pipeline。"

# 风控监控专家
hermes -p risk_manager
# 微信里说："你是QuantMind的风控监控专家，负责IC退化检测/PT监控/异常告警。
#  请阅读SYSTEM_STATUS.md和V5升级方案，学习当前基线和告警阈值。"
```

每个Profile自主学习后，会自动构建各自专属的MEMORY.md和Skills——不需要你手动写。

#### D.2 Orchestrator编排

在主Profile里设定自动化工作流：

```
你（微信）：评估最近3个月的策略表现，如果有问题搜索改进方案

Orchestrator：
  → 分派 risk_manager: 计算近3月IC趋势+MDD+PnL
  → risk_manager返回: turnover_mean_20 IC下降15%，其他稳定
  → 判断: 未达30%告警线，但需要关注
  → 分派 factor_researcher: 搜索turnover类替代因子
  → factor_researcher返回: turnover_f(IC=-0.099)可能更好，截面corr=0.78
  → 汇总报告 → 微信通知你
```

**Phase D 验收标准：**
- [ ] 3个专家Profile创建并初始化
- [ ] 每个Profile有独立MEMORY.md
- [ ] Orchestrator能分派任务给Profile
- [ ] 端到端自动工作流验证

---

### Phase E: 自进化引擎（持续进行）

#### E.1 Skills自动积累

随着使用，Hermes自动为QuantMind积累专属skills：

```
~/.hermes/skills/
├── factor_onboarding.md        # 因子入库9步pipeline
├── ic_evaluation.md            # IC评估标准流程
├── wf_validation.md            # WF验证流程
├── factor_health_check.md      # 因子健康检查
├── neutralization.md           # 中性化流程
├── parquet_rebuild.md          # Parquet缓存重建
├── pt_signal_analysis.md       # PT信号日志分析
├── tushare_data_fetch.md       # Tushare数据拉取
├── ic_decay_analysis.md        # IC衰减曲线分析
├── factor_correlation_check.md # 因子相关性检查
└── ...（自动增长）
```

#### E.2 GEPA自进化

```bash
# 克隆自进化引擎
git clone https://github.com/NousResearch/hermes-agent-self-evolution
cd hermes-agent-self-evolution

# 运行进化（优化Agent的因子研究方法论）
python evolve.py --task "quantitative_factor_research" --generations 10
```

GEPA机制：生成prompt变体→在真实任务上跑→用成功率评分→保留最优→变异→下一代。

#### E.3 Atropos轨迹微调

```bash
# 让Hermes跑100次因子研究任务
hermes batch --task-file factor_research_tasks.jsonl --output trajectories/

# 导出为训练格式
python -m hermes_agent.trajectory export trajectories/ --format sharegpt

# 用轨迹微调量化专用模型
# → 比通用Claude在量化任务上更精准
# → 用这个模型驱动Hermes → 更好的结果 → 更多轨迹 → 飞轮
```

#### E.4 Plugin Hooks

```python
# ~/.hermes/plugins/quantmind_hooks.py

from hermes_agent.plugins import HermesPlugin

class QuantMindPlugin(HermesPlugin):
    
    def on_session_end(self, session):
        """每次session结束后自动更新"""
        # 如果这次session做了因子评估，更新FACTOR_TEST_REGISTRY
        if "IC评估" in session.summary or "因子" in session.summary:
            self.agent.execute_tool("terminal", 
                "cd /mnt/c/Users/xin/quantmind-v2 && git add -A && git commit -m 'auto: update from Hermes session'")
    
    def post_llm_call(self, response):
        """LLM回复后检查是否违反铁律"""
        if "NaN" in response and "写入" in response:
            return "⚠️ 检测到可能写入NaN，铁律29禁止此操作。请确认。"
```

**Phase E 验收标准：**
- [ ] Skills数量>10个
- [ ] GEPA运行一轮进化
- [ ] 至少导出一批轨迹
- [ ] Plugin hooks正常触发

---

## 四、完整使用场景

### 场景1：日常PT监控（自动，你不需要做任何事）

```
[每天17:30 Cron自动触发]
Hermes → 微信：
  📊 PT信号报告 2026-04-14
  ✅ DailySignal 17:15 正常执行
  ✅ 4因子全加载: turnover(-1)✓ volatility(-1)✓ bp_ratio(+1)✓ dv_ttm(+1)✓
  ✅ Top-20选股完成, action=hold (非调仓日)
  📈 今日PnL: +0.42% | 累计: +1.23%

[每天09:45 Cron自动触发]  
Hermes → 微信：
  📋 PT执行报告 2026-04-14
  ✅ DailyExecute 09:31 正常
  ✅ action=hold, 无交易
  💰 持仓20只, NAV=¥1,012,345

[异常情况]
Hermes → 微信：
  🚨 PT异常告警！
  ❌ DailySignal失败: dv_ttm数据缺失
  原因: Tushare daily_basic 2026-04-14 未更新
  建议: 检查Tushare服务状态，手动重跑信号生成
```

### 场景2：随时查询（你主动问）

```
你：CORE4因子最近IC怎么样？
Hermes：[查DB + 计算]
  近3月月均IC:
  • turnover_mean_20: -0.089 (历史-0.096, ↓7%) ⚠️轻微下降
  • volatility_20: -0.085 (历史-0.091, ↓7%) ⚠️轻微下降  
  • bp_ratio: +0.055 (历史+0.059, ↓7%) 正常波动范围
  • dv_ttm: +0.028 (历史+0.028, 持平) ✅稳定
  
  结论：整体IC轻微下降但在正常波动范围内。
  如需深入分析，我可以跑IC衰减曲线。

你：factor_values里有哪些因子IC最高？
Hermes：[查DB]
  Top 10 by |IC| (cache/phase3a_ic_quickscreen.csv):
  1. high_low_range_20: IC=-0.112, t=-3.53
  2. volatility_60: IC=-0.108, t=-3.24
  3. turnover_std_20: IC=-0.102, t=-3.68
  ...
```

### 场景3：自主因子发现（终极形态）

```
你：搜索最新的A股因子论文，找到新因子方向

Hermes：
  [web_search: A股 alpha factor 2025 2026 论文]
  [读取5篇论文，提取因子公式]
  [检查MEMORY.md已关闭方向——没有重叠]
  [spawn SubAgent: data_engineer]
    → 确认数据可用
    → 拉取所需数据
    → 计算因子入库
    → 中性化 + health_check
  [spawn SubAgent: factor_researcher]
    → IC评估
    → 画像分析
    → 与CORE4相关性检查
  
  [2小时后，微信通知]
  📊 因子发现报告
  
  发现3个新方向：
  1. ✅ xxx因子 (来源: 论文A)
     IC=-0.08, t=-3.5, 与CORE4最大corr=0.32
     推荐: P1 CORE候选
     
  2. ⚠️ yyy因子 (来源: 论文B)
     IC=-0.05, t=-2.1, 未达显著性阈值
     推荐: 放入ML特征池
     
  3. ❌ zzz因子 (来源: 论文C)
     IC=-0.01, t=-0.3
     推荐: 关闭
  
  要对xxx因子跑WF验证吗？[是/否]

你：是

Hermes：
  [跑WF 5-fold验证]
  [1小时后]
  
  WF验证结果：
  • OOS Sharpe: 0.91 (+5% vs 当前0.87)
  • OOS MDD: -12.8% (改善)
  • Overfit: 0.81
  • 5fold全正
  • PASS ✅
  
  要更新PT配置吗？[是/否]

你：是

Hermes：
  [更新pt_live.yaml]
  [更新signal_engine.py]
  [commit + push]
  ✅ PT配置已更新，下次调仓日(月末)生效。
```

---

## 五、成本估算

| 项目 | 月成本 | 说明 |
|------|--------|------|
| Hermes软件 | $0 | MIT开源 |
| DeepSeek API (日常监控+查询) | ~$2-4 | Cron(~5次/天) + 交互(~10次/天) |
| GLM-5-Turbo API (复杂研究) | ~$3-6 | 因子研究/策略分析/论文解读 |
| 基础设施 | $0 | WSL2本地运行 |
| **月度总计** | **~$5-10** | DeepSeek日常 + GLM-5研究 |

对比：
| 方案 | 月成本 | 能力 |
|------|--------|------|
| 纯DeepSeek | ~$3-5 | 监控+查询+简单分析 |
| **DeepSeek+GLM-5（推荐）** | **~$5-10** | **监控+查询+复杂研究** |
| DeepSeek+Claude Sonnet | ~$15-25 | 同上但更贵 |
| 纯Claude Sonnet | ~$30-50 | 全部用顶级模型 |

对比人工：这些工作全人工做需要每天1-2小时 × 30天 = 30-60小时/月

---

## 六、风险控制

| 风险 | 严重性 | 缓解措施 |
|------|--------|---------|
| LLM幻觉导致误操作 | 高 | MCP只读 + PT操作需人工审批 |
| 微信iLink协议变化 | 中 | 关注Hermes更新 + 备选Telegram |
| WSL2稳定性 | 中 | systemd自动重启 + 断线重连 |
| DB凭证暴露 | 中 | MCP Server限制只读+白名单表 |
| API成本失控 | 低 | DeepSeek($0.27/M)+GLM-5($0.96/M)都很便宜 + 设月度预算上限 |
| 与QMT资源竞争 | 低 | Hermes资源占用极小 |
| 项目新(2026/02) | 中 | 先只读监控，验证稳定后再扩展 |

**核心安全原则：Hermes先做"只读观察者"（Phase A-C），验证稳定后再升级为"执行者"（Phase D-E）。**

---

## 七、时间线

```
Week 0 (4/12-4/13):
  ✅ 方案设计(本文档)
  → Phase A: 安装+微信连接 (半天)
  → Phase B: MCP连接 (半天)

Week 1 (4/14-4/18):
  → Phase C: .hermes.md + 入职对话 + Cron (30分钟)
  → Hermes自主学习项目文档，自动积累Skills
  → 验证Cron正常触发
  → 同时Phase 3因子扩展继续进行

Week 2-3 (4/21-5/2):
  → Phase D: 多Profile（告诉角色，让它们自己学习）
  → 让Hermes参与Phase 3C/3D因子研究
  → Skills持续自动积累和改进

Month 2+:
  → Phase E: 自进化引擎
  → GEPA优化
  → 轨迹微调
  → Hermes越来越懂QuantMind，越用越强
```

---

## 八、与Phase 3 Roadmap的协同

| Phase 3任务 | Hermes参与方式 |
|-------------|---------------|
| 3.0 PT监控 | Cron自动监控(Phase C) |
| 3A 因子扩展 | CC执行，Hermes监控进度+通知结果 |
| 3B 数据入库 | CC执行，Hermes检查数据完整性 |
| 3C 因子分类 | Hermes Factor Researcher分析 |
| 3D ML合成 | CC执行，Hermes评估结果 |
| 3E Kronos/DSL | CC执行，Hermes搜索论文+评估 |
| 3F PEAD | Hermes提醒4/20数据可用 |
| 3G 自动化 | Hermes取代大部分自动化需求 |
