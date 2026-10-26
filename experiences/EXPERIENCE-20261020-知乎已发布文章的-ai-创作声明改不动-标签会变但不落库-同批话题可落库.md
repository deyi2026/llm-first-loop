---
title: 知乎已发布文章的 AI 创作声明改不动：标签会变但不落库（同批话题可落库）
scenario: 对一篇已经发布在知乎专栏的文章，补设平台级「AI 创作声明」（包含 AI 辅助创作 作者对内容负责）
root_cause: ""
solution: 已发布文章的创作声明走编辑页更新路径不会持久化：四种点击路径下按钮标签都会变，但刷新后回到「无声明」，已发表页也无该行；同期话题能持久化，说明不是更新链路坏了。排查时注意「发布中…」可持续 25s 以上，此期间点「更新」会被忽略，容易误判为平台拒绝。结论：新文章务必在 /write 发布前一次设好声明；已发布文章只能靠正文内显式声明段落兜底。
evidence: docs/promotion/STATUS-20261020-why-agent-now-zhihu-wechat.md「未闭合（平台侧）」；/tmp/zh_decl_*.py 四次尝试与刷新后读回回执；已发表页 DOM 搜索「AI 辅助创作」= false
tags: [知乎, 创作声明, 平台合规, 未闭合]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T22:09:23.014058+08:00"
updated_at: "2026-10-20T22:09:23.014058+08:00"
---

2026-10-20 对已发布的知乎文章 https://zhuanlan.zhihu.com/p/2095986664028033172 补设创作声明，四次尝试：
1) 合成事件链（mousedown/mouseup/click + scrollIntoView）点「无声明」下拉并选「包含 AI 辅助创作 作者对内容负责」——按钮标签会变成 AI 声明值，但点「更新」后刷新仍为「无声明」。
2) 真实坐标点击（Input.dispatchMouseEvent）选下拉项，标签同样变更。
3) 用 browser_operate（Host 通道）对 grounding_ref / kind+name 点击。
4) 等待更新完成后再刷新（此前一次是在按钮仍显示「发布中…」时刷新，把更新请求打断）。
现象：刷新后编辑页 /p/{id}/edit 的创作声明控件回到「无声明」，已发表页 .Post-RichTextContainer 全文搜索「AI 辅助创作」无命中；同期添加的话题「人工智能」在已发表页 a.TopicLink 可见，说明更新链路本身可用、只有创作声明字段未落库。
判断：对**已发布**文章，创作声明走编辑页更新路径不生效（至少本环境如此）。文章正文末尾保留显式声明段落作为兜底。新发文章应在发布前于 /write 的发布设置里一次设好（见 experience:EXPERIENCE-20261020-zhihu-write-publish-then-set-ai-declaration）。
排查坑：知乎「发布中…」状态可持续 25s 以上；在此期间点「更新」会被忽略，误判为"平台拒绝"。

当前性验证：复现路径为打开该文章 /p/{id}/edit，读「创作声明」控件文本（预期「无声明」）并在已发表页 DOM 搜「AI 辅助创作」（预期无命中）；两处读数若相反，说明平台行为已变，以读数为准。