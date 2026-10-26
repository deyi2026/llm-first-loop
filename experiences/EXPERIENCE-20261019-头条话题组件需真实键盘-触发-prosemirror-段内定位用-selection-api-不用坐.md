---
title: "头条话题组件需真实键盘 # 触发；ProseMirror 段内定位用 Selection API 不用坐标点击"
scenario: "通过 CDP 向今日头条 mp.toutiao.com 图文编辑器（ProseMirror）正文插入平台话题组件（#xx# 蓝色可点击话题），并做段内精确光标定位与文本修复"
root_cause: ""
solution: "话题组件：真实 keyDown '#' → 浮层 → insertText 过滤词 → 点候选。段内定位：TreeWalker+Range。清理保护：每步退格后读块内容。当前性验证：先在活页面确认 .mention-selector-modal 类名仍存在再沿用。"
evidence: "本会话 CDP 回执：TAG_BLOCK innerHTML 含 syl-inline/tteditor-forum data-id=5500688358（2026-10-19 13:2x）；缺陷与修复记录 docs/promotion/STATUS-20261019-daily20.md D20-A"
tags: [toutiao, cdp, topic-tag, prosemirror, promotion]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-19T13:31:32.286918+08:00"
updated_at: "2026-10-19T13:31:32.286918+08:00"
---

头条正文里输入 # 后的话题浮层由真实键盘事件触发：Input.dispatchKeyEvent(keyDown, key='#', text='#') 会在光标处弹出 mention-selector-modal；再用 Input.insertText 输入过滤词会出现候选列表（如 #人工智能# 15万讨论），点击候选即插入 <syl-inline __syl_tag="true"><a class="tteditor-forum" data-id=…> 话题组件（innerText 带 \u0002 控制符是组件特征）。反例：跳过 # 键盘事件直接 Input.insertText('#人工智能') 只会得到纯文本段落，无浮层、无组件。配套教训：ProseMirror 段内光标定位不可用坐标点击（点击会落在段落中部），必须用 document.createTreeWalker 找文本节点 + Range/Selection 精确置位后再 insertText；退格清理时逐次检查块文本，防止合并吞掉相邻段末尾文字。

当前性验证：在头条发布页 CDP 执行 `document.querySelector('.ProseMirror[contenteditable]')` 存在且执行 keyDown('#') 后 1.5s 内 `document.querySelector('.mention-selector-modal')` 可见，说明该方法仍适用；若浮层类名变化，grep 页面 DOM 中含「话题」的弹层类名再定位。复现：docs/promotion/_tag20.py 的修正版流程（keyDown '#' → insertText 过滤词 → 点候选），应得到含 syl-inline/tteditor-forum 的话题块。