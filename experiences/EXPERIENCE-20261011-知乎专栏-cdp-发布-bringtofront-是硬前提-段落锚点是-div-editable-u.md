---
title: 知乎专栏 CDP 发布：bringToFront 是硬前提，段落锚点是 div.Editable-unstyled 而非 p
scenario: "通过 CDP 直连（127.0.0.1:9229）向知乎专栏 zhuanlan.zhihu.com/write 发布中文长文（正文+本地配图+创作声明），无需人工介入。"
root_cause: ""
solution: |
  固化脚本 docs/promotion/_zhpub.py，顺序如下：
  
  1. Page.bringToFront 激活标签页 —— 硬前提。未激活时 Input.dispatchKeyEvent 静默丢失，粘贴/键入都不生效，且「发布」按钮恒为 disabled。曾因缺这一步误判成「知乎粘贴不登记内容、内部模型为空」，实际只是焦点丢失。
  2. 清空正文：不要用 Cmd+A（实测选区不生效）。可靠法 = Range.selectNodeContents(ed) + ed.focus() + 真实 Backspace 键。粘贴同样是「追加」而非「替换」，不清空就会内容翻倍。
  3. 正文投递：ClipboardEvent('paste')，DataTransfer 同时带 text/html 与 text/plain，target = .public-DraftEditor-content[contenteditable]。
  4. 配图投递：同一 ClipboardEvent，payload 换成 type=image/png 的 File。锚点元素是 div.Editable-unstyled，不是 <p>——按 <p> 查必然 NO_ANCHOR。
  5. 创作声明（「无声明」→「包含 AI 辅助创作 作者对内容负责」）：必须先 scrollIntoView 让按钮 rect 落入视口再点，否则点击坐标 y≈974 越界、点击落空。
  6. 发布前守门看「发布」按钮 disabled 状态，而非字数计数。
  
  已知降级：知乎粘贴净化丢弃 <b>/<strong>，行内加粗丢失；h2、blockquote、hr、图片保留。字数计数口径与正文 innerText 不等（如 3900 vs 3470），非内容缺失。
evidence: "两篇实际发布并公网实见通过：https://zhuanlan.zhihu.com/p/2092739969639102248（提醒发了，事情却没人接，22:20，yyj，含「包含 AI 辅助创作 作者对内容负责」，6 个 h2，3 图，3644 字）与 https://zhuanlan.zhihu.com/p/2092741427319068055（AI 都不敢生成这种图，22:21，6 个 h2，2 图，3508 字）。回执 docs/promotion/receipts/20261011-daily08-zhihu.json、20261011-daily09-zhihu.json。"
tags: [cdp, zhihu, publishing, browser-automation, bringToFront, contenteditable]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T22:21:02.958208+08:00"
updated_at: "2026-10-11T22:21:02.958208+08:00"
supersedes: [EXPERIENCE-20261011-头条编辑器用-clipboardevent-注入图片会清空正文-必须用段落文本节点内的折叠光标-且粘]
---