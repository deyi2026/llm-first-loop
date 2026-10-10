---
title: macOS 排查端口占用：lsof 查询建议加 -nP 加快输出（交接转述，未亲验）
scenario: "在 macOS 上排查端口占用/进程网络连接（如 lsof -i :PORT 或 lsof -iTCP -sTCP:LISTEN），当 DNS 解析慢或不可达时，默认 lsof 输出会因反解析与端口名转换长时间卡顿。"
root_cause: ""
solution: "lsof 查询加 -nP：跳过 DNS 反解析与端口名转换，显著加快输出；验证动作：`time lsof -i :<PORT>` vs `time lsof -nP -i :<PORT>` 对比耗时应显著下降，且 `lsof -nP -iTCP -sTCP:LISTEN` 仍应正常列出监听行。"
evidence: ""
tags: [macos, lsof, 端口占用, 性能, unverified, handoff-relay]
source:
  attempt_note: 写前按 method 卡 preclassify-record-kind-and-embed-currency-check 判定为 lesson+unverified，未用写失败当探针；查重已发现既有重复记录，本条为显式委派写入并已互链标注
  channel: 父代理委派任务（非真人新授权）
  duplicate_of: "experience:EXPERIENCE-20261010-macos-lsof-np-dns"
  original_context: 上一会话 macOS 端口占用排查后的交接转述；本回合未亲自运行该命令
  type: handoff_relay
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-10-10T00:59:05.446251+08:00"
updated_at: "2026-10-10T00:59:05.446251+08:00"
---

结论：在 macOS 上排查端口占用时，lsof 查询建议加 -nP 参数：-n 跳过 DNS 反解析、-P 跳过端口名到服务名的转换，二者可显著加快输出（DNS 慢或不可达时默认输出会长时间卡顿才逐行吐出）。

出处与验证态说明：本条来自本次任务上下文的交接转述（上一会话 macOS 端口占用排查的结论），本回合未亲自运行该命令，无直接回执证据，故为 lesson + unverified。

当前性验证动作（可执行）：在同一端口上对比 `time lsof -i :<PORT>` 与 `time lsof -nP -i :<PORT>`：后者应明显更快完成输出；且 `lsof -nP -iTCP -sTCP:LISTEN` 应仍能正常列出监听进程（输出含 LISTEN 行），即 -nP 未改变查询语义、只影响名称解析。

查重备注：记录库已存在内容一致的 active lesson（experience:EXPERIENCE-20261010-macos-lsof-np-dns，2026-10-10T00:35 写入）；本条为父代理显式委派写入，检索时已发现该重复，后续检索/去重请优先沿用既有记录。