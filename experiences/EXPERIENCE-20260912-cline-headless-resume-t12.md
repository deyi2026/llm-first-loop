---
title: cline headless 续接会新建工作区：进程外 resume 语义导致 t12 假失败
scenario: "对 headless coding agent 做\"强杀 25s 后续接同一任务\"的评测（t12_interrupt_resume）"
root_cause: headless CLI 的会话续接不携带工作区亲和性：进程被杀后重新调用时，agent 在新上下文中把绝对路径当作新任务工作目录重新创建
solution: 本 pilot 将 cline t12 0/3 明确归类为 harness 边界而非模型能力（模型在新 ws 完成了全部阶段，内容正确）；报告单独说明
evidence: /tmp/agentpilot/t12_interrupt_resume__cline__r1__0ec65d*/ 仅 mark.py+_phase1.log；…__bdbaed*/ 有 marks.json+stage1-3.txt；results.jsonl cline t12 三 run FileNotFoundError；REPORT.md §3.1
tags: [cline, headless, resume, eval-pitfall, workspace-affinity]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-12T15:06:23.684659+08:00"
updated_at: "2026-09-12T15:06:23.684659+08:00"
---

cline --task --exit 的每次调用都是新会话：--id conv_* 续接后仍在运行时新建工作区目录执行写入（r1 证据：phase-1 ws 0ec65d 只有 mark.py，resume 后新 ws bdbaed 里有完整 marks.json==[p1,p2,p3]），验收脚本在原 ws 找不到产物 → 判失败。即：模型完成了任务，但 harness 无法保证"同 cwd 再入"。对评测设计的影响：涉及中断-续接的任务项要区分"模型能力"与"harness 续接语义"，否则会把 adapter 限制误记为模型失败。修复方向（未做）：resume 调用显式传 cwd=原 ws 并校验 cline 实际落盘目录。