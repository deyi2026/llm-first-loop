---
method_id: attribute-validation-run-via-structural-identity-before-reuse-e30bf0d78688
name: attribute-validation-run-via-structural-identity-before-reuse
description: 当存在多个测试/验证 job 回执，需要判断哪个结果可作为当前候选状态（代码树/构建物）的证据时，用调度器记录中的结构身份字段做四维匹配：tree/workspace 快照哈希、起跑时间是否晚于最后落盘时间（快照包含性）、会话/owner 归属、命令口径是否覆盖验收范围。任一维不匹配即结构性排除（单条即够，例如起跑早于落盘的绿只证明旧树）；全部匹配才可复用。聊天传闻或转贴的他 job PASS 输出属弱证据，不能推翻结构匹配的权威记录。据此在『复用在跑 job』与『自行重跑』之间裁决，避免误采他人/旧树结果与冗余重跑。
aliases: 别人的绿灯算不算数, 绿是旧代码树跑出来的, 起跑早于落盘只证明旧树, tree snapshot hash 对不上, owner 归属不匹配
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f8beea3a-4ad1-4248-9dd6-815807df0073:3:d36cfddf0c94d3b8b75a
evidence_refs: learning:learn:717f2ab4536d
created_at: 2026-10-10T14:21:37.143415+08:00
updated_at: 2026-10-23T05:53:08.623538+08:00
---
## Trigger
已有多个异步验证/测试 job 的调度记录（含 tree 快照、起跑时间、归属、命令串），需要裁决其绿/红结果是否适用于当前候选状态，或决定是否需要自行发起验证；同时存在弱证据（聊天传闻、转贴输出）试图影响归属判断。

## Discriminator
调度记录中当时已可见的结构身份四元组：(1) tree/workspace 快照哈希是否等于候选树；(2) job 起跑时间是否晚于最后落盘时间（决定该 run 的快照是否包含候选改动）；(3) target-session/owner 归属；(4) 命令口径（全量 vs 子集、ignore 范围）是否等于验收范围。四项无需任何新查询即可核对。

## Short path
- 先固定候选状态的权威身份：当前树哈希、最后落盘时间、期望归属、验收命令口径
- 对每个 job 回执逐一核对四元组；任一维不匹配即排除并注明具体是哪一维（单条排除即够）
- 对唯一全匹配且未到终态的 job：绑定等待其 terminal 回执，回执须含终态+exit_code+最终统计行，期间不重跑
- 弱证据与记录冲突时以记录为准；只有传闻附带可核验的记录字段且与 fixture 冲突时才重开归属
- 全匹配 job 回执合格且其后无新落盘 → 采信复用；所有 job 均被结构排除 → 无人在验证候选，立即在候选树上自行发起全量验证并等自己的终态

## Stop conditions
- 存在全匹配且 terminal 的 job，exit_code 与最终统计齐备，且无 tree/归属反转证据、起跑后无新落盘 → 采信为候选证据，停止
- 唯一匹配 job 仍在跑 → 绑定等待其终态回执，不重跑、不空转轮询
- 全部 job 被结构排除 → 转入自行发起验证

## Verification
- 每条采信/排除结论都能指向具体记录字段（树哈希、起跑时间 vs 落盘时间、session/owner、命令串）
- 复用的绿回执必须同时含 exit_code 与最终统计行，防统计缺失的假绿
- 与近邻卡边界核对：『终态是否已到』属 verify-async-terminal-state 类卡管辖；本卡只裁决『哪个 run 算候选状态的证据』

## Counterexamples
- 用户明确要求重跑，或验收命令口径与现有 job 不同 → 不做复用判断，直接按新口径发起
- job 记录缺少 tree/时间戳等身份字段，结构匹配不可行 → 只能按 owner+命令等弱维度保守处理或直接重跑
- 同步命令、响应本身即最终结果 → 不存在归属问题，直接分析结果
- job 树与候选树匹配，但验收范围包含 job 明确 ignore 的子集 → 即便全绿也不完整，需补跑缺口子集
