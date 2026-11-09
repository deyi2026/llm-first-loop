---
method_id: settled-child-relay-close-delivery-chain-no-replay-838199c91bd9
name: settled-child-relay-close-delivery-chain-no-replay
description: 以子代理续话身份恢复、且来源 run 已结算时，既不重放、也不在本会话证据库里找交付证据：以拓扑回执（outcome+run_settled+lease）为重放闸门，沿相互独立的权威面闭合交付链——产物文件本体（完整性字段）、父会话事件流（消费事实）、外部只读 git 终态（下游处置）——最后持久化一份终态任务状态，使未来接力收敛为 no-op。可省掉的典型绕行：全量目标台账枚举、scope 已声明 current_session 时的跨会话 archive 检索。
aliases: 子代理跑完了还要重放吗, 续话接手已结算子任务先查什么, 接力快照禁止重放怎么核终态, 审查已交付如何确认下游闭环, settled 子任务续话免重放, 恢复会话先查拓扑再找报告
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:db1a7963-7751-4d71-9c39-f05915243cce:0:2b8f9bb91392ef6961f9
evidence_refs: learning:learn:080d7ffaf57b
created_at: 2026-11-09T15:11:34.769607+08:00
updated_at: 2026-11-09T15:11:34.769607+08:00
---
## Trigger
接力快照把本会话标识为某子代理 run 的续话，要求先核验执行状态与外部副作用终态、禁止自动重放未结算工具；当前会话无已存任务状态。

## Discriminator
子代理拓扑回执同时给出 outcome、run_settled、lease 三元组——这是『是否需要/允许重放』的唯一闸门事实，一旦 terminal+settled 即排除重放并把未知量收窄为『交付完整性、父会话消费、下游处置』三个；观测范围回执（scope=current_session、cross_session=false）进一步判定交付证据只存在于父会话事件流与确定性产物路径，本会话证据检索按构造必然 miss。

## Short path
- 查任务状态：不存在 → 确认这是全新续话现场而非中断重放点
- 查子代理拓扑：outcome=completed 且 run_settled=1、lease settled → 重放被排除，剩余未知量只有交付链三环节
- 按 store 命名约定构造确定性产物路径并直读交付物，核完整性字段（body_truncated=false、计数、sha/指纹绑定）
- 尾读父会话事件流一次，确认消费者已读取该产物（read 事件时间戳）
- 对冻结目标做一次只读外部终态检查（git HEAD/合并回执），确认裁决已被下游处置
- 持久化终态任务状态（含各链路证据引用），使未来接力 no-op；报告并停止

## Stop conditions
- 拓扑 settled + 产物完整未截断 + 父会话已消费 + 下游终态已观察 + 无指向本会话的 pending 事项 → 无未尽义务，不重放、不补救，停止
- 任一交付链环节断裂（产物截断/verdict 缺失、父会话未消费、下游未处置）→ 不宣告终态，按断裂环节向父会话升级

## Verification
- 四个环节各在独立权威面核验：拓扑台账（settled/outcome）、产物文件本体字段、父会话事件流（消费事实）、外部 git/合并回执（下游处置）
- 终态任务状态落盘回执（state_ref 与内容摘要）可复查，作为未来接力的短路证据

## Counterexamples
- 拓扑显示 run 未结算或 outcome=failed/interrupted → 走失败分类与委派范围重切分，本方法不适用
- 接手的是他人会话的接力快照、属主可能仍在写 → 先做属主存活门控与副作用归属仲裁，而非直接宣告闭环
- 产物 body_truncated=true 或 verdict 不完整 → 交付链已断裂，须升级而不是当作已交付
- 本会话自身就是待执行任务的执行者（run 尚未 started/settled）→ 正常执行任务，而不是做闭环核验
