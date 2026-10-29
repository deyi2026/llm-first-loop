---
method_id: stop-waiting-when-effect-gated-on-requester-session-exit-01a460e76c78
name: stop-waiting-when-effect-gated-on-requester-session-exit
description: 受管 restart/update 类异步动作的契约若写明物理生效分两阶段、需等发起方会话退出才执行（防自重启干扰），而发起方就是当前会话，则会话内定时等待与轮询『生效回执』结构性无果。正确收尾：提交动作后至多一次 status 确认门已挂起（requester==本会话），随后只核验会话内可核验的持久面，desired generation/HEAD 回执、release 快照内容与产物绑定、tracked 树干净，并把『结束会话自动切换 vs override 立即切换』作为出口交用户裁决。本集 45 秒等待+状态轮询只证实了 schema 早已写明的 waiting_for_requester_exit。
aliases: 重启要等发起会话退出还需要等吗, 配置固化了但进程还没换怎么收尾, 别为等自己退出前的生效傻等, waiting_for_requester_exit还轮询吗, 自重启服务提交后要等多久
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:212bbc07-73ca-4b2a-af34-769842c6d47d:3195:075ca46549f5ba65a8ae
evidence_refs: learning:learn:cff6734825a2
created_at: 2026-10-29T06:47:33.532474+08:00
updated_at: 2026-10-29T06:47:33.532474+08:00
---
## Trigger
异步控制面动作（restart/update 类）调用前已读的契约/schema 明文写着：物理生效分两阶段、需等待发起方（requester）会话退出才执行；且发起方就是当前会话。

## Discriminator
调用前已读的契约文本含『等待 requester 会话结束』的两阶段设计；动作回执的 requester_session_id 等于当前会话标识。=> 本会话存活期间 succeeded 生效回执结构性不可能出现；可验证的只有持久化的期望态与产物。

## Short path
- 调用控制面前先读契约/schema，登记所有『物理生效以发起方会话退出为前提』的门。
- 门存在且发起方是本会话 → 照常提交动作，一次拿回 desired generation/git_head、产物绑定与 action_id 回执。
- 至多一次 status：确认动作处于等待 requester 退出且 requester==本会话——这就是终态事实，此后不再定时等待、不再轮询生效、不追加活进程探查。
- 核验会话内可核验的持久面：release 快照落盘、含目标修复独有符号、tracked 树干净、产物绑定与回执一致。
- 向用户精确报告『期望态已固化、进程未换』两层状态，给出结束会话自动切换 vs override 立即切换两个出口由用户裁决。

## Stop conditions
- 一次 status 显示动作在等 requester 退出且 requester==本会话 → 停止一切等待与轮询
- desired 回执与 release 快照核验完成 → 收口报告，不再新增探查
- 用户选定出口（结束会话/override）→ 执行对应动作后结束

## Verification
- 回执 desired generation/git_head 与目标一致；release 快照含修复独有符号且 tracked 树干净
- requester_session_id 与当前会话一致，确认该门确实属于本会话
- 最终报告明确区分『配置已固化』与『进程已生效』两层，不混称『已重启』

## Counterexamples
- 门条件是目标服务空闲而非 requester 退出（重启的是别的服务）→ 会话内轮询可见 succeeded，应做有限等待
- 动作由其他会话/CI 发起且该发起方已退出 → 本会话不是门，轮询可观察进展
- 同步或单阶段重启工具无两阶段设计 → 立即轮询即正确
- 用户明确要求立刻生效并接受会话中断 → 走 override 举证推进路径，而非报告等待
