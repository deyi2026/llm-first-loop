---
title: "service_control stage_facts 的 per-service succeeded 是\"最近动作终态\"而非\"当前代动作结果\""
scenario: "读 service_control status 判断某服务是否已随某 generation 重启时，stage_facts 里各服务 status=succeeded 容易被误读为\"本次 generation 的三面结果\"。实际该字段只反映服务最近一次 action 的终态，可能是多个 generation 之前的旧动作。本例：feishu 在 gen 103 publish 中被完全跳过（无任何 action 下发），但 stage_facts 仍显示 succeeded（那是 gen 98 动作的旧终态），导致上一轮误判\"三面 gen 103 全 succeeded\"。"
root_cause: ""
solution: "不要用 stage_facts 的 succeeded 断言某服务已随当前 generation 重启。断言\"服务已在代 N 落定\"必须核对 stable.generation==N（feishu 当时停在 98 即是反证）；对 action 时间归属存疑时用 event_stream(scope=workspace, query=<action_id>) 查该 action 的真实发生时间。附带事实：本例告警的根因不是验证层 pgrep 失明，而是 publish 的目标选择逻辑漏掉 feishu（gen 99-103 期间 feishu 无任何 action 下发，audit_signals 有多条历史 feishu lag），该上游逻辑尚未定位，下次 publish 可能复发。"
evidence: "event_stream(scope=workspace, query=svc-b5691d4c2f6c45499aa1f1842f0abdb0)：该 feishu \"succeeded\" action 的唯一历史命中在 2026-09-24T04:35:11Z（session 0db9f81d 轮询其状态），属 gen 98 时间窗；06:18Z/06:20Z 的 gen 103 publish 窗口内 feishu 无任何 action。status 回执（evidence://v1/8d3d8217c3205f3ba8dd19470c8e14e3218f264333dc0fa969f4ad6577f3a66d）：feishu stable.generation=98，web/learning stable.generation=103。ps 回执：feishu 11101 起于 12:35:08 本地（=04:35Z，gen 98），web 76734 起于 14:17:52、learning 77672 起于 14:20:19（gen 103 窗口）。修复动作回执：service_control restart svc-4df27c343deb417b8f54cbd27cd59961 status=succeeded，detail=\"restart_mirror rc=0; identity generation=103 git_head=9bad898b...; verify=confirmed_ok feishu[ok pid=84416 head=9bad898bfc42]\"。"
tags: [service_control, status-reading, stage_facts, generation, operational]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-24T14:39:15.782583+08:00"
updated_at: "2026-09-24T14:39:15.782583+08:00"
supersedes: [EXPERIENCE-20260924-service-control-restart-failed]
---

2026-09-24 feishu 重启告警处置中发现：status 返回的 stage_facts 按服务列出 action_id+status，该 status 是"该服务最近一个 action 的终态"，不携带代际归属信息。gen 103 publish 实际只重启了 web(06:18Z)/learning(06:20Z)，feishu 的 succeeded 条目是 gen 98 的旧 action（04:35Z），据此误报"三面 gen 103 全 succeeded"。判读规程：对每个服务，用 stable.generation==desired.generation 且 stable.action_id 与 publish 代际时间窗匹配来断言"该服务已在该代落定"；stage_facts 的 succeeded 单独不可作为代际覆盖证据。核验途径：event_stream(scope=workspace, query=<action_id>) 拿 action 真实时间线；ps -eo pid,lstart 独立核对进程启动时间与代际时间窗。