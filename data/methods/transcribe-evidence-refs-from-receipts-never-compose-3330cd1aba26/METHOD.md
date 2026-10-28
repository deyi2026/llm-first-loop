---
method_id: transcribe-evidence-refs-from-receipts-never-compose-3330cd1aba26
name: transcribe-evidence-refs-from-receipts-never-compose
description: 给 task/goal/审查记录等持久化文档填写 evidence ref、回执 id、hash、URL 等溯源字段时，这些字段是『转写目标』而非『生成目标』：唯一合法取值来源是本 run 中产生该产物的工具回执（或 receipts 清单）里逐字打印的字符串。本集写任务证据时先后拼出两个格式逼真但不存在的 ref（…c3e9c4b4dc50e2a2 / …e56e36e788b7c8de），写入端不校验、静默接受，事后才用真实回执覆盖：产物事实无损，但记录出现假引用。与 receipt-anchored-params 卡互补：那张管会改状态的控制调用参数，本卡管无校验的记录溯源字段。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:396fca55-097a-4879-a217-f33fe29e277b:403:6b0f78ce5d6dcfe73b90
evidence_refs: learning:learn:861e7b8efad1
created_at: 2026-10-19T21:37:45.083210+08:00
updated_at: 2026-10-19T21:37:45.083210+08:00
---
## Trigger
在 task/goal/审查记录等持久化文档中填写指向本 run 产物的证据引用、回执 ref、hash、URL 等溯源标识字段，且记录系统对 ref 不做存在性校验、拼造值会被静默接受时

## Discriminator
该产物的产生动作刚发生：其工具回执（或 receipts 目录清单）已逐字节打印出权威 ref/文件名/哈希。任何不在本 run 任何工具输出中出现过的 ref 字符串，在写下那一刻起就是编造，与底层产物是否真实存在无关——这是写入当时即可观察的事实，不需要事后发现。

## Short path
- 每次动作产生回执时，立刻把回执中逐字出现的 ref/路径/哈希登记为该产物的唯一权威标识
- 填写 evidence 字段时，从已登记回执逐字节转写；找不到来源回执则该字段留 pending/空，绝不按『长得像』构造
- 对目录下实际 ref 不确定时，做一次有界 ls receipts/ 取得权威字符串清单，再转写
- 关闭任务前，把记录中全部 ref 形态 token 与本 run 回执输出/清单做字节级比对，未命中者立即用真实回执覆盖并复查同类

## Stop conditions
- 记录中每个 evidence ref 都能在本 run 某次工具输出或 receipts 清单中字节级命中
- 尚无回执支撑的字段全部标 pending，而不是填入构造值

## Verification
- 机械抽取记录中所有 ref/hash/URL 形态 token，逐一与回执语料（含 receipts 清单）字节级比对，未命中即假引用
- 抽查任一条 evidence ref：反查 receipts/ 下对应文件确实存在，且内容支撑该 claim

## Counterexamples
- 自由文本字段（摘要、说明、方法笔记）没有权威来源，正常撰写，不适用逐字转写
- 自有确定性命名规则（如文件名含 child_id）按规则计算新名字属生成而非拼造，规则本身就是来源
- 为尚未发生的动作预登记 ref 时必须显式标 planned/pending，不得呈现为已存在证据
- 写入端带存在性硬校验、错 ref 会当场拒绝的系统里，损失仅一次重试，规则仍适用但紧迫性下降
