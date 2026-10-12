---
title: browser_action 挂载即全拒（semantic_action_fields_mismatch）根因与修复：machine-authored args_normalization 需 adapter 注入
scenario: SMC browser 工具挂载（LFL_BROWSER_* env opt-in）后模型在环实测；工具 schema 与底层验证合同字段集不一致的集成缺陷
root_cause: _annotate：验证合同字段集（14 字段）与模型面工具 schema（13 字段，additionalProperties=false）不一致；machine-authored 字段的注入责任在两层都缺失，且单元测试手工构造完整字段掩盖了该缺口。
solution: 机器层字段（receipt-only、never model-owned）的注入责任放在 adapter 入口：execute() 对缺失字段注入规范默认值，保持模型面 schema 不变；malformed 仍 fail-closed。配套回归测试两条：真实链路 missing→ok；伪造 ref 下 missing 不再是 fields_mismatch（而是后续 version 前置拒绝）。
evidence: "receipt rcp_6606916f8e3fc435_0002 status=ok（click，修复后首个 dispatch）；页面状态 clicks=0→1、NoteInput value_text=gen13-verified（predicate satisfied）；大页 mid snapshot bsnap-6-1cc5ab0097cd4ec3 token_estimate=3245637 成功；4.5MB 页两次 \"CDP observation connection lost; dropped session for same-target reconnect\" 后重连成功；commit e30478643 + gen13 verify ok"
tags: [browser-smc, semantic-action, integration-defect, live-mount-test, args_normalization]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-09-18T13:03:42.747689+08:00"
updated_at: "2026-09-18T13:03:42.747689+08:00"
---

2026-09-18 用户授权把 browser_perceive/browser_action 挂到会话亲自测试。测试过程与结论：

1) 修复前症状：semantic execute / browser_action 全部 receipt status=rejected，reason=semantic_action_fields_mismatch。因单元测试全部手工构造 14 字段（含 args_normalization），测试全绿但真实工具面 100% 不可用——"测试绿 ≠ 链路可用"。

2) 根因：BrowserActionAdapter._validate 的 required 集合包含 args_normalization（machine-authored, never model-authored，_valid_args_normalization docstring 自证），而 browser_action 工具 schema 是 13 字段 + additionalProperties=false，模型永远无法提供该字段；工具层 execute() 原样透传 dict(kwargs)，无人注入。

3) 修复：adapter.execute() 入口对缺失 args_normalization 注入规范默认 {"applied": False, "rule": None}（不可变复制 {**action,...}）；malformed 值仍按 args_normalization_mismatch fail-closed。commit e30478643，gen13 发布。

4) 修复后全链路验证（runtime_generation=6）：click IncrementCounter → receipt ok + 页面 clicks=0→1；fill NoteInput → receipt ok + value_text=gen13-verified（browser_wait_object_text predicate satisfied）；大页 mid（1.13MB）snapshot 成功（token_estimate 3.2M，无 close 1009）；断连重连端到端实证：4.5MB 页 connection lost → "dropped session for same-target reconnect" → 下次调用自动重连同 target 成功。

5) 附带发现（未修，待评估）：(a) 4.5MB fixture 页超出 64MiB 默认帧上限，连续 drop；可通过 LFL_BROWSER_CDP_MAX_FRAME_BYTES 调，但更根本的是 captureSnapshot 无分页。(b) 困在超大页时 navigate 逃生通道也死：pre_dispatch_observation_failed:RuntimeError → navigate rejected，模型侧无逃生手段，只能外部 CDP 直连导航。