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


## 通用岗位版

在仓库外保留私有工作目录，下面的路径与组织身份由运行方配置：

- 已启用岗位列表及各自的岗位标准 JSON。结构见示例目录。配置在招聘方确认后使用。
- 每个岗位的单聊收件人、发送时间和起始序号 JSON。参照 examples/delivery.demo.json 的字段，将收件人设为当前组织内已确认的单聊身份。首批预览通过后才登记自动发送授权。
- 招聘邮箱的授权范围、邮箱搜索条件和投递入口到岗位的映射。岗位排程由当前运行方配置。P001 旧任务的 10:00 / 17:30 仅表示该岗位的现行安排。
- Workbuddy 私有目录用 WB_WORK 指定。筛选脚本的 --work 指向私有筛选工作区，里面的 live 或 demo 子目录记录各岗位的评分、批次与回执。