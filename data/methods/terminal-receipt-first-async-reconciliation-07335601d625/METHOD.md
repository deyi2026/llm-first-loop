---
method_id: terminal-receipt-first-async-reconciliation-07335601d625
name: terminal-receipt-first-async-reconciliation
description: 先前发出的异步/两阶段动作，其预期效果未在权威状态出现时，第一未知量应是『该动作如何终止』：直接取该 action_id 的持久化终态回执（成功/失败+失败明细），由明细指出真正缺失的前置步骤（如 desired-state 未 publish、restart≠deploy），再决定补哪一步。不要把『已受理』回执推断为『进行中』，不要先全仓宽搜实现代码，也不要未读失败原因就盲目重发。判据：权威 status 显示 live 与期望不符、无 pending/in-flight、stable 停在更早成功动作——三者并存即证明先前动作已在别处终止，终止原因只在终态回执里。此路径用一条 action_id 因果边把『可能的各种原因』缩成一个可验证下一跳。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:855926d8-3b7a-4a6d-9c5e-34631b59df2b:912:b37bdbfa6f20c43d0b2c
evidence_refs: learning:learn:394d5f525dc0
created_at: 2026-09-19T11:07:32.956876+00:00
updated_at: 2026-09-19T11:07:32.956876+00:00
---
## Trigger
用户或上文引用了先前异步/两阶段动作的 action_id，而权威 status 接口显示其预期效果缺失（generation/HEAD/PID 未变）

## Discriminator
权威状态同时呈现三个可观察事实：live 与期望不一致；无 pending/in-flight 记录且 restart_required=false；stable 记录停在更早的成功动作上——并存即证明先前动作已终止而非排队中，其终止原因只存在于该动作的持久化终态回执，而不在受理事件或实现源码里

## Short path
- 调权威 status，确认预期效果缺失且系统静默（无 pending），把未知量收窄为『先前动作如何终止』
- 按已知 action_id 取持久化终态回执（动作回执存储目录，或事件流按 id 过滤到 terminal 事件），读取 status 与 failure detail
- 用失败明细定位真正缺的前置：如 deployment binding 校验 desired vs actual HEAD 不匹配 ⇒ 缺的是上游 publish/发布记录，而非重发执行动作
- 确认缺失步骤的权限边界（若属 operator 控制面且被 fence，则给出已预验前置条件的精确命令交用户执行）
- 前置补齐后再重发执行动作，下一轮用同一 status 字段验收新 stable 记录与 generation/HEAD

## Stop conditions
- 终态回执已解释效果缺失原因，且缺失步骤及其权限归属已明确，已向用户给出可执行的下一步
- 回执显示已成功但权威状态仍不符 ⇒ 转入多源一致性核验分支，不再通过翻实现源码寻找答案

## Verification
- 回执中的 desired/actual 字段与当前权威 status、仓库真实 HEAD 三方能对上
- 补齐前置并重发后，status 出现新的 stable 成功记录，且 generation/HEAD 达到用户预期值

## Counterexamples
- status 显示动作仍处于 pending 或持有 lease ⇒ 应按两阶段等待语义处理（等待 requester 退出/idle），尚无终态回执可读
- 动作系统只写事件流不落盘回执 ⇒ 事件流即终态来源，方法退化为按 action_id 过滤 terminal 事件
- 效果缺失的原因是动作从未被发出（无 action_id 可引用）⇒ 根因在发起侧，无回执可对账
- 同步调用且成功响应本身即权威结果 ⇒ 不存在需要对账的异步间隙，直接进入验收
