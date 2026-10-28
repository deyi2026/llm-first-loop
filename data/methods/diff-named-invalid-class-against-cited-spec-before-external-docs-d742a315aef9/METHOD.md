---
method_id: diff-named-invalid-class-against-cited-spec-before-external-docs-d742a315aef9
name: diff-named-invalid-class-against-cited-spec-before-external-docs
description: 当运行在传输层成功但本地契约校验输出具名失败类（如 xxx_not_in_options）时，先做仓内闭环：失败类→校验代码行→该模块 docstring/注释引用的权威规格（设计文档章节、官方 schema 副本、契约常量旁的官方域记录）→spec 与实现的字段/形态 diff；再用已观察的兄弟字段证据（如概率分布键集恰等于发送选项集）判定『远端已理解、错在本地映射』。因实现与其 mock/fixture 常共享同一盲读，仓内定位后仍需一次定向外部权威确认（用已知官方 reference URL，不靠搜索猜路径）。把『先猜文档 URL、换措辞搜证据库、泛 web 搜索』放在 diff 之后。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:d1e343a5-0eb5-4b62-b607-a8cd333ed256:659:311d4569049ecfe057cc
evidence_refs: learning:learn:7ce37daf9841
created_at: 2026-10-15T12:29:34.574157+08:00
updated_at: 2026-10-15T12:29:34.574157+08:00
---
## Trigger
一次运行/管线在 transport/HTTP 层成功，但本地 schema/契约校验对若干条目给出具名 invalid 类别；且定义该校验的模块可在本地读取，并引用了可本地读取的权威规格（设计文档章节锚点、契约常量注释、vendored schema 或官方域记录）

## Discriminator
具名失败类直接映射到本地校验代码里的单一判别式（如 `value in options`），把未知量收窄为『权威规格规定的字段/形态 vs 实现实际读取的字段/形态』这一个 delta；而该权威规格当时已在仓内可得（本集：契约模块自述为设计文档 §8.x 的实现锚定，且该文档 §11.6 数分钟前刚被读过）——无需先做外部发现即可完成归因

## Short path
- 按预注册中止条件停在『unexplained invalid』：recorded-but-invalid 视为失败，冻结预算内不重发、不追加
- 从报告/事件提取逐条具名失败类，grep 定位定义它的校验行，明确它牵出的唯一未知量（本集：响应实际携带哪个字段）
- 沿校验模块自引用的权威规格边（docstring § 锚点/仓内设计文档/vendored schema/契约常量旁的官方域）做 spec-vs-实现字段 diff，得到候选根因
- 用已观察兄弟字段佐证方向（如概率键集==发送选项集→远端理解正确、错在本地提取），排除远端侧假设
- 因实现与 mock/fixture 可能共享同一盲读，做一次定向外部权威确认（已知官方 reference URL，不靠搜索猜测）；随后如实报告并要求新一轮授权重跑

## Stop conditions
- 根因（字段/形态 delta）已由仓内 cited spec + 外部权威或已持久化原始报文两路以上独立证据钉死
- 仓内锚点沉默/含糊，或本身疑似由实现反写（spec-by-impl）→外部权威源转为主导路径
- 失败类不映射本地判别式（远端 5xx/超时/纯语义值错误）→改用一般根因分析方法
- 原始报文未持久化且规格含糊→不得仅凭文档下结论，需授权后带持久化的最小复跑

## Verification
- 修复恰好采用规格字段名，且可推断会对已录响应翻转观察到的失败类（对照兄弟字段行为不变）
- mock/fixture 期望改为从权威规格再生成，而非从修复后实现再生成，打破共享盲读
- 确认诊断全程零额外计费外发、冻结预算未被穿透；被拒报文摘要持久化已列入修复项

## Counterexamples
- 仓内规格本身由同一实现反写或已过期：diff 无差异但 bug 仍在，必须以外部/运行时 schema 为唯一权威
- 失败源于远端（HTTP 5xx、限流、超时）或纯语义值错误（字段合法但内容/分布错）：字段映射 diff 不适用
- 校验器只输出布尔失败、无具名类别：先补具名分类，再谈 spec diff
