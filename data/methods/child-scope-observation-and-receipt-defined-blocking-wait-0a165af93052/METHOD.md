---
method_id: child-scope-observation-and-receipt-defined-blocking-wait-0a165af93052
name: child-scope-observation-and-receipt-defined-blocking-wait
description: 等待后台子代理/异步任务结算时，把派发回执当作接口契约：它已点名结算工具与等待参数范围，就用该工具做串行最长阻塞等待。需要进展/活性信息时，先核对观察通道的 scope 参数是否覆盖目标——scope 限定为当前会话的通道按构造只镜像父侧自身动作，用它探测子代理必然只回显自己的轮询（本例 7 条事件全部是父侧 llm_decide/subagent_result）；活性检查必须走 child_id 限定的子侧通道。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:abda90a9-c633-4664-b777-2ef993c8f7d9:557:e2e3dce23962b822eff1
evidence_refs: learning:learn:a9ca18cac0b5
created_at: 2026-10-06T01:52:11.274029+08:00
updated_at: 2026-10-06T01:52:11.274029+08:00
---
## Trigger
已派发子代理/后台任务，其'结算与否'成为唯一悬置未知量；父级暂无可并行推进的实质工作，需要等待，或想确认子代理是否仍在正常推进而非卡死。

## Discriminator
当时已可见：(1) 派发回执显式声明唯一结算通道与等待范围（subagent_result(child_id=…, wait_seconds=0..30)），即单次调用即可吸收整段等待，且每次未结算回执都提示'可继续父级工作…或稍后再次查询'；(2) 事件流调用的 scope 参数取值 current_session，其声明语义只覆盖本会话父侧事件，子代理运行在 child 侧 scope——发出前即可判定该通道结构上无法回答'子代理是否卡死'，却仍发起了一次必然只回显自身轮询的探测。

## Short path
- 读派发回执，确认结算工具名、wait_seconds 允许范围与纠偏/查询通道——这是等待契约，不需要再发现
- 无父级实质工作可并行时，串行发起最长阻塞等待；仅当一次等待完整耗尽仍 unsettled 才发下一次
- 确需活性检查（怀疑卡死/需要 steer）时，只用 child_id 限定的子侧查询或回执内建字段，不借用父 scope 事件流
- 收到 child_state=completed 后一次性取回结果，停止全部等待/观察类调用

## Stop conditions
- child_state=completed：取回结果即停，不再发起任何等待/观察调用
- 一次阻塞等待已吸收满时长仍 unsettled：只能继续下一次等长阻塞，不得插入父 scope 进展探测
- 回执明示可继续父级工作且确有独立工作：转做父级工作，不空转轮询

## Verification
- 等待类调用数 ≈ ceil(总等待时长/wait 上限)+常数；每个中间回执除 settled 位外零新增信息，说明无多余探测
- 每条观察类调用发出前核对：其 scope/过滤参数在语义上覆盖目标对象（child 侧），否则预期回执只含父侧动作，不应发出

## Counterexamples
- 轮询本身带增量信息（进度百分比、阶段字段逐次变化）时，反复读是正常信息获取，不是摩擦，不应套用
- 父级确有可并行的实质工作时，正确解是工作与等待交错（回执也如此提示），而非机械拉长阻塞
- wait_seconds 无上限或工具默认无限阻塞时，一律取最长可能挂死整轮，应保守分段等待
- 观察工具本就按 child_id 查询（子侧 scope）时，活性检查合法，本方法的 scope 排除条款不适用
- 需要在时限内及时取消子代理时，等待节奏是安全/时效判断问题，不应被'最长阻塞'绑死
