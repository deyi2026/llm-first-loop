---
title: 发布前自检：md 图片 alt 残段是反复出现的残段污染源
scenario: 把本地 Markdown 转 HTML 后投到图文平台，平台正文里出现「!图注文案」这类无意义残段。
root_cause: md2html 未实现 image 节点，图片链接被剥壳后 alt 文本落入正文。
solution: "md→html 转换若不处理 `![]()` 语法，alt 文本会被「链接剥壳」规则转成普通段落，发布后成残段，历史上已两次触发（2026-10-12 D10、D13）。规范：转换后立即自检 `<p>![^<]*</p>` 与裸 `fig\d+`，清零后再发布；或在 HTML 阶段不输出 img 标签，图片统一走平台编辑器上传通道单独插入（顺带避免外链图床失效）。"
evidence: "docs/promotion/STATUS-20261012.md:32 与 STATUS-20261013.md（2026-10-13 D13 发布前实测 grep 命中 <p>!心跳协议：纯文本即结算</p>，已清除）"
tags: [发布前自检, md2html, 残段, 质量]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-13T11:19:15.262407+08:00"
updated_at: "2026-10-13T11:19:15.262407+08:00"
supersedes: [EXPERIENCE-20261012-md2html-图片-alt-必须写图注文案-否则正文出残段]
---

规则不是普适真理，发布前用一次廉价 grep 确认当前稿件是否命中该模式即可。

当前性验证：`grep -o '<p>![^<]*</p>' docs/promotion/<当期>.html` 与 `grep -c 'fig[0-9]' docs/promotion/<当期>.html`，两者都应为 0；复现：在 20261013-lfl-daily-13.html 上跑第一条命令，修复前命中 1 段（<p>!心跳协议：纯文本即结算</p>），修复后 0 命中。