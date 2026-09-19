---
title: browser_action 对象动作 target_id 用短 id 而非完整 grounding_ref；大页失败根因是帧超限非超时
scenario: SMC browser_action 挂载会话实测：对象动作（fill/click）的 target_id 格式；大页 capture 失败诊断
root_cause: ""
solution: "对象动作 target_id 用短 id（el_xxx，即 SemanticObject.id）；navigate 的 target_id 用 page scope_ref（browser-page-scope:xxx），version_scope=resource。4.5MB 级大页失败先看错误串 mode：frame_too_large=响应帧超限（设计分段采集），timeout=recv 超时（调 LFL_BROWSER_CDP_MAX_FRAME_BYTES 或查网络）。"
evidence: "本会话 evidence://v1/f937f47a60b6752512022a2a84f7645a3a5adbf335cfcdedf7146c20d127bf79（snapshot）与两次 browser_action receipt（rcp_6c12fbceba651ea6 rejected / rcp_196e8f9ab555e0cc ok）；大页错误串 capture_channel_degraded[mode=frame_too_large]; diag resp_chars=18359445"
tags: [smc-browser, browser_action, target-id, cdp-frame-limit, gen14]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T13:42:27.840570+08:00"
updated_at: "2026-09-18T13:42:27.840570+08:00"
---

gen14 实测（2026-09-18）：browser_action 的 target_id 传完整 grounding://.../object/el_xxx URL 会被拒（version_precondition_indeterminate:target_not_in_expected_version），传短 id（el_xxx）通过——因为 perception.assess_version_precondition 的 object_grounding 匹配键是短 id，而工具描述写的是 "use SemanticObject.grounding_ref"。导航回小页后 escape receipt 的 before_version 是模型手里最后可用版本（bsnap-7-8aa419b7f94fa364，即轻量 assess 的 expected==observed）。大页根因定位：4.5MB fixture 上 DOMSnapshot 响应序列化 resp_chars≈18.36M，失败模式 frame_too_large（超 64MiB 帧上限），非 5s 超时——为 EVO-a2727fb2 Phase2 分段采集设计提供了方向。