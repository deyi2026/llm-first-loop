---
title: 头条编辑器：最后一张图的描述无法持久化（两篇复现，已过审仍丢失）
scenario: 今日头条 mp 编辑器（mp.toutiao.com/profile_v4/graphic/publish）。用 Input.insertText 填入 N 条图片描述（textarea.pgc-img-caption-ipt，限 50 字），发布前守门读到 captions_nonempty === N，但进入 from=edit 编辑页读回时，最后一条的 value 为空字符串。
root_cause: 平台侧对最后一个图片描述输入框的提交处理有缺陷：Input.insertText 写入后前端状态有值，但保存时该字段未随文档提交，服务器返回空串。非选区/焦点问题——同会话前 N-1 条用相同方式写入并成功持久化。
solution: |
  处置：接受该限制并在回执标 UNRESOLVED，不要反复重填（第 08 期重填+保存+过审后仍为空）。报告口径改为「N 条描述中只有 N-1 条在线」，不得声称描述齐全。
  
  规避（未验证）：填完后把焦点移回首条描述再提交；或发布前只对前 N-1 条断言 captions_nonempty，最后一条单列为已知不可持久化项。
  
  当前性验证：下次发布后，打开 https://mp.toutiao.com/profile_v4/graphic/publish?from=edit&pgc_id=<新PGC>，执行 document.querySelectorAll('textarea.pgc-img-caption-ipt') 并读每条 .value；应见最后一条为空字符串＝缺陷仍在；三条均非空＝已修复，本卡应转 invalidated。
  
  【2026-10-12 复核：缺陷仍在】第 10 期（PGC 7695739521175568939）与第 11 期（PGC 7695740310252421675）同会话再现，STATUS-20261012.md 已记为 known_gap，不再为它反复推送审核。本卡维持 active。
evidence: "第 08 期 pgc 7695403879906738703：发布前守门 captions_nonempty=3（receipts/20261011-daily08-submit.json）；22:04 from=edit 页读回 caps[2]=\"\"；22:06 用 Input.insertText 重填并复读确认三条非空后保存；22:09 列表实见「已发布 展现12」即修改已过审；22:11 重开同一编辑页 caps[2] 仍为 \"\"。第 09 期 pgc 7695406258093818408 独立复现 caps[1] 为空。同会话对照组：同页「引用AI」用 label.click() 保存后持久化成立，证明非保存链路整体失效。"
tags: [今日头条, 发布流水线, 图片描述, 持久化缺陷, 收口核对]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-11T22:03:55.313559+08:00"
updated_at: "2026-10-11T22:03:55.313559+08:00"
---