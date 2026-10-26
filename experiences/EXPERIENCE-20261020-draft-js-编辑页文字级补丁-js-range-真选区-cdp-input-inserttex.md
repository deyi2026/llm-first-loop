---
title: Draft.js 编辑页文字级补丁：JS Range 真选区 + CDP Input.insertText 替换（方向键/三击/Shift 点击全无效）
scenario: "需要对知乎专栏已发布文章做文字级修订（/p/{id}/edit，Draft.js 编辑器）"
root_cause: Draft.js 用内部 EditorState 管选区，不响应合成键盘事件的选区扩展；但会监听 DOM selectionchange 事件把真 DOM 选区同步进内部状态，之后 CDP Input.insertText 走原生文本输入通道即可替换该选区。
solution: JS Range 跨目标短语建真选区（非折叠）→ 等 selectionchange 同步（~0.8s）→ CDP Input.insertText 替换文本 → DOM grep「新串≥1 且旧串=0」复核。勿用方向键/三击/Shift 点击做选区。
evidence: docs/promotion/receipts/20261020-daily22-zhihu-published.json patch_round.method/verify；docs/promotion/STATUS-20261020-daily22.md 补丁 grep 行
tags: [draftjs, zhihu, cdp, text-patch, promotion]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T09:26:51.154826+08:00"
updated_at: "2026-10-20T09:26:51.154826+08:00"
---

2026-10-20 第 22 期发布后补丁：需把「市面上没有任何模型的上下文窗口装得下」改为「远超主流模型上下文窗口的实用范围」并在自述局限补 ToolRet 边界。在 /p/{id}/edit 的 Draft.js 编辑器里，以下选区方法全部无效（块文本 189 字符不变）：三击、Cmd(4)+Left、Cmd+Shift(12)+Right、单击块首+Shift(8)+End、Shift+单击块尾、Shift+ArrowRight×8——window.getSelection().toString() 恒为 0，Backspace 无删除。唯一成功法：JS TreeWalker 找到目标短语的文本节点 → document.createRange() 跨短语 setStart/setEnd（非折叠）→ removeAllRanges+addRange → 等 ~0.8s（selectionchange 让 Draft.js 同步内部 EditorState）→ CDP Input.insertText 新文本 → 选区被替换。两次补丁均一次成功，发表页 DOM 验证旧串=0 新串≥1。