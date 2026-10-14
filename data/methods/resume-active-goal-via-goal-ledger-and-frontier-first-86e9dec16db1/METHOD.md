---
method_id: resume-active-goal-via-goal-ledger-and-frontier-first-86e9dec16db1
name: resume-active-goal-via-goal-ledger-and-frontier-first
description: 存在活动 goal 的续跑：goal 回执本身是中断点的一等账本——tasks: N open / M 给出精确剩余量，checkpoint 给出已完成里程碑，spec_change_ref 直接点名权威文档路径；再加一跳 Task Frontier 即得 open task 名、依赖与 revised 标记。此时对 evidence 库取样、全库文件名搜索、关键词文档搜索等宽恢复动作对『停点在哪』的边际信息为零，只会产出截断列表与 miss。in_progress 任务的『实际做到哪、哪些产物已过期』用 git 提交时间戳 × 产物 mtime 对齐判定：产物早于最后修复提交即失效，只重做失效集；修复影响面窄且消费方单一时，可局部复绿替代全量重跑。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a2f05599-54ef-4df0-83ac-5403f3fbc184:1119:35b5382e28a9e83993b1
evidence_refs: learning:learn:4704a53632c3
created_at: 2026-10-13T14:44:55.716901+08:00
updated_at: 2026-10-13T14:44:55.716901+08:00
---
## Trigger
用户发极简续跑指令（如『继续』）且存在活动 goal：goal 回执已含 tasks: N open / M、checkpoint 摘要与 spec_change_ref 精确路径（与『无活动 goal』的续跑情形互斥）。

## Discriminator
goal 回执的结构化字段（open 计数、checkpoint、spec_change_ref）加上一次 Task Frontier 视图，是否已能唯一确定剩余任务、依赖与停点；若能，则 evidence 流取样/全库 search_files/关键词 search_docs 对『停点在哪』这一未知量的信息量为零或负（截断+miss）。本集 goal 回执在宽枚举前已显式给出：2 open / 6、M0/M1 checkpoint、spec 文档精确路径。

## Short path
- 读活动 goal 回执 → 未知量『还剩多少、权威 spec 在哪』：tasks 计数与 spec_change_ref 字段直接回答，无需任何搜索
- 一跳 Task Frontier / goal task 视图 → 未知量『哪几个 open、停在哪』：得到 open task 名、waiting 依赖、done/revised 标记
- git log 时间戳 × 产物目录 mtime 对齐 → 未知量『in_progress 任务实际停点、哪些验收产物过期』：晚于产物时间的修复提交使旧产物失效（如 m4_final 早于终审修复提交，需 m4_final2 新快照）
- 只读 spec_change_ref 指向文档中被 frontier 点名需求对应的小节 → 未知量『验收口径』
- 执行剩余收尾并对每项取机械回执；所有未知量闭环后停止恢复类动作

## Stop conditions
- Task Frontier 显示 0 open / completion_ready=true → 只做收口与归档验证，不再做任何恢复枚举
- 剩余任务、实际停点、过期产物集三个未知量均被 goal 账本或时间戳对齐回答 → 停止恢复动作，转入执行

## Verification
- 任务图声明与 git/产物时间戳一致：in_progress 任务的产物若早于最后一次修复提交，必须修复后复跑新快照，不得引用旧产物当验收证据
- 每个收尾动作有机械回执（测试通过数/提交 hash/goal 状态翻转），最终 goal 回执确认 completed 且 spec_archive 过核验
- 局部复绿替代全量重跑时，须能指出修复的变更面与唯一消费方（如修复仅动数据文件且仅一个测试消费）

## Counterexamples
- 无活动 goal 的『继续』：goal 账本不存在，应走已点名的环境 provenance 边（search-miss 回执参考、点名备忘、git delta），即 resume-continuation-via-named-provenance-and-git-delta 管辖的情形，勿套用本卡
- goal 回执字段缺失或明显过时（checkpoint 为空、task 图长期未维护）：结构化账本不可信，需 evidence/git 恢复
- 未知量是未进 task 图的临时变更（untracked 文件、未提交的临时修复）：Task Frontier 答不了，应查 git status / evidence 流
- 需要理解 spec 语义细节时：直接读 spec_change_ref 指向文档的相关小节，而不是对文档库做关键词搜索
