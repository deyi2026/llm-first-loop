---
method_id: wip-ownership-by-freshness-not-history-fbad1497a281
name: wip-ownership-by-freshness-not-history
description: 共享工作树存在多方并发会话时，任何树变更（commit/stash/revert）前先用“当前新鲜度”判定无关 M 文件的归属：对比文件 mtime 与各会话 lock/日志的新鲜度，而不是回溯事件流关键词搜索；服务 build 报告里的 git_dirty/head 只是进程启动时快照，工作树真相必须用直接 git status 实核。若 mtime 是分钟级且锁文件新鲜→第三方正在活跃写入，其 WIP 不碰、不 stash、不吸收，只以显式路径提交自己的产物，并在文档记录解释边界。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:1477:2bf774230fe743a8d74d
evidence_refs: learning:learn:3b2722693423
created_at: 2026-09-18T19:29:02.334519+00:00
updated_at: 2026-09-18T19:29:02.334519+00:00
---
## Trigger
共享/多会话工作树中，自己的提交需与他人的未提交 M/?? 文件共存处理；或服务状态快照字段（如 git_dirty=false）与疑似当前树状态矛盾；或两次相邻观察之间无关文件集合仍在增长。

## Discriminator
相邻两次观察之间无关 M 文件集合在增长（如 3→5，且新文件带配套测试）——写入者是“现在进行时”的活跃方。分钟级 mtime + 同期新鲜 lock 即为充分的归属证据；历史事件流搜索只能证明过去发生过什么，无法判定“现在是否还在写”。

## Short path
- 直接 git status 取当前树真相；服务 build 快照字段仅当启动时参考，与现状矛盾时不采信任一侧。
- 观察到无关文件集合增长→假设存在活跃第三方；stat 这些文件的 mtime 并列事件目录 lock/日志 mtime 做归属判定，不做历史内容关键词搜索。
- 若新鲜→判为活跃他人 WIP：不 stash、不还原、不纳入提交；仅对自己的产物做安全核验（如 grep 写操作确认只读）。
- 以显式路径提交自己的文件；提交后核对他人 M 文件原样未动。
- 把解释边界（如测量污染说明）写入预登记文档，挂后续检查点，停止对该第三方的进一步枚举。

## Stop conditions
- 归属已由新鲜度证据判定（活跃或停摆），且自己的提交已落地、diff 仅含显式路径。
- 不再枚举第三方会话历史——归属判定只需回答“是否还在写”，不需要知道“具体是谁”。

## Verification
- 提交后 git status 显示他人 M 文件保持原样，commit diff 仅含自己的显式路径。
- 判定依据自洽：无关文件 mtime 晚于疑似旧会话的最后活动时间，且同期存在新鲜 lock/日志写入。

## Counterexamples
- 单会话仓库：无并发归属问题，全部 WIP 按自己的工作直接处理。
- 无关文件 mtime 已数小时/天且无新鲜 lock：更像被遗弃 WIP——仍不应默默吸收，但处置路径是协调而非“活跃避让”。
- 服务状态字段是实时查询而非启动快照、且已与树一致：无需再跑 git status 重复实核。
