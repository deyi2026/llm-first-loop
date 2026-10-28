---
title: 头条编辑器把正文「刚才」标记为未渲染 rel-time：写稿禁用相对时间词，admission 逐字闸是唯一拦截点
scenario: 通过 CDP ClipboardEvent('paste') 向头条 syl-editor 注入长文并走 review_admission(article_publish) 双闸发布。稿件含口语相对时间词「刚才」时，平台把该词标记为未渲染 <rel-time> 元素，admission 的稿件一致性比对（match_ratio）与 Rule28 内容审查均将其判为发布缺陷（P1 级：发布文本偏离送审稿）。
root_cause: 平台编辑器对口语相对时间词做自动富文本标记化（rel-time），ClipboardEvent paste 链路原样带入且标记在 innerText 投影中不可见，结构性收口指标（chars/imgs/captions）对其盲区
solution: 写稿阶段禁用「刚才/刚刚」等相对时间词，改用「此前/本会话」等静态词；发布链路 VERIFY GATE 之外必须保留 admission 逐字比对闸（本次正是它拦住了结构性检查的盲区）。修复走 md 换词→重建→全量重贴→渲染态 grep rel-time=0 复核。
evidence: "Rule28 首闸 REVISE 回执（child subagent_6e21c1330a75，P1-1 原文「literal unrendered <rel-time> markup appears twice…replacing the manuscript word 刚才」）；修复后渲染态送审稿 grep rel-time=0（docs/promotion/receipts/daily39-manuscript-page.txt）+ 二闸 PASS（subagent_d83fae58f27d，candidate 1e3ef302）；收口作品管理页 10-28 08:41 审核中（receipts/d39research/d39_close.json）"
tags: [头条, syl-editor, rel-time, review-admission, 内容级坑, 推广]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-28T08:42:39.173262+08:00"
updated_at: "2026-10-28T08:42:39.173262+08:00"
supersedes: [EXPERIENCE-20261024-review-admission-发表闸门-0-9-行匹配税-图片行结构性失配-编辑器把-刚才-等相]
---

现象：d39 稿件正文两处使用口语相对时间词「刚才」（「让它回顾自己刚才的整个工作过程」「不管刚才发生了什么」），头条 syl-editor/ProseMirror 在 ClipboardEvent paste 注入后把该词转成未渲染的 <rel-time> 标记，且扩散进预览与描述副本。Rule28 reviewer 判 P1：「发布正文将包含可见标记或丢词，偏离送审稿」。VERIFY GATE 的 chars/imgs/captions 等结构性检查全部无法发现此问题（innerText 计数不受影响），只有逐字对照送审稿的 admission 闸能拦住。

修复：md 全文替换「刚才」→「此前」/直接删除（两处：改「此前发生了什么」、删词为「回顾自己整个工作过程」），重建 HTML、重开 tab 全量重贴，页面渲染态 grep rel-time=0 复核，二闸 PASS。

预防：写头条稿时禁用「刚才/刚刚/今天早上」等会被平台标记化的相对时间词，用「此前/本会话/实验中」等静态词。若已发生，修 md 后必须全量重贴（编辑器内定点替换 rel-time 元素不可行）。