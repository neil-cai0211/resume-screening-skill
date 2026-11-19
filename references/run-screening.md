# 执行指南

设定发布仓库外的私有目录 `WORK`。命令中的 `PROFILE` 是已确认的岗位 JSON 文件，`DELIVERY` 是私有发送配置。它的结构见 [模拟配置](../examples/delivery.demo.json)，使用真实授权组织中核实过的一对一收件人 ID、显示名和查询值。当天工作日以发送配置里的星期及运行方维护的工作日历为准。岗位启用后可由现有调度器发起收件、评分和发送两种轮次。常用参数见 [配置示例](../config.example.md)。

## 收件与评分

1. 将已启用且纳入本批的岗位传给 `python scripts/screen.py route PROFILE ... --signal 完整岗位名`。可重复提供可信投递信号，或用 `--role 岗位号` 显式指定。收到 `needs_confirmation` 时先确认归属。专用邮箱、投递文件夹可映射成岗位号。正文里的职位关键词不能代替投递元信息。
2. 用只读邮箱连接器收取附件或处理指定本地目录。将一封邮件的每个附件分别登记。岗位内先匹配已核实的候选人编号，初次投递由运行方分配并保留编号。遇到同名或候选人归属冲突，核实后再继续。取原件并转 PDF，提取文本，去除联系方式、证件号和住址。有正文但缺原简历的投递可暂存在私有待补材料清单，取得 PDF 后再登记；单独执行旧 P001 入口时按原流程处理。扫描件须核查 OCR 质量。
3. 执行 `python scripts/screen.py --work WORK register PROFILE 候选号 姓名 最近公司 简历.pdf 脱敏文本.txt --source 投递唯一标识`。同岗位重复附件返回 `duplicate`，编号不一致返回 `id_conflict`。同一编号的新内容创建下一版。未评分记录继续排队，旧版记录不进入新批次。
4. 对 `python scripts/screen.py --work WORK queue PROFILE` 返回的评分条目，运行 `python scripts/screen.py prompt PROFILE 脱敏文本路径`，将提示词写成 UTF-8，保存到 `WB_WORK/prompts/{评估任务键}.prompt.txt`。评估任务键由队列给出，重试附加唯一后缀，避免拿到旧会话结果。调用现有 `python scripts/run_one.py 评估任务键`，然后用相同任务键运行 `python scripts/extract_result.py 评估任务键`。默认使用仓库原有 Workbuddy 运行参数，用户指定时遵从授权配置。模型不出分或结果缺证据时可精简输入或纠正 JSON，最多重试 3 次，仍失败就汇报，并保留待评分条目。
5. 执行 `python scripts/screen.py --work WORK record PROFILE 候选号 简历版本 WB_WORK/raw/评估任务键.result.json`。脚本核对字段、分值与证据原句后计算总分和结论。只有本岗位当前简历、当前标准、结论为推荐的记录能进入新批次。模型判定依据和短评需做内容核对。评分只使用岗位确认的规则，门槛不足和材料缺失如实记录。

## 预览和发送

1. `python scripts/screen.py --work WORK preview PROFILE DELIVERY` 生成评价、PDF ZIP、候选人和收件人清单及预览校验码。`empty` 表示无需产生新批次。已预览批次见 `queue PROFILE`。
2. 展示实际评价、压缩包、收件人及发送时段，让授权用户确认首批与后续按同一规则自动发送。收到确认后执行 `python scripts/screen.py --work WORK authorize PROFILE DELIVERY 批次号 校验码 --confirmation 确认记录`。已有授权也要在发送前核对配置。私有配置变化后重新走首批预览。
3. 发送轮次在授权时段内执行。用户当场明确要求即时发送时，登记 `--manual-confirmation 确认记录`。对确有待发项的每位面试官，先按配置查询身份，核对同一钉钉组织下的真实 ID。未唯一匹配、与预览身份不符或权限异常均暂停该收件人。
4. 先评价后附件。每次动作先执行 `python scripts/screen.py --work WORK reserve PROFILE DELIVERY 批次号 收件人ID message`，附件把 `message` 换成 `attachment`。只有返回 `ready` 才执行一次发送，使用返回的文件和同一个已核对 ID，收到文件的一端也要校验 SHA256。加载当前安装的钉钉消息能力，按实际命令契约通过 dws 发至该 ID 的单聊。确认文本和文件两种消息均支持固定到相同 ID 后再开始。按身份、内容和回执核对是否成功。失败时保持同账号、同渠道，联系不上原发送环境时汇报。
5. 有确切回执后执行 `python scripts/screen.py --work WORK ack 批次号 收件人ID 材料类型 操作号 sent --receipt 回执记录`。明确未送达时写 `failed`，下一次仅重新领取该项。网络超时或是否投递未知时保持 `sending`，先查询消息再登记确切结果。重复领取已送达或状态不明的项不会再次返回 `ready`。
6. `python scripts/screen.py --work WORK status 批次号` 显示预览目录、校验码和每位面试官的两项状态。只有都送达才记本轮完成。若尚无已送达或状态不明的项，可用 `release 批次号` 释放旧预览中的简历，更新配置后重新打包。已分配序号会保留间隔。若已部分送达且配置或接收者变更，报告已送达对象和缺项，由用户决定后续处理。
7. 向用户汇报新评人数、推荐与待定、发送结果和卡点。发送不需要推送的空批次不生成消息。遇到评分引擎、邮箱、发送端不可用时，报告受影响范围和待处理记录。

## 模拟验收与 P001 迁移

在所有命令的子命令前加入 `--demo`，评分、包和台账会写入模拟工作区，不能授权发送。试用 [电话销售岗位配置](../examples/DEMO-SALES.json) 和 [模拟面试官配置](../examples/delivery.demo.json)，只用虚构简历。

P001 的现有任务可继续依据 [P001 v4.7 执行方案](p001-workflow.md) 使用。通用流程参照 [P001 v4.7 配置](../examples/P001.json)。新入口优先按评分表第五节判分，保留 55 分推荐线、否决规则、履历未更新处理、三栏目和包结构。上线前核对实际人选的迁移策略、历史台账、上一推荐序号、未发送记录和待核实规则。经用户确认切换后，将起始推荐序号设为历史最大值加一，并只接手双方核对过的新增投递与未发批次，避免两套任务同时推送。
