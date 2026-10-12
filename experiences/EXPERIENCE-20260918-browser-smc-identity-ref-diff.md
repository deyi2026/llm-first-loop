---
title: Browser SMC：动态文本节点 identity 不稳定，勿用旧 ref 等待；等稳定元素属性或 diff 取新节点
scenario: 用 browser_perceive/browser_semantic_execute 验证 JS 动态更新文本的效果（如状态栏 textContent 重写）
root_cause: ""
solution: 动态文本效果不要拿旧文本节点 ref 去等待；对稳定元素等属性（input→value_text），或重拍 snapshot 后用 diff 的 created 列表取新文本节点 ref 再 hydrate。
evidence: "会话内实测：click IncrementCounter 后 wait 旧 StaticText ref（el_92dd79e2fbf37a983f85）20 次采样全 indeterminate/target_not_observed；重拍快照（evidence://v1/9e03d65d4a01ff62b2dbf718861297f681f27ad1c0cabe1561606c423a4ce1d1）读到新节点 name=\"clicks=1 note=empty twin=\"；diff(bsnap-1-7ae8e804ca247269→bsnap-1-0cf92a5a677957f5) 给出 created el_a28a7dda2b803f7815fe；hydrate 该 ref 读到 \"clicks=1 note=hello-from-llm twin=B\"；input 的 wait value_text=hello-from-llm 首采样 satisfied。"
tags: [browser, smc, browser_perceive, browser_semantic_execute, identity-instability]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-18T10:59:38.712864+08:00"
updated_at: "2026-09-18T10:59:38.712864+08:00"
---

在 loopback CDP 绑定的 browser SMC 工具上：JS 用 textContent= 赋值更新状态文本时，旧文本节点被销毁重建，其 grounding_ref/el_id 失效；browser_wait_object_text 对旧 ref 返回 indeterminate/target_not_observed（不是页面错误）。稳定元素（button/input/带aria-label的容器）的 el_id 跨快照稳定。正确做法：对输入类效果等稳定元素的属性（如 input value_text）；对文本型效果先重拍 snapshot，用 diff 的 created 节点拿新 ref 再 hydrate 读 name。receipt 的 completeness.reasons 含 identity_unstable_objects 时即此情形。