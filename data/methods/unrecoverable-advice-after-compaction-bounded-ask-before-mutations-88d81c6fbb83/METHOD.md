---
method_id: unrecoverable-advice-after-compaction-bounded-ask-before-mutations-88d81c6fbb83
name: unrecoverable-advice-after-compaction-bounded-ask-before-mutations
description: 上下文压缩后收到极简续跑指令（如『继续』）、且上一轮建议决定后续分支时：第一步先并行探测全部会话状态面（task_state、compaction manifest、message_flow/goal），而不是先去水合 evidence。三面全空回执即证明建议原文只存在于已丢失的对话——evidence 账本仅持久化工具观察（source 均为 execute_command/subagent_result 等），任何换措辞搜索都无解。随即停止寻找原文，按已有账本尾部方法重建已完成工作、完成全部只读收尾（综合对照、落 lesson、完整性核查），再把会写账本/提交记录的分支枚举成 A/B 类有限选项交用户裁决。核心收益：把『继续找原文』的无效搜索归零，并把擅自变更持久数据的风险换成一次有界询问。
aliases: 压缩后上一条建议找不回来了怎么办, 继续指令但查不到之前建议的内容, task state 和 compaction manifest 都没有还能恢复吗, 要改账本但用户没确认过该不该等, 上下文丢了哪些内容其实找不回
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:924c084a-15a9-4599-8ec2-dbeb07e01797:86:29b79a2a2a2638f9e689
evidence_refs: learning:learn:f19a6274b0db
created_at: 2026-11-04T15:25:33.952105+08:00
updated_at: 2026-11-04T15:25:33.952105+08:00
---
## Trigger
极简续跑指令（『继续』类）落在上下文压缩/会话状态丢失之后，上一轮建议或决定点决定后续走向，且至少一个候选分支会实质改动持久数据（账本更正、净分变化、记录提交）

## Discriminator
会话状态面的回执组合可判定原文是否可恢复：task_state『not found』+ compaction manifest『not found』+ message_flow 为空/goal 无记录。同时 list_evidence 可见条目的 source 全部是工具观察类（execute_command、subagent_result、search_records 等），不含助手对话文本——一旦状态面全空，上一轮建议文本在任何持久化面都不存在，为找回它而继续搜索必然无解。

## Short path
- 第一步并行探测全部会话状态面（task_state、compaction manifest、message_flow/goal），未知量：待续指令原文是否存在于任何持久化面；
- 任一面命中原文 → 直接按原文续跑，本方法退出；
- 全部空回执 → 判定原文不可恢复，立即停止任何为找回它而做的换措辞搜索或额外水合；
- 按账本尾部重建已完成工作（list_evidence → 倒序水合末尾的 result 类条目），未知量：哪些工作已收口、结论是什么；
- 执行全部只读/可逆收尾：盲评对照综合、落 lesson、数据完整性核查；
- 把会写账本/提交记录的分支枚举成有限选项（A/B/AB 式）呈报用户裁决，绝不擅自执行变更分支，也不代替用户猜原建议是哪一条。

## Stop conditions
- 任一状态面回执包含待续建议原文（改为按原文执行，本方法退出）
- 所有只读收尾完成且变更分支已枚举呈报（停止，等待用户选择）
- 发现被扣留的分支实为纯只读（直接执行并在回报中标注，不必询问）

## Verification
- 呈报前重读每个被扣留分支的写入语义，确认其确会改动持久数据（账本净分/记录提交），只读项不得扣留
- 确认没有未探测的对话状态面：task_state、compaction manifest、message_flow、goal checkpoint 均已拿到明确回执
- 用户选定后按该分支执行，并在回报中说明原文本不可恢复的依据（各面回执），避免用户误以为可再找回

## Counterexamples
- compaction manifest 命中且含建议原文 → 水合原文直接续跑，不问用户
- 存在 goal/checkpoint 快照记录了待办管道 → 按快照续跑（属账本尾部重建/陈旧快照核对类方法的场景），不由本方法接管
- 全部待续动作只读且可逆 → 选最可能的解释直接执行并标注假设，不打断用户
- 建议已被上一轮落成 experience/记录条目 → 先检索记录库找回结构化版本，再决定是否仍需询问
