---
title: service_control publish 不重建 webui/dist：上线前必须手动 npm run build 并核对产物标识
scenario: 修改 webui 前端源码后走 service_control(publish+restart) 上线；publish 成功但线上仍旧版本
root_cause: ""
solution: publish 前显式重建 webui 并在 dist 里 grep 关键改动标识；发现绑错产物后 release 旧 barrier 再 restart
evidence: "publish 247 回执 webui_artifact_sha256=f64a6e12…（对应旧 dist mtime 2026-10-13 02:11，grep v2-learning-view=0）；重新构建后 dist/assets/index-BAaxFy_E.js 含 v2-learning-view（4 处）；publish 248 回执 webui_artifact_sha256=05d1865b…；restart 248 被 barrier 拒绝（owner svc-f6761a69…），release 后 svc-9e3d974c… 受理成功"
tags: [service_control, publish, webui, deployment, restart, barrier]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-13T07:05:12.107164+08:00"
updated_at: "2026-10-13T07:05:12.107164+08:00"
---

service_control(publish) 只做「干净 git 树 + webui/dist 现有产物 hash 绑定」，不会触发 npm run build。若上次构建早于代码改动（如 dist mtime 02:11 vs 修复提交 06:56），publish 会照常成功并把旧 dist 绑进新 generation（247 绑了 f64a6e12 旧产物，grep v2-learning-view=0）。修复流程：cd webui && npm run build → 验证 grep 新类名/关键字 dist/assets/index-*.js → 重新 publish → restart。注意：受控 restart 的 barrier 在动作终态前被持有，同服务新 restart 会被 admission barrier conflict 拒绝；若旧动作绑定错误产物，先 service_control(release, service, expected_operation_id=旧动作id, reason) 释放本会话签发的屏障，再发新 restart。