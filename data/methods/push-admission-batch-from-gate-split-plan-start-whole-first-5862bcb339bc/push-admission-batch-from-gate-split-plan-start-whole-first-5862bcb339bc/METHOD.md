---
method_id: push-admission-batch-from-gate-split-plan-start-whole-first-5862bcb339bc
name: push-admission-batch-from-gate-split-plan-start-whole-first
description: 向准入闸为受管 push（git_push 等按批受审的推送类 kind）发起 start 时，合法批次由闸生成的 split_plan 定义，不得拿任务书的完整改动清单自组批——自组批被确定性拒绝（push_batch_not_in_plan），且修正取值不在任务上下文，只能向闸索取。先整量 start（不带 paths）触发 duration 预检取回 split_plan，再逐批以精确 paths start 等独立 Reviewer PASS（P0/P1=0），全部批 PASS 后才消费资格执行 push。与 scope 类方法互补：那条管 scope 维度由执行面推导，这条管批次维度由闸生成，两条任一不满足都会被各自命名错误码拒绝。
aliases: 推送审查批次谁说了算, 先不带paths发起拿切分, 自组清单被闸拒绝怎么办, git推送准入逐批过审流程, 漏审防护按闸的批走
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:c5af189a-3424-4525-9436-3f706df8e72f:85:5c18f92bd4d9f789c8c1
evidence_refs: learning:learn:32c76c2c78e2
created_at: 2026-11-19T16:27:28.158340+08:00
updated_at: 2026-11-19T16:27:28.158340+08:00
---
## Trigger
需要为 kind=git_push 等按批受审的推送类动作向审查/准入闸发起 start，而手上唯一可用的 paths 是任务书或 diff 给出的完整改动清单（并非闸生成的批次）时。

## Discriminator
本集闸回执明文的契约：“声明的 paths 必须精确等于闸生成的 split_plan 中的某一整批（不得自造批导致漏审）”——批次划分权在闸自身，调用方自组清单不构成合法批；且该修正取值不在任务上下文，微调 paths 重发不可能命中合法批。

## Short path
- 整量 start：review_admission(action=start, kind=git_push, workdir/command/scope 照任务书)，不带 paths，让闸触发 duration 预检并返回 split_plan
- 解析回执中的 split_plan，得到唯一合法批划分
- 对每一批以该批精确 paths 再次 start，等待该批独立 Reviewer 终态 PASS（P0/P1=0）
- 全部批 PASS 后按闸要求消费资格执行受管 push
- 任一调用被拒时，把回执 reason 当作与合同的差分：修正取值由闸持有（如批次切分）就先发取值型调用向闸索取，不在上下文就不用近似值重试

## Stop conditions
- 未取回 split_plan 前，不提交任何带 paths 的批
- 存在未 PASS 的批时不执行 push；Host 拒绝时只按回执 reason 修正，不改命令、不绕过
- 到达终态（全部批 PASS，或真实拒绝 reason 已如实上报并等待授权）即停

## Verification
- 每批 start 的 paths 与 split_plan 对应批逐字一致
- accepted=true 回执的 child_id/candidate_sha256/material scope 与冻结 HEAD/Lane 一致
- 全程无任何未经闸批准的远端效果（零 push、无跨会话资格消费），拒绝时原样引用 reason 文本

## Counterexamples
- kind 不是按批受审的推送类（如 full_test 或按工件绑定的发布审查）：paths/scope 仍应由义务与执行面推导，不必整量索取切分
- 闸的回执或文档明确该 kind 接受调用方整清单、且 split_plan 恰为等于全量清单的一整批：该清单即合法批，直接提交
- 拒绝 reason 指向的修正取值就在任务上下文（缺字段、scope 取值已知）：按既有差分重发法机械补齐一次即可，无需两阶段协议
