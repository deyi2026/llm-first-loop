---
method_id: dedupe-cross-session-duplicate-claim-then-split-attribution-from-truth-p-4e66b3d3e061
name: dedupe-cross-session-duplicate-claim-then-split-attribution-from-truth-probe
description: 空会话收到用户简短状态声明（如『已经重启』）时，把两个未知量分开查：归属/去重用一次限窗事件流查询（谁在处理、谁执行、还有何未闭合），真值用一次权威 manifest 抽查（pid/started_at/git_head 对 HEAD）。他端已接手则不重做其动作，回报用『一致结论+归属+增量』三段式。避免无窗多轮换关键词扫描，也避免跳过归属直接下结论。
aliases: 用户同一句话发到多个会话, 已经重启是不是别的会话处理过了, 重复消息跨会话去重, 先查谁接手再核真值, 多会话并发别重做别人的动作, 重启声明归属核查
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c0fcfe68-fb12-4d65-894f-e765836fa751:0:76545f92a04a7ac33512
evidence_refs: learning:learn:892f903d5919
created_at: 2026-11-09T15:41:25.218616+08:00
updated_at: 2026-11-09T15:41:25.218616+08:00
---
## Trigger
新或空会话（task state miss、无可恢复 evidence）收到用户无上下文的简短状态/动作声明（如『已经重启』），且工作区多会话并行、声明时间戳前后存在他端活跃或同主题在途 lane

## Discriminator
声明带时间戳；单次限窗事件流查询（since≈声明前10–30分钟，按消息内容匹配而非仅关键词邻近）可同时回答三个独立未知量：①该消息是否也送达他端并已被接手；②相关动作由谁执行、是否在途或已作废；③还有哪些收尾未闭合。而『是否生效』只能由权威 manifest 面回答——归属面与真值面不可互相替代，各自查一次即够

## Short path
- 记录声明时间戳，做一次限窗事件流查询，按消息内容匹配定位他端对同一声明的接手记录与在途动作
- 他端已接手：不重复其动作（不重推、不重启、不重审），只做独立权威抽查（服务 manifest 的 pid/started_at/git_head 对仓库 HEAD，desired 对 live）
- 限窗内无他端同主题内容匹配：转入单会话权威探针路径，停止上下文扫描
- 回报三段式：与他端一致的真值结论；动作归属（谁在何时执行，含延迟/代管重启等非用户手动情形）；未被声明覆盖的增量（仍跑旧代码的服务、在途审查尾巴）
- 两个面各自确认后立即停止，不追加确认性查询

## Stop conditions
- 权威面真值、动作归属、未覆盖增量三者均已确认且与他端公开结论对齐
- 限窗查询证明无他会话接手，且权威探针已给出完整答案

## Verification
- 本会话独立抽查（status 回执+进程谱系双通道）与他端处理会话结论一致：同 pid/generation/HEAD
- 确认未重复执行他端已执行或已声明作废的动作（重复 push/重启/审查）
- 增量项逐服务点名并标注重启归属，而非笼统接受『已重启』

## Counterexamples
- 声明仅针对本会话且限窗内无他端同主题内容匹配：跳过去重步骤，直接权威探针即可
- 限窗内他端活跃属其他 goal 的噪声：不能把时间邻近误读为接手，须按消息内容匹配判定
- 单会话环境或无事件流/协调面：方法不适用
- 声明是具体技术问题（报错、A/B 分支断言）而非状态动作声明：直接映射权威探针，无需归属考古
