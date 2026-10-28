---
method_id: cross-axis-liveness-verify-before-peer-takeover-7cbabce569a8
name: cross-axis-liveness-verify-before-peer-takeover
description: 监控另一会话/agent 以决定是否接管其共享资源工作（如另一会话的 git push 序列）时，『无事件』若来自刚更换过的查询轴（按 session id / since 过滤），而此前每次目击都来自另一条轴（workspace scope / 内容词），应先怀疑观测通道漏检而非对方停滞。远程 ref 不动 + 审查子代理 completed-but-uncollected 在本地工作阶段（rebase、走 PR 修 CI）同样成立，属歧义证据而非确认证据。判停滞须两条独立查询轴一致静默且超阈值；接管首个动作用可被安全拒绝的探测。本集即因单轴负结果+歧义代理即宣告接管，靠 drift-check 才零写入挽回。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0991556a-eab1-4a63-9113-ea54a5166bf4:36:a0bfc5cdfa891798dac1
evidence_refs: learning:learn:a52eab07e283
created_at: 2026-10-22T23:59:48.199194+08:00
updated_at: 2026-10-22T23:59:48.199194+08:00
---
## Trigger
监控另一 agent/会话在共享资源上的活跃度以决定接管时机；最近一次 event/日志查询更换了过滤轴后返回空；正准备按『超 N 倍轮询周期无动作』判停滞并接管

## Discriminator
信号消失与观测通道变更同时发生：此前同窗口用 scope/内容词查询每轮都能看到对方事件，改用 session-id 过滤后即静默 → 先验证通道；且对方已有过改计划弃用已启动审查的先例（换过批次切点），uncollected ≠ 卡死，远程不动 ≠ 不在本地干活

## Short path
- 收到过滤查询的空结果后，第一个未知量是通道是否有效：用此前成功目击的轴（同 scope、同内容词）原样重查一次，而非开始构建停滞证据链
- 若宽轴仍见对方任意事件（含 rebase/PR/CI 修复等本地动作）→ 对方存活，撤销停滞假设，回到观察位
- 若两条轴一致静默且达停滞阈值（如 3 倍轮询周期）→ 判停滞；接管首个动作选可被安全拒绝的探测（如跨会话收取审查，DENIED 无副作用），再进入重执行序
- 每次接管写入前用宽轴事件 + 远程状态对账复核一次，防对方复活造成双写

## Stop conditions
- 宽轴重查发现对方在阈值窗口内有任意事件 → 停滞假设作废，回观察位并记录窄轴漏检教训
- 观察到对方终态报告或 settlement 完成 → 转入核验收尾，不再接管
- 两轴一致静默超阈值且共享资源无写入竞争 → 执行接管序，每步前置复核

## Verification
- 停滞判定的每条证据标注其来源查询轴，至少两条独立轴一致静默才可宣告
- 接管后的首个写入动作前，重跑宽轴事件查询与远程状态检查，确认对方未复活

## Counterexamples
- session id 就是文档化的唯一/权威查询轴，且此前的正目击也来自同一轴 → 其静默即有效停滞证据，无需多轴
- 对方契约上只通过远程可见操作工作（不存在本地工作阶段）→ 远程静默达阈值即可接管
- 对方正在主动破坏共享状态、需立即干预止损时，不得为验证观测通道多等一轮
