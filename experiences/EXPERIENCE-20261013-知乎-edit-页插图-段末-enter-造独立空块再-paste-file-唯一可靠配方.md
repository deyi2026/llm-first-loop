---
title: 知乎 /edit 页插图：段末 Enter 造独立空块再 paste File（唯一可靠配方）
scenario: "知乎专栏编辑器（zhuanlan.zhihu.com）在 /write 粘贴正文后会自动跳转 /p/{draft}/edit 并存草稿；需要按位置插入本地图片并保持章节 h2 结构不被破坏。"
root_cause: ""
solution: "1) 正文用整篇合成 paste（selectNodeContents+Backspace 清空，再 dispatch paste 带 text/html+tune 后的 HTML）——这是唯一可靠的写入入口。2) 插图定位不能靠脚本 Range.setStartBefore（DraftJS 不采纳，会落到编辑器末尾），必须 Input.dispatchMouseEvent 真实点击。3) 真实点击后再 paste File 会把所在 h2 降级成 DIV，且工具栏「标题/二级标题」「el.click()」、段首 Backspace、Ctrl+Z 全部无效——块类型切换与删除类编辑在 /edit 页整体被 DraftJS 内部 selection 同步问题阻断，不要再尝试。4) 正确做法：定位目标 h2 的前一块，取该块 TreeWalker 最后一个非空文本节点，用 getClientRects() 最后一行定位（x=right-1, y=top+min(height/2,4)）真实点击 → 按 Enter 生成独立空块 → 点空块 → 合成 paste File 图；这样段落不被 split、h2 不降级，图紧贴目标标题之前。5) 删除已插图片：真实点击 figure 中心选中后按 Backspace。6) data URI <img> 随 HTML 粘贴只会得到知乎占位图（多图共用同一占位 src），不能用。当前性验证：跑 `python3 docs/promotion/_zhpub13.py` 应输出 gate 结果 h2n=6、imgs=2、loaded=2 且 images 不出现在标题之前（块序中 figure 紧贴 H2）；复现验收 `grep -c \"添加图片注释\" /tmp/zh13verify2.log` 应为 0（公网无占位文字）。"
evidence: docs/promotion/receipts/20261013-daily13-zhihu.json（文章 2093317776920392419 已发布；编辑器侧 h2=6、imgs=2 loaded 1000x690/1000x672；公网整页截图 zh13_article_verify.png 与裁剪 zh13_crop_a/b.png 确认图位正确、无占位文字）；失败对照：data URI 方案两张图 src 相同占位、h2 降级为 DIV/H3、Range+Backspace 与 el.click() 均无效果。
tags: [知乎, CDP, DraftJS, 插图, 发布流程]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T12:47:46.319793+08:00"
updated_at: "2026-10-13T12:47:46.319793+08:00"
supersedes: [EXPERIENCE-20261013-头条图文发布-整篇-html-合成-paste-真实点击插图-发布后必须用浏览器验收, EXPERIENCE-20261012-知乎编辑页二态-write-可合成粘贴-p-id-edit-只认-inserttext-按钮]
---