---
method_id: check-desired-head-binding-before-restart-choose-update-2e3637e8aef7
name: check-desired-head-binding-before-restart-choose-update
description: 在 desired-state 生命周期控制面（desired 与物理生效分离）下，"重启使新代码生效"不能默认发 restart：restart 只按当前 desired 绑定的 code_root/HEAD 重放旧代码，会"成功"却不加载新提交（静默失效）。先读 status 回执，对比 desired 绑定的 git_head/generation、本地目标 HEAD 与 runtime 进程启动时间：绑定落后⇒选 update（publish+restart 单语义），且只重启承载目标改动的 target；发布前核 tracked 树干净，外部工具造成的脏改动先备份再恢复；提交后 action 若 waiting_for_requester_exit，用定时唤醒在会话结束后核验而非阻塞等待。不要用宽泛环境枚举（多变体 ps/lsof/全库 grep）替代控制面回执已给出的事实。
aliases: 重启完新代码怎么没生效, restart 只重放旧 git_head, desired 绑的 commit 落后了, 该发 update 别发 restart
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:6011132d-5da7-46ed-9be9-40d1379ec22d:1093:4c33ef3d6ae744ce829e
evidence_refs: learning:learn:e4bff46a41ca
created_at: 2026-10-11T15:00:33.334325+08:00
updated_at: 2026-10-11T15:00:33.334325+08:00
---
## Trigger
任务要求"重启使（新提交的）代码生效"或需把最新 commit 落到运行态，且环境存在 desired 与物理生效分离的生命周期控制面（status/publish/restart/update 分层语义）。

## Discriminator
status 回执给出的 desired deployment 绑定（generation/git_head）与本地目标 commit HEAD 的差，叠加 runtime 进程启动时间：desired 仍绑旧 HEAD 且进程启动早于新 commit ⇒ 单纯 restart 只重放旧代码，必须 update；desired 已绑目标 HEAD ⇒ restart 即可。

## Short path
- 读控制面 status：取 desired generation、git_head 绑定与 lag（未知量：控制面当前期望运行哪份代码）。
- git log -1 取目标 commit 及时间，ps 取 runtime 进程启动时间（未知量：运行态是否旧于目标提交、重启是否必要）。
- 对比 desired HEAD vs 目标 HEAD 定动作：不一致⇒update（publish+restart 单语义），一致⇒restart；target 仅取承载目标改动的服务。
- 核发布前置 git status：tracked 脏改动先 diff/stat 判来源，外部工具所致则备份到 /tmp 再恢复 tracked 版本（未知量：树是否可发布）。
- 执行后查 action status；若 waiting_for_requester_exit（重启将终止承载本会话的 runtime），登记会话结束后的定时核验而非阻塞等待。

## Stop conditions
- status 已示 desired 绑定目标 HEAD 且进程启动晚于该 commit：无需任何动作，停止。
- 判定绑定落后后直接走 update：不再做宽泛环境枚举（多变体 ps、端口 lsof、全库 grep）补与决策无关的事实。
- action 转 succeeded 且新进程 pid、git_head、matches_desired_generation 与目标一致：停止。

## Verification
- action 回执 status=succeeded 且 deployment_generation 与发布代一致。
- 重启后进程为新 pid 且 git_head=目标 commit、matches_desired_generation=true。
- 异步收敛结论以带时间戳的 status 快照表述，不在物理重启完成前断言终态。

## Counterexamples
- desired 已绑定目标 commit、只是进程未重启：直接 restart 即可；此时 update 会多发一代 desired，制造无谓 lag 与额外回滚面。
- restart/reload 语义是重读磁盘当前代码而非按 desired 快照（普通 systemd/PM2/裸 kill+start）：直接重启即生效，本判别不适用。
- tracked 脏改动是本任务或用户需要的内容：不可备份即恢复 tracked 版本，须先确认或 stash，否则发布时静默丢弃该改动。
- 提交确实横跨全部 target 或用户明确要求全量收敛：target=all 才是正解，"只重启承载服务"的窄化不应套用。
