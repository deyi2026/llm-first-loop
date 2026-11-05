---
method_id: approval-receipt-item-execute-from-pipeline-ledger-anchor-paths-in-cwd-0f06277b7813
name: approval-receipt-item-execute-from-pipeline-ledger-anchor-paths-in-cwd
description: 带精确ID的审批回执要求核实后执行一项管线变更时：先 pending_actions 核对状态并从 hint 取子系统名；用该ID在子系统 append-only 审计台账（如 data/audit/）grep 一行取提案全文（建议项/边界/影响面），再从提案具名符号定向映射 src 改动面并逐项验证。所有文件路径以 pwd/provenance 锚定，不使用任何无回执出处的绝对路径。可免去：猜路径 grep、重复检索记录摘要、先于提案全文的宽语义源码搜索。
aliases: 审批通过的演进去哪个文件找全文, 执行 EVO 前先读审计台账原文, 提案建议逐条落地成代码改动点, grep 猜绝对路径扑空后先 pwd, 先拿提案全文再动源码
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:924c084a-15a9-4599-8ec2-dbeb07e01797:180:664512840ca4631e7d58
evidence_refs: learning:learn:4bb44509132e
created_at: 2026-11-04T16:22:25.048931+08:00
updated_at: 2026-11-04T16:22:25.048931+08:00
---
## Trigger
外部审批回执（人工面板批准）带精确 ID 通知某管线条目（演进/变更单）进入执行态，任务要求核实后忠实执行；记录检索已命中该条目但正文被截断，缺建议项与边界全文

## Discriminator
两个已在手的事实把搜索空间缩到一行：pending_actions 的 hint 点名了完成工具所属子系统（如 evolution_complete），且检索命中记录自带类型标签与完整 ts——二者共同指明提案全文就在该子系统的 append-only 台账里，ID 即行键。同时：若此前没有任何工具输出给出过仓库绝对路径，则命令中出现的任何绝对路径都是无出处猜测，真实工作根只能由 pwd/回执路径锚定

## Short path
- pending_actions 一次：核对执行中条目数与审批回执一致，从 hint 提取子系统名
- pwd 确定真实工作根；ls 该子系统的审计目录（如 data/audit/）一次，按文件名定位 append-only 台账
- 用回执中的精确 ID 在台账 grep 一行，读取提案全文：建议项 a/b/c、边界、影响面、impact_files
- 从提案正文逐字提取具名符号（字段名/枚举/校验名/统计名），逐符号在 src/ 定向 grep，得到改动点清单
- 逐建议项实现并各配验证；收紧校验类改动应先在真实门禁看到旧调用点被新校验拒绝，补齐后转绿
- 跑门禁全链路通过后执行完成登记动作，停止，不再追加取证

## Stop conditions
- 提案全文已从台账原行取得且行内状态与审批回执一致
- 提案每条建议项都有对应改动点与验证回执，完成登记成功后即停止

## Verification
- 台账行的 ID/ts 与检索命中记录一致，确认取到的是同一原行而非转述摘要
- 完成登记能逐条对应提案建议项；门禁回执为通过
- 校验收紧类改动若全程绿且从未拦下任何旧调用点，应怀疑护栏未真正生效并补测

## Counterexamples
- 检索命中已返回完整未截断正文（含全部建议项与边界）时，无需再定位台账文件，直接进入符号映射
- 提案是纯政策/规则文本、不含可 grep 的具名符号时，符号定向映射不适用，须按语义面定位改动处
- cwd 不是仓库根（外部沙箱/宿主代理）时，pwd 相对检索失效，应从部署回执或 git 配置解出仓库根，而不是换另一个猜测的绝对路径
- 仅改文档、不触碰校验链路的变更，不需要『先红后绿』的护栏验证
