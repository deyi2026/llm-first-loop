---
method_id: single-authoritative-state-receipt-stop-identical-recalls-ba63ca214300
name: single-authoritative-state-receipt-stop-identical-recalls
description: 用户询问当前运行状态（如『你是什么大模型/当前路由到哪个模型』），而一个幂等状态/目录查询工具的首次回执已是 success 且显式命中所问字段（如『当前会话模型: X（会话覆盖）← 当前』）时，该回执即为终态证据：直接引用作答并停止调用。同一无参重复调用不增加权威性，只复制同一回执。仅当状态可能已变（如刚 switch_model）、回执失败、或所需字段本身落在截断区内时才再次调用，且应换参数而非原样重发。
aliases: 同一个状态工具连打多次, 回执已写明当前模型还重复确认, 查当前路由一次回执就够, 幂等目录查询重复调用, 无状态变化还反复刷模型目录
status: candidate
source_model: cognilocal/ornith-ai/Ornith-1.5-35B-A3B-MLX
source_episode_refs: episode:bc3e7780-af3b-4ea4-97e2-85cec88dbb96:2:f952de596eeaa834ba45
evidence_refs: learning:learn:c19fa4df6fb4
created_at: 2026-11-14T19:56:35.257704+08:00
updated_at: 2026-11-14T19:56:35.257704+08:00
---
## Trigger
用户问题可归约为单个当前运行时事实（当前模型/路由/配置状态），且存在一个幂等状态查询工具可在一次调用中显式命名该事实；首次调用已返回 success 回执

## Discriminator
首次回执顶部已含权威标注行『当前会话模型: <id>（会话覆盖）← 当前』，完整覆盖所问未知量；尾部截断发生在所需字段之后，不影响已获答案；两次调用之间环境中无任何可能改变状态的事件

## Short path
- 把用户问题归约为一个未知量：当前会话实际路由到哪个模型
- 调用一次状态/目录工具，检查回执是否 success 且显式命名当前状态
- 若命名字段完整出现（截断仅发生在其后），直接以该回执作答，并在答案中区分『路由事实』与 runtime_identity_declared=unknown 等未观测字段
- 停止；不再发起第二次相同调用，重复回执不计为额外佐证

## Stop conditions
- success 回执已显式命名所问的当前状态字段，且该字段未落在截断区内
- 两次调用之间不存在可能改变状态的事件（切换、失败、重载）

## Verification
- 答案逐字引用回执中的权威命名行作为证据
- 若所需字段本身被截断，改用带过滤/分页参数的取回，而不是原样重发同一调用

## Counterexamples
- 所需字段位于截断区之后（如询问目录尾部某个远端模型的详情）：应换参数取回，本方法不适用
- 刚执行 switch_model 后验证切换是否生效：状态可能已变，此时一次重查是必要的新观测而非重复确认
- 回执为 transient 错误/超时而非 success：重试是恢复动作，不属于本方法禁止的重复确认
- 探测对象是随机采样输出（如让模型自报身份的生成结果）：重复探测可诊断一致性，与确定性目录读取不同
