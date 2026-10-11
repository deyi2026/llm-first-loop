---
method_id: dump-exact-identifier-on-grounded-target-match-failure-72ab37ee7540
name: dump-exact-identifier-on-grounded-target-match-failure
description: 语义/grounded 工具按 {kind,name,role} 精确匹配解析 target 失败、但该元素在页面上可见存在时，这是一次标识字符串失配或同名歧义，不是「工具不行」，也不是换裸脚本通道的理由。先在同层权威观察（AX/DOM snapshot，带过滤）读出确切 name 原文，逐字符比对不可见字符（U+200B 零宽空格、NBSP、首尾空白）并统计同名实例数：不一致→用确切名重试或提交 name 归一化/grounding_ref 直选的演进建议；多个同名且 target 无行级作用域→真实能力缺口，选人工或明确授权的替代通道。避免在回执被导航元素占满、projection 截断时反复做全量 snapshot。结论必须区分「名字失配/同名无 scope/元素不存在」三类。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:9f3f9ab8-30d9-4a2d-9f58-148054503778:2078:51e98b97c0d0d4457c96
evidence_refs: learning:learn:3a353ef7f76c
created_at: 2026-10-11T00:04:43.708164+08:00
updated_at: 2026-10-11T00:04:43.708164+08:00
---
## Trigger
语义操作（如 browser_operate 的精确 name 匹配）返回「找不到目标」类失败，而用户要操作的对象在当前页面上可见，其可见文本与所查名字看起来一致。

## Discriminator
元素可见存在 + 精确名匹配失败 ⇒ 失败位于标识字符串层（不可见字符/空白）或同名歧义层（多个相同 name 且 target 无行级 scope）；一条带过滤的 AX/DOM 确切字符串回执即可区分这两者，无需换执行通道、也无需全量重扫。

## Short path
- 若可见性本身存疑，先用一条视觉证据确认元素存在、可见文本与展开状态；纯名字失配问题可跳过此步
- 对失败 target 做一条带过滤的 AX/DOM snapshot（按 kind/text 收窄，如 button 且 text 含目标词），读出确切 name 原文
- 与失败调用的 target 名逐字符比对（零宽空格 U+200B、NBSP、首尾空白、大小写），同时统计同名实例数量
- 分支：字符串不一致→用确切名重试，或提交 name 归一化/grounding_ref 直选的演进建议；同名多实例且工具无行级 scope→判定真实能力缺口，推荐人工操作或经用户明确授权的替代通道
- 结论中明确归入「名字失配」「同名无 scope」「元素不存在」之一，然后停止

## Stop conditions
- 已取得确切标识字符串并与失败 target 比对完成，失败原因可被回执原文解释
- AX/DOM 中该元素不存在或无 name：转为 coverage/遍历问题，退出本方法走覆盖面诊断

## Verification
- 结论必须引用 AX/DOM 回执中 name 的原文（含不可见字符）作为证据，不能凭可见文本断言两者一致
- 若声称「能力缺口」，需同时给出三件证据：确切名原文、同名实例数、target 结构中确无行级定位字段

## Counterexamples
- 元素在 DOM/AX 中确实不存在（如 shadow DOM/iframe 未被语义层遍历）→ 是覆盖问题，不是字符串失配，本方法不适用
- 失败回执是超时或导航竞态而非 match 失败 → 应重新观察页面状态，不是 dump 标识字符串
- 语义层没有该操作对应的动作类型（非定位问题）→ 才考虑原始通道，且需用户明确授权
- 目标在 canvas/图片内，无任何 AX 名可读 → 字符串比对路径不适用
