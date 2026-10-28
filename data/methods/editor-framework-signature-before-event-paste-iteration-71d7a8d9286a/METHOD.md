---
method_id: editor-framework-signature-before-event-paste-iteration-71d7a8d9286a
name: editor-framework-signature-before-event-paste-iteration
description: 向工作区零先例的第三方平台富文本编辑器自动化写入时，第一次 DOM 快照里目标元素的 id/class/属性已携带编辑器框架签名（如 edui 前缀→UEditor、ProseMirror class、Draft.js 数据属性）。签名即声明内容由该框架内部模型接管：合成 paste/DOM 事件注入会被其模型重写。正确顺序是先识别签名、用该框架原生 API 在最小字段（标题）验证一次写入并读回，通过后再批量搬运正文与配图；而不是迭代事件注入变体。同任务中有先例的平台（有已验证脚本/经验卡）直接复用脚本，不做编辑器发现。本集在零脚本零经验卡平台上事件粘贴标题被内部模型重写、多次失败后识别签名改原生 API 收口。
status: candidate
source_model: minimax/MiniMax-M3.1-Flash-Preview
source_episode_refs: episode:214d1ca4-043c-4d41-8fad-d50fecf79228:250:0a98bbdecd608572c5a6
evidence_refs: learning:learn:acbce68c603d
created_at: 2026-10-19T15:26:23.384827+08:00
updated_at: 2026-10-19T15:26:23.384827+08:00
---
## Trigger
浏览器自动化向第三方平台富文本编辑器写入标题/正文（发布或改稿），且该平台在工作区零先例（发布脚本/回执/经验卡检索均零命中），写入后出现内容被改写、丢失或重排的失败。

## Discriminator
写入目标元素的 DOM id/class/data 属性携带编辑器框架签名（edui*→UEditor、.ProseMirror、Draft.js 偏移属性等）。该签名在打开编辑器页的第一次快照时已可读，无需试错即可判定：内容模型归该框架管，事件级注入会被重写，原生 API 才是权威写入通道。另有一条覆盖判别：对平台名做脚本/回执/记录三层检索，零命中即『机制未验证』路径，应预算发现成本而非套用其它平台的粘贴流程。

## Short path
- 平台机制覆盖检查：对每个目标平台做一次文件名/内容 grep 与记录检索，分为『有已验证机制』与『零覆盖』两类；有覆盖平台直接复用既有脚本只改参数。
- 零覆盖平台：打开编辑器后第一步从已有 DOM 快照读编辑器容器的 id/class/属性，识别框架签名；未知量：内容模型由谁接管。
- 签名已识别→改用该框架原生写入 API，先在标题等最小字段写入一次并读回内部模型内容，确认未被重写。
- 最小字段验证通过后再批量搬运正文与配图；发布顺序按『发布后能否自助修改』排（复用既有方法），不可回滚平台最后发。
- 逐平台出回执（标题/源稿 sha/图片数）并公网回读终态 URL。

## Stop conditions
- 零覆盖平台：框架签名已识别，且原生 API 写入后读回内容与源稿一致（标题/实义行/图片数量与顺序无损）
- 每个目标平台都有发布回执且公网 URL 回读成功

## Verification
- 写入后读回编辑器内部模型内容（不只看 DOM 外观），逐条比对源稿实义行与图片数量/顺序
- 回执记录 title/源稿 sha/图片数，发布后以公网终态 URL 回读收尾，不以编辑器内状态收尾

## Counterexamples
- 编辑器是无框架签名的普通 textarea/contenteditable：没有『原生 API』可言，直接赋值或既有的事件/粘贴协议才是正解，本方法不适用。
- 平台提供可直接调用的发布 API 且有凭据时，应整体跳过编辑器自动化改走 API，而不是研究编辑器契约。
- 平台在工作区已有已验证发布脚本（本集的另一目标平台）：直接复用脚本，不做任何编辑器发现。
