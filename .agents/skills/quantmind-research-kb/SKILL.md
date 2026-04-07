---
name: quantmind-research-kb
description: 研究知识库管理。自动归档研究结论、实验记录、失败方向。新研究前自动检查是否重复已失败方向。
---

# QuantMind Research Knowledge Base

## 目录结构
```
docs/research-kb/
  decisions/     # 关键决策及理由
  experiments/   # 实验记录
  findings/      # 可复用研究发现
  failed/        # 已证明无效的方向（最重要）
  literature/    # 参考论文笔记
```

## 触发条件
- 研究脚本完成后自动归档
- 用户说"记录结论"、"归档实验"、"更新知识库"

## 开始新研究前自动检查
搜索 docs/research-kb/failed/ 中所有文件，关键词匹配当前方向。
如果找到匹配 → 显示失败原因，询问是否继续。

## 归档格式

### failed/ 格式
```markdown
# 失败方向: [标题]
- 日期: YYYY-MM-DD
- 假设: [原始假设]
- 实验: [做了什么]
- 结果: [具体数字]
- 失败原因: [为什么不work]
- 适用条件: [结论成立的条件]
- 不应重复的变体: [类似方向]
```

### findings/ 格式
```markdown
# 发现: [标题]
- 日期: YYYY-MM-DD
- 证据: [数据支持]
- 应用: [如何使用]
```

### decisions/ 格式
```markdown
# 决策: [标题]
- 日期: YYYY-MM-DD
- 选项: [考虑的选项]
- 决策: [最终选择]
- 理由: [为什么]
```
