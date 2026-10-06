---
title: schedule wake 无法跨越 restart 的会话等待边界
scenario: 发布新部署（publish generation N + restart）后，计划用 schedule wake 在新进程起来后自动续跑验证（如 attestation/绑定回归）
root_cause: ""
solution: "不要把 schedule wake 用在\"restart 等待会话结束\"的边界之后。同会话内能完成的验证当轮做完；跨重启验证留给用户触发的下一条消息，并在交付说明里明示\"需要你回来发一句话，我接着验\"。"
evidence: "用户实测反馈（2026-10-06T00:56:34+08:00 会话）：\"已经重启，你设置的提醒没生效，没有给大模型发送唤醒消息\"；同轮以真实用户消息续跑完成 S4 验证，见 docs/S4-RESULT-20261006-live-attestation-enforce.md 唤醒链说明节。"
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-06T01:04:13.998648+08:00"
updated_at: "2026-10-06T01:04:13.998648+08:00"
---

schedule(wake=true) 是"当前真人 run 签发的一次性同会话续跑"，run 终止即失效。service_control restart 的两阶段等待会在会话结束后才执行重启，恰好跨过 wake 的存活边界 ⇒ 重启后的自动续跑不会发生。跨重启的验证链要么在本轮内完成，要么等用户下一条消息续跑，或显式告知用户需要人工触发。当前性验证：再遇"发布+重启后自动续验"计划时，先读 schedule 工具 Schema 的 wake 契约行（"仅是当前真人 run 签发的一次性同会话续跑，不可递归唤醒"）确认该约束仍在，再决定是否依赖。