---
method_id: pin-remote-identity-and-history-relatedness-before-sync-ops-6d3fa7ef9164
name: pin-remote-identity-and-history-relatedness-before-sync-ops
description: 用户以名字指称同步目标（如『GitHub』）或询问是否需要 push/哪些分支待合并时，先枚举 remotes 并把该名字钉到具体 URL：默认跟踪远端(origin)和 git status 的 ahead/behind 行只对跟踪远端负责，不证明与用户指称的目标同步。对钉定远端比较 SHA；若目标远端落后且无法直推，先跑 merge-base 判历史相关性：空 merge-base=无共同祖先（快照导入线），常规 merge/push 无效，须逐项核实远端独有提交内容（版本串/CHANGELOG段/关键代码标记）已在本地，再 --force-with-lease 覆盖并 fetch 复核 SHA。空参数命令可能 exit 0 产出空真结论（假『0冲突』预演），一律作废。分支甄别用 git cherry 补丁等价而非领先数。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:33d3039e-2906-4f07-9dc7-517532290686:7:f1af94b64fb66665037d
evidence_refs: learning:learn:15d3bdb1fbe3
created_at: 2026-10-14T17:11:22.096355+08:00
updated_at: 2026-10-14T17:11:22.096355+08:00
---
## Trigger
用户询问与某个以名字指称的远端目标（GitHub/主仓）的同步状态、是否需要 push，或要求列出待合并工作树/分支；本地存在多个 remote 或远端命名与角色不符。

## Discriminator
首次检查即可见的两条事实：git remote -v 列出多个远端且默认跟踪远端(origin)的 URL 与用户指称目标不符（如指向 legacy 镜像/不同 repo）；git status 的 ## branch...origin/xxx 行只针对跟踪远端。这足以把『已同步』降级为『仅与 origin 同步』，并把比较对象收敛为一个具体 remote。

## Short path
- 枚举 remote -v，按 URL 钉定用户指称目标对应的 remote 名；未知量：哪个远端才是目标主仓？
- fetch 该远端并比较分支 SHA/ahead-behind；未知量：与目标的真实 delta（本集为落后两天/2807 提交）。
- 若目标远端落后少量提交且直推会受阻，跑 git merge-base 并查双方历史根提交；未知量：历史是否相关、merge 是否可行。
- merge-base 退出码 1=无共同祖先：枚举目标远端独有提交，逐项验证其内容（版本号、CHANGELOG 段、关键安全改动标记）已存在于本地；未知量：远端是否持有本地缺失内容。
- 内容全等后 push --force-with-lease；网络失败/超时后重试是幂等安全的，收到 Everything up-to-date 说明上次已服务端完成；最后 fetch 复核远端 SHA=本地 SHA。
- 待合并分支用 git cherry 补丁等价判定真缺，过滤已 squash 并入的分支，输出量化清单。

## Stop conditions
- 对正确远端重新 fetch 后 ref 与本地分支 SHA 相等（ahead=0 behind=0），且分支甄别以补丁等价完成。
- 发现目标远端独有提交含本地确实缺失的内容时，立即停止 force 计划，转 merge/rebase 或交用户裁决。

## Verification
- 成稿前对钉定远端重新 fetch 并比较 rev-parse SHA，不引用跟踪远端的 ahead/behind 作为结论依据。
- 规划 merge 前已核 merge-base 退出码与双方根提交；任何由空参数/空 merge-base 跑出的『成功/0冲突』结果作废重跑。

## Counterexamples
- 仅一个远端且 origin 就是用户目标：默认跟踪比较已足够，无需整套流程。
- merge-base 非空（历史相关）：走常规 push/merge，禁止 force-with-lease。
- 目标远端独有提交含本地没有的真实内容：force 覆盖会丢工作，必须先合并再推。
- 纯本地分支整理、用户未指称任何外部目标：不需要远端身份核验。
