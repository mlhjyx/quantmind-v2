# Pre-Commit Checklist

commit之前必须完成：

1. `ruff check` + `ruff format` 通过
2. `grep` 确认无新增硬编码凭据（`psycopg2.connect` / `password`）
3. 确认PT状态未被意外改变
4. `git diff --stat` 审查变更列表，无意外修改
5. commit message包含：改了什么 + 为什么 + 影响范围
