---
method_id: failure-receipt-is-zero-info-not-absence-20ac7bad5b0a
name: failure-receipt-is-zero-info-not-absence
description: 检索回执分两类：成功+零命中（存在性的弱否定证据）与失败/超时（对存在性零信息）。本集曾把记录库查询超时当查空，得出『决议从未进入保存通道』的错误断言；架构 exception_log 确认是 tool_timeout，改用精确标识符窄查询+事件流交叉后全部捞回。方法：下『未记录/未发生』结论前必须持有 success 零命中回执并交叉独立 provenance 通道；失败回执只触发『查故障状态→窄查询重试→换通道』，不触发否定结论。检索工具不可用时停止伪装调用，直接汇报已验证事实。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d4b773f7-7796-4ff1-a76a-310f94b7feff:1078:73a42a795b899311b501
evidence_refs: learning:learn:2118d9478a52
created_at: 2026-09-25T15:05:17.944485+00:00
updated_at: 2026-09-25T15:05:17.944485+00:00
---
## Trigger
检索/查询类工具回执为超时或执行错误（如 tool_timeout、异常、故障），而下一步倾向于得出『内容未记录/从未保存/不存在』这类否定存在结论；尤其当系统设计上承诺记录（core loop 含『记住』阶段、存在事件流/declaration/provenance 层）使『未记录』成为需要强证据的低先验假设时。

## Discriminator
回执状态字段本身可直接观察：『[success] 未找到匹配』（查询已执行、真零命中）与『[执行超时] / error_type=tool_timeout』（查询未完成、对存在性无信息）是两种性质不同的证据；且架构状态/异常日志通道当时即可查到失败类型。这个分类在收到回执当刻就能完成，不需要任何事后信息。

## Short path
- 收到检索回执先分类：success+命中 / success+零命中 / failure(超时/错误)。若是 failure，标记『对存在性零信息』，禁止在其上建筑『没记录』结论。
- 查架构状态/异常日志通道确认失败类型（如 tool_timeout），把未知量从『有没有记录』缩为『该查询是否根本没执行』。
- 用精确标识符（具体编号、时间戳、文档名）做窄查询重试，避开导致超时的宽查询词组合。
- 窄查询仍 miss 时交叉独立 provenance 通道（事件流 declaration_check、action_trace 中的写入动作）获取同一事实。
- 只有 success 零命中 + 独立通道同样无记录，才向用户（当事人）求助或提出『未记录』假设；若可用工具集已不含检索类工具，停止把检索意图塞进控制类工具字段，直接汇报已验证事实。

## Stop conditions
- 权威来源（记录库 success 命中或事件流 declaration/trace 条目）已给出所需事实且相互印证——停止检索，直接汇报。
- 检索类工具持续失败或不可用——停止重试与伪装调用（勿往 convergence/控制类工具的声明字段里塞待办检索），向用户呈交已验证事实并请其补缺。
- 用户本人是事实当事人且仅缺少量具体值——直接问用户，不再枚举检索路径。

## Verification
- 每条『已验证』事实都能指回一条 success 回执（记录库命中条目或事件流 declaration_check/action_trace）。
- 最终结论中不依赖任何 failure 回执作为存在性证据；否定存在断言必须由 success 零命中 + 至少一个独立 provenance 通道同样无记录支撑。
- 重试后的窄查询与原失败查询指向同一目标事实（标识符一致），确认是重试而非换了问题。

## Counterexamples
- 回执是『[success] 未找到匹配』（真零命中）且系统无独立 provenance 通道时，『未记录/不存在』假设可直接进入下一步，无需先查故障日志或交叉通道。
- 目标系统没有记录承诺、也没有事件流（如查询纯外部网站/第三方 API），超时后的正确动作是换数据源、降级或放弃，而非交叉内部通道或反复窄查。
- 查询有副作用或重试代价高（写操作、付费接口、破坏性探测）时，不应机械窄查重试，应改走降级路径或直接求助。
