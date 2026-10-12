---
title: 下次服务重启前先用 grill_me 拷问重启闭环方案（用户指令，待验证）
scenario: "用户于 2026-09-19 19:32 指示：下次执行服务重启（publish + 工具层 service_control restart）时，先用 grill_me 工具对重启方案做追问式拷问，检验闭环是否用得到、是否完备，再动手执行。当前尚无下一次重启实例，未验证。"
root_cause: ""
solution: "触发条件：用户要求重启服务。流程：1) status 读当前 generation/git_head，起草完整重启方案（publish --expected-generation N → 工具层 service_control restart(expected_generation=N+1, 新 action_id) → 事后 status 验证 pid_alive/git_head/restart_required=false/action_id 匹配）；2) 方案全文交 grill_me 拷问（focus：CAS 条件与并发、重启部分失败的处置、事后验证盲点）；3) 按暴露缺口修正后再执行；4) 重启完成后对照拷问结论与实际回执，记录拷问点命中率，回填验证状态并升级为 experience 或保持 lesson。"
evidence: ""
tags: [service-restart, grill-me, closed-loop, user-directive]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-09-19T19:32:33.904839+08:00"
updated_at: "2026-09-19T19:32:33.904839+08:00"
supersedes: [EXPERIENCE-20260816-llm-first-loop-guard]
---

下次执行 web/feishu/learning 服务重启时，先用 grill_me 对重启闭环方案做追问式拷问再执行。待验证点：拷问是否真能提前暴露闭环缺口（如 CAS 并发、部分失败处置、验证盲点），还是只增加流程开销。