---
method_id: source-self-session-id-from-receipts-before-parameterized-control-query-32e57294c6c9
name: source-self-session-id-from-receipts-before-parameterized-control-query
description: 查『我自己的 active children / 租约 / pending obligations』这类自引用控制面信息时，工具（如 subagent_topology）虽然 required=[] 为空，但描述文字写明二选一 child_id/parent_id，空参调用必被运行时拒绝。此时第一个未知量不是拓扑内容，而是『我的 session id』——它可以从一次 self-scoped 轻量回执（event_stream scope=current_session 等）直接读出。先补标识符、再发一次参数化查询，省去『空参失败→找 id→重试』的浪费回合。适用于一切以自身为参数的自省/拓扑查询。
aliases: 查自己子代理前 parent_id 从哪来, topology 空参调用被拒后先做什么, 怎么拿到当前会话的 session id, 清点活跃子代理前要先取什么标识, 自引用查询缺自己的 id
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5b834c0c-be5e-483d-893a-904b4a3981bd:0:14f1a08794ba4807d73f
evidence_refs: learning:learn:2a06a1a2b066
created_at: 2026-11-13T10:49:17.851880+08:00
updated_at: 2026-11-13T10:49:17.851880+08:00
---
## Trigger
需要以『自己』为参数查询控制面/拓扑（active children、租约、pending obligations），该查询工具描述写明必须提供 parent_id 或 child_id 之一，而当前手头回执中尚未出现过自己的 session id

## Discriminator
两件当时已知的事实：① 工具 schema 的 prose 写明『二选一输入』——required[] 为空只是 schema 宽松，运行时仍强制该参数（本集实测回执『缺少 parent_id 或 child_id』）；② 此前所有回执（模型目录、git、路径查询）都未内嵌自己的 session id。二者叠加表明：必须先取得 id，不能寄望 runtime 推断默认 self 作用域

## Short path
- 读 schema 时记下 prose 契约：『二选一输入』意味着空参必失败，即便 required=[] 为空
- 把『我的 session id 在哪』当作第一未知量：发一次 self-scoped 轻量调用（如 event_stream scope=current_session, limit=1），从回执 session= 字段直接读出 id
- 用 parent_id=<session id> 调用拓扑/控制面工具一次拿到 active_children/租约/pending obligations
- 继续原计划（spawn 前清点、接管判断），不再重复该查询

## Stop conditions
- 任一先前回执已内嵌自身 session id —— 直接复用，跳过 bootstrap 步
- 查询目标其实是外部实体且其 id 已由先前回执给出（如 spawn 回执的 child_id）—— 直接参数化查询
- 拓扑/控制面回执已给出所需列表且无缺参失败 —— 停止发现，进入 spawn/决策

## Verification
- 参数化查询回执包含具体 active_children/租约列表，且无『缺少参数』类失败
- 所用 session id 与 self-scoped 回执中的 session= 字段逐字一致

## Counterexamples
- 工具显式支持 self/parent 关键字或文档写明默认 self 作用域（如 agent_message 的 target='parent'）—— 直接调用，不需要 bootstrap
- fresh session 一条事件都没有、也没有其它内嵌 session 的回执 —— 应换标识符来源或放弃该查询，而不是反复空参重试
- 要查的是已知 child 的归属/租约 —— 用已有 child_id 直接查，先取自身 id 属于多余前置
