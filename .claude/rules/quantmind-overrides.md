# QuantMind项目专属规则（覆盖ECC通用规则）

## 测试规则
- 研究脚本（scripts/research_*.py）不需要写测试
- 生产代码（backend/app/, backend/engines/）需要测试但不强制TDD
- 因子计算脚本优先保证正确性，测试其次
- 不要为一次性分析脚本添加pytest

## 数据库安全
- 重数据任务最多2个Python进程并发（铁律9，PG OOM教训）
- ALTER TABLE前检查pg_stat_activity中的活跃连接和锁
- factor_values批量写入用execute_values，每批5000行
- 所有IC计算结果必须写入factor_ic_history（铁律11）

## 因子研究
- forward return从T+1入场（A股T+1制度），不用T日收盘价
- 因子预处理顺序固定：去极值(MAD 5σ) → 填充(行业中位数) → 中性化(行业+市值WLS) → z-score
- 新因子必须附带经济机制描述（铁律13）
- t > 2.5 硬性下限（Harvey Liu Zhu 2016）

## 代码风格
- Python: sync psycopg2, Service内部不commit
- Engine层 = 纯计算, 无IO, 无数据库访问
- 金融金额用Decimal
- 遵循项目CLAUDE.md中的所有规则，CLAUDE.md与ECC冲突时以CLAUDE.md为准

## 不适用的ECC功能
- TDD模式：研究脚本不适用，不要自动激活
- TypeScript/Go/Java reviewer：项目是Python-first
- E2E测试：不做浏览器端到端测试
- Node.js规则：前端用npm但核心是Python后端
