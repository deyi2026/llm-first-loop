---
title: 47773fff5 独立补审 PASS：generation 隔离修复经独立子代理三维核验（347 项测试全绿）
scenario: RULE-AI-28 三闸补审：commit 47773fff5（子代理 effect generation 隔离修复）在修复当日被跳过代码闸与 push 闸，需事后独立补审裁决。同类：补审的深度标准（静态链路核验+测试子集是否足够替代全量）。
root_cause: ""
solution: spawn 独立子代理（inherit=false，白名单 execute_command/read_file/search_files，禁写）审查：①静态坐实根因链（子会话从不注册 run 代际→run_generation_authority 必 False→binding 带父代必拒）；②核验修复窗口（registry.execute 外围置空 current_run_generation，finally 恢复）不影响 fleet lease fence（代际检查之前独立探测 lease，fail-closed 保留）；③回归面核验（窗口外 spawn 归属/pending_obligations/cancel_parent/WAL 均不受影响）；④测试以关键词子集（347 项）替代全量 7508 全绿，red-before-fix 以静态机制推演替代动态复现（守禁写令）。结论 PASS，三条非阻断观察：非 fleet 部署 journal 层权威缺口（原状）、拒绝文案不区分 lease/generation 来源（已被 EVO-20261014-459a8a1e 覆盖）、WAL 与 binding 的 origin_run_generation 取值不一致（纯可观测性）。
evidence: "subagent_result(subagent_f8ae8d75f00d) 完整回执：VERDICT: PASS；测试输出（2+125+154+66 passed, 0 failed）；git merge-base --is-ancestor=YES；链路核验行号引用（lifecycle.py:241、session.py:1242-1245、runner.py:2315-2328、journal.py:425-461）"
tags: []
source: {}
status: active
record_kind: experience
verification_state: verified
created_at: "2026-10-14T18:03:30.675430+08:00"
updated_at: "2026-10-14T18:03:30.675430+08:00"
supersedes: [EXPERIENCE-20261014-故障修复语境挤掉审查闸-rule-ai-28-三闸在-fenced-紧急修复链路中被跳过-加载-执行]
---