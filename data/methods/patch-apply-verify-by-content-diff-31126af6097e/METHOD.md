---
method_id: patch-apply-verify-by-content-diff-31126af6097e
name: patch-apply-verify-by-content-diff
description: 对已发布内容或本地定稿打补丁时，replace 的目标串必须当次 grep 取精确原文；补丁后必须 grep「新串 ≥1 且旧串 =0」才算改了，不得把脚本退出 0 当作补丁生效。
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:fe0e1465-7509-459e-8792-eaaf6d7269f5:738:1340fd68cf251b68b0a6
created_at: 2026-10-12T20:03:10.574969+08:00
updated_at: 2026-10-12T20:03:10.574969+08:00
---
# 补丁必须按内容 diff 复核：断言失败必须阻塞

## Trigger
对已发布内容（公网页/多平台副本）或本地定稿做小段文字修正；或补丁通过字符串 replace 实现，且目标串来自记忆/上次阅读而非当次 grep。

## Discriminator
两个任一为真即触发：
(a) 补丁的「成功信号」是脚本无异常退出，而非内容层面的「新串在、旧串无」；
(b) 目标串来自记忆而非当次 grep（全半角/空格/标点易差一两个字）。

本集：尾注补丁串与实际文本差两字，replace 未命中，断言失败被误读为成功，错误措辞随两版上线（头条 19:21 / 知乎 19:33），19:44 公网验收 grep 实证旧文案仍在才发现。

## Short path
1. 补丁前先 grep 实际文本，取到**逐字精确**的旧串。
2. replace 后立刻 grep：**新串计数 ≥1 且旧串计数 =0**，两者都满足才算改了。
3. 断言 / exit code 非 0 必须阻塞流程并人工介入；不得 try/except 吞掉后继续发布。
4. 多平台副本逐个独立复核，不能以「我改了源文件」推及已发布副本——已发布副本必须走各平台编辑页读回后再 grep。

## Stop conditions
- 新串存在且旧串清零 → 才允许进入发布/更新。
- 旧串仍存在 → 停止，不得把「脚本跑了」当「改成了」。

## Verification
- grep 旧串 0 命中、新串 ≥1 命中（两条件缺一不可）。
- 对已发布副本，用公网/编辑页读回后的文本再 grep 一次。

## Counterexamples
- 目标串来自记忆而非当次 grep。
- 只 grep 新串不 grep 旧串（旧串仍在 = 没替换成功）。
- 用「脚本 exit 0」替代内容断言（异常被吞时 exit 0 与失败不可区分）。
- 把「源文件已改」当作「已发布副本已改」（两平台副本需独立修正）。

## 与既有卡的边界
- method:editor-model-authority-real-input-and-counter-invariants 管的是**编辑器权威状态**（字数/图片数不变量），本卡管的是**文本内容精确性**；两者常同场出现，互不替代。
- method:inspect-resulting-state-before-repeating-non-idempotent-action 管「失败误判导致重复变更」，本卡管「成功误判导致缺陷上线」，方向相反。
- experience:EXPERIENCE-20260824-200-43 管「引用未测数字」，本卡管「补丁是否真落盘」。
