---
title: 改稿后必须重跑宿主准入：准入绑定稿 sha，旧 child 自动作废
scenario: LFL 推广班在宿主准入 PASS 之后、点「确认发布」之前又改了稿（R3 措辞意见、图内术语修正）
root_cause: ""
solution: 改稿后重跑准入；回执 frozen_md_sha 必须等于当前主稿 sha，发布脚本做 fail-closed 断言
evidence: receipts/d85-admission.json（frozen_md_sha=1881a660… 与 build_md_sha/local_md_sha256 一致）；docs/promotion/STATUS-20261114.md 跨班遗留⑫
tags: [promotion, rule28, admission, publish-flow, stale-review]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-14T13:58:14.099779+08:00"
updated_at: "2026-11-14T13:58:14.099779+08:00"
---

场景：LFL 推广班的宿主准入（Rule28 发布类闸）在审稿通过后、正式发布前开启；若此后又改稿（措辞或图注），已开的准入就绑定在旧稿上。
实测（d85，2026-11-14）：第一轮准入 child `subagent_91bf9d8ccc1b` 对应当时稿 sha `93a37acc…`，R3 之后又改了 5 处措辞（正文 sha 变为 `1881a660…`），该准入随即作废；重跑第二轮 child `subagent_81ed758f44fe`（candidate `857b447e…`，material 37,839 字符）才 PASS。
解法：① 改稿后必须重跑准入，不复用旧 child；② 落盘的准入回执里 `frozen_md_sha` 必须等于当前主稿 sha（发布脚本会 fail-closed 断言）；③ 改稿时优先把措辞修完再开准入，别边审边改。本班顺序：R3 → 5 处措辞修完 → 重贴 → 重跑准入 → 确认发布。
验证：receipts/d85-admission.json（frozen_md_sha=1881a660…，与 build/主稿三方一致）；STATUS-20261114.md 跨班遗留⑫。