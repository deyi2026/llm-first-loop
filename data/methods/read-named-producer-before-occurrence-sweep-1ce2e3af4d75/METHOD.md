---
method_id: read-named-producer-before-occurrence-sweep-1ce2e3af4d75
name: read-named-producer-before-occurrence-sweep
description: 审计实现语义时，若刚读过的代码已显式 import/指名产生该事实的模块或类，下一跳直接读那个被指名的生产者定义，而不是对关键词做全仓 occurrence 搜索。只有当不存在显式 producer edge 时才做发现式搜索，且搜索要按『定义点』定向，并把命中区分为定义文件与记录性数据（结果日志/事件日志/eval 拷贝），只把前者当语义证据。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:a8ca7a5d-9f35-462e-b02e-e13f15ff0023:46:7efb22f8f3602baf898b
evidence_refs: learning:learn:a0dd54ae8b2f
created_at: 2026-09-20T08:40:10.261617+00:00
updated_at: 2026-09-20T08:40:10.261617+00:00
---
## Trigger
代码语义核验任务（核某字段/工具/协议实际如何实现），且当前已读文件的 import 或定义块中已出现与待核事实因果相关的具名模块/类。

## Discriminator
当时已见事实：browser_perceive.py 的 import 块显式给出 `from llm_loop.browser.perception import BrowserPerceptionAdapter`（助手自己也已说『sha 计算应在 perception adapter』），即观测内容及其 sha 的生产模块已被具名，可把『sha 在哪算』缩到 1 个文件；此时发起的全仓 sha 搜索反而返回 action.py 动作回执哈希、smx_perceive 另一层快照哈希、episode_history 日志哈希等多个无关 sha 族，把 1 个已知候选扩散成多个待排除项。

## Short path
- 先明确未知量：如『content_sha256 是否为全量 canonical 观测的哈希』。
- 若当前文件已具名生产者，直接读该被 import 的模块（llm_loop/browser/perception.py），定位 snapshot 内容的哈希构造点。
- 用已在手的消费侧代码（browser_semantic_operation.py 的 canonical 校验行）交叉确认语义，得出结论。
- 其余缺口各自沿已有 edge 走：打包缺口读已定位的 provider schema/执行段；子代理缺口因当时无任何引用边，才做文件名定向搜索并读定义文件。
- 某条缺口拿到定义点答案即关闭该缺口，不再做同主题的 occurrence 补搜。
- 若中途需要搜索，按定义点定向（文件名/符号定义），并按路径区分 src 定义文件与 results.jsonl/event_logs 等记录性命中。

## Stop conditions
- 每条待核缺口都已获得引用定义点 file:line 的答案。
- 具名生产者文件已读且事实被确认或证伪，立即转入下一条缺口，不对同关键词重复 sweep。
- edge 断裂（被指名模块只是转发或不含目标事实）时，沿它内部下一个具名引用再走一跳；仍断裂才降级为定向发现搜索。

## Verification
- 结论必须引用定义点代码本身（哈希构造函数、schema、契约文本），不得引用 results.jsonl、event_logs、eval harness 拷贝等记录性数据作为语义证据。
- 被引定义文件必须与被审工具的 import/引用链一致（如 perception.py 确在 browser_perceive 的 import 链上）。
- 否定性结论（如 provider 面无打包）必须引用 provider-facing schema/契约源码，而非间接旁证。

## Counterexamples
- 待核事实尚无任何显式引用边（如本例核 spawn_subagent 隔离之前，未读过任何引用它的文件）：此时定向发现搜索是正确第一步，不应强行找『生产者』。
- 任务目标本身就是枚举全部出现点（如安全审查『谁会写这个字段』）：occurrence 全量搜索即任务本身，不构成摩擦。
- 审计对象是运行时实际行为或部署配置，可能与源码定义不一致：定义点不是权威，应改查运行时 artifact/manifest。
- 当前文件的 docstring/schema 已完整回答问题：应直接停止，不走任何下一跳。
