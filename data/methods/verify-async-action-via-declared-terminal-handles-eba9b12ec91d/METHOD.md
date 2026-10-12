---
method_id: verify-async-action-via-declared-terminal-handles-eba9b12ec91d
name: verify-async-action-via-declared-terminal-handles
description: 受管动作受理≠完成：验证异步后台动作（restart/publish 等）终态时，优先使用受理回执自己声明的定向句柄（按 action_id 的 status 查询、event_stream(query=service_action_terminal)），一次取得 succeeded/failed 与 live 身份段；不要先拉全局快照再顺序翻页。若回执/evidence 被截断且前部是高噪音审计数组（generation_lag 类），不要重读同一 blob 期望不同内容，改用目标键检索（服务名+live/restart_required）直接跳到目标段。declared handle 把『整快照翻找』缩成一次可验证调用；噪声截断时用键控检索代替重复读取。与 fresh-read 卡互补：那张管『何时读』（并发下的成稿时点），本张管『用哪个入口读、如何在截断噪声中定位』。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0f0a5645-b407-4183-bd45-9c5d82003d93:46:c8c1509b9fb956357435
evidence_refs: learning:learn:463771d0a0ee
created_at: 2026-10-10T01:17:39.958629+08:00
updated_at: 2026-10-10T01:17:39.958629+08:00
---
## Trigger
已对受管服务/后台 mutation 拿到『受理≠完成』的受理回执，需要确认终态；或工具回执/evidence blob 已知被截断、前部为高容量审计数组而目标段（live 身份/终态）在后部。

## Discriminator
受理回执文本本身已显式声明终态核对入口与本次 action_id（action=status 按 action_id 查询、event_stream(query=service_action_terminal)），且首个 status 快照已暴露其布局：前部是 barriers+generation_lag 长数组、截断发生在 per-service live 段之前。这两点在决定下一步动作之前就已可见，足以把候选空间从『翻找整个快照』缩成一次定向句柄调用或一次键控检索。

## Short path
- 提交受管动作后，从受理回执抄下 action_id 与其声明的终态核对入口；未知量=该动作 succeeded/failed
- 直接用 action 作用域查询（status 按 action_id，或 event_stream query=service_action_terminal）取终态，不先做全局快照翻页
- 终态=succeeded 后核对 live 身份段（pid_alive、restart_required=false / matches_desired_generation）即宣布完成；failed 则走 verify_acknowledge 显式闭合
- 若快照被截断且已知前部为审计噪声，不重读同一 evidence ref/range：用目标键（服务名+live/restart_required）做 search_evidence 直接命中目标段

## Stop conditions
- 已从终态句柄读到 status=succeeded/failed，且 live 身份字段与 desired generation 一致（或 failed 已显式闭合）
- 不为『再多确认一遍』对同一 evidence ref 以同参数重复读取

## Verification
- 终态声明必须来自终态核对句柄返回的 status 字段，而非受理回执本身
- live 身份字段（pid_alive / restart_required=false / matches_desired_generation）与 desired 对齐后才收口
- 本次验证路径中对同一 evidence ref 无重复同参读取（duplicate-read 检查）

## Counterexamples
- 回执本身已是同步终态（status=succeeded），无需任何后续核对
- status 响应小而完整、直接含终态与 live 段，顺序读一次即可，检索是多余调用
- 任务本身就是要审计 generation_lag 等历史信号，该数组是目标内容而非噪声，不适用本方法
- 回执未声明任何定向句柄且快照完整未截断时，直接顺序阅读即可，本方法无增益
