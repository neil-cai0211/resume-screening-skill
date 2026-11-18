# 去重与候选编号台账（模板）

真实台账只放在仓库外的私有工作区，不要把真实邮件 id、附件哈希或候选人记录提交进本仓库。

去重键（命中任一即视为已处理）：附件 sha256、邮件 id、姓名+最近一段公司。同名用学校和公司区分。候选编号累计，不要重置。

格式：

```
邮件id | 编号 | YYYY-MM-DD HH:MM（Asia/Shanghai） 结论摘要；sha256=...
```

虚构示例：

```
msg-example-001 | 001 | 2026-11-18 10:05 不合适 36分；sha256=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
msg-example-002 | 002 | 2026-11-18 10:08 推荐面试 61分，待17:30发送；sha256=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
```
