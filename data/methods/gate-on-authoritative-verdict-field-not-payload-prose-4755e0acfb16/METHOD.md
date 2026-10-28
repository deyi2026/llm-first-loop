---
method_id: gate-on-authoritative-verdict-field-not-payload-prose-4755e0acfb16
name: gate-on-authoritative-verdict-field-not-payload-prose
description: 当昂贵/高危下游动作（如跑完整 CI、部署）被硬门禁卡住——『仅当权威准入工具签发 PASS 且 P0=0/P1=0 才放行』——门禁判定只看工具返回的结构化 qualification/签名域。若同一回执的自由文本尾部（review_tail/日志）出现与结构化判定矛盾的 PASS 字样，把它当作需上报的差异，而不是满足门禁的证据；拿到明确非 pending 的终态即停止轮询与一切下游动作，把格式修复留给维护者。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f9e89f9d-a726-401b-8422-8a60f4b87371:0:bc705455aa7759e8772e
evidence_refs: learning:learn:7c7a5cf6284d
created_at: 2026-10-19T01:29:31.281043+08:00
updated_at: 2026-10-19T01:29:31.281043+08:00
---
## Trigger
用户指令把下游动作条件化为『权威审查/准入工具必须正式签发 PASS（含 P0=0/P1=0）才执行』，且该工具同时返回结构化判定域（qualification/reason）与自由文本日志尾部，二者表面冲突。

## Discriminator
工具已返回明确终态：结构化 qualification 为 REVISE/not_pass（reason=verdict_incomplete_or_not_pass），而非 pending/running；同时尾部含 'VERDICT: PASS P0=0 P1=0 P2=2' 子串。用户放行条件绑定的是准入工具的签发结果，故结构化域是权威回执，正文子串不是回执——此事实当时已足够裁决『停止』，无需再取任何新信息。

## Short path
- admission start：记录返回的 child_id 与工具签发的 candidate 指纹；若用户另给冻结 tree/patch SHA，说明派生口径后继续（审查本身独立进行）。
- status(child_id)：pending/review_still_running → 按原 child_id 等待轮询，不换参数、不重开 child。
- status(child_id)：一旦返回非 pending 终态，仅用结构化 qualification 域评估门禁；REVISE → 门禁失败，立即停止：不启动被门禁的命令，也不再追加确认性轮询。
- 报告中如实并列三件事：权威域（qualification+reason）、矛盾的尾部 PASS 子串、指纹绑定核验；给出疑似原因（如 verdict 行混入 P2 段导致解析不完整）并把修复决策（修正机器可读格式后重走全流程）交回维护者。

## Stop conditions
- 结构化 qualification 为终态且不满足门禁（非 PASS，或 P0/P1>0）→ 停止并报告，绝不运行下游命令。
- candidate 指纹相对准入冻结值漂移 → 停止并报告 drift（即使正文看似 PASS）。
- 终态已明确（非 pending/running）→ 不再为『确认』重复轮询同一 child_id；仅当终态性本身有歧义时，至多做一次诊断性重查后停止。

## Verification
- 回放检查：放行/停止决定只引用结构化判定域与指纹，从未把正文 PASS 子串当作门禁满足证据。
- 确认停止后无被门禁命令的启动记录、无重复 child/命令、无 commit/部署/配置激活类副作用。
- 报告同时包含权威判定与矛盾子串及 child_id/指纹，使差异可被维护者独立复核。

## Counterexamples
- 用户门禁明确以审查产物正文中的 verdict 行为权威、包装工具仅为传输通道时：应按正文判定，本方法不适用。
- 结构化域仍为 pending/running 而尾部已见终稿文本：尚未到终态，应继续轮询而非停止。
- 回执是网络超时/瞬时错误且无 qualification 值：属可重试传输失败，不是权威 not-PASS，重试不算反模式。
- 非 PASS 由指纹漂移引起：停止理由应报 drift 而非 verdict 解析问题，处置路径不同。
