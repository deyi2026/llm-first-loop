---
method_id: receipt-authoritative-maps-phantom-tool-and-duplicate-goal-self-coordina-9da20f8f3fd9
name: receipt-authoritative-maps-phantom-tool-and-duplicate-goal-self-coordination
description: 用户点名的工具在本进程不存在时，[工具不存在] 回执打印的工具目录就是权威地图：把指令意图映射到最近的真实工具（get_goal/task_frontier）直接执行并回报替换事实，不反问、不重试幻影名。会话内 get_goal 只能回答本会话有无实体；create_goal 成功回执并列打印的跨会话并行 goal 清单才是同题重复的廉价探测器。发现重复且用户已预授权『不需要再问我』时，用回执目录里现成的只读 coordination_status 查对方 lane/工作树占用，自行裁定让位或独占推进并写进回报——把发现升级成用户问句违背了本轮免问预授权。
aliases: 用户指定的工具不存在怎么办, 工具名报不存在找替代, 创建 goal 发现别的会话有同题, 同题 goal 重复撞车处理, 免问授权下要不要停下来确认, 跨会话 goal 重复自查
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:0a79bf7c-4ae8-4f1a-be35-75280ea0a40e:244:dc1732d4d59c9ff8ac23
evidence_refs: learning:learn:c7ea52e18ad5
created_at: 2026-11-07T13:53:30.454635+08:00
updated_at: 2026-11-07T13:53:30.454635+08:00
---
## Trigger
用户指令按名字指定某个工具/句柄且其存在性未在本进程验证过；或正在执行『会话内查无→创建』分支的创建类写入（goal/任务/记录），同时用户已给出免问预授权。

## Discriminator
两条回执在任何后续动作之前已给出的事实：(1) [工具不存在] 失败回执逐条列出本进程真实工具目录；(2) create_goal 成功回执随附跨会话并行 goal 清单（含其他会话同题 goal 的 ID 与摘要）。二者分别回答『该用哪个真实句柄』与『等价实体是否已在他处存在』，无需向用户追问。

## Short path
- 按用户点名原样调用一次（口中的工具名只是假设）；失败回执附带的工具目录即替换地图。未知量：本进程用什么承载该意图。
- 由目录把『列未完成 goal』映射到 get_goal（任务级诉求→task_frontier），一次调用核实。未知量：本会话有无可复用实体。
- 查无→按预授权 create_goal；同一成功回执的并行清单顺带回答跨会话重复。未知量：同题实体是否已存在于其他会话。
- 发现重复→调用回执目录中现成的只读 coordination_status，查对方 lane/工作树是否在途占用同一工件。未知量：本会话该让位还是独占。
- 据占用裁定姿态（对方在途→让位/排程并说明；空闲→本会话独占推进），checkpoint 后回报：回执事实与推断分列成表，不把发现落成待答问句。

## Stop conditions
- Goal ID、status、checkpoint 均以真实回执回报，且协调姿态已由 coordination_status 回执裁定，而非留作用户问题。
- 用户本轮圈定的边界（暂不建 lane、不改文件、只回报状态）未被越过即停。

## Verification
- 替换、跨会话重复、占用三类结论各自引用对应回执原文（工具目录行、并行 goal 清单行、coordination_status 回执）。
- 『另一会话同题 goal 很可能就是用户记忆来源』这类因果猜测在回报中显式标注为推断，不与回执事实混排。

## Counterexamples
- 点名工具确实存在但报瞬态错误（超时/限流/鉴权）：应诊断并重试原工具，而不是替换成别的工具。
- 工具目录中没有任何工具能承载该意图（如确需全组织 goal 枚举而无此工具）：不能臆造替代，此时向用户澄清才是正确动作，免问预授权不豁免能力缺口。
- 用户本轮明说『有歧义就停下来问我』：发现重复即停并提问是履行指令，不是违约。
- 创建回执不含并行实体清单或清单为空：跳过协调检查，直接进入下一未知量。
