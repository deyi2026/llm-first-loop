---
title: 同一工作区可能有并行执行者在处理同一篇号：收口前必须核对文件归属，且不得覆盖他人回执
scenario: 推广班发布后，同一工作区出现并行执行者对同一篇号继续改稿并重写 STATUS/回执
root_cause: ""
solution: 收口前先核对文件归属（mtime + 回执内容）；只追加不覆盖他人成果；用两份准入回执分别对照首发版与改稿版 sha；独立只读复验公网现状且不写他人回执；自己的缺陷据实归因并修复留证。
evidence: "本班实测：docs/promotion/receipts/d94-toutiao-local.json（14:15 首发，phase submitted）、receipts/d94-poll-final.json（14:25:14 已发布）、receipts/d94-edit-local.json（06:58:59Z 改稿提交，md_sha 3346935a…）、receipts/d94-edit-admission.json（改稿准入 PASS，frozen_md_sha 3346935a…）、receipts/20261117-daily94-public-verified.json（15:00:14 公网复核）、STATUS-20261117-daily94.md 与 STATUS-20261117.md（mtime 15:08 由他人改写）；本班执行者独立只读复验读数：全文 15,575 字符、4 图尺寸 1000x962/1000x943/1000x929/1000x1016 逐张一致、4 条图注全命中、20/20 探针命中。"
tags: [推广, 并发, 收口, STATUS, 回执, 改稿, 归属]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-17T15:39:24.727213+08:00"
updated_at: "2026-11-17T15:39:24.727213+08:00"
---

场景：定时推广班执行中，同一工作区（docs/promotion/）出现另一并行执行者在处理**同一篇号**：本班 14:15 提交、14:25:14 转已发布后，另一执行者在 14:26 之后继续修改正文 md（sha 由 9898dc25… 变为 3346935a…）、走头条编辑页整篇重贴改稿（14:58:59 提交）、补跑机检与公网 cache-bust 复核（15:00:14），并在 15:08 重写了 STATUS-20261117-daily94.md 与当日总账。现象：自己刚写的回执/台账/STATUS 会被他人覆盖，且「在架版本」与「我发布的版本」是两个 sha。处置：①不覆盖他人成果——先看文件 mtime 与回执内容，识别归属；②自己的 STATUS 只**追加**带执行归属的小节，不重写他人段落；③跨班引用时用两份准入回执分别对照（首发资格 vs 改稿资格）；④独立只读复验公网现状，不写他人回执文件；⑤发现的缺陷（如派生脚本漏替换输出文件名里的篇号导致覆盖他人回执）据实归因到自己动作，并修复 + 在 STATUS 留证。教训：收口前必须核对「谁写的这批文件」，否则会把并行执行者的成果当成自己的或反向覆盖；发布后若他人改稿，在架 sha 与自己冻结 sha 不一致是正常且必须登记的事实。