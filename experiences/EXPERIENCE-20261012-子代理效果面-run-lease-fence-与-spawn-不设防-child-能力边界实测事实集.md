---
title: 子代理效果面 run-lease fence 与 spawn 不设防：child 能力边界实测事实集
scenario: 多子代理编排设计（房间/团队/POC）中，需要判断 child 能做什么、威胁模型怎么定、等待型任务怎么编排时。
root_cause: ""
solution: 按此事实集设定 child 能力面与审计清单：效果类（execute_command/文件写）视为被结构性拒绝但不得单独依赖（父 run 边界外行为未测）；spawn 类视为不设防，必须进任务书禁令+结算轨迹 diff 审计；需要墙钟等待或定时的心跳设计不可行，等待用 spawn-per-turn 替代；孙代残留用 subagent_topology 核查。
evidence: "evidence://v1/1ff89373bdd9cb38f5f061985569847329a5de003a70d3cbd1771248afded47e (spawn receipt); evidence://v1/fe31894ad5580e5b4f1251e5f10ea1f403966169018f05a9ed66560ef3b (subagent_lease); evidence://v1/b4a2c5ac699d518c8fda622543bb4dad1a021db40d9d3ed34af7132b0bfc7c32 (lease-test 结算回执 13/13 fenced); evidence://v1/4e57ecf3a1a8c0cd94dd074cbea87f4456a2c5ff27623adce051b7aa5961a904 (probe 结算回执 spawn 成功); evidence://v1/1edc55eb7e34e298d50498a64fba2ce0a25038c61fb2cb75216191bfbaa3b23e (topology)"
tags: [subagent, run-lease-fence, effect-authority, spawn-not-fenced, NFR-6, room-protocol, waiting-cost]
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-12T00:14:25.078030+08:00"
updated_at: "2026-10-12T00:14:25.078030+08:00"
---

2026-10-12 租约长测中实测发现（三个 child、14+6 轮工具调用、全部带回执）：
1. 子代理效果面 fence：execute_command 在 child 内 14/14 被拒，错误原文「effect authority 丢失（run lease fenced），命令拒绝执行」。父 run 活跃期间 child 没有效果类执行权。机制出处 DESIGN-20261001-model-invocation-history-replay-safety.md（fence 执行时现算）。
2. fence 不覆盖 agent 类工具：child 内 spawn_subagent 成功，grandchild 实际启动（depth=1）。递归舰队风险是实测事实，不是假设；多 bot 设计的安全审计必须把 spawn/agent_*/workflow 类调用列为禁令清单与结算轨迹 diff 项。
3. 孙代隔离：祖父级对 grandchild 无 handle 读权（「仅直接 parent 可以读取该 child handle」）；subagent_topology(parent_id) 可看 active_children=none 级别的残留核查。
4. send_feishu_message 有 confirm 二次确认门；child 自传 confirm=true 是否被 outbound 白名单拦截——未测（开放项）。
5. child 无墙钟等待原语（sleep 属效果面被拒）：心跳只能自然轮转 ≈10–15s/轮 ≈15–18K in/轮，等待成本 ≈64–96K in/min/bot。需要等待的编排应改用 spawn-per-turn（每回合新 spawn，结算即结束），而不是长驻等待。
适用边界：父 run 活跃期间；父 run 结束后 fence 行为未测。测 fence 广度时不要用 escalation_request/send_feishu(confirm=true) 当探针（可能真实出站）。