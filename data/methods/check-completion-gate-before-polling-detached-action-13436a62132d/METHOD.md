---
method_id: check-completion-gate-before-polling-detached-action-13436a62132d
name: check-completion-gate-before-polling-detached-action
description: 对已受理的 detached 控制动作（尤其目标是承载当前会话的服务，如从活跃会话内重启该会话依赖的 web）不要直接进入 status 轮询等待。先用一次读取回答唯一未知量：终态依赖什么条件？worker 源码显示它同步执行哪个脚本，脚本头注释/precheck 给出等待条件、超时与回退。若条件包含请求方自身活跃状态（如 session run-lock 空闲门、fail-closed），则本轮内终态结构性不可达——立即停止轮询，把同一官方命令移交给回合结束后执行并附验收步骤。附带规则：CAS/代数冲突报错自带 current 值时，先读权威状态（show/verify）与目标比对；若当前记录已等于目标且 verify 通过，说明操作早已完成，不重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:701:daf462e2760a6404c320
evidence_refs: learning:learn:2b1ddb7f1ed9
created_at: 2026-09-18T14:01:58.190344+00:00
updated_at: 2026-09-18T14:01:58.190344+00:00
---
## Trigger
控制面动作回执为 accepted/detached worker + '轮询 status 查终态'，且动作目标是承载或门控当前会话的基础设施；或 detached 任务首个 status 仍 running 且回执无 ETA。典型场景：从活跃会话内发起对其宿主服务的 restart。

## Discriminator
第一次 status 回执中即可见：target=web 且 requester_session_id 等于当前会话 id——被改动的对象就是请求方自己的宿主；同时 worker 进程命令行与其执行的脚本都在本地可读（ps 可见、源码在磁盘）。这两点在进入等待循环之前就把'继续盲等 vs 查契约'缩成'先读门条件'：若完成门是'请求方空闲'（run-lock），而请求方正在本回合内活跃，则该门在本回合内不可能为真，等待必然超时或 fail-closed。

## Short path
- CAS/代数冲突报错已含 current 值：先读权威状态（store show/verify）而非重试或考据源码顺序；比对当前记录的 git_head/roots/artifact 与目标，一致且 verify ok 即判定操作已完成，停止，不再执行原命令。
- 在提交（或刚受理）一个会改动'当前会话宿主服务'的 detached 动作后、进入任何 sleep/status 循环前，读执行者契约：worker 源码确认它同步运行哪个脚本，脚本头注释与 precheck 函数回答唯一未知量——终态等待什么条件、超时多久、回退是否 fail-closed。
- 定位门的真值来源（如 data/sessions/*.run.lock），并测试当前会话自身是否满足'busy'谓词：本回合的活跃 run 即是门所等待的对象。
- 若门包含请求方自身活跃状态（自指且 fail-closed）：立即停止轮询，让动作按设计失败关闭（无副作用），不在本回合内等待终态。
- 把与 worker 相同的官方命令移交给回合结束后执行（回合结束即释放 run 锁），并附具体验收：回执 rc=0、新 pid≠旧 pid、readiness 端点 200、真实 UI 路由 200。

## Stop conditions
- 权威状态（show/verify）已证明目标记录在位且与目标 HEAD/artifact 一致——停止，报告'已完成'，不重试原命令。
- 执行者契约显示完成门包含请求方自身活跃状态且 fail-closed——停止一切轮询/等待，转为回合后移交。
- 门与请求方无关且有已知有界超时——最多做一轮有界轮询，然后直接查终态记录/回执。

## Verification
- 以 store 记录 + 回执为终局证据：rc=0、detail 含新 pid 且不等于旧 pid。
- readiness 端点返回 200，且真实 UI 路由返回 200（防止'后端绿但页面 404'的假成功）。
- 确认被挡下的尝试无副作用：旧进程原封未动、无部分状态写入（对照回执与进程表）。

## Counterexamples
- detached 任务等待的是与请求方无关的外部工作（构建、数据迁移、外部健康检查）——按合理间隔有界轮询即可，预读全部执行脚本是浪费。
- 门条件不包含请求方（例如在 web 会话内重启 feishu 桥）——本轮内等待可以成功，不应过早移交给用户。
- 该类动作历史上数秒内到达终态——一两次 status 检查足够，无需契约考古。
- 首个 status 查询已返回终态——跳过所有门分析，直接验收。
