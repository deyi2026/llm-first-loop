---
method_id: ownership-denial-terminal-degrade-to-labeled-checkpoint-af4dde3754a6
name: ownership-denial-terminal-degrade-to-labeled-checkpoint
description: 收口/停止类指令点名父侧或其他会话持有的实体（reviewer child、后台 run、durable TASK）时，第一未知量是『本会话是否拥有任何授权通道』而非实体终态本身：并行只读探测各权威通道一次；命名所有权/范围类拒绝（非直接 parent 可读、not owned、不在本会话 scope）是对本会话能力的确定性终局判决，至多换一个所有权范围不同的独立通道复核即封顶，随后降级为单次 checkpoint 写入，逐条标注『本会话已验证/他方通报未核/未完成-无授权通道』，绝不用脚本模拟被拒动作，也不把通报升级为已验证。区别于缺字段重签与瞬时故障重试。
aliases: 查其他会话的子代理被拒绝, 不是直接 parent 读不了 child 状态, 后台任务没有授权停止通道怎么办, 父侧通报的事实如何如实标注, 跨会话实体本会话查不到, 被拒后不要模拟停止动作
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ac770e54-e409-4936-9ad6-d191455efb75:112:215dde4361fa57027f49
evidence_refs: learning:learn:f5591f1e70da
created_at: 2026-11-13T20:20:47.818620+08:00
updated_at: 2026-11-13T20:20:47.818620+08:00
---
## Trigger
收口/停止类指令点名由父侧或其他会话持有的事实（异步 reviewer child、后台 run、durable TASK），并把查询/停止动作条件化于『若已有工具能安全/有授权』；本会话并不确定自己是否是这些实体的直接 parent 或 owner。

## Discriminator
通道回执的错误类别先分类：命名所有权/范围类拒绝（如『仅直接 parent 可以读取该 child handle』『review_child_not_owned』『task state not found in current session/workspace』）是对本会话能力的确定性终局判决，补字段、换措辞重发、工作区级 event/search 噪音搜索都不可修复；它与命名缺字段的合同差分（应补字段重签）和超时/5xx 瞬时故障（应重试）是三类不同信号，对应三种相反的后续动作。

## Short path
- 把收口指令拆成编号条目，逐条分类事实来源：本会话已验证 / 他方通报 / 依赖本会话可能不具备的通道能力；对后两类，第一未知量是『本会话是否拥有任何授权通道』，而非实体终态本身。
- 对最权威通道各做一次并行只读探测（child 终态通道 + 本会话任务/durable 图状态通道）。
- 收到命名所有权拒绝后，至多换一个所有权范围不同的独立通道复核一次；第二个同类拒绝即判定本会话无任何通道，终结通道枚举，不做工作区级噪音搜索。
- 立即降级到指令预授权的 fallback：单次 checkpoint 写入，逐条标注 provenance（本会话已验证 / 他方通报未重核 / 未完成-无授权通道），并引用拒绝回执原文。
- 绝不用脚本模拟被拒动作（如伪造 request_stop）；冻结其他一切写入/派发，按指令原顺序逐条汇报。

## Stop conditions
- checkpoint 已持久化，且每个无法核实的条目都带显式『未核/未完成』标注与拒绝回执出处
- 通道枚举已在 ≤2 个独立拒绝处封顶，无重复调用、无新增写入或派发
- 他方通报的事实（候选 SHA、child pending 状态）保持『通报未验证』等级，未被升级为已验证

## Verification
- 收口报告条目与指令条目 1:1 对应，无遗漏、无指令外新动作
- 每个『不可完成』结论引用的拒绝码与本会话实际回执原文一致，而非推断
- 报告中『父侧通报未重核』与『本会话已验证』两类标签可明确区分

## Counterexamples
- 拒绝码是命名缺字段/类型错误（合同差分）→ 走补字段重签路径，不是降级
- 回执为超时/5xx/限流等瞬时故障 → 重试原通道，不得据此断定无所有权
- child 由本会话自己 spawn（本会话就是直接 parent）→ 通道可读，走正常终态获取/轮询，不降级
- 指令未预授权任何 fallback 路径 → 不可自行降级，应明示实际所为并等待所有者指示
