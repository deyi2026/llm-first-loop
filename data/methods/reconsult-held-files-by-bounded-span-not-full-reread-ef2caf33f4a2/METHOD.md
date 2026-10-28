---
method_id: reconsult-held-files-by-bounded-span-not-full-reread-ef2caf33f4a2
name: reconsult-held-files-by-bounded-span-not-full-reread
description: 长实现/验证会话中，再次需要查阅一个本 run 早前回执已完整读取、且带内容身份标识的文件（源码或设计文档）时，把重取压到当前未知量的锚点段落：先核对早前回执的 version_token/sha256 是否仍代表当前文件（未编辑即未变），再用有界 range read / evidence hydration 只取所需行段，不做整文件等值重读；标识变化（自己已编辑）才重读变更区域，跨文件语义问题改用窄 grep。把重取从『再确认整个已知相同的文件』变成『按未知量取一小段』，长会话中直接削减重复字节与轮次。
status: active
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:31e64fa8-0da2-4a1c-afd1-a74ed4fcd805:311:a4535998d6b7d48d009a
evidence_refs: learning:learn:f8ef2cc56351
created_at: 2026-10-19T09:33:29.521208+08:00
updated_at: 2026-10-19T12:28:30.931768+08:00
---
## Trigger
多轮长会话（实现/验证/审查循环）中，上下文可能已淘汰早前内容，此刻需要再次查阅某源文件或设计文档；而本 run 早前工具回执已完整读取过它（coverage=complete，含 version_token/sha256/snapshot_ref 等身份标识），且当前问题带明确 file:line 锚点或符号名（来自设计文档事实表、traceback 或早前回执）。

## Discriminator
重取前已在手的三件事实：(1) 早前回执 coverage 覆盖所需行且为 complete；(2) 该文件期间未被自己编辑（version_token/stat 标识不变，read_file 回执或 git 状态可证）；(3) 当前未知量可映射到具体锚点行/符号。三者齐备即证明整文件重读只会返回逐字节相同内容、信息增益为零；缺任一条（已编辑/覆盖不全/无锚点）才需要发起真正的新读取。

## Short path
- 把再次查阅写成一个可定位的未知量（哪个符号/哪几行/哪个断言），并找到它的锚点（设计文档 file:line、traceback、早前回执行号）。
- 核对早前回执的身份标识（version_token/sha256/mtime:size）：未变 → 所持内容即当前真值，整文件重读无增益；已变（自己编辑过）→ 只计划重读被改区域。
- 若内容已不在工作上下文，用有界 range read 或 evidence hydration 只取锚点附近行段（沿用回执的 next_start/coverage 定位），而非 1-N 行全量重读；运行时已有 exact-read 复用时优先走复用路径。
- 校验取回片段的锚点行落在预期符号上、回执身份标识与早前一致，随即返回原任务；记录本次 span+标识供下次重取。

## Stop conditions
- 锚点段落已取回且身份标识与早前回执一致 → 未知量已解，立即停止进一步读取。
- 身份标识变化（本 run 内自己编辑过该文件）→ 只重读变更区域并将其作为新的权威回执，旧 evidence 按 stale 处理。
- 问题不是段落形状（如『哪些 callsite 使用某 flag』）→ 改用作用域受限 grep/跨文件检索，不再重读单个文件。

## Verification
- 新回执的 version_token/sha256 与早前回执逐字段一致，证明取回段落即当前工作区内容而非过期快照。
- 锚点行号命中预期符号/函数定义；若未命中，说明覆盖或行号假设错误，改读更大范围或重新定位，而不是默认信任该片段。

## Counterexamples
- 本 run 内自己已编辑过该文件（标识已变）：水合旧 evidence 会拿到 stale 字节，必须读 live 变更区域。
- 早前读取本身是有界/截断的（complete:false，如大文档 range read），所需行在覆盖之外：必须从源头扩展 range，而非复用已持 evidence。
- 需要的是跨文件语义结论（调用方分布、某参数是否被使用）：任何单文件段落重读都无法回答，正确工具是窄 grep。
- 文件只有几十行且无明确锚点：记账成本超过收益，直接整读即可。
