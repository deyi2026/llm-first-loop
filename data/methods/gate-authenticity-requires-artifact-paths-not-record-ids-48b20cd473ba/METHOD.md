---
method_id: gate-authenticity-requires-artifact-paths-not-record-ids-48b20cd473ba
name: gate-authenticity-requires-artifact-paths-not-record-ids
description: 向带真实性核验的归档/审计门提交结果引用（result_doc、merged_docs）时，先落实为门可核验的真实工件：文件路径。本集首次用 evolution_exec 记录 id 作 result_doc 被 reason_code=spec_archive_missing 拦截；而 goal 回执当时已点名落盘文件，EVO 提交的文档变更可由 git log/show 一次枚举并 stat 核实。先沿回执点名工件+git 归属构建引用再一次性提交，可免一次 blocked 往返；记录 id 只放 reason 溯源链，无文档产出时走不适用出口而非硬凑。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f2769b0a-b64f-4ef5-81b2-e6a1d35727de:459:bcb4c21fc5e80ee516e7
evidence_refs: learning:learn:b9574a39f294
created_at: 2026-10-14T07:53:56.240128+08:00
updated_at: 2026-10-14T07:53:56.240128+08:00
---
## Trigger
向要求真实性核验的门（spec_archive/归档闸/审计闸）提交结果引用，且上游回执或提交历史已点名实际落盘的文档工件与提交 hash

## Discriminator
门的核验对象是可独立验证的引用（文件路径），登记记录 id 不是其可核验载体；goal/任务回执中已出现具体落盘文件名（如 RULE-AI-30 所在规则文档）与提交痕迹，这个已点名工件就是合法引用的直接来源，无需先试错

## Short path
- 从 goal/任务回执提取已点名的落盘文件与提交痕迹，明确未知量：本次变更实际产出哪些可核验文档
- git log/show 圈定相关提交实际改动的文档文件（区分语义提交与机械收口提交的归属），得到 merged_docs/result_doc 候选集
- stat/文件系统核验候选路径真实存在，锁定 result_doc
- 一次性提交归档：引用全部用真实文件路径，reason 保留 commit hash + 记录 id 的完整溯源链；确认无文档产出时改走『声明不适用』出口

## Stop conditions
- 门回执 success 且 spec_archive 已登记（goal 状态回执确认 applicable 已记录）
- 确认本次变更无文档类产出，已改走不适用出口而非拼凑弱相关文档

## Verification
- result_doc/merged_docs 中每个路径均经 stat 核验存在，且文件改动归属与所引 commit 的 git show 统计一致
- 登记/流程记录 id 只出现在 reason 溯源说明中，不作为门的可核验引用

## Counterexamples
- 门的契约明确接受 registry/记录 id 作为合法引用类型时，直接用记录 id 提交，不必先转文件路径
- 被拦原因是暂时性故障（超时/限流）而非 reason_code 指向引用不实时，重试原引用即可，无需重构引用
- 变更纯代码无文档产出时，不应拿弱相关文档凑 result_doc，走不适用出口
- 上游回执未点名任何工件且无 git 元数据可用时，先查询门契约或请人工确认，而不是猜测引用格式试错
