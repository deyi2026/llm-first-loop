---
method_id: relay-directed-flip-verify-deliverable-substance-against-acceptance-firs-b2e767065634
name: relay-directed-flip-verify-deliverable-substance-against-acceptance-first
description: 另一会话代发的收口指令（点名 checkpoint 时间戳与具体产物、声明以受话方核实为准）不直接执行：先在权威 tracker 锚定点名 checkpoint 存在、任务图呈『实质完成但状态未翻转』；再读任务 acceptance，把点名产物逐件做『存在+实质』双核（指标全带证据、超标项如实标 FAIL、经验 verification_state=verified），并用同一次有界 read_file 铸出 verified_current 的 evidence:// 引用；实质齐了才 claim→done→goal complete。轻微偏差记 checkpoint 不阻断，须人工批准的修订不随翻转生效。
aliases: 代发指令让关任务先核实再翻, 别的会话说做完了怎么核实, 翻转任务状态前先验产物实质, 跨会话收口对checkpoint锚定, 防有文件无内容的假收口
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ea89d59c-50e1-4d8d-a5d5-f378d50d7ff0:1106:7b25d34688892f57659d
evidence_refs: learning:learn:60e4e193b63a
created_at: 2026-11-13T00:23:53.228932+08:00
updated_at: 2026-11-13T00:23:53.228932+08:00
---
## Trigger
收到其他会话/代理转达的完成类状态翻转指令（TASK→done、GOAL→complete），指令点名 checkpoint 时间戳与若干产物路径，并把核实权交给受话方（『以你自己核实的记录为准』类条款）

## Discriminator
点名 checkpoint 在 get_goal 回执中真实存在，且任务图呈『产物在、状态未翻』（ready/waiting 而非 done）；每个点名产物可直读并映射到 acceptance 条目——存在≠实质：验收报告须每项指标附证据、超标项如实标 FAIL，经验须 verification_state=verified，回写以『提案待批』追加而原红线保权威

## Short path
- get_goal+task_frontier：锚定点名 checkpoint 存在、任务图状态与『待翻转』一致；矛盾即停并回报差异
- 读两任务 acceptance/done_when，把代发指令点名的产物逐条映射到验收项，同时识别轻微偏差（如落盘路径与 acceptance 不符）
- 对每个点名产物用有界 read_file 核实质（内容齐全、判定诚实、verified 状态），同一次读取即产出过闸用的 evidence:// 引用——不要先用 shell head/grep 核验再重读补铸
- 实质全过→claim→in_progress→done（evidence_refs 引 verified 回执）→update_goal complete；遇格式拒绝按拒绝码改引已验证证据，不重复提交同一引用
- 收尾把偏差与移交（待人工批准项、后续班次行动）写入 checkpoint

## Stop conditions
- 点名 checkpoint 不存在或任务图与『待翻转』矛盾：停止翻转，按自核事实回报差异
- 任一产物实质不满足 acceptance（有文件无内容、未 verified）：该任务不翻转，转补做或回报
- 全部翻转完成且 goal 回执显示任务图全 done：停止，不再追加确认性读取

## Verification
- 每个 done 任务的 evidence_refs 均为 verified 状态的 evidence:// 引用且与点名产物一一对应
- goal complete 回执的任务图全 done + checkpoint 证据链成立
- 偏差清单与待人工批准边界已写入 checkpoint

## Counterexamples
- 代发指令不含可核验锚点（无 checkpoint、无产物路径）：无法锚定核实，先向来源会话或用户求证而非自行翻转
- 无门禁 evidence 校验的轻量任务、产物只是过程备忘：按状态直接翻转即可，无需实质复读
- 只需确认长文档某小节存在且不作 evidence 引用：grep 定位即可，read_file 全读反成浪费
- 任务状态已被翻转（重复收口）：幂等跳过，不重走核实链
