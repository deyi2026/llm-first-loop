---
method_id: freeze-workdir-writes-during-one-shot-admission-window-e883241b10ca
name: freeze-workdir-writes-during-one-shot-admission-window
description: 一次性准入资格（review_admission 类）按 workdir+冻结材料签发后、被闸动作执行前存在等待窗口：若会话运行时的写入汇（task_state 账本/progress.json、日志、回执）物理落盘在该 workdir 内，任何一次写入都会改变切片外 untracked/tracked 内容摘要，使用时 revalidated_on_use 复检失败、资格作废。规则：签发后到消费完成为止把整个 workdir 当冻结区——repeat_guard 的『先记账』提示可推迟或改写到绑定集之外；等待窗口内只做只读轮询；被闸动作完成或链路按政策停止后才恢复写入。本集即在轮询中保存 task_state 更新了 .scratch/progress.json，PASS 资格在门禁使用时因越界漂移被阻断，整链被迫停止。
aliases: 等审查结果时工作树哪些文件不能写, 资格签发后还能往仓库里落盘吗, 门禁说切片外改动变了怎么回事, 轮询时保存进度会不会毁掉PASS, 复审通过但执行被拦怎么排查
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:cf6ab009-4624-446f-b19d-ba420c380bd8:0:e5b1f47a85697a0a227e
evidence_refs: learning:learn:f623549fe5a1
created_at: 2026-11-12T08:32:49.527485+08:00
updated_at: 2026-11-12T08:32:49.527485+08:00
---
## Trigger
有状态的一次性准入资格已绑定 workdir 与冻结材料摘要签发（如 review_admission kind=full_test scope=patch），被闸动作需在同一会话轮询等待后才执行，且会话运行时写入汇（task_state/progress/日志/回执文件）物理落在该 workdir 内

## Discriminator
资格回执含『一次性』+『冻结/内容摘要绑定』语义：start 回执已标 one-shot 与 workdir/target 绑定，终态回执进一步显示 revalidated_on_use 覆盖切片外 tracked+untracked 摘要。该事实把『等待期可正常记账』缩成『签发→使用窗口内 workdir 必须零写入，账本推迟或外移』。即便绑定细则迟到终态回执，one-shot+冻结语义在签发时已可见，足以支持保守冻结。

## Short path
- 签发回执时提取绑定语义：资格是否一次性？绑定了哪些 digest？切片外内容是否在使用时复检？
- 枚举本会话会落进该 workdir 的所有写入汇（task_state 账本、progress.json、运行日志、回执文件），全部标记为冻结窗口内禁写
- 等待窗口内只做只读轮询；遇 repeat_guard『先记账本』提示时，以推迟记账回应或写到绑定集之外，绝不向 workdir 落盘
- 真实终态满足前置条件后，立即执行被闸动作（此间仍零写入），保留原始退出码与日志
- 被闸动作执行完成或按用户政策停链后，才恢复记账并把回执写到允许位置，最后复核被审面 digest 与签发时一致

## Stop conditions
- 被闸动作已执行（或链路按政策停止）→ 解除冻结，恢复常规记账与回执写入
- 资格契约明确不绑定切片外内容（无 revalidated_on_use 类复检）→ 只需冻结声明路径，其余写入无害

## Verification
- 消费资格前用只读 git status/digest 核对：签发时绑定的切片外 tracked/untracked 摘要当前仍一致（本集判据：untracked=3 的 .scratch 文件 mtime 与内容未变）
- 门禁/被闸动作完成后复核被审面（staged patch SHA256、HEAD）与签发时完全一致，证明冻结未污染候选本身

## Counterexamples
- 资格契约只 digest 声明路径、明确不复检切片外 untracked → .scratch 记账无害，全面冻结只是浪费等待窗口
- 会话写入汇在 workdir 之外（独立 state 存储或 /tmp）→ 等待期记账自由，无需推迟
- 被闸动作自身必须向 workdir 写报告/产物——那是消费时及之后的行为，不属于签发→使用窗口的禁写范围
