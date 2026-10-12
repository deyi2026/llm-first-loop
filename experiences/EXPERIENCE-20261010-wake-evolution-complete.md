---
title: wake 分叉会话不能代归属会话执行 evolution_complete 登记
scenario: "wake 分叉会话执行先前真人授权的\"全量回归验证+evolution_complete 登记\"委派：验证完成且通过，但登记动作被跨会话归属边界拒绝。"
root_cause: ""
solution: 验证与登记解耦：分叉会话完成验证并落盘结构化证据（junitxml+完整日志），收口报告如实说明登记被拒原因与剩余一步；由归属会话或用户完成 evolution_complete。勿绕过归属边界。
evidence: evolution_complete 拒绝回执（本 run）：「建议 EVO-20261010-1e06d6b4 归属会话 '9f3f9ab8-30d9-4a2d-9f58-148054503778'，当前会话 'c7c423f8-5e37-404b-a6b3-9631910a54d7'，不可代为登记完成」；method_manage record_use 两次回执「当前 Episode provenance 不可用」；验证证据：/tmp/evo_full_junit.xml（7383 passed/0 failed）、/tmp/evo_full_pytest_venv.log、/tmp/evo_full_pytest.log（误环境 274 failed/27 errors）
tags: []
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-10-10T20:44:52.227990+08:00"
updated_at: "2026-10-10T20:44:52.227990+08:00"
---

定时续跑（wake）分叉出的新会话 c7c423f8 执行"验证通过后 evolution_complete 登记"时被确定性拒绝：建议 EVO-20261010-1e06d6b4 归属原会话 9f3f9ab8，跨会话不可代登记（工具回执引用 spec §5.8.1-1d / §6.5-2）。同会话 method_manage record_use 也因"Episode provenance 不可用"失败，说明分叉会话缺少归属/provenance 上下文是系统性约束，非重试可解。正确做法：委派消息把"登记"与"验证"分开——分叉会话只做验证并留完整可引用回执，登记留给归属会话续跑时执行或由用户触发。另：后台回归必须绑定正确解释器（项目 .venv 而非裸 python3），避免 tail -15 截断失败清单；本次裸 python3 误跑产生 274 failed+27 errors 的环境性假阴性。