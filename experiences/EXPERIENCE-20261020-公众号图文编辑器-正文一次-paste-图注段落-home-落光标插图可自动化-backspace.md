---
title: 公众号图文编辑器：正文一次 paste + 图注段落 Home 落光标插图可自动化，Backspace 级联会吞标题末字
scenario: 把一篇含表格、3 张本地配图和 3 条图注的长文发布到微信公众号图文编辑器（mp.weixin.qq.com/cgi-bin/appmsg?action=edit）
root_cause: ""
solution: 标题与正文分处两个 ProseMirror，需分别写入：标题用 Input.insertText，正文用一次 HTML paste；表格随 HTML 保留。配图用「点图注段落 → Home 落光标 → File 合成 paste」，图片自动转存 mmbiz 且落在图注上方。严禁用 Home/Shift+End/Backspace×3 清占位段，会吞掉前一个原子节点（图片）并吃掉相邻段落末字；必须用 Range.selectNode 选节点后只按一次 Backspace。每次编辑后用页面渲染态 dump 逐块核对 H2/图注/表格，RULE-AI-28 送审稿也按该 dump 生成。
evidence: docs/promotion/_pub_wx_agentnow.py 阶段化脚本；docs/promotion/_wx_agentnow.dump.jsonl（终态 70 块/7834 字符/7 H2/表格 4x3/3 图 mmbiz/3 图注/残留 0）；docs/promotion/_wx_agentnow.publish.md（按渲染态生成）；docs/promotion/STATUS-20261020-why-agent-now-zhihu-wechat.md
tags: [公众号, mp.weixin.qq.com, ProseMirror, 图文发布, 插图, RULE-AI-28]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T22:08:56.624604+08:00"
updated_at: "2026-10-20T22:08:56.624604+08:00"
supersedes: [EXPERIENCE-20261015-知乎图文必须走-h2-锚点-回车占位-file-合成-paste-data-uri-被拒-range]
---

实测（2026-10-20，mp.weixin.qq.com 图文编辑器）：

1) 正文链路可自动化：标题与正文是两个独立 `.ProseMirror`（标题带 data-placeholder="请在这里输入标题"，正文 clientHeight 更大）。正文用一次 HTML paste 落入即可，表格随 HTML 保留，markdown 残留为 0。
2) 配图：点图注段落 → Home 落光标 → File 合成 paste（ClipboardEvent + DataTransfer），图片会自动转存 mmbiz.qpic.cn，实载 1619–1621px，位置落在图注上方。
3) **危险**：为清理占位段落而做的 Home/Shift+End/Backspace×3 会连带删掉前一个原子节点（图片），也会吞掉相邻段落的末字。本轮实测把第三节、第六节两个 H2 各吞掉最后一个字（"不可靠"→"不可"、"版本"→删掉），由 RULE-AI-28 送审（页面渲染态 vs 稿件逐行比对）抓出并用 Input.insertText 补回。正确做法是用 Range.selectNode 精确选节点后只按一次 Backspace。
4) 送审稿按页面渲染态逐块生成：图片块整块不入稿，表格行转成 `| a | b | c |`。

封面与发表：见单独记录（封面无法自动化）。