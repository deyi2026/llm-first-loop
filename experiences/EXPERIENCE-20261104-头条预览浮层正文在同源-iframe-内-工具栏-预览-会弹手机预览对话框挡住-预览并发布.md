---
title: 头条预览浮层正文在同源 iframe 内；工具栏「预览」会弹手机预览对话框挡住「预览并发布」
scenario: 今日头条图文发布链路：点「预览并发布」后要实读预览浮层文本，确认浮层内容与当前编辑器一致（重贴稿件后必查，否则可能用旧预览发布）。
root_cause: ""
solution: 浮层正文在 .preview-article-article iframe 的 contentDocument 里，读它而不是读容器；工具栏「预览」按钮会弹「手机预览」对话框，先「关闭预览」再点「预览并发布」。
evidence: 本班实测：浮层容器 innerText 长度 0，iframe contentDocument 文本长度 7603 且命中新串/不含旧串；receipts/20261104-daily59-public-body.json；审稿与发布链路脚本 docs/promotion/_d59_publish.py
tags: [头条发布, CDP, 预览浮层, iframe]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-04T13:40:46.114243+08:00"
updated_at: "2026-11-04T13:40:46.114243+08:00"
supersedes: [EXPERIENCE-20261104-修订稿重贴后必须重开预览浮层并实读浮层文本-否则可能用旧预览发布]
---

今日头条发布页点「预览并发布」后，浮层正文**渲染在同源 iframe 内**：容器 `.preview-article-article` 的 innerText 长度为 0，其唯一子节点是 `<iframe>`（外加一个 `.preview-loading` 占位）。直接读容器会误判为「空预览」。

正确读法（CDP Runtime.evaluate）：`document.querySelector('.preview-article-article iframe').contentDocument.body.innerText`。

本班用它实读浮层文本，确认浮层含终稿新串「只有它在“送达 vs 采用”这个坐标上把它单独拿出来量化」且不含旧串「只有这篇把它单独拿出来量化」，从而证明「重贴后重开预览」这一步真的生效，而不是拿旧预览发布。

配套坑：编辑器工具栏的「预览」按钮会弹出**「手机预览」对话框**（遮罩 + 「关闭预览」按钮），遮住「预览并发布」；此时页面里根本找不到「预览并发布」按钮。必须先点「关闭预览」，再点「预览并发布」。

当前性验证：跑 `python3 -I docs/promotion/_d59_publish.py preview` 应输出 PREVIEW CLICKED 且 CONFIRM_BTNS 非空；读浮层文本应含上述新串。