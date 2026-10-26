---
title: browser_perceive vision 跨不同页面返回同一 ref/sha 时判为缓存锁死，不可当当前状态证据
scenario: "需要读后台页面（今日头条号内容管理 /profile_v4/manage/graphic）确认文章审核状态时，用 browser_perceive(action=snapshot, vision=evidence) 取视觉证据。"
root_cause: ""
solution: "每次 snapshot 比对 vision 回执的 sha256 与 path：若跨不同 URL、不同 document_generation 仍返回同一 sha/path，则该截图是陈旧缓存，必须判为无效证据并弃用，不得交给 read_image 做状态判定。改走 DOM 语义层（projection_kinds 按 link/button/row/text/cell 分别试，确认 matched_total 是否为 0）或改判定通道（如数据页、详情页、公网 URL）。另：projection_kinds 过滤时 matched_total=0 只说明该 kind 无对象，不代表页面无内容，需换 kind 或看 page total。当前性验证：重跑一次 browser_perceive(action=snapshot, vision=evidence)，若 vision.sha256 与上次相同即问题复现（弃用截图通道）；若 sha256 已变化则该缺陷已消失，可恢复用截图判定。"
evidence: 三次 snapshot（document_generation 5 与 6、URL 分别为 /profile_v4/content/all 与 /profile_v4/manage/graphic?tab=all）vision 块均返回 sha256=1f81733dde36ccb65491e919a1a6b9f5c144d7e11d7e6405d12ddd25786275e1、path=data/browser_perception/vision/1f81733dde36ccb65491e919a1a6b9f5c144d7e11d7e6405d12ddd25786275e1.png，而同批 content_sha256 分别为 9ac9f1e6…/680bdc3e…/9b2b2094…，即 DOM 已变而截图未变。
tags: [browser, vision, evidence, cache, toutiao]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-20T08:35:06.292596+08:00"
updated_at: "2026-10-20T08:35:06.292596+08:00"
---