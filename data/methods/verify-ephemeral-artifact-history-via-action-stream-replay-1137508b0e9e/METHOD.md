---
method_id: verify-ephemeral-artifact-history-via-action-stream-replay-1137508b0e9e
name: verify-ephemeral-artifact-history-via-action-stream-replay
description: 落经验卡/定稿结论前需回核一次已结束、可能已被清理的做法（如 worktree 里的临时证据文件）时，先用产物精确名查动作/事件流，而不是全库文件扫描或换关键词反复查 evidence/archive：写入、门禁回执、放行与清理都记录在 action_trace 里，一次查询即可闭合时间线；写卡时按直核（事件回放）与转述（二手记录）分档标注证据。
aliases: 文件被worktree清理了去哪找回现场, 落卡前回放当时操作核实, 查已删除文件当时的写入和PASS回执, 经验卡证据分直核还是转述, 按精确文件名翻动作日志
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:95500c09-6f2a-4a06-babc-88afd527db4d:314:f38e0dceb7eca0e538f7
evidence_refs: learning:learn:464e4f1b9586
created_at: 2026-10-31T21:10:22.568736+08:00
updated_at: 2026-10-31T21:10:22.568736+08:00
---
## Trigger
要在落经验卡/写结论前回核一次已结束做法的现场（精确路径、写入时间、门禁 PASS 回执），而该做法由被记录的 agent 动作（execute_command/heredoc 写文件、worktree 增删）完成，产物本体可能已随清理消失

## Discriminator
用户请求原文已给出精确罕见的产物名，并指明该做法发生在刚才的任务流（同 session 谱系）——写入动作必然已进 action_trace/event_stream；而 Evidence/record 检索按任务主题组织、看不到原始命令事件，含 .releases/.worktrees 镜像目录的仓库全库文件名扫描既超时又注定扑空（文件已被清理）

## Short path
- 从请求原文提取精确 token：产物文件名 + 关键动作词（写入/门禁/推送）
- 用精确 token 查 event_stream/action_trace，一次拿到写入事件的精确路径与时间戳
- 沿同一 session 时间轴取后续事件，闭合时间线：写入→审查 start/verdict→放行→清理
- 一条只读命令（ls/find）确认文件现状；不在则以事件流为权威现场，不再继续扫文件系统
- search_records 做防重与前身卡检索（语义近邻仍走 record store，事件流替代不了）
- save_experience 时按证据档位标注：直核=事件回放对上时间戳；转述=二手 memory/上轮总结

## Stop conditions
- 时间线闭合：产物创建→门禁 PASS 回执→生效动作→清理均与事件流时间戳/路径一致
- 防重检索完成，前身记录（memory/suggestion 原文）已找到并在卡内引用
- 卡内每条关键断言都已标明直核或转述档位，未用二手记录冒充直核

## Verification
- 事件流回放出的路径与时间戳与卡内叙述逐字一致
- 外部结果（远端 sha、CI 状态）用各自权威面复核，不拿事件流冒充外部事实
- 若文件仍存在，抽读一份核对内容与事件流中的写入命令一致

## Counterexamples
- 产物仍在磁盘且可直接定位：读文件与 git 历史更权威更短，无需回放事件流
- 要核的是外部世界结果（远端分支状态、CI 结论）：事件流只证明命令发出过，不证明结果
- 目的是语义防重、找相近前身卡：record store 语义检索才是正确通道，事件流查不到语义近邻
