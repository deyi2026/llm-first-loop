---
method_id: resume-premise-arbitrate-by-landed-commits-fresh-read-before-absence-cla-6ca2f90c47a5
name: resume-premise-arbitrate-by-landed-commits-fresh-read-before-absence-claim
description: 多轮仓库任务续跑时，上下文对受版本控制文档存有旧记忆（如'某修订还没落地/纪律还是旧版'）。当新 artifact（脚本 docstring、回执）引用该文档具体措辞而与记忆冲突时，不要凭记忆断言'文档里没有这段话'并去调查'中间发生了什么'：续跑第一步的 git log 已点名落地/补遗提交，旧前提当场作废。对可变 tracked 文件的缺内容/有内容断言只认对锚点段落的一次新鲜读取；把'待办修订'逐条映射成'已落地→丢弃前提'或'未落地→仍有效'后，直接回到真实主线。
aliases: 续跑时旧文档记忆还能信吗, 凭记忆说文档缺某段话前先重读锚点, 脚本引用的措辞在文档里找不到, 断点续跑先看上次提交落没落地, 记忆里的修订其实已经合并了
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:cab051cc-c0ca-4a09-b848-6d4a00ec0ffe:1674:4b86ae817df9ad27bb35
evidence_refs: learning:learn:5539983db231
created_at: 2026-10-30T12:31:17.801206+08:00
updated_at: 2026-10-30T12:31:17.801206+08:00
---
## Trigger
断点/多会话续跑仓库任务：上下文带着对某受版本控制文档内容的旧记忆（某修订待落地的前提），而当前读取到的 artifact 引用了该文档的具体措辞，两者表面不一致。

## Discriminator
续跑第一个动作的 git log/status 已经把'修订落地'与'补遗'提交列在历史里——待办前提与它直接冲突即可判死；且对 tracked 可变文件的'某措辞不存在'断言，唯一合法来源是本回合的新鲜锚点读取，不是会话记忆。

## Short path
- 续跑首个 git delta 逐条映射记忆前提：对应提交已在历史 → 前提作废；无对应提交 → 仍有效，才值得探查
- 遇到'引用措辞 vs 记忆旧文'冲突时，先对 commit message 点名的锚点段落（如'98 行批量纪律'）做一次新鲜读取，不凭记忆断言缺失
- 新鲜读取证实措辞在 HEAD → 记忆判为旧缓存并丢弃；用 goal/task 记录一次核清该修订终态（complete 即无续作义务）
- 回到真实主线（本轮队列/评审实况），仅在主线确需门禁语义时才读 store 门槛代码
- 只有新鲜读取也证实缺失时，才进入'引用方与被引方谁过期'的调查分支

## Stop conditions
- 锚点新鲜读取与引用方一致：停止对账与'中间发生了什么'式调查，回主线
- goal/task 记录终态为 complete：该修订不再是待办，不按待办探查
- 新鲜读取证实措辞确实缺失：转入引用方/被引方谁过期的调查（记忆可能没错）

## Verification
- 把引用方的锚点短语与 HEAD 工作树新鲜原文逐字比对，而非与记忆比对
- 用 goal/task 记录核对修订对应条目的终态与时间戳
- 任何'文件里没有 X'的断言发出前，确认其出自本回合读取回执

## Counterexamples
- 引用方自身过期：docstring 引用的是从未合并的草案措辞，HEAD 新鲜读取也找不到 → 该查引用方而不是文档，旧记忆没错
- 争议对象是未提交的工作树/未跟踪文件：commit 历史不仲裁，须直接核 status/工作树字节
- 文档不在版本控制内（无 git 历史 oracle）：只能靠新鲜读取或权威 store 回执对账
