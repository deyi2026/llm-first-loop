---
title: 审稿子代理的裁决只覆盖该包的产物 SHA——改稿后旧包的 PASS 不再覆盖新产物
scenario: 审稿子代理的 PASS 常被当成「这一篇稿已审过」的通用凭据。但子代理读的是审稿包，包内主稿是快照；稿子改过之后，先前那轮 PASS 覆盖的是旧稿，新稿等于没被审过。拿旧 PASS 去申请宿主准入或直接发布，就是拿未审产物冒充已审产物。
root_cause: ""
solution: 把「包版本」当作审稿有效性的边界：任何一次正文修改都作废先前所有轮的裁决，必须重建包 + 另开新轮；宿主准入时用 status 回执里的 candidate_sha256 与当前磁盘主稿 sha256 比对，确认覆盖的是同一份产物。当前性验证：改稿后跑 `shasum -a 256 docs/promotion/<主稿>.md` 与 `python3 -I docs/promotion/_dXX_build.py` 输出的 md_sha256 对比，再重跑 `_dXX_reviewpkg.py` 并确认包字符数与主稿字数一致；若包未重建，两次 sha 不会同时对上。
evidence: "d71：第五轮审稿 PASS（p0=0 p1=0 p2=0，child subagent_6e51eff1b43d）对应审稿包 pkg chars 28,617、磁盘主稿 md_sha f0d75ab8ebcb5834…、build md_sha 与之相等；Rule28 宿主准入 status 回执 qualification=PASS、candidate_sha256=1f326448d0e4be3649884d200168ce15eff1fe989f4ab54380b71222ccefa907；准入回执 receipts/d71-admission.json 三方 SHA 一致。"
tags: [promotion, review, rule28, provenance]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-08T13:48:16.513416+08:00"
updated_at: "2026-11-08T13:48:16.513416+08:00"
supersedes: [EXPERIENCE-20261108-改稿后必须重建审稿包再开下一轮审稿-审稿子代理读的是包里的主稿全文-不是磁盘上的主稿]
---