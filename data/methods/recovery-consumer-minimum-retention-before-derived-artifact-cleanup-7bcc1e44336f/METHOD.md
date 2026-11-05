---
method_id: recovery-consumer-minimum-retention-before-derived-artifact-cleanup-7bcc1e44336f
name: recovery-consumer-minimum-retention-before-derived-artifact-cleanup
description: 执行书面清理计划、批量删除某机制的派生工件（release checkout、快照树、归档目录）时，保留量不能只信计划字面值：先读『消费这些工件的恢复机制』源码（回滚 known-good 查找、应急脚本入口），确认其最小在位需求与 miss 行为——若它只认在场目录、找不到就返回 None 放弃且不触发自动重建，则『工件可由 git 幂等重建』不等于『恢复路径可用』。保留集应取机制需求（现役+最近若干条恢复目标）而非计划数字，偏离须显式声明理由；删除后重跑机制查找复测仍命中，并做一次重建探针把可恢复性变成实测。
aliases: 删 release 前先看回滚要留几棵, 只留现役一棵会不会断回滚, 清理计划保留数和恢复机制对不上, 删快照归档前查应急入口在位需求, 回滚目标被清掉后 restart 失败怎么办
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:dc65c21c-3531-46e5-a85e-a6b3e5e358a7:981:df691109491f8f83bbc6
evidence_refs: learning:learn:844545169d9d
created_at: 2026-11-05T17:17:26.177607+08:00
updated_at: 2026-11-05T17:17:26.177607+08:00
---
## Trigger
把既定清理/瘦身计划执行成批量删除，待删对象是派生工件（如 .releases/<sha> 检出、机器生成快照/归档树），且系统存在会在磁盘上按路径寻找这些工件的恢复/回滚/应急机制

## Discriminator
删除前即可从源码读到的两个事实：①恢复机制的候选接受条件是『目录（含其脚本）仍在场』，miss 时返回 None/放弃回滚而不是自动重建；②计划保留量（如只留现役一棵）低于该机制的最小在位集。这两个事实足以把『按计划删』与『保留到机制可用』区分开，无需事后验证

## Short path
- 机械复核计划的目标集断言（脏文件、ref 可达性、目录名与 HEAD 一致），不沿用文档结论
- 定位会消费待删工件的恢复机制源码，读清三件事：候选接受条件、miss 行为（自动重建还是返回 None）、最小在位集多大
- 保留集 = max(计划保留, 机制最小需求)；与计划的偏离及代码依据写进最终汇报
- 删除脚本先落盘成文件再执行（沿用同 run 已放行的姿势），逐棵记录 REMOVED/FAIL/SKIP
- 删后复测：重跑机制的目标解析确认仍命中保留条目；抽一棵已删 sha 做幂等重建探针后清理；现役服务 pid/head/generation 前后不变

## Stop conditions
- 恢复机制查找仍命中保留的最近恢复目标（回滚路未失效）且现役服务 alive/head 不变，即达成本步，停止扩大核查
- 若查明无任何机制消费该类工件（查找代码与引用均无命中），按计划保留量执行即止

## Verification
- 删除后重跑恢复机制的目标解析（如 known-good 扫描），确认仍命中保留条目
- 对一棵已删 sha 执行幂等物化/重建探针：tracked 文件数与关键脚本齐全后清理探针树，可恢复性以实测为准
- 对照删除前后现役服务的 pid、git_head、generation 与 alive 状态

## Counterexamples
- 恢复机制在 miss 时会自动幂等重建工件（materialize-on-demand），此时按计划最小保留即可，多留只是占盘
- 待删工件不存在任何恢复/回滚消费方（无查找代码、无应急入口引用），只需护栏核查后照计划删
- 保留工件不参与任何生命周期判断且成本可忽略时，『多留几条』本身不是方法收益，不要把多留当默认答案
