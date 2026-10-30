---
method_id: remeasure-delta-before-inherited-deferred-push-9f65dd609caf
name: remeasure-delta-before-inherited-deferred-push
description: 用户批准执行上一轮提议的延迟动作（典型：『推这几个提交』）时，指令继承的是旧快照前提。第一未知量不是怎么执行，而是该动作要闭合的差距是否仍存在：多会话共享仓库里并发线可能已完成它。最早的判别信号是首个回执证伪记忆标识符（remote 名 unknown revision、HEAD 位置与预期不符）——这是前提过期证据，应触发重测而非绕过报错。钉定当前权威 remote 并 fetch 后，对命名对象直接测 delta（双向 ahead/behind 计数＋逐 SHA 祖先校验）；0/0 或全部已是远端祖先即判 no-op 并停止，不展开周边普查。目标分支上较新的交接型提交信息可能自证完成。
aliases: 要推的提交是不是已经推上去了, 上轮提议这轮还要不要做, remote 不存在说明状态过期了, 执行前先确认任务还在不在, 推送前对账远端
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:212bbc07-73ca-4b2a-af34-769842c6d47d:3314:e2fa910c51db0342b502
evidence_refs: learning:learn:87b98f71c1b5
created_at: 2026-10-30T15:37:51.507267+08:00
updated_at: 2026-10-30T15:37:51.507267+08:00
---
## Trigger
用户指令执行上一轮/交接提议的延迟动作（如『推这 N 个提交』），且工作区多会话共享、上轮观察距今可能已过期；或首个执行回执证伪了记忆中的标识符（remote 名解析失败、HEAD/分支与预期不符）。

## Discriminator
首个回执的报错内容本身：命名 remote/revision 报 unknown revision 或 does not appear to be a git repository，说明记忆快照已失效——它把候选空间从『如何完成动作』缩成『动作差距是否仍存在』；随后一次权威 delta 测量（fetch 后双向 ahead/behind 计数、点名提交的 --is-ancestor 校验）即可终裁，无需多面普查。

## Short path
- 把继承指令视为对当前状态的前提断言：第一未知量＝该动作要闭合的命名差距（如 N 个未推提交）现在是否仍存在。
- 首个回执若证伪记忆标识符（remote 名失效、HEAD 不符），禁止用同一旧名重试或换参数硬闯；改为枚举当前 remotes，钉定权威远端与分支实际检出位置。
- fetch 权威远端后直接测 delta：双向 ahead/behind 计数；对指令点名的每个对象做 merge-base --is-ancestor 对远端分支校验。
- delta 为 0/0 或全部已为远端祖先 → 判定动作已被并发线完成（目标分支较新的交接提交信息可能自证），引用证据报告 no-op 并停止；仅真实领先才进入执行规划（门禁/审查/推送形式）。

## Stop conditions
- 权威远端 vs 本地分支双向计数为 0/0，且指令点名的每个提交均为远端分支祖先：无动作可执行，立即停止（后续 dry-run、其他 remote/工作树普查均属冗余）。
- delta 非零：前提成立，转入常规执行路径。

## Verification
- git fetch 权威远端后，rev-list --left-right --count <remote>/<branch>...<branch> 为 0 0。
- 对每个点名提交执行 git merge-base --is-ancestor <sha> <remote>/<branch>，退出码为 0。
- （可选冗余）push --dry-run 回执 Everything up-to-date 仅作交叉确认，不作为继续普查的理由。

## Counterexamples
- 单会话独占的新鲜工作区、上轮观察仅数分钟前：前提大概率仍成立，测一次 delta 即可执行，不应展开 remote 改名、工作树卫生等宽普查。
- remote 解析失败源于网络/凭据（如 could not read Username）而非改名或删除：这是可达性故障，推不出『动作已被完成』，须先恢复访问再测 delta。
- 指令针对从未推送的全新本地分支：ahead 必然非零，前提天然成立，直接进入执行规划。
