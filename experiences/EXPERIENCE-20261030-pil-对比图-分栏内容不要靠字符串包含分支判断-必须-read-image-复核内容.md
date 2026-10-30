---
title: PIL 对比图：分栏内容不要靠字符串包含分支判断，必须 read_image 复核内容
scenario: 为对比稿生成左右分栏信息图（PIL 绘制），第一版左右两栏画成了同一套机制内容，肉眼只查排版时很容易漏掉。
root_cause: ""
solution: "分栏数据用显式字段（每栏各传内容列表），不用字符串包含判断分支；渲染后 read_image 明确核对\"左栏/右栏内容是否不同\"，不只核对溢出重叠；长脚注改手动分行绘制避免数字断行。"
evidence: "实证：2026-10-30 稿件 fig185 首版左栏误画成 LFL 卡片库内容（elif 分支判断失误），独立审稿子代理判为 P1-4（\"图185 左栏应为原生记忆块机制\"），经 read_image 复核发现并重绘；fig188 脚注\"记忆条目 4153 条\"数字被拆行，改为手动两行绘制后修复。审稿回执：docs/promotion/receipts/memt-compare-issue-review-r1.json（verdict REVISE）、r2.json（verdict PASS）；修复脚本 docs/promotion/figures/_m1.py（rev2）。"
tags: [figure, PIL, read_image, review, 信息图]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-30T12:59:18.107435+08:00"
updated_at: "2026-10-30T12:59:18.107435+08:00"
---

用 PIL 画左右对比图时，不要用 `'MemT' in mid` 这类字符串包含去决定左右栏画哪套内容：一次变量重排后两个分支同时命中 else，两个栏位画出同一套机制，文字层面完全看不出错。正确做法是每个栏位传显式标志/正文列表，渲染后必须 read_image 复核内容而不只是排版；改完还要同步改文中对该图内容的描述。另外长脚注里"4153"这类数字会被按字符断行拆开，把脚注改成手动分行绘制可避免。