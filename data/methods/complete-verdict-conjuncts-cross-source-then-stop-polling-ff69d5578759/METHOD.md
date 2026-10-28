---
method_id: complete-verdict-conjuncts-cross-source-then-stop-polling-ff69d5578759
name: complete-verdict-conjuncts-cross-source-then-stop-polling
description: 授权书要求『轮询直到 terminal』，但被轮询端点的回执已 settled（如 qualification=PASS+SHA 匹配、无 pending 标记）且 schema 冻结、只含部分验收合取项时，把验收条款当逐项账本：已给项记账，缺失项（真实终态、P0/P1 计数）到各自权威源补齐（如 start 回执里的 child_id→子代理终态查询）；账本全满即停止轮询并执行被门禁动作。不要求冻结端点自己 emit terminal 字段，也不在账本满后追加确认轮。本集 4 轮 wait+status 中第 2-4 轮属冗余：第 1 轮回执已 settled，child 查询拿到 completed/P0=P1=0 后又多等了一轮。与『route-missing-fields-to-child』互补：那条管首跳路由，本条管跨源账本闭合后的立即停止与行动。
aliases: 回执一直PASS但没有terminal字段还要继续轮吗, 验收条件凑齐了就别再轮询确认, 轮询端点不吐终态就改查子代理终态, 合取验收拆账本跨来源补齐, 账本满了直接停止等待去执行, until terminal按语义终态退出而不是等字段
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0a37a89a-ded5-4f58-8502-1934aeaf0919:0:c22361797287f8571efb
evidence_refs: learning:learn:8361f008ac75
created_at: 2026-10-24T17:48:49.823888+08:00
updated_at: 2026-10-24T17:48:49.823888+08:00
---
## Trigger
轮询循环的退出条件是语义终态（『until terminal』『直到真实 completed PASS』），验收规则是命名字段合取；某轮回执已携带该端点能给出的全部 settled 合取项、无 pending/running 标记，且与上一轮 schema 同构；缺失项对应的权威源（child_id、job exit code 等）已在手可查

## Discriminator
回执 settled 而非 pending、且连续同构 → 再轮询该端点不产生新字段；同时缺失的每条合取项都有已识别的权威来源可补（assistant 自己在第 1 轮后已明确列出缺哪些字段：completed/verified、P0/P1 计数，而 child_id 早在 start 回执中返回）。停止判据是『每条验收项都有一张权威回执背书』，而非『被轮询端点 emit terminal』

## Short path
- 按授权发起一次 start，记录 child_id 与 candidate SHA
- 首轮 wait+status 收集该端点能给的合取项（qualification=PASS、SHA 与 Host material 一致）
- 回执 settled 且缺终态/计数字段 → 不重复轮询该端点，转查 child 真实终态（completed + VERDICT + P0/P1 计数）
- 账本全满（qualification PASS ∧ SHA 一致 ∧ child 真实 completed ∧ PASS ∧ 关键计数=0）→ 立即停止轮询，按授权执行被门禁动作（一次、逐字）
- 下游后台 job 若回执含 state=running/exit=None，则按常规 wait+output 等真实终态，不属本方法分支

## Stop conditions
- 每条验收合取项均有一张权威回执背书（来源可以不同），即视为语义 terminal，停轮询并行动
- 任一合取项在所有权威源都取不到、或 child 仍在运行 → 继续有限轮询或按缺项上报，不伪造完成
- 被门禁动作已获授权且账本已满后，不再追加任何确认性轮询

## Verification
- 逐项列出验收条款↔满足它的具体回执（status 回执 / child 终态 / job exit code），确认无凭空项
- start 与被准入命令各恰好一次、逐字执行，无重复 start
- 对照 wait 累计秒数与轮次预算，确认不存在『账本满后多余一轮』

## Counterexamples
- 回执含 pending/running 标记（如后台 job state=running、exit=None）→ 终态会由该端点后续给出，应正常阻塞等待，不套用本方法提前停
- 验收契约明文规定只有该端点自身的终态回执有效、他源补齐不算数 → 只能按 missing 上报，不得拼账本后行动
- 缺失项没有可查权威源（child_id 未返回、子代理状态不可查询）→ 账本无法闭合，禁止提前执行门禁后动作
