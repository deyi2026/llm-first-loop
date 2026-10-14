---
method_id: single-failed-action-receipt-collapses-stuck-diagnosis-ce50e24d4f59
name: single-failed-action-receipt-collapses-stuck-diagnosis
description: 用户在无先前上下文的会话报告"卡住/没变化"类症状时：第一份 pending/failed 状态回执若已把症状映射到唯一失败动作，且 detail 给出明确因果（如 target 因活跃锁等待超时）与 superseded 接管标志，则剩余未知量只有一个——该命名 target 的当前权威状态。直接读该 target 的权威 runtime 记录（manifest/进程/版本）并做一次存活探针，跳过 evidence 库、事件流、浏览器页等宽枚举；若用户可见界面仍"没变化"，再查并发写入者（其他会话未发布改动）解释表面滞后，并用回执中 busy-lock 信号预警再次操作会排队。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:be01f045-dc21-4178-9495-77183219b9f2:1:cdefcdd31ef8046dbaf4
evidence_refs: learning:learn:ce865a26c152
created_at: 2026-10-13T21:20:30.187362+08:00
updated_at: 2026-10-13T21:20:30.187362+08:00
---
## Trigger
用户（尤其新会话、无上下文）报告"卡住不动/没有变化"类症状需要诊断，且已取得一份 pending/failed 动作状态回执

## Discriminator
回执是否同时满足三点：(1) 仅一个 failed/blocked 动作；(2) 其 detail 已含能解释症状的直接因果（等待类超时、锁占用）并命名具体 target；(3) 带 superseded/takeover 标志且无其他 pending/异常。满足即把"哪里卡了"从全空间缩为"该 target 现在是否健康"这一个未知量

## Short path
- 查 pending/failed 动作状态，定位唯一失败动作、其因果（等锁超时）与接管标志；未知量：卡住的是什么？
- 沿回执命名的 target 直读其权威 runtime 记录（manifest/进程/版本，对比 desired）；未知量：接管后是否已健康运行？
- 对该 target 做一次存活探针（端口/health）；未知量：是否实际在服务而非僵尸存活？
- 若用户可见界面仍"没变化"，查并发写入者（workspace 事件流）确认未发布改动可解释表面滞后；无法解释则直接向用户提一个澄清问题
- 输出带时间戳的因果链 + 澄清问题 + busy-lock 再排队预警，停止

## Stop conditions
- 权威 runtime 记录与存活探针均已确认 target 健康、版本匹配 desired
- "没变化"已被未发布并发改动解释，或已向用户提出具体澄清问题

## Verification
- 最终断言中的 pid/版本/时间戳来自刚读的权威 manifest 与探针，而非状态回执快照或记忆
- 因果链每一环（等待超时→superseded→新代成功→当前健康）都有带时间戳的回执/记录支撑

## Counterexamples
- 回执中 pending/failed 为空：症状尚未映射到任何具体动作，需要先做日志/事件流层面的宽发现，本方法不适用
- 用户的"卡住"指浏览器页面交互本身（页面无响应/渲染不动）：browser/page 检查才是正确下一跳，跳过它反而错
- 失败动作未被 superseded 且无新代接管：剩余未知量是"是否 override/acknowledge 以解除阻塞"的决策，而非验证当前状态
