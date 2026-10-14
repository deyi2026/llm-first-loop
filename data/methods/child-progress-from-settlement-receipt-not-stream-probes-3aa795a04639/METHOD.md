---
method_id: child-progress-from-settlement-receipt-not-stream-probes-3aa795a04639
name: child-progress-from-settlement-receipt-not-stream-probes
description: 后台 spawn 的子代理未结算时，不要在父可见事件流/日志里翻找子代理进度：spawn 回执枚举的交互通道（steer + 结算查询）即全部交互面，且子会话观测隔离，父级流只含父自身轨迹。把'子代理是否在干活/能力是否生效'这一未知量留给结算回执——它自带 per-tool 成功/失败轨迹，是子代理行为验证的权威证据。未结算期间继续父级工作或用命名通道纠偏；仅在怀疑真实挂死时做至多一次定向诊断。推广一层：任何带完成句柄的后台子任务（job scheduler、background task）同理——先读 spawn/提交回执声明的合同通道，结算回执是证据源。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:b1e2c610-ff59-483f-a50b-9ef6586aaae0:704:f171bfe1526b42798707
evidence_refs: learning:learn:72d0c9d75ec1
created_at: 2026-10-14T16:57:29.930717+08:00
updated_at: 2026-10-14T16:57:29.930717+08:00
---
## Trigger
spawn 的后台子代理/子任务处于 running 状态，父会话想知道它是否真在干活或其能力配置是否生效，正考虑查事件流/日志等旁路观测通道来确认进度时

## Discriminator
探查前已存在两个可观察事实：(1) spawn 回执本身枚举了全部 sanctioned 通道（中途纠偏=agent_message、查询/等待=subagent_result），并显式声明'本回执不是任务结算'——即结算证据只会在 subagent_result 回执交付，且回执包含 per-tool 轨迹；(2) 子代理是独立会话、观测隔离，父可见流（含 workspace scope）只含父自身 action_trace。这两点足以在探查前就排除'去父级事件流找子代理轨迹'整条分支，无需实际试遍 scope 参数。

## Short path
- spawn 后先读回执的通道枚举与免责声明，明确：结算证据（含 per-tool 成功/失败轨迹）将由 subagent_result 回执交付
- 轮询未结算时只做两件事：继续父会话自身工作（如并行写文档骨架），或经命名 steer 通道纠偏；不为观察进度而升级/扩大事件流 scope
- 结算回执到达后，直接以其 per-tool trace 作为子代理行为与能力验证的权威证据，进入结论与文档回填，不再从任何流中二次取证

## Stop conditions
- 结算回执已回答开出的未知量（如各层工具的成功/被拒计数、child_state、轮数）——立即停止一切观测尝试并结转证据
- 怀疑真实挂死且超过合理时限：允许至多一次定向诊断探查以区分停滞与隔离，之后转 steer 纠偏或取消，不再枚举查询参数

## Verification
- 父级任意 scope 的事件流查询均不出现子代理 action（隔离事实成立，可作负证据记录）
- 最终结论中引用的每一条子代理行为证据，都能在结算回执的工具轨迹中找到对应条目（无来源外推）
- 若某次父级查询真的出现了子代理事件，说明隔离前提被证伪——收回本方法并改用该可见通道

## Counterexamples
- 平台显式提供 child-scope 轨迹查询或文档声明 workspace 聚合视图可见子会话事件——此时该通道就是正当路径，直接使用
- 同步或同会话内联子任务：子事件本就出现在父流中，无需等待结算回执才能观察进度
- 需要的是子代理运行中途的语义内容（不只是完成状态）——应用命名 steer 通道（agent_message）索取回答，而非翻查事件流
- 结算回执不含 per-tool 轨迹的旧版合同：此时旁路观测是必要的，方法不适用
