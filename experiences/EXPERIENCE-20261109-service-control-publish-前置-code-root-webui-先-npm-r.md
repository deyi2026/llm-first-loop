---
title: service_control publish 前置：code_root/webui 先 npm run build（写 dist/.lfl-webui-source.json 源绑定）
scenario: service_control(action=publish) 报 webui source binding missing or unreadable，代码已经合入 main
root_cause: ""
solution: 先在 code_root/webui 跑 npm run build（它会重建 vite dist 并写 dist/.lfl-webui-source.json，绑定 tracked webui 源指纹），再 publish；build 前确认 webui/ 无未提交改动与未跟踪输入，否则 binding 拒绝或把 WIP 打进 release。
evidence: "publish 首次失败：DeploymentBindingError: webui source binding missing or unreadable（主树 webui/dist 无 .lfl-webui-source.json）。在 code_root/webui 跑 npm run build（node scripts/build-with-source-binding.mjs）后 .lfl-webui-source.json 生成，再 publish 成功 generation=402、webui_artifact_sha256=2d85af19…。证据：evidence://v1/65f8b5307e437fe93ea67ab1da582b4cc934ddfd66de50035e7bf44c744b6d92（publish 成功回执）。"
tags: [service_control, publish, webui, deploy]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-11-09T14:48:19.654023+08:00"
updated_at: "2026-11-09T14:48:19.654023+08:00"
---