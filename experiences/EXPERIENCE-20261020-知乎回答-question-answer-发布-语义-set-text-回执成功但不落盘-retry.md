---
title: 知乎回答（question/answer）发布：语义 set_text 回执成功但不落盘，retry_tool 绕过参数重排，CDP 直连 ClipboardEvent 投递是可靠路径
scenario: "在知乎（zhihu.com/question/xxx）用语义 browser_operate 或 CDP 直连，给问题撰写并发布一条长中文回答，含章节标题，需要过独立审查闸（RULE-AI-28）后再点\"发布回答\"。"
root_cause: ""
solution: "语义通道写入失败（回执成功但 DOM 无变化）时不要反复重试或换参数——直接切 CDP 直连（127.0.0.1:9229）+ docs/promotion/zh2.py 助手：bringToFront → Range.selectNodeContents + Backspace 清空 → ClipboardEvent paste（text/html + text/plain，target=.public-DraftEditor-content）→ 以\"发布回答\"按钮 disabled 状态为守门 → 点击发布 → 跳转到 /answer/<id> 后用登录态浏览器回读正文做验收。模型侧 tool_call 参数被 schema 引导解码重排时（text 被塞进 target），用 retry_tool 显式传参绕过。"
evidence: "2026-10-20 实跑：语义 set_text 连续 4 次回执 completed 但 value_text 恒为 \"\n\"（会话文件 30775cd1-*.json 中 tool msg 115/117/121/145/147/149/161 记录了实际派发参数 text 被塞进 target）；retry_tool 绕过重排后契约通过；CDP 直连后 ed.innerText 长度 4327→4467→4457，发布后 URL 跳 answer/2095915218119438371，浏览器回读 len=4457 h2=6，首尾与审后稿一致。知乎匿名 web_fetch 403（此前分析阶段同 URL 族亦 403）。"
tags: [zhihu, browser, cdp, publishing, draftjs, retry_tool, review-gate, verification]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T16:31:36.307447+08:00"
updated_at: "2026-10-20T16:31:36.307447+08:00"
---

场景：知乎回答（question/xxx/answer 编辑器，非专栏 zhuanlan）用语义 browser_operate 发布长中文回答。

## 1. 语义 browser_operate 在知乎富文本编辑器上"回执成功但无写入"
- 现象：`set_text` 回执 status=completed、steps_executed=1、match_count=1，但编辑区 value_text 仍为 "\n"，页面 DOM 无变化，截图 sha256 不变（截图另有缓存问题：vision 路径 mtime 不更新，别用它判断页面是否变化）。
- 根因：知乎回答/专栏编辑器是 Draft.js（`.public-DraftEditor-content[contenteditable]`），DOM 只是投影，权威状态在编辑器模型；语义 set_text 走 CDP 事件管线时对这类受控组件不落盘。
- 结论：知乎这类富文本编辑器**不要用语义 set_text**，直接走 CDP 直连（127.0.0.1:9229）。

## 2. 模型侧 tool_call 参数被重排（独立于契约）
- 现象：browser_operate 的 set_text 调用，schema 顶层 required 含 delta_pages；实际派发参数变成 `{"do","target"}` 且 **text 被塞进 target 内部**（target schema 是 oneOf: kind+name / kind+name_normalized / grounding_ref），于是 provider 契约 set(step)=={do,target,text} 判失败，报 `text_step_fields_mismatch`。
- 规避（已验证有效）：用 `retry_tool(tool_name="browser_operate", arguments={...})` 显式传参，绕过 schema 引导解码的键重排，契约立刻通过。retry_tool 仍走完整安全/校验/超时包裹。

## 3. CDP 直连知乎回答的可用配方（复用 docs/promotion/zh2.py）
- 激活标签页：`Page.bringToFront` 是硬前提，未激活时键入/粘贴静默丢失。
- 清空正文：不要 Cmd+A（选区不生效）。用 Range.selectNodeContents(ed) + ed.focus() + 真实 Backspace 键；粘贴是"追加"不是"替换"，不清空会翻倍。
- 投递正文：ClipboardEvent('paste')，DataTransfer 同时带 text/html 与 text/plain，target = `.public-DraftEditor-content[contenteditable]`。
- 章节标题：在 text/html 里用 `<h2>`，Draft.js 会转成真正的 h2 块（知乎回答无标题栏，h2 是合规的层级）。
- **注意**：知乎净化会丢弃 `<strong>`/`<b>`（实测 b=0），但保留 h2/blockquote/hr/图片。若正文需要强调，改用独立段落或 blockquote，不要指望行内加粗。
- 发布前守门：看"发布回答"按钮的 disabled 状态（发布按钮文本是"发布回答"，与专栏的"发布"不同），不要看字数计数。
- 回答页的编辑器选择器与专栏一致：`.public-DraftEditor-content`。

## 4. 验收
- 发布后 URL 会跳到 `.../question/<id>/answer/<answer_id>`，回答页正文容器可用 `.RichContent-inner` / `.AnswerItem-content` 读取。
- web_fetch 匿名抓知乎会 403（已轮换 UA 仍失败），这是站点反爬特性而非发布失败；公网回读要用登录态浏览器（zh2.ev + bringToFront）做。
- 截图（browser_perceive vision）存在缓存：同一 path 的 mtime 可能不更新，判断"页面是否变化"要用 DOM/文本读取，不要用截图 sha。
