---
title: task-startup-discipline-no-auto-restart-ask-user-first
scenario: 会话恢复/新会话开始或任务编排时，面对历史任务（已完成的）或未完成任务（task frontier 中的 pending/blocked 项、残留后台 job）决定是否启动；以及任何“重新跑一遍/续跑”类请求。
root_cause: ① 自动重启历史任务浪费资源且可能产生重复副作用（重复写入/通知/覆盖产物）；是否重启属于语义决策，决策权在用户，不在模型或程序。② 附带发现同类根因：模型在“意图已明确、信息已齐备”时仍可能退化为重复性预备调用（如同名 get_tool_schema 连环调用）而不推进实际动作，程序层缺少针对“同工具同参数连续 N 次”的死循环熔断。
solution: ① 已完成的过去任务一律不重新启动；② 未完成任务需要启动/恢复前，必须先向用户说明并征得明确同意后才执行；③ “重新执行历史任务”默认视为高影响动作，未经用户授权不得发起；④ 执行纪律：意图与所需信息齐备时立即发出目标动作调用，禁止退化为重复性预备调用（本会话实测 save_experience 的 schema 被重复拉取 9 次而未落盘，architecture_status 的 schema 连续重复 5 次，均属此模式）。
evidence: 本会话审计流可查：save_experience 的 get_tool_schema 重复拉取 ≥9 次（跨 3 个用户回合未完成实际落盘）；architecture_status schema 连续重复 ≥4 次；两次均无进展动作。截至本条经验落盘，该死循环缺陷仍可随时复现，属待修复架构问题（另有配套 submit_evolution 建议）。
tags: [任务管理, 后台任务, 用户确认, 会话恢复, 行为纪律, 高影响动作, 死循环防护]
source:
  context: 头条文章分析任务之后用户提出的任务启动纪律 + 同会话发生的工具调用死循环缺陷
  session: 2025 头条文章抓取/任务纪律会话
  type: user_feedback
status: archived
record_kind: experience
verification_state: legacy_unclassified
created_at: "2026-09-02T22:27:01.256499+08:00"
updated_at: "2026-09-11T19:33:32.133104+08:00"
superseded_by: "rule:RULE-AI-23"
promoted_to_rule: RULE-AI-23
last_verified_at: "2026-09-11T19:33:32.133104+08:00"
---

用户原话（本会话）：“就是过去的任务，已经做过的，不应该起，就算有没有完成的任务需要起也要问了用户才起。”

执行纪律（模型层）：
1. 见到“继续/上次/之前那个”类指令时，先判断指向的是未完成的新任务还是已完成的历史任务；已完成的一律不动。
2. 任何重启/续跑动作前，先向用户一句话确认：“检测到未完成任务 X，是否继续？”，获批后才执行。
3. 严禁出现“说明要做→反复查询 schema→始终不发真正动作调用”的空转序列；拿到的 schema 当轮就用。

程序层建议（配套，待架构演进审阅）：
- 同工具+同参数连续 ≥3 次 → 熔断注入警告，阻断继续原调用；
- 任务重启前置守卫：task 状态 done → 拒绝并告知用户；非 done → 要求用户确认后放行。