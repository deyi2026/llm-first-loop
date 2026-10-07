---
method_id: locate-workdir-via-job-receipt-commandline-8d8ea4f52975
name: locate-workdir-via-job-receipt-commandline
description: 后台任务（测试/构建/发布）的终态回执自带实际执行的命令行，其中的 `cd <绝对路径> && ...` 就是该任务工作目录的权威 provenance。需要定位仓库/工作目录时，先沿上下文已点名的 job/action 句柄一跳取回执并解析命令行，而不是凭记忆猜路径、也不是枚举候选目录。本集收益：省掉 1 次失败路径猜测 + 1 次候选目录枚举（枚举发生在回执已披露路径之后，属 post-receipt 冗余）。宿主路径风格（/home vs /Users 等）没有任何证据时尤其不要猜。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:9571992a-d742-4a48-824b-b1f635b8674f:2237:a358000b1800ebaf680c
evidence_refs: learning:learn:e7152e8bac63
created_at: 2026-10-07T15:06:01.588805+08:00
updated_at: 2026-10-07T15:06:01.588805+08:00
---
## Trigger
需要确定某个后台/异步任务（测试、构建、发布）对应的本地仓库或工作目录，而当前会话没有已确认路径；或一次 cd 路径猜测失败后准备广搜/枚举候选目录时。

## Discriminator
已收到（或经一次 job-status 查询即可达）的任务终态回执中包含实际执行命令行，`cd <绝对路径>` 字段已直接披露工作目录——该事实在进入任何目录枚举之前就已存在于上下文中（schedule/event_stream 回执通常已点名 job id，一跳即取到该回执）。

## Short path
- 路径未知或猜测失败时，先从 schedule/event_stream 回执中找已点名的 job id / action id，不猜路径、不枚举目录
- 查询该句柄的终态回执，从『命令: cd <绝对路径> && ...』解析工作目录
- 直接在解析出的路径执行下一步目标命令（如 git status），跳过候选目录枚举
- 仅当回执无绝对路径或被截断时，才退回 pwd/环境探查或目录枚举

## Stop conditions
- 回执命令行给出绝对路径，且在该路径下完成了定位后的目标操作
- 当前 shell 的 pwd/环境已直接确认即目标仓库根，无需再读回执

## Verification
- 在解析出的路径执行 git rev-parse --show-toplevel（或等效）确认仓库根，并与回执中被测/构建的语义匹配
- 多个候选 job 时，核对所用句柄与 schedule/event_stream 点名一致，避免定位到别的仓库

## Counterexamples
- 回执命令行全为相对路径或被截断，解析不出绝对工作目录——此时才需要 pwd/环境探查或枚举
- 同一会话多个 job 指向不同仓库/根目录，单条回执不足以消歧，须先按任务语义选句柄
- 回执来自早已迁移/重建仓库的历史任务，与当前权威记录（如最新 publish 回执的 code_root）冲突时以当前权威为准
- 当前进程 cwd 本身就是目标仓库（pwd 一步即得），解析回执反而绕远
