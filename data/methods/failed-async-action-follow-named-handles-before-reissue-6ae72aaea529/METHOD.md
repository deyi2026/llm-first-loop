---
method_id: failed-async-action-follow-named-handles-before-reissue-6ae72aaea529
name: failed-async-action-follow-named-handles-before-reissue
description: 后台/两阶段异步动作（restart、deploy 等）终态 failed 后，其回执通常已点名失败原因的存放处：reason_ref 句柄、range.complete=false+next_start 分页指针、可按完整 action_id 寻址的 per-action 日志与 admission 台账。先沿这些命名指针读权威失败详情，再按 operation_id 查挂起屏障是否正在拒绝新任务（可用性伤害），裁决后才重发/override/release；若阻塞 run 锁含 requester 自身会话，等待型重发必然复现超时。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:667:4f1e9b1d58be045bc4d4
evidence_refs: learning:learn:0d4071bb8e38
created_at: 2026-10-14T08:01:08.850314+08:00
updated_at: 2026-10-14T08:01:08.850314+08:00
---
## Trigger
异步/两阶段后台动作（如 service restart）终态为 failed 或超时，且回执含 reason_ref、range.complete=false/next_start、完整 action_id 等命名句柄；或正准备重发同类动作、或用户报告相关服务不可用之时。

## Discriminator
回执本身已点名失败原因的落点：reason:xxx 句柄、分页指针 next_start（内容截断≠内容缺失）、按 action_id 可精确寻址的 per-action 日志目录与 admission/ledger jsonl；以及『idle 门等目标空闲、但活跃 run 锁中包含 requester 自身会话』这一结构性自锁事实——它们当时就能把『到处搜索失败原因』缩成两三个可验证下一跳。

## Short path
- 从 failed 回执一次性抽取命名句柄（reason_ref、完整 action_id、range.next_start），不先做换词关键词搜索
- 解析 reason 句柄或对同一权威 blob 按 next_start 翻页，读出失败详情（如 target still busy after 900s: active run locks: 1）与失败阶段
- 按 action_id 精确路径查 per-action 日志目录：文件缺失⇔死在等待/gate 阶段而非执行脚本阶段（避免全树 grep 超时）
- 按 operation_id grep admission/台账文件：挂起屏障是否此刻仍在拒绝新任务，量化可用性伤害与阻塞者名单
- 裁决后行动：命名阻塞（活跃 run 锁、requester 自锁）未解除前不重发等待型动作；选择 release/等待/override，并用回执点名的终态入口（status/event_stream）验证

## Stop conditions
- 权威台账已给出失败阶段与阻塞者身份，且当前 admission 屏障状态与目标服务可用性（端点响应）均已实测验证
- 在命名阻塞解除或显式裁决放弃之前，不重发同类等待型动作
- 重发/释放后已查到异步终态或实测无屏障，才宣布恢复，不以『已受理』当『已完成』

## Verification
- 失败阶段与 per-action 日志存在性互证（等待期失败⇔无执行日志文件）
- release 或重发后重查 status：admission_barriers=[] 且目标服务端点正常响应
- 新受理回执的终态仍需经其点名的异步查询入口核对后才能下结论

## Counterexamples
- 回执 complete=true 且失败原因已在可见窗口内：直接分析并停止，无需翻页或检索
- reason_ref 无可解析台账、也无 per-action 工件：换词 evidence/关键词搜索是正当回退，本方法不适用
- 失败瞬态且动作幂等无副作用（如一次读超时）：先低成本重发再深挖 RCA 可接受，不必先解全部命名句柄
- 失败动作不留任何挂起 gate/屏障、不拦截新任务：跳过可用性伤害与阻塞者排查步骤
