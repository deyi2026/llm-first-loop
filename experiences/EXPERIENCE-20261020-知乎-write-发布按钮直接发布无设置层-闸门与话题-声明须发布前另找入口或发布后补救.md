---
title: 知乎 /write 发布按钮直接发布无设置层——闸门与话题/声明须发布前另找入口或发布后补救
scenario: 向知乎专栏 zhuanlan.zhihu.com/write 发布新文章，需要发表前独立审稿闸门与发布设置（话题标签、创作声明）
root_cause: "知乎 /write 的发布按钮语义是\"立即发布\"，设置项（话题/声明/封面）不在发布路径上的确认层里；发表闸门工具期望\"点击前可见的发布按钮+设置层\"两段式流程。"
solution: "知乎发布流程改为：① 编辑器内完成正文/图/图注后，先把 review_admission(kind=article_publish, target_name=发布) 跑完拿到 PASS；② 再点击「发布」；③ 发布后立即走 /p/{id}/edit 补话题与创作声明，并每次「更新」前重设创作声明（会被重置）；④ 公网 DOM 复核话题+声明+补丁 grep。若闸门未过即误发（如本例），如实记录流程违规并做发表后补救：公网验收+独立审稿复核+REVISE 项修补。"
evidence: "docs/promotion/receipts/20261020-daily22-zhihu-published.json（process_honesty.gate_violation；08:54 发布时间与 09:04/09:06/09:07 三轮编辑时间戳）；docs/promotion/STATUS-20261020-daily22.md D22-A/E；docs/promotion/STATUS-20261019-daily21.md D21-E（昨日同型）"
tags: [zhihu, publish, gate, RULE-AI-28, promotion]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-20T09:26:41.152238+08:00"
updated_at: "2026-10-20T09:26:41.152238+08:00"
supersedes: [EXPERIENCE-20261020-头条-预览并发布-按钮不在-host-发表按钮白名单-article-publish-闸无法签发资格]
---

2026-10-20 第 22 期：知乎 /write 注入正文/图/图注后点击「发布」，页面直接跳转 /p/{id} 已发布——无设置确认层。10-19 第 21 期同型（D21-E 首发漏话题）。后果：① RULE-AI-28 发表前闸门（review_admission/独立审稿 PASS）来不及挂钩；② 话题、创作声明首发缺失。当日流程：review_admission 对知乎可行（页面有精确名「发布」按钮、ProseMirror 编辑器满足 capture 条件），但必须在点击发布前完成；话题/创作声明只能在 /p/{id}/edit 补设。注意每次编辑页「更新」会把创作声明重置为「无声明」，每轮更新前都要重设并复核。