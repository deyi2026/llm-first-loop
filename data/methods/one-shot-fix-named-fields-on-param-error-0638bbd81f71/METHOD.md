---
method_id: one-shot-fix-named-fields-on-param-error-0638bbd81f71
name: one-shot-fix-named-fields-on-param-error
description: 契约类参数错误回执是一次性修正指令，不是重试信号。当 failure 回执显式点名缺失/非法字段（missing=<field>）时，把每个被点名字段当权威修正项：取值能由用户目标唯一导出则直接组装修正调用，取值类型/enum 不确定才先读一次 get_tool_schema；然后一次性重发完整修正后的调用。禁止对同一 exact 参数原样重发——契约错误是确定性的，原样重发只是枚举'也许这次能过'，不产生任何新信息，必然重复同一失败。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d8f59859-1341-4560-9f92-9163e49963d5:821:0fe96d44da8661dc38b5
evidence_refs: learning:learn:bc9fdc5eda46
created_at: 2026-09-30T15:15:54.668474+08:00
updated_at: 2026-09-30T15:15:54.668474+08:00
---
## Trigger
工具返回 [参数错误]/参数契约不满足类 failure 回执，且回执文本显式点名缺失或非法字段（如 missing=target）

## Discriminator
第一次失败回执已逐字给出修正量：missing=target，且用户目标已唯一确定取值（重启 feishu 与 learning 两个服务，target 需分别指定）。该事实在第一次失败后即已存在，足以把候选动作从'再试一次'缩成'补上被点名字段后重发'；第二次原样重发在信息上必然与第一次失败完全相同。

## Short path
- 首次失败后逐字解析回执点名字段清单（missing=target）
- 判断取值来源：能由用户目标导出则直接取（target=feishu 与 target=learning 各一次调用）；字段类型/enum 不确定才读一次 get_tool_schema(service_control)
- 按修正后的完整参数一次性重发，不重复原调用
- 异步受理后用回执给出的终态核对入口（status + action_id）等待并核对终态
- 以 verify_verdict/pid/git_head 等核验证据汇报并停止

## Stop conditions
- 修正后的调用收到 accepted 受理回执（含 action_id），转入异步终态核对
- 若再次失败且回执点名新字段，只对新字段做一次增量修正后重发，仍禁止原样重发

## Verification
- 对比失败前后调用参数：差异恰好覆盖回执点名的全部字段，无遗漏
- 同一 exact 参数组合不得在同一契约错误上出现第二次（可机械检测：identical failed call 计数为 0）

## Counterexamples
- 回执为 transient 超时/网络类错误且未点名任何字段：带退避的重试是合理的，不适用本方法
- 回执措辞含糊（invalid request）未指明字段：应先读完整 schema 再重发，而非猜测字段名
- 被点名字段的取值无法由用户目标唯一导出（多个合法 enum 值语义均可）：先读 schema/文档或向用户澄清，不要猜值硬发
