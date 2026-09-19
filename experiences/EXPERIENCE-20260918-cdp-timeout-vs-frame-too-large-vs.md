---
title: CDP大页观察三层故障的判读：timeout vs frame_too_large vs 死连接，及重连语义验证法
scenario: Browser SMC Phase 1 大页(10.4MB HTML/~100k节点)观察：capture_channel_degraded 错误的分层诊断
root_cause: ""
solution: "读diag三步法：mode=timeout→观察预算不够(last_diag.resp_chars是上一条成功请求，不是失败请求)；mode=frame_too_large→帧>max_size(默认128MiB,env LFL_BROWSER_CDP_MAX_FRAME_BYTES可覆盖,hard cap 256MiB)；两者都应报dropped-session-for-same-target-reconnect并在下一次操作自动恢复(navigate/snapshot实证)。>128MiB的AX全树按设计不继续抬上限——由node_cap/object_cap投影裁剪兜底(20000/80000)。"
evidence: "receipt rcp_a1819cb98b8fd701_0002/rdc ad266a27011974aa_0002; snapshot bsnap-21-7317c3ebf15b09d6→bsnap-23-d788ca6c085cfc68; commits 5cfea26cc,086249703,e5be80a52(gen24)"
tags: [browser, cdp, 1009, huge-page, diagnostics]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T17:30:08.297942+08:00"
updated_at: "2026-09-18T17:30:08.297942+08:00"
---

_gen22复测链条：(1) DOMSnapshot 47MB帧在64MiB上限内成功收到（~1.4s），随后 Accessibility.getFullAXTree 超时（5s预算不够）——raise到20s(5cfea26cc)。(2) _gen24复测：captureSnapshot 47MB成功，AX全树帧>128MiB(086249703默认值)触发websockets max_size→close 1009→分类frame_too_large→drop session→同target重连。(3) navigate回小页+snapshot成功(bsnap-23 dom+ax complete)，证明通道自动恢复，旧1009死连接困死已修复。三个递进故障层(预算→帧上限→树规模)一次复测各暴露一层；last_diag是上一次成功请求的diagnostics，读错误时勿把resp_chars当成失败请求的大小。