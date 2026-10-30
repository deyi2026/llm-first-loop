---
method_id: async-receipt-action-id-status-before-event-stream-sweep-51ec9758cb76
name: async-receipt-action-id-status-before-event-stream-sweep
description: 异步后台动作（restart/publish 类）的受理回执自带唯一 action_id 并明示终态核对入口 status(action_id=…) 时，核对终态就逐单走这条键控查询：本集先发了无信息 echo 占位、再用 event_stream 关键词检索，命中的是历史会话的同款检索记录而非本次终态，最后一条键控 status 一次拿到 succeeded+verify_verdict。事件流只在无 id 或需跨单聚合时用。
aliases: 重启受理了怎么确认完成, 异步重启核对 succeeded, 事件流查到的是历史记录不是本次终态, 受理不等于完成怎么核实, 后台动作终态核对
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:e827e946-e151-4ded-9bdf-58c042570992:154:d91a45a3da5e5e778d54
evidence_refs: learning:learn:9f1479c34019
created_at: 2026-10-30T16:36:22.658964+08:00
updated_at: 2026-10-30T16:36:22.658964+08:00
---
## Trigger
已受理的异步变更动作需要核对终态（受理≠完成），且受理回执中已给出唯一 action_id 与明示的键控核对入口

## Discriminator
受理回执本身是否已含唯一 action_id 并点名『终态核对入口：status(action_id=…)』；本集更早的全量 status 回执也已按 operation_id 键控返回事实——键控通道已被证明可行，而事件流关键词查询会匹配到历史会话的同款 action_trace 记录

## Short path
- 受理时即记录每单 action_id 与回执明示的核对入口
- 有界等待后逐单调用 status(action_id=…)，只读该单的 status 与 verify_verdict
- succeeded/confirmed_ok 即闭合该单；waiting_for_requester_exit 类设计性挂起则交接 action_id 与同一查法，不阻塞等待、不发占位 shell 命令
- 仅当无 action_id 或未知量是跨单聚合（如找所有待确认 failed）时才退到 event_stream/全量 status 宽检索

## Stop conditions
- 每个 action_id 均查到显式终态（succeeded/failed），failed 单已进入确认流程
- 挂起单的等待原因是设计性行为（如等本会话结束），且 action_id 与核对方式已交接给用户或后续会话

## Verification
- status 回执中的 action_id、deployment_generation/git_head 与 publish 回执一致，且 verify_verdict=confirmed_ok
- 最终陈述中没有任何一单把『已受理』表述为『已完成』

## Counterexamples
- 未知量是跨单聚合（『有哪些 failed 待确认』『全部服务当前进度』）时，宽 status/event_stream 扫描才是正确工具，单键查询回答不了
- 动作无 action_id（fire-and-forget）或键控接口不可用时，事件流/日志检索是唯一途径
- 契约明示事件流为唯一核对通道时，按契约走事件流而非键控查询
