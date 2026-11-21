---
method_id: check-blocker-lane-ledger-before-waiting-reap-dryrun-then-escalate-5361ac591bc1
name: check-blocker-lane-ledger-before-waiting-reap-dryrun-then-escalate
description: 受闸操作（知识入库 flush、合并/发布闸、账本写等）失败且回执指名他人会话的 lane 为阻塞源、并建议『等对方终态后重试』时，不要直接进入无界等待，也不要绕闸手写。第一未知量是『对方到底还活着吗』：读该 lane 自身台账，用创建后零活动、head_sha 为空、open 多日这些当时可见事实区分『真在干活』与『永不自终的停滞 lane』。停滞 lane 先跑系统收敛工具的 dry-run；若工具因 liveness 不可证而 fail-closed 拒收，则带台账证据向属主/用户升级，同时继续主线未阻塞步骤、被闸产物保持原样待解除后重试。
aliases: 别人lane堵住入库怎么办, 等对方lane终态还是直接收敛, 停滞lane上报属主处理, 知识卡入库被闸堵死, 收敛工具拒收后找人裁决
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:d901b48e-25bf-45f0-a33f-23eaa879ddc3:177:a79d6c6ebc467d1db886
evidence_refs: learning:learn:4ba9b9984f6e
created_at: 2026-11-19T00:56:31.810336+08:00
updated_at: 2026-11-19T00:56:31.810336+08:00
---
## Trigger
受闸操作失败回执指名他人会话的 lane 为阻塞源并建议『等对方 lane 终态后重试』，需要裁决是等待、收敛还是升级，且主线尚有未阻塞的授权步骤。

## Discriminator
该 lane 台账记录里 created_at==last_activity（创建后零活动）、head_sha 为空、status=open 已逾一日以上——决策时即可见，足以把『活跃对方』与『永远等不到终态的停滞 lane』分开；收敛工具 dry-run 返回的 liveness 分类（unavailable→fail-closed 拒收）则是系统对『可否代为关闭他人 lane』的权威判据，自判『它是死的』不构成许可。

## Short path
- 读失败回执，提取被指名的 lane id 与回执自身的建议动作
- 在 lane 台账中按 id 查该记录：比对 created_at 与 last_activity、head_sha、status、属主 session
- 若停滞（创建后零活动、head 为空）：不按回执字面等待重试，先跑系统收敛工具的 dry-run（零副作用）
- 若工具 fail-closed（本环境 liveness 探测不可用）：不强行关闭、不绕闸手写，带台账证据向属主/用户发 help_request 升级
- 继续主线未被阻塞的步骤，被闸产物（如未入库知识卡）保持原样不动，待阻塞解除后原样重试

## Stop conditions
- 阻塞 lane 到达终态→按回执建议重试受闸操作
- 收敛工具给出 conclusive 分类→执行收敛后重试
- 升级已发出（含属主 id、停滞时长与台账证据）→停止调查，闸保持关闭等待属主/人工裁决

## Verification
- 未经工具自身 conclusive 分类不关闭他人 lane；强行关闭或手写绕闸都视为违例
- 最终报告如实写明：闸仍被阻塞、证据是什么、需要谁做什么裁决，不宣称已解决
- 被闸产物未被改动（数量/内容与阻塞时一致），确保解除后可直接重试

## Counterexamples
- last_activity 晚于 created_at 或 head_sha 非空→对方真在干活，按有界轮询等待重试，不 reap 也不升级
- liveness 探测可用且工具已给出 conclusive/suspect 分类→按工具分类行动，不用自己的停滞启发式替代
- 被闸操作本身就是关键路径且无并行工作可做→立即带证据升级，不穿插主线
- 阻塞者是自己会话的 lane（回执提示用 --session-id 排除）→直接修正/关闭自己的 lane，不走他人 lane 的 reap/升级路径
