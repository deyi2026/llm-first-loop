---
title: Browser SMC 语义执行实测：duplicate_action_id 防重放、identity-unstable 文本对象与 re-observe 闭环
scenario: 对语义操作工具（Observe→Ground→Execute→Receipt→Re-observe）做模型在环实弹测试时，遇到三类容易误判的现象：动作被拒、文本谓词 indeterminate、re-observe 后旧 ref 失效。
root_cause: ""
solution: "把三类现象归类为协议语义而非故障：(a) duplicate_action_id 是 (target_ref,verb,args) 内容哈希的防重放护栏——重新 snapshot 取新 ref 再派发，不要等待也不要换工具；(b) 段落对象不投影 value_text，且文本变更会删除旧 StaticText 对象并创建新对象（identity_unstable_objects）——验证文本要走当前快照的新对象（hydrate 读 name）或 diff created 列表；(c) 每步 mutation 后以 diff/wait 谓词再观察闭环，receipt ok ≠ 完成。navigate 用 resource_ref，对象动作用 grounding_ref；page-scope 跨文档稳定，可作 URL 谓词锚点。"
evidence: "receipts rcp_d99236de0898544b(rejected duplicate_action_id), rcp_61a618208339d677(re-dispatch ok); hydrate \"clicks=2 note=hello from llm-first-loop twin=B\" (content_sha256 708ba273…); diff bsnap-2-ababe9dc→ade9bed3 & e8e62572→60e99951; snapshot bsnap-2-14e9e9315aa40ef6 (document_generation 2, NextPage); docs/browser-smc-mount-20260918.md"
tags: [browser-smc, semantic-operation, idempotency, action-id-dedupe, model-in-loop-test]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T11:19:29.876141+08:00"
updated_at: "2026-09-18T11:19:29.876141+08:00"
---

在 LFL web 会话中用 browser_perceive + browser_semantic_execute 实操（2026-09-18，loopback fixture + Chrome headless CDP）：
1) 动作幂等护栏：action_id 由 (grounding_ref, verb, args) 内容哈希派生。同一 grounding_ref 重复 click → receipt status=rejected, reason=duplicate_action_id，动作未派发。解除方式不是等待（rejection≠not-ready），而是 browser_perceive 重拍快照取新 ref（action_id 含快照谱系 → 新 id）再 dispatch，即刻成功。
2) 文本对象不稳定：段落 <p> 不投影 value_text（wait 返回 property_unobserved，indeterminate）；textContent 变更 = 旧 StaticText 对象 removed + 新对象 created（diff 可见）。对旧文本对象 wait 会 target_not_observed。验证文本要看当前快照里新创建的对象（hydrate 读 name），不要复用旧 ref。
3) receipt ok 只是机械事实：每次 mutation 后用 diff(from=before_version,to=after_version) 或 wait 谓词再观察才算闭环；跨页动作（link click / navigate）以 document_generation 变化 + scope_url 谓词确认。
4) 对象动作 target 用 SemanticObject.grounding_ref（版本内嵌），navigate 用快照 resource_ref；page-scope 跨文档导航保持稳定，可作 URL 谓词锚点。