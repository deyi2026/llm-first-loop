---
method_id: match-evidence-modality-to-user-complaint-752a2d104abd
name: match-evidence-modality-to-user-complaint
description: 当用户报告的是感知层症状（如『看不到密码框』『看起来没有』），核心未知量在渲染/视觉层；结构快照（DOM/AX）无论分页读多少，只能回答存在与可用性，回答不了『人眼是否看见/是否醒目』。应先取与投诉同模态的证据（截图+视觉分析），按结果分支：已渲染但不显眼→直接给原因与操作指引；未渲染→才转入结构层排查 absent/hidden/disabled。附带两点：credential 输入框 dom/ax 的 type/name 冲突（password vs textbox）是预期掩码语义，不是需深挖的异常；调用工具前先确认 action 接受的字段，避免 fields_mismatch 式猜测参数。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:1275:d0d2ded0a4cdd85c9e56
evidence_refs: learning:learn:ac42e6304307
created_at: 2026-09-18T19:19:26.133840+00:00
updated_at: 2026-09-18T19:19:26.133840+00:00
---
## Trigger
用户用感知动词报告 UI 问题（看不到/看不见/没显示出来/太暗/像没有），而工具箱同时提供结构层证据（DOM/AX 快照）与视觉层证据（截图/图像分析），且二者取证成本相近

## Discriminator
投诉谓词是『看到』而非『存在/失效』——这一点在任务起点即可观察，它把未知量定位到视觉渲染层：结构枚举对该未知量无判别力。另有时可见信号：密码框在快照中 dom 报 type=password 而 ax 报 textbox/name 冲突，属浏览器掩码语义，反而佐证字段存在而非异常。

## Short path
- 按投诉谓词分层：『看不到』→视觉层未知量；『没有/坏了/不生效』→结构或行为层未知量
- 感知类投诉先取同模态证据：对用户所述页面状态截图并做视觉分析，直接回答『是否渲染、是否醒目』
- 按视觉结果分支：已渲染但低对比度/无占位符 → 以视觉证据为因，给用户元素定位与操作指引；未渲染/空白 → 才转结构快照查 absent/hidden/disabled/off-viewport
- 结构确认只做一次定向核验（exists+enabled），把 dom/ax 在密码框上的冲突当掩码语义，不再分页通读整份快照
- 停止：解释与指引均引用与投诉同模态的证据，且结构状态与视觉发现交叉一致

## Stop conditions
- 视觉证据已直接判定目标元素渲染状态（含『渲染但低可见性』这类可发现性缺陷），且结构层确认其可交互
- 视觉证据显示页面整体未渲染/空白 → 问题移交渲染管线排查，本方法不再继续取证
- 用户澄清投诉实为功能性（输入被拒/提交无效）→ 换结构/行为层方法

## Verification
- 最终解释引用的证据模态与投诉模态一致：『看不见』的结论必须落在截图/视觉分析上，而非仅 DOM 存在性
- 交叉一致：视觉可见 ⇔ 结构 exists 且未 hidden/disabled；不一致时以更接近用户体验的一层为准并标注冲突
- 无 fields_mismatch 类猜测参数调用；action schema 可查时先查再调

## Counterexamples
- 投诉是功能性的（『提交没反应』『密码被拒』）→ 结构/行为证据为主，截图次要，不应套用本方法
- 视觉层不可得或截图已过期（页面需交互才进入目标状态）→ 结构快照先行是合理的
- 屏幕阅读器用户的可访问性投诉 → AX 树才是匹配模态，截图不能回答该问题
- 目标元素根本不在 DOM 中 → 问题变为『为何未渲染』（JS 错误/条件渲染），需查渲染管线而非视觉对比度
