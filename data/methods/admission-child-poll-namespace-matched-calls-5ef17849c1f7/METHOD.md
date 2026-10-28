---
method_id: admission-child-poll-namespace-matched-calls-5ef17849c1f7
name: admission-child-poll-namespace-matched-calls
description: 保持父 Run 活跃、轮询准入型审查子代理终态时，wait 类工具的 job_id 只绑定 execute_command 后台任务命名空间，不接受 admission 返回的 child_id；把 child_id 传给 wait 必得『任务不存在或无权访问』。任务书通常已给出精确调用形状：wait 只传 seconds（墙钟配速），status 只传 child_id（状态查询）。按字面执行，不合成 wait(job_id=child_id) 这类混合调用；遭一次命名空间型拒绝后立即切换为墙钟配速+status 轮询，不重试同形状。
aliases: 怎么等review子代理跑完, wait报子代理不存在, 父Run保活轮询子代理终态, 轮询admission子代理状态, wait不认child_id, 审查回执轮询等待怎么写
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:71c09986-f338-4af6-b1ef-f33868c39032:0:e5a381b3943e62fc51be
evidence_refs: learning:learn:d5b416d50056
created_at: 2026-10-26T07:04:33.282322+08:00
updated_at: 2026-10-26T07:04:33.282322+08:00
---
## Trigger
任务书要求保持父 Run 活跃、轮询准入门子代理（review_admission/admission 类 child）直到真实 terminal，且已写明分工具调用形状（wait seconds + status child_id）

## Discriminator
任务书已显式配对参数：wait 只收 seconds、status 只收 child_id；且 wait 的 job_id 命名空间不含 admission 子代理——一个 admission 刚返回的有效 ID 被 wait 报『任务不存在或无权访问』，是命名空间拒绝，而非 ID 无效或瞬时故障

## Short path
- admission(start) 仅一次，同层核对 candidate_sha256 与预计算值逐字节一致，记录 child_id
- 严格按任务书面面形状用 wait(seconds<=120) 做墙钟配速保持父 Run 活跃，不把 child_id 传入 wait
- 用 status(child_id) 查 child_state/qualification，再次核对同层 SHA
- 非终态则继续有界时钟循环；终态则回读完整报告（completed/VERDICT/P0/P1/P2），accepted 只算受理不算 PASS
- 终态+裁决回读完毕即停止

## Stop conditions
- child_state=completed 且 VERDICT/P0/P1/P2/qualification 全部回读、三方 SHA 逐字节一致
- 遇到 REVISE/阻断/终止信号立即停止并报告
- wait 遭命名空间型拒绝后不再尝试任何携带 child_id 的 wait 形状

## Verification
- start 回执、status 回执、子代理报告三处 SHA 逐字节一致
- qualification 来自真实 terminal 之后的回执，而非 accepted=true 误读

## Counterexamples
- 当前环境 wait 工具文档/回执明确声明接受子代理 ID，或任务书直接指示 wait(job_id=child_id)：传 ID 才是正确形状，本方法不适用
- wait 失败是瞬时超时/无响应而非『ID 不在该命名空间』：同形状重试可能正确，不应换形状
- 任务书完全未给调用形状且无工具命名空间信息：一次探针失败是学习命名空间的合理成本，属正常路径而非绕远
