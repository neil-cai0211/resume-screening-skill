# 简历筛选与推荐技能

把招聘岗位资料整理成可确认的评分标准，再按岗位筛选简历，生成面试官评价与推荐 PDF 包。新增同类岗位通过配置接入。执行入口为 [SKILL.md](SKILL.md)。

## 用法

1. 从对话、文档或指定的薪人薪事职位描述建立评分标准，交招聘方确认。见 [岗位配置与确认](references/build-role.md)。
2. 用已确认的岗位配置识别投递、调用 Codex 评分并核对证据。生成私有台账和推荐预览。见 [执行指南](references/run-screening.md)。
3. 预览通过后，在授权时段发给已确认的面试官。分别核对评价和附件的回执。

仓库有两份脱敏示例。 [P001 后端研发经理](examples/P001.json) 包含 v4.7 专用评分、门槛与三维度对外评语。 [电话销售代表](examples/DEMO-SALES.json) 是用于验证复用的草案，初面 SOP 中的现场核实项仍在初面环节处理。

## 测试

需要 Python 3.10+，评分校验、打包和发送状态只用标准库。

```text
python -m unittest discover -s tests -v
```

测试使用虚构简历、评分和回执。真实运行由有权限的 Agent 调用邮箱、Codex、Ego Lite 和钉钉等本机能力。运行参数见 [config.example.md](config.example.md)。实际简历、投递来源、收件人和处理台账保存在私有工作区。

现有 P001 定时任务执行口径见 [P001 v4.7](references/p001-workflow.md)。迁移到通用入口前，先按执行指南对照历史序号、未发批次和模拟结果。
