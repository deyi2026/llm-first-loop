---
method_id: operate-target-not-found-enumerate-snapshot-index-b5fa1def1994
name: operate-target-not-found-enumerate-snapshot-index
description: 当 snapshot 支撑的语义 operate 以 target_not_found/match_count=0 熄火时，匹配器的候选空间是已捕获的 grounding 快照——一个封闭索引。match_count=0 证明所假设的身份（document 名、页面标题、region role）不在索引里，而非瞬时故障。此时不要再生成新的名字假设；应查询快照 projection，找真正携带所需属性（如 link/button 上的 attributes.name，用 matched_total 确认类非空）的对象，用其中一个已验证对象作为 operate 锚点。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:43696f9c-0fd9-4c30-b4d9-3f05343cba9a:84:3cbe723fc33e946e6375
evidence_refs: learning:learn:758b100c652c
created_at: 2026-10-06T02:21:13.145776+08:00
updated_at: 2026-10-06T02:21:13.145776+08:00
---
## Trigger
使用基于快照的语义 operate（或任何针对已捕获观测做目标解析的匹配器）时，操作以 target_not_found / match_count=0 halted，而下一步诱惑是再猜一个目标身份（标题、角色、文档名）。

## Discriminator
熄火回执本身已给出两条当时可用的判别事实：(a) halt_reason=target_not_found、match_count=0 是对封闭索引的精确 miss，automatic_retry=false，不是超时类瞬态失败；(b) 快照对象只在特定交互类（link/button）上携带 attributes.name，document 对象 hydrate 后仅 {tag: html} 无 name，main/region 查询 matched_total=0——即任一候选身份的存在性可直接从索引查证，无需猜测。

## Short path
- 收到 match_count=0 即停，不发出第二个带新假设名字的 operate。
- 对最新快照 projection 按可能携带 name 的 kinds（如 link/button/text）过滤查询，用 matched_total 确认该类非空。
- 取一个 attributes.name 显式存在的对象作为 operate 锚点。
- 只重发一次 operate；要求回执 match_count>=1 且 scope_relation=same。
- 若索引证明没有任何对象携带所需属性，放弃目标匹配路线换策略，而不是继续枚举身份。

## Stop conditions
- 回执 match_count>=1 且 scope_relation=same——锚点/绑定目标已达成，即使动作本身副作用为空（如零位移 scroll）。
- 快照 projection 证明没有对象携带所需属性——切换策略而非继续猜名字。

## Verification
- 检查回执字段：match_count=1、scope_relation=same、steps_executed=1，确认是精确命中而非模糊重绑。
- 被验证的命题（如同宿主绑定）以回执的 match/scope 字段为准，而非动作副作用；action_receipt_status:failed 且 changed=0 的 no-op 不否定绑定证明。

## Counterexamples
- 快照已过期、与活页 generation 不一致：先重打快照；对陈旧索引的 match_count=0 不能证明活页上不存在。
- 匹配机制是活页模糊匹配而非快照解析，或目标本身就是带真实可访问名的 document：此时 match_count=0 不证明索引缺席，首次尝试若成功则本方法无需介入。
- 未知量是文档身份本身（如按标题导航）而非交互锚点：枚举 button/link 与该未知量无关，不应套用。
