---
method_id: prefer-completion-wake-binding-over-repeated-bounded-polls-c013e59e79af
name: prefer-completion-wake-binding-over-repeated-bounded-polls
description: 受管异步子任务（独立 Reviewer、子代理等）准入回执的 waiting_protocol 通常并列两种等待模式：有界 status 轮询与 completion-wake 事件绑定（如绑 review_terminal）。若见到 pending 只反复重发同一 status 调用，每次阻塞数十秒，会堆出 6~7 次完全相同调用并触发 repeat_guard 噪声。回执认可的更短路径：首次 status 确认 pending → 绑定 completion wake → 唤醒后一次 status 核验 qualification（唤醒事件本身不构成裁决）。轮询只作为兜底：回执未提供 wake、唤醒未触发且临近 deadline、或等待期间需穿插其他工作时。本卡与『repeat_guard 中途裁决』卡互补：前者裁决已发生的重复是否生产性，本卡从源头不进入轮询循环。
aliases: 等子代理审查结果, 结果没出来一直轮询, 轮询还是唤醒怎么选, 减少重复status查询, 异步任务完成后再核验
status: candidate
source_model: glm/glm-5.3-flash
source_episode_refs: episode:dc9cbbb4-590e-40e1-b360-158e5ef5619b:818:d085fc210e9935acbac1
evidence_refs: learning:learn:fe54cbb1fc07
created_at: 2026-11-19T19:14:52.214744+08:00
updated_at: 2026-11-19T19:14:52.214744+08:00
---
## Trigger
受管异步子任务的准入/start 回执（waiting_protocol）同时列出有界 status 轮询与 completion-wake 绑定两种等待模式，且首次 status 调用已返回非终态 pending（如 reason=review_still_running、remaining_seconds 单调递减）。

## Discriminator
首次轮询前回执中已显式在场的两条事实：『completion wake 可绑定终态事件』（事件驱动等待可用）与『pending 才继续查询或等待』（换入等待是回执许可分支）。二者共同把『剩余预算几十至几百秒怎么花』从每30秒一次调用缩成一次绑定+唤醒后一次核验，无需等终态或守卫触发才可知。

## Short path
- 按回执『先用 status 查询』带等待参数调用一次，确认 pending 并记录 child_id 与剩余预算
- 读回执 waiting_protocol：存在 completion wake 绑定选项则绑定终态事件，把剩余等待交给系统唤醒，不再原样重发 status
- 唤醒后按回执要求做一次 status 调用，核验 qualification 确为终态（唤醒事件不等于裁决）
- 按终态消费并汇报（PASS/P0/P1）后停止；若唤醒未触发且临近 deadline，才回退为有界轮询

## Stop conditions
- 唤醒后的 status 核验返回终态 qualification，核验一致即可汇报收口
- 绑定前发现回执实际未提供 wake 绑定 → 回退到回执的有界轮询模式
- 临近 deadline_seconds 仍无唤醒 → 做一次有界 status 查询取得真实状态后再决定

## Verification
- 终态裁决必须来自真实 status 回执的 qualification 字段，不得以唤醒事件或墙钟推算替代核验
- 同一 child 的 status 调用次数应降至约 1~3 次（首次+唤醒后核验+兜底），run 内 repeat_guard 不再因该轮询触发

## Counterexamples
- 回执或任务书只定义有界轮询预算（等待参数+次数上限）、未提供任何 wake 选项——此时按预算继续轮询，不得自行发明唤醒
- 等待期间存在可穿插的生产性工作且每次轮询均为有界阻塞——重发 status 并非绕远，由『守卫中途裁决』卡管辖
- estimated_seconds 逼近 deadline 或唤醒机制可靠性未知——采用混合式：绑 wake + 有界超时轮询兜底
- 准入回执本身报错或子任务启动失败（无 pending 态可言）——按失败类别处理，本卡不适用
