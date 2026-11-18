# 运行配置示例（不要把真实值提交进 git）

复制本文件为仓库外的 `config.local.md`，或改用环境变量。下面都是占位符。

```bash
# 只读招聘邮箱（当前实践中的账号写在私有配置，不要填回本仓库）
export GMAIL_ACCOUNT="<GMAIL_ACCOUNT>"
export RESUME_SINCE="2026-11-06"

# 用于发送钉钉的用户笔记本
export LAPTOP_MACHINE_ID="<LAPTOP_MACHINE_ID>"
export DWS_PATH="<DWS_PATH>"
export HIRING_MANAGER_QUERY="<HIRING_MANAGER_QUERY>"

# Workbuddy
export WB_CLI="<WB_CLI>"
export WB_MODEL="hy4flash-free"
export WB_WORK="<WB_WORK>"
export WB_SESSION_DIR="<WB_SESSION_DIR>"
export WB_TIMEOUT_S="1800"
export CODEBUDDY_INTERNET_ENVIRONMENT="internal"
```

说明：

- 邮箱连接器必须保持只读。
- `WB_MODEL` 默认使用免费的 `hy4flash-free`。不要改成付费模型，除非用户当场指定。
- dws 每次发送前都要按 `HIRING_MANAGER_QUERY` 重新搜索，唯一命中后再发。
